# Prism 知识库管理与 Agent 工具体系总结报告

> 生成时间：2026-06-30
> 适用对象：后续接手的 agent / 开发者，以及希望理解 Prism 现状的非技术读者
> 仓库路径：`H:\Agent\Project\Prism\prism`

---

## 一、系统总体架构

Prism 是一个"个人知识操作系统"，核心理念是：用户上传的原始资料通过 **治理链路** 提炼成结构化知识（CKP/PKU），并通过 **图链路** 建立实体关联，最终由 **Agent 工具层** 提供给 AI 使用。

```
用户资料/文档
    ↓ 治理链路（LLM 抽取）
  CKP（主题知识点）─SUPPORTED_BY─ PKU（证据单元）─EVIDENCED_BY─ Source（chunk）
                                    │
                         MENTIONS_ENTITY（桥接边 ← 本次核心工作）
                                    │
  Entity（人名/邮箱/机构）─MENTIONED_IN─ Source（chunk）
  Alias ─ALIAS_OF─ Entity
    ↓ Agent 工具层
  entity_graph_search / knowledge_evidence_search / governed_knowledge_v2 / ...
```

三大存储层：
| 存储 | 角色 |
|---|---|
| **MySQL** | 主数据库：KnowledgeItem / KnowledgeChunk / CKP / PKU / KnowledgeEntity / EntityMention |
| **Neo4j** | 图索引：CKP/PKU/Entity/Alias/Source 节点 + 关系边（可多跳查询） |
| **Milvus** | 向量索引：chunk embedding / CKP embedding / PKU embedding / memory embedding |

---

## 二、知识库管理（后台链路）

### 2.1 文档治理链路（`knowledge_governance.py`）

**入口**：上传文档 → `settle_document_item_to_governance(db, item_id)`

**流程**：
```
KnowledgeItem (文档)
  ↓ 按 parent_chunk 遍历
  ├─ 实体抽取：extract_and_settle_entities()
  │     ├─ 识别人名 / 邮箱 / 机构 / 论文标题（规则 NER）
  │     └─ 写入 KnowledgeEntity / EntityMention / EntityRelation（MySQL）
  │
  └─ PKU 抽取（LLM）：_extract_document_chunk_pkus_with_llm()
        ├─ 识别 claim / method / rule / problem / experiment_result 等
        ├─ 写入 PersonalKnowledgeUnit（MySQL）
        └─ 聚合 → CKP 主题归并
```

**触发方式**：
- Worker 消费 Redis 队列（`engine/app/jobs/worker.py:404`）
- 治理完成后自动触发图投影（需 `ENTITY_GRAPH_ENABLED=1`）

### 2.2 资产单元治理链路

**入口**：`POST /personal_asset_units/{id}/confirm`

**流程**：`settle_personal_asset_unit_to_governance(db, unit)` → 实体抽取 + PKU 抽取 → 提交 → 图投影

### 2.3 Neo4j 图投影（`graph_projection.py`）

**三段投影，必须按序执行**：

```python
project_ckp_graph(db, graph)          # 投影 CKP → PKU → Source 链路
project_entity_graph(db, graph)       # 投影 Entity / Alias → Source 链路
project_pku_entity_mentions(db, graph) # ★ 桥接：PKU -[MENTIONS_ENTITY]-> Entity
```

`project_pku_entity_mentions` 是本次新增的核心改动：
- 按 `(source_kind, source_id)` 做 PKU ↔ EntityMention 的 join
- 对落在 child chunk 上的 EntityMention 做 **parent 归并**（因为 PKU 总是指向 parent chunk）
- 建立 `PKU -[:MENTIONS_ENTITY]-> Entity` 显式桥接边，把治理图与实体图连通

**自动投影入口**（`graph_sync.py`）：
```python
project_governance_graph_if_enabled(db, user_id=...)
```
- 受 `ENTITY_GRAPH_ENABLED`（默认 0）控制
- 投影失败是 best-effort，只记录日志，**不影响治理结果**
- 已接入：文档治理 worker + 资产单元确认 API

**手动全量回填**：
```bash
python -m backend.scripts.backfill_entity_graph
```

### 2.4 实体抽取质量（`entity_extraction.py`）

当前支持的实体类型与提取方式：

| 类型 | 识别方式 | 质量状态 |
|---|---|---|
| `email` | 完整邮箱 regex | ✅ 高精度 |
| `person` | Title-Case 英文姓名 + 止词过滤 | ✅ 本次改善，误识别降低 |
| `organization` | 含机构关键词（University/Lab/Institute…）+ 长度约束 | ✅ 本次改善 |
| `paper` | 首行 colon 标题 + 噪声过滤 | ⚠️ 仍有误识别，精度中等 |

