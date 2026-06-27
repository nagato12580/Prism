# Prism Deep Knowledge Search 设计文档

> 日期：2026-06-27  
> 状态：设计稿  
> 范围：知识治理层 Deep Search，不接记忆系统，不接 Web，不引入独立 A2A HTTP transport。

## 1. 背景

当前 Prism 已有多条知识检索能力：

- `knowledge_topic_search`：查询 CKP 主题和稳定知识点。
- `knowledge_evidence_search`：查询 PKU 级证据。
- `knowledge_material_search`：通过 CKP/PKU 回溯原始材料。
- `raw_document_search` / `knowledge_search`：面向原始 chunk 的 Agentic RAG。
- `governed_knowledge_v2`：尝试以 chunk 向量召回为第一跳，再反查 PKU、聚合 CKP。

这些能力能完成普通检索，但对于“系统分析、完整证据链、冲突检查、结构关系梳理”类问题仍不够稳定：

1. 一次性检索不能判断证据是否完整。
2. chunk-first 全库召回可能慢，也容易在英文问题或跨领域问题上误召回。
3. CKP/PKU/source 之间的治理关系没有被组织成可循环扩展的搜索过程。
4. 现有 Judge 只判断 evidence 是否 sufficient，缺少多维验收和明确补查策略。

本设计新增 `deep_knowledge_search` 工具，将知识治理搜索升级为多轮、可验收、可追踪的 Deep Search。

## 2. 目标

第一版目标：

1. 只检索 Prism 知识治理层：CKP、PKU、PKU/CKP 关系、原始 document chunk、personal asset。
2. 使用 `Scope-first + Evidence-deepening` 策略，而不是默认全库 chunk vector search。
3. 引入 Orchestrator 中央调度、Searcher Agent 找证据、Judge Agent 验收证据。
4. 使用 A2A-shaped in-process 协议表达 Searcher/Judge 之间的任务、消息、产物。
5. 使用 EvidencePool 统一去重、评分、分组。
6. 使用 Judge 多维验收判断是否完整，并生成下一轮补查指令。
7. 由前端聊天框下方“深度搜索”开关控制工具是否对主 Agent 可见。

非目标：

1. 不接入记忆系统。
2. 不接入 Web search。
3. 不引入 Neo4j、Kuzu、AGE 等图数据库。
4. 不实现独立 A2A HTTP 服务。
5. 不替代现有默认知识工具。
6. 不让 Judge 直接搜索知识库。

## 3. 总体架构

```text
Chat request
  -> enable_deep_search?
      false: deep_knowledge_search 不注册给主 Agent
      true:  deep_knowledge_search 注册给主 Agent，并追加 prompt 指令

Main Agent
  -> deep_knowledge_search(query, depth, focus)
      -> DeepSearchOrchestrator
          -> SearcherAgent
              -> ScopeFinderExecutor
              -> SourceBacktrackExecutor
              -> PkuRequeryExecutor
              -> PkuGraphExpandExecutor
              -> CkpExpandExecutor
              -> ChunkSearchExecutor
          -> EvidencePool
          -> JudgeAgent
          -> decide_next / finalize
```

核心原则：

```text
Orchestrator 管流程和预算。
Searcher 只负责找证据。
Judge 只负责验收证据，不直接搜索。
EvidencePool 是跨轮唯一事实来源。
主 Agent 负责最终自然语言表达。
```

## 4. 搜索策略

Deep Search 使用 `Scope-first + Evidence-deepening`。

```text
1. Scope Finder
   先用 CKP / PKU / topic / metadata 找候选范围。

2. Source Backtracking
   从 seed CKP/PKU 回溯 PKU source。

3. Scoped Deepening
   证据不足时，在候选范围内继续找 PKU 或 chunk。

4. Graph Expansion
   范围太窄时，沿 PKU/CKP 关系扩展。

5. Global Fallback
   只有 deep 模式或明确需要全库搜索时，才全库 chunk 检索。
```

策略优先级：

```text
initial_scope
 -> source_backtrack
 -> pku_requery
 -> pku_graph_expand
 -> ckp_structure_expand
 -> ckp_rescope
 -> scoped_chunk_search
 -> global_fallback
```

