# P3 统一检索（GraphRAG）设计

- 日期：2026-07-05
- 状态：草案（待评审）
- 关联：
  - `docs/superpowers/specs/2026-07-03-universal-graph-index-design.md`（主架构 spec，本文件是其 P3 §6 的细化）
  - `docs/superpowers/specs/2026-07-05-stepA-hardening-stepB-graphify-analysis-design.md`（Step A+B：P3 的图扩展依赖其产出的社区/god/surprising）
  - `docs/deep_knowledge_search_benchmark_design.md`（P3 回归基准）

## 1. 背景

P1（全覆盖抽取）+ Step A（实体间 `RELATED_TO`）+ Step B（社区/god/cohesion/surprising）已让图谱成为**丰富可导航的底座**。但检索层仍是 4 个并列 agent 工具（`knowledge_search` / `deep_knowledge_search` / `entity_graph_search` / `governed_knowledge_search`），LLM 要在它们之间选择，负担重、易选错或重复检索——这是用户最早提出的核心张力。

P3 把"用哪条检索路径"这个**确定性决策**从 LLM 下沉到一个统一检索编排器，并让检索真正用上图谱（GraphRAG）。agent 只见 2 个工具（快/深），路径选择由编排器按 mode 决定。

## 2. 已锁定的关键决策（brainstorming 结论）

| 决策 | 选择 |
|------|------|
| rerank | **引入** cross-encoder rerank（A）。Jina/Cohere/bge 风格 HTTP，可配 provider；失败降级为只 RRF。 |
| 图扩展深度 | **自适应**（C）。fast=1 跳；deep=2 跳 + 同社区成员 + god 邻居 + surprising 边。 |
| 工具迁移 | 4→2：`entity_graph_search`/`governed_knowledge_search` 的查询逻辑下沉为 `unified.py` 的**内部 helper**，从 agent 工具注册摘掉。 |
| evidence bundle | 复用既有结构（CKP→PKU→Source，带 relation/role/confidence），扩展项加 `surprising` 标记。 |
| 范围 | 本期一次做完（统一编排器 + rerank + 图扩展 + 4→2 + graph_client 读方法）。 |

## 3. 总体架构

新增 `engine/app/retrieval/unified.py::retrieve(query, mode, ...) -> EvidenceBundle`。两个 agent 工具都调它，仅 `mode` 不同：

```
query
 ├─ ① query 理解：抽关键词 → 经 entity_resolution 匹配到图里的 Entity（种子）
 ├─ ② 向量召回：复用 hybrid_search（Milvus 向量 + ES BM25，RRF），Chunk + PKU + CKP 各 top-k
 ├─ ③ 图扩展（自适应，见 §5）：
 │      fast  = 种子 Entity 的 1 跳邻居
 │      deep  = 2 跳 + 同社区成员 + god 邻居 + surprising 边
 │      → 扩展到的 Entity/Source 折算为额外候选 chunk
 ├─ ④ RRF 融合：向量召回 + BM25 + 图扩展候选
 ├─ ⑤ rerank：cross-encoder 重排 top-N（失败降级为跳过）
 └─ ⑥ evidence bundle：CKP→PKU→Source，relation/role/confidence/surprising
```

`entity_graph_search.py` / `governed_knowledge.py` 中的查询函数保留为 `unified.py` 调用的内部 helper（图遍历、CKP/PKU 回源），但**不再是 agent 工具**。

## 4. 两个 agent 工具（4 → 2）

| 工具 | mode | 行为 |
|------|------|------|
| `knowledge_search`（改） | `fast` | 向量+BM25+图1跳 → RRF → rerank → evidence bundle。单轮。 |
| `deep_knowledge_search`（改） | `deep` | 保留多轮 agentic 外壳（检索-判断-再检索），每轮调 `retrieve(mode="deep")`：图2跳+社区/god/surprising → RRF → rerank。 |

`tools/__init__.py`：从 agent 工具注册中摘除 `entity_graph_search` 与 `governed_knowledge_search`（其模块文件与函数保留，供 `unified.py` 复用）。

## 5. 图扩展（核心新逻辑）— `engine/app/retrieval/graph_expand.py`

输入：种子 Entity 列表（来自 ① 的 query 匹配）+ mode + 预算配置。
输出：扩展到的候选 chunk/source 列表（带来源标记：`graph_1hop`/`graph_2hop`/`community`/`god`/`surprising`）。

机制（经 `graph_client` 读 Neo4j）：
- `neighbors(entity_id, hops, limit)`：沿 MENTIONED_IN/RELATED_TO 走 N 跳。
- `community_members(community_id, limit)`：同社区其它实体。
- `god_neighbors(entity_id, limit)`：god 节点的邻居（导航锚点）。
- surprising 边：Step B 写的 `RELATED_TO {surprising:true}`，取其端点。

预算（可配，防噪声/防爆炸）：
```
GRAPH_EXPAND_FAST_HOPS=1
GRAPH_EXPAND_DEEP_HOPS=2
GRAPH_EXPAND_SEED_ENTITIES=10
GRAPH_EXPAND_NEIGHBORS_PER_NODE=8
GRAPH_EXPAND_COMMUNITY_MEMBERS=10   (deep only)
GRAPH_EXPAND_GOD_NEIGHBORS=10        (deep only)
GRAPH_EXPAND_MAX_CANDIDATES=60
```

