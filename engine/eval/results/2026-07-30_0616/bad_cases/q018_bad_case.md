# Bad Case: q018

**Question:** MVOT中的运输矩阵T(p)的维度是多少
**Paper:** 3746027.3754701.pdf
**Type:** data_detail

## Answer
当前没有可用的个人知识库，我无法从你的资料中检索到具体上下文。不过，基于多边缘最优传输（MVOT）的通用定义，可以给出一般性说明：

---

在 **多边缘最优传输（Multi-marginal Optimal Transport）** 中，运输矩阵（也叫运输计划/传输计划）是一个**多维张量**，而非标准的二维矩阵。

设问题的边缘分布（marginals）个数为 **m**，第 k 个边缘分布的支撑点个数为 **n_k**，则运输张量 $T(p)$ 的维度为：

> **n₁ × n₂ × ... × n_m**

即一个 **m 阶张量**（m-dimensional tensor / m-way array）。

### 举例
- 若 **m = 2**（即两个边缘分布的经典最优传输），$T(p)$ 是 **n₁ × n₂** 的二维矩阵——这就是经典 Kantorovich 运输矩阵。
- 若 **m = 3**（三边缘），$T(p)$ 是 **n₁ × n₂ × n₃** 的三维张量。
- 一般地，有 m 个边缘时，$T(p)$ 的元素 $T_{i_1 i_2 \ldots i_m}(p)$ 表示从每个边缘的第 $i_k$ 个支撑点同时运输的数量。

---

**不确定点**：不同的文献（如 Brenier、Pass、Gangbo 等人的工作）中对 $T(p)$ 的定义细节可能略有差异（例如是否显式包含参数 p 的映射关系）。如果你能告诉我你参考的是哪篇具体论文或笔记，我可以给出更精确的答案。

## Judge Scores
- Faithfulness: 1
- Relevance: 1
- Completeness: 1
- Overall: 1.0
- Rationale: 模型回答完全未基于知识库内容，编造了多边缘传输的通用定义，而知识库明确给出T(p)是n×m矩阵。

## Sources Cited


## Metadata
- TTFB: 26ms
- Total latency: 11059ms
- Tool calls: 1