## 5. Depth 档位

```text
quick:
  max_iterations = 2
  max_queries_per_iteration = 2
  min_overall_score = 0.75
  min_grounding_score = 0.70
  禁止 global_fallback
  禁止 ckp_rescope

standard:
  max_iterations = 3
  max_queries_per_iteration = 3
  min_overall_score = 0.82
  min_grounding_score = 0.75
  默认禁止 global_fallback
  允许 ckp_rescope 一次

deep:
  max_iterations = 5
  max_queries_per_iteration = 4
  min_overall_score = 0.88
  min_grounding_score = 0.80
  允许 global_fallback 一次
  允许 ckp_rescope 两次
```

工具输入：

```json
{
  "query": "...",
  "depth": "quick | standard | deep",
  "focus": "auto | evidence | conflict | structure | material",
  "limit": 10
}
```

前端传入的 `deep_search_depth` 是上限。模型可以降级，但不能把用户选择的 `standard` 升级到 `deep`。

## 6. A2A-shaped 协议

第一版不实现 HTTP transport，但内部数据模型贴近 A2A 的任务和产物概念。

### 6.1 Agent Card

Searcher:

```json
{
  "agent_id": "deep-search.searcher",
  "name": "Governed Knowledge Searcher",
  "skills": [
    "scope_finding",
    "source_backtracking",
    "pku_requery",
    "pku_graph_expansion",
    "ckp_rescope",
    "scoped_chunk_search"
  ],
  "output_artifacts": ["evidence_pack"]
}
```

Judge:

```json
{
  "agent_id": "deep-search.judge",
  "name": "Coverage Judge",
  "skills": [
    "coverage_evaluation",
    "grounding_check",
    "conflict_check",
    "followup_generation"
  ],
  "output_artifacts": ["coverage_judgment"]
}
```

### 6.2 Task

```json
{
  "task_id": "uuid",
  "parent_task_id": "run-id",
  "agent_id": "deep-search.searcher",
  "kind": "search_iteration",
  "status": "submitted | working | completed | failed",
  "iteration": 1,
  "messages": [],
  "artifacts": [],
  "error": null
}
```

Task kind:

```text
search_iteration
judge_iteration
```

### 6.3 Message

Message 承载请求、指令、上下文，不承载最终结构化产物。结构化结果使用 Artifact。

Searcher message data:

```json
{
  "user_question": "...",
  "depth": "standard",
  "focus": "auto",
  "iteration": 1,
  "search_directives": [],
  "current_scope": {},
  "budget": {
    "max_queries": 3,
    "top_k_scope": 8,
    "top_k_sources": 12
  }
}
```

Judge message data:

```json
{
  "user_question": "...",
  "depth": "standard",
  "focus": "auto",
  "iteration": 1,
  "evidence_pool_snapshot": {},
  "search_trace": [],
  "previous_judgments": []
}
```

### 6.4 Artifact

Searcher artifact: `evidence_pack`

```json
{
  "artifact_type": "evidence_pack",
  "iteration": 1,
  "data": {
    "strategy_used": ["initial_scope", "source_backtrack"],
    "queries": [],
    "scope": {
      "seed_ckps": [],
      "seed_pkus": [],
      "candidate_item_ids": [],
      "candidate_source_ids": [],
      "candidate_topic_ids": [],
      "scope_confidence": 0.0
    },
    "evidence_items": [],
    "source_results": [],
    "relations": [],
    "new_evidence_count": 0,
    "no_new_evidence": false
  }
}
```

Judge artifact: `coverage_judgment`

```json
{
  "artifact_type": "coverage_judgment",
  "iteration": 1,
  "data": {
    "status": "complete | incomplete | unanswerable",
    "answerability": "answerable | partially_answerable | unanswerable",
    "coverage_score": 0.0,
    "grounding_score": 0.0,
    "source_diversity_score": 0.0,
    "conflict_score": 0.0,
    "structure_score": 0.0,
    "overall_score": 0.0,
    "conflict_checked": false,
    "structure_checked": false,
    "missing_aspects": [],
    "weak_evidence": [],
    "followup_queries": [],
    "required_intents": [],
    "reason": ""
  }
}
```

