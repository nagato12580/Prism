# Wiki 引擎重构 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Prism 现有的「概念抽取 → group 合并 → 文章生成」三阶段管线重构成 LLM Wiki 风格的「Analysis → Generation」两步 CoT 管线，引入 wikilink + 4 信号关系图、KP 级 RAG 检索、治理三件套。

**Architecture:** 见 `docs/superpowers/specs/2026-06-16-wiki-engine-refactor-design.md`

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic + React + Zustand + httpx + DeepSeek (OpenAI 兼容) + NetworkX + python-louvain + sigma.js + graphology

**Source Spec:** `docs/superpowers/specs/2026-06-16-wiki-engine-refactor-design.md`

**Reference Code:** `H:\Agent\Project\llm_wiki\src\lib\` (LLM Wiki TypeScript 实现，作为对译参考)

**Working Branch:** `feature/wiki-engine-v2`

---

## 阶段总览

| 阶段 | 目标 | 工作量 | 收益 |
|------|------|--------|------|
| 阶段 1 | 数据模型 + 解析层（无副作用基础设施） | 4-5 天 | 单元测试覆盖核心契约 |
| 阶段 2 | 两步 CoT 管线 + DeepSeek 适配 | 5-7 天 | 替换三阶段，token 成本下降 |
| 阶段 3 | KP 级 RAG 检索 + 4 信号图 + Agent Tool | 5-7 天 | 改善概念性问题回答质量 |
| 阶段 4 | 治理三件套（Lint / Dedup / Sweep） | 4-5 天 | 长期 wiki 健康度 |
| 阶段 5 | 前端图视图 + 治理 UI + Louvain 社区 | 5-7 天 | 完整用户体验 |

**总工作量**：约 4-5 周（全职推进）

**风险节点**：
- 阶段 2：DeepSeek prompt 适配（需要 A/B 验证）
- 阶段 1：数据迁移（slug 回填可能产生冲突）

---

## File Map（汇总）

### 新建文件（约 25 个）

#### 阶段 1
| 文件 | 职责 |
|------|------|
| `engine/app/wiki/slug.py` | title → kebab-case slug |
| `engine/app/wiki/parsers.py` | parse_file_blocks / parse_review_blocks |
| `engine/app/wiki/wikilink.py` | extract / resolve / rewrite |
| `engine/app/wiki/cache.py` | SHA256 增量缓存 |
| `engine/app/wiki/feature_flags.py` | WIKI_PIPELINE_V2 切换 |
| `engine/app/wiki/language.py` | 语言守卫 |
| `engine/tests/wiki/test_slug.py` | slug 单元测试 |
| `engine/tests/wiki/test_parsers.py` | 解析器单元测试 |
| `engine/tests/wiki/test_wikilink.py` | wikilink 单元测试 |

#### 阶段 2
| 文件 | 职责 |
|------|------|
| `engine/app/wiki/pipeline_v2.py` | 两步 CoT 主流程 |
| `engine/app/wiki/persist.py` | KP / Relation / Review 写入 |
| `engine/app/wiki/merge.py` | LLM 合并多源 KP 正文（对译 LLM Wiki `src/lib/page-merge.ts` 的 `mergePageContent`） |
| `engine/app/wiki/chunker.py` | 长文切分（抽自旧 extraction_engine） |
| `engine/tests/wiki/test_pipeline_v2.py` | 管线集成测试 |
| `engine/eval/wiki_v2_dataset.json` | 回归数据集 |
| `engine/eval/wiki_v2_eval.py` | V1/V2 对比脚本 |
| `docs/superpowers/specs/2026-06-16-wiki-engine-deepseek-tuning.md` | DeepSeek 调试经验 |

#### 阶段 3
| 文件 | 职责 |
|------|------|
| `engine/app/wiki/graph/__init__.py` | 包标记 |
| `engine/app/wiki/graph/relevance.py` | 4 信号权重 |
| `engine/app/wiki/graph/builder.py` | 从 DB 构图 |
| `engine/app/wiki/graph/recompute.py` | 重算调度 |
| `engine/app/wiki/retrieval/__init__.py` | 包标记 |
| `engine/app/wiki/retrieval/setup.py` | Milvus collection / ES index 创建 |
| `engine/app/wiki/retrieval/kp_search.py` | KP 级 hybrid 检索 |
| `engine/app/wiki/retrieval/graph_expand.py` | 图扩展 |
| `engine/app/agent/tools/wiki.py` | wiki_search agent tool |
| `engine/tests/wiki/test_relevance.py` | 4 信号单元测试 |
| `engine/tests/wiki/test_graph_builder.py` | 图构建测试 |
| `engine/tests/wiki/test_kp_search.py` | KP 检索测试 |

#### 阶段 4
| 文件 | 职责 |
|------|------|
| `engine/app/wiki/governance/__init__.py` | 包标记 |
| `engine/app/wiki/governance/lint.py` | structural + semantic lint |
| `engine/app/wiki/governance/dedup.py` | LLM 软碰撞检测 + 合并 |
| `engine/app/wiki/governance/sweep.py` | review 自动消解 |
| `engine/app/wiki/governance/fix.py` | lint 修复执行 |
| `engine/tests/wiki/test_lint.py` | lint 单元测试 |
| `engine/tests/wiki/test_dedup.py` | dedup 单元测试 |

#### 阶段 5
| 文件 | 职责 |
|------|------|
| `engine/app/wiki/graph/community.py` | Louvain |
| `engine/app/wiki/graph/insights.py` | surprising / gaps |
| `frontend/src/pages/WikiGraphPage.tsx` | 图视图 |
| `frontend/src/pages/WikiLintPanel.tsx` | Lint 管理面板 |
| `frontend/src/pages/WikiDedupPanel.tsx` | Dedup 候选管理 |
| `frontend/src/pages/WikiReviewPanel.tsx` | Review 队列管理 |
| `frontend/src/components/wiki/GraphRenderer.tsx` | sigma.js 封装组件 |

### 修改文件（约 12 个）

| 文件 | 改动 |
|------|------|
| `backend/app/models/wiki.py` | KP / Relation 加字段，新增 3 张治理表 |
| `backend/app/schemas/wiki.py` | 新增 graph / lint / dedup / review 的 schema |
| `backend/app/api/wiki.py` | 新增 graph / lint / dedup / review / search 端点 |
| `backend/app/utils/auto_migrate.py` | 追加新表 + 新字段，加 slug 回填脚本 |
| `engine/app/api/wiki.py` | 新增 extract_v2 / search / lint / dedup / sweep 端点 |
| `engine/app/wiki/prompts.py` | 新增 build_analysis_prompt / build_generation_prompt |
| `engine/app/wiki/extraction_engine.py` | 加 feature flag 入口（保留旧管线） |
| `engine/app/agent/tools/__init__.py` | 注册 wiki_search 工具 |
| `engine/app/config.py` | 加 WIKI_PIPELINE_V2 / KP 检索相关配置 |
| `frontend/src/app/api.ts` | 新增 graph / lint / dedup / review API 调用 |
| `frontend/src/app/routes.tsx` | 追加 4 条新路由 |
| `frontend/src/app/wikiStore.ts` | 加 graph / lint / dedup / review 状态 |


---

## 阶段 1: 数据模型 + 解析层（4-5 天）

**目标**：建立无副作用基础设施，为后续管线改造铺路。这一阶段的代码全部可以单元测试，不依赖 LLM。

**前置**：
- 切到 `feature/wiki-engine-v2` 分支
- 阅读参考文档：
  - `docs/superpowers/specs/2026-06-16-wiki-engine-refactor-design.md` 第 4-5 节
  - LLM Wiki 源码：`H:\Agent\Project\llm_wiki\src\lib\ingest.ts`（`parseFileBlocks` / `parseReviewBlocks`）
  - LLM Wiki 源码：`H:\Agent\Project\llm_wiki\src\lib\wiki-graph.ts`（`extractWikilinks` / `resolveTarget`）

### Task 1.1: 数据模型扩展

**Files:**
- Modify: `backend/app/models/wiki.py`
- Modify: `backend/app/utils/auto_migrate.py`

- [ ] **Step 1**: 在 `WikiKnowledgePoint` 类追加新字段
  
  按设计文档 §4.1.1 添加：
  - `slug` (String 255, indexed, **暂不加 UniqueConstraint，见 Step 4 migration 顺序说明**)
  - `page_type` (String 32, indexed, default "concept")
  - `related_slugs` (JSON, default list)
  - `source_doc_ids` (JSON, default list)
  - `in_link_count` / `out_link_count` (Integer, default 0)
  - `community_id` (Integer, nullable, indexed)
  - `content_hash` (String 64, indexed)
  - `last_extracted_at` (DateTime)
  - `__table_args__` 里 **不要** 在模型类里直接加 `UniqueConstraint("user_id", "slug")`，在 migration Step C 完成回填后再通过 DDL 单独加

- [ ] **Step 2**: 在 `WikiKnowledgeRelation` 类追加新字段
  
  按设计文档 §4.1.2 添加：
  - `origin` (String 16, default "llm", indexed)
  - `weight_total / weight_direct / weight_source / weight_neighbor / weight_type` (Float, default 0.0)
  - `last_computed_at` (DateTime)
  - `__table_args__` 加复合唯一约束（from/to/type/origin 四元组）

- [ ] **Step 3**: 新增 3 张治理表
  
  按设计文档 §4.2 添加：
  - `WikiReviewItem` 类
  - `WikiLintFinding` 类
  - `WikiDedupCandidate` 类

- [ ] **Step 4**: 在 `auto_migrate.py` 实现三步 migration（**顺序不可颠倒**）
  
  > ⚠️ **必须按 A → B → C 顺序**：先加字段，再回填，再加唯一约束。
  > 如果先加约束再回填，冲突时 MySQL 会报 IntegrityError 导致部分 KP slug 为 NULL，
  > 进入不一致状态且难以恢复。
  
  ```python
  # backend/app/utils/auto_migrate.py — 追加以下迁移逻辑
  
  def migrate_wiki_v2(engine):
      """三步 wiki_v2 migration。幂等：重复执行安全。"""
      with engine.begin() as conn:
          # ── Step A: 加字段（允许 NULL，无约束） ─────────────
          _add_column_if_missing(conn, "wiki_knowledge_point", "slug",
                                  "VARCHAR(255) DEFAULT NULL")
          _add_column_if_missing(conn, "wiki_knowledge_point", "page_type",
                                  "VARCHAR(32) NOT NULL DEFAULT 'concept'")
          _add_column_if_missing(conn, "wiki_knowledge_point", "related_slugs",
                                  "JSON NULL")
          _add_column_if_missing(conn, "wiki_knowledge_point", "source_doc_ids",
                                  "JSON NULL")
          _add_column_if_missing(conn, "wiki_knowledge_point", "in_link_count",
                                  "INT NOT NULL DEFAULT 0")
          _add_column_if_missing(conn, "wiki_knowledge_point", "out_link_count",
                                  "INT NOT NULL DEFAULT 0")
          _add_column_if_missing(conn, "wiki_knowledge_point", "community_id",
                                  "INT NULL")
          _add_column_if_missing(conn, "wiki_knowledge_point", "content_hash",
                                  "VARCHAR(64) NULL")
          _add_column_if_missing(conn, "wiki_knowledge_point", "last_extracted_at",
                                  "DATETIME NULL")
          # WikiKnowledgeRelation
          _add_column_if_missing(conn, "wiki_knowledge_relation", "origin",
                                  "VARCHAR(16) NOT NULL DEFAULT 'llm'")
          for col in ["weight_total", "weight_direct", "weight_source",
                      "weight_neighbor", "weight_type"]:
              _add_column_if_missing(conn, "wiki_knowledge_relation", col,
                                      "FLOAT NOT NULL DEFAULT 0.0")
          _add_column_if_missing(conn, "wiki_knowledge_relation", "last_computed_at",
                                  "DATETIME NULL")
          
          # ── Step B: 回填 slug（必须在加约束前完成） ──────────
          _backfill_slugs(conn)
          
          # ── Step C: 加唯一约束（回填完成后才能安全执行） ─────
          _add_unique_if_missing(conn, "wiki_knowledge_point",
                                  "uq_wiki_kp_user_slug",
                                  "user_id, slug")
          _add_unique_if_missing(conn, "wiki_knowledge_relation",
                                  "uq_wiki_rel_from_to_type_origin",
                                  "from_point_id, to_point_id, type, origin")
          
          # ── 新表 ───────────────────────────────────────────
          _create_table_if_missing(conn, "wiki_review_item", WIKI_REVIEW_ITEM_DDL)
          _create_table_if_missing(conn, "wiki_lint_finding", WIKI_LINT_FINDING_DDL)
          _create_table_if_missing(conn, "wiki_dedup_candidate", WIKI_DEDUP_CANDIDATE_DDL)
          
          # ── §4.3 索引 ───────────────────────────────────────
          _add_index_if_missing(conn, "wiki_knowledge_point",
                                 "idx_wiki_kp_user_type", "user_id, page_type")
          _add_index_if_missing(conn, "wiki_knowledge_point",
                                 "idx_wiki_kp_content_hash", "content_hash")
          _add_index_if_missing(conn, "wiki_knowledge_relation",
                                 "idx_wiki_rel_origin_weight", "origin, weight_total")
          _add_index_if_missing(conn, "wiki_review_item",
                                 "idx_wiki_review_user_status", "user_id, status")
          _add_index_if_missing(conn, "wiki_lint_finding",
                                 "idx_wiki_lint_user_status", "user_id, status, type")
  
  
  def _backfill_slugs(conn):
      """回填 wiki_knowledge_point.slug（幂等）。"""
      from engine.app.wiki.slug import make_slug
      
      rows = conn.execute(
          "SELECT id, user_id, title FROM wiki_knowledge_point WHERE slug IS NULL"
      ).fetchall()
      
      # 按 (user_id, slug) 做冲突计数
      existing_slugs: dict[str, set[str]] = {}
      for row in conn.execute(
          "SELECT user_id, slug FROM wiki_knowledge_point WHERE slug IS NOT NULL"
      ).fetchall():
          existing_slugs.setdefault(row.user_id, set()).add(row.slug)
      
      updates = []
      for row in rows:
          base = make_slug(row.title or "untitled")
          slug = base
          counter = 2
          user_slugs = existing_slugs.setdefault(row.user_id, set())
          while slug in user_slugs:
              slug = f"{base}-{counter}"
              counter += 1
          user_slugs.add(slug)
          updates.append({"slug": slug, "id": row.id})
      
      if updates:
          conn.execute(
              "UPDATE wiki_knowledge_point SET slug = :slug WHERE id = :id",
              updates,
          )
  ```
  
  > 提示：`_add_column_if_missing` / `_add_unique_if_missing` / `_add_index_if_missing` / `_create_table_if_missing` 是幂等辅助函数，在现有 `auto_migrate.py` 中类似函数已有实现，参考其模式扩展即可。

- [ ] **Step 5**: 测试 migration

  ```bash
  # 在测试 DB 上跑
  python -m backend.app.utils.auto_migrate --dry-run
  python -m backend.app.utils.auto_migrate
  ```

  **验收**：
  - `DESCRIBE wiki_knowledge_point` 包含所有新字段
  - `SHOW INDEX FROM wiki_knowledge_point` 包含 5 个新索引
  - 现有 KP 数据未丢失，`slug` 字段已回填

### Task 1.2: 核心契约层（无副作用模块）

**Files:**
- Create: `engine/app/wiki/slug.py`
- Create: `engine/app/wiki/parsers.py`
- Create: `engine/app/wiki/wikilink.py`
- Create: `engine/app/wiki/cache.py`
- Create: `engine/app/wiki/feature_flags.py`
- Create: `engine/app/wiki/language.py`

- [ ] **Step 1**: 创建 `slug.py`
  
  按设计文档 §5.1.2 中 `slug.py` 草稿实现 `make_slug` 函数。

  关键约束：
  - 保留 CJK 字符（不音译）
  - 保留 `_PRESERVE_TERMS` 中的术语原样（GPT-5、PyTorch 等）
  - 空格 / 标点 → `-`
  - 折叠多个 `-`
  - 最大长度 80 字符
  - 空标题 → `"untitled"`

- [ ] **Step 2**: 创建 `parsers.py`
  
  按设计文档 §5.3.1 的草稿完整实现：
  - `FILE_BLOCK_RE` / `REVIEW_BLOCK_RE` / `KP_PATH_RE` 正则
  - `is_safe_kp_path` 函数（路径白名单 + 黑名单）
  - `parse_frontmatter` 函数（YAML 解析）
  - `parse_generation_output` 主入口
  
  对译 LLM Wiki `src/lib/ingest.ts` 的 `parseFileBlocks`（含 `FILE_BLOCK_REGEX`、`isSafeIngestPath`）和 `parseReviewBlocks`。

- [ ] **Step 3**: 创建 `wikilink.py`
  
  按设计文档 §5.3.2 的草稿完整实现：
  - `extract_wikilinks` (从 markdown 提取去重保序的目标 slug 列表)
  - `resolve_slug` (大小写/连字符不敏感的 slug 解析)
  - `rewrite_wikilink` (全局重写，保留别名)
  - `fuzzy_suggest` (基于 levenshtein 的修复建议)
  
  对译 LLM Wiki `src/lib/wiki-graph.ts` 的 `extractWikilinks` / `resolveTarget`，以及 `src/lib/lint-fixes.ts` 的修复辅助函数。

- [ ] **Step 4**: 创建 `cache.py`
  
  实现 SHA256 增量缓存：
  - `compute_source_hash(text: str) -> str`
  - `check_ingest_cache(db, doc_id, source_hash) -> list[str] | None`
  - `save_ingest_cache(db, doc_id, source_hash, kp_ids) -> None`
  
  注意：缓存数据存在 `wiki_document.content_hash` 字段（已加在 Task 1.1）。

- [ ] **Step 5**: 创建 `feature_flags.py`
  
  ```python
  from engine.app.config import settings
  
  
  def is_v2_enabled(user_id: str | None = None) -> bool:
      """V2 管线 feature flag。
      
      默认通过环境变量 WIKI_PIPELINE_V2=1 开启。
      可扩展为按 user_id 灰度。
      """
      return settings.WIKI_PIPELINE_V2
  ```
  
  在 `engine/app/config.py` 加：
  ```python
  WIKI_PIPELINE_V2: bool = os.getenv("WIKI_PIPELINE_V2", "0") == "1"
  ```

- [ ] **Step 6**: 创建 `language.py`
  
  按设计文档 §5.2.4 的草稿实现 `content_matches_target_language`。
  
  使用 `langdetect` 库（已在 requirements.txt 加）。

### Task 1.3: 单元测试

**Files:**
- Create: `engine/tests/wiki/__init__.py`
- Create: `engine/tests/wiki/test_slug.py`
- Create: `engine/tests/wiki/test_parsers.py`
- Create: `engine/tests/wiki/test_wikilink.py`
- Create: `engine/tests/wiki/test_cache.py`

- [ ] **Step 1**: `test_slug.py` 覆盖
  
  测试用例：
  - 中文标题：`"反硝化除磷菌"` → `"反硝化除磷菌"`
  - 英文短语：`"Self Attention"` → `"self-attention"`
  - 含数字：`"GPT-5 Architecture"` → `"gpt-5-architecture"`
  - 保留术语：`"OpenAI Codex"` → `"openai-codex"`（虽 lower，但保留连字符）
  - 标点：`"什么是 LangChain?"` → `"什么是-langchain"`
  - 空字符串：`""` → `"untitled"`
  - 超长截断：100 字符 → 80 字符

- [ ] **Step 2**: `test_parsers.py` 覆盖
  
  测试用例：
  - 单 FILE 块解析正常
  - 多 FILE 块解析
  - REVIEW 块解析（含 OPTIONS / PAGES / SEARCH）
  - 不安全路径拒绝（`../../etc/passwd`、绝对路径、Windows 保留名）
  - 缺失 frontmatter 必填字段
  - frontmatter slug 与 path slug 不一致警告
  - 未知 REVIEW type 拒绝
  - OPTIONS 非白名单值过滤
  - 第一字符不是 `-` warning
  - 空响应正常处理

- [ ] **Step 3**: `test_wikilink.py` 覆盖
  
  测试用例：
  - `extract_wikilinks`: `"[[foo]] 和 [[bar|别名]]"` → `["foo", "bar"]`
  - `extract_wikilinks` 去重保序：`"[[a]] [[b]] [[a]]"` → `["a", "b"]`
  - `resolve_slug` 大小写不敏感：`"Foo"` 匹配 `{"foo": "kp1"}` → `"kp1"`
  - `resolve_slug` 连字符 / 空格互换：`"foo bar"` 匹配 `{"foo-bar": "kp1"}`
  - `rewrite_wikilink` 保留别名：`"[[foo|别名]]"` + `foo→bar` → `"[[bar|别名]]"`
  - `fuzzy_suggest` 找到最近匹配：`"transfomer"` + `["transformer", "translator"]` → `"transformer"`

- [ ] **Step 4**: `test_cache.py` 覆盖
  
  使用 sqlite in-memory 测试：
  - 写入缓存后 `check_ingest_cache` 命中
  - 不同 hash 不命中
  - 不同 doc_id 不命中

- [ ] **Step 5**: 运行测试
  
  ```bash
  cd engine && pytest tests/wiki/ -v
  ```

### Task 1.4: 阶段 1 验收

- [ ] **验收 1**: 单元测试覆盖率
  
  ```bash
  cd engine && pytest tests/wiki/ --cov=app/wiki --cov-report=term-missing
  ```
  
  目标：核心模块（slug / parsers / wikilink / cache）覆盖率 ≥85%

- [ ] **验收 2**: Migration 干跑无错误
  
  在测试库上重复执行 migration，确认幂等。

- [ ] **验收 3**: 现有功能不受影响
  
  ```bash
  # 跑现有 wiki 流程
  cd engine && pytest tests/test_chunker.py tests/test_hybrid_search.py -v
  ```
  
  原 `extraction_engine.py` 三阶段管线仍可用。

- [ ] **验收 4**: 提交 PR
  
  PR 标题：`[wiki-v2] Phase 1: data model + parsing infrastructure`
  
  PR 描述包含：
  - 新增字段列表
  - 新增模块列表 + 测试覆盖率
  - migration 验证日志
  - 与 spec 文档的 §4-5 章节关联


---

## 阶段 2: 两步 CoT 管线 + DeepSeek 适配（5-7 天）

**目标**：实现 V2 管线，与旧三阶段管线通过 feature flag 切换。

**前置**：
- 阶段 1 已合并
- 在测试库上重置 `WIKI_PIPELINE_V2=0`，确认旧管线仍工作
- 准备 5-10 个不同类型的测试文档（短中文、长中文、英文、混合、表格密集）

### Task 2.1: Prompt 实现

**Files:**
- Modify: `engine/app/wiki/prompts.py`

- [ ] **Step 1**: 在 `prompts.py` 顶部追加新常量与函数（保留旧的不删）
  
  按设计文档 §5.2.2 / §5.2.3 实现：
  - `ANALYSIS_SYSTEM_PROMPT`
  - `build_analysis_prompt(ctx) -> str`
  - `GENERATION_SYSTEM_PROMPT`
  - `build_generation_prompt(ctx, analysis) -> str`
  - `format_kp_index(kps) -> str` 辅助函数

- [ ] **Step 2**: 单元测试 `engine/tests/wiki/test_prompts.py`
  
  测试用例：
  - prompt 包含必要的格式约束（`---FILE:`、`---END FILE---`、`OPTIONS: Create Page | Skip`）
  - source_filename 正确插入
  - 现有 KP 索引正确格式化
  - 空 index / 空 schema 时不破坏 prompt 结构

### Task 2.2: Pipeline V2 主流程

**Files:**
- Create: `engine/app/wiki/pipeline_v2.py`
- Create: `engine/app/wiki/persist.py`
- Create: `engine/app/wiki/chunker.py`（抽自旧 `extraction_engine.py:_chunk_text`）

- [ ] **Step 1**: 创建 `chunker.py`
  
  把旧 `extraction_engine.py` 中的 `_chunk_text` / `_is_section_boundary` / `SECTION_PATTERNS` 抽出来。
  
  导出函数：
  - `chunk_long_text(text: str, max_chars: int = 4000) -> list[str]`
  - 与旧版完全等价，仅作为后续 V2 复用

- [ ] **Step 2**: 创建 `IngestContext` 数据类（在 `pipeline_v2.py` 中）
  
  ```python
  @dataclass
  class IngestContext:
      doc: WikiDocument
      file: KnowledgeFile
      source_text: str
      source_text_hash: str
      source_filename: str
      user_id: str
      topic_id: str | None
      purpose: str  # 阶段 5 加，先空字符串
      schema_definition: str  # 阶段 5 加
      existing_kp_index: list[dict]
      folder_context: str
      today: datetime
      precomputed_analysis: str = ""
      
      @classmethod
      def prepare(cls, db, doc_id, file_id) -> "IngestContext | None":
          """从 DB 装载完整上下文。"""
          ...
  ```

- [ ] **Step 3**: 实现 `pipeline_v2.run_extraction_v2`
  
  按设计文档 §5.1.1 阶段总览实现：
  - Stage 0: 文件解析（复用 `KnowledgeFile.content_text`）
  - Stage 0.5: 增量缓存检查
  - Stage 1: Analysis（调 `llm_chat`）
  - Stage 2: Generation（调 `llm_chat`）
  - Stage 2.5: Aggregate Repair（FILE 块为 0 时重生成）
  - Stage 3: Parse + Persist
  - Stage 4: 异步图重算（暂时只是占位 logger）
  - Stage 5: KP 向量化（暂时跳过，阶段 3 加）
  
  关键日志：每个 Stage 开始 / 完成都通过 `_log` 写入 `WikiExtractionLog`。

- [ ] **Step 4**: 实现 `persist.py`
  
  按设计文档 §5.4 完整实现：
  - `persist_kps`（upsert 路径调用 `merge_kp_content`，不直接覆盖 content）
  - `persist_relations_dual_source`
  - `upsert_relation`
  - `persist_review_items`

- [ ] **Step 4.5**: 实现 `merge.py`（multi-source KP body merge）
  
  对译 LLM Wiki `src/lib/page-merge.ts` 的 `mergePageContent`，参考 §8.1 中的 "页面合并" 条目。
  
  核心逻辑：
  ```python
  # engine/app/wiki/merge.py
  
  MERGE_SYSTEM_PROMPT = """你是 wiki 维护者。将两份关于同一主题的 wiki KP 正文合并成一份。
  
  规则：
  - 保留两份中所有具体事实（数字、阈值、角色名、条件）
  - 去掉重复叙述
  - 保持 markdown 结构
  - 不要添加原文没有的内容
  - 如果两份内容基本相同，直接返回较详细的那份
  - 不要输出任何解释，只输出合并后的 markdown
  """
  
  def merge_kp_content(old_body: str, new_body: str, llm) -> str:
      """LLM 合并两份 KP 正文。失败时 caller 应 fallback 到 new_body。
      
      sanity check：合并后长度不应短于 max(old, new) * 0.7，
      否则认为 LLM 丢失了事实，拒绝合并（返回 None）。
      """
      if not old_body.strip():
          return new_body  # 旧内容为空，直接用新的
      
      merged = llm.chat([
          {"role": "system", "content": MERGE_SYSTEM_PROMPT},
          {"role": "user", "content": f"## 已有版本\n\n{old_body}\n\n## 新版本\n\n{new_body}"},
      ])
      
      # sanity check：防止 LLM 大量丢失事实
      min_expected = max(len(old_body), len(new_body)) * 0.7
      if len(merged) < min_expected:
          raise ValueError(
              f"merge sanity failed: merged len {len(merged)} < "
              f"expected {min_expected:.0f} (70% of max source)"
          )
      return merged
  ```

- [ ] **Step 5**: 在 `extraction_engine.py` 顶部加 feature flag 入口
  
  ```python
  def run_extraction(doc_id: str, file_id: str):
      from .feature_flags import is_v2_enabled
      
      if is_v2_enabled():
          from .pipeline_v2 import run_extraction_v2
          return run_extraction_v2(doc_id, file_id)
      
      # 以下保留原 V1 实现
      ...
  ```

### Task 2.3: Engine API 改造

**Files:**
- Modify: `engine/app/api/wiki.py`

- [ ] **Step 1**: 新增 `/extract_v2` 端点（强制 V2，用于 A/B 测试）
  
  按设计文档 §5.8.2 实现。

- [ ] **Step 2**: `/extract` 端点保持不变（自动根据 flag 路由）

- [ ] **Step 3**: 增加单元测试 `engine/tests/wiki/test_pipeline_v2.py`
  
  使用 mocked LLM client，覆盖：
  - 正常路径：1 个 doc → N 个 KP + M 个 relation
  - 缓存命中：第二次相同 hash → 跳过 LLM
  - Stage 1 LLM 失败 → 状态 failed，记日志
  - Stage 2 输出 0 个 FILE 块 → 触发 aggregate repair
  - Aggregate repair 仍失败 → 写 fallback source summary
  - 解析 warning 但有 KP → 标 partial 但 status=completed
  - 跨文档 slug 冲突 → upsert 合并 source_doc_ids
  - wikilink 跨文档解析（已有 KP 在 DB）

### Task 2.4: DeepSeek 适配验证

**Files:**
- Create: `docs/superpowers/specs/2026-06-16-wiki-engine-deepseek-tuning.md`
- Modify: `engine/eval/wiki_v2_dataset.json`
- Create: `engine/eval/wiki_v2_eval.py`

- [ ] **Step 1**: 准备测试文档集
  
  在 `engine/eval/wiki_v2_dataset.json` 中放 5-10 个文档：
  - 短中文文档（<2K 字符）
  - 长中文文档（>20K 字符）
  - 英文论文摘要
  - 中英混合（技术文档）
  - 表格密集（Excel 转 markdown）
  - 流程定义类文档

- [ ] **Step 2**: 写 `wiki_v2_eval.py` 评估脚本
  
  ```python
  # 对每个测试文档：
  # 1. 用 V1 跑 → 记录 KP 数 / relation 数 / token 消耗 / 用时
  # 2. 用 V2 跑 → 同样记录
  # 3. 输出对比表 + 关键差异（哪个 KP 是 V2 新增的、哪个 V1 漏抽的）
  # 4. 输出 prompt 解析失败统计（V2 parse warnings）
  ```

- [ ] **Step 3**: 跑评估，记录 DeepSeek 偏离格式的情况
  
  在 `wiki-engine-deepseek-tuning.md` 文档中记录：
  - 哪些 prompt 修订有效（如开头加"严格规则:"）
  - DeepSeek 常见偏离模式（带前言、带 markdown 代码块包装、用 `<think>` 块）
  - 对应的 prompt 加固（如 `temperature=0.0`、明确禁止 `<think>`）
  - 实际成功率数据

- [ ] **Step 4**: 根据评估结果修订 prompt
  
  把成功率拉到 ≥95%。如果 DeepSeek 反复偏离某个约束，考虑：
  - 在 system prompt 顶部用 ALL CAPS 强调
  - 结构化为 JSON 输出（极端方案，但失去 wikilink 优势）
  - 加 retry 逻辑（解析失败自动用更严格的 prompt 再试一次）

### Task 2.5: 阶段 2 验收

- [ ] **验收 1**: V2 管线在 5+ 个测试文档上端到端跑通
  
  ```bash
  WIKI_PIPELINE_V2=1 python -m engine.run
  # 上传测试文档，检查 wiki_knowledge_point / wiki_knowledge_relation 表
  ```

- [ ] **验收 2**: 关键指标（跑 `engine/eval/wiki_v2_eval.py` 输出结果）
  
  ```python
  # 在 wiki_v2_eval.py 末尾加以下断言
  assert success_rate >= 0.95, f"parse success rate {success_rate:.2%} < 95%"
  assert avg_v2_relations >= avg_v1_relations, "V2 relations should be >= V1"
  assert avg_v2_tokens <= avg_v1_tokens * 0.50, "V2 tokens should be ≤50% of V1"
  
  # 缓存命中验证（SQL）
  # 上传同一文档第二次后查：
  # SELECT count(*) FROM wiki_extraction_log
  # WHERE document_id = '<id>' AND message LIKE '%cache-hit%'
  # 期望 >= 1
  ```
  
  - V2 解析成功率（FILE 块数 ≥1 的运行 / 总运行） ≥ 95%
  - 平均 wikilink relation 数 ≥ V1 relation 数
  - 单文档 token 成本 ≤ V1 的 50%
  - 缓存命中时 LLM 调用数 = 0（`wiki_extraction_log` 含 `cache-hit` 条目）

- [ ] **验收 3**: 旧管线不被破坏
  
  ```bash
  WIKI_PIPELINE_V2=0 python -m engine.run
  # 旧文档仍能用旧管线 ingest，无回归
  ```

- [ ] **验收 4**: A/B 报告
  
  在 PR 描述中附上 V1/V2 对比表，至少 5 个文档：
  
  | 文档 | V1 KPs | V2 KPs | V1 Relations | V2 Relations | V1 Tokens | V2 Tokens |
  |------|--------|--------|--------------|--------------|-----------|-----------|
  | ...  | ...    | ...    | ...          | ...          | ...       | ...       |

- [ ] **验收 5**: V1→V2 等价性回归测试

  > 防止 V2 改名导致用户 wiki 突然"重复了"的问题。

  1. 取 **阶段 1 完成时**的数据库快照（或直接记录现有 V1 KP 列表）
  2. 清空测试库，用 V2 重跑同一批文档
  3. 对比两个 KP 集合：

  ```python
  # engine/eval/wiki_v2_regression.py
  
  from engine.app.ingestion.vectorizer import embed_texts
  
  def load_kp_titles(db, docs: list[str]) -> list[str]:
      """按 document_id 加载 KP title 列表。"""
      ...
  
  def title_similarity(t1: str, t2: str, embeddings: dict) -> float:
      """用 embedding 余弦相似度判断两个 title 是否语义对应。"""
      ...
  
  def check_v1_v2_equivalence(v1_titles: list[str], v2_titles: list[str]):
      """验证 V1 中 80%+ 的 KP 能在 V2 中找到语义对应（cosine > 0.85）。"""
      assert len(v2_titles) >= len(v1_titles) * 0.80, (
          f"V2 KP count {len(v2_titles)} < 80% of V1 {len(v1_titles)}"
      )
      
      # 每个 V1 title 在 V2 中找最相似的
      matched = 0
      unmatched = []
      for t1 in v1_titles:
          best = max(title_similarity(t1, t2, ...) for t2 in v2_titles)
          if best >= 0.85:
              matched += 1
          else:
              unmatched.append((t1, best))
      
      match_rate = matched / len(v1_titles)
      assert match_rate >= 0.80, (
          f"V1→V2 match rate {match_rate:.2%} < 80%. "
          f"Unmatched: {unmatched[:5]}"
      )
  ```

  目标：
  - V2 KP 数 ≥ V1 KP 数 × 80%
  - V1 中 80%+ 的 title 在 V2 中能找到 cosine ≥ 0.85 的对应项


  
  PR 描述包含：
  - DeepSeek 适配章节链接
  - V1/V2 A/B 对比表
  - feature flag 验证（`WIKI_PIPELINE_V2=0` 走旧管线）
  - 已知偏差与 follow-up


---

## 阶段 3: KP 级 RAG 检索 + 4 信号图 + Agent Tool（5-7 天）

**目标**：让 Agent 可以通过 `wiki_search` 工具命中沉淀好的知识点，并通过图扩展拿到关联上下文。

**前置**：
- 阶段 2 已合并，V2 管线产生的 KP 在测试库有数据
- Milvus / ES 服务可用

### Task 3.1: 图引擎层

**Files:**
- Create: `engine/app/wiki/graph/__init__.py`
- Create: `engine/app/wiki/graph/relevance.py`
- Create: `engine/app/wiki/graph/builder.py`
- Create: `engine/app/wiki/graph/recompute.py`
- Create: `engine/tests/wiki/test_relevance.py`
- Create: `engine/tests/wiki/test_graph_builder.py`

- [ ] **Step 1**: `requirements.txt` 加依赖
  
  ```
  networkx>=3.0
  ```

- [ ] **Step 2**: 创建 `relevance.py`
  
  按设计文档 §5.5.1 完整实现，对译 `H:\Agent\Project\llm_wiki\src\lib\graph-relevance.ts` 的 `WEIGHTS` / `TYPE_AFFINITY` / `calculateRelevance`。

- [ ] **Step 3**: 创建 `builder.py`
  
  按设计文档 §5.5.2 完整实现 `build_user_graph`。

- [ ] **Step 4**: 创建 `recompute.py`
  
  按设计文档 §5.5.3 完整实现 `recompute_graph_for_user`（暂不调用 Louvain，留给阶段 5）。

- [ ] **Step 5**: 单元测试
  
  `test_relevance.py` 覆盖：
  - 4 信号分别为 0 时 total = 0
  - direct link 双向：A→B 和 B→A 同时存在 → direct = 6.0
  - source overlap 多个共享：3 个共享 doc → source = 12.0
  - Adamic-Adar：A 和 B 共享 1 个度为 4 的邻居 → neighbor ≈ 1.5/log(4) ≈ 1.08
  - type affinity 默认值：未知组合 → 0.5 * 1.0 = 0.5
  - 自连：A.id == B.id → total = 0
  
  `test_graph_builder.py` 覆盖：
  - 空 user → 空图
  - HIDDEN_TYPES 过滤：query 类不进图
  - 无向图去重：A→B 和 B→A 只有 1 条边
  - 跨 doc 关系：source overlap 信号被正确计算

### Task 3.2: 检索后端基础设施

**Files:**
- Create: `engine/app/wiki/retrieval/__init__.py`
- Create: `engine/app/wiki/retrieval/setup.py`
- Create: `engine/app/wiki/retrieval/kp_search.py`
- Create: `engine/app/wiki/retrieval/graph_expand.py`
- Modify: `engine/app/wiki/pipeline_v2.py`（加 Stage 5 KP 向量化）
- Modify: `engine/app/config.py`

- [ ] **Step 1**: 创建 `setup.py`
  
  按设计文档 §5.6.1 完整实现：
  - `KP_COLLECTION = "prism_wiki_kp"`
  - `KP_INDEX = "wiki_kp"`
  - `ensure_kp_milvus_collection(dim)` 函数
  - `ensure_kp_es_index(es)` 函数
  
  在 engine 启动时调用（`engine/run.py` 的 startup hook）。

- [ ] **Step 2**: 创建 `kp_search.py`
  
  按设计文档 §5.6.2 完整实现：
  - `hybrid_search_kp` 主入口
  - `es_search_kp`
  - `milvus_search_kp`
  - `rrf_fuse`

- [ ] **Step 3**: 创建 `graph_expand.py`
  
  按设计文档 §5.6.3 完整实现 `graph_expand_kp`。

- [ ] **Step 4**: 在 `pipeline_v2.py` 加 Stage 5：KP 向量化
  
  ```python
  async def stage_5_index_kps(ctx, kp_ids: list[str]):
      """KP 向量化 + ES 索引。"""
      from engine.app.wiki.retrieval.kp_search import index_kp_to_milvus, index_kp_to_es
      
      db = ctx.db
      kps = db.query(WikiKnowledgePoint).filter(
          WikiKnowledgePoint.id.in_(kp_ids)
      ).all()
      for kp in kps:
          # content_hash 不变跳过
          if kp_already_indexed(kp.id, kp.content_hash):
              continue
          embedding = embed_text(kp.title + "\n" + (kp.content or "")[:2000])
          index_kp_to_milvus(kp, embedding)
          index_kp_to_es(kp)
  ```

- [ ] **Step 5**: 在 `config.py` 加配置
  
  ```python
  WIKI_KP_EMBEDDING_BATCH_SIZE: int = int(os.getenv("WIKI_KP_EMBEDDING_BATCH_SIZE", "32"))
  WIKI_KP_SEARCH_TOP_K_DEFAULT: int = int(os.getenv("WIKI_KP_SEARCH_TOP_K_DEFAULT", "10"))
  ```

### Task 3.3: Agent Tool 集成

**Files:**
- Create: `engine/app/agent/tools/wiki.py`
- Modify: `engine/app/agent/tools/__init__.py`

- [ ] **Step 1**: 创建 `wiki.py`
  
  按设计文档 §5.6.4 完整实现 `wiki_search` 工具。

- [ ] **Step 2**: 在 `tools/__init__.py` 注册新工具
  
  ```python
  from . import wiki  # noqa: F401  # 触发 register_tool
  ```

- [ ] **Step 3**: 单元测试 `engine/tests/wiki/test_wiki_search_tool.py`
  
  使用 mock 的 `hybrid_search_kp` / `graph_expand_kp`，覆盖：
  - 命中：返回 status=found，含 primary_hits + graph_expanded
  - 空 wiki：返回 status=empty
  - 命中 < 3 个：seed_ids 等于 primary 全部
  - graph_expand 抛异常：仍返回 primary（不阻塞）
  - citations 被正确累加到 ctx

### Task 3.4: Backend API 扩展

**Files:**
- Modify: `backend/app/api/wiki.py`
- Modify: `backend/app/schemas/wiki.py`

- [ ] **Step 1**: 在 `schemas/wiki.py` 加请求/响应 schema
  
  - `WikiSearchRequest`：query, user_id, top_k, use_vector, expand_graph, hops
  - `WikiSearchResponse`：mode, primary, graph_expanded
  - `WikiGraphResponse`：nodes, edges
  - `WikiGraphRecomputeRequest`：user_id, full

- [ ] **Step 2**: 在 `backend/app/api/wiki.py` 追加端点
  
  按设计文档 §5.8.1 实现：
  - `GET /api/v1/wiki/graph`
  - `POST /api/v1/wiki/graph/recompute`
  - `POST /api/v1/wiki/search`

- [ ] **Step 3**: 在 `engine/app/api/wiki.py` 追加端点
  
  按设计文档 §5.8.2 实现：
  - `POST /api/v1/wiki/graph/recompute`
  - `POST /api/v1/wiki/search`

### Task 3.5: 集成测试 + RAG 评估

**Files:**
- Create: `engine/eval/wiki_search_eval.py`

- [ ] **Step 1**: 准备 RAG 评估数据集
  
  在 `engine/eval/golden_dataset.json` 已有的基础上加 KP-friendly query：
  - 概念性："什么是反硝化除磷"、"BERT 的核心思想"
  - 流程性："简述污水处理的工艺流程"
  - 对比性："PAOs 和 DPAOs 的区别"

- [ ] **Step 2**: 写 `wiki_search_eval.py`
  
  ```python
  # 对每个 query：
  # 1. 用 chunk hybrid search → top-5 hit
  # 2. 用 wiki_search (KP) → top-5 KP + graph_expanded
  # 3. 用 LLM judge：哪个回答更准确？
  # 4. 输出 win/loss/tie 表
  ```

- [ ] **Step 3**: 端到端集成测试
  
  在 chat 接口里测试：
  ```
  用户：什么是反硝化除磷
  → Agent 应该调用 wiki_search 而不是 knowledge_search
  → citations 含 KP 信息（slug / page_type）
  → 答案基于 KP description 而非 chunk 拼凑
  ```

### Task 3.6: 阶段 3 验收

- [ ] **验收 1**: 关键指标
  
  - KP 检索 top-5 hit_rate ≥ 85%（在已建库的 query 上）
  - 平均检索耗时 ≤ 300ms（KP + graph_expand 总和）
  - graph_expand 平均扩展节点数 3-8 个
  - 4 信号权重在 DB 中正确写回（`weight_total > 0` 的 relation 数 = 总 relation 数）

- [ ] **验收 2**: Agent 行为验证
  
  人工跑 10 个 query：
  - 概念性问题：≥7 个调用 `wiki_search`
  - 事实细节问题：≥5 个调用 `knowledge_search`
  - 没有 query 同时调两个工具失败

- [ ] **验收 3**: A/B 报告
  
  在 PR 描述中：
  - chunk-only vs chunk+KP 在 20 个 query 上的对比
  - 至少 3 个具体 case：KP 命中带来的回答质量提升

- [ ] **验收 4**: 提交 PR
  
  PR 标题：`[wiki-v2] Phase 3: KP-level RAG + 4-signal graph + agent tool`
  
  PR 描述包含：
  - 评估报告链接
  - Milvus / ES 资源消耗（KP collection 大小）
  - 与 spec 文档 §5.5-5.6 章节关联


---

## 阶段 4: 治理三件套（4-5 天）

**目标**：让 wiki 在长期使用中保持健康。

**前置**：
- 阶段 3 已合并，KP 数据已稳定积累
- 测试库中至少有 30+ KP，便于触发 lint 找到真实问题

### Task 4.1: Lint

**Files:**
- Create: `engine/app/wiki/governance/__init__.py`
- Create: `engine/app/wiki/governance/lint.py`
- Create: `engine/app/wiki/governance/fix.py`
- Create: `engine/tests/wiki/test_lint.py`

- [ ] **Step 1**: 实现 `lint.py`
  
  按设计文档 §5.7.1 完整实现：
  - `run_structural_lint(db, user_id) -> list[finding]`
  - `run_semantic_lint(db, user_id, llm_client) -> list[finding]`
  - `upsert_findings` 辅助函数

- [ ] **Step 2**: 实现 `fix.py`
  
  按设计文档 §5.8.1 中 `apply_lint_fix` 端点的语义实现修复执行：
  - `apply_broken_link_fix(finding_id, db)`：把 broken_target 改写为 suggested_target_slug
  - `apply_orphan_fix(finding_id, db)`：暂时只做"标记为 ignored"（后续可加"创建占位 KP"）
  - `apply_no_outlinks_fix(finding_id, db)`：调用 LLM 让其在正文中加 wikilink（参考 LLM Wiki `enrich-wikilinks.ts`）

- [ ] **Step 3**: 单元测试
  
  `test_lint.py` 覆盖：
  - 空 wiki：lint 返回空
  - broken-link 检测：A 引用 [[non-existent]] → 1 个 finding
  - 模糊建议：[[transfomer]] 应建议 transformer
  - orphan 检测：B 无入链 → 1 个 finding
  - synthesis 类被排除：不报 orphan
  - no-outlinks 检测：C 正文无 wikilink → 1 个 finding
  - 重复 finding 去重：相同 type+point_id+broken_target 只 1 条 open

### Task 4.2: Dedup

**Files:**
- Create: `engine/app/wiki/governance/dedup.py`
- Create: `engine/tests/wiki/test_dedup.py`

- [ ] **Step 1**: 实现 `dedup.py`
  
  按设计文档 §5.7.2 完整实现：
  - `DEDUP_DETECT_PROMPT`
  - `detect_duplicate_groups(db, user_id, llm_client)`
  - `merge_duplicate(db, candidate_id, canonical_id, llm_client)`
  - `_extract_json_object` 辅助函数（参考 LLM Wiki `sweep-reviews.ts:extractJsonObject`）
  - `llm_merge_contents` 辅助函数（参考 LLM Wiki `dedup.ts:mergeBodyContents`）

- [ ] **Step 2**: 单元测试
  
  `test_dedup.py` 用 mock LLM，覆盖：
  - 检测：LLM 返回 1 组同义 slug → 写入 1 条候选
  - 检测：LLM 返回非法 JSON → 不崩溃，返回空
  - 合并：选定 canonical 后，被合并 KP 的 wikilink 在全局重写
  - 合并：relation 的 from/to 指针重定向
  - 合并：被合并 KP 的 frontmatter 数组并入 canonical
  - 合并：被合并 KP 被删除
  - 合并：candidate.status 变 merged

### Task 4.3: Sweep

**Files:**
- Create: `engine/app/wiki/governance/sweep.py`
- Create: `engine/tests/wiki/test_sweep.py`

- [ ] **Step 1**: 实现 `sweep.py`
  
  按设计文档 §5.7.3 完整实现：
  - `sweep_pending_reviews(db, user_id, llm_client)`
  - `extract_candidate_names(review)` 辅助函数
  - `build_kp_index_summary(kps)` 辅助函数
  - `llm_judge_resolved(batch, kp_index, llm_client)` 辅助函数

- [ ] **Step 2**: 在 V2 pipeline 末尾自动调用 sweep
  
  在 `pipeline_v2.py` 的 Stage 5 后追加：
  ```python
  # Stage 6: 异步触发 sweep
  threading.Thread(
      target=lambda: sweep_pending_reviews(_Session(), ctx.user_id, llm_client),
      daemon=True,
  ).start()
  ```

- [ ] **Step 3**: 单元测试
  
  `test_sweep.py` 覆盖：
  - 规则匹配：missing-page review 的 title 已存在 KP slug → 标 resolved
  - 规则不匹配 + LLM 判定 resolved → 标 resolved
  - contradiction 类不被自动消解
  - 空 pending：返回 examined=0

### Task 4.4: API 与 Backend 暴露

**Files:**
- Modify: `engine/app/api/wiki.py`
- Modify: `backend/app/api/wiki.py`
- Modify: `backend/app/schemas/wiki.py`

- [ ] **Step 1**: Engine 侧端点
  
  按设计文档 §5.8.2 实现：
  - `POST /api/v1/wiki/lint/run`
  - `POST /api/v1/wiki/dedup/detect`
  - `POST /api/v1/wiki/dedup/merge`
  - `POST /api/v1/wiki/sweep`

- [ ] **Step 2**: Backend 侧端点
  
  按设计文档 §5.8.1 实现：
  - `POST /api/v1/wiki/lint/run`
  - `GET /api/v1/wiki/lint`
  - `POST /api/v1/wiki/lint/{finding_id}/fix`
  - `POST /api/v1/wiki/dedup/detect`
  - `GET /api/v1/wiki/dedup`
  - `POST /api/v1/wiki/dedup/{candidate_id}/merge`
  - `GET /api/v1/wiki/reviews`
  - `POST /api/v1/wiki/reviews/sweep`
  - `PATCH /api/v1/wiki/reviews/{review_id}`

- [ ] **Step 3**: 在 `schemas/wiki.py` 加对应 schema
  
  - `WikiLintFindingOut`
  - `WikiDedupCandidateOut`
  - `WikiReviewItemOut`
  - `WikiReviewUpdateRequest`
  - `DedupMergeRequest`

### Task 4.5: 阶段 4 验收

- [ ] **验收 1**: 治理功能端到端
  
  1. 在测试库 ingest 5+ 文档（含故意制造的同义 KP，如同时上传"反硝化除磷.md"和"DPAOs 流程.md"）
  2. `POST /api/v1/wiki/lint/run` → 返回结构 lint findings
  3. `POST /api/v1/wiki/dedup/detect` → 返回候选组（应该至少有"反硝化除磷"组）
  4. `POST /api/v1/wiki/dedup/{id}/merge?canonical_id=...` → 合并成功
  5. 合并后再 `GET /api/v1/wiki/lint` → 不应再有重复
  6. `POST /api/v1/wiki/reviews/sweep` → 返回 examined / resolved 数

- [ ] **验收 2**: 关键指标（附可执行验证）
  
  - structural lint 在 30 KP 上耗时 < 1s
  - semantic lint 在 30 KP 上耗时 < 30s（含 LLM）
  - dedup detect 在 30 KP 上耗时 < 60s（含 LLM）
  - dedup merge 后 wikilink 重写覆盖率 100%
  
  ```sql
  -- 验证 merge 后无悬空 [[old_slug]]（把 <old_slug> 替换为实际被合并的 slug）
  SELECT id, slug, SUBSTRING(content, 1, 200) AS content_preview
  FROM wiki_knowledge_point
  WHERE content LIKE '%[[<old_slug>]]%'
     OR content LIKE '%[[<old_slug>|%';
  -- 期望：0 行
  
  -- 验证 relation 指针已重定向（不再有指向被合并 KP 的 relation）
  SELECT count(*) FROM wiki_knowledge_relation
  WHERE from_point_id = '<merged_kp_id>'
     OR to_point_id = '<merged_kp_id>';
  -- 期望：0 行
  
  -- 验证 wiki_dedup_candidate 状态
  SELECT status FROM wiki_dedup_candidate WHERE id = '<candidate_id>';
  -- 期望：merged
  ```
  
  ```python
  # 在 tests/wiki/test_dedup.py 的集成 case 末尾加断言
  merged_kp_id = "..."  # 被合并掉的 KP
  old_slug = "dpao"
  
  remaining = (
      db.query(WikiKnowledgePoint)
      .filter(WikiKnowledgePoint.content.like(f"%[[{old_slug}]]%"))
      .count()
  )
  assert remaining == 0, f"Found {remaining} pages still linking to [[{old_slug}]]"
  ```

- [ ] **验收 3**: 提交 PR
  
  PR 标题：`[wiki-v2] Phase 4: governance (lint + dedup + sweep)`
  
  PR 描述包含：
  - 治理 e2e 测试日志
  - 与 spec 文档 §5.7-5.8 章节关联


---

## 阶段 5: 前端图视图 + 治理 UI + Louvain 社区（5-7 天）

**目标**：完整的用户体验，让 wiki 引擎从"可用"到"好用"。

**前置**：阶段 4 已合并，所有 Backend API 可用。

### Task 5.1: 前端依赖与脚手架

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/src/app/api.ts`
- Modify: `frontend/src/app/wikiStore.ts`

