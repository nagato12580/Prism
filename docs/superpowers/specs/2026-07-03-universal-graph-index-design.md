# 统一全图索引设计：从「精选治理」到「全覆盖图谱底座」

- 日期：2026-07-03
- 状态：草案（待评审）
- 关联文档：
  - `docs/knowledge_architecture_dual_chain_design.md`（双链路 PKU/CKP 治理设计）
  - `docs/superpowers/specs/2026-06-18-dual-chain-knowledge-governance-implementation.md`
  - `docs/superpowers/specs/2026-06-20-document-chunk-pku-extraction-design.md`

## 1. 背景与动机

当前 Prism 的知识图谱层基于 PKU/CKP 双链路治理：

```
DocumentSource / PersonalAssetItem → PersonalKnowledgeUnit(PKU) → CanonicalKnowledgePoint(CKP)
```

这套治理是「精选」式的：只有能被抽成原子知识点（PKU）并归一（CKP）的内容才进入图谱层。结果是：

- 大量个人碎片、文档细节抽不出干净的 PKU，**只落在向量检索里，不在图中**。
- 这些内容无法被图遍历到达，无法体现跨文档连接，丧失了「图」的连接与导航价值。
- 检索面因此分裂为 4 个并列工具（`knowledge_search` / `deep_knowledge_search` / `entity_graph_search` / `governed_knowledge_search`），agent 选择负担重、易选错或重复检索。

### 目标

把图谱层从「被治理的规范知识层」升级为**万物皆可索引的通用底座**（graphify 式全覆盖），同时**保留**双链路治理的精华（modality/polarity 区分、same_as 归一、evidence 回源）。

一句话原则：

> **图是统一的连接组织，不是精选展厅。Entity 抽取对每一条 Source/Chunk 都是强制的——不管能不能抽出 PKU，它提到的实体必定进图、必定挂边。**

### 非目标

- 不替换 Neo4j 为其它图存储。
- 不废弃 PKU/CKP 双链路治理，而是把它降级为「全图中的被治理子图」。
- 不在本期做多用户隔离（沿用现有「全局共享单库」，多租户作为预留扩展面）。

## 2. 总体架构

两个 LLM 代理 + API 层确定性路由：

```
                       ┌──── API 确定性路由 ────┐
                       │                        │
        /api/v1/chat   │                        │  /api/v1/ingest
                       ▼                        ▼
            ┌─ 对话代理(现有)─┐        ┌─ 图谱维护代理(新)─────────────┐
            │ LangChainAgent  │        │ LangGraph 编排                │
            │ 统一检索编排器   │        │  抽取子代理 fan-out(graphify) │
            │ (向量+图扩展)    │        │  → 归一 → graphify 分析       │
            └─────────────────┘        │  → 诊断门 → 写 Neo4j          │
                                       └───────────────────────────────┘
                                          shared: Neo4j(存取) + graphify(分析)
```

- **Neo4j = 存取与运行时查询**（保留，多用户就绪）。
- **graphify = 批量分析与治理**（borrow 算法，NetworkX 图临时构建，分析完写回 Neo4j 即弃）。
- **抽取 = LangChain 子代理 fan-out**，按 graphify extraction-spec 输出 JSON。

不设「全局 LLM 路由代理」：入库与聊天本就是两条 API，路由用代码判断即可，省下的成本花在抽取子代理与对话检索上。

## 3. 统一全图的节点与边模型（§1）

复用现有 `graph_client.py` 中的 label（CKP/PKU/Source/Entity/Alias），新增 `:Chunk`。

### 节点

| Label | 是什么 | 覆盖策略 |
|-------|--------|---------|
| `:Source` | 每个文档/个人资产（万物入口） | 强制：每条入库必有 |
| `:Chunk` | 文档切片（Source 子节点） | 强制：每个 chunk 必有 |
| `:Entity` | graphify 式抽取的实体（人/机构/概念/术语/方法…） | **强制全量**：每个 Source/Chunk 都抽 |
| `:Alias` | 实体表面变体 | 跟 Entity 走 |
| `:PKU` | 原子知识单元 | 保留为子集：抽得到才建（精选） |
| `:CKP` | 规范知识点 | 保留为子集：归一后才建（精选） |

关键：PKU/CKP 不再是「进图的门槛」，而是图里**被打上治理标签的子集节点**。抽不出 PKU 的碎片，仍以 `:Source`+`:Entity` 存在于图中。

### 边

**全覆盖连接（graphify 式，强制）：**
- `(:Source)-[:HAS_CHILD]->(:Chunk)`（已有）
- `(:Chunk)-[:MENTIONS_ENTITY]->(:Entity)`（已有，**强制**：每个 chunk 必挂）
- `(:Source)-[:ABOUT_ENTITY]->(:Entity)`（已有，**强制**：每个 source 必挂）
- `(:Entity)-[:RELATED_TO]->(:Entity)`（新增：graphify 式 INFERRED 关系、共现、社区边）

