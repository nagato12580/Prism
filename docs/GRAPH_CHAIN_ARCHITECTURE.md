# Prism 图链路架构（交接文档）

> 本文档面向后续开发与 Claude 会话，描述 2026-07 完成的**图谱治理链路大改造**后的系统现状。
> 它是对根 `CLAUDE.md`（仍描述改造前的基础架构）的**增量更新**——两者一起读。
> 设计来源：`docs/superpowers/specs/2026-07-*.md`；执行计划：`docs/superpowers/plans/2026-07-*.md`。

## 0. TL;DR

Prism 已从"向量 RAG + 双链路 PKU/CKP 治理"演进为**统一图谱治理链路**：每条入库内容都进图、图谱由 graphify 分析（社区/god/surprising）、检索在向量+BM25 之上叠加图扩展与 rerank、对话被动注入图洞察、CKP 状态由图信号治理。改造分 5 个阶段（P1→StepA→StepB→P3→P5→P4），全部已实现并合入 `feature/entity-graph-projection`。

---

## 1. 阶段总览（均已实现）

| 阶段 | 能力 | 关键产物 |
|------|------|---------|
| **P1** 全覆盖抽取 | 每个 chunk 经 LLM 抽实体/关系进图 | `extraction/stage_a.py`、`entity_extraction.settle_entity_candidates`、`graph_projection.project_item_entities` |
| **Step A** 收尾 | 实体间 RELATED_TO、Neo4j 重入库清理、confidence 默认值 | `delete_item_sources`、泛化 `_resolve_entity_for_relation` |
| **Step B** graphify 分析 | 社区发现/god/surprising/diagnostics 写回 Neo4j | `graph/analyzer.py::run_analysis` |
| **P3** 统一检索 | 向量+BM25+图扩展+rerank，agent 工具 4→2 | `retrieval/unified.py`、`rerank.py`、`graph_expand.py` |
| **P5** 洞察注入 | 图洞察（隐藏联系/枢纽/可追问）注入 system prompt | `graph/insights.py::graph_insights_context` |
| **P4** 图治理 | CKP 状态 draft→stable 由 cohesion/god 驱动 | `graph/ckp_governance.py::govern_ckp_status_by_graph` |

> **P4a（未做）**：基础语义状态规则（same_as/supports/contradicts → stable/disputed）。P4 只做了图信号那一半。

---

## 2. 系统架构（改造后）

三进程 + 共享 MySQL，外加 Neo4j（图谱）、Milvus（向量）、ES（BM25）、Redis（队列）：

```
Browser (React :5173)
    ├── /api/v1/chat/answer ──→ Engine (FastAPI :5180)
    ├── /api/v1/ingest ────────→ Engine (:5180)
    └── /api/v1/* ─────────────→ Backend (FastAPI :5175)

Engine :5180（AI/RAG 核心）
  ingestion/pipeline.py     入库：chunk→embed→MySQL/Milvus/ES→Stage A→投影→run_analysis
  extraction/               Stage A LLM 实体/关系抽取（并行 fan-out）
  graph/                    analyzer（graphify 分析）/ insights（注入）/ ckp_governance（状态）
  retrieval/                unified（GraphRAG 编排）/ hybrid（RRF）/ rerank / graph_expand
  agent/                    runner（注入记忆+图洞察）/ prompts（工具边界）/ tools（agent 工具）/ rag（agentic 多轮）
  jobs/worker.py            异步 PKU/CKP 抽取（双链路治理）

Backend :5175（CRUD/解析/治理服务）
  services/entity_extraction.py   实体落库（settle_entity_candidates）
  services/graph_client.py        Neo4j 读写（实体/社区/god/surprising/清理）
  services/graph_projection.py    MySQL→Neo4j 投影（MENTIONED_IN/RELATED_TO）
  services/knowledge_governance.py 双链路 PKU/CKP 抽取与归一（worker 调用）
  models/                          KnowledgeEntity / CKP/PKU / GraphCommunity / GraphInsightSummary
```

**进程边界**：Backend 管 CRUD/文件解析/触发入库；Engine 跑 AI 管线与流式对话；两者共享同一 MySQL。Neo4j 是图谱唯一存储（MySQL 存实体原始数据 + 治理层，Neo4j 存图结构 + 分析标签）。

---

## 3. 端到端数据流