- [ ] **Step 1**: 安装前端依赖
  
  ```bash
  cd frontend
  pnpm add sigma graphology graphology-layout-forceatlas2
  ```

- [ ] **Step 2**: 在 `api.ts` 追加新 API 调用
  
  按设计文档 §5.9.5 完整实现：
  - `fetchWikiGraph()`
  - `fetchLintFindings(status)` / `triggerLintRun(semantic)` / `applyLintFix(id)`
  - `fetchDedupCandidates()` / `triggerDedupDetect()` / `mergeDedup(...)`
  - `fetchReviews(status)` / `triggerReviewSweep()` / `updateReview(...)`
  
  补充类型定义：
  ```ts
  export type GraphNode = { id; slug; title; page_type; community; in_count; out_count }
  export type GraphEdge = { source; target; type; origin; weight; weight_breakdown }
  export type LintFinding = { id; type; severity; point_id; detail; broken_target?; suggested_target_slug? }
  export type DedupCandidate = { id; point_ids; reason; confidence }
  export type ReviewItem = { id; type; title; description; status; affected_point_ids; search_queries }
  ```

- [ ] **Step 3**: 在 `wikiStore.ts` 加状态分片
  
  ```ts
  interface WikiState {
    // ... 现有 ...
    graph: { nodes: GraphNode[]; edges: GraphEdge[] } | null
    lintFindings: LintFinding[]
    dedupCandidates: DedupCandidate[]
    reviews: ReviewItem[]
    
    loadGraph: () => Promise<void>
    loadLintFindings: (status?) => Promise<void>
    loadDedupCandidates: () => Promise<void>
    loadReviews: (status?) => Promise<void>
  }
  ```