## 7. Orchestrator 状态机

```text
initialize
 -> search_iteration
 -> merge_evidence
 -> judge_iteration
 -> decide_next
 -> repeat or finalize
```

### 7.1 Initialize

初始化 run state：

```json
{
  "run_id": "uuid",
  "status": "working",
  "user_question": "...",
  "depth": "standard",
  "focus": "auto",
  "iteration": 0,
  "current_scope": {
    "seed_ckp_ids": [],
    "seed_pku_ids": [],
    "candidate_item_ids": [],
    "candidate_source_ids": [],
    "candidate_topic_ids": []
  },
  "evidence_pool": {},
  "tasks": [],
  "judgments": [],
  "search_trace": [],
  "stop_reason": null
}
```

第一轮默认 directives：

```json
[
  {
    "query": "<user question>",
    "intent": "scope",
    "strategy": "initial_scope",
    "scope_policy": "seed_scope",
    "reason": "Find CKP/PKU scope first."
  },
  {
    "query": "<user question>",
    "intent": "material",
    "strategy": "source_backtrack",
    "scope_policy": "within_seed_scope",
    "reason": "Backtrack matched PKU evidence to raw sources."
  }
]
```

若 `focus=structure`，第一轮额外允许 `ckp_structure_expand`。

### 7.2 Search Iteration

Orchestrator 创建 Searcher task，发送 directives 和 current scope。Searcher 执行对应 executor，返回 `evidence_pack`。

### 7.3 Merge Evidence

EvidencePool 合并每轮结果：

```text
CKP 去重。
PKU 去重。
source 去重。
relation 去重。
EvidenceItem 去重。
重新计算 final_score。
更新 current_scope。
记录 new_evidence_count。
```

### 7.4 Judge Iteration

Judge 只接收 EvidencePool snapshot、search trace、用户问题，不查库，不调用工具。

### 7.5 Decide Next

停止条件：

```text
Judge status = complete
Judge status = unanswerable
iteration >= max_iterations
no_new_evidence_count >= 1 且非 deep
no_new_evidence_count >= 2
followup_queries 为空
budget exceeded
task failed 且不可降级
```

硬门槛：

```text
没有 raw source，不能 complete。
只有 CKP/related_to，不能 complete。
用户问冲突，conflict_checked 必须 true。
用户问结构，structure_checked 必须 true。
```

最终状态映射：

```text
judge_complete -> complete
judge_unanswerable -> unanswerable
max_iterations with evidence -> partial
no_new_evidence with evidence -> partial
task_failed with evidence -> partial
task_failed without evidence -> failed
```

## 8. Executor 设计

所有 executor 返回统一的 EvidencePack delta：

```json
{
  "seed_ckps": [],
  "seed_pkus": [],
  "source_results": [],
  "relations": [],
  "candidate_item_ids": [],
  "candidate_source_ids": [],
  "candidate_topic_ids": [],
  "evidence_items": [],
  "stats": {}
}
```

### 8.1 ScopeFinderExecutor

策略：

```text
LLM query analysis + deterministic SQL recall
```

LLM query analysis 输出：

```json
{
  "terms": [],
  "phrases": [],
  "entities": [],
  "domains": [],
  "intent": "evidence | conflict | structure | material | mixed",
  "needs_conflict_check": false,
  "needs_structure": false,
  "language": "zh | en | mixed",
  "query_rewrites": []
}
```

调用频率：

```text
initial_scope: 调一次
ckp_rescope: 调一次
pku_requery / pku_graph_expand / source_backtrack / chunk_search: 不调
```

CKP recall 字段：

```text
title
canonical_statement
summary
aliases
domains
entities
concepts
keywords
```

PKU recall 字段：

```text
statement
normalized_statement
subject
predicate
object
domains
entities
concepts
keywords
```

Scope score：