### 3.1 入库（写图）
```
上传文件 → backend KnowledgeItem → engine /api/v1/ingest
  → pipeline.ingest_item(item_id):
      1. chunk_parent_child → MySQL KnowledgeChunk（parent/child）
      2. embed → Milvus 向量；ES 索引
      3. _run_stage_a_for_item:                                     [P1]
           清理旧 mention（MySQL）
           extract_stage_a_parallel（每 chunk 一个 LLM 子代理）→ EntityCandidate（含 relations）
           settle_entity_candidates → MySQL KnowledgeEntity/Alias/Mention/Relation
      4. _project_and_analyze:
           project_item_entities → Neo4j MENTIONED_IN/RELATED_TO + delete_item_sources（清旧 Source）  [StepA/P1]
           run_analysis（全图）:                                                                       [StepB/P5/P4]
             export Entity-Entity 图（共现边+关系边）→ graphify build_from_json → cluster(Louvain)
             → 稳定重映射 community_id → god(度数)/surprising/diagnostics → 写 Neo4j
             → 社区标签(便宜LLM)+suggest_questions → graph_community/graph_insight_summary  [P5]
             → govern_ckp_status_by_graph: draft→stable by cohesion/god → CKP.extra_meta     [P4]
  （异步）jobs/worker: settle_document_item_to_governance → PKU/CKP 抽取与归一
```

### 3.2 检索（P3 统一 GraphRAG）
```
agent 调 knowledge_search / deep_knowledge_search
  → ctx.rag_runner.run(query) → AgenticRagRunner（多轮 检索-判断-改写）
       每轮 search = make_unified_search(mode):
         ① match_seed_entities(query) → seed Entity（别名/normalized_key 匹配）
         ② hybrid_search（Milvus 向量 + ES BM25，RRF）
         ③ graph_expand（自适应：fast=1跳；deep=2跳+社区+god+surprising）→ 额外候选
         ④ RRF 融合 + rerank（cross-encoder，失败降级为纯 RRF）
         → SearchHit 列表（带 source_marker：vector/graph_1hop/community/god/surprising/rerank）
  → _build_evidence → evidence bundle（CKP→PKU→Source，带出处）
  → agent 生成带引用的回答
```

### 3.3 对话（P5 注入）
```
runner._build_messages(query):
  SystemMessage(system_prompt)
  SystemMessage(recall_memory_context(query))        # 既有：记忆
  SystemMessage(graph_insights_context(query))       # P5：图洞察（隐藏联系/枢纽/可追问）
  ...history, HumanMessage(query)
agent 据 system prompt 选 tool（knowledge_search/deep/memory/clarify）
```

---

## 4. 模块清单（新增/显著变更）

### Engine
| 路径 | 职责 |
|------|------|
| `engine/app/extraction/prompts.py` | Stage A 抽取 prompt + 三档置信度 JSON 解析（EXTRACTED/INFERRED/AMBIGUOUS，禁 0.5） |
| `engine/app/extraction/stage_a.py` | `extract_entities_for_chunk`（单 chunk LLM）、`extract_stage_a_parallel`（ThreadPoolExecutor fan-out，即"子代理"） |
| `engine/app/graph/analyzer.py` | `run_analysis`：graphify build/cluster/score_all/surprising/diagnostics + 稳定重映射 + P5 标签/问题 + P4 治理 |
| `engine/app/graph/insights.py` | `graph_insights_context`（注入块）、`generate_community_labels`（便宜 LLM）、`compute_suggested_questions`（结构化）、`has_insight_signal`（门控） |
| `engine/app/graph/ckp_governance.py` | `map_ckp_to_entities`、`aggregate_ckp_signals`、`govern_ckp_status_by_graph`（draft→stable，只晋不降） |
| `engine/app/retrieval/unified.py` | `unified_search` + `make_unified_search`（返回 SearchFn，注入 AgenticRagRunner） |
| `engine/app/retrieval/rerank.py` | cross-encoder rerank（HTTP，失败降级） |
| `engine/app/retrieval/graph_expand.py` | `match_seed_entities` + `expand_candidates`（1/2 跳+社区+god+surprising） |
| `engine/app/retrieval/hybrid.py` | RRF 融合（向量 0.6 + BM25 0.4，k=60）—— 被 unified 复用，未改 |
| `engine/app/ingestion/pipeline.py` | `ingest_item` 末尾接 `_run_stage_a_for_item` → `_project_and_analyze`（失败隔离） |
| `engine/app/agent/runner.py` | `_build_messages` 注入 recall + graph_insights（均 try/except，不拖累首字） |
| `engine/app/agent/prompts.py` | **工具边界已重写**：knowledge_search/deep + memory_search；命名实体用 deep_knowledge_search 核实 |
| `engine/app/agent/tools/__init__.py` | 已下线 entity_graph_search/governed_knowledge/knowledge_governance 的注册 |

