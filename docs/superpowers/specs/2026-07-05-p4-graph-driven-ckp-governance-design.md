# P4 图信号驱动的 CKP 状态治理 设计

- 日期：2026-07-05
- 状态：草案（待评审）
- 关联：
  - `docs/superpowers/specs/2026-07-03-universal-graph-index-design.md`（主架构 spec，本文件是其 P4 的细化）
  - `docs/superpowers/specs/2026-07-05-stepA-hardening-stepB-graphify-analysis-design.md`（Step B：community_id/is_god/cohesion，P4 的信号源）
  - `docs/superpowers/specs/2026-07-05-p5-graph-insights-injection-design.md`（P5：`graph_community` 表存 cohesion，P4 读取）

## 1. 背景

探索发现两个事实，重塑了 P4 的定义：

1. **CKP 状态晋升逻辑从未实现。** `CanonicalKnowledgePoint.status` 有 `draft/stable/disputed/deprecated` 四态，但代码里只赋值过 `draft`（创建时）和 `deprecated`（替代时）。双链路 spec 描述的 `same_as≥N→stable`、`contradicts→disputed` 规则**从未落地**——所有 CKP 永远停在 draft。
2. **治理层是活的。** `settle_document_item_to_governance` 由 job worker（`engine/app/jobs/worker.py`）在入库后异步调用，PKU/CKP 确实会被创建；只是创建完就永远 draft。

P4 的范围（已与用户确认）：**只做图信号增强**——用 Step B 产出的社区内聚度（cohesion）与 god 节点信号驱动 `draft→stable` 晋升。基础语义规则（same_as/contradicts）留作 P4a 单独推进。接受：不做 P4a 时，只有满足图信号条件的 CKP 会变 stable，其余仍 draft。

## 2. 已锁定的关键决策（brainstorming 结论）

| 决策 | 选择 |
|------|------|
| P4 范围 | **只做图信号增强**；基础 same_as/contradicts 规则留 P4a。 |
| 状态变更 | `draft → stable`（cohesion/god 驱动）；**只晋不降**（避免抖动）；`→disputed` 留 P4a。 |
| CKP↔Entity 映射 | `CKP.concepts` ∪ `CKP.entities`（JSON）→ 经 `normalize_entity_key` 匹配 `KnowledgeEntity`（含 EntityAlias）。 |
| 信号源 | cohesion：`graph_community` 表（P5 写）；community_id：Neo4j `entity_community`；is_god：Neo4j Entity 节点属性。 |
| 触发点 | `run_analysis` 末尾（Step B 写完社区/god、P5 写完 graph_community 之后）。失败隔离。 |
| 透明性 | 信号 + 原因写 `CKP.extra_meta`（graph_cohesion / god_backed / reason / graph_governed_at）。 |

## 3. 总体行为

```
run_analysis 末尾 → govern_ckp_status_by_graph(db, graph, user_id)
  for each CKP (status != deprecated, user_id):
    1. 映射：CKP.concepts ∪ CKP.entities → KnowledgeEntity（normalized_key，含别名）
    2. 聚合信号：
         cohesion_score = max(graph_community.cohesion[ entity_community(e) ])  over backing entities
         god_backed     = any(Neo4j Entity.is_god == true)                     over backing entities
    3. 写 CKP.extra_meta = {graph_cohesion, god_backed, reason, graph_governed_at}
    4. 晋升（仅 draft→stable，只晋不降）：
         if status == "draft" and (cohesion_score >= THR or god_backed):
             status = "stable"; reason = "graph:cohesion" | "graph:god"
```

无支撑实体映射的 CKP：跳过（extra_meta 不写，状态不变）。

## 4. CKP↔Entity 映射细节

- 取 `CKP.concepts`（list[str]）与 `CKP.entities`（list[str]）并集去重。
- 每个 surface 经 `normalize_entity_key` → 在 `EntityAlias.normalized_key` / `KnowledgeEntity.normalized_key` 中匹配（限 `user_id`）。
- 命中实体 id 集合 = 该 CKP 的 backing entities。
- 复用既有 `entity_resolution.normalize_entity_key`（不重复造）。

## 5. 信号聚合

