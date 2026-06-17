# Wiki 引擎重构 — 架构设计文档

> **状态**：设计阶段
> **作者**：基于 LLM Wiki 项目（`https://github.com/nashsu/llm_wiki`）方法论改造
> **目标读者**：Claude Code（设计 + 实施）
> **关联实施计划**：`docs/superpowers/plans/2026-06-16-wiki-engine-refactor.md`
> **前置文档**：`docs/superpowers/specs/2026-06-16-wiki-knowledge-extraction-design.md`（当前三阶段管线设计）

---

## 0. TL;DR

把 Prism 现有的「概念抽取 → group 合并 → 文章生成」三阶段管线重构成 LLM Wiki 风格的「Analysis → Generation」两步 CoT 管线，同时引入：

1. **Wikilink + 4 信号关系图** — LLM 在正文中写 `[[wikilink]]`，代码解析为加权图
2. **跨文档知识连接** — 通过 source overlap、Adamic-Adar 等信号自动发现关系
3. **治理体系** — Lint / Dedup / Sweep / Cascade 自动维护 wiki 健康度
4. **KP 级 RAG 检索** — 与现有 chunk 级检索并行，提升概念性问题的回答质量
5. **图视图 + 治理 UI** — 前端可视化知识网络与治理操作

**改造原则**：
- 保留 Prism DB 真相源架构（不复刻 LLM Wiki 的文件系统模式）
- 保留现有 6 张 wiki 表，仅扩字段；新增 3 张治理表
- Feature flag 切换新旧管线，可回滚
- 现有 chunk 检索保留，KP 检索作为新通道并行

---

## 1. 改造背景

### 1.1 现状评估

Prism 现有 wiki 管线（`engine/app/wiki/extraction_engine.py`）的核心问题：

| 问题 | 根因 | 影响 |
|---|---|---|
| 跨 chunk 同名概念碎裂 | 每个 chunk 独立调用 `_extract_from_chunk`，互不可见 | 同一实体被拆成多个 KP |
| 跨 chunk 关系丢失 | `alias_map` 只覆盖当前文档，跨 chunk 关系 from/to 对不上 | LLM 输出的关系大量被静默丢弃 |
| 跨文档知识断裂 | 关系仅存于单文档内 | 无法发现跨文档的概念关联 |
| LLM 调用过重 | Stage 2 (N chunk) + Stage 3.5a (N KP) + Stage 3.5b (N KP) | 一个 10 chunk + 8 KP 的文档要 26 次 LLM 调用 |
| 关系强度单一 | 只有 LLM 给的 confidence 一个数 | 无法做图扩展、社区检测 |
| 无治理机制 | 一次性写入，永不维护 | 重复 KP、悬空 wikilink、过时 review 长期累积 |
| 检索粒度单一 | 只有 chunk 级 RAG | 概念性问题只能从原始 chunk 拼凑 |

### 1.2 LLM Wiki 方法论核心

参考 LLM Wiki 项目（`H:\Agent\Project\llm_wiki`）的四个关键设计：

1. **关系是写出来的，不是算出来的** — LLM 在生成正文时主动写 `[[wikilink]]`，代码只解析不抽取
2. **两步 CoT** — 分析与生成分离，质量优于单步（见 `src/lib/ingest.ts` 的 `buildAnalysisPrompt` 与 `buildGenerationPrompt`，§8.1 列出函数级位置）
3. **4 信号关系权重** — direct link × 3.0 / source overlap × 4.0 / Adamic-Adar × 1.5 / type affinity × 1.0（见 `src/lib/graph-relevance.ts` 的 `WEIGHTS` 与 `TYPE_AFFINITY` 常量）
4. **markdown 真相源** — 派生数据（图、向量、社区）随时可重建

本次改造**采纳前三条**，第四条因 Prism 是 DB 真相源架构，改为「DB 真相源 + 派生缓存」等价机制。

---

## 2. 改造目标

### 2.1 必达目标（前 3 阶段）

- ✅ 替换三阶段管线为两步 CoT，feature flag 切换
- ✅ 引入 wikilink 解析与 4 信号关系权重
- ✅ KP 级混合检索接入 RAG agent
- ✅ 现有 KP 数据无损迁移到新模型字段
- ✅ DeepSeek 在新 prompt 下输出格式稳定（≥ 95% 成功率）

### 2.2 选做目标（后续阶段）

- ⭕ Lint / Dedup / Sweep 治理三件套
- ⭕ 前端图视图 + 治理面板
- ⭕ Louvain 社区检测 + Graph Insights
- ⭕ Purpose 字段与 schema 自由度扩展

### 2.3 非目标

- ❌ 不引入文件系统真相源（保持 DB-only）
- ❌ 不做 Obsidian 兼容
- ❌ 不替换 chunk 级 RAG（并行新增 KP 通道）
- ❌ 不改变上传入口与 `knowledge_file` 表

---

## 3. 总体技术架构

### 3.1 端到端数据流