### Task 5.2: 知识图视图

**Files:**
- Create: `frontend/src/components/wiki/GraphRenderer.tsx`
- Create: `frontend/src/pages/WikiGraphPage.tsx`
- Modify: `frontend/src/app/routes.tsx`

- [ ] **Step 1**: 创建 `GraphRenderer.tsx`
  
  封装 sigma.js 渲染逻辑（参考 LLM Wiki `src/components/graph/graph-view.tsx`）：
  - props: `{ nodes, edges, colorMode, onNodeClick }`
  - 处理 ForceAtlas2 布局
  - 处理 hover 高亮（邻居保持，非邻居淡化）
  - 处理 zoom 控制按钮

- [ ] **Step 2**: 创建 `WikiGraphPage.tsx`
  
  按设计文档 §5.9.2 完整实现，调用 `<GraphRenderer>` 组件。

- [ ] **Step 3**: 路由注册
  
  ```tsx
  // routes.tsx
  { path: 'wiki/graph', element: <WikiGraphPage /> },
  ```

- [ ] **Step 4**: 在 `WikiPage` 顶部加 "查看图谱" 按钮
  
  ```tsx
  <Link to="/wiki/graph">查看知识图谱</Link>
  ```

### Task 5.3: 治理 UI

**Files:**
- Create: `frontend/src/pages/WikiLintPanel.tsx`
- Create: `frontend/src/pages/WikiDedupPanel.tsx`
- Create: `frontend/src/pages/WikiReviewPanel.tsx`
- Modify: `frontend/src/app/routes.tsx`

