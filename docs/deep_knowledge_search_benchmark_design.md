# Prism Deep Knowledge Search Benchmark 设计

## 1. 评测目标

Deep Knowledge Search 不是单纯召回器，而是一条完整链路：

```text
Scope Finder
 -> Source Backtracking
 -> EvidencePool
 -> Judge
 -> Follow-up Search
 -> Final Answer Basis
```

因此 benchmark 不能只看 chunk recall，还要评估：

1. 是否找到正确 CKP / PKU 范围。
2. 是否回溯到正确原始 source。
3. 是否发现支持、反证、结构关系。
4. Judge 是否正确判断 complete / incomplete。
5. 多轮搜索是否在合理成本内收敛。
6. 最终 answer_basis 是否被证据充分支撑。

## 2. 对比基线

Benchmark 至少比较以下链路：

```text
traditional_hybrid:
  Milvus vector + ES/MySQL BM25 + RRF，chunk 级基线。

governed_evidence:
  现有 CKP/PKU governed evidence 检索。

governed_v2:
  chunk vector/hybrid -> PKU -> CKP。

deep_knowledge_search_quick:
  Deep Search quick 档。

deep_knowledge_search_standard:
  Deep Search standard 档。

deep_knowledge_search_deep:
  Deep Search deep 档。
```

第一版实现时，至少要求：

```text
traditional_hybrid
governed_evidence
deep_knowledge_search_standard
```

## 3. 数据集设计

建议新增：

```text
evaluation/datasets/deep_knowledge_search_v1.json
```

数据集包含 5 类问题，每类至少 10 条，第一版共 50 条。

### 3.1 Evidence Chain

目标：评估“结论是否有证据支持”。

示例：

```text
metadata filter 为什么适合个人知识库检索？
CKP/PKU 检索比纯 chunk 检索的优势是什么？
```

标注：

```json
{
  "expected_ckp_ids": [],
  "expected_pku_ids": [],
  "expected_source_ids": [],
  "required_relation_types": ["supports", "defines"],
  "required_answer_aspects": ["定义", "实验观察", "适用条件"]
}
```

### 3.2 Conflict Detection

目标：评估是否发现 contradicts / 反证。

示例：

```text
metadata filter 有没有反例或冲突记录？
我之前关于 chunk-first 的观点有没有被后续实验反驳？
```

标注：

```json
{
  "expected_contradicting_pku_ids": [],
  "expected_conflict_relation_ids": [],
  "must_check_conflict": true
}
```

### 3.3 Structure / Relation

目标：评估 CKP relation 和知识结构。

示例：

```text
metadata filter 和 hybrid retrieval 有什么关系？
CKP、PKU、chunk 三层之间是什么结构？
```

标注：

```json
{
  "expected_relation_ids": [],
  "expected_neighbor_ckp_ids": [],
  "required_relation_types": ["part_of", "uses", "requires", "related_to"],
  "must_check_structure": true
}
```

### 3.4 Source-grounded Fact

目标：评估是否能找到原文定义、参数、步骤。

示例：

```text
metadata filtering 原文定义是什么？
文档里对 parent-child chunking 的工程落地方式怎么说？
```

标注：

```json
{
  "expected_source_ids": [],
  "expected_chunk_ids": [],
  "answer_must_include_exact_source": true
}
```

### 3.5 Scope Ambiguity / Rescope

目标：评估初始范围错误时能否 rescope。

示例：

```text
low rank adaptation 在我的知识库里有哪些证据？
LLM-as-a-Judge 的评估方式是什么？
```

标注：

```json
{
  "expected_ckp_ids": [],
  "expected_pku_ids": [],
  "requires_rescope_or_requery": true
}
```

## 4. 数据格式

建议 JSON schema：

```json
{
  "meta": {
    "name": "deep_knowledge_search_v1",
    "version": "1.0",
    "created_at": "2026-06-27",
    "description": "Benchmark for Prism governed deep knowledge search."
  },
  "queries": [
    {
      "id": "dks001",
      "question": "...",
      "language": "zh | en | mixed",
      "category": "evidence_chain | conflict | structure | source_fact | rescope",
      "depth": "standard",
      "focus": "auto | evidence | conflict | structure | material",
      "expected": {
        "ckp_ids": [],
        "pku_ids": [],
        "source_ids": [],
        "chunk_ids": [],
        "relation_ids": [],
        "relation_types": [],
        "answer_aspects": [],
        "must_check_conflict": false,
        "must_check_structure": false,
        "must_have_raw_source": true
      }
    }
  ]
}
```

## 5. 指标体系

指标分三层。

## 5.1 Retrieval / Scope Metrics

用于衡量是否找到了正确节点和 source。

### CKP Recall@K

```text
ckp_recall@k = returned_expected_ckp_count@k / expected_ckp_count
```

目标：

```text
standard: mean ckp_recall@5 >= 0.70
deep:     mean ckp_recall@5 >= 0.78
```