```
┌──────────────────────────────────────────────────────────────┐
│  Frontend (:5173)                                                │
│  - WikiPage / WikiUploadPage / WikiDocDetail / WikiPointDetail   │
│  - 新增：WikiGraphView / WikiLintPanel / WikiReviewPanel         │
└────────────────┬─────────────────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────────────────┐
│  Backend (:5175)                                                 │
│  - 现有：wiki CRUD + extract 触发                                │
│  - 新增：graph / insights / lint / dedup / review API            │
└────────────────┬─────────────────────────────────────────────┘
                 │ POST /api/v1/wiki/extract (内部 HTTP)
                 ▼
┌──────────────────────────────────────────────────────────────┐
│  Engine (:5180) Wiki Module                                      │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Pipeline V2 (feature flag: WIKI_PIPELINE_V2)          │  │
│  │                                                          │  │
│  │  Stage 0:    文件解析（复用 file_parser）                │  │
│  │  Stage 0.5:  SHA256 增量缓存检查                         │  │
│  │  Stage 1:    Analysis (LLM #1) → 结构化分析              │  │
│  │  Stage 2:    Generation (LLM #2) → FILE/REVIEW blocks    │  │
│  │  Stage 2.5:  Aggregate Repair (可选)                     │  │
│  │  Stage 3:    Parse + Persist                             │  │
│  │              - parse_file_blocks → KP 草稿                │  │
│  │              - parse_review_blocks → review 草稿          │  │
│  │              - 提取 [[wikilink]] → relations              │  │
│  │              - 写入 KP / Relation / Review                │  │
│  │  Stage 4:    异步图重算（增量）                          │  │
│  │  Stage 5:    KP 向量化（Milvus + ES）                    │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Graph Engine                                            │  │
│  │  - builder: 从 DB 构建 NetworkX 图                       │  │
│  │  - relevance: 4 信号权重计算                             │  │
│  │  - community: Louvain（阶段 5）                          │  │
│  │  - insights: surprising / gaps（阶段 5）                 │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Retrieval Layer                                         │  │
│  │  - 现有：chunk hybrid (vector + BM25)                    │  │
│  │  - 新增：kp hybrid (Milvus collection + ES index)        │  │
│  │  - 新增：graph_expand (4 信号 N-hop 扩展)                │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Governance (阶段 4-5)                                   │  │
│  │  - lint: structural + semantic                           │  │
│  │  - dedup: LLM 软碰撞检测 + 用户确认合并                  │  │
│  │  - sweep: review 自动消解                                │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────────────────┐
│  Data Layer                                                      │
│  - MySQL: wiki_*（扩字段 + 3 张新表）                            │
│  - Milvus: prism_knowledge (现有 chunk) + prism_wiki_kp (新增)   │
│  - ES: chunks (现有) + wiki_kp (新增)                            │
│  - Redis: 图缓存（按 user_id 分片）                              │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 核心方法论对照

| 维度 | LLM Wiki 原版 | Prism 改造版 |
|---|---|---|
| 真相源 | `wiki/*.md` 文件 | MySQL `wiki_knowledge_point.content` |
| Wiki 页面身份 | 文件 slug (kebab-case basename) | DB `slug` 字段（kebab-case） |
| Frontmatter | YAML in markdown | DB 字段：`page_type / related_slugs / source_doc_ids / tags` |
| Wikilink 写入 | LLM 在 `wiki/*.md` 正文写 | LLM 在 `wiki_knowledge_point.content` 正文写 |
| Wikilink 解析 | `parseWikilinks(content)` | 同名 Python 函数解析 markdown |
| 4 信号 source 共享 | 共享原 source 文件名 | 共享 `wiki_document.id` |
| 队列持久化 | `.llm-wiki/ingest-queue.json` | MySQL `wiki_document.status`（已有） |
| 图缓存 | 进程内 + dataVersion 失效 | Redis + `content_hash` 失效 |
| 多租户 | 多 project 目录 | `user_id` + `topic_id` |

### 3.3 与现有代码的兼容性边界

**不动的地方**：
- `knowledge_file` / `knowledge_item` / `knowledge_chunk` 现有模型
- `engine/app/ingestion/pipeline.py`（chunk 级 ingest）
- `engine/app/agent/runner.py` 主流程
- `engine/app/retrieval/{vector_search,bm25_search,hybrid}.py`（chunk 检索）
- 前端现有 4 个 wiki 页面（仅增不改）

**改动的地方**：
- `backend/app/models/wiki.py` 扩字段（不破坏现有数据）
- `backend/app/api/wiki.py` 加新 endpoint
- `engine/app/wiki/*` 新增 pipeline_v2 + 治理模块
- `engine/app/agent/tools/` 新增 `wiki_search` 工具
- `frontend/src/pages/Wiki*.tsx` 增加图/治理交互

**与 inbox 模块的边界**：

Prism 仓库中存在并行开发的 inbox 模块（`backend/app/api/inbox.py`、`docs/superpowers/specs/2026-06-17-inbox-review-settlement-design.md`），该模块也有"待处理项"/"settle"概念。

本次改造新增的 `wiki_review_item` 表与 inbox 是**独立的两套机制**，边界如下：

| 维度 | `wiki_review_item` | inbox |
|------|-------------------|-------|
| 来源 | ingest LLM 自动生成的 `---REVIEW---` 块 | 用户手动触发 / 外部输入 |
| 类型 | contradiction / duplicate / missing-page / suggestion | inbox 自身定义 |
| 消解 | sweep 自动判断 + 用户手动操作 | inbox 自身 settle 流程 |
| 存储 | `wiki_review_item` 表 | inbox 专用表 |

**如未来要统一**：可把 `wiki_review_item` 视为 inbox 的一种 `source_type="wiki_ingest"` 子集，将 wiki review 路由到 inbox 的 settle 界面。这不在本次改造范围，留作后续迭代。

**实施注意**：阶段 1-5 期间，不要把 `wiki_review_item` 的 CRUD 和 inbox 路由共用，保持独立。

---

## 4. 数据模型改造

### 4.1 扩展现有表（最小侵入）

#### 4.1.1 `wiki_knowledge_point` 新增字段

```python
# backend/app/models/wiki.py — 在现有 WikiKnowledgePoint 类追加字段

class WikiKnowledgePoint(Base):
    # ... 现有字段全部保留 ...

    # ▼ 新增：LLM Wiki 风格 frontmatter 字段
    slug = Column(String(255), index=True, comment="kebab-case 唯一标识；同 user 内唯一")
    page_type = Column(String(32), default="concept", index=True,
                       comment="entity/concept/synthesis/comparison/finding/thesis/methodology")
    related_slugs = Column(JSON, default=list,
                          comment="frontmatter related: 裸 slug 列表（不含 [[]] 不含 .md）")
    source_doc_ids = Column(JSON, default=list,
                           comment="贡献此 KP 的 wiki_document.id 列表（多源合并时累加）")

    # ▼ 新增：图谱缓存字段（每次重算图时更新）
    in_link_count = Column(Integer, default=0, comment="入链数")
    out_link_count = Column(Integer, default=0, comment="出链数")
    community_id = Column(Integer, nullable=True, index=True, comment="Louvain 社区 ID")

    # ▼ 新增：增量缓存
    content_hash = Column(String(64), index=True, comment="SHA256 of content，KP 内容变更检测")
    last_extracted_at = Column(DateTime, comment="最后一次被 ingest 触及的时间")

    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uq_wiki_kp_user_slug"),
    )
```

**Migration 策略**：
- 新字段全部允许 NULL/默认值，旧数据零侵入
- `slug` 字段在 migration 时通过 `make_slug(title)` 批量回填
- `page_type` 从现有 `wiki_concept.type` 映射：
  - `concept` / `technique` → `concept`
  - `claim` → `finding`
  - `artifact` → `entity`
  - `source` → 不再作为 KP（迁移时跳过，已是 doc 自身）
- `source_doc_ids` 从 `document_id` 字段初始化为单元素列表 `[document_id]`

#### 4.1.2 `wiki_knowledge_relation` 新增字段

```python
class WikiKnowledgeRelation(Base):
    # ... 现有字段全部保留 ...

    # ▼ 新增：关系来源标识
    origin = Column(String(16), default="llm", index=True,
                    comment="llm | wikilink | inferred | manual")

    # ▼ 新增：4 信号权重（每次重算图时更新）
    weight_total = Column(Float, default=0.0, comment="综合权重 = sum(各信号 × 系数)")
    weight_direct = Column(Float, default=0.0, comment="direct link 信号 × 3.0")
    weight_source = Column(Float, default=0.0, comment="source overlap 信号 × 4.0")
    weight_neighbor = Column(Float, default=0.0, comment="Adamic-Adar × 1.5")
    weight_type = Column(Float, default=0.0, comment="type affinity × 1.0")
    last_computed_at = Column(DateTime, comment="权重最后计算时间")

    __table_args__ = (
        UniqueConstraint("from_point_id", "to_point_id", "type", "origin",
                        name="uq_wiki_rel_from_to_type_origin"),
    )
```

**Migration 策略**：
- 现有 relation 全部标记 `origin="llm"`
- `weight_*` 全部初始化为 0，等首次图重算填充

#### 4.1.3 `knowledge_topic` 新增字段（可选，阶段 5）

```python
class KnowledgeTopic(Base):
    # ... 现有字段保留 ...
    purpose = Column(Text, comment="该 topic 的用途说明，作为 ingest prompt 的 context")
    schema_definition = Column(Text, comment="自定义 page_type 与目录约定")
```

### 4.2 新建治理表

#### 4.2.1 `wiki_review_item`

```python
class WikiReviewItem(Base):
    """Review 队列：来自 ingest LLM 输出的 ---REVIEW--- 块"""
    __tablename__ = "wiki_review_item"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    document_id = Column(CHAR(36), ForeignKey("wiki_document.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(32), index=True,
                  comment="contradiction | duplicate | missing-page | suggestion")
    title = Column(String(512))
    description = Column(Text)
    affected_point_ids = Column(JSON, default=list, comment="相关 KP id 列表")
    search_queries = Column(JSON, default=list, comment="LLM 预生成的搜索 query (用于 deep research)")
    options = Column(JSON, default=list, comment='["Create Page", "Skip"]')
    status = Column(String(16), default="pending", index=True,
                    comment="pending | resolved | skipped | dismissed")
    resolution_note = Column(Text)
    user_id = Column(CHAR(36), default="default-user", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime)
```

#### 4.2.2 `wiki_lint_finding`

```python
class WikiLintFinding(Base):
    """Lint 发现：orphan / broken-link / no-outlinks / contradiction / stale"""
    __tablename__ = "wiki_lint_finding"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    type = Column(String(32), index=True,
                  comment="orphan | broken-link | no-outlinks | contradiction | stale | missing-page")
    severity = Column(String(16), comment="warning | info")
    point_id = Column(CHAR(36), ForeignKey("wiki_knowledge_point.id", ondelete="CASCADE"), nullable=True)
    detail = Column(Text)
    broken_target = Column(String(512), comment="broken-link 时填，wikilink 目标 slug")
    suggested_target_slug = Column(String(255), comment="模糊匹配建议")
    affected_point_ids = Column(JSON, default=list, comment="语义 lint 涉及多个 KP 时填")
    status = Column(String(16), default="open", index=True,
                    comment="open | fixed | ignored | stale")
    user_id = Column(CHAR(36), default="default-user", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime)
```

#### 4.2.3 `wiki_dedup_candidate`

```python
class WikiDedupCandidate(Base):
    """Dedup 候选组：等待用户确认 canonical"""
    __tablename__ = "wiki_dedup_candidate"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    point_ids = Column(JSON, comment="同一组的 KP id 列表（≥2）")
    canonical_id = Column(CHAR(36), nullable=True, comment="用户选定后填")
    reason = Column(Text, comment="LLM 给出的判重理由")
    confidence = Column(String(16), comment="high | medium | low")
    status = Column(String(16), default="pending", index=True,
                    comment="pending | merged | dismissed")
    user_id = Column(CHAR(36), default="default-user", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    merged_at = Column(DateTime)
```

### 4.3 索引建议

```sql
-- 高频查询索引
CREATE INDEX idx_wiki_kp_user_type ON wiki_knowledge_point(user_id, page_type);
CREATE INDEX idx_wiki_kp_content_hash ON wiki_knowledge_point(content_hash);
CREATE INDEX idx_wiki_rel_origin_weight ON wiki_knowledge_relation(origin, weight_total DESC);
CREATE INDEX idx_wiki_review_user_status ON wiki_review_item(user_id, status);
CREATE INDEX idx_wiki_lint_user_status ON wiki_lint_finding(user_id, status, type);
```


---

## 5. 管线改造详细设计

### 5.1 目标管线（Pipeline V2）

替换现有 `engine/app/wiki/extraction_engine.py` 的三阶段管线，改为两步 CoT。新管线放在 `engine/app/wiki/pipeline_v2.py`，通过 feature flag 与旧管线共存。

#### 5.1.1 阶段总览

```
Stage 0:    文件解析（复用 backend/app/utils/file_parser.py）
            - PDF/DOCX/XLSX/PPTX/MD/TXT → text
            - 失败则 fallback 旧管线

Stage 0.5:  增量缓存检查
            - SHA256(file_text) → 查 wiki_document.content_hash
            - 命中：跳过整个管线，直接 status=completed

Stage 1:    Analysis (LLM #1)
            - 输入：file_text + 同 user 现有 KP index
            - 输出：Markdown 结构化分析
              · Key Entities / Key Concepts / Key Findings
              · Connections to Existing Wiki
              · Contradictions / Recommendations
            - 长文：滚动摘要 + 多 chunk 分析合成

Stage 2:    Generation (LLM #2)
            - 输入：Stage 1 分析 + file_text + index
            - 输出：FILE blocks + REVIEW blocks
              ---FILE: kp/<slug>---
              <yaml frontmatter>
              <markdown body 含 [[wikilink]]>
              ---END FILE---
              ---REVIEW: type | title---
              <description>
              OPTIONS: Create Page | Skip
              SEARCH: q1 | q2 | q3
              ---END REVIEW---

Stage 2.5:  Aggregate Repair（可选）
            - 检测 generation 是否漏写或破坏 frontmatter
            - 单独重生成有问题的 FILE 块

Stage 3:    Parse + Persist
            - parse_file_blocks → KP 草稿列表
            - parse_review_blocks → review 草稿列表
            - 路径安全校验（is_safe_kp_slug）
            - 语言守卫（content_matches_target_language）
            - 写入 wiki_knowledge_point（按 slug upsert）
            - 解析正文 [[wikilink]] → 写入 relations
            - 解析 frontmatter related → 写入 relations
            - LLM 显式 relations → 写入 relations
            - 写入 wiki_review_item
            - 更新 wiki_document.content_hash

Stage 4:    异步图重算（不阻塞主流程）
            - 增量：只重算受影响 KP + 一跳邻居的边权重
            - 全量：阶段 5 引入 Louvain 时按需触发

Stage 5:    KP 向量化 + ES 索引
            - 新建 KP：embed → Milvus prism_wiki_kp
            - ES 写入 wiki_kp index（title/description/content）
            - content_hash 未变的 KP 跳过
```

#### 5.1.2 模块文件结构

```
engine/app/wiki/
├── __init__.py
├── extraction_engine.py        # ← 旧三阶段管线，保留作 fallback
├── pipeline_v2.py              # ← 新两步 CoT 主流程（本次改造重点）
├── prompts.py                  # ← 现有：扩展 build_analysis_prompt + build_generation_prompt
├── parsers.py                  # ← 新增：parse_file_blocks / parse_review_blocks
├── slug.py                     # ← 新增：title → kebab-case slug + 唯一性保证
├── chunker.py                  # ← 抽自 extraction_engine 的 _chunk_text
├── language.py                 # ← 新增：language guard
├── persist.py                  # ← 新增：写入 KP / Relation / Review
├── merge.py                    # ← 新增：LLM 合并多源 KP 正文（对译 LLM Wiki page-merge.ts）
├── wikilink.py                 # ← 新增：extract / resolve / rewrite
├── cache.py                    # ← 新增：SHA256 增量缓存
├── feature_flags.py            # ← 新增：WIKI_PIPELINE_V2 切换
├── graph/
│   ├── __init__.py
│   ├── builder.py              # ← 新增：从 DB 构建 NetworkX 图
│   ├── relevance.py            # ← 新增：4 信号权重
│   ├── community.py            # ← 阶段 5：Louvain
│   └── insights.py             # ← 阶段 5：surprising / gaps
├── retrieval/
│   ├── __init__.py
│   ├── kp_search.py            # ← 新增：KP 级 hybrid 检索
│   └── graph_expand.py         # ← 新增：图扩展
└── governance/
    ├── __init__.py
    ├── lint.py                 # ← 阶段 4：structural + semantic
    ├── dedup.py                # ← 阶段 4：LLM 软碰撞检测
    └── sweep.py                # ← 阶段 4：review 自动消解
```


### 5.2 Prompt 设计（DeepSeek 适配）

#### 5.2.1 直译策略与 DeepSeek 调试章节

**默认策略**：直接对译 LLM Wiki 的 prompt（中文化），保持强约束格式不变。LLM Wiki 的 `buildGenerationPrompt`（`src/lib/ingest.ts`，函数级定位见 §8.1）是项目核心，强制 LLM 输出严格 `---FILE:` 块格式，已在 GPT/Claude/MiniMax 上验证有效。

**DeepSeek 风险点**：
1. DeepSeek-V3 偶尔会在响应开头加"以下是生成的文件:"等前言（违反"第一字符必须是 `-`"约束）
2. DeepSeek-Reasoner 会输出 `<think>` 块，需在 prompt 中明确禁止
3. 中文长文档 generation 阶段偶尔会用 `​` (U+200B) 等不可见字符填充，破坏 frontmatter 解析
4. `temperature=0.1` + `top_p=0.95` 是 LLM Wiki 的默认值，DeepSeek 上建议降到 `temperature=0.0`

**调试章节**：`docs/superpowers/specs/2026-06-16-wiki-engine-deepseek-tuning.md` 单独写（阶段 1 完成后产出）。

#### 5.2.2 Analysis Prompt（Stage 1）

完全对译 `src/lib/ingest.ts` 的 `buildAnalysisPrompt` 函数，中文化：

```python
# engine/app/wiki/prompts.py

ANALYSIS_SYSTEM_PROMPT = """你是一名专业的研究分析师。阅读源文档后产出结构化分析。

严格规则：
- 不要输出 <think>、思考过程、隐藏推理
- 不要用 ```markdown 代码块包装响应
- 直接输出最终分析正文，从 ## 开始

输出语言：中文（保留专有名词、模型名、技术术语原文）
"""


def build_analysis_prompt(ctx: "IngestContext") -> str:
    """构建 Stage 1 用户消息。"""
    purpose_section = ""
    if ctx.purpose:
        purpose_section = f"\n## 知识库用途说明\n{ctx.purpose}\n"

    index_section = ""
    if ctx.existing_kp_index:
        index_section = f"\n## 当前 wiki 索引（用于检查现有内容）\n{format_kp_index(ctx.existing_kp_index)}\n"

    folder_section = ""
    if ctx.folder_context:
        folder_section = f"\n## 文件夹上下文\n{ctx.folder_context}\n"

    return f"""请对下面的源文档产出结构化分析。{purpose_section}{index_section}{folder_section}

请按以下小节产出分析（用中文，每个小节都要有内容；如确实无相关信息，写"（无）"）：

## 关键实体
列出文档中提到的人物、组织、产品、数据集、工具。每个实体说明：
- 名称和类型
- 在文档中的角色（中心 / 周边）
- 是否可能已在 wiki 中存在（参考上方 wiki 索引）

## 关键概念
列出文档中的理论、方法、技术、现象。每个概念说明：
- 名称和简要定义
- 为什么在本文档中重要
- 是否可能已在 wiki 中存在

## 主要论点与发现
- 核心主张或结论是什么？
- 有哪些证据支撑？
- 证据强度如何？

## 与现有 wiki 的连接
- 这份文档与哪些已有 KP 相关？
- 是强化、挑战还是扩展现有知识？

## 矛盾与张力
- 是否与已有 wiki 内容冲突？
- 文档内部是否有自相矛盾？

## 建议
- 应创建或更新哪些 KP？
- 应突出 / 弱化什么？
- 有哪些值得标注给用户的开放问题？

要全面但简洁。聚焦真正重要的内容。

---

## 源文档
源文件名：{ctx.source_filename}
{ctx.source_text}
"""
```

#### 5.2.3 Generation Prompt（Stage 2）

直译 `src/lib/ingest.ts` 的 `buildGenerationPrompt` 核心约束：

```python
GENERATION_SYSTEM_PROMPT = """你是一名 wiki 维护者。基于提供的 Stage 1 分析生成 wiki 文件。

严格规则：
- 不要输出 <think>、思考过程、解释性前言（如"以下是生成的文件"）
- 整个响应只能由 ---FILE: 块和 ---REVIEW: 块构成
- 响应的第一个字符必须是 `-`（即 `---FILE:` 的开头）
- 第一个字符不是 `-`，整段响应将被丢弃

输出语言：FILE 正文用中文，但保留专有名词、模型名、技术术语原文
"""


def build_generation_prompt(ctx: "IngestContext", analysis: str) -> str:
    today = ctx.today.strftime("%Y-%m-%d")
    source_id = ctx.source_filename

    schema_section = ""
    if ctx.schema_definition:
        schema_section = f"""
## 项目 Schema 与路由（权威约定）
{ctx.schema_definition}

请优先使用 schema 定义的 page_type；如未定义则使用 `concept` 或 `entity`。
"""

    return f"""{schema_section}

## 重要：源文件
本次源文件：**{source_id}**
本次 wiki_document.id：**{ctx.doc.id}**
今天日期：**{today}**

所有从此源文件生成的 KP frontmatter 的 `sources` 字段必须包含 `{source_id}`。
所有新建 KP 的 `created` / `updated` 用 `{today}`。

## 要生成什么

1. 关键实体的 KP 文件（如分析建议）
2. 关键概念的 KP 文件
3. 必要时生成 finding / synthesis / comparison 类型的 KP

不要为源文件本身生成 KP（doc 已存在于 wiki_document）。

## Frontmatter 规则（解析器严格校验）

每个 KP 文件以 YAML frontmatter 开头：

1. 文件第一行必须严格是 `---`（三个连字符，无其他字符）
2. 不要用 ```yaml 包装
3. 数组用标准内联形式 `[a, b, c]`
4. wikilink 只能在正文中，不能写在 `related` 字段（无效 YAML）
5. `related` 字段写裸 slug：`related: [foo, bar-baz]`

必需字段：
- `slug`     — kebab-case 唯一标识（不超过 80 字符，保留 CJK 字符）
- `type`     — entity | concept | synthesis | comparison | finding | thesis | methodology
- `title`    — 字符串（含冒号需用引号包裹）
- `created`  — {today}
- `updated`  — {today}
- `tags`     — 字符串数组
- `related`  — 裸 slug 数组（不带 [[]] 不带 .md）
- `sources`  — 必须包含 "{source_id}"

正文规则：
- 用 [[other-slug]] 在正文中交叉引用其他 KP
- 用 [[slug|显示文本]] 添加别名
- 文件名使用 kebab-case

## REVIEW 块类型

所有 FILE 块之后，可选输出 REVIEW 块，标记需要人工判断的内容：

- contradiction: 与现有 wiki 冲突
- duplicate: 可能与已有 KP 重复
- missing-page: 重要概念被引用但没有专门 KP
- suggestion: 进一步研究方向

OPTIONS 严格枚举：`OPTIONS: Create Page | Skip`（仅这两个，不要发明新选项）

对于 suggestion 和 missing-page，SEARCH 字段必须给出 2-3 条搜索引擎友好的 query：
`SEARCH: query 1 | query 2 | query 3`

## Stage 1 分析（仅作上下文，不要复述）

{analysis}

## 当前 wiki 索引

{format_kp_index(ctx.existing_kp_index)}

## 输出格式（必须严格遵守）

整个响应只能由 FILE 块和 REVIEW 块构成。没有任何前言、解释、markdown 表格或 prose。

FILE 块模板：
```
---FILE: kp/<slug>.md---
---
slug: <slug>
type: <type>
title: <title>
created: {today}
updated: {today}
tags: [...]
related: [...]
sources: ["{source_id}"]
---

# <title>

<markdown 正文，使用 [[other-slug]] 交叉引用>
---END FILE---
```

REVIEW 块模板：
```
---REVIEW: <type> | <title>---
<描述>
OPTIONS: Create Page | Skip
PAGES: <slug1>, <slug2>
SEARCH: <query 1> | <query 2>
---END REVIEW---
```

## 输出要求（违反将导致整段被丢弃）

1. 响应的第一个字符必须是 `-`（即 `---FILE:` 的第一个字符）
2. 不要输出任何前言（如"以下是文件"）
3. 不要复述分析
4. 不要在 FILE/REVIEW 块外输出任何 markdown
5. 在最后一个 `---END FILE---` 或 `---END REVIEW---` 后不要有任何尾随内容
6. FILE 正文用中文，但保留专有名词、模型名、技术术语原文

如果第一个字符不是 `-`，整段响应将被丢弃。

---

# 现在开始生成
"""
```

#### 5.2.4 输出语言守卫

LLM Wiki 在 `src/lib/ingest.ts` 中通过 `contentMatchesTargetLanguage` 函数（位于 `autoIngestImpl` 之后），用 `detectLanguage` 检查每个 FILE 块。Prism 主要面对中文文档，简化版：

```python
# engine/app/wiki/language.py

def content_matches_target_language(content: str, target: str = "zh") -> bool:
    """语言守卫：检查 KP 正文是否在目标语言家族内。

    目标 zh: 接受 Chinese / Traditional Chinese
    目标 en: 接受任何拉丁字母为主的语言
    跨家族（如 zh 目标但生成英文）整页丢弃
    """
    body = _strip_frontmatter_and_code(content)
    sample = body[:1500]
    if len(sample.strip()) < 20:
        return True  # 太短不判
    
    detected = _detect_language(sample)
    
    if target == "zh":
        return detected in {"zh", "zh-Hant", "ja"}  # 日文用了大量汉字，宽松
    if target == "en":
        return detected not in {"zh", "zh-Hant", "ja", "ko", "ar", "th"}
    return True
```


### 5.3 解析层（无副作用）

#### 5.3.1 `parsers.py` —— FILE/REVIEW 块解析

完整移植 `src/lib/ingest.ts` 的 `parseFileBlocks`（含 `FILE_BLOCK_REGEX`、`isSafeIngestPath`）和 `parseReviewBlocks`。

```python
# engine/app/wiki/parsers.py

import re
import yaml
from dataclasses import dataclass, field
from typing import Any

# 与 LLM Wiki 完全一致的正则
FILE_BLOCK_RE = re.compile(
    r"---FILE:\s*([^\n]+?)\s*---\n(.*?)\n---END FILE---",
    re.DOTALL,
)
REVIEW_BLOCK_RE = re.compile(
    r"---REVIEW:\s*([^\n|]+?)\s*\|\s*([^\n]+?)\s*---\n(.*?)\n---END REVIEW---",
    re.DOTALL,
)

OPTIONS_LINE_RE = re.compile(r"^OPTIONS:\s*(.+)$", re.MULTILINE)
PAGES_LINE_RE = re.compile(r"^PAGES:\s*(.+)$", re.MULTILINE)
SEARCH_LINE_RE = re.compile(r"^SEARCH:\s*(.+)$", re.MULTILINE)

# 路径白名单：kp/<slug>.md
KP_PATH_RE = re.compile(r"^kp/([a-z0-9\u4e00-\u9fff][a-z0-9\u4e00-\u9fff\-]*)\.md$")
# 路径黑名单
DENY_PATH_PARTS = {"..", "~", ".", "system32", "etc"}


@dataclass(frozen=True)
class ParsedFileBlock:
    raw_path: str
    slug: str
    frontmatter: dict[str, Any]
    body: str
    is_safe: bool


@dataclass(frozen=True)
class ParsedReviewBlock:
    type: str
    title: str
    description: str
    options: list[str]
    affected_pages: list[str]
    search_queries: list[str]


@dataclass
class ParseResult:
    file_blocks: list[ParsedFileBlock] = field(default_factory=list)
    review_blocks: list[ParsedReviewBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def is_safe_kp_path(path: str) -> bool:
    """路径安全校验。对应 LLM Wiki 的 isSafeIngestPath。"""
    if not path or path.startswith("/") or path.startswith("\\"):
        return False
    parts = path.replace("\\", "/").split("/")
    if any(p in DENY_PATH_PARTS for p in parts):
        return False
    if not KP_PATH_RE.match(path):
        return False
    return True


def parse_frontmatter(body: str) -> tuple[dict, str]:
    """从 markdown 提取 YAML frontmatter。"""
    if not body.startswith("---\n"):
        return {}, body
    end = body.find("\n---", 4)
    if end < 0:
        return {}, body
    yaml_text = body[4:end]
    rest = body[end + 4:].lstrip("\n")
    try:
        fm = yaml.safe_load(yaml_text) or {}
        if not isinstance(fm, dict):
            return {}, body
        return fm, rest
    except yaml.YAMLError:
        return {}, body


def parse_generation_output(text: str) -> ParseResult:
    """主入口：解析 Stage 2 输出。"""
    result = ParseResult()
    
    # 第一字符校验
    stripped = text.lstrip()
    if not stripped.startswith("---FILE:") and not stripped.startswith("---REVIEW:"):
        result.warnings.append(
            f"output does not start with ---FILE: or ---REVIEW:; got {stripped[:40]!r}"
        )
    
    for m in FILE_BLOCK_RE.finditer(text):
        raw_path = m.group(1).strip()
        block_body = m.group(2)
        
        if not is_safe_kp_path(raw_path):
            result.warnings.append(f"unsafe path rejected: {raw_path!r}")
            continue
        
        slug_match = KP_PATH_RE.match(raw_path)
        slug = slug_match.group(1) if slug_match else ""
        
        fm, body = parse_frontmatter(block_body)
        if not fm:
            result.warnings.append(f"frontmatter missing/invalid for {raw_path}")
            continue
        
        # 必填字段校验
        required = ["slug", "type", "title", "created", "updated", "sources"]
        missing = [f for f in required if f not in fm]
        if missing:
            result.warnings.append(f"{raw_path}: missing fields {missing}")
            continue
        
        # frontmatter slug 与路径 slug 必须一致
        if str(fm.get("slug")) != slug:
            result.warnings.append(
                f"{raw_path}: frontmatter slug {fm.get('slug')!r} != path slug {slug!r}; "
                f"using path slug"
            )
        
        result.file_blocks.append(ParsedFileBlock(
            raw_path=raw_path, slug=slug,
            frontmatter=fm, body=body, is_safe=True,
        ))
    
    for m in REVIEW_BLOCK_RE.finditer(text):
        rtype = m.group(1).strip().lower()
        if rtype not in {"contradiction", "duplicate", "missing-page", "suggestion"}:
            result.warnings.append(f"unknown review type rejected: {rtype}")
            continue
        title = m.group(2).strip()
        body = m.group(3)
        
        options = []
        if (mm := OPTIONS_LINE_RE.search(body)):
            options = [s.strip() for s in mm.group(1).split("|")]
        # 过滤非白名单 OPTIONS（防 LLM 幻觉）
        options = [o for o in options if o in {"Create Page", "Skip"}]
        
        pages = []
        if (mm := PAGES_LINE_RE.search(body)):
            pages = [s.strip() for s in mm.group(1).split(",") if s.strip()]
        
        searches = []
        if (mm := SEARCH_LINE_RE.search(body)):
            searches = [s.strip() for s in mm.group(1).split("|") if s.strip()]
        
        # description 是去除 OPTIONS/PAGES/SEARCH 行后的剩余内容
        desc_lines = [
            line for line in body.splitlines()
            if not OPTIONS_LINE_RE.match(line)
            and not PAGES_LINE_RE.match(line)
            and not SEARCH_LINE_RE.match(line)
        ]
        description = "\n".join(desc_lines).strip()
        
        result.review_blocks.append(ParsedReviewBlock(
            type=rtype, title=title, description=description,
            options=options, affected_pages=pages, search_queries=searches,
        ))
    
    return result
```

#### 5.3.2 `wikilink.py` —— 链接解析与重写

完整移植 `src/lib/wiki-graph.ts` 的 `WIKILINK_REGEX` + `extractWikilinks` + `resolveTarget` 模糊匹配，加上 `src/lib/lint-fixes.ts` 的修复辅助。

```python
# engine/app/wiki/wikilink.py

import re

# 与 LLM Wiki 完全一致的正则
WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")


def extract_wikilinks(content: str) -> list[str]:
    """从 markdown 正文提取所有 [[...]] 目标 slug（去重，保序）。"""
    seen: set[str] = set()
    result: list[str] = []
    for m in WIKILINK_RE.finditer(content):
        target = m.group(1).strip()
        if target and target not in seen:
            seen.add(target)
            result.append(target)
    return result


def resolve_slug(raw: str, slug_map: dict[str, str]) -> str | None:
    """大小写/连字符不敏感的 slug 解析。

    Args:
        raw: 来自 [[]] 的原始 slug
        slug_map: 格式 { "lowercased-slug": "kp_id" }

    Returns:
        匹配到的 kp_id，或 None
    """
    if not raw:
        return None
    
    normalized = raw.lower().strip().replace(" ", "-")
    if normalized in slug_map:
        return slug_map[normalized]
    
    no_dash = normalized.replace("-", "")
    return slug_map.get(no_dash)


def rewrite_wikilink(content: str, old_slug: str, new_slug: str) -> str:
    """全局重写 [[old]] → [[new]]，保留别名 [[old|alias]] → [[new|alias]]。"""
    pattern = re.compile(rf"\[\[{re.escape(old_slug)}(\|[^\]]+?)?\]\]")
    return pattern.sub(rf"[[{new_slug}\1]]", content)


def fuzzy_suggest(broken: str, candidates: list[str]) -> str | None:
    """broken-link 的 lint 建议：基于 levenshtein 找最相似的 slug。"""
    from difflib import get_close_matches
    matches = get_close_matches(broken.lower(), [c.lower() for c in candidates], n=1, cutoff=0.6)
    if not matches:
        return None
    # 找回原始大小写
    return next(c for c in candidates if c.lower() == matches[0])
```

### 5.4 持久化层（双源关系合流）

#### 5.4.1 `persist.py` —— KP 与 Relation 写入

```python
# engine/app/wiki/persist.py

import hashlib
from datetime import datetime
from sqlalchemy.orm import Session

from backend.app.models.wiki import (
    WikiKnowledgePoint, WikiKnowledgeRelation, WikiReviewItem,
)
from .parsers import ParsedFileBlock, ParsedReviewBlock
from .wikilink import extract_wikilinks, resolve_slug


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def persist_kps(
    db: Session,
    ctx: "IngestContext",
    file_blocks: list[ParsedFileBlock],
) -> dict[str, str]:
    """写入 KP，返回 slug → kp_id 映射。"""
    kp_id_by_slug: dict[str, str] = {}
    today = datetime.utcnow()
    
    for block in file_blocks:
        slug = block.slug
        fm = block.frontmatter
        body = block.body
        title = str(fm.get("title", slug.replace("-", " ")))
        page_type = str(fm.get("type", "concept"))
        related_slugs = list(fm.get("related", []) or [])
        tags_list = fm.get("tags", []) or []
        tags_str = ",".join(str(t) for t in tags_list)
        content_hash = _sha256(body)
        
        existing = (
            db.query(WikiKnowledgePoint)
            .filter_by(user_id=ctx.user_id, slug=slug)
            .first()
        )
        
        if existing:
            # 同 slug upsert：合并数组字段；正文走 LLM 合并（不直接覆盖）
            #
            # ⚠️ 直接覆盖 existing.content = body 会丢失旧 doc 贡献的事实。
            # 正确做法：调用 merge_kp_content 让 LLM 合并两份正文，参考
            # LLM Wiki 的 src/lib/page-merge.ts 的 mergePageContent。
            #
            # merge_kp_content 实现放在 engine/app/wiki/merge.py，
            # 签名：merge_kp_content(old_body: str, new_body: str, llm) -> str
            # 失败时 fallback 到 new_body（容错），并记日志。
            existing.title = title
            existing.page_type = page_type
            if existing.content and existing.content.strip() != body.strip():
                try:
                    from .merge import merge_kp_content
                    merged = merge_kp_content(existing.content, body, ctx.llm)
                    existing.content = merged
                except Exception as exc:
                    # merge 失败：fallback 到 new body，记日志
                    import logging
                    logging.getLogger(__name__).warning(
                        f"[persist_kps] merge_kp_content failed for slug={slug!r}: {exc}. "
                        f"Falling back to new body."
                    )
                    existing.content = body
            else:
                existing.content = body  # 旧 content 为空或完全相同，直接覆盖
            existing.content_hash = content_hash
            existing.related_slugs = sorted(set(
                (existing.related_slugs or []) + related_slugs
            ))
            existing.tags = ",".join(sorted(set(
                (existing.tags or "").split(",") + tags_list
            ) - {""}))
            existing.source_doc_ids = sorted(set(
                (existing.source_doc_ids or []) + [ctx.doc.id]
            ))
            existing.last_extracted_at = today
            kp_id_by_slug[slug] = existing.id
        else:
            kp = WikiKnowledgePoint(
                document_id=ctx.doc.id,
                user_id=ctx.user_id,
                slug=slug,
                title=title,
                page_type=page_type,
                description="",  # 兼容字段
                content=body,
                tags=tags_str,
                related_slugs=related_slugs,
                source_doc_ids=[ctx.doc.id],
                content_hash=content_hash,
                status="已发布",
                last_extracted_at=today,
            )
            db.add(kp)
            db.flush()
            kp_id_by_slug[slug] = kp.id
    
    db.commit()
    return kp_id_by_slug


def persist_relations_dual_source(
    db: Session,
    ctx: "IngestContext",
    file_blocks: list[ParsedFileBlock],
    kp_id_by_slug: dict[str, str],
) -> dict[str, int]:
    """双源关系建立：正文 wikilink + frontmatter related。

    返回统计 {"wikilink": N, "related": M}。
    """
    stats = {"wikilink": 0, "related": 0}
    
    # 全局 slug 解析表（同 user 所有 KP）
    all_kps = db.query(WikiKnowledgePoint).filter_by(user_id=ctx.user_id).all()
    slug_map = {kp.slug.lower(): kp.id for kp in all_kps}
    
    for block in file_blocks:
        from_slug = block.slug
        from_id = kp_id_by_slug.get(from_slug)
        if not from_id:
            continue
        
        # 来源 1: 正文 [[wikilink]]
        for raw_link in extract_wikilinks(block.body):
            target_id = resolve_slug(raw_link, slug_map)
            if target_id and target_id != from_id:
                if upsert_relation(db, from_id, target_id, "links_to",
                                   origin="wikilink", confidence=1.0):
                    stats["wikilink"] += 1
        
        # 来源 2: frontmatter related
        for related_slug in block.frontmatter.get("related", []) or []:
            target_id = resolve_slug(str(related_slug), slug_map)
            if target_id and target_id != from_id:
                if upsert_relation(db, from_id, target_id, "related",
                                   origin="wikilink", confidence=0.8):
                    stats["related"] += 1
    
    db.commit()
    return stats


def upsert_relation(
    db: Session,
    from_id: str,
    to_id: str,
    rel_type: str,
    *,
    origin: str,
    confidence: float = 1.0,
) -> bool:
    """复合唯一约束 (from, to, type, origin)；存在则取 max(confidence)。
    
    返回 True 表示新建，False 表示已存在。
    """
    existing = (
        db.query(WikiKnowledgeRelation)
        .filter_by(
            from_point_id=from_id, to_point_id=to_id,
            type=rel_type, origin=origin,
        )
        .first()
    )
    if existing:
        if confidence > (existing.confidence or 0):
            existing.confidence = confidence
        return False
    
    db.add(WikiKnowledgeRelation(
        from_point_id=from_id, to_point_id=to_id,
        type=rel_type, origin=origin, confidence=confidence,
    ))
    return True


def persist_review_items(
    db: Session,
    ctx: "IngestContext",
    review_blocks: list[ParsedReviewBlock],
    kp_id_by_slug: dict[str, str],
) -> int:
    """写入 review 队列。"""
    if not review_blocks:
        return 0
    
    slug_to_id = {**kp_id_by_slug}
    all_kps = db.query(WikiKnowledgePoint).filter_by(user_id=ctx.user_id).all()
    for kp in all_kps:
        slug_to_id.setdefault(kp.slug, kp.id)
    
    count = 0
    for review in review_blocks:
        affected_ids = [
            slug_to_id[s] for s in review.affected_pages if s in slug_to_id
        ]
        db.add(WikiReviewItem(
            document_id=ctx.doc.id,
            user_id=ctx.user_id,
            type=review.type,
            title=review.title,
            description=review.description,
            affected_point_ids=affected_ids,
            search_queries=review.search_queries,
            options=review.options or ["Create Page", "Skip"],
            status="pending",
        ))
        count += 1
    
    db.commit()
    return count
```


### 5.5 图引擎层

#### 5.5.1 `graph/relevance.py` —— 4 信号权重

完整移植 `src/lib/graph-relevance.ts` 的 `WEIGHTS` / `TYPE_AFFINITY` 常量与 `calculateRelevance` 函数。

```python
# engine/app/wiki/graph/relevance.py

import math
from dataclasses import dataclass

# 直接对应 src/lib/graph-relevance.ts 的 WEIGHTS 常量
WEIGHTS = {
    "direct_link": 3.0,
    "source_overlap": 4.0,
    "common_neighbor": 1.5,
    "type_affinity": 1.0,
}

# 直接对应 src/lib/graph-relevance.ts 的 TYPE_AFFINITY 常量
TYPE_AFFINITY = {
    ("entity", "concept"): 1.2,
    ("concept", "entity"): 1.2,
    ("entity", "entity"): 0.8,
    ("concept", "concept"): 0.8,
    ("source", "entity"): 1.0,
    ("source", "concept"): 1.0,
    ("synthesis", "concept"): 1.2,
    ("concept", "synthesis"): 1.2,
    ("query", "concept"): 1.0,
    ("query", "entity"): 0.8,
    ("finding", "concept"): 1.0,
    ("finding", "entity"): 0.8,
}
DEFAULT_AFFINITY = 0.5


@dataclass
class KPNode:
    id: str
    slug: str
    page_type: str
    source_doc_ids: frozenset[str]
    out_links: frozenset[str]
    in_links: frozenset[str]


def calculate_relevance(
    a: KPNode,
    b: KPNode,
    all_nodes: dict[str, KPNode],
) -> dict[str, float]:
    """4 信号权重计算。返回 {direct, source, neighbor, type_affinity, total}。"""
    if a.id == b.id:
        return {"direct": 0.0, "source": 0.0, "neighbor": 0.0,
                "type_affinity": 0.0, "total": 0.0}
    
    # 信号 1: direct link
    forward = 1 if b.id in a.out_links else 0
    backward = 1 if a.id in b.out_links else 0
    direct = (forward + backward) * WEIGHTS["direct_link"]
    
    # 信号 2: source overlap
    shared = len(a.source_doc_ids & b.source_doc_ids)
    source = shared * WEIGHTS["source_overlap"]
    
    # 信号 3: Adamic-Adar
    a_neighbors = a.out_links | a.in_links
    b_neighbors = b.out_links | b.in_links
    common = a_neighbors & b_neighbors
    aa_score = 0.0
    for nid in common:
        n = all_nodes.get(nid)
        if not n:
            continue
        deg = len(n.out_links | n.in_links)
        aa_score += 1.0 / math.log(max(deg, 2))
    neighbor = aa_score * WEIGHTS["common_neighbor"]
    
    # 信号 4: type affinity
    affinity = TYPE_AFFINITY.get((a.page_type, b.page_type), DEFAULT_AFFINITY)
    type_aff = affinity * WEIGHTS["type_affinity"]
    
    return {
        "direct": direct,
        "source": source,
        "neighbor": neighbor,
        "type_affinity": type_aff,
        "total": direct + source + neighbor + type_aff,
    }
```

#### 5.5.2 `graph/builder.py` —— 从 DB 构建图

```python
# engine/app/wiki/graph/builder.py

import networkx as nx
from sqlalchemy.orm import Session

from backend.app.models.wiki import WikiKnowledgePoint, WikiKnowledgeRelation
from .relevance import KPNode, calculate_relevance


# 中间产物，不进图。对应 LLM Wiki 的 HIDDEN_TYPES = {"query"}
HIDDEN_TYPES = {"query"}


def build_user_graph(
    db: Session, user_id: str,
) -> tuple[nx.Graph, dict[str, KPNode]]:
    """从 DB 构建 user 范围内的 wiki 图。"""
    kps = (
        db.query(WikiKnowledgePoint)
        .filter(WikiKnowledgePoint.user_id == user_id)
        .filter(~WikiKnowledgePoint.page_type.in_(HIDDEN_TYPES))
        .all()
    )
    if not kps:
        return nx.Graph(), {}
    
    kp_ids = {k.id for k in kps}
    relations = (
        db.query(WikiKnowledgeRelation)
        .filter(WikiKnowledgeRelation.from_point_id.in_(kp_ids))
        .filter(WikiKnowledgeRelation.to_point_id.in_(kp_ids))
        .all()
    )
    
    out_links: dict[str, set[str]] = {k.id: set() for k in kps}
    in_links: dict[str, set[str]] = {k.id: set() for k in kps}
    for r in relations:
        out_links[r.from_point_id].add(r.to_point_id)
        in_links[r.to_point_id].add(r.from_point_id)
    
    nodes: dict[str, KPNode] = {
        k.id: KPNode(
            id=k.id, slug=k.slug, page_type=k.page_type,
            source_doc_ids=frozenset(k.source_doc_ids or []),
            out_links=frozenset(out_links[k.id]),
            in_links=frozenset(in_links[k.id]),
        )
        for k in kps
    }
    
    G = nx.Graph()
    for k in kps:
        G.add_node(k.id, slug=k.slug, type=k.page_type, title=k.title,
                   community=k.community_id)
    
    seen = set()
    for r in relations:
        key = tuple(sorted([r.from_point_id, r.to_point_id]))
        if key in seen:
            continue
        seen.add(key)
        scores = calculate_relevance(
            nodes[r.from_point_id], nodes[r.to_point_id], nodes,
        )
        G.add_edge(
            r.from_point_id, r.to_point_id,
            weight=scores["total"], **scores,
        )
    
    return G, nodes
```

#### 5.5.3 `graph/recompute.py` —— 重算调度

```python
# engine/app/wiki/graph/recompute.py

import logging
from datetime import datetime
from sqlalchemy.orm import Session

from backend.app.models.wiki import WikiKnowledgePoint, WikiKnowledgeRelation
from .builder import build_user_graph

logger = logging.getLogger(__name__)


def recompute_graph_for_user(
    db: Session,
    user_id: str,
    *,
    full: bool = False,
) -> dict:
    """图重算入口。

    full=False（默认）：只重算所有边权重 + 节点 in/out count
    full=True：在上述基础上加 Louvain 社区检测（阶段 5 启用）

    注意：边权重重算需要全图 4 信号信息（Adamic-Adar 依赖 N-hop 邻居），
    所以即使是"增量"也要遍历全图。NetworkX 万节点级别毫秒级，可接受。
    """
    started = datetime.utcnow()
    G, nodes = build_user_graph(db, user_id)
    
    if not G.nodes:
        return {"nodes": 0, "edges": 0}
    
    # 1. 边权重写回
    edge_count = 0
    for u, v, data in G.edges(data=True):
        # NetworkX 是无向图，但 DB 中边有方向；按主键对查找两条
        rels = (
            db.query(WikiKnowledgeRelation)
            .filter(
                ((WikiKnowledgeRelation.from_point_id == u)
                 & (WikiKnowledgeRelation.to_point_id == v))
                | ((WikiKnowledgeRelation.from_point_id == v)
                   & (WikiKnowledgeRelation.to_point_id == u))
            )
            .all()
        )
        for r in rels:
            r.weight_total = data["total"]
            r.weight_direct = data["direct"]
            r.weight_source = data["source"]
            r.weight_neighbor = data["neighbor"]
            r.weight_type = data["type_affinity"]
            r.last_computed_at = started
        edge_count += 1
    
    # 2. 节点 in/out count
    for nid, node in nodes.items():
        db.query(WikiKnowledgePoint).filter_by(id=nid).update({
            "out_link_count": len(node.out_links),
            "in_link_count": len(node.in_links),
        })
    
    # 3. Louvain（阶段 5 启用）
    if full and len(G.nodes) >= 3:
        from .community import detect_communities
        community_map = detect_communities(G)
        for nid, cid in community_map.items():
            db.query(WikiKnowledgePoint).filter_by(id=nid).update({
                "community_id": cid,
            })
    
    db.commit()
    elapsed_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
    logger.info(
        f"[wiki-graph] user={user_id} nodes={len(G.nodes)} edges={edge_count} "
        f"full={full} elapsed_ms={elapsed_ms}"
    )
    return {
        "nodes": len(G.nodes),
        "edges": edge_count,
        "elapsed_ms": elapsed_ms,
    }
```

#### 5.5.4 `graph/community.py` —— Louvain（阶段 5）

```python
# engine/app/wiki/graph/community.py

import networkx as nx

try:
    import community as community_louvain  # python-louvain
except ImportError:
    community_louvain = None


def detect_communities(G: nx.Graph) -> dict[str, int]:
    """Louvain 社区检测。返回 {kp_id: community_id}。"""
    if community_louvain is None:
        raise RuntimeError(
            "python-louvain not installed. Run: pip install python-louvain"
        )
    if len(G.nodes) < 3:
        return {nid: 0 for nid in G.nodes}
    
    partition = community_louvain.best_partition(G, weight="weight", resolution=1.0)
    
    # 按社区规模重新编号（最大社区 = 0）
    from collections import Counter
    sizes = Counter(partition.values())
    sorted_ids = sorted(sizes.keys(), key=lambda c: -sizes[c])
    remap = {old: new for new, old in enumerate(sorted_ids)}
    return {nid: remap[cid] for nid, cid in partition.items()}


def compute_community_cohesion(
    G: nx.Graph, community_map: dict[str, int],
) -> dict[int, float]:
    """每个社区的 cohesion = 内部边数 / 可能的最大边数。

    用于 graph_insights.detect_knowledge_gaps。
    """
    from collections import defaultdict
    members: dict[int, list[str]] = defaultdict(list)
    for nid, cid in community_map.items():
        members[cid].append(nid)
    
    cohesion: dict[int, float] = {}
    for cid, ids in members.items():
        n = len(ids)
        if n < 2:
            cohesion[cid] = 1.0
            continue
        intra = sum(1 for u, v in G.edges() if community_map.get(u) == cid
                    and community_map.get(v) == cid)
        max_edges = n * (n - 1) / 2
        cohesion[cid] = intra / max_edges if max_edges > 0 else 0.0
    return cohesion
```


### 5.6 检索层（KP 级 + 图扩展）

#### 5.6.1 新建 Milvus collection 与 ES index

```python
# engine/app/wiki/retrieval/setup.py

from pymilvus import (
    Collection, CollectionSchema, FieldSchema, DataType, utility,
)
from elasticsearch import Elasticsearch

KP_COLLECTION = "prism_wiki_kp"
KP_INDEX = "wiki_kp"


def ensure_kp_milvus_collection(dim: int = 1024):
    if utility.has_collection(KP_COLLECTION):
        return
    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
        FieldSchema(name="kp_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="slug", dtype=DataType.VARCHAR, max_length=255),
        FieldSchema(name="page_type", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
    ]
    schema = CollectionSchema(fields, description="Prism Wiki KP embeddings")
    coll = Collection(KP_COLLECTION, schema)
    coll.create_index("embedding", {
        "index_type": "IVF_FLAT",
        "metric_type": "IP",
        "params": {"nlist": 128},
    })
    coll.load()


def ensure_kp_es_index(es: Elasticsearch):
    if es.indices.exists(index=KP_INDEX):
        return
    es.indices.create(index=KP_INDEX, body={
        "settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}},
        "mappings": {
            "properties": {
                "kp_id": {"type": "keyword"},
                "user_id": {"type": "keyword"},
                "slug": {"type": "keyword"},
                "page_type": {"type": "keyword"},
                "title": {"type": "text", "analyzer": "ik_max_word"},
                "content": {"type": "text", "analyzer": "ik_max_word"},
                "tags": {"type": "keyword"},
                "doc_id": {"type": "keyword"},
                "created_at": {"type": "date"},
            }
        }
    })
```

#### 5.6.2 `retrieval/kp_search.py` —— 混合检索

```python
# engine/app/wiki/retrieval/kp_search.py

from typing import TypedDict
from pymilvus import Collection
from elasticsearch import Elasticsearch

from engine.app.config import settings
from engine.app.es_client import get_es
from engine.app.ingestion.vectorizer import embed_texts
from .setup import KP_COLLECTION, KP_INDEX


class KPSearchHit(TypedDict):
    kp_id: str
    slug: str
    title: str
    page_type: str
    score: float
    vector_score: float
    bm25_score: float
    doc_ids: list[str]


def hybrid_search_kp(
    user_id: str,
    query: str,
    *,
    top_k: int = 10,
    use_vector: bool = True,
) -> list[KPSearchHit]:
    """KP 级 hybrid 检索（向量 + BM25 + RRF 融合）。"""
    if not query.strip():
        return []
    
    bm25_hits = es_search_kp(user_id, query, top_k * 2)
    vector_hits: list[dict] = []
    if use_vector:
        emb = embed_texts([query])[0]
        vector_hits = milvus_search_kp(user_id, emb, top_k * 2)
    
    return rrf_fuse(bm25_hits, vector_hits, k=60, top_k=top_k)


def es_search_kp(user_id: str, query: str, top_k: int) -> list[dict]:
    es = get_es()
    body = {
        "size": top_k,
        "query": {
            "bool": {
                "must": [{"multi_match": {"query": query, "fields": ["title^2", "content"]}}],
                "filter": [{"term": {"user_id": user_id}}],
            }
        }
    }
    resp = es.search(index=KP_INDEX, body=body)
    return [
        {
            "kp_id": h["_source"]["kp_id"],
            "slug": h["_source"]["slug"],
            "title": h["_source"]["title"],
            "page_type": h["_source"]["page_type"],
            "bm25_score": h["_score"],
            "doc_ids": h["_source"].get("doc_ids", []),
        }
        for h in resp["hits"]["hits"]
    ]


def milvus_search_kp(user_id: str, embedding: list[float], top_k: int) -> list[dict]:
    # 安全校验：防止 user_id 注入 Milvus 表达式（如 `" or true`）。
    # 使用与 backend _validate_user_id 一致的白名单正则。
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", user_id):
        raise ValueError(f"invalid user_id format: {user_id!r}")
    
    coll = Collection(KP_COLLECTION)
    coll.load()
    # 参数化 expr：使用 Milvus 提供的 partition_key 或显式 == 操作符。
    # user_id 已经过校验，只含 [A-Za-z0-9_-]，不含引号 / 控制字符。
    expr = f'user_id == "{user_id}"'
    resp = coll.search(
        [embedding], anns_field="embedding",
        param={"metric_type": "IP", "params": {"nprobe": 16}},
        limit=top_k, expr=expr,
        output_fields=["kp_id", "slug", "page_type"],
    )
    return [
        {
            "kp_id": hit.entity.get("kp_id"),
            "slug": hit.entity.get("slug"),
            "page_type": hit.entity.get("page_type"),
            "vector_score": float(hit.score),
        }
        for hit in resp[0]
    ]


def rrf_fuse(
    bm25_hits: list[dict],
    vector_hits: list[dict],
    *,
    k: int = 60,
    top_k: int = 10,
) -> list[KPSearchHit]:
    """Reciprocal Rank Fusion。"""
    scores: dict[str, dict] = {}
    
    for rank, h in enumerate(bm25_hits):
        kp_id = h["kp_id"]
        scores.setdefault(kp_id, {**h, "score": 0.0, "vector_score": 0.0, "bm25_score": 0.0})
        scores[kp_id]["bm25_score"] = h.get("bm25_score", 0.0)
        scores[kp_id]["score"] += 1.0 / (k + rank)
    
    for rank, h in enumerate(vector_hits):
        kp_id = h["kp_id"]
        scores.setdefault(kp_id, {**h, "score": 0.0, "vector_score": 0.0, "bm25_score": 0.0})
        scores[kp_id]["vector_score"] = h.get("vector_score", 0.0)
        scores[kp_id]["score"] += 1.0 / (k + rank)
    
    fused = sorted(scores.values(), key=lambda x: -x["score"])
    return fused[:top_k]
```

#### 5.6.3 `retrieval/graph_expand.py` —— 图扩展

```python
# engine/app/wiki/retrieval/graph_expand.py

from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.app.models.wiki import WikiKnowledgeRelation


def graph_expand_kp(
    db: Session,
    seed_kp_ids: list[str],
    *,
    hops: int = 2,
    top_per_hop: int = 3,
    decay: float = 0.5,
) -> list[tuple[str, float]]:
    """4 信号权重 N-hop 扩展。

    返回 [(kp_id, score)] 按 score 降序，不包含 seed。
    score = base_score × edge.weight_total × decay^hop
    """
    if not seed_kp_ids:
        return []
    
    expanded: dict[str, float] = {}
    frontier: dict[str, float] = {kid: 1.0 for kid in seed_kp_ids}
    seed_set = set(seed_kp_ids)
    
    for hop in range(hops):
        next_frontier: dict[str, float] = {}
        for kp_id, base in frontier.items():
            neighbors = (
                db.query(WikiKnowledgeRelation)
                .filter(or_(
                    WikiKnowledgeRelation.from_point_id == kp_id,
                    WikiKnowledgeRelation.to_point_id == kp_id,
                ))
                .order_by(WikiKnowledgeRelation.weight_total.desc())
                .limit(top_per_hop)
                .all()
            )
            for r in neighbors:
                target = r.to_point_id if r.from_point_id == kp_id else r.from_point_id
                if target in seed_set:
                    continue
                score = base * (r.weight_total or 0.0) * (decay ** hop)
                if score > expanded.get(target, 0.0):
                    expanded[target] = score
                    next_frontier[target] = score
        frontier = next_frontier
        if not frontier:
            break
    
    return sorted(expanded.items(), key=lambda x: -x[1])
```

#### 5.6.4 Agent Tool 集成

```python
# engine/app/agent/tools/wiki.py

import json
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool
from engine.app.wiki.retrieval.kp_search import hybrid_search_kp
from engine.app.wiki.retrieval.graph_expand import graph_expand_kp


KEY = "wiki_search"


class WikiSearchInput(BaseModel):
    query: str = Field(..., description="概念或主题查询，用于检索 wiki 知识点")
    top_k: int = Field(5, description="返回的 KP 数量")


def build(ctx: ToolContext) -> StructuredTool:
    def run(query: str, top_k: int = 5) -> str:
        primary = hybrid_search_kp(ctx.user_id, query, top_k=top_k)
        if not primary:
            return json.dumps({
                "status": "empty",
                "summary": "未在 wiki 中找到相关知识点",
                "primary_hits": [],
                "graph_expanded": [],
            }, ensure_ascii=False)
        
        seed_ids = [h["kp_id"] for h in primary[:3]]
        with ctx.db_session() as db:
            expanded_ranked = graph_expand_kp(db, seed_ids, hops=1, top_per_hop=3)
            top_expanded_ids = [kid for kid, _ in expanded_ranked[:5]]
            from backend.app.models.wiki import WikiKnowledgePoint
            expanded_kps = (
                db.query(WikiKnowledgePoint)
                .filter(WikiKnowledgePoint.id.in_(top_expanded_ids))
                .all()
            )
            expanded_summary = [
                {
                    "kp_id": kp.id, "slug": kp.slug, "title": kp.title,
                    "page_type": kp.page_type,
                    "description": (kp.content or "")[:300],
                }
                for kp in expanded_kps
            ]
        
        # 把命中的 KP 加入 citations
        ctx.citations.extend([
            {
                "kp_id": h["kp_id"], "slug": h["slug"], "title": h["title"],
                "page_type": h["page_type"], "score": h["score"],
            }
            for h in primary
        ])
        
        ctx.stats_holder[KEY] = {
            "primary_count": len(primary),
            "expanded_count": len(expanded_summary),
        }
        
        return json.dumps({
            "status": "found",
            "summary": f"找到 {len(primary)} 个相关 KP，图扩展 {len(expanded_summary)} 个邻居",
            "primary_hits": primary,
            "graph_expanded": expanded_summary,
        }, ensure_ascii=False)
    
    return StructuredTool.from_function(
        func=run, name=KEY,
        description="搜索 Prism Wiki 知识点（已结构化的概念页面）。"
                    "适合查询定义、流程、规则、对比等概念性问题。"
                    "对于具体事实细节问题，优先用 knowledge_search。",
        args_schema=WikiSearchInput,
    )


register_tool(ToolSpec(
    key=KEY, name=KEY,
    description="Search Prism Wiki KPs (curated concepts).",
    builder=build,
    default_enabled=True,
))
```


### 5.7 治理三件套（阶段 4 起）

#### 5.7.1 `governance/lint.py` —— 结构 + 语义 lint

```python
# engine/app/wiki/governance/lint.py

from collections import Counter
from datetime import datetime
from sqlalchemy.orm import Session

from backend.app.models.wiki import (
    WikiKnowledgePoint, WikiLintFinding,
)
from ..wikilink import extract_wikilinks, resolve_slug, fuzzy_suggest


def run_structural_lint(db: Session, user_id: str) -> list[dict]:
    """无 LLM 的结构 lint。返回 finding 列表（同时持久化）。"""
    kps = db.query(WikiKnowledgePoint).filter_by(user_id=user_id).all()
    if not kps:
        return []
    
    slug_to_id = {kp.slug.lower(): kp.id for kp in kps}
    findings: list[WikiLintFinding] = []
    in_counts: Counter = Counter()
    
    # 1. 统计入链
    for kp in kps:
        for raw in extract_wikilinks(kp.content or ""):
            target_id = resolve_slug(raw, slug_to_id)
            if target_id:
                in_counts[target_id] += 1
    
    # 2. 检查每个 KP
    skip_orphan_types = {"query", "synthesis"}
    for kp in kps:
        outlinks = extract_wikilinks(kp.content or "")
        
        # broken-link
        for raw in outlinks:
            if not resolve_slug(raw, slug_to_id):
                suggested = fuzzy_suggest(raw, list(slug_to_id.keys()))
                findings.append(WikiLintFinding(
                    type="broken-link",
                    severity="warning",
                    point_id=kp.id,
                    user_id=user_id,
                    detail=f"page references [[{raw}]] but target not found",
                    broken_target=raw,
                    suggested_target_slug=suggested,
                    status="open",
                ))
        
        # orphan
        if (
            in_counts.get(kp.id, 0) == 0
            and kp.page_type not in skip_orphan_types
        ):
            findings.append(WikiLintFinding(
                type="orphan",
                severity="info",
                point_id=kp.id,
                user_id=user_id,
                detail="无入链；此 KP 未被其他 KP 引用",
                status="open",
            ))
        
        # no-outlinks
        if not outlinks and kp.page_type != "query":
            findings.append(WikiLintFinding(
                type="no-outlinks",
                severity="info",
                point_id=kp.id,
                user_id=user_id,
                detail="正文中无 [[wikilink]]",
                status="open",
            ))
    
    # 去重持久化（相同 type+point_id+broken_target 仅保留一条 open）
    upsert_findings(db, user_id, findings)
    return [_to_dict(f) for f in findings]


def run_semantic_lint(
    db: Session,
    user_id: str,
    llm_client,
) -> list[dict]:
    """LLM 语义 lint：contradiction / stale / missing-page。

    采用 LLM Wiki `lint.ts` 中 `runSemanticLint` 的策略：
    1. 把所有 KP 的标题 + 前 500 字摘要喂给 LLM
    2. 要求按 ---LINT: type | severity | title--- 格式输出
    3. 解析回 WikiLintFinding
    """
    kps = db.query(WikiKnowledgePoint).filter_by(user_id=user_id).all()
    if len(kps) < 3:
        return []
    
    summaries = [
        f"### {kp.slug}\n标题：{kp.title}\n类型：{kp.page_type}\n"
        f"摘要：{(kp.content or '')[:500]}"
        for kp in kps
    ]
    summaries_text = "\n\n".join(summaries)
    
    response = llm_client.chat([
        {"role": "system", "content": SEMANTIC_LINT_SYSTEM_PROMPT},
        {"role": "user", "content": f"## Wiki KPs\n\n{summaries_text}"},
    ])
    
    findings = parse_lint_blocks(response, kps, user_id)
    upsert_findings(db, user_id, findings)
    return [_to_dict(f) for f in findings]


SEMANTIC_LINT_SYSTEM_PROMPT = """你是 wiki 质量分析师。审阅以下 wiki KP 摘要并发现问题。

只报告真正的问题，不要凭空捏造。

输出格式（每个问题一个块）：
---LINT: type | severity | 标题---
问题描述
PAGES: <slug1>, <slug2>
---END LINT---

type 严格枚举：
- contradiction: 两个或多个 KP 之间存在矛盾论断
- stale: 内容看起来过时或被新信息覆盖
- missing-page: 重要概念被反复提及但没有专门的 KP

severity 严格枚举：
- warning: 应该处理
- info: 可以处理

只输出 ---LINT--- 块，不输出其他任何内容。
"""
```

#### 5.7.2 `governance/dedup.py` —— 软碰撞去重

```python
# engine/app/wiki/governance/dedup.py

import json
from sqlalchemy.orm import Session

from backend.app.models.wiki import (
    WikiKnowledgePoint, WikiKnowledgeRelation, WikiDedupCandidate,
)
from ..wikilink import rewrite_wikilink


DEDUP_DETECT_PROMPT = """你是 wiki 重复检测专家。下面是某个用户 wiki 中的所有 entity 和 concept 类 KP 摘要。

找出指代同一事物但用不同名字的组（如缩写、中英对照、同义词、单复数等）。

输出严格 JSON：
{
  "groups": [
    {
      "slugs": ["slug-1", "slug-2", "slug-3"],
      "reason": "短文：为什么认为它们是同一事物",
      "confidence": "high|medium|low"
    }
  ]
}

规则：
- 仅当你有 medium 以上 confidence 时才输出
- 每组至少 2 个 slug
- 不要输出代码块包装
- 如果没有重复，输出 {"groups": []}
"""


def detect_duplicate_groups(
    db: Session,
    user_id: str,
    llm_client,
) -> list[dict]:
    """三阶段：摘要提取 → LLM 判重 → 写入候选表。"""
    kps = (
        db.query(WikiKnowledgePoint)
        .filter_by(user_id=user_id)
        .filter(WikiKnowledgePoint.page_type.in_(["entity", "concept"]))
        .all()
    )
    if len(kps) < 2:
        return []
    
    summaries = [
        {
            "slug": kp.slug,
            "title": kp.title,
            "description": (kp.content or "")[:200],
            "tags": kp.tags or "",
            "type": kp.page_type,
        }
        for kp in kps
    ]
    
    response = llm_client.chat([
        {"role": "system", "content": DEDUP_DETECT_PROMPT},
        {"role": "user", "content": json.dumps(summaries, ensure_ascii=False)},
    ])
    
    try:
        data = json.loads(_extract_json_object(response))
        groups = data.get("groups", []) or []
    except (json.JSONDecodeError, ValueError):
        return []
    
    slug_to_id = {kp.slug: kp.id for kp in kps}
    candidates = []
    for g in groups:
        slugs = g.get("slugs", []) or []
        point_ids = [slug_to_id[s] for s in slugs if s in slug_to_id]
        if len(point_ids) < 2:
            continue
        cand = WikiDedupCandidate(
            point_ids=point_ids,
            reason=g.get("reason", ""),
            confidence=g.get("confidence", "medium"),
            user_id=user_id,
            status="pending",
        )
        db.add(cand)
        candidates.append(cand)
    db.commit()
    
    return [
        {
            "id": c.id,
            "point_ids": c.point_ids,
            "reason": c.reason,
            "confidence": c.confidence,
        }
        for c in candidates
    ]


def merge_duplicate(
    db: Session,
    candidate_id: str,
    canonical_id: str,
    llm_client,
) -> dict:
    """用户确认后执行合并。"""
    cand = db.query(WikiDedupCandidate).get(candidate_id)
    if not cand or cand.status != "pending":
        raise ValueError(f"candidate {candidate_id} not pending")
    if canonical_id not in cand.point_ids:
        raise ValueError(f"canonical_id {canonical_id} not in group")
    
    kps = (
        db.query(WikiKnowledgePoint)
        .filter(WikiKnowledgePoint.id.in_(cand.point_ids))
        .all()
    )
    canonical = next(k for k in kps if k.id == canonical_id)
    others = [k for k in kps if k.id != canonical_id]
    
    # LLM 合并 markdown 正文
    contents = [k.content or "" for k in kps]
    merged_body = llm_merge_contents(llm_client, canonical.title, contents)
    
    # 代码合并 frontmatter 数组（union）
    canonical.content = merged_body
    canonical.related_slugs = sorted(set(sum(
        [k.related_slugs or [] for k in kps], []
    )))
    canonical.source_doc_ids = sorted(set(sum(
        [k.source_doc_ids or [] for k in kps], []
    )))
    canonical.tags = ",".join(sorted(set(
        ",".join([k.tags or "" for k in kps]).split(",")
    ) - {""}))
    canonical.aliases = ",".join(sorted(set(
        (canonical.aliases or "").split(",")
        + [k.title for k in others]
    ) - {""}))
    
    # 全局重写 wikilink
    other_slugs = [k.slug for k in others]
    all_kps = (
        db.query(WikiKnowledgePoint)
        .filter_by(user_id=cand.user_id)
        .filter(WikiKnowledgePoint.id != canonical_id)
        .filter(~WikiKnowledgePoint.id.in_([k.id for k in others]))
        .all()
    )
    for kp in all_kps:
        new_content = kp.content or ""
        for old_slug in other_slugs:
            new_content = rewrite_wikilink(new_content, old_slug, canonical.slug)
        if new_content != kp.content:
            kp.content = new_content
    
    # 重写 relation 的 from/to 指针
    for k in others:
        db.query(WikiKnowledgeRelation).filter_by(
            from_point_id=k.id
        ).update({"from_point_id": canonical_id})
        db.query(WikiKnowledgeRelation).filter_by(
            to_point_id=k.id
        ).update({"to_point_id": canonical_id})
    
    # 删 KP（CASCADE 清理空的 relation）
    for k in others:
        db.delete(k)
    
    cand.status = "merged"
    cand.canonical_id = canonical_id
    db.commit()
    
    return {
        "canonical_id": canonical_id,
        "merged_count": len(others),
        "merged_slugs": other_slugs,
    }
```

#### 5.7.3 `governance/sweep.py` —— Review 自动消解

```python
# engine/app/wiki/governance/sweep.py

from sqlalchemy.orm import Session
from datetime import datetime
from itertools import islice

from backend.app.models.wiki import WikiReviewItem, WikiKnowledgePoint


def sweep_pending_reviews(
    db: Session,
    user_id: str,
    llm_client,
) -> dict:
    """ingest 完成后调用。两阶段消解。"""
    pending = (
        db.query(WikiReviewItem)
        .filter_by(user_id=user_id, status="pending")
        .all()
    )
    if not pending:
        return {"resolved": 0, "examined": 0}
    
    kps = db.query(WikiKnowledgePoint).filter_by(user_id=user_id).all()
    slug_set = {kp.slug.lower() for kp in kps}
    title_set = {kp.title.lower() for kp in kps}
    
    auto_resolved: list[tuple[WikiReviewItem, str]] = []
    
    # Stage 1: 规则匹配（仅 missing-page 类）
    for r in pending:
        if r.type != "missing-page":
            continue
        for cand_name in extract_candidate_names(r):
            normalized = cand_name.lower()
            if normalized in slug_set or normalized in title_set:
                auto_resolved.append((r, "rule-matched"))
                break
    
    # Stage 2: LLM judge（剩余）
    rule_resolved_ids = {r.id for r, _ in auto_resolved}
    remaining = [r for r in pending if r.id not in rule_resolved_ids]
    BATCH = 40
    
    for batch in _chunked(remaining, BATCH):
        kp_index = build_kp_index_summary(kps)
        resolved_ids = llm_judge_resolved(batch, kp_index, llm_client)
        for r in batch:
            if r.id in resolved_ids:
                auto_resolved.append((r, "llm-judged"))
    
    # 保守：contradiction 类不自动消解
    safe = [(r, why) for r, why in auto_resolved if r.type != "contradiction"]
    
    now = datetime.utcnow()
    for r, why in safe:
        r.status = "resolved"
        r.resolution_note = f"auto: {why}"
        r.resolved_at = now
    db.commit()
    
    return {
        "resolved": len(safe),
        "examined": len(pending),
        "skipped_contradiction": sum(
            1 for r, _ in auto_resolved if r.type == "contradiction"
        ),
    }


def _chunked(lst, n):
    it = iter(lst)
    while batch := list(islice(it, n)):
        yield batch
```


### 5.8 Backend API 改造

#### 5.8.1 在现有 `backend/app/api/wiki.py` 上扩展

新增端点：

```python
# backend/app/api/wiki.py — 追加以下端点

import logging
import re
import threading

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

# ── 通用 helpers（被下面的端点复用） ──────────────────────

# user_id 安全字符白名单：UUID / 字母 / 数字 / 连字符 / 下划线。
# 防止注入 SQL 操作符 / Milvus expr 控制字符。
_USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _validate_user_id(user_id: str) -> str:
    if not user_id or not _USER_ID_RE.fullmatch(user_id):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_user_id", "message": f"invalid user_id format: {user_id!r}"},
        )
    return user_id


def _post_engine(path: str, payload: dict) -> None:
    """Fire-and-forget POST 到 Engine。

    内部 HTTP 调用，超时 30s。失败不抛，只记日志。
    所有 _call_engine_* helpers 都通过这个封装走。
    """
    try:
        httpx.post(
            f"http://127.0.0.1:{settings.ENGINE_PORT}/api/v1/wiki{path}",
            json=payload,
            timeout=30,
        )
    except Exception as exc:
        logger.warning(f"[wiki] engine call failed path={path} payload={payload} err={exc}")


def _call_engine_recompute(user_id: str, full: bool) -> None:
    _post_engine("/graph/recompute", {"user_id": user_id, "full": full})


def _call_engine_lint(user_id: str, semantic: bool) -> None:
    _post_engine("/lint/run", {"user_id": user_id, "semantic": semantic})


def _call_engine_dedup_detect(user_id: str) -> None:
    _post_engine("/dedup/detect", {"user_id": user_id})


def _call_engine_sweep(user_id: str) -> None:
    _post_engine("/sweep", {"user_id": user_id})


# ── Graph endpoints ───────────────────────────────────────

@router.get("/graph")
def get_graph(
    user_id: str = "default-user",
    types: str | None = Query(None, description="逗号分隔过滤 page_type"),
    db: Session = Depends(get_db),
):
    """返回 user 范围内的 wiki 图（节点 + 边 + 社区）。"""
    type_filter = set(types.split(",")) if types else None
    
    kps = db.query(WikiKnowledgePoint).filter_by(user_id=user_id).all()
    if type_filter:
        kps = [kp for kp in kps if kp.page_type in type_filter]
    
    if not kps:
        return {"nodes": [], "edges": [], "communities": []}
    
    kp_ids = {kp.id for kp in kps}
    relations = (
        db.query(WikiKnowledgeRelation)
        .filter(WikiKnowledgeRelation.from_point_id.in_(kp_ids))
        .filter(WikiKnowledgeRelation.to_point_id.in_(kp_ids))
        .all()
    )
    
    nodes = [
        {
            "id": kp.id,
            "slug": kp.slug,
            "title": kp.title,
            "page_type": kp.page_type,
            "community": kp.community_id,
            "in_count": kp.in_link_count or 0,
            "out_count": kp.out_link_count or 0,
        }
        for kp in kps
    ]
    edges = [
        {
            "source": r.from_point_id,
            "target": r.to_point_id,
            "type": r.type,
            "origin": r.origin,
            "weight": r.weight_total or 0.0,
            "weight_breakdown": {
                "direct": r.weight_direct,
                "source": r.weight_source,
                "neighbor": r.weight_neighbor,
                "type": r.weight_type,
            },
        }
        for r in relations
    ]
    
    return {"nodes": nodes, "edges": edges}


@router.post("/graph/recompute")
def trigger_graph_recompute(
    user_id: str = "default-user",
    full: bool = False,
):
    """触发图重算（异步）。"""
    _validate_user_id(user_id)
    threading.Thread(
        target=_call_engine_recompute,
        args=(user_id, full),
        daemon=True,
    ).start()
    return {"status": "scheduled", "user_id": user_id, "full": full}


@router.get("/graph/insights")
def get_insights(
    user_id: str = "default-user",
    db: Session = Depends(get_db),
):
    """返回 surprising connections + knowledge gaps（阶段 5）。"""
    # ... 调用 engine/app/wiki/graph/insights.py
    ...


# ── KP search endpoint ────────────────────────────────────

@router.post("/search")
def search_kps(
    payload: WikiSearchRequest,
    db: Session = Depends(get_db),
):
    """对外 KP 检索（供前端、Agent、外部 MCP 调用）。"""
    # 实际由 Engine 处理，Backend 透传
    response = httpx.post(
        f"http://127.0.0.1:{settings.ENGINE_PORT}/api/v1/wiki/search",
        json=payload.dict(),
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


# ── Governance endpoints ──────────────────────────────────

@router.post("/lint/run")
def trigger_lint_run(
    user_id: str = "default-user",
    semantic: bool = False,
):
    """触发 lint（structural 默认本地，semantic 走 LLM）。"""
    _validate_user_id(user_id)
    threading.Thread(
        target=_call_engine_lint,
        args=(user_id, semantic),
        daemon=True,
    ).start()
    return {"status": "scheduled", "user_id": user_id, "semantic": semantic}


@router.get("/lint", response_model=list[WikiLintFindingOut])
def list_findings(
    user_id: str = "default-user",
    status: str = "open",
    db: Session = Depends(get_db),
):
    """列出 lint 发现。"""
    return (
        db.query(WikiLintFinding)
        .filter_by(user_id=user_id, status=status)
        .order_by(WikiLintFinding.created_at.desc())
        .all()
    )


@router.post("/lint/{finding_id}/fix")
def apply_lint_fix(
    finding_id: str,
    db: Session = Depends(get_db),
):
    """应用 lint 修复建议（broken-link → 改写 wikilink；orphan → 创建 stub）。"""
    finding = db.query(WikiLintFinding).filter_by(id=finding_id).first()
    if not finding:
        raise HTTPException(status_code=404, detail="finding not found")
    # ... 调用 engine/app/wiki/governance/fix.py
    ...


@router.post("/dedup/detect")
def trigger_dedup_detect(
    user_id: str = "default-user",
):
    """触发去重检测（LLM 调用）。"""
    _validate_user_id(user_id)
    threading.Thread(
        target=_call_engine_dedup_detect,
        args=(user_id,),
        daemon=True,
    ).start()
    return {"status": "scheduled", "user_id": user_id}


@router.get("/dedup", response_model=list[WikiDedupCandidateOut])
def list_dedup_candidates(
    user_id: str = "default-user",
    status: str = "pending",
    db: Session = Depends(get_db),
):
    return (
        db.query(WikiDedupCandidate)
        .filter_by(user_id=user_id, status=status)
        .order_by(WikiDedupCandidate.created_at.desc())
        .all()
    )


@router.post("/dedup/{candidate_id}/merge")
def merge_dedup_group(
    candidate_id: str,
    canonical_id: str,
    db: Session = Depends(get_db),
):
    """用户确认 canonical 后执行合并。"""
    response = httpx.post(
        f"http://127.0.0.1:{settings.ENGINE_PORT}/api/v1/wiki/dedup/merge",
        json={"candidate_id": candidate_id, "canonical_id": canonical_id},
        timeout=60,  # 包含 LLM 合并 body 的时间
    )
    response.raise_for_status()
    return response.json()


# ── Review endpoints ──────────────────────────────────────

@router.get("/reviews", response_model=list[WikiReviewItemOut])
def list_reviews(
    user_id: str = "default-user",
    status: str = "pending",
    type: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(WikiReviewItem).filter_by(user_id=user_id, status=status)
    if type:
        q = q.filter_by(type=type)
    return q.order_by(WikiReviewItem.created_at.desc()).all()


@router.post("/reviews/sweep")
def trigger_review_sweep(user_id: str = "default-user"):
    """触发自动消解（LLM judge）。"""
    _validate_user_id(user_id)
    threading.Thread(
        target=_call_engine_sweep,
        args=(user_id,),
        daemon=True,
    ).start()
    return {"status": "scheduled", "user_id": user_id}


@router.patch("/reviews/{review_id}")
def update_review(
    review_id: str,
    payload: WikiReviewUpdateRequest,
    db: Session = Depends(get_db),
):
    """手动改 review 状态。"""
    review = db.query(WikiReviewItem).filter_by(id=review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="review not found")
    if payload.status:
        review.status = payload.status
        if payload.status in ("resolved", "skipped", "dismissed"):
            review.resolved_at = datetime.utcnow()
    if payload.resolution_note:
        review.resolution_note = payload.resolution_note
    db.commit()
    return review
```

#### 5.8.2 Engine 侧 API 扩展

```python
# engine/app/api/wiki.py — 追加以下端点

@router.post("/extract_v2")
def extract_v2(request: WikiExtractRequest):
    """V2 两步 CoT 提取入口（feature flag 启用时使用）。"""
    from ..wiki.pipeline_v2 import run_extraction_v2
    
    threading.Thread(
        target=lambda: run_extraction_v2(request.doc_id, request.file_id),
        daemon=True,
    ).start()
    return {"doc_id": request.doc_id, "status": "processing", "version": "v2"}


@router.post("/graph/recompute")
def recompute_graph(user_id: str, full: bool = False):
    from ..wiki.graph.recompute import recompute_graph_for_user
    
    db = _Session()
    try:
        result = recompute_graph_for_user(db, user_id, full=full)
        return {"user_id": user_id, **result}
    finally:
        db.close()


@router.post("/search")
def kp_search(request: WikiSearchRequest):
    from ..wiki.retrieval.kp_search import hybrid_search_kp
    from ..wiki.retrieval.graph_expand import graph_expand_kp
    
    primary = hybrid_search_kp(
        request.user_id, request.query,
        top_k=request.top_k,
        use_vector=request.use_vector,
    )
    
    expanded = []
    if primary and request.expand_graph:
        seed_ids = [h["kp_id"] for h in primary[:3]]
        db = _Session()
        try:
            expanded_ranked = graph_expand_kp(
                db, seed_ids, hops=request.hops, top_per_hop=3,
            )
            ids = [kid for kid, _ in expanded_ranked[:request.top_k]]
            from backend.app.models.wiki import WikiKnowledgePoint
            kps = db.query(WikiKnowledgePoint).filter(
                WikiKnowledgePoint.id.in_(ids)
            ).all()
            id_to_kp = {kp.id: kp for kp in kps}
            expanded = [
                {
                    "kp_id": kid,
                    "slug": id_to_kp[kid].slug,
                    "title": id_to_kp[kid].title,
                    "score": score,
                }
                for kid, score in expanded_ranked
                if kid in id_to_kp
            ]
        finally:
            db.close()
    
    return {
        "mode": "hybrid" if request.use_vector else "keyword",
        "primary": primary,
        "graph_expanded": expanded,
    }


@router.post("/lint/run")
def lint_run(user_id: str, semantic: bool = False):
    from ..wiki.governance.lint import run_structural_lint, run_semantic_lint
    
    db = _Session()
    try:
        structural = run_structural_lint(db, user_id)
        semantic_findings = []
        if semantic:
            from ..llm.client import chat_client
            semantic_findings = run_semantic_lint(db, user_id, chat_client)
        return {
            "structural_count": len(structural),
            "semantic_count": len(semantic_findings),
        }
    finally:
        db.close()


@router.post("/dedup/detect")
def dedup_detect(user_id: str):
    from ..wiki.governance.dedup import detect_duplicate_groups
    from ..llm.client import chat_client
    
    db = _Session()
    try:
        groups = detect_duplicate_groups(db, user_id, chat_client)
        return {"candidate_count": len(groups), "groups": groups}
    finally:
        db.close()


@router.post("/dedup/merge")
def dedup_merge(payload: DedupMergeRequest):
    from ..wiki.governance.dedup import merge_duplicate
    from ..llm.client import chat_client
    
    db = _Session()
    try:
        result = merge_duplicate(
            db, payload.candidate_id, payload.canonical_id, chat_client,
        )
        return result
    finally:
        db.close()


@router.post("/sweep")
def sweep(user_id: str):
    from ..wiki.governance.sweep import sweep_pending_reviews
    from ..llm.client import chat_client
    
    db = _Session()
    try:
        result = sweep_pending_reviews(db, user_id, chat_client)
        return result
    finally:
        db.close()
```


### 5.9 前端改造

前端在现有 4 个 wiki 页面（`WikiPage / WikiUploadPage / WikiDocDetail / WikiPointDetail`）基础上新增 3 个面板，**仅增不改**。

#### 5.9.1 新增页面

| 路由 | 文件 | 内容 |
|------|------|------|
| `/wiki/graph` | `frontend/src/pages/WikiGraphPage.tsx` | sigma.js 知识图谱可视化 |
| `/wiki/lint` | `frontend/src/pages/WikiLintPanel.tsx` | Lint findings 列表 + 一键修复 |
| `/wiki/dedup` | `frontend/src/pages/WikiDedupPanel.tsx` | 去重候选确认 |
| `/wiki/reviews` | `frontend/src/pages/WikiReviewPanel.tsx` | Review 队列管理 |

#### 5.9.2 `WikiGraphPage.tsx` 关键设计

参考 LLM Wiki `src/components/graph/graph-view.tsx`（D3 + sigma.js）的实现思路：

```tsx
// frontend/src/pages/WikiGraphPage.tsx

import { useEffect, useRef, useState } from 'react'
import Graph from 'graphology'
import Sigma from 'sigma'
import forceAtlas2 from 'graphology-layout-forceatlas2'

import { fetchWikiGraph } from '@/app/api'

type ColorMode = 'type' | 'community'

const TYPE_COLORS: Record<string, string> = {
  entity: '#5B8FF9',
  concept: '#5AD8A6',
  finding: '#F6BD16',
  synthesis: '#7262FD',
  comparison: '#FF9D4D',
}

const COMMUNITY_PALETTE = [
  '#5B8FF9', '#5AD8A6', '#F6BD16', '#7262FD',
  '#FF9D4D', '#E86452', '#6DC8EC', '#945FB9',
  '#FF99C3', '#1E9493', '#FF6B3B', '#FFC845',
]

export function WikiGraphPage() {
  const containerRef = useRef<HTMLDivElement>(null)
  const sigmaRef = useRef<Sigma | null>(null)
  const [colorMode, setColorMode] = useState<ColorMode>('type')
  const [highlightId, setHighlightId] = useState<string | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    let mounted = true
    fetchWikiGraph().then((data) => {
      if (!mounted) return
      const g = new Graph({ multi: false })
      
      // 节点
      data.nodes.forEach((n) => {
        const color = colorMode === 'type'
          ? TYPE_COLORS[n.page_type] ?? '#999'
          : COMMUNITY_PALETTE[(n.community ?? 0) % COMMUNITY_PALETTE.length]
        g.addNode(n.id, {
          label: n.title,
          size: 4 + Math.sqrt(n.in_count + n.out_count),
          color,
          slug: n.slug,
          page_type: n.page_type,
          community: n.community,
        })
      })
      
      // 边
      data.edges.forEach((e) => {
        const w = e.weight ?? 1
        const color = w > 5 ? '#3DA86E' : w > 2 ? '#999' : '#DDD'
        try {
          g.addEdge(e.source, e.target, {
            weight: w,
            size: Math.min(0.5 + w / 4, 4),
            color,
            type: e.type,
            origin: e.origin,
          })
        } catch { /* 重复边 */ }
      })
      
      // ForceAtlas2 布局
      forceAtlas2.assign(g, {
        iterations: 100,
        settings: { gravity: 1, scalingRatio: 8, slowDown: 5 },
      })
      
      // Sigma 渲染
      if (sigmaRef.current) sigmaRef.current.kill()
      sigmaRef.current = new Sigma(g, containerRef.current!, {
        renderEdgeLabels: false,
        labelSize: 12,
        labelDensity: 0.07,
      })
      
      // hover 高亮
      sigmaRef.current.on('enterNode', ({ node }) => setHighlightId(node))
      sigmaRef.current.on('leaveNode', () => setHighlightId(null))
      sigmaRef.current.on('clickNode', ({ node }) => {
        const slug = g.getNodeAttribute(node, 'slug')
        window.location.href = `/wiki/points/${node}`
      })
    })
    
    return () => {
      mounted = false
      sigmaRef.current?.kill()
    }
  }, [colorMode])

  return (
    <div className="flex flex-col h-screen">
      <div className="flex gap-4 p-4 border-b">
        <button
          onClick={() => setColorMode('type')}
          className={colorMode === 'type' ? 'btn-primary' : 'btn'}
        >
          按类型着色
        </button>
        <button
          onClick={() => setColorMode('community')}
          className={colorMode === 'community' ? 'btn-primary' : 'btn'}
        >
          按社区着色
        </button>
      </div>
      <div ref={containerRef} className="flex-1" />
    </div>
  )
}
```

#### 5.9.3 治理面板（Lint / Dedup / Review）

复用同一个面板布局组件 `<GovernancePanel>`，三个具体页面只填充各自的 column 配置：

```tsx
// frontend/src/pages/WikiLintPanel.tsx

