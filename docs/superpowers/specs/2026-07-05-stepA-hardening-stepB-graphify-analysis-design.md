# Step A 收尾加固 + Step B graphify 分析层 设计

- 日期：2026-07-05
- 状态：草案（待评审）
- 关联：
  - `docs/superpowers/specs/2026-07-03-universal-graph-index-design.md`（主架构 spec，本文件是其 P2 + 收尾项的细化）
  - `docs/superpowers/plans/2026-07-03-p1-universal-entity-extraction.md`（P1 已实现）
  - P1 最终整体评审的开放项 I1 / I2 / M1

## 1. 背景

P1（提交至 `1da70a7`）实现了 Stage A 全覆盖实体抽取：每个入库 chunk 经 LLM 抽取实体，写入 MySQL 并投影到 Neo4j `MENTIONED_IN` 边。P1 最终整体评审留下三个开放项，且 graphify 引擎复用（主 spec P2）尚未实现。本 spec 把这两块作为一个连续推进：

- **Step A（收尾加固）**：补 I2 / I1 / M1，让图谱在重入库时干净、并具备实体间连接组织（为 Step B 社区发现提供 richer edges）。
- **Step B（graphify 分析层）**：复用 graphify 的 cluster/god_nodes/surprising_connections/diagnostics，把"一堆 MENTIONED_IN 边"升级为"有社区、有枢纽、有洞察的可导航图谱"，写回 Neo4j。

## 2. 已锁定的关键决策（brainstorming 结论）

| 决策 | 选择 |
|------|------|
| graphify 分析节奏 | **每入库增量**（B）。全图 Louvain 重算，中规模亚秒~秒级，可接受。 |
| 分析数据源 | **从图存储导出**（A）。MySQL 为单一真相源，无需额外持久化 extraction JSON。 |
| 社区稳定性 | **全量重算 + 稳定重映射**（①）。新社区按与旧社区最大节点重叠映射回旧 `community_id`，全新社区才分配新 id。 |
| 诊断门 | 非破坏性：记日志/告警，不阻断入库（与 P1 失败隔离一致）。 |
| Step A→B 顺序 | 连续推进；A 先（为 B 提供连接组织与干净地基）。 |

## 3. Step A 设计

### 3.1 A1 — Neo4j 侧重入库清理（I2，正确性）

P1 的 C1 修复只清了 MySQL 侧孤儿 `EntityMention`。Neo4j 侧重入库仍会累积指向已删 chunk 的僵尸 `Source` 节点与 `MENTIONED_IN` 边。

**做法**：在 `backend/app/services/graph_projection.py::project_item_entities` 投影**之前**，先按 item 删除该 item 在 Neo4j 的旧 Source 节点及其边：

```cypher
MATCH (s:Source {item_id: $item_id}) DETACH DELETE s
```

然后重新投影（upsert Source/Entity + MENTIONED_IN）。该 Cypher 幂等：删完重建，保证无僵尸。封装为 `graph_client` 新方法 `delete_item_sources(item_id)` 或直接在 projection 内通过 driver 执行。

### 3.2 A2 — 接回实体间关系（I1，连接组织）

P1 为避免浪费 LLM 调用裁掉了 prompt 的 `relations`。现在接回，让图谱获得 Entity↔Entity `RELATED_TO` 边——这是 Step B 社区发现聚出有意义群组的关键（光靠 Source→Entity 星型边，社区很贫瘠）。

- `engine/app/extraction/prompts.py`：`STAGE_A_EXTRACTION_PROMPT` 加回 `relations` 数组（subject/predicate/object/tier/score），输出格式恢复 `{"entities":[...], "relations":[...]}`（注意 `{{ }}` 转义）。
- `parse_stage_a_json`：返回结构改为同时携带 entities 与 relations（新增 `parse_stage_a_relations(raw)` 或扩展返回值为命名元组/dict）。
- `engine/app/extraction/stage_a.py`：新增 `_to_relation_candidate`，把 relation dict 造为 `EntityCandidate(kind="relation", subject_surface, predicate, object_surface, object_entity_type, confidence=score, evidence_span, extraction_method=f"llm_stage_a:{tier}")`。`extract_entities_for_chunk` 返回 `entities + relations` 合并的候选列表。
- **关键代码改动**：`backend/app/services/entity_extraction.py::_resolve_entity_for_relation` 当前把 subject 硬编码为 `entity_type="person"`——泛化为"按 surface 文本跨所有 entity_type 解析"（先查 `settled_by_surface` 任意类型，再按 normalized_key 查库），使 concept↔concept 关系能落库。
- `project_item_entities`：增量投影该 item 的 `EntityRelation` → Neo4j `RELATED_TO`（`graph_client` 白名单已有 `RELATED_TO`；未知 predicate 映射为 `RELATED_TO`）。