**治理与回源（保留）：**
- `(:PKU)-[:EVIDENCED_BY]->(:Chunk|:Source)`
- `(:PKU)-[:SUPPORTED_BY|:CONTRADICTS]->(:CKP)`（已有）
- `(:CKP)-[:USES|:PART_OF|:REFINES]->(:CKP)`（已有）
- `(:Entity)-[:ALIAS_OF]->(:Entity)` 经 Alias（已有）

### `graph_client.py` 允许的标签/关系集需扩展

- 新增 label：`:Chunk`
- 新增/确认强制关系：`MENTIONS_ENTITY`、`ABOUT_ENTITY`、`RELATED_TO` 已在白名单。
- 节点新增属性：`community_id`、`is_god`、`cohesion`（由 graphify 分析层回写）。

## 4. 抽取管线：两段式 + 增量（§2）

```
Source 入库
  ├─ 切 Chunk（MySQL，已有）
  └─ 对每个 Chunk：
       ┌─ Stage A【强制·graphify 式】Entity + 关系抽取（子代理 fan-out）
       │    → 每个 chunk 必出 Entity，必挂 MENTIONS_ENTITY/ABOUT_ENTITY
       │    → 保证全图覆盖，哪怕 Stage B 空手而归
       └─ Stage B【精选·保留现有逻辑】PKU 抽取 → 归一到 CKP
            → 抽得到才建 PKU/CKP；抽不到也已在图中（Stage A）
```

### Stage A 抽取内容（graphify spec）

每个 chunk 抽：
- Entity 列表（人/机构/概念/术语/方法/产品，带 entity_type）
- Entity 间关系 `RELATED_TO` + 属性（三档置信度：EXTRACTED/INFERRED/AMBIGUOUS；confidence_score 取自离散集合，禁用 0.5）
- chunk→Entity 边：`MENTIONS_ENTITY`（显式提到）/`ABOUT_ENTITY`（核心主题）
- 节点 ID 规则：`{相对路径}_{实体名}` 全小写、仅 `[a-z0-9_]`，保证幂等与增量一致。

### 增量（高频增量命脉）

1. `content_hash` 命中 → 整体跳过（幂等，已有机制）。
2. 未命中 → 仅对该文件 chunk 重抽 Stage A + Stage B。
3. 边 diff：对比旧 Entity 边集合 vs 新集合；新增 MERGE、消失删除（避免幽灵边）。
4. entity_resolution 增量跑：新 Entity 尝试并入已有 Entity。

### 成本控制

- Stage A 用便宜快模型（实体抽取不需最强模型），Stage B/对话用强模型。
- chunk 批处理（5–10 一批，降低调用次数）。
- 抽取结果按 `content_hash` 缓存。

## 5. graphify 引擎深度整合（§2′/§3′）

### 角色分工（避免双图并存）

- **抽取层**：LangChain 子代理 fan-out → 产出 graphify schema JSON（统一契约）。
- **graphify 分析层（批处理，临时 NetworkX 图）**：`build_from_json` → `cluster` → `god_nodes` / `surprising_connections` / `diagnostics`。
- **Neo4j 存取层（运行时）**：`graph_client` 写入节点/边，承载 agent 检索/图遍历/多用户事务。

NetworkX 图是临时的，分析完写回 Neo4j 即弃，**不与 Neo4j 并存为第二存储**。

### graphify 能力复用清单

| graphify 能力 | 在 Prism 里干什么 |
|---------------|------------------|
| `build_from_json` | 把子代理产出 JSON 建临时 NetworkX 图 |
| `cluster`（Louvain） | 社区发现 → Neo4j 节点打 `community_id` |
| `god_nodes` | 枢纽节点 → 打 `is_god`，作 agent 导航锚点 |
| `surprising_connections` | 跨社区 surprising 边 → 写回 Neo4j 当「隐藏联系」 |
| `diagnose_extraction` | 抽取后健康检查（自环/悬空/塌缩）→ 治理质量门 |
| `suggest_questions` | 给 agent 生成「这张图能回答什么」引导 |

### schema 适配层（graphify ↔ Neo4j）

薄映射层 `engine/app/extraction/graphify_adapter.py`：
- `file_type=concept/rationale` → `:Entity` 或 `:CKP`（按是否归一）
- `relation=references/cites` → `:RELATED_TO` / `:SUPPORTED_BY`
- `relation=semantically_similar_to` → `:RELATED_TO {confidence}`
- graphify `hyperedge` → 社区或多元关系

## 6. 检索融合：4 工具 → 2 工具（§3）

LLM 不决定「用哪条检索路径」，路径选择下沉到统一检索编排器。

### 统一检索编排器 `retrieve(query, mode)`

```
query
 ├─ ① Query 理解：抽 Entity/关键词
 ├─ ② 向量召回（多层）：Chunk + PKU + CKP 各 top-k（Milvus，已有）
 ├─ ③ 图扩展（全图遍历）：对命中 Entity/CKP 走 1~2 跳
 │      MENTIONS_ENTITY / RELATED_TO / SUPPORTED_BY|CONTRADICTS
 ├─ ④ RRF 融合 + rerank（复用 retrieval/hybrid.py）
 └─ ⑤ Evidence Bundle 返回（双链路设计 §18 结构）：
       CKP → 关联 PKU → 原始 Source/Chunk，带 relation_type/role/confidence
```

