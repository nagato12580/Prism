# PKU 向量召回改造与离线测评报告

## 1. 本阶段做了什么

本阶段目标是给 PKU 增加独立向量召回能力，让查询不只能先命中 CKP，再间接展开 PKU；而是可以直接命中细粒度证据 PKU，再通过 `PKUCanonicalLink` 回溯到 CKP 和原始 chunk。

已完成的链路包括：

1. 新增 `prism_pku` 向量集合与 `backend/app/services/pku_vectors.py`，支持 `upsert_pku_vector()` 和 `search_pku_vectors()`。
2. PKU 创建后自动刷新向量，覆盖 `personal_asset_item`、`personal_asset_unit`、`document_chunk` 三类来源。
3. 新增历史 PKU 回填脚本 `backend/scripts/backfill_pku_vectors.py`。
4. `governed_evidence` 查询时新增 PKU vector recall：
   - query -> PKU vector hits
   - PKU -> CKP link 回溯
   - 融入 CKP 候选集合
   - 对命中的 PKU evidence 做轻量加分
   - 继续返回 parent evidence，并展开 child evidence 参与 expanded metric

## 2. 设计思想

这次改造的核心判断是：CKP 负责“知识主题组织”，PKU 负责“证据命中”。

CKP 的标题、摘要、canonical statement 往往比较抽象，适合归并和路由，但细粒度问答里真正能回答问题的内容经常落在 PKU 的 `statement`、`normalized_statement`、`evidence_span` 里。因此新增 PKU 向量召回，不是为了替代 CKP，而是给查询增加一条更靠近证据层的入口。

当前融合策略是保守融合：

- CKP vector 仍然保留；
- CKP lexical 仍然保留；
- PKU vector 只负责补充召回 CKP 候选；
- evidence 排序仍以 PKU 文本相关性为主，PKU vector 只做轻量 boost。

原因是本轮调试发现，PKU vector 如果直接强力参与排序，会把一些泛化的训练/微调类 PKU 顶到前面，挤掉原来文本匹配更强的证据。

## 3. Backfill 结果

原计划运行：

```powershell
python -m backend.scripts.backfill_pku_vectors --user-id default-user --limit 1000
```

这次大批量运行耗时过长，执行后没有自然输出最终统计；随后用小批量命令确认状态：

```powershell
python -m backend.scripts.backfill_pku_vectors --user-id default-user --limit 20
```

结果：

```text
scanned: 20
updated: 0
skipped: 20
failed: 0
```

当前数据库状态分布：

```text
active PKU 总数: 661
active 且 embedding_status=done: 100
active 且 embedding_status=pending: 561
active 且有 embedding_ref: 100
```

结论：本轮只完成了部分历史 PKU 向量化。后续需要把 backfill 改成可观测、可恢复、可批量 embedding 的任务，而不是一次性长跑脚本。

## 4. 离线测评结果

数据集：`evaluation/datasets/formal_docs_v1.json`

样本数：60

最新结果目录：

```text
evaluation/runs/retrieval/2026-06-22_170217_compare/
```

三条链路结果：

| 链路 | Exact Recall@10 | Expanded Recall@10 | Expanded MRR | Expanded Hit@10 |
| --- | ---: | ---: | ---: | ---: |
| traditional_hybrid | 0.516 | 0.516 | 0.856 | 95.0% |
| governed_ckp_pku | 0.000 | 0.281 | 0.207 | 28.3% |
| governed_evidence + PKU vector | 0.000 | 0.602 | 0.475 | 61.7% |

上一轮 `governed_evidence` 基线：

```text
Expanded Recall@10: 0.632
Expanded Hit@10:    65.0%
Expanded MRR:       0.492
```

本轮接入 PKU vector 后：

```text
Expanded Recall@10: 0.602
Expanded Hit@10:    61.7%
Expanded MRR:       0.475
```

结论：PKU vector recall 已经在代码链路上生效，但当前离线指标没有超过上一轮 governed_evidence 基线，也没有达到 Phase 2 目标。

## 5. 为什么没有提升

这轮调试对比了 `2026-06-22_155519_compare` 和 `2026-06-22_170217_compare` 的 query 级结果，发现主要问题是：PKU vector 会召回一些语义相近但主题偏宽的 PKU，例如微调数据格式、训练集/验证集、LoRA 参数等内容。这些 PKU 在向量空间里和多个问题接近，但不一定是当前问题的正确证据。

典型恶化样本包括：

- q016：Beam Search 问题，正确证据从 rank 1 掉出 top10。
- q049：NDCG 计算步骤，正确证据从 rank 1 掉到 rank 17。
- q054：LoRA A/B 矩阵初始化，正确证据从 rank 1 掉到 rank 16。
- q056：PRM 目标，正确证据从 rank 1 掉到 rank 17。

已经做过一次修正：把 PKU evidence boost 从强加权改成轻量加分，指标从：

```text
Expanded Recall@10: 0.566
Expanded MRR:       0.400
Expanded Hit@10:    58.3%
```

恢复到：

```text
Expanded Recall@10: 0.602
Expanded MRR:       0.475
Expanded Hit@10:    61.7%
```

但仍低于上一轮基线，说明下一步不能继续简单调大权重，而要加门控。

## 6. 下一步建议

下一阶段建议做“PKU vector 门控融合”，而不是继续盲目调权重：

1. PKU vector hit 只有在满足 query term overlap、source domain 一致、link confidence 达标时才进入 CKP 候选。
2. 对 PKU vector 召回结果按 linked CKP 的 lexical score 做二次过滤，没有任何 lexical 支撑的候选只进扩展候选池，不进 top 排序池。
3. 对高频泛化 PKU 加降权，例如训练格式、通用配置、泛化经验类 PKU。
4. 给 backfill 增加进度输出、断点续跑、批量 embedding 和失败重试。
5. 后续重新完整 backfill 661 条 active PKU 后，再重跑本测评集。

## 7. 本轮结论

本轮完成了 PKU 向量链路的工程接入和可测试闭环，但还没有完成指标意义上的 Phase 2 达标。

当前链路已经具备继续优化的基础：PKU 可写入向量、可回填、可 query-time 检索、可通过 link 回溯 CKP、可降级。但离线评测显示，PKU vector 需要门控和重排约束，否则会带来语义泛化噪声。