### PKU Recall@K

```text
pku_recall@k = returned_expected_pku_count@k / expected_pku_count
```

目标：

```text
standard: mean pku_recall@10 >= 0.60
deep:     mean pku_recall@10 >= 0.70
```

### Source Recall@K

```text
source_recall@k = returned_expected_source_count@k / expected_source_count
```

目标：

```text
standard: mean source_recall@10 >= 0.65
deep:     mean source_recall@10 >= 0.75
```

### Grounded Evidence Rate

有至少一个 `PKU + raw source` 证据的 query 比例。

```text
grounded_evidence_rate = queries_with_pku_source / total_queries
```

目标：

```text
standard >= 0.80
deep >= 0.88
```

## 5.2 Deep Search Behavior Metrics

用于衡量多轮链路是否按设计工作。

### Completion Rate

Judge 判断为 complete 的比例。

```text
completion_rate = complete_runs / total_runs
```

目标：

```text
standard >= 0.70
deep >= 0.78
```

注意：completion rate 不能孤立看，必须同时满足 grounding 指标，避免虚假 complete。

### Correct Stop Rate

停止原因是否合理。

可接受 stop_reason：

```text
judge_complete
judge_unanswerable
max_iterations_with_evidence
no_new_evidence_with_evidence
```

不可接受：

```text
task_failed
invalid_judge_json
empty_followup_without_evidence
```

目标：

```text
correct_stop_rate >= 0.95
```

### Average Iterations

```text
avg_iterations = total_iterations / total_queries
```

目标：

```text
quick <= 2.0
standard <= 3.0
deep <= 5.0
```

### No Global Fallback Violation

standard / quick 不应触发 global fallback。

```text
global_fallback_violation_count = 0
```

目标：

```text
quick = 0
standard = 0
deep <= total_queries
```

### No Scope-less Chunk Search

`scoped_chunk_search` 必须带 scope。

目标：

```text
scope_less_chunk_search_count = 0
```

## 5.3 Answer Quality Metrics

这些指标评估最终 `answer_basis` 和证据是否匹配。

### Coverage Score

由 Judge 输出，也可用离线 evaluator 复判。

```text
coverage_score = 用户问题要求覆盖程度
```

目标：

```text
standard mean >= 0.78
deep mean >= 0.84
```

### Grounding Score

判断 answer_basis 是否由 PKU + source 支撑。

目标：

```text
standard mean >= 0.75
deep mean >= 0.82
```

### Conflict Check Accuracy

仅对 conflict 类问题计算。

```text
conflict_check_accuracy =
  correctly_checked_conflict_queries / conflict_queries
```

正确包括：

```text
1. 返回 expected contradicting evidence。
2. conflict_checked = true。
3. answer_basis 提到是否存在冲突。
```

目标：

```text
standard >= 0.75
deep >= 0.85
```

### Structure Check Accuracy

仅对 structure 类问题计算。

```text
structure_check_accuracy =
  correctly_checked_structure_queries / structure_queries
```

目标：

```text
standard >= 0.75
deep >= 0.85
```

### Hallucination / Unsupported Claim Rate

使用离线 LLM-as-a-Judge 检查 answer_basis 中是否有无法由 EvidencePool 支持的断言。

```text
unsupported_claim_rate =
  unsupported_claim_count / total_claim_count
```

目标：

```text
standard <= 0.10
deep <= 0.08
```

## 5.4 Cost / Latency Metrics

### Latency

记录：

```text
p50_latency_ms
p95_latency_ms
max_latency_ms
```

建议目标：

```text
quick p95 <= 8s
standard p95 <= 20s
deep p95 <= 45s
```

### LLM Calls

记录：

```text
planner_llm_calls
query_analysis_llm_calls
judge_llm_calls
total_llm_calls
```

目标：

```text
quick avg total_llm_calls <= 3
standard avg total_llm_calls <= 6
deep avg total_llm_calls <= 10
```

### Search Calls

记录：

```text
scope_finder_calls
source_backtrack_calls
pku_requery_calls
pku_graph_expand_calls
ckp_expand_calls
chunk_search_calls
global_fallback_calls
```

用于定位慢点和过度搜索。

## 6. 输出文件

建议新增脚本：

```text
engine/eval/run_deep_knowledge_search_eval.py
```

输出目录：

```text
evaluation/runs/deep_search/<timestamp>/
```

输出文件：

```text
summary.json
detailed.csv
detailed_verbose.json
coverage_report.md
failure_cases.md
```

### summary.json