- [ ] **Step 1**: 创建三个面板
  
  按设计文档 §5.9.3 实现，每个面板都遵循相似的布局：
  - 顶部：标题 + 触发按钮
  - 中部：列表（每条带 type/severity/详情）
  - 每条右侧：操作按钮（修复 / 合并 / 标记已读）

- [ ] **Step 2**: 路由注册
  
  ```tsx
  { path: 'wiki/lint', element: <WikiLintPanel /> },
  { path: 'wiki/dedup', element: <WikiDedupPanel /> },
  { path: 'wiki/reviews', element: <WikiReviewPanel /> },
  ```

- [ ] **Step 3**: 在 `WikiPage` 顶部加导航
  
  ```tsx
  <nav className="flex gap-4">
    <Link to="/wiki">主页</Link>
    <Link to="/wiki/graph">图谱</Link>
    <Link to="/wiki/lint">健康检查</Link>
    <Link to="/wiki/dedup">去重</Link>
    <Link to="/wiki/reviews">审阅队列</Link>
  </nav>
  ```

### Task 5.4: Louvain 社区检测 + Insights

**Files:**
- Create: `engine/app/wiki/graph/community.py`
- Create: `engine/app/wiki/graph/insights.py`
- Modify: `engine/app/wiki/graph/recompute.py`
- Modify: `engine/app/api/wiki.py`
- Modify: `backend/app/api/wiki.py`