```text
scope_score =
  lexical_score        * 0.45
+ metadata_score       * 0.20
+ confidence_score     * 0.15
+ pku_link_score       * 0.15
+ recency_score        * 0.05
```

Scope Finder 不查全量 chunk。

### 8.2 SourceBacktrackExecutor

职责：

```text
seed PKU -> source
seed CKP -> PKUCanonicalLink -> PKU -> source
```

PKU 过滤：

```text
status = active
confidence >= 0.35
```

关系过滤：

```text
evidence: same_as / supports / defines / example_of / extends
conflict: contradicts
material: same_as / supports / defines / extends / related_to / example_of
structure: same_as / defines / related_to / extends
auto: same_as / supports / defines / contradicts / example_of / extends
```

Source 解析：

```text
document_chunk: KnowledgeChunk，优先 small-to-big 返回 parent chunk
personal_asset_unit: PersonalAssetUnit
personal_asset_item: PersonalAssetItem
knowledge_item: KnowledgeItem 兜底
```

关键规则：

```text
CKP 不能单独作为证据。
最终证据必须落到 PKU + source。
contradicts 是高价值证据。
related_to 不能单独支撑结论。
```

### 8.3 PkuRequeryExecutor

目标：在已有 scope 内重新找更具体的 PKU。

查询范围优先级：

```text
1. PKUCanonicalLink.canonical_id IN seed_ckp_ids
2. PersonalKnowledgeUnit.source_id IN candidate_source_ids
3. source 属于 candidate_item_ids 下的 chunks/assets
4. PKU.entities / domains / concepts overlap
```

不在本 executor 内全局查 PKU。

评分：

```text
pku_requery_score =
  lexical_score          * 0.40
+ scope_match_score      * 0.25
+ pku.confidence         * 0.15
+ link_confidence        * 0.10
+ source_available_score * 0.10
```

### 8.4 PkuGraphExpansionExecutor

扩展路径：

```text
seed PKU -> PKURelation -> neighbor PKU
seed CKP -> PKUCanonicalLink -> sibling PKUs
seed source/entity -> same source/entity PKUs（仅 deep 或 Judge 明确要求）
```

第一版只扩一跳。`related_to` 最多一跳，并且不能单独支撑结论。

### 8.5 CkpExpandExecutor

包含两个能力：

```text
ckp_rescope:
  当前范围可能错了，用 Judge followup query 重新找 CKP。

ckp_structure_expand:
  当前范围基本对，沿 CanonicalRelation 扩结构邻居。
```

CKP relation intent：

```text
structure:
  part_of / has_part / uses / requires / refines / related_to / broader_than / narrower_than

evidence:
  supports / explains / defines / derived_from / applies_to

conflict:
  contradicts / alternative_to / replaces / deprecated_by
```

路径查找第一版只支持 direct + one-hop。

### 8.6 ChunkSearchExecutor

包含两个能力：

```text
scoped_chunk_search:
  在 candidate_item_ids / candidate_source_ids / candidate_topic_ids 内查 chunk。

global_fallback:
  仅 deep 或用户明确全库搜索时，全库 hybrid_search 兜底。
```

Scoped search 必须有 scope，否则不执行。

Global fallback：

```text
quick: 禁用
standard: 默认禁用
deep: 允许一次
```

Global fallback 结果：

```text
scope_distance = 4
strategy_penalty = 0.70
```

## 9. EvidencePool

### 9.1 数据模型

EvidenceNode:

```json
{
  "node_key": "ckp:xxx",
  "node_type": "ckp | pku | source | raw_chunk",
  "id": "xxx",
  "title": "...",
  "text": "...",
  "metadata": {},
  "confidence": 0.0,
  "score": 0.0,
  "discovery": {}
}
```

EvidenceEdge:

```json
{
  "edge_key": "pku:p1->ckp:c1:supports",
  "edge_type": "pku_ckp | ckp_ckp | pku_pku | pku_source",
  "source_key": "pku:p1",
  "target_key": "ckp:c1",
  "relation_type": "supports",
  "role": "definition_source",
  "confidence": 0.0,
  "reason": "",
  "score": 0.0,
  "discovery": {}
}
```

