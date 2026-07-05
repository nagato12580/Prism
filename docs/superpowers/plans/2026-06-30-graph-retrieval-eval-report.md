# 图检索离线测评报告

> 日期：2026-06-30
> 数据集：`evaluation/datasets/formal_docs_v1.json`（60 题，标注 relevant child chunks）
> 测评脚本：`engine/eval/compare_retrieval_chains.py`（新增 `graph_ckp_pku`、`graph_source` 两条 Neo4j 图检索链）
> 运行产物：`evaluation/runs/retrieval/2026-06-30_072848_compare/`

## 一、测评设计

### 新增图检索链

| 链名 | Cypher 路径 | 原语 | 说明 |
|---|---|---|---|
| `graph_ckp_pku` | CKP(title CONTAINS term) →SUPPORTED_BY→ PKU →EVIDENCED_BY→ Source(document_chunk) | 图遍历 + 词法匹配 | 从 CKP 主题节点出发，沿治理关系回溯到原始 chunk |
| `graph_source` | Source(title CONTAINS term, source_kind=document_chunk) | 图索引词法匹配 | 直接在 Neo4j Source 节点上做 title 词法匹配 |

两条链均用 `_query_terms(query)` 提取查询词（与 governed 链相同的分词逻辑），在 Neo4j 上执行 Cypher CONTAINS 匹配 + 关系遍历，**不依赖 Milvus 向量**，单链 60 题执行 <5 秒。

### 对照链（已有基线）

| 链名 | 原语 | 基线来源 |
|---|---|---|
| `traditional_hybrid` | Milvus 向量 + BM25 RRF 融合 | 本次同环境重跑 |
| `governed_ckp_pku` | MySQL CKP 词法 → PKU → Source（V1） | 2026-06-22 基线 |
| `governed_evidence` | MySQL CKP+PKU 词法+向量 → Source（V1+PKU vector） | 2026-06-22 基线 |

### 指标

- **exact**：检索到的 chunk_id 直接与标注的 relevant child chunk_id 比对
- **expanded**：检索到的 parent chunk 展开为其 child chunk 后再比对（治理链常回溯到 parent，故 expanded 更公平）
- Recall@10、Hit@10（至少命中 1 个相关 chunk 的查询比例）、MRR

## 二、Neo4j 图数据现状

| 节点/关系 | 数量 | 可用于检索的属性 |
|---|---|---|
| CKP | 552 | `title`、`ckp_type`、`status`、`confidence` |
| PKU | 4920 | `unit_type`、`confidence`（**无 statement 文本**） |
| Source | 4900 | `title`、`source_id`、`source_kind`、`item_id` |
| Source(document_chunk) | 974 | 同上 |
| SUPPORTED_BY (CKP→PKU) | 800 | — |
| EVIDENCED_BY (PKU→Source) | 820 | — |
| **CKP→PKU→Source(doc) 可达 chunk** | **97** | — |

关键限制：**仅 97 个 document chunk 经 CKP→PKU→Source 路径可达**（占 974 个 document_chunk Source 的 10%），PKU 节点无 statement 文本（只在 MySQL 中有），CKP 仅有 title 做词法匹配。

## 三、量化结果

### 各链独立指标（expanded，60 题）

| 链 | Recall@10 | Hit@10 | MRR | 延迟 |
|---|---|---|---|---|
| traditional_hybrid | 0.511 | 95.0% (57/60) | 0.863 | ~40s（含 Milvus embedding） |
| governed_evidence | 0.602 | 61.7% (37/60) | 0.475 | 基线（含 PKU 向量） |
| governed_ckp_pku | 0.281 | 28.3% (17/60) | 0.207 | 基线 |
| **graph_ckp_pku** | **0.030** | **3.3% (2/60)** | **0.008** | **<3s** |
| **graph_source** | **0.030** | **3.3% (2/60)** | **0.010** | **<3s** |

### 融合分析（best-of：对每题取各链最高 recall）

| 融合组合 | Recall@10 | Hit@10 | vs 主链 recall 增量 |
|---|---|---|---|
| traditional 单独 | 0.511 | 95.0% | — |
| traditional ⊕ graph（best-of） | **0.531** | 95.0% | **+0.020 (+3.9%)** |
| governed_evidence 单独 | 0.602 | 61.7% | — |
| governed_evidence ⊕ graph（best-of） | **0.605** | 61.7% | +0.003 (+0.5%) |