- [ ] **Step 1**: `requirements.txt` 加 `python-louvain`

- [ ] **Step 2**: 创建 `community.py`
  
  按设计文档 §5.5.4 完整实现：
  - `detect_communities(G)` 
  - `compute_community_cohesion(G, community_map)`

- [ ] **Step 3**: 创建 `insights.py`
  
  对译 `H:\Agent\Project\llm_wiki\src\lib\graph-insights.ts`：
  - `find_surprising_connections(G, communities) -> list`
  - `detect_knowledge_gaps(G, communities) -> list`

- [ ] **Step 4**: 在 `recompute.py` 启用 Louvain
  
  当 `full=True` 时调用 `detect_communities` 并写回 `community_id`。

- [ ] **Step 5**: 暴露 insights API
  
  - Engine: `GET /api/v1/wiki/graph/insights`
  - Backend: `GET /api/v1/wiki/graph/insights`

- [ ] **Step 6**: 在前端图视图加 "按社区着色" 切换 + insights 侧栏

### Task 5.5: 阶段 5 验收

- [ ] **验收 1**: 前端 build 通过
  
  ```bash
  cd frontend && pnpm build
  ```

- [ ] **验收 2**: 端到端用户流程
  
  1. 访问 `/wiki/graph` → 看到知识图谱（节点 + 边 + 颜色）
  2. 点击 "按社区着色" → 颜色按 community_id 重绘
  3. 悬停节点 → 邻居保持高亮，非邻居淡化
  4. 点击节点 → 跳转 `/wiki/points/<id>`
  5. 访问 `/wiki/lint` → 触发 lint，看到 findings 列表
  6. 点击 "修复" → finding 标 fixed
  7. 访问 `/wiki/dedup` → 触发 detect，看到候选组
  8. 选定 canonical 合并 → 候选标 merged
  9. 访问 `/wiki/reviews` → 触发 sweep，过期的自动标 resolved