EvidenceItem:

```json
{
  "item_key": "pku:p1|source:document_chunk:s1|ckp:c1",
  "kind": "pku_source | raw_chunk | ckp_relation | pku_relation",
  "claim_text": "...",
  "source_text": "...",
  "source_title": "...",
  "source_kind": "document_chunk",
  "source_id": "...",
  "pku_id": "p1",
  "canonical_id": "c1",
  "relation_type": "supports",
  "role": "definition_source",
  "unit_type": "definition",
  "modality": "fact",
  "scores": {},
  "discovery": {}
}
```

### 9.2 去重

```text
CKP: canonical_id
PKU: pku_id
source: source_kind + source_id
relation: source_key + target_key + relation_type
EvidenceItem: pku_id + source_key + canonical_id + relation_type
raw_chunk: chunk_id
```

同 key 保留最高分，合并 discovery paths 和 match reasons。

### 9.3 评分

Base score：

```text
base_score =
  retrieval_score      * 0.35
+ relation_confidence  * 0.25
+ knowledge_confidence * 0.20
+ source_quality       * 0.15
+ coverage_bonus       * 0.05
```

Scope distance penalty：

```text
0: 1.00
1: 0.95
2: 0.88
3: 0.80
4: 0.70
```

Strategy penalty：

```text
initial_scope/source_backtrack: 1.00
pku_requery: 0.95
pku_graph_expand: 0.92
ckp_structure_expand: 0.88
ckp_rescope: 0.85
scoped_chunk_search: 0.90
global_fallback: 0.70
```

Relation priority bonus：

```text
defines: +0.05
supports: +0.04
contradicts: +0.04
same_as: +0.03
example_of: +0.02
extends: +0.01
related_to: -0.10
```

Final score：

```text
final_score =
  clamp(
    (base_score + relation_priority_bonus)
    * scope_distance_penalty
    * strategy_penalty,
    0,
    1
  )
```

### 9.4 Snapshot 分组

```json
{
  "supporting_evidence": [],
  "contradicting_evidence": [],
  "definitions": [],
  "methods": [],
  "examples": [],
  "source_materials": [],
  "related_topics": [],
  "raw_chunks": [],
  "score_summary": {
    "evidence_count": 0,
    "support_count": 0,
    "contradiction_count": 0,
    "source_count": 0,
    "raw_source_count": 0,
    "avg_score": 0.0,
    "top_score": 0.0,
    "has_raw_sources": false,
    "has_contradictions": false,
    "has_only_related_to": false
  }
}
```

硬规则：

```text
CKP-only 不进入 supporting_evidence，只进 related_topics。
related_to 不能单独支持 complete。
raw_chunk_without_pku 可以补原文，但低于 pku_source。
contradicts 不降权。
```

## 10. Judge

Judge 不搜索，不回答，只验收。

### 10.1 System Prompt 核心规则

```text
You are the Coverage Judge for Prism governed knowledge deep search.

Your job is NOT to answer the user directly.
Your job is to evaluate whether the provided evidence is sufficient for a grounded answer.

You cannot search the knowledge base.
You must judge only from the provided evidence_pool_snapshot and search_trace.

A complete answer requires:
1. The user's major requirements are covered.
2. Claims are grounded in PKU + source evidence whenever possible.
3. CKP-only or related_to-only evidence is not enough for factual conclusions.
4. Source identities are not mixed.
5. If the user asks about conflicts, contradiction evidence must be checked.
6. If the user asks about structure, CKP relation evidence must be present.
7. Missing evidence should become followup_queries for the Searcher.

Return strict JSON only.
```

### 10.2 多维验收

Judge 输出：

```json
{
  "status": "complete | incomplete | unanswerable",
  "answerability": "answerable | partially_answerable | unanswerable",
  "coverage_score": 0.0,
  "grounding_score": 0.0,
  "source_diversity_score": 0.0,
  "conflict_score": 0.0,
  "structure_score": 0.0,
  "overall_score": 0.0,
  "conflict_checked": false,
  "structure_checked": false,
  "missing_aspects": [],
  "weak_evidence": [],
  "followup_queries": [],
  "required_intents": [],
  "reason": ""
}
```

