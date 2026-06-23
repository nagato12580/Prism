# Governed Evidence 检索链路测评报告

## 本次运行信息

- 测评集：`evaluation/datasets/formal_docs_v1.json`
- 问题数量：60
- 运行目录：`evaluation/runs/retrieval/2026-06-22_155519_compare/`
- 对比链路：
  - `traditional_hybrid`
  - `governed_ckp_pku`
  - `governed_evidence`
- 大模型：`deepseek-v4-flash`
- 向量模型：`jina-embeddings-v3`

## 改造目标

这次改造的目标不是替换原来的 CKP/PKU 治理链路，而是在保留原有语义治理能力的基础上，新增一条专门面向“证据召回”和“离线测评”的链路：`governed_evidence`。

原来的 `governed_ckp_pku` 更像语义治理链路，适合做知识点归纳、稳定结论召回、跨来源综合。新链路 `governed_evidence` 更偏证据检索，目标是通过 CKP/PKU 结构找到能支撑回答的原文证据，并能和 child chunk 粒度的黄金集对齐。

## 这次具体改了什么

第一阶段完成了 6 个核心改造：

1. **增加查询时 CKP 向量召回**
   - 使用已有的 `prism_ckp` 向量集合。
   - 查询时不再只依赖“最近 80 条 CKP”。
   - 让语义相近但关键词不完全一致的 CKP 有机会进入候选集。

2. **增加 CKP 全量 lexical 候选**
   - 对 CKP 的标题、标准表述、摘要、关键词、概念，以及关联 PKU 文本做关键词匹配。
   - 作为 CKP 向量召回的补充。

3. **融合 CKP 向量候选和关键词候选**
   - 将向量召回和关键词召回的 CKP 候选融合排序。
   - 避免单一路径失效。

4. **对 linked PKU 做 query-aware 重排**
   - 原来 linked PKU 主要按 `link confidence` 和创建时间排序。
   - 新链路会根据当前 query 对 PKU 的 `statement`、`normalized_statement`、`evidence_span`、`keywords` 等字段重新打分。
   - 这样可以把“当前问题真正相关的证据”排到前面。

5. **显式支持 parent-child evidence 展开**
   - 当前 PKU 主要挂在 parent chunk 上，而黄金集标注的是 child chunk。
   - 新链路仍然把 parent chunk 作为检索单位返回，但评测时会展开 parent 下的 child chunk。
   - 这样可以避免把一个正确 parent 的多个 child 拆散后浪费 TopK 预算。

6. **评测脚本新增三链路对比**
   - 原先只对比 `traditional_hybrid` 和 `governed_ckp_pku`。
   - 现在新增 `governed_evidence`，可以同时看传统 RAG、原治理链路、新证据链路三者的表现。

## 关键修复

调试过程中发现一个重要排序问题：

原实现里，evidence 模式下 source 的分数使用的是：

```text
max(ckp_score, evidence_score, link_confidence)
```

这个逻辑会导致一个问题：即使某个 PKU 和当前 query 不相关，只要它的 `link_confidence` 很高，它仍然会把真正相关的 PKU 挤下去。

最终修复为：

```text
evidence 模式下 source score = query-aware PKU evidence score
```

也就是说，在 `governed_evidence` 链路里，证据排序优先服务当前问题，而不是优先服务历史治理置信度。

## 设计思想

这次设计的核心判断是：

**CKP 不应该被改造成另一个 chunk 索引。**

CKP 的价值是稳定、归一、可治理的知识点；PKU 的价值是承载具体证据；chunk 的价值是提供原文上下文。因此新链路按三层结构组织：

- **CKP**：标准知识点，用来做语义归并和候选路由。
- **PKU**：个人知识单元，用来承载证据陈述。
- **Chunk**：原始文档片段，用来做回答 grounding 和离线测评。

因此，`governed_evidence` 的目标不是“用 CKP 替代传统 RAG”，而是让 CKP/PKU 成为一个更强的证据编排层。

## 测评结果

| 链路 | Exact Recall@10 | Expanded Recall@10 | Expanded MRR | Expanded Hit@10 |
| --- | ---: | ---: | ---: | ---: |
| `traditional_hybrid` | 0.516 | 0.516 | 0.864 | 95.0% |
| `governed_ckp_pku` | 0.000 | 0.281 | 0.207 | 28.3% |
| `governed_evidence` | 0.000 | 0.632 | 0.492 | 65.0% |