- [ ] **验收 3**: 关键指标
  
  - 全图渲染（500 节点）≤ 2s
  - 社区颜色与 type 颜色平滑切换
  - Louvain 在 500 节点上 < 1s
  - 治理 UI 在 100 条 finding 上滚动流畅

- [ ] **验收 4**: 提交 PR
  
  PR 标题：`[wiki-v2] Phase 5: graph view + governance UI + Louvain`
  
  PR 描述包含：
  - 截图（图谱页 + 三个治理面板）
  - 与 spec 文档 §5.5.4 / 5.9 章节关联

---

## 全局收尾

### 文档更新

- [ ] 更新 `CLAUDE.md`：在 Module Map 中加新增的 wiki 子模块
- [ ] 更新 `README.md`：补充 V2 管线启用方法（`WIKI_PIPELINE_V2=1`）
- [ ] 在 `docs/superpowers/specs/` 写一份 retrospective：
  - 实际工作量 vs 预估
  - 哪些 prompt 调试经验未来可复用
  - 哪些设计决策事后看应该不同

### 切流量到 V2

- [ ] **节点 1**：`WIKI_PIPELINE_V2=1` 默认在 dev 环境
- [ ] **节点 2**：跑 1 周观察指标（spec §6.2 列出的指标）
- [ ] **节点 3**：评估稳定后修改默认值，旧管线进入 deprecation
- [ ] **节点 4**：3 个月后删除旧 `extraction_engine.py`（提交 cleanup PR）

