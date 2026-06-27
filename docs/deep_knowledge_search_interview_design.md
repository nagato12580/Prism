# Prism Deep Knowledge Search 面试版架构设计

## 1. 项目背景

Prism 是一个个人知识治理助手，不只是传统笔记或简单 RAG。系统中有两类核心知识来源：

1. 上传文档、PDF、技术资料、网页等外部资料。
2. 用户日常沉淀的碎片资产，如想法、实验记录、问题、观察、决策。

这些来源会被治理到统一知识层：

```text
DocumentChunk / PersonalAssetUnit
  -> PersonalKnowledgeUnit(PKU)
  -> CanonicalKnowledgePoint(CKP)
  -> CKP/PKU relations
```

其中：

- `PKU` 是原子知识单元，保留 source_kind/source_id，可回溯原始 chunk 或 asset。
- `CKP` 是归一后的稳定知识点，用来组织多个 PKU。
- `PKUCanonicalLink` 表达 PKU 与 CKP 的关系，如 `supports`、`defines`、`contradicts`。
- `CanonicalRelation` / `PKURelation` 表达知识点和知识单元之间的结构关系。

已有工具能做普通检索，但对于“系统分析、完整证据链、冲突检查、结构关系梳理”这类问题，单轮检索不够稳定。

## 2. 问题定义

旧链路主要有三类问题。

### 2.1 一次性检索无法判断证据是否完整

普通 RAG 或单轮 governed search 能返回相关片段，但不知道：

- 是否覆盖用户问题的所有子问题。
- 是否只有相关主题，没有真正证据。
- 是否缺少原始 source。
- 是否需要检查反证或冲突。

### 2.2 全库 chunk 向量召回不适合作为默认第一跳

`governed_knowledge_v2` 的 vector-first 思路是：

```text
query -> chunk vector search -> PKU -> CKP
```

这在很多场景有效，但如果用户问题是英文、抽象或跨领域，全库 chunk 召回容易：

- 慢。
- 误召回。
- 命中范围太散。
- 后续 PKU/CKP 聚合噪声变大。

因此更合理的路线是先用 CKP/PKU/topic/metadata 确定范围，再在范围内下钻原文。

### 2.3 证据检索和证据验收职责混在一起

如果一个 Agent 同时负责找资料、判断完整性、生成答案，容易出现：

- 检索 Agent 过度乐观。
- 找到几个相关证据就提前停止。
- 没有显式暴露缺口。
- 难以量化评估每轮搜索为什么继续或停止。

## 3. 设计目标

Deep Knowledge Search 的目标是把知识治理层检索升级成多轮可控流程：

```text
Scope-first + Evidence-deepening
```

核心目标：

1. 先确定 CKP/PKU 候选范围，再回溯原始 source。
2. 证据不足时，按缺口逐步扩展，而不是直接全库搜索。
3. 使用 Searcher Agent 找证据，Judge Agent 验收证据。
4. Judge 不直接搜索，只给出缺口和下一轮建议。
5. Orchestrator 统一调度循环、预算和停止条件。
6. EvidencePool 统一合并、去重、评分和分组。
7. 前端提供“深度搜索”开关，用户打开后主 Agent 才能看到该工具。

## 4. 总体架构

```text
ChatPage 深度搜索开关
  -> /chat/answer(enable_deep_search=true, deep_search_depth=standard)
  -> build_agent_runner
      -> deep_knowledge_search 工具可见
      -> system prompt 追加深度搜索指令
  -> Main Agent 调用 deep_knowledge_search
      -> DeepSearchOrchestrator
          -> SearcherAgent
          -> EvidencePool
          -> JudgeAgent
          -> decide_next / finalize
```

### 4.1 Orchestrator

Orchestrator 是中央调度器，负责：

- 创建每轮 Searcher/Judge 任务。
- 维护 current_scope。
- 维护 EvidencePool。
- 控制 quick/standard/deep 档位预算。
- 根据 Judge 结果决定继续、停止或降级。

### 4.2 Searcher Agent

Searcher 负责执行检索策略，不判断完整性，不生成最终答案。

它包含多个 executor：

