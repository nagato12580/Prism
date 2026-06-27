# 自底向上检索链路离线测评报告

## 1. 本次测评对象

本次新增并测评 `bottom_up` 自底向上检索链路。

链路逻辑：

```text
用户问题
 -> PKU 向量召回
 -> PKU 关键词/实体/证据字段词面召回
 -> 合并 PKU 候选并打分
 -> 通过 pku_canonical_link 回溯 CKP
 -> 通过 PKU.source_kind/source_id 回溯 document_chunk
 -> parent chunk 在评测中展开到 child chunk
```

这条链路与之前 `governed_evidence` 的区别是：`governed_evidence` 先召回 CKP，再展开 PKU；`bottom_up` 先从 PKU 证据层找入口，再回到 CKP 和来源。

## 2. 测评配置

- 数据集：`evaluation/datasets/formal_docs_v1.json`
- 问题数：60
- 模型：`deepseek-v4-flash`
- Embedding：`jina-embeddings-v3`
- 输出目录：`evaluation/runs/retrieval/2026-06-24_161140_compare/`
- 运行命令：

```powershell
python -m engine.eval.compare_retrieval_chains --dataset evaluation/datasets/formal_docs_v1.json --chains bottom_up --verbose
```

## 3. 核心结果

| 链路 | Exact Recall@10 | Expanded Recall@10 | Expanded MRR | Expanded Hit@10 |
| --- | ---: | ---: | ---: | ---: |
| bottom_up | 0.000 | 0.793 | 0.713 | 83.3% |

Exact 指标为 0 是预期现象：PKU 通常挂在 parent chunk 上，而黄金集标注的是 child chunk。Expanded 指标会把 parent chunk 展开到 child chunk，更能反映这条 CKP/PKU 证据链路的真实召回能力。

## 4. 与历史结果对比

历史记录中的关键结果：

| 链路 | Expanded Recall@10 | Expanded MRR | Expanded Hit@10 |
| --- | ---: | ---: | ---: |
| traditional_hybrid | 0.516 | - | 95.0% |
| governed_ckp_pku | 0.281 | 0.207 | 28.3% |
| governed_evidence + PKU vector | 0.602 | 0.475 | 61.7% |
| governed_evidence baseline | 0.632 | 0.492 | 65.0% |
| bottom_up | 0.793 | 0.713 | 83.3% |

结论：自底向上链路在当前黄金集上明显优于已有 CKP/PKU 链路，也超过了 `governed_evidence`。它没有超过传统 hybrid 的 Hit@10，但 MRR 和 Recall 已经说明 PKU 作为入口节点非常有效。

## 5. 失败样本观察

Expanded Hit@10 未命中的问题包括：

- `q005`：模型微调新手推荐工作流。
- `q018`：`lora_dropout` 默认值。
- `q046`：全量微调、LoRA、QLoRA 优缺点。
- `q053`：LLM 评分阈值低时应采取哪些措施。
- `q060`：C++ 表设计规范中单实例表个数限制。

部分问题在 Top20 才命中，例如：

- `q008`：有效日期，相关 child 在第 18 位。
- `q017`：高斯分布初始化 A，相关 child 在第 14 位。
- `q039`：Python 格式化工具和行宽，相关 child 在第 13 位。
- `q044`：RAG 检索组件评测指标，相关 child 在第 18 位。
- `q055`：防止重复长文本，相关 child 在第 18 位。

这说明自底向上链路的“找得到”能力较强，但 Top10 排序仍有优化空间。

## 6. 当前实现说明

本次为了离线测评，在 `engine/eval/compare_retrieval_chains.py` 中新增：

- `_query_bottom_up()`
- `_bottom_up()`
- `bottom_up` chain map 注册

当前打分为轻量融合：

```text
PKU vector score: 0.65
PKU lexical score: 0.35
PKU confidence: 0.05 boost
```

词面字段：

```text
statement
normalized_statement
evidence_span
keywords
concepts
entities
domains
```

## 7. 判断

这次结果支持之前的架构判断：对于当前 CKP/PKU 体系，底层 PKU 更适合作为问题入口。原因是 PKU 的 `statement/evidence_span/keywords` 与用户问题处在更接近的语义空间，命中后再沿图回溯 CKP/source，比先找 CKP 更稳。

建议下一步不要把它只停留在评测脚本里，而是做成正式的 agent 检索工具或接入 `knowledge_evidence_search`：

```text
用户问题
 -> bottom_up PKU 入口召回
 -> CKP 图扩展
 -> sibling PKU / source 展开
 -> 路径打分
 -> LLM rerank
```

短期优化重点：

1. 把 Top20 命中但 Top10 未命中的样本做排序错误分析。
2. 增加 source/item title 约束，减少跨文档相似 PKU 噪声。
3. 对数值、参数、默认值类问题增加关键词精确匹配 boost。
4. 与 traditional hybrid 做融合，保留传统链路的高 Hit@10 优势。