import { useEffect, useState } from 'react'
import { fetchLintFindings, applyLintFix, triggerLintRun } from '@/app/api'

type LintFinding = {
  id: string
  type: string
  severity: 'warning' | 'info'
  point_id: string | null
  detail: string
  broken_target?: string
  suggested_target_slug?: string
  status: string
}

export function WikiLintPanel() {
  const [findings, setFindings] = useState<LintFinding[]>([])
  const [loading, setLoading] = useState(false)

  const refresh = () => {
    setLoading(true)
    fetchLintFindings().then(setFindings).finally(() => setLoading(false))
  }
  useEffect(refresh, [])

  return (
    <div className="p-6">
      <div className="flex justify-between mb-4">
        <h1 className="text-xl">Wiki 健康检查</h1>
        <div className="flex gap-2">
          <button onClick={() => triggerLintRun(false).then(refresh)}>
            运行结构 Lint
          </button>
          <button onClick={() => triggerLintRun(true).then(refresh)}>
            运行语义 Lint (LLM)
          </button>
        </div>
      </div>
      {loading && <div>加载中...</div>}
      <div className="space-y-2">
        {findings.map((f) => (
          <div key={f.id} className={`border rounded p-3 ${f.severity === 'warning' ? 'border-orange-300' : 'border-gray-200'}`}>
            <div className="flex justify-between">
              <div>
                <span className="font-bold">{f.type}</span>
                <span className="ml-2 text-sm text-gray-500">{f.severity}</span>
              </div>
              <button onClick={() => applyLintFix(f.id).then(refresh)}>
                修复
              </button>
            </div>
            <div className="mt-1">{f.detail}</div>
            {f.broken_target && f.suggested_target_slug && (
              <div className="text-sm text-gray-600 mt-1">
                建议：[[{f.broken_target}]] → [[{f.suggested_target_slug}]]
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
```

`WikiDedupPanel.tsx` 和 `WikiReviewPanel.tsx` 同构，只是字段不同。

#### 5.9.4 路由扩展

```tsx
// frontend/src/app/routes.tsx — 在现有 children 数组里追加

{ path: 'wiki/graph', element: <WikiGraphPage /> },
{ path: 'wiki/lint', element: <WikiLintPanel /> },
{ path: 'wiki/dedup', element: <WikiDedupPanel /> },
{ path: 'wiki/reviews', element: <WikiReviewPanel /> },
```

#### 5.9.5 API 客户端扩展

```ts
// frontend/src/app/api.ts — 追加

export async function fetchWikiGraph(): Promise<{
  nodes: GraphNode[]
  edges: GraphEdge[]
}> {
  return apiGet('/api/v1/wiki/graph')
}

export async function fetchLintFindings(status = 'open'): Promise<LintFinding[]> {
  return apiGet(`/api/v1/wiki/lint?status=${status}`)
}

export async function triggerLintRun(semantic: boolean) {
  return apiPost('/api/v1/wiki/lint/run', { semantic })
}

export async function applyLintFix(id: string) {
  return apiPost(`/api/v1/wiki/lint/${id}/fix`)
}

export async function fetchDedupCandidates(): Promise<DedupCandidate[]> {
  return apiGet('/api/v1/wiki/dedup?status=pending')
}

export async function triggerDedupDetect() {
  return apiPost('/api/v1/wiki/dedup/detect')
}

export async function mergeDedup(candidateId: string, canonicalId: string) {
  return apiPost(`/api/v1/wiki/dedup/${candidateId}/merge?canonical_id=${canonicalId}`)
}

export async function fetchReviews(status = 'pending'): Promise<ReviewItem[]> {
  return apiGet(`/api/v1/wiki/reviews?status=${status}`)
}

export async function triggerReviewSweep() {
  return apiPost('/api/v1/wiki/reviews/sweep')
}
```


---

## 6. 改造收益与可观测指标

### 6.1 收益概览

| 维度 | 现状 | 改造后 | 量化目标 |
|---|---|---|---|
| **跨 chunk 实体合并** | 同名精确匹配 | LLM 全局视野，自动合并 | 同实体碎片数 ↓50% |
| **跨文档关系** | 几乎为 0 | source overlap × 4.0 自动建立 | 跨文档 relation 占比 ≥20% |
| **每文档 LLM 调用** | 1 + N_chunk + N_kp | 1 + 1（长文 1+3） | token 成本 ↓60% |
| **重传同文档** | 检查 KP 部分跳过 | SHA256 命中完全跳过 | 重传成本 → 0 |
| **关系强度可解释性** | 单一 confidence | 4 信号分量 + total | 可解释 100% |
| **概念性问题回答质量** | chunk 拼凑 | KP 直接命中 + 图扩展 | top-3 准确率 +15pp |
| **知识网络可视化** | 无 | sigma.js 图视图 | 全图渲染 ≤2s |
| **治理覆盖** | 无 | lint/dedup/sweep 三件套 | 健康度 SQL 可查 |

### 6.2 详细指标定义

所有指标按 user_id 维度聚合，写入 `wiki_extraction_log` 或新增 `wiki_metrics` 表。

#### 6.2.1 Pipeline 质量指标

| 指标 | 定义 | 目标 | 采集 |
|---|---|---|---|
| `pipeline_v2.success_rate` | V2 成功 ingest 数 / 总触发数 | ≥95% | engine log + sql |
| `pipeline_v2.parse_warnings_per_run` | 平均每次 ingest 的 parse warnings | ≤2 | parser 输出 |
| `pipeline_v2.kp_count_per_doc` | 每文档生成的 KP 数 | 5-15（中等文档） | sql count |
| `pipeline_v2.cache_hit_rate` | SHA256 命中率 / 总触发数 | ≥30% | engine log |
| `pipeline_v2.llm_call_count_per_doc` | 平均 LLM 调用数 | 短文 2、长文 ≤5 | engine log |
| `pipeline_v2.token_cost_per_doc` | 平均 token 消耗 | 短文 ≤8K、长文 ≤30K | engine log |
| `pipeline_v2.fallback_rate` | 走旧管线的次数 / 总触发数 | ≤5% | feature flag log |

#### 6.2.2 关系层指标

| 指标 | 定义 | 目标 | 采集 |
|---|---|---|---|
| `relation.wikilink_origin_pct` | origin=wikilink 的 relation 占比 | ≥40% | sql aggregate |
| `relation.cross_doc_pct` | 跨 wiki_document 的 relation 占比 | ≥20% | sql + 图 |
| `relation.avg_weight_total` | 平均 weight_total | 因数据而定，监控趋势 | sql avg |
| `relation.adamic_adar_contribution` | weight_neighbor / weight_total 比值 | 监控分布 | sql |
| `kp.avg_in_links` | KP 平均入链数 | ≥1.5（健康图） | sql |
| `kp.orphan_rate` | 孤立 KP 占比 | ≤15% | lint finding |
| `kp.broken_link_rate` | 悬空 wikilink 占比 | ≤5% | lint finding |

#### 6.2.3 检索层指标

| 指标 | 定义 | 目标 | 采集 |
|---|---|---|---|
| `kp_search.hit_rate` | KP 命中数 ≥1 的请求占比 | ≥85%（已建库） | engine log |
| `kp_search.avg_latency_ms` | 平均检索耗时 | ≤300ms | engine log |
| `graph_expand.avg_expansion_size` | 图扩展平均节点数 | 3-8 | engine log |
| `agentic_rag.iter_count` | 平均 RAG 迭代次数 | ≤2（KP 介入后下降） | runner log |
| `agentic_rag.kp_tool_call_rate` | wiki_search 被调用的请求占比 | 监控趋势 | runner log |

#### 6.2.4 治理指标

| 指标 | 定义 | 目标 | 采集 |
|---|---|---|---|
| `lint.findings_per_user` | 每 user 的 open finding 数 | 监控趋势 | sql |
| `lint.broken_link_count` | broken-link 总数 | 周下降 | sql |
| `dedup.candidate_per_run` | 每次 detect 产出的候选组数 | 监控 | engine log |
| `dedup.merge_acceptance_rate` | 用户接受 merge 的占比 | ≥60%（confidence high） | sql |
| `review.sweep_resolved_rate` | sweep 自动消解占比 | ≥40% | sweep log |
| `review.pending_count` | 待处理 review 总数 | 监控趋势 | sql |

#### 6.2.5 评估方法

**回归测试集**：在 `engine/eval/` 下扩展现有结构，新增：
- `engine/eval/wiki_v2_dataset.json` — 20-50 个文档 ingest 用例
- `engine/eval/wiki_v2_eval.py` — 比较 V1 / V2 在同一文档上的 KP 数、关系数、token 消耗
- `engine/eval/wiki_search_eval.py` — KP 检索 hit_rate、MRR、NDCG@5

**A/B 对比方法**：
1. 同一文档分别用 V1 / V2 跑（feature flag 控制）
2. 抽 10% KP 让人工打分（准确性、完整性、关联性）
3. 同一组 query 分别命中 chunk RAG / KP RAG，比较答案质量

### 6.3 可扩展场景

改造完成后，wiki 引擎可以独立支持以下场景：

1. **个人 Agent 知识库**（已规划）
   - Prism Agent 通过 `wiki_search` 工具查询沉淀知识
   - 多 topic 隔离支持工作 / 个人不同上下文

2. **团队知识库**（轻改造）
   - `user_id` 改为 `team_id`，加 ACL 表
   - 加 `wiki_kp_acl` 控制谁能读 / 写
   - 多人上传，dedup 候选组进入审核流

3. **企业内部 RAG 服务**（中改造）
   - 把 Engine 抽出独立部署
   - 加 API token 鉴权（参考 LLM Wiki `src/lib/api-token.ts`）
   - 提供 MCP server 给 Claude Code / Codex

4. **跨组织知识联邦**（重改造）
   - 多 wiki 实例，每个实例独立 user_id 命名空间
   - 通过 mcp 互相检索（read-only）
   - 关系层不跨实例（避免隐私边界问题）

5. **行业知识库 SaaS**（重改造）
   - 多租户 + 配额管理
   - 不同租户用不同 schema_definition
   - 提供 page_type 自定义能力（行业特化）

6. **离线 Agent 知识下载**
   - 导出整个 user 的 KP 为 markdown 文件树
   - 兼容 Obsidian 格式（YAML frontmatter + [[wikilink]]）
   - 用户随身携带 wiki 副本


---

## 7. 风险与缓解

### 7.1 高风险项

#### 7.1.1 DeepSeek prompt 格式偏离

**风险**：DeepSeek 偶尔输出 `以下是文件:` 等前言，破坏 `第一字符必须是 -` 约束。

**缓解**：
- 解析器对前言宽容（lstrip 后再校验）
- prompt 末尾重复 `---END FILE---` 后无任何输出 的指令
- 失败重试机制：解析为 0 个 FILE block 时，调一次 `aggregate_repair` 单独重生成

#### 7.1.2 长文档 token 爆炸

**风险**：超过 32K token 的文档单次 generation 会被 DeepSeek 截断。

**缓解**：
- Stage 1 长文走 chunk 分析 + 滚动摘要（移植 `src/lib/ingest.ts` 的 `splitSourceIntoSemanticChunks` + `analyzeLongSourceInChunks`）
- Stage 2 每个 chunk 独立生成，最后 dedup
- `ENGINE_MAX_SOURCE_TOKENS=32000` 配置硬上限

#### 7.1.3 数据迁移失败

**风险**：现有 KP 缺 slug 字段，批量回填可能产生重复 slug 冲突。

**缓解**：
- migration 脚本采用 `make_slug + 序号后缀` 解冲突（如 `concept-foo-2`）
- migration 干跑 mode：先打印冲突列表给用户确认
- 整个 migration 在事务内，失败回滚

#### 7.1.4 Milvus / ES 资源消耗

**风险**：KP 数量上去后，新增 collection / index 占用资源。

**缓解**：
- KP 向量化按 user_id 分 partition（Milvus 原生支持）
- ES index 按 user_id 加 routing
- 设置 `KP_EMBEDDING_BATCH_SIZE=32`，避免大批量挂死

### 7.2 中风险项

#### 7.2.1 图重算性能

**风险**：用户 KP 数 >5K 时，全图 4 信号计算可能慢。

**缓解**：
- NetworkX 在 5K 节点级别毫秒级，无问题
- 边权重写回可批量（`bulk_update_mappings`）
- Louvain 全量计算每周一次，不在 ingest 路径

#### 7.2.2 LLM 合并正文质量

**风险**：dedup merge 让 LLM 合并多版本正文，可能丢失事实。

**缓解**：
- LLM merge prompt 要求"保留所有数字、阈值、角色名"
- 合并前后做 token 数对比，下降 >30% 报警
- 保留旧 KP 内容快照在 `wiki_dedup_candidate.point_ids` JSON 里供回滚

### 7.3 低风险项

- 前端图视图依赖新增 sigma.js / graphology 库（包大小 ~150KB）
- `python-louvain` 依赖（~50KB pure Python）
- `networkx` 依赖（已普遍存在）

---

## 8. 关键参考索引（LLM Wiki 源码路径）

Claude Code 在实施时可通过 `Read` 工具直接读取以下绝对路径，作为对译参考。所有路径在 H:\Agent\Project\llm_wiki 项目中已验证存在。

> **行号注记**：以下行号基于 LLM Wiki 仓库 commit 时的状态。如读到的内容与名字不符，请通过 `Select-String -Path "<file>" -Pattern "^(export )?(async )?function <name>"` 重新定位。**优先以函数名为准**。

### 8.1 Pipeline 主流程

| 主题 | LLM Wiki 路径 | 函数名 / 起始行 |
|------|---------------|----------------|
| Ingest 入口 | `src/lib/ingest.ts` | `autoIngest` (export, 471) |
| Ingest 实现 | `src/lib/ingest.ts` | `autoIngestImpl` (483) |
| Analysis prompt | `src/lib/ingest.ts` | `buildAnalysisPrompt` (export, 1702) |
| Generation prompt | `src/lib/ingest.ts` | `buildGenerationPrompt` (export, 1753) |
| FILE 块正则 | `src/lib/ingest.ts` | `FILE_BLOCK_REGEX` (export, 240) |
| FILE 块解析 | `src/lib/ingest.ts` | `parseFileBlocks` (export, 356) |
| Path 安全 | `src/lib/ingest.ts` | `isSafeIngestPath` (export, 290) |
| REVIEW 块解析 | `src/lib/ingest.ts` | `parseReviewBlocks` (private, 1625) |
| 长文切分 | `src/lib/ingest.ts` | `splitSourceIntoSemanticChunks` (export, 2165) |
| 增量缓存 | `src/lib/ingest-cache.ts` | 整文件 |
| 输出清洗 | `src/lib/ingest-sanitize.ts` | 整文件 |
| Frontmatter parse/write | `src/lib/frontmatter.ts` | 整文件 |
| 页面合并（多源 upsert） | `src/lib/page-merge.ts` | `mergePageContent` |
| Source identity | `src/lib/source-identity.ts` | 整文件（注：LLM Wiki 用文件路径，Prism 用 `wiki_document.id`，仅作概念参考） |
| 队列（仅参考概念，Prism 用 wiki_document.status） | `src/lib/ingest-queue.ts` | 整文件 |

### 8.2 关系与图

| 主题 | LLM Wiki 路径 | 函数名 / 起始行 |
|------|---------------|----------------|
| Wikilink 正则 | `src/lib/wiki-graph.ts` | `WIKILINK_REGEX` (115) |
| extractWikilinks | `src/lib/wiki-graph.ts` | `extractWikilinks` (145) |
| resolveTarget（模糊匹配） | `src/lib/wiki-graph.ts` | `resolveTarget` (private，在 buildWikiGraph 之后) |
| 4 信号权重常量 | `src/lib/graph-relevance.ts` | `WEIGHTS` (30) + `TYPE_AFFINITY` (37) |
| calculateRelevance | `src/lib/graph-relevance.ts` | `calculateRelevance` (export, 247) |
| 图构建 | `src/lib/wiki-graph.ts` | `buildWikiGraph` (export, 159) |
| Louvain 社区检测 | `src/lib/wiki-graph.ts` | `detectCommunities` (private, 31) |
| Insights | `src/lib/graph-insights.ts` | 整文件 |

### 8.3 治理

| 主题 | LLM Wiki 路径 | 函数名 / 起始行 |
|------|---------------|----------------|
| Structural lint | `src/lib/lint.ts` | `runStructuralLint` (export, 150) |
| Semantic lint | `src/lib/lint.ts` | `runSemanticLint` (export, 305) |
| Lint 修复 | `src/lib/lint-fixes.ts` | 整文件 |
| Dedup（三阶段） | `src/lib/dedup.ts` | `extractEntitySummary` / `detectDuplicateGroups` / `mergeDuplicateGroup` |
| Sweep（review 自动消解） | `src/lib/sweep-reviews.ts` | 整文件 |
| Cascade delete | `src/lib/wiki-page-delete.ts` | 整文件 |
| Enrich wikilinks（防破坏补链） | `src/lib/enrich-wikilinks.ts` | 整文件 |

### 8.4 检索

| 主题 | LLM Wiki 路径 | 备注 |
|------|---------------|------|
| 主入口 | `src/lib/search.ts` | TS 端总分发 |
| 后端混合检索 | `src-tauri/src/search.rs` | Rust 实现，参考思路 |

### 8.5 前端图视图（参考实现）

| 主题 | LLM Wiki 路径 |
|------|---------------|
| 图视图主组件 | `src/components/graph/graph-view.tsx` |
| 图布局 worker | `src/components/graph/graph-layout-worker.ts` |
| 图过滤 | `src/lib/graph-filters.ts` |
| 图可见性 | `src/lib/graph-visibility.ts` |

### 8.6 设计原则文档

| 文档 | 路径 |
|------|------|
| LLM Wiki 设计哲学 | `H:\Agent\Project\llm_wiki\llm-wiki.md` |
| 关系系统设计 | `H:\Agent\Project\llm_wiki\wiki-relationship-design.md` |
| 项目 README | `H:\Agent\Project\llm_wiki\README.md` |

---

## 9. 后续工作（不在本次改造范围）

以下内容留给后续迭代：

1. **Purpose / Schema 自由化**（阶段 5+）
   - 在 `knowledge_topic` 加 `purpose` / `schema_definition`
   - 上传时根据 topic schema 动态生成 page_type 枚举
   - LLM Wiki 的 `purpose.md` 等价物

2. **Deep Research 集成**
   - REVIEW.search_queries 触发 web 搜索
   - 搜索结果 auto-ingest 回 wiki
   - 形成 review → research → ingest 闭环

3. **多模态 / 图片 caption**
   - 复用现有 `wiki_image` 表
   - 在 KP 正文中嵌入图片引用
   - 视觉 LLM 生成 alt-text

4. **Obsidian 兼容导出**
   - 把 user wiki 导出为 markdown 文件树
   - 包含 [[wikilink]] + frontmatter
   - 支持版本快照

5. **MCP Server 暴露**
   - 把 wiki API 包装成 MCP server
   - Claude Code / Codex 可通过 npx skills 接入

6. **Skill / Agent 工具增强**
   - `wiki_overview` 工具：返回 wiki/index.md 等价物
   - `wiki_create_kp` 工具：让 agent 主动创建 KP
   - `wiki_diff` 工具：查询 KP 变更历史

---

## 文档结束

> 本设计文档配套实施计划：`docs/superpowers/plans/2026-06-16-wiki-engine-refactor.md`
> 实施过程中如发现设计需要调整，请同时更新此文档与实施计划，保持一致。