Overall score：

```text
overall_score =
  coverage_score * 0.35
+ grounding_score * 0.30
+ source_diversity_score * 0.15
+ conflict_score * 0.10
+ structure_score * 0.10
```

如果用户明确问冲突，提高 conflict 权重；如果用户明确问结构，提高 structure 权重。

### 10.3 Followup 规则

```text
缺具体 PKU -> pku_requery
缺原文 -> scoped_chunk_search
缺反证 -> pku_graph_expand + conflict
缺结构 -> ckp_structure_expand
范围可能错 -> ckp_rescope
完全没结果且 deep 允许 -> global_fallback
```

LLM JSON 失败处理：

```text
重试一次。
仍失败则构造 conservative incomplete judgment。
```

## 11. Searcher Planner

Planner 只生成 directives，不回答，不判断完成度。

调用规则：

```text
initial_scope: 使用固定第一轮 directives，可由 planner 补充。
后续轮: 优先使用 Judge.followup_queries。
如果 Judge 只给 missing_aspects，则 Planner fallback 生成 directives。
```

Planner 输出：

```json
{
  "directives": [
    {
      "query": "...",
      "intent": "scope | evidence | conflict | structure | material",
      "strategy": "initial_scope | source_backtrack | pku_requery | pku_graph_expand | ckp_structure_expand | ckp_rescope | scoped_chunk_search | global_fallback",
      "scope_policy": "seed_scope | within_seed_scope | expand_neighbors | rescope | within_candidate_sources | global_fallback",
      "reason": "..."
    }
  ]
}
```

Orchestrator 会二次校验 directives：

```text
strategy 必须在 allowed_strategies。
数量不超过 max_directives。
query 非空。
去重 query + strategy。
depth 禁止的策略必须过滤。
source_backtrack 必须已有 scope，否则延后。
```

## 12. 工具注册与聊天开关

新增前端开关：

```text
深度搜索
```

可选档位：

```text
quick | standard | deep
```

Chat request 增加：

```json
{
  "enable_deep_search": true,
  "deep_search_depth": "standard"
}
```

后端规则：

```text
enable_deep_search = false:
  deep_knowledge_search 不注册给主 Agent。

enable_deep_search = true:
  deep_knowledge_search 注册给主 Agent。
  System prompt 追加深度搜索指令。
```

动态 prompt：

```text
用户已开启深度搜索模式。
对于涉及 Prism 知识库、知识治理层、文档证据、PKU/CKP、证据链、冲突检查、系统分析的问题，你应优先调用 deep_knowledge_search 获取多轮检索结果，再基于返回的 evidence、coverage_report 和 sources 回答。
如果问题明显是闲聊、时间查询、非知识库问题，则不必调用 deep_knowledge_search。
```

`deep_knowledge_search` 在 registry 中 `default_enabled=False`。每次 chat request 根据开关通过 overrides 暴露工具。

## 13. 文件结构

新增：

```text
engine/app/agent/a2a/
  __init__.py
  models.py

engine/app/agent/deep_search/
  __init__.py
  schemas.py
  config.py
  orchestrator.py
  searcher_agent.py
  judge_agent.py
  planner.py
  scope_finder.py
  source_backtrack.py
  pku_requery.py
  pku_graph_expand.py
  ckp_expand.py
  chunk_search.py
  evidence_pool.py
  prompts.py
  governed_retriever.py

engine/app/agent/tools/
  deep_knowledge.py
```

修改：

```text
engine/app/agent/tools/base.py
  ToolContext 增加 topic_id/source_types/allowed_item_ids/enable_deep_search/deep_search_depth

engine/app/chat/answer.py
  build_agent_runner 增加 deep search 参数
  build_enabled_tools 使用 overrides
  system prompt 动态追加 deep search 指令

engine/app/api/chat.py
  ChatRequest 增加 enable_deep_search/deep_search_depth

engine/app/agent/tools/__init__.py
  import deep_knowledge

frontend/src/pages/ChatPage.tsx
  对话框下方增加深度搜索开关和档位

frontend/src/app/api.ts
  chat 请求增加 deep search 参数
```

