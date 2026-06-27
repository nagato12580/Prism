# governed_knowledge_v2 离线评测报告

## 评测结论

本次在 `dev` 分支对 `governed_knowledge_v2` 做了快速离线评测，评测集使用 `evaluation/datasets/formal_docs_v1_first20.json`，共 20 条 query。

需要特别注意：当前环境下 Milvus 不可达，`governed_knowledge_v2` 没有真正进入 vector-first 的 v2 召回路径，而是 fallback 到传统 `hybrid_search`。因此本次指标不能证明 v2 新链路的真实效果，只能作为 fallback 行为和评测接入是否正常的验证。

## 环境与链路状态

- 当前分支：`dev`
- 被测链路：`governed_knowledge_v2`
- 评测入口：`engine/eval/compare_retrieval_chains.py`
- v2 实现：`engine/app/agent/tools/governed_knowledge_v2.py`
- Milvus 连通性检查结果：
  - `_ensure_milvus() = False`
  - `_milvus_reachable = False`
- 实际执行路径：`governed_knowledge_v2` -> Milvus 不可达 -> fallback 到 `hybrid_search`

## 指标结果

有效结果目录：

`evaluation/runs/retrieval/2026-06-24_173021_compare`

### governed_v2

- Exact Recall@10：0.325
- Expanded Recall@10：0.728
- Expanded MRR：0.703
- Expanded Hit@10：85.0%
- 评测条数：20
- 失败条数：0

### 对照：traditional_hybrid，同一 20 条 query

- Exact Recall@10：0.325
- Expanded Recall@10：0.728
- Expanded MRR：0.703
- Expanded Hit@10：85.0%

## 结果解读

`governed_v2` 与 `traditional_hybrid` 在同一批 20 条 query 上指标完全一致，这和当前代码路径一致：v2 因为 Milvus 不可达，回退到了传统 hybrid 检索。

所以这次评测说明两件事：

1. `governed_knowledge_v2` 已经可以接入统一离线评测脚本。
2. 当前环境没有测到真实的 v2 vector-first 召回能力。

它没有说明：

1. v2 新链路优于传统 hybrid。
2. PKU vector 召回、CKP/PKU 分层召回、query-aware rerank 已经在真实链路里生效。

## 已完成的验证

执行了 v2 相关测试：

```powershell
python -m pytest engine/tests/test_governed_knowledge_v2.py engine/tests/test_compare_retrieval_chains.py -k "governed_v2 or governed_knowledge_v2" -q
```

结果：

```text
5 passed, 7 deselected
```

## 下一步建议

下一步不要先看全量指标，而是先确认 v2 是否真的进入 Milvus/vector-first 路径。建议按下面顺序推进：

1. 修复或确认 Milvus 连接，确保 `prism_knowledge` collection 可访问。
2. 在 `governed_knowledge_v2` 返回结果中增加链路遥测字段，例如 `retrieval_backend = "milvus" | "hybrid_fallback"`。
3. 先跑 5 到 10 条 query 的 smoke eval，确认每条 query 都走 `milvus`。
4. 再跑完整 60 条黄金评测集，对比 `traditional_hybrid`、`bottom_up`、`governed_v2`。

只有第 3 步确认真实 v2 路径生效后，全量指标才有架构判断价值。

## 本次未完成项

尝试使用完整 60 条 `evaluation/datasets/formal_docs_v1.json` 单独评测 `governed_v2`，命令运行 10 分钟后超时，生成了目录 `evaluation/runs/retrieval/2026-06-24_174503_compare`，但没有生成 `summary.json`，因此不作为有效评测结果。