本次规则增强要点：
- 脚注编号剥离：`Yanchao Tan1,2` → `Yanchao Tan`
- 机构行分隔符扩展支持 `;`
- 止词过滤：排掉 `Senior Member`、`Proximal Gradient`、`Beam Search`、`Associate Professor` 等头衔/术语
- 噪声 span 过滤：`_looks_like_noise_span()` 拦截代码块/yaml/长配置片段

---

## 三、给 AI 的工具层（Agent Tools）

### 3.1 工具注册机制

**注册表**：`BUILTIN_REGISTRY`（`engine/app/agent/tools/base.py`）

**加载方式**：`tools/__init__.py` 通过 import 副作用注册所有工具

**运行时启用**：
```python
tools = build_enabled_tools(ctx, overrides={"governed_knowledge_v2": True, ...})
```

**默认启用（8 个）**：
```
knowledge_topic_search / knowledge_evidence_search / knowledge_material_search /
raw_document_search / entity_graph_search / memory_search / clarify_user / datetime
```

---

### 3.2 工具完整清单

#### 检索类工具（知识层）

| 工具 key | 默认启用 | 检索原语 | 数据层 | 核心职责 |
|---|---|---|---|---|
| `knowledge_topic_search` | ✅ | 结构化过滤 | CKP（MySQL） | 按主题/类型列 CKP 知识点 |
| `knowledge_evidence_search` | ✅ | 结构化过滤 | PKU（MySQL） | 按 unit_type 列证据单元 |
| `knowledge_material_search` | ✅ | PKU/CKP 回溯 | Source（MySQL） | 从 PKU/CKP 回溯到原始资料 |
| `raw_document_search` | ✅ | 关键词 | chunk（MySQL） | 原文 chunk 关键词检索 |
| `governed_knowledge_v2` | ❌ | 向量优先 | chunk→PKU→CKP | 语义向量检索（Milvus依赖） |
| `deep_knowledge_search` | ❌ | 多轮编排 | 全层 | 多步 scope→evidence→judge 深搜 |

#### 图检索工具

| 工具 key | 默认启用 | 检索原语 | 数据层 | 核心职责 |
|---|---|---|---|---|
| `entity_graph_search` | ✅ | Neo4j 多跳图遍历 | Entity/Alias/PKU/CKP/Source | 实体查找 + 关联知识点 + 出处路径 |

**`entity_graph_search` 是本次最核心改动的工具**，现在返回三层结果：
1. `entities`：命中的实体（人名/邮箱/机构/论文）
2. `sources`：实体出现的出处文档 chunk
3. `governed_paths`：实体通过桥接边关联的 PKU/CKP 治理链路

返回示例（查询 `Yanchao Tan`）：
```json
{
  "status": "success",
  "summary": "Found entity context for Yanchao Tan. Most relevant knowledge points: 优化推导网络, 多视图表示学习, 实验评估与模型分析. Source-backed evidence appears in: OIMGC-Net. Returned 5 CKP/PKU path(s), 5 source(s).",
  "governed_paths": [
    { "ckp_title": "优化推导网络", "support_confidence": 0.95, "pku_unit_type": "method", "source_id": "..." },
    { "ckp_title": "多视图表示学习", "support_confidence": 0.90, "pku_unit_type": "method", "source_id": "..." }
  ]
}
```

#### 资产类工具

| 工具 key | 默认启用 | 职责 |
|---|---|---|
| `asset_search` | ✅ | 个人资产关键词检索 |
| `asset_overview` | ✅ | 资产概览 |
| `asset_related` | ✅ | 关联资产 |

#### 结构化索引工具

| 工具 key | 默认启用 | 职责 |
|---|---|---|
| `page_index_get_document` | ❌ | 获取文档结构 |
| `page_index_get_document_structure` | ❌ | 获取文档大纲 |
| `page_index_get_page_content` | ❌ | 获取页面内容 |

#### 记忆与控制流

| 工具 key | 默认启用 | 职责 |
|---|---|---|
| `memory_search` | ✅ | 用户长期记忆/偏好/目标检索 |
| `web_search` | ❌ | 外部网页搜索 |
| `clarify_user` | ✅ | 向用户澄清确认 |
| `datetime` | ✅ | 获取当前时间 |

---

### 3.3 工具选择指引（给 Agent）

工具在 `prompts.py` 里有详细的边界说明，核心原则：