第一阶段目标：

- `Expanded Hit@10 >= 60%`：已达成。
- `Expanded Recall@10 >= 45%`：已达成。

相比原 `governed_ckp_pku`：

- `Expanded Recall@10`：0.281 -> 0.632
- `Expanded Hit@10`：28.3% -> 65.0%
- `Expanded MRR`：0.207 -> 0.492

## 为什么 Exact Recall 仍然是 0

这是评测口径导致的，不代表链路没有召回证据。

当前黄金集标注的是 child chunk，而 CKP/PKU 文档证据主要挂在 parent chunk 上。`governed_evidence` 有意把 parent chunk 作为证据检索单位返回，再通过 expanded 指标展开到 child chunk 进行评测。

因此，对 `governed_evidence` 来说，更有意义的指标是：

- `Expanded Recall@10`
- `Expanded MRR`
- `Expanded Hit@10`

而不是严格 chunk_id 直连匹配的 `Exact Recall@10`。

## 失败样本分析

`governed_evidence` 在 60 个问题中仍有 21 个问题没有在 Hit@10 命中。

失败样本按文档分布：

- `面试常见问题`：9
- `大模型微调指南`：4
- `好未来`：4
- `C++编码规范V01.00`：3
- `python_coding_standards`：1

主要失败类型：

1. **英文问题查询中文资料**
   - 英文 query 和中文 CKP/PKU 文本之间词面重合弱。
   - 当前 CKP 向量文本还不够丰富，不能很好覆盖跨语言表达。

2. **非常细粒度的数值或章节问题**
   - 例如默认值、生效日期、章节编号等。
   - 这类问题常常只出现在很小的 evidence span 里，CKP 标题和摘要可能不会包含。

3. **CKP 表述比较宽泛，答案只在某个具体 PKU/原文片段里**
   - CKP 能召回到正确主题，但 linked PKU 或 parent chunk 排序还不够细。

4. **同一个 CKP 下有多个相近 PKU**
   - 当前 query-aware rerank 已经改善了这个问题，但仍有部分正确 parent 排在 Top10 之外。

## 性能问题

加入 query-time CKP 向量召回后，三链路完整测评明显变慢。原因是每个 query 都会调用 embedding 和 CKP vector search。

这在离线第一阶段测评中可以接受，但如果要进入在线链路，需要继续优化：

- 对 query embedding 做缓存。
- 对评测集做批量向量查询。
- 缓存 parent chunk 到 child chunk 的展开结果。
- 建立 CKP/PKU lexical index，避免每次 query 都扫全量 CKP。

## 下一阶段建议

下一阶段应该重点提升细粒度证据覆盖能力：

1. **增加 PKU 向量检索**
   - 当前只做 CKP 向量召回。
   - 很多细粒度答案只存在 PKU/evidence_span 中，因此需要 query -> PKU -> CKP 的反向召回。

2. **升级 CKP embedding text**
   - 当前 CKP 向量文本主要来自标题、标准表述、摘要、关键词、概念。
   - 后续应加入别名、代表性 PKU statement、代表性 evidence span、可能的问题表达。

3. **增加中英双语 query expansion**
   - 特别是英文问题检索中文文档时，需要把 query 改写或翻译成中文检索表达。

4. **引入更强的 CKP-PKU-evidence reranker**
   - 当向量召回和关键词融合进入瓶颈后，可以用 cross-encoder 或 LLM judge 对候选证据重排。

5. **优化在线性能**
   - query embedding 缓存。
   - CKP/PKU 候选缓存。
   - parent-child 展开缓存。

## 结论

第一阶段证明了 CKP/PKU 不只是知识治理结构，也可以作为有效的证据检索编排层。

新链路 `governed_evidence` 相比原 `governed_ckp_pku` 有明显提升：

```text
Expanded Recall@10: 0.281 -> 0.632
Expanded Hit@10:    28.3% -> 65.0%
Expanded MRR:       0.207 -> 0.492
```

但它和 `traditional_hybrid` 仍然有差距，尤其是在非常细粒度、跨语言、数值类问题上。下一阶段的关键不是继续微调 CKP 排序，而是补上 PKU 级向量检索和更强的 evidence rerank。
