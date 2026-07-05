# P5 洞察接入对话设计

- 日期：2026-07-05
- 状态：草案（待评审）
- 关联：
  - `docs/superpowers/specs/2026-07-03-universal-graph-index-design.md`（主架构 spec，本文件是其 P5 的细化）
  - `docs/superpowers/specs/2026-07-05-stepA-hardening-stepB-graphify-analysis-design.md`（Step B：社区/god/cohesion/surprising，P5 的数据来源）
  - `docs/superpowers/specs/2026-07-05-p3-unified-graphrag-retrieval-design.md`（P3：`match_seed_entities` 复用）

## 1. 背景

P1（全覆盖抽取）+ Step A（实体间关系）+ Step B（社区/god/cohesion/surprising）+ P3（统一 GraphRAG 检索）已让图谱成为丰富底座、检索已用上图。但图谱里**已经算好的洞察**（跨社区隐藏联系 surprising、枢纽 god 节点、可追问的问题）**还没有主动到达用户**——用户得自己问对问题才能发现。P5 把这些洞察以**被动注入**的方式交给 agent，让它在回答时能主动提示"这张图还藏着 X 联系 / 你还可以追问 Y"。

## 2. 已锁定的关键决策（brainstorming 结论）

| 决策 | 选择 |
|------|------|
| 交付机制 | **注入**（A）—— 仿 `active_recall`，`graph_insights_context(query)` 返回背景块注入 system prompt；信号门控 + try/except，无命中返回空串，绝不拖累首字延迟。 |
| 洞察范围 | **god + surprising + suggest_questions**（A+B）。 |
| suggest_questions | graphify 结构化生成（无 LLM）；不用其桥接节点分支（会过滤 concept 节点），用 god-with-INFERRED / AMBIGUOUS 边 / surprising 端点。 |
| 社区标签 | 在 run_analysis 末尾用**1 次便宜 LLM 调用**为每个社区生成 ≤6 字标签，存 `graph_community` 表；解锁可读的 surprising/suggest_questions 与未来 P4 治理。 |
| 触发 | 信号门控（探索性/概念性问题才触发），避免每轮都查 Neo4j。 |

## 3. 总体架构

仿 `engine/app/agent/active_recall.py::recall_memory_context`：

```
runner._build_messages
 ├─ SystemMessage(system_prompt)
 ├─ SystemMessage(recall_memory_context(query))      # 既有：记忆
 ├─ SystemMessage(graph_insights_context(query))     # P5 新增：图洞察
 └─ ...history, HumanMessage(query)
```

`graph_insights_context(query, user_id) -> str`：
- 信号门控（不触发 → `""`）。
- 复用 P3 的 `match_seed_entities` 把 query 映射到 seed Entity → 其 `community_id`。
- 读 Neo4j（surprising 边端点、god 标记）+ `graph_community` 表（社区标签、suggested_questions）。
- 拼背景块；无命中 → `""`。
- 全程 try/except，超时/异常 → `""`。

## 4. run_analysis 扩展（补算洞察）

在 `engine/app/graph/analyzer.py::run_analysis` 末尾（写回 community_id/is_god 之后）追加：

### 4.1 社区标签（1 次便宜 LLM）
- 对每个社区：取其 top-N 实体 `canonical_name`，喂给便宜 LLM（`COMMUNITY_LABEL_MODEL`，默认复用 `ENTITY_EXTRACT_MODEL` 或 `LLM_MODEL`）。
- prompt：`"用一个≤6字中文短语概括这组知识主题：{实体列表}"`。
- 结果写 `graph_community.label`。

### 4.2 suggest_questions（结构化，无 LLM）
- 调 `graphify.analyze.suggest_questions(G, communities, community_labels, top_n)`（实测：结构化、无 LLM）。
- 只保留对实体图有效的类型：`god`（高 INFERRED 度）、`ambiguous_edge`、surprising 相关；丢弃被 concept 过滤的 `bridge_node`。
- 写 `graph_community.suggested_questions`（JSON 数组，按 community 分桶）。

> 网络图临时（NetworkX），分析完即弃，不并存第二存储（沿用 Step B 原则）。

## 5. 数据模型

新增 `backend/app/models/graph_community.py`：

```text
graph_community
  id            string pk
  user_id       string index
  community_id  int          # 与 Neo4j Entity.community_id 对应
  label         string       # ≤6字中文标签
  cohesion      float        # 来自 score_all（冗余存，注入时免查 Neo4j）
  suggested_questions  json  # [{type, question, why}, ...]
  updated_at    datetime
  unique(user_id, community_id)
```

注册到 `backend/app/models/__init__.py`，由 `auto_migrate`（CREATE TABLE IF NOT EXISTS）建表。

## 6. 注入逻辑细节

`engine/app/graph/insights.py::graph_insights_context(query, user_id="default-user") -> str`：