### 3.3 A3 — confidence 默认值（M1）

`backend/app/services/entity_extraction.py::EntityCandidate.confidence` 与模型列默认 `0.5`（Stage A 禁止值）→ 改 `0.0`。Stage A 始终显式赋值，故不影响新路径；只是消除"忘记赋值就落入禁止值"的隐患。

## 4. Step B 设计

### 4.1 新模块 `engine/app/graph/analyzer.py`

封装 graphify 复用。核心函数 `run_analysis(db, graph_client, user_id) -> AnalysisResult`，在 `_run_stage_a_for_item` 投影完成后调用（每入库，全图）。流程：

```
① export_graph_for_graphify(db, user_id) -> {nodes, edges}
     - 节点 = KnowledgeEntity（id, label=canonical_name, file_type="concept"）
     - 边来源二：
         a) 显式 EntityRelation（RELATED_TO 等）→ 边
         b) 共现边：同一 Source 提及的两个 Entity → 加一条边（weight=共现次数）
       ↑ 共现边把 Source-Entity 二部图投影为 Entity-Entity 同质图，
         这是社区发现能聚出有意义群组的关键。
② graphify.build.build_from_json(exported, directed=False) -> NetworkX Graph
③ graphify.cluster.cluster(G) -> {node_id: community_id}
④ 稳定重映射：
     - 先读 Neo4j 中 Entity 节点的旧 community_id
     - 对每个新社区，按与旧社区的最大节点重叠（Jaccard）映射回旧 id
     - 全新社区分配新 id（当前最大 id + 1）
⑤ graphify.analyze.god_nodes(G) -> [node_id]
⑥ graphify.analyze.surprising_connections(G, communities) -> [edges]
⑦ graphify.diagnostics.diagnose_extraction(exported) -> report（记日志，不阻断）
⑧ 写回 Neo4j：
     - Entity 节点 SET community_id, is_god, cohesion（cohesion 来自 graphify.score_all）
     - surprising 边：MERGE (a)-[:RELATED_TO {surprising:true}]->(b)
```

NetworkX 图临时构建，分析完写回即弃——**不并存第二图存储**（主 spec §5）。

### 4.2 触发点与失败隔离

- 触发：`engine/app/ingestion/pipeline.py::_run_stage_a_for_item`，在 `_project_item_entities_to_graph` 之后调用 `run_analysis`，置于既有 `try/except` 内。LLM/图分析任意异常只记日志、不阻断入库（沿用 P1 隔离模式）。
- 新增配置 `GRAPH_ANALYSIS_ENABLED`（默认 True）。`False` 时短路。

### 4.3 依赖

`requirements.txt` 增加 `graphifyy`。远程执行机器需 `pip install graphifyy`（已验证本机 Python 可导入 graphify；其依赖 networkx，graspologic 可选，缺失则 graphify 回退 NetworkX Louvain）。

### 4.4 schema 适配层

`export_graph_for_graphify` 产出的 JSON 直接符合 graphify `{nodes, edges}` schema（node: id/label/file_type；edge: source/target/relation/confidence/confidence_score）。无需独立适配模块——导出函数即适配层。

## 5. 数据流（Step A + B 合并后的入库）

```
ingest_item
 ├─ chunk → embed → MySQL/Milvus/ES（已有）
 ├─ Stage A 抽取（entities + relations）[fan-out]              ← A2 接回 relations
 ├─ 清理：MySQL 旧 mention（P1 C1）+ Neo4j 旧 Source（A1）      ← A1 新增
 ├─ settle_entity_candidates → MySQL Entity/Mention/Relation   ← A2 泛化 resolver
 ├─ project_item_entities → Neo4j MENTIONED_IN + RELATED_TO    ← A2 投影 relations
 └─ run_analysis（全图）                                         ← Step B 新增
      export → graphify build → cluster → 稳定重映射
      → god_nodes → surprising → diagnostics
      → 写回 community_id / is_god / cohesion / surprising 边
```