### agent 可见工具（4 → 2）

| 工具 | 何时用 | 内部 |
|------|--------|------|
| `knowledge_search` | 默认，快 | 向量召回 + 图 1 跳 |
| `deep_knowledge_search` | 复杂/跨源/矛盾 | 多轮迭代 + 图 2 跳 + 主动澄清 |

`entity_graph_search` 与 `governed_knowledge_search` 不删除，降级为编排器内部模式/子步骤。

### 检索策略自动分流（双链路设计 §13）

- 细节问题（原话/参数）→ 偏向 Chunk/Source 召回。
- 复杂问题（观点变化/矛盾）→ 偏向 CKP 关系图 + 多源并行。
- 分流由编排器按 query 特征决定，不靠 LLM 猜工具。

## 7. 代理拓扑（§6）

- **图谱维护代理（新）**：LangGraph 编排，内部为「抽取子代理 fan-out → 归一 → graphify 分析 → 诊断门 → 写 Neo4j」。由 `/api/v1/ingest` 触发，异步后台执行。
- **对话代理（现有，增强）**：检索换成统一编排器，其余不动。
- **全局编排**：API 层确定性路由 + 共享上下文（用户/库/权限），不单设 LLM 路由代理。

## 8. 与现有代码的改造点（§4）

| 动作 | 文件 / 模块 | 改什么 |
|------|------------|--------|
| 新增 | `engine/app/extraction/subagent_extractor.py` | LangGraph `Send` map-reduce，每 chunk 一子代理，graphify spec |
| 新增 | `engine/app/extraction/graphify_adapter.py` | graphify JSON ↔ Neo4j schema 映射 |
| 新增 | `engine/app/graph/analyzer.py` | 封装 graphify build/cluster/god/surprising/diagnostics，写回 Neo4j |
| 新增 | `engine/app/retrieval/unified.py` | 统一检索编排器 |
| 改 | `backend/app/services/entity_extraction.py` | 从可选增强升级为强制 Stage A，核心改用子代理 fan-out |
| 改 | `backend/app/services/graph_client.py` | 加 `:Chunk` label；节点加 `community_id`/`is_god`/`cohesion`；加批量写、边 diff |
| 改 | `engine/app/agent/tools/__init__.py` | `entity_graph_search`/`governed_knowledge_search` 降级为内部模式；agent 只暴露 2 工具 |
| 改 | `engine/app/ingestion/pipeline.py` | 插入强制 Stage A + 入库后触发 graphify 分析批处理 |

**不动**：`runner.py`（agent 循环）、`retrieval/hybrid.py`（RRF）、双链路 PKU/CKP 归一逻辑、记忆系统、前端。

## 9. 分阶段交付（§5）

| 阶段 | 做什么 | 验证标准 |
|------|--------|---------|
| P1 全覆盖抽取 | Stage A 强制子代理抽取 → 每个 chunk 挂 Entity 边 | 之前「没进图」的碎片能被图遍历到达 |
| P2 graphify 分析层 | cluster/god/surprising/diagnostics 跑通，写回 Neo4j | 节点带 community_id；诊断门告警塌缩边 |
| P3 统一检索 | 统一编排器上线，4 工具 → 2 工具 | 同问题召回率/连接发现 ≥ 现有 deep_search，工具调用数下降 |
| P4 社区驱动治理 | cohesion + god 参与 CKP 状态判定；诊断门卡增量 | disputed/stable 判定有图信号依据 |
| P5 洞察接入对话 | suggest_questions、god 导航、surprising 连接进 agent | agent 能主动提示「这张图还藏着 X 联系」 |

P1 为地基（全覆盖），先跑通，后续均为加法。

## 10. 风险与取舍

- **Entity 全量抽取 → Neo4j 节点数上涨**：中规模可接受；需监控并预留社区/索引优化（P2）。
- **graphify 与 Neo4j 一致性**：NetworkX 图为临时分析用，单一写入方向（分析层 → Neo4j），避免双向同步复杂度。
- **子代理抽取成本**：高频增量下用便宜模型 + 批处理 + content_hash 缓存控制。
- **schema 适配层维护**：graphify 升级时需同步映射表；版本锁定 graphify。
- **检索行为变更**：4→2 工具是 agent 行为变更，P3 需用 `deep_knowledge_search` benchmark 做回归比对。

## 11. 最终架构原则

1. 图是统一连接组织，不是精选展厅。
2. Entity 抽取对所有 Source/Chunk 强制（全覆盖）。
3. PKU/CKP 是全图中的被治理子图，不是进图门槛。
4. Neo4j 存取，graphify 分析，不并存第二图存储。
5. 抽取派子代理并行完成。
6. 三档置信度统一取代散落的 confidence 写法。
7. LLM 不做确定性路由（路径选择下沉到编排器）。
8. 原文不丢、来源不混、回答必回源（继承双链路原则）。