```
按检索原语 × 数据层正交划分，每个工具只对应一个格子：

• 要找"我有哪些主题" → knowledge_topic_search
• 要找"关于 X 的观点/规则/证据" → knowledge_evidence_search
• 要找"我的资料里关于 X 的综合出处" → knowledge_material_search (intent=opinions)
• 要找"某人/邮箱/机构是否存在 + 关联哪些知识点" → entity_graph_search（必须首用）
• 要做语义自然语言匹配 → governed_knowledge_v2（需开启）
• 要做多步深度综合 → deep_knowledge_search（需开启）
• 要查用户偏好/目标 → memory_search
• 要查文件原文段落 → raw_document_search（先试 evidence/material，不足再用）
```

---

## 四、本次会话核心改动汇总

### 4.1 工具治理（改造第1、2步）

| 改动 | 文件 | 说明 |
|---|---|---|
| 删除 `knowledge_search` 注册 | `knowledge.py` | 通用 RAG 死工具下线 |
| 删除 V1 `governed_knowledge_search` 注册 | `governed_knowledge.py` | 保留 helper 库，下线注册 |
| 注册 `governed_knowledge_v2` | `__init__.py` | 修复孤儿工具 |
| 重写 8 个工具的 description 为对照式 | 各 tool 文件 | "Use when X / Do NOT use → Z" |
| 更新 `prompts.py` 边界段 | `prompts.py` | 补 V2 / deep 条目 |

**测试**：37 通过 / 0 回归（engine 套件 +1 新增边界测试）

### 4.2 Neo4j 图检索离线测评

| 新增 | 路径 |
|---|---|
| `graph_ckp_pku` 检索链 | `engine/eval/compare_retrieval_chains.py` |
| `graph_source` 检索链 | 同上 |
| `graph_entity_ckp` 检索链 | 同上 |

**知识问答集（60 题）融合指标**：
- `traditional` 单独：R@10 = 0.511
- `traditional + graph_entity_ckp`：R@10 = 0.554（**+8.4%**）
- `traditional + all_graph`：R@10 = 0.574（**+12.3%**）

### 4.3 PKU↔Entity 桥接（核心图工作）

| 改动 | 文件 | 说明 |
|---|---|---|
| `project_pku_entity_mentions()` | `graph_projection.py` | 建立桥接函数 + child→parent 归并 |
| `GraphProjectionResult.pku_entity_mention_count` | 同上 | 新增计数字段 |
| `project_governance_graph_if_enabled()` | `graph_sync.py` | best-effort 自动投影封装 |
| worker 接入自动投影 | `engine/app/jobs/worker.py:404` | 治理完成后触发 |
| assets API 接入自动投影 | `backend/app/api/assets.py:937` | confirm 后触发 |

**Neo4j 桥接边数量**：458 条（child→parent 归并后）

**测试**：22 通过（含 5 个桥接测试 + 3 个 sync 测试）

### 4.4 entity_graph_search 工具升级

| 改动 | 说明 |
|---|---|
| 新增 `governed_paths` 字段 | 返回 Entity→PKU→CKP 路径 |
| query-aware governed rerank | `_rank_governed_paths()` / `_rank_sources()` 按 query term 命中重排 |
| query-aware summary | `_query_aware_summary()`：优先报实体 + 最相关 CKP + 出处 |
| `query_terms` 字段 | 返回 query 分词结果，便于下游 |
| 成功判定升级 | `governed_paths` 非空也算 success |

### 4.5 实体抽取质量提升

| 改动 | 文件 | 说明 |
|---|---|---|
| `_looks_like_noise_span()` | `entity_extraction.py` | 过滤代码/yaml/markup 片段 |
| `_looks_like_person_name()` | 同上 | 止词黑名单 + 单词级拦截 |
| 机构行 `;` 分割 | 同上 | `_ORG_SPLIT_RE` 支持分号 |
| 脚注编号剥离 | 同上 | `_clean_author_token()` / `_clean_organization()` |
| 新增 6 个 badcase 测试 | `test_entity_extraction.py` | 回归保护 |

**效果**：实体回填后 entity_count 从 1447 增至 **2582**，pku_entity_mention_count 从 74 增至 **546**

### 4.6 实体专项评测集

| 版本 | 样本数 | 类型分布 | Expanded Hit@10 |
|---|---|---|---|
| 初版（email-only） | 12 | 全 email | 100% |
| 本次最终版 | 24 | email 3 + person 8+ + org 1 | **95.8%** |

文件：`evaluation/datasets/entity_graph_v1.json`
构建脚本：`evaluation/build_entity_graph_eval.py`

---

## 五、当前未解决问题与后续方向

### 已知问题