### 已知 follow-up

记录在 `docs/superpowers/specs/wiki-engine-followups.md`：

1. **Purpose / Schema 自由化**：在 `knowledge_topic` 加字段
2. **Deep Research 集成**：REVIEW.search_queries 触发 web 搜索
3. **多模态扩展**：复用 `wiki_image` 表
4. **Obsidian 兼容导出**
5. **MCP server 暴露**

---

## 关键参考索引（供 Claude Code 实施时查阅）

### 当前项目相关文件

| 主题 | 路径 |
|------|------|
| 设计文档 | `docs/superpowers/specs/2026-06-16-wiki-engine-refactor-design.md` |
| 旧管线（保留作 fallback） | `engine/app/wiki/extraction_engine.py` |
| 旧 Prompt | `engine/app/wiki/prompts.py` |
| 数据模型 | `backend/app/models/wiki.py` |
| Backend API | `backend/app/api/wiki.py` |
| Engine API | `engine/app/api/wiki.py` |
| Agent runner | `engine/app/agent/runner.py` |
| 现有 chunk RAG | `engine/app/agent/rag/agentic.py` |
| 现有 hybrid 检索 | `engine/app/retrieval/hybrid.py` |
| 前端 wiki 主页 | `frontend/src/pages/WikiPage.tsx` |
| 前端路由 | `frontend/src/app/routes.tsx` |