```text
ScopeFinderExecutor
SourceBacktrackExecutor
PkuRequeryExecutor
PkuGraphExpansionExecutor
CkpExpandExecutor
ChunkSearchExecutor
```

### 4.3 Judge Agent

Judge 负责验收 EvidencePool：

- 覆盖度是否足够。
- 是否有 PKU + source 支撑。
- 是否只有 CKP 或 related_to。
- 是否需要冲突检查。
- 是否需要结构关系。
- 是否需要继续搜索。

Judge 不搜索知识库，只输出 `coverage_judgment`。

### 4.4 EvidencePool

EvidencePool 是跨轮唯一事实来源，负责：

- CKP / PKU / source / relation 去重。
- 多路径证据合并。
- 证据综合评分。
- 输出 Judge snapshot。
- 输出最终 sources。

## 5. A2A-shaped 协议

系统采用 A2A-shaped in-process 协议，而不是直接使用函数裸调用。这样未来可以平滑升级到真实 A2A 服务。

内部抽象包括：

```text
AgentCard
A2ATask
A2AMessage
A2AArtifact
RunState
```

Searcher 输出 artifact：

```json
{
  "artifact_type": "evidence_pack",
  "iteration": 1,
  "data": {
    "strategy_used": ["initial_scope", "source_backtrack"],
    "scope": {},
    "evidence_items": [],
    "source_results": [],
    "relations": [],
    "new_evidence_count": 0
  }
}
```

Judge 输出 artifact：

```json
{
  "artifact_type": "coverage_judgment",
  "iteration": 1,
  "data": {
    "status": "complete | incomplete | unanswerable",
    "coverage_score": 0.0,
    "grounding_score": 0.0,
    "source_diversity_score": 0.0,
    "conflict_score": 0.0,
    "structure_score": 0.0,
    "overall_score": 0.0,
    "followup_queries": []
  }
}
```

## 6. 搜索流程

### 6.1 第一轮：范围定位和回源

第一轮固定执行：

```text
initial_scope
 -> source_backtrack
```

`ScopeFinderExecutor` 做：

```text
LLM query analysis
 -> CKP lexical recall
 -> PKU lexical recall
 -> metadata/topic weighting
 -> PKU -> CKP expansion
```

LLM 只负责解析查询线索，不负责决定真实结果。

`SourceBacktrackExecutor` 做：

```text
seed PKU -> source
seed CKP -> PKUCanonicalLink -> PKU -> source
```

重要原则：

```text
CKP 不能单独作为证据。
最终证据必须落到 PKU + source。
```

### 6.2 后续轮：按 Judge 缺口补查

如果 Judge 认为证据不足，Orchestrator 根据 followup 执行：

```text
pku_requery:
  在已有 CKP/source 范围内找更具体 PKU。

pku_graph_expand:
  沿 PKURelation 或同 CKP sibling PKU 扩展。

ckp_structure_expand:
  沿 CanonicalRelation 找结构邻居。

ckp_rescope:
  当前范围可能错时，重新定位 CKP。

scoped_chunk_search:
  在 candidate_item_ids/source/topic 内检索原文 chunk。

global_fallback:
  仅 deep 模式或明确全库需求时，全库检索兜底。
```

### 6.3 搜索半径控制

系统用 `scope_distance` 控制证据可信半径：

```text
0 = seed 直接证据
1 = sibling / one-hop PKU
2 = CKP structure or scoped chunk
3 = CKP rescope
4 = global fallback
```

距离越远，评分越低，防止搜索漂移。

## 7. EvidencePool 评分

每个证据统一转成 EvidenceItem：

```json
{
  "kind": "pku_source | raw_chunk | ckp_relation | pku_relation",
  "claim_text": "...",
  "source_text": "...",
  "source_kind": "document_chunk",
  "pku_id": "...",
  "canonical_id": "...",
  "relation_type": "supports",
  "scores": {
    "retrieval_score": 0.0,
    "relation_confidence": 0.0,
    "knowledge_confidence": 0.0,
    "source_quality": 0.0,
    "final_score": 0.0
  }
}
```

评分公式：

```text
base_score =
  retrieval_score      * 0.35
+ relation_confidence  * 0.25
+ knowledge_confidence * 0.20
+ source_quality       * 0.15
+ coverage_bonus       * 0.05
```