```json
{
  "meta": {
    "dataset": "evaluation/datasets/deep_knowledge_search_v1.json",
    "run_at": "...",
    "total_queries": 50,
    "chains": ["traditional_hybrid", "governed_evidence", "deep_standard"],
    "llm_model": "...",
    "embedding_model": "..."
  },
  "aggregates": {
    "deep_standard": {
      "ckp_recall@5": {"mean": 0.0},
      "pku_recall@10": {"mean": 0.0},
      "source_recall@10": {"mean": 0.0},
      "grounded_evidence_rate": 0.0,
      "completion_rate": 0.0,
      "correct_stop_rate": 0.0,
      "coverage_score": {"mean": 0.0},
      "grounding_score": {"mean": 0.0},
      "conflict_check_accuracy": 0.0,
      "structure_check_accuracy": 0.0,
      "unsupported_claim_rate": 0.0,
      "latency_ms": {"p50": 0, "p95": 0},
      "avg_iterations": 0.0,
      "avg_llm_calls": 0.0
    }
  }
}
```

### detailed.csv

字段：

```text
query_id
category
question
chain
status
stop_reason
iterations
ckp_recall@5
pku_recall@10
source_recall@10
grounded_evidence
coverage_score
grounding_score
source_diversity_score
conflict_score
structure_score
overall_score
conflict_checked
structure_checked
unsupported_claim_count
latency_ms
llm_calls
search_calls
global_fallback_used
scope_less_chunk_search
```

### detailed_verbose.json

每条 query 保存：

```json
{
  "query_id": "...",
  "question": "...",
  "expected": {},
  "result": {
    "answer_basis": {},
    "coverage_report": {},
    "evidence_pool": {},
    "search_trace": [],
    "sources": [],
    "stop_reason": "judge_complete"
  },
  "metrics": {}
}
```

## 7. Benchmark 运行方式

建议命令：

```powershell
python -m engine.eval.run_deep_knowledge_search_eval `
  --dataset evaluation/datasets/deep_knowledge_search_v1.json `
  --chains governed_evidence deep_standard `
  --verbose
```

可选：

```text
--depth quick|standard|deep
--max-queries 10
--no-llm-judge
--output-root evaluation/runs/deep_search
```

## 8. 离线 LLM-as-a-Judge

Deep Search 内部已有 Judge，但 benchmark 仍需要一个离线 evaluator，避免“自评自证”。

离线 evaluator 输入：

```json
{
  "question": "...",
  "expected_answer_aspects": [],
  "expected_evidence": {},
  "answer_basis": {},
  "evidence_pool": {}
}
```

输出：

```json
{
  "coverage_score": 0.0,
  "grounding_score": 0.0,
  "unsupported_claims": [],
  "missing_expected_aspects": [],
  "verdict": "pass | partial | fail"
}
```

离线 evaluator 与 runtime Judge 区别：

```text
runtime Judge:
  决定是否继续搜索。

offline evaluator:
  用黄金标注复核最终结果。
```

## 9. 阈值与验收标准

第一版上线门槛：

```text
deep_standard:
  ckp_recall@5 mean >= 0.70
  pku_recall@10 mean >= 0.60
  source_recall@10 mean >= 0.65
  grounded_evidence_rate >= 0.80
  completion_rate >= 0.70
  correct_stop_rate >= 0.95
  coverage_score mean >= 0.78
  grounding_score mean >= 0.75
  unsupported_claim_rate <= 0.10
  scope_less_chunk_search_count = 0
  global_fallback_violation_count = 0
```

相对现有基线：

```text
Deep Search standard 相比 governed_evidence:
  source_recall@10 不低于基线
  coverage_score 提升 >= 0.08
  grounding_score 提升 >= 0.05
  conflict_check_accuracy 提升 >= 0.15
```

性能门槛：

```text
standard:
  avg_iterations <= 3
  p95_latency_ms <= 20000
  avg_total_llm_calls <= 6
```

## 10. 面试可讲的量化指标

如果最终实现达标，可以这样表达：

```text
我把评测拆成三层：
1. 检索层：CKP Recall、PKU Recall、Source Recall。
2. 链路层：completion rate、correct stop rate、平均迭代数、fallback violation。
3. 答案层：coverage score、grounding score、conflict/structure accuracy、unsupported claim rate。

这样能同时证明系统不是只“搜得多”，而是更完整、更可追溯、更少幻觉，并且成本可控。
```

## 11. 风险与注意事项

1. 内部 runtime Judge 不能作为唯一评测来源，必须有离线 evaluator。
2. 黄金集必须标注 CKP/PKU/source/relation，否则无法评估治理层能力。
3. 延迟指标要区分冷启动和热启动。
4. 如果 Milvus 或 MySQL 不可用，结果要标记为 invalid run，不纳入有效 benchmark。
5. 对 conflict/structure 类问题要单独统计，不能被普通 source_fact 问题稀释。

## 12. 最小实现顺序

```text
1. 定义 deep_knowledge_search_v1.json 标注格式。
2. 先构造 10 条 smoke dataset。
3. 实现 run_deep_knowledge_search_eval.py 的详细输出。
4. 接入 deep_knowledge_search 工具。
5. 先跑 smoke，确认 search_trace 和 stop_reason 正确。
6. 扩展到 50 条完整 benchmark。
7. 对比 governed_evidence / traditional_hybrid / deep_standard。
```