扩展到的 Entity → 经 MENTIONED_IN 反查其 Source/Chunk → 作为额外候选。折算时记 `来源标记`，供 evidence bundle 与 rerank 参考。

## 6. rerank client — `engine/app/retrieval/rerank.py`

`rerank(query, candidates: list[dict], top_n) -> list[dict]`。
- HTTP 调用，provider 由配置决定（Jina/Cohere/bge-reranker API）。
- **失败降级**：rerank API 不可用/超时 → 记日志、跳过 rerank、原序返回 RRF 结果。检索绝不因 rerank 挂而失败。
- 配置：`RERANK_ENABLED`（默认 True）、`RERANK_API_BASE`、`RERANK_API_KEY`、`RERANK_MODEL`、`RERANK_TOP_N`（默认 20）、`RERANK_TIMEOUT_SECONDS`。

## 7. evidence bundle（复用 + 扩展）

复用既有 evidence bundle 结构。扩展候选项额外带：
- `source_marker`：`vector` / `bm25` / `graph_1hop` / `graph_2hop` / `community` / `god` / `surprising`
- `surprising`：bool（是否来自 surprising 边）
- `community_id`、`is_god`：节点的图属性（来自 Step B）

agent 回答时据此区分"向量命中/图连接命中/surprising 联系"，可显式说"这条来自跨社区隐藏联系"。

## 8. 与现有代码的改造点

| 动作 | 文件 | 改什么 |
|------|------|--------|
| 新增 | `engine/app/retrieval/unified.py` | `retrieve(query, mode, ...)` 编排器 |
| 新增 | `engine/app/retrieval/rerank.py` | cross-encoder rerank client（失败降级） |
| 新增 | `engine/app/retrieval/graph_expand.py` | 种子+邻居+社区+god+surprising → 候选 |
| 改 | `engine/app/agent/tools/knowledge.py` | 改调 `retrieve(mode="fast")` |
| 改 | `engine/app/agent/tools/deep_knowledge_search.py` | 每轮改调 `retrieve(mode="deep")`（保留多轮外壳） |
| 改 | `engine/app/agent/tools/__init__.py` | 摘除 entity_graph_search/governed_knowledge 的 agent 工具注册 |
| 改 | `backend/app/services/graph_client.py` | 加读方法 `neighbors`/`community_members`/`god_neighbors`/`surprising_endpoints` |
| 改 | `engine/app/config.py` | rerank 配置 + 图扩展预算配置 |
| 改（可选） | `engine/app/agent/tools/entity_graph_search.py`、`governed_knowledge.py` | 把查询函数导出为可复用 helper（无功能变更，仅供 unified 调用） |

**不动**：`runner.py`（agent 循环）、`retrieval/hybrid.py`（RRF，被复用）、Stage A / Step B 写入路径、前端。

## 9. 测试 + 验收

- **单元**：
  - query→Entity 匹配（含归一/别名）。
  - 图扩展：fast=1跳 / deep=2跳+社区+god+surprising（fake graph，断言候选来源标记正确、预算封顶生效）。
  - rerank：成功重排 + 失败降级（mock HTTP 抛错 → 原序返回，不抛）。
  - RRF 融合含图扩展候选。
  - evidence bundle 组装（source_marker/surprising/community_id 字段）。
- **集成**：fast/deep 两路径端到端（mock LLM + mock rerank + fake graph + sqlite）。
- **回归**：用现有 `deep_knowledge_search` benchmark（`docs/deep_knowledge_search_benchmark_design.md`）跑前后比对——同问题集召回率/连接发现 ≥ 现状；并统计 agent 工具调用数应下降（4→2 后不再出现 entity_graph/governed 工具调用）。

**验收标准**：
1. agent 只调用 `knowledge_search`/`deep_knowledge_search`（不再调 entity_graph/governed）。
2. 同问题召回率 ≥ 现状，跨文档连接发现（图扩展命中）> 现状。
3. rerank 不可用时检索仍正常（降级）。

## 10. 风险与取舍

- **图扩展噪声**：扩展候选可能引入弱相关内容。对策：预算封顶 + rerank 兜底 + `source_marker` 透明可追溯。
- **延迟**：rerank + 图扩展各加一次往返。对策：fast 模式只 1 跳 + rerank top_n 限 20；deep 模式本就允许更慢。
- **rerank 依赖**：需额外 API key/成本。对策：`RERANK_ENABLED=False` 可全局降级为纯 RRF。
- **图扩展读 Neo4j**：每次检索多次 Neo4j 查询。对策：种子实体封顶 + 邻居封顶 + 单次检索内复用结果。
- **范围纪律**：本期不做 P5（洞察接入对话文案）、不做 P4（社区驱动治理），只把检索统一并接上图。

## 11. 最终原则

1. 检索路径选择是确定性逻辑，下沉到编排器，LLM 不做路由。
2. 图扩展让"跨文档连接"成为一等检索信号（GraphRAG）。
3. rerank 提精度，但永远可降级，不阻断检索。
4. evidence bundle 透明标注每条证据的来源（向量/图/社区/surprising）。
5. agent 工具从 4 收 2，选择负担消除。