| 问题 | 严重程度 | 位置 |
|---|---|---|
| `raw_document_search` 输出缺 `evidence_items` 字段 | 中 | `backend/app/services/knowledge_governance.py` |
| `paper` 实体仍有较高误识别率（短文本标题尚可，长文本段落仍泄漏） | 中 | `entity_extraction.py:_extract_paper_title` |
| `person` 中文人名抽取未实现（当前仅支持英文 Title-Case 姓名） | 中 | `entity_extraction.py` |
| Neo4j 图投影无增量机制（目前全量回填，无 delta 更新） | 低 | `graph_projection.py` |
| `ENTITY_GRAPH_ENABLED` 默认关闭（生产未启用图同步） | 低 | 配置 |

### 高价值后续方向

#### A. 动态工具加载（Profile 机制）
当前 `build_enabled_tools` 是静态开关，建议改为：
```python
TOOL_PROFILES = {
    "default": {...},
    "deep": {...},      # 开启 deep_knowledge_search
    "graph_only": {...} # 以图为主
}
```

#### B. 工具选择意图路由
在进 agent 前加轻量分类：
- 含"关系/关联/谁" → `entity_graph_search` 优先
- 含"详细/综合/完整" → `deep_knowledge_search`
- 含"我的偏好/习惯" → `memory_search`

#### C. 中文人名抽取
当前规则 NER 只识别英文 Title-Case 姓名，中文人名需另设规则或轻量 NER 模型。

#### D. entity_graph_search 的 source/snippet rerank
目前 query-aware rerank 只看 `ckp_title` 和 source `title`，可进一步把 `snippet / evidence_span` 纳入打分。

#### E. 图投影增量化
当前每次治理都触发全量投影（project_ckp_graph + project_entity_graph + bridge），应改为：
- 只投影本次改动的 CKP/PKU/Entity 集合
- 生产时打开 `ENTITY_GRAPH_ENABLED=1`

---

## 六、测试状态快照

| 套件 | 通过 | 状态 |
|---|---|---|
| `backend/tests/test_graph_projection.py` | 19 | ✅ |
| `backend/tests/test_graph_sync.py` | 3 | ✅ |
| `engine/tests/test_entity_graph_search_tool.py` | 15 | ✅ |
| `backend/tests/test_entity_extraction.py`（定向） | 6 | ✅ |
| **图桥接相关合计** | **43** | ✅ |
| engine 全量套件（基线） | 187（改前） | 既有 15 失败与本次无关 |
| engine 全量套件（改后） | 188（+1） | ✅ 无回归 |

---

## 七、关键文件索引

```
backend/app/services/
  entity_extraction.py          # 规则 NER：人名/邮箱/机构/论文 抽取
  graph_projection.py           # SQL → Neo4j 投影（含桥接函数）
  graph_sync.py                 # best-effort 自动投影封装
  graph_client.py               # Neo4j 写入客户端
  graph_query.py                # Neo4j 多跳查询服务（前端/API 用）
  knowledge_governance.py       # 治理核心：PKU/CKP 抽取聚合

engine/app/agent/tools/
  entity_graph_search.py        # 图检索工具（含 governed_paths）
  knowledge_governance.py       # 4 个默认启用的结构化检索工具
  governed_knowledge_v2.py      # 向量优先检索（registered，default disabled）
  deep_knowledge_search.py      # 多步深搜（default disabled）
  memory.py                     # 长期记忆检索
  assets.py                     # 个人资产检索
  base.py                       # ToolContext / BUILTIN_REGISTRY / build_enabled_tools

engine/app/agent/
  prompts.py                    # System prompt + 工具边界指引段

engine/app/jobs/
  worker.py                     # 文档治理 worker（含图投影接入点 line 404）

backend/app/api/
  assets.py                     # 资产 confirm API（含图投影接入点 line 937）

backend/scripts/
  backfill_entity_graph.py      # 手动全量实体回填脚本

evaluation/
  build_entity_graph_eval.py    # 实体专项评测集构建脚本（含噪声过滤规则）
  datasets/entity_graph_v1.json # 实体专项评测集（24 题：email/person/org）
  datasets/formal_docs_v1.json  # 知识问答评测集（60 题）

docs/superpowers/plans/
  2026-06-30-tool-redundancy-cleanup-and-description-boundaries.md
  2026-06-30-graph-retrieval-eval-report.md
  2026-06-30-graph-bridge-pku-entity.md
  2026-06-30-entity-graph-specialized-eval-report.md
```

---

## 八、当前系统能力一句话总结

> Prism 的 Agent 现在不仅能按主题/证据类型查知识（CKP/PKU），也能通过"实体名 → 治理知识点 → 出处"的图路径查询"某人/某机构/某邮箱出现在哪些资料里，以及关联了哪些已治理的知识点"——这是本次桥接工作带来的核心能力扩展。