## 6. 与现有代码的改造点

| 动作 | 文件 / 模块 | 改什么 |
|------|------------|--------|
| 新增 | `engine/app/graph/__init__.py`、`engine/app/graph/analyzer.py` | graphify 复用：export/build/cluster/重映射/god/surprising/diagnostics/写回 |
| 改 | `backend/app/services/graph_projection.py` | A1：投影前删 item 旧 Source；A2：project_item_entities 增量投影 EntityRelation |
| 改 | `backend/app/services/graph_client.py` | A1：加 `delete_item_sources(item_id)`（或暴露 Cypher 执行） |
| 改 | `backend/app/services/entity_extraction.py` | A2：泛化 `_resolve_entity_for_relation`；A3：confidence 默认 0.0 |
| 改 | `engine/app/extraction/prompts.py` | A2：加回 relations；保持 `{{ }}` 转义 |
| 改 | `engine/app/extraction/stage_a.py` | A2：解析 relations + `_to_relation_candidate`；返回合并候选 |
| 改 | `engine/app/ingestion/pipeline.py` | Step B：`_run_stage_a_for_item` 末尾调 `run_analysis`（失败隔离） |
| 改 | `engine/app/config.py` | 新增 `GRAPH_ANALYSIS_ENABLED` |
| 改 | `requirements.txt` | 加 `graphifyy` |

**不动**：`runner.py`（agent 循环）、对话/检索工具（P3 再动）、PKU/CKP 归一逻辑、前端。

## 7. 测试策略

- **A1**：重入库后 Neo4j 无僵尸 Source（fake graph 记录 delete 调用）。
- **A2**：relation 候选经 settle 落 EntityRelation；`_resolve_entity_for_relation` 能解析非 person 类型；`project_item_entities` 投影 RELATED_TO。
- **A3**：EntityCandidate 默认 confidence 为 0.0。
- **B（export）**：export 产物含共现边；schema 合法。
- **B（稳定重映射）**：连续两次 run_analysis，相同节点 community_id 不漂；新增节点落入合理社区。
- **B（写回）**：Neo4j Entity 节点带 community_id/is_god；surprising 边带 `surprising:true`。
- **B（失败隔离）**：graphify 异常不阻断 ingest_item。
- 全程 mock LLM（A2 relations）、fake GraphClient、sqlite；graphify 用真实库跑（确定性算法）。

## 8. 分阶段交付（一个计划内两步）

| 阶段 | 内容 | 验证 |
|------|------|------|
| Step A | A1/A2/A3 | 重入库无僵尸；实体间 RELATED_TO 边存在；confidence 默认 0.0 |
| Step B | analyzer + 接入 | Entity 带 community_id/is_god；surprising 边；二次分析 community_id 稳定；graphify 异常不阻断入库 |

## 9. 风险与取舍

- **每入库全图分析的成本**：中规模可接受；若规模增长，可加 `GRAPH_ANALYSIS_ENABLED` 或改为 dirty-batch（留作后续，不在本期）。
- **社区重映射的边界**：图剧烈变化时映射可能不完美，但保证"老社区 id 尽量稳定、新社区给新 id"的契约。
- **共现边膨胀**：高频共现实体对可能产生大量边；导出时按 weight 截断（top-N）或设最小共现阈值（实现时定，默认 min=1）。
- **graphify 依赖**：远程机器需联网安装；graspolic ANSI 输出在 Windows 旧终端的滚动问题（graphify v0.3.10+ 已抑制）。
- **范围纪律**：本期不接入对话/检索（P3）、不做社区驱动治理（P4），只把图谱变丰富+可分析。

## 10. 最终原则

1. 图存储（MySQL/Neo4j）是唯一真相源；graphify 分析只读它、写回它。
2. 每入库增量分析，但 community_id 稳定（重映射）。
3. 共现边是社区发现的关键输入（Entity-Entity 同质图）。
4. 所有新增路径失败隔离，不阻断入库。
5. Step A 为 Step B 提供连接组织（relations）与干净地基（Neo4j 清理）。