### Backend
| 路径 | 职责 |
|------|------|
| `backend/app/services/entity_extraction.py` | `settle_entity_candidates`（共享写路径）；`_resolve_entity_for_relation`（已泛化，跨类型） |
| `backend/app/services/graph_client.py` | Neo4j：upsert_entity/source/relate + 读方法 entity_community/are_gods/neighbors/community_members/god_neighbors/surprising_endpoints + delete_item_sources/read_entity_communities/set_entity_analysis |
| `backend/app/services/graph_projection.py` | `project_item_entities`（增量，投影前清旧 Source）、`project_entity_graph`/`project_ckp_graph`（全量） |
| `backend/app/services/knowledge_governance.py` | 双链路 PKU/CKP 抽取与归一（worker 调用）；**状态晋升逻辑仍缺（→ P4a）** |
| `backend/app/models/entity.py` | KnowledgeEntity / EntityAlias / EntityMention / EntityRelation |
| `backend/app/models/knowledge_governance.py` | CanonicalKnowledgePoint（status: draft/stable/disputed/deprecated）/ PersonalKnowledgeUnit / PKUCanonicalLink |
| `backend/app/models/graph_community.py` | GraphCommunity（社区标签 + cohesion） |
| `backend/app/models/graph_insight_summary.py` | GraphInsightSummary（全局 suggest_questions） |

---

## 5. 图谱数据模型（Neo4j + MySQL）

**Neo4j 节点**：`:Entity` / `:Source` / `:CKP` / `:PKU` / `:Alias`
**Neo4j 边**：`MENTIONED_IN`（Entity↔Source）、`RELATED_TO`（Entity↔Entity，可带 `surprising:true`）、`SUPPORTED_BY`（CKP↔PKU）、`EVIDENCED_BY`（PKU↔Source）、`HAS_CHILD`、`ALIAS_OF`

**Entity 节点属性（Step B 写入）**：`community_id`、`is_god`、`cohesion` —— **只在 Neo4j，不在 MySQL**。

**关键表**：
- `knowledge_entity` / `entity_alias` / `entity_mention` / `entity_relation`（MySQL，实体原始数据）
- `canonical_knowledge_point`（CKP，`status` + `metadata` 列存 graph_cohesion/god_backed/reason）
- `graph_community`（user_id, community_id, label, cohesion）—— P5
- `graph_insight_summary`（user_id, suggested_questions JSON）—— P5

---

## 6. Agent 工具面（改造后，干净）

| 工具 | 默认 | 用途 |
|------|------|------|
| `knowledge_search` | ✅ on | 统一 GraphRAG 检索（快：1 跳图扩展） |
| `deep_knowledge_search` | off（deep 模式开） | 深度检索（2 跳 + 社区/god/surprising + 多轮） |
| `memory_search` | ✅ on | 用户长期记忆 |
| `clarify_user` | ✅ on | 结构化澄清 |
| `datetime` | ✅ on | 时间 |
| `web_search` | off | 外网（需配置） |

**已下线（不再暴露给 agent，文件保留作内部复用）**：`entity_graph_search`、`governed_knowledge_search`、`knowledge_topic_search`、`knowledge_evidence_search`、`knowledge_material_search`、`raw_document_search`。

> 正常模式工具集 = knowledge_search + memory_search + clarify_user + datetime；深度模式叠加 deep_knowledge_search。`knowledge_search` 必须 `default_enabled=True`（否则正常模式无知识工具——这是改造中修过的 bug）。

---

## 7. 配置（.env，新增项）

```
# Stage A 抽取
ENTITY_EXTRACT_MODEL / ENTITY_EXTRACT_WORKERS / ENTITY_EXTRACT_ENABLED
# Step B 分析
GRAPH_ANALYSIS_ENABLED
# P3 检索
RERANK_ENABLED / RERANK_API_BASE / RERANK_API_KEY / RERANK_MODEL / RERANK_TOP_N
GRAPH_EXPAND_FAST_HOPS=1 / GRAPH_EXPAND_DEEP_HOPS=2 / GRAPH_EXPAND_*（预算封顶）
# P5 注入
GRAPH_INSIGHTS_ENABLED / GRAPH_INSIGHTS_TIMEOUT_SECONDS / COMMUNITY_LABEL_MODEL
# P4 治理
GRAPH_GOV_ENABLED / GRAPH_GOV_COHESION_THRESHOLD=0.3
# 基础设施（既有）
NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD / DATABASE_URL / LLM_* / EMBEDDING_*
```

依赖：`graphifyy`（graphify 引擎，Step B/P5/P4 用）。

---

## 8. 关键坑（务必知道）