### 图检索命中的 2 题深度对比

| 查询 | 问题 | 相关 chunk 数 | traditional R@10 | graph_ckp R@10 | graph_source R@10 |
|---|---|---|---|---|---|
| q013 | Python 编码规范中函数参数过多时推荐哪种封装方式 | 5 | 0.4 (2/5) | **0.8 (4/5)** | **1.0 (5/5)** |
| q058 | 模型预测置信度在 0.60-0.90 之间时应该如何处理 | 5 | 0.4 (2/5) | **1.0 (5/5)** | 0.8 (4/5) |

### 传统漏检的 3 题（图能否补上）

| 查询 | 问题 | traditional | graph_ckp | graph_source |
|---|---|---|---|---|
| q005 | 模型微调新手推荐工作流 | miss | miss | miss |
| q010 | 文本分类最小可行方案推荐数据量 | miss | miss | miss |
| q015 | 大模型微调评估指标如何组合使用 | miss | miss | miss |

**结论：图检索无法补上传统的覆盖盲区**（3 题均为图不可达 chunk）。

## 四、结论与解释

### 图检索的优势：概念规则型查询的召回深度

q013/q058 是**概念规则型问题**（"函数参数封装方式"、"置信度阈值处理"），它们恰好映射到 CKP 主题节点。CKP 节点聚合了多个 PKU 证据单元，每个 PKU 通过 EVIDENCED_BY 指向不同 Source chunk。图遍历一次沿 CKP→PKU→Source 路径即可**召回该概念下的全部相关 chunk**（5/5, recall=1.0），而传统向量检索只召回语义最相似的 2/5（recall=0.4）。

这是图检索的核心价值：**当查询能命中 CKP 主题节点时，沿治理关系遍历的召回完整性优于向量相似度排序**。

### 图检索的劣势：覆盖面不足

- **Hit@10 仅 3.3%**（2/60）：仅 97 个 chunk 经 CKP→PKU→Source 可达，且 CKP title 词法匹配对自然语言长问题命中率低。
- **不补覆盖盲区**：传统/governed 漏检的查询，其相关 chunk 不在图的可达集中。
- **PKU 节点无文本属性**：Neo4j 投影时未写入 `statement`/`normalized_statement`，导致 PKU 层无法做文本匹配，只能靠 CKP title 间接命中。

### 融合价值

| 场景 | 图检索贡献 |
|---|---|
| 与 traditional 融合 | Hit@10 不变（95%），recall +3.9%（0.511→0.531），在 2 题重叠区提升召回深度 |
| 与 governed_evidence 融合 | Hit@10 不变（61.7%），recall +0.5%，增益微弱 |

图检索作为**互补信号**有增量但有限，主要受限于图投影的覆盖面。

## 五、改进建议

1. **扩大图投影覆盖**：将 PKU `statement`/`normalized_statement`/`keywords` 写入 Neo4j PKU 节点，使 PKU 层可做文本匹配（当前只有 `unit_type`/`confidence`）。这会使 CKP→PKU→Source 路径的可达 chunk 从 97 扩展到接近 974。
2. **CKP title 增强**：将 CKP `keywords`/`concepts`/`canonical_statement` 写入 Neo4j CKP 节点（当前只有 `title`），提升词法命中率。
3. **融合策略**：图检索不适合作为独立检索器，应作为 **reranking/boost 信号**——当图命中 CKP 时，对该 CKP 关联的 chunk 在传统召回结果中做 score boost，而非独立召回。
4. **实体检索单独评测**：`entity_graph_search`（Alias→Entity→Source）的设计目标是命名实体查找，本次 golden 数据集无实体型查询，建议另建实体检索测评集（如"谭彦超出现在哪些资料里"）。

## 六、运行产物

| 文件 | 说明 |
|---|---|
| `evaluation/runs/retrieval/2026-06-30_072848_compare/summary.json` | traditional + graph_ckp_pku + graph_source 同环境对照 |
| `evaluation/runs/retrieval/2026-06-30_072705_compare/summary.json` | graph 链单独 + verbose（含检索 chunk 文本） |
| `evaluation/runs/retrieval/2026-06-30_072848_compare/detailed_expanded.csv` | 逐题 expanded 指标 |
| `engine/eval/compare_retrieval_chains.py` | 新增 `graph_ckp_pku`、`graph_source` 链 |