- `entity_community(e_id)`：Neo4j `GraphClient.entity_community`（Step B 补的读方法）→ `community_id`。
- `cohesion`：查 `graph_community` 表 `(user_id, community_id)` → `cohesion`（P5 写）。无记录 → 0.0。
- `cohesion_score = max(cohesion of distinct backing-entity communities)`；无 backing → 0.0。
- `god_backed`：批量查 Neo4j：对 backing entities 取 `god_neighbors`/或直接读 Entity.is_god。实现用一次性 Cypher：`MATCH (e:Entity) WHERE e.id IN $ids RETURN e.id, e.is_god`（新增 `GraphClient.are_gods(ids) -> dict`）。

## 6. 晋升规则（可配）

```
GRAPH_GOV_ENABLED              默认 True
GRAPH_GOV_COHESION_THRESHOLD   默认 0.3
```
- `draft → stable` 当 `cohesion_score >= THR` 或 `god_backed`。
- 其余状态（stable/disputed/deprecated）**不动**（只晋不降；disputed/deprecated 由 P4a/人工负责）。
- `reason`：`"graph:cohesion(<score>)"` 或 `"graph:god"` 或 `""`（未晋升）。

## 7. 与现有代码的改造点

| 动作 | 文件 | 改什么 |
|------|------|--------|
| 新增 | `engine/app/graph/ckp_governance.py` | `map_ckp_to_entities`、`aggregate_ckp_signals`、`govern_ckp_status_by_graph` |
| 改 | `engine/app/graph/analyzer.py` | run_analysis 末尾（P5 持久化之后、return 之前）调 `govern_ckp_status_by_graph(db, graph, user_id)`，try/except |
| 改 | `backend/app/services/graph_client.py` | 加 `are_gods(ids) -> dict[str,bool]`（一次 Cypher 批量读 is_god） |
| 改 | `engine/app/config.py` | `GRAPH_GOV_ENABLED`、`GRAPH_GOV_COHESION_THRESHOLD` |
| 新增测试 | `engine/tests/test_ckp_governance.py` | 映射/聚合/晋升/不降级/失败隔离 |

**不动**：P3 检索、P5 注入、对话、双链路抽取主流程、CKP 创建逻辑。

## 8. 测试 + 验收

- **映射**：CKP.concepts 命中/未命中/部分命中；别名匹配。
- **聚合**：fake graph + sqlite，`cohesion_score` 取 max、`god_backed` 布尔正确；无 backing → 0.0/False。
- **晋升规则**：
  - cohesion≥THR 的 draft → stable，extra_meta 带 reason。
  - god_backed 的 draft → stable。
  - 低分且非 god 的 draft → 保持 draft。
  - 已 stable 的 → 不变（不降级）。
  - deprecated → 不动。
- **失败隔离**：Neo4j/DB 异常 → govern 不阻断 run_analysis，CKP 状态不变。
- **e2e**：入库（触发 worker 建 CKP + 触发 run_analysis）后，查 CKP：部分从 draft 变 stable，extra_meta 含 graph_cohesion/god_backed。

**验收标准**：
1. 满足图信号条件的 CKP 自动 draft→stable，并在 extra_meta 留痕。
2. 不满足的保持 draft；已 stable 的不回退。
3. `GRAPH_GOV_ENABLED=0` 全程降级，CKP 状态不受图影响。
4. govern 异常不阻断入库/分析。

## 9. 风险与取舍

- **图信号噪声**：纯拓扑晋升（无语义 same_as）可能把松散 CKP 误升 stable。对策：阈值可配；只晋不降避免抖动；P4a 落地后图信号与语义规则会联判（图信号作加分项）。
- **映射稀疏**：CKP.concepts 为空或匹配不上实体时无法治理 → 跳过（不报错）。后续可补图遍历映射（CKP→PKU→Source→Entity）作为兜底，本期不做（YAGNI）。
- **依赖 P5 的 graph_community**：P4 读 cohesion 依赖 P5 已写 graph_community 表。执行顺序：P5 先于 P4（或 P4 在 graph_community 缺失时 cohesion 取 0，仅 god 信号生效——降级安全）。
- **范围纪律**：不做 disputed、不做降级、不做语义 same_as——全部留 P4a。

## 10. 最终原则

1. P4 只做图信号增强；基础语义治理是独立的 P4a。
2. 只晋不降，避免状态抖动。
3. 信号 + 原因写 extra_meta，治理可追溯。
4. 复用 Step B/P5 的产出（community_id/is_god/graph_community），不重复算。
5. 失败隔离：治理绝不阻断入库与分析。