1. **graphify 的 `god_nodes` 会过滤 concept 节点**（无真实文件路径的节点）→ 对纯实体图返回空。`analyzer.py` 改用 `nx.degree` 自算 god，不要换回 `god_nodes`。
2. **graphify `cluster()` 返回 `{community_id: [node_ids]}`**（社区→成员），`score_all` 返回 `{community_id: cohesion}`（按社区，不是按节点）—— 写回时要注意反转映射。
3. **社区稳定性**：每入库全图重算 Louvain，靠 `_remap_communities`（按与旧社区最大 Jaccard 重叠映射回旧 id）保证 `community_id` 不漂。
4. **community_id/is_god/cohesion 只在 Neo4j**——读 cohesion 用 `graph_community` 表（P5 写），读 community 用 `graph_client.entity_community`，别查 MySQL KnowledgeEntity。
5. **suggest_questions 的 `bridge_node` 类型对 concept 节点无效**（同样被过滤）→ `compute_suggested_questions` 已丢弃该类型，只保留 god/ambiguous。
6. **pytest 必须带 `DATABASE_URL`**（`backend/app/database.py` 导入时建引擎，空则报错）：`DATABASE_URL=sqlite:///./_t.db python -m pytest ...`。
7. **失败隔离是硬约束**：Stage A / 投影 / run_analysis / rerank / 注入 任意失败都只记日志，绝不阻断入库或拖累首字延迟。改这些路径时保持 try/except。
8. **14 个预存测试失败**（改造前就有，根因：mock 过时/fixture 形状/env 依赖，与本次改造无关）—— 跑全量会看到，别误判为新代码引入。
9. **每入库全图 Louvain**：中规模 OK；库很大时会慢，后续可改 dirty-batch（未做）。
10. **chunk 截断**：Stage A `_MAX_CHUNK_CHARS=4000`，超长 chunk 末尾实体可能漏（child chunk 一般 384 token，基本触发不到）。

---

## 9. 跑测试 & 验证

```bash
# 单元（需 DATABASE_URL）
DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_stage_a.py engine/tests/test_graph_analyzer.py \
  engine/tests/test_graph_insights.py engine/tests/test_ckp_governance.py engine/tests/test_unified_retrieval.py \
  engine/tests/test_graph_expand.py engine/tests/test_rerank.py engine/tests/test_agent_tools.py -v

# 端到端（需真实服务）
# 见 docs/superpowers/plans/2026-07-05-p3-stepb-e2e-verification-runbook.md
```

> 单元测试全是 mock（mock LLM、fake GraphClient、sqlite），**不证明真实服务运行正确**。改动后务必跑 e2e runbook 验证 Neo4j 真写了社区/god、检索真用了图扩展。

---

## 10. 待办路线图

| 优先级 | 事项 | 说明 |
|--------|------|------|
| 🔴 高 | **P4a 基础语义治理** | 实现 same_as/supports → stable、contradicts → disputed（spec 有，代码缺）。P4 只做了图信号那一半。 |
| 🟡 中 | 测试欠账 | 清理 14 个预存失败，恢复可信回归网。 |
| 🟡 中 | 多模态入库 | 扫描 PDF OCR（现 file_parser 抽空）、视频 ASR 接进 ingestion。影响真实语料覆盖。 |
| 🟢 低 | 增量分析 | 每入库全图 Louvain → dirty-batch（规模增长后）。 |
| ⚪ 可选 | 多用户租户 / 图谱可视化 UI / 质量评测 | 产品化向。 |

---

## 11. 文档索引

- 主架构 spec：`docs/superpowers/specs/2026-07-03-universal-graph-index-design.md`
- 各阶段 spec：`docs/superpowers/specs/2026-07-05-*.md`（stepA+stepB / p3 / p5 / p4）
- 各阶段 plan：`docs/superpowers/plans/2026-07-*.md`
- 双链路原始设计：`docs/knowledge_architecture_dual_chain_design.md`
- 远程执行指南：`docs/superpowers/REMOTE-EXECUTION-GUIDE.md`
- e2e runbook：`docs/superpowers/plans/2026-07-05-p3-stepb-e2e-verification-runbook.md`

---

## 12. 给后续 Claude 的速查

- 改检索 → 看 `retrieval/unified.py`（编排）+ `graph_expand.py`（图扩展）+ `rerank.py`；`hybrid.py` 是底层 RRF，别动。
- 改图谱分析 → 看 `graph/analyzer.py::run_analysis`；注意 god 用 degree、cluster 返回 {cid:[members]}、社区稳定靠 `_remap_communities`。
- 改对话注入 → 看 `graph/insights.py::graph_insights_context` + `runner._build_messages`（仿 active_recall）。
- 改治理 → 看 `graph/ckp_governance.py`（图信号）+ `services/knowledge_governance.py`（语义，P4a 待补）。
- 改 agent 工具 → `tools/__init__.py` 注册 + `prompts.py` 工具边界（两者必须一致，否则 agent 调不存在的工具）。
- 改入库 → `ingestion/pipeline.py::ingest_item`，末尾的 Stage A/投影/分析全在 `_run_stage_a_for_item`，失败隔离。
- 提交规范：末尾加 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