## 14. 现有代码复用边界

直接复用：

```text
hybrid_search
KnowledgeChunk small-to-big 加载逻辑
SQLAlchemy models:
  PersonalKnowledgeUnit
  CanonicalKnowledgePoint
  PKUCanonicalLink
  CanonicalRelation
  PKURelation
  KnowledgeChunk
  KnowledgeItem
  PersonalAssetUnit
  PersonalAssetItem
LLM chat client
ToolSpec / ToolContext / build_enabled_tools
```

封装复用：

```text
governed_knowledge.py 中的 source backtracking / evidence bundle / scoring helper
governed_knowledge_v2.py 中的 child->parent / reverse PKU lookup 思路
```

Deep Search 不直接复用 `governed_knowledge_v2` 的全流程，因为本设计已经从 vector-first 改为 scope-first。

## 15. 测试策略

新增测试：

```text
engine/tests/test_deep_search_scope_finder.py
engine/tests/test_deep_search_source_backtrack.py
engine/tests/test_deep_search_pku_requery.py
engine/tests/test_deep_search_pku_graph_expand.py
engine/tests/test_deep_search_ckp_expand.py
engine/tests/test_deep_search_chunk_search.py
engine/tests/test_deep_search_evidence_pool.py
engine/tests/test_deep_search_judge.py
engine/tests/test_deep_search_orchestrator.py
engine/tests/test_deep_knowledge_tool.py
frontend/tests/chat-deep-search-toggle.test.mjs
```

核心验收：

```text
1. enable_deep_search=false 时，Agent 看不到 deep_knowledge_search。
2. enable_deep_search=true 时，Agent 看得到 deep_knowledge_search。
3. deep search 能跑至少两轮：search -> judge -> followup search。
4. EvidencePool 能输出 supporting / contradicting / source_materials。
5. Judge 能基于多维分数决定 complete / incomplete。
6. Orchestrator 能按 stop_reason 停止。
7. 前端能发送开关参数。
```

集成用例：

```text
证据链:
  metadata filter 为什么适合个人知识库检索？
  期望找到 document_chunk + personal_asset 证据。

冲突检查:
  metadata filter 有没有反例或冲突记录？
  期望 contradicting_evidence 非空，conflict_checked=true。

结构关系:
  metadata filter 和 hybrid retrieval 有什么关系？
  期望 ckp_structure_expand 返回 related_topics，structure_checked=true。

范围重定向:
  low rank adaptation 在我的知识库里有哪些证据？
  期望 ckp_rescope 或 pku_requery 能找到 LoRA/low rank adaptation。

精确原文:
  metadata filtering 原文定义是什么？
  期望 scoped_chunk_search 返回 raw chunk，不触发 global_fallback。

全库兜底:
  deep 模式允许 global_fallback 一次；standard 默认不允许。
```

## 16. 实现顺序

```text
1. a2a models / schemas / config
2. EvidencePool
3. SourceBacktrackExecutor
4. ScopeFinderExecutor
5. PkuRequeryExecutor
6. PkuGraphExpansionExecutor
7. CkpExpandExecutor
8. ChunkSearchExecutor
9. SearcherAgent
10. JudgeAgent
11. Orchestrator
12. deep_knowledge tool
13. Chat API / ToolContext / prompt switch
14. Frontend deep search toggle
15. End-to-end tests
```

## 17. 完成标准

第一版完成后，系统应满足：

```text
普通聊天不开深度搜索，不暴露 deep_knowledge_search。
用户打开深度搜索后，主 Agent 优先调用 deep_knowledge_search。
Deep Search 从 CKP/PKU 范围定位开始，不默认全库 chunk 检索。
证据不足时，按 Judge 缺口逐步 pku_requery / graph_expand / rescope / chunk_search。
Judge 不搜索，只基于 EvidencePool 验收。
工具返回 answer_basis、coverage_report、evidence_pool、search_trace、sources。
主 Agent 基于工具返回结果组织最终回答。
```