1. **门控**：`has_insight_signal(query)` —— 含概念/探索信号词（如"关系/联系/区别/还有/相关/为什么/怎么"等）或 query 命中 seed entity 才触发；否则 `""`。
2. **seed**：`match_seed_entities(db, query)` → seed entity ids（封顶 `GRAPH_INSIGHTS_SEED_ENTITIES`，默认 6）。
3. **community**：seed entity 的 `community_id`（Neo4j 读，或 graph_client.entity_community）。
4. **收集**：
   - surprising：`graph_client.surprising_endpoints(seed)` → 对端实体 canonical_name + note。
   - god：该 community 的 god 实体（Neo4j `is_god=true` 且同 community）。
   - questions：`graph_community.suggested_questions` 里该 community 的前 2 条。
5. **拼块**（无命中 → `""`）：
   ```
   【图谱洞察】
   - 隐藏联系：<A> 与 <B> 存在跨主题关联（surprising）
   - 枢纽节点：<C>（多个概念围绕它）
   - 可追问：<问题1>；<问题2>
   回答时可参考这些联系，并在合适时主动提示用户。
   ```
6. try/except + 超时（`GRAPH_INSIGHTS_TIMEOUT_SECONDS`，默认 3.0）→ `""`。

## 7. 与现有代码的改造点

| 动作 | 文件 | 改什么 |
|------|------|--------|
| 新增 | `backend/app/models/graph_community.py` | `GraphCommunity` 模型 |
| 改 | `backend/app/models/__init__.py` | 导出 `GraphCommunity`（触发 auto_migrate） |
| 新增 | `engine/app/graph/insights.py` | `graph_insights_context` + `has_insight_signal` + `_generate_community_labels` |
| 改 | `engine/app/graph/analyzer.py` | run_analysis 末尾补：社区标签 LLM + suggest_questions，写 graph_community |
| 改 | `engine/app/agent/runner.py` | `_build_messages` 注入 graph_insights_context（紧跟 active_recall） |
| 改 | `engine/app/config.py` | `GRAPH_INSIGHTS_ENABLED`、`GRAPH_INSIGHTS_TIMEOUT_SECONDS`、`GRAPH_INSIGHTS_SEED_ENTITIES`、`COMMUNITY_LABEL_MODEL` |

**不动**：P3 检索、对话工具、前端、Step B 的 cluster/god/surprising 主流程（只在末尾追加）。

## 8. 测试 + 验收

- **社区标签**：mock LLM，断言每个社区生成 label 并写 graph_community。
- **suggest_questions 过滤**：断言 `bridge_node` 类型被丢弃、god/ambiguous 保留。
- **注入块组装**：fake graph + sqlite，seed 命中 → 块含 surprising/god/questions；seed 未命中 → `""`；门控不触发 → `""`；异常 → `""`。
- **runner 注入**：monkeypatch `graph_insights_context`，断言 `_build_messages` 含对应 SystemMessage；`GRAPH_INSIGHTS_ENABLED=0` 时不注入。
- **e2e**：真实跑一个概念性问题，日志/trace 确认注入了洞察块；关闭开关验证降级为不注入。

**验收标准**：
1. 探索性问题时 agent 回答能引用 surprising/god 联系，或主动追问 suggested_question。
2. 非探索/无命中时不注入（不拖累延迟、不刷屏）。
3. `GRAPH_INSIGHTS_ENABLED=0` 全程降级，对话不受影响。

## 9. 风险与取舍

- **社区标签 LLM 成本**：每入库（run_analysis）1 次调用，按社区数批量。用便宜模型；社区多时按 top-K 实体摘要控制 token。可配 `COMMUNITY_LABEL_MODEL`。
- **suggest_questions 质量**：结构化生成，依赖图结构质量（AMBIGUOUS 边、INFERRED 度）；图很小时问题少或为空——属正常，注入块自动留空。
- **注入噪声**：洞察块过长会干扰回答。对策：每类封顶（surprising≤2、god≤2、questions≤2），块≤300 字。
- **门控误判**：信号词过宽会每轮查 Neo4j。对策：门控保守（仅探索信号 + seed 命中双条件更佳），并设超时。
- **范围纪律**：本期不做 P4（社区驱动 CKP 治理）；社区标签作为 P4 的副产品先行产出，但不在本期用于治理判定。

## 10. 最终原则

1. 洞察是**被动注入**，仿 active_recall，绝不拖累首字延迟。
2. 信号门控 + try/except + 超时 = 克制且健壮。
3. 复用 P3 的 seed 匹配、Step B 的社区/god/surprising，不重复造。
4. 社区标签是解锁可读洞察 + P4 治理的关键一次性投入。
5. 注入块短而有结构（隐藏联系/枢纽/可追问），避免噪声。