### LLM Wiki 参考路径

> **行号注记**：以下表格按函数名引用。具体行号参见 spec §8（已校正）。如读到的内容与函数名不符，请用 `Select-String -Path "<file>" -Pattern "^(export )?(async )?function <name>"` 重新定位。

| 主题 | 路径 / 函数 |
|------|------------|
| 主流程 | `src/lib/ingest.ts` 的 `autoIngest` / `autoIngestImpl` |
| Analysis prompt | `src/lib/ingest.ts` 的 `buildAnalysisPrompt` |
| Generation prompt | `src/lib/ingest.ts` 的 `buildGenerationPrompt` |
| FILE 块正则 | `src/lib/ingest.ts` 的 `FILE_BLOCK_REGEX` |
| FILE 块解析 | `src/lib/ingest.ts` 的 `parseFileBlocks` |
| REVIEW 块解析 | `src/lib/ingest.ts` 的 `parseReviewBlocks`（私有函数） |
| Path 安全 | `src/lib/ingest.ts` 的 `isSafeIngestPath` |
| 页面合并（多源 upsert） | `src/lib/page-merge.ts` 的 `mergePageContent` |
| 4 信号权重 | `src/lib/graph-relevance.ts` 的 `WEIGHTS` / `TYPE_AFFINITY` / `calculateRelevance` |
| Wikilink 解析 | `src/lib/wiki-graph.ts` 的 `WIKILINK_REGEX` / `extractWikilinks` / `resolveTarget` |
| 图构建 | `src/lib/wiki-graph.ts` 的 `buildWikiGraph` |
| Louvain | `src/lib/wiki-graph.ts` 的 `detectCommunities`（私有函数） |
| Insights | `src/lib/graph-insights.ts` |
| Lint | `src/lib/lint.ts` 的 `runStructuralLint` / `runSemanticLint` |
| Dedup | `src/lib/dedup.ts` |
| Sweep | `src/lib/sweep-reviews.ts` |
| 前端图视图 | `src/components/graph/graph-view.tsx` |

---

## 实施过程注意事项

1. **每个阶段独立 PR**：阶段 1-5 各自独立合并，不要堆在一个 PR
2. **测试驱动**：阶段 1、3 的核心模块（解析、wikilink、4 信号）必须有 ≥85% 单元测试覆盖
3. **Feature flag 严格遵守**：阶段 2 完成后，`WIKI_PIPELINE_V2=0` 必须能完全回退旧行为
4. **DeepSeek 调试章节单独写**：阶段 2 期间发现的 prompt 偏差全部记录到 `wiki-engine-deepseek-tuning.md`
5. **数据迁移可重入**：所有 migration 必须支持重复执行（幂等）
6. **不破坏现有功能**：阶段 1-3 完成后，不开 V2 flag 的现有 wiki 功能必须无回归

---

## 文档结束

> 实施过程中如发现需要调整设计，请同步更新 `docs/superpowers/specs/2026-06-16-wiki-engine-refactor-design.md` 与本计划文档。