再乘以：

```text
scope_distance_penalty
strategy_penalty
```

并加入小幅 relation bonus：

```text
defines: +0.05
supports: +0.04
contradicts: +0.04
same_as: +0.03
related_to: -0.10
```

关键规则：

```text
contradicts 是高价值证据，不降权。
related_to 不能单独支撑结论。
global_fallback 强降权。
raw_chunk_without_pku 低于 pku_source。
```

## 8. Judge 多维验收

Judge 输出五类分数：

```text
coverage_score:
  用户问题主要面向是否覆盖。

grounding_score:
  是否有 PKU + source 支撑。

source_diversity_score:
  是否有多个独立 source 或多个 PKU。

conflict_score:
  是否检查 contradicts / 反证。

structure_score:
  是否覆盖 CKP relation / 结构关系。
```

综合分：

```text
overall_score =
  coverage_score * 0.35
+ grounding_score * 0.30
+ source_diversity_score * 0.15
+ conflict_score * 0.10
+ structure_score * 0.10
```

完成门槛：

```text
quick:
  overall_score >= 0.75
  grounding_score >= 0.70

standard:
  overall_score >= 0.82
  grounding_score >= 0.75

deep:
  overall_score >= 0.88
  grounding_score >= 0.80
```

硬门槛：

```text
没有 raw source，不能 complete。
只有 CKP/related_to，不能 complete。
用户问冲突，conflict_checked 必须 true。
用户问结构，structure_checked 必须 true。
```

## 9. 工具注册和用户开关

前端对话框下方增加：

```text
深度搜索
```

可选档位：

```text
quick | standard | deep
```

请求参数：

```json
{
  "enable_deep_search": true,
  "deep_search_depth": "standard"
}
```

后端规则：

```text
enable_deep_search=false:
  deep_knowledge_search 不注册给主 Agent。

enable_deep_search=true:
  deep_knowledge_search 注册给主 Agent。
  system prompt 追加“优先调用 deep_knowledge_search”的指令。
```

这样普通聊天不会被 Deep Search 拖慢，用户显式打开后才进入多轮搜索。

## 10. 技术取舍

### 10.1 为什么不是两个自由 Agent 互相聊天

自由多 Agent 容易失控，难以评测。这里采用 Orchestrator 中央调度：

```text
Searcher 找证据。
Judge 验收证据。
Orchestrator 决定继续或停止。
```

### 10.2 为什么 Judge 不搜索

如果 Judge 也能搜索，职责会混乱。第一版 Judge 只根据 EvidencePool 判断：

```text
证据是否覆盖？
缺什么？
下一轮建议怎么搜？
```

实际搜索仍交给 Searcher。

### 10.3 为什么不是默认 chunk-first

chunk-first 全库召回可能慢且噪声大。Prism 的优势是 CKP/PKU 治理层，所以第一跳应先定位范围，再下钻原文。

### 10.4 为什么不直接上图数据库

当前 CKP/PKU/Relation 表已经能表达图结构。第一版使用 SQL-backed graph expansion 更轻量，避免基础设施过重。

## 11. 面试讲述要点

可以按这个顺序讲：

1. 问题：普通 RAG 只能返回相关片段，不能保证证据完整，也不理解知识治理关系。
2. 数据建模：用 PKU 表示原子知识，用 CKP 表示归一知识点，用 relation 表达支持、冲突、结构关系。
3. 搜索策略：Scope-first，而不是全库 chunk-first。
4. 多 Agent 分工：Searcher 找证据，Judge 验收，Orchestrator 调度。
5. EvidencePool：统一去重、评分、分组，是跨轮搜索的事实来源。
6. Judge 多维验收：coverage、grounding、diversity、conflict、structure。
7. 用户体验：前端深度搜索开关控制工具可见性，避免普通对话变慢。
8. 可评测性：每轮 search_trace、stop_reason、coverage_report 都可离线评估。

一句话总结：

```text
我把传统一次性 RAG 改造成了知识治理层上的多轮深度搜索：先定位 CKP/PKU 范围，再回溯证据，证据不足时按缺口扩展，并用独立 Judge 对覆盖度和证据扎实度做多维验收。
```
