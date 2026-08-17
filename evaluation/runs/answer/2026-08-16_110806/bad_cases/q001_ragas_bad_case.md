# Ragas Bad Case: q001

**Question:** 在RAG系统中，父子块之间的映射关系通常通过什么方式在工程落地中建立

**Tags:** hallucination_risk, noisy_context, missing_context, below_threshold:faithfulness, below_threshold:context_precision, below_threshold:context_recall

## Scores

{
  "faithfulness": 0.01818181818181818,
  "response_relevancy": 0.840821299084435,
  "context_precision": 0.0,
  "context_recall": 0.0
}

## Answer

**结论**：在当前知识库（"论文"库）中检索不到与 RAG 父子块映射直接相关的内容——命中的是一篇多视图聚类论文（BONE），与本题无关。因此以下回答基于通用工程实践知识，不作为知识库证据引用。

工程落地中建立父子块（parent-child chunk）映射的主流方式是**「两阶段切分 + 元数据 ID 引用」**，检索时"命中子块、回取父块"（即 small-to-big / ParentDocumentRetriever 模式）。具体有几种常见落地方式：

**1. 元数据 ID 引用（最主流）**
- 索引管线中先按较大粒度切出父块（如 512~1024 token 或整个章节），再在父块内部按较小粒度切出子块（如 128~256 token）。
- 每个子块写入 `parent_id` 元数据字段，父块写入 `child_ids` 列表。
- 存储时子块负责向量化/检索，父块保留全文用于最终喂给 LLM。代表实现：LangChain 的 `ParentDocumentRetriever`、LlamaIndex 的节点 `relationships`（CHILD/PARENT 关系）均基于此思路。

**2. 位置/偏移量区间映射**
- 切分时记录每个块在原文中的字符起止偏移（start/end offset）。
- 父子关系由"区间包含"推导：父块区间包含子块区间。适合需要动态重切、或按原文定位回填的场景。

**3. 文档结构层级解析**
- 对 Markdown/HTML/PDF 先按标题层级建树：父块 = 章节/小节，子块 = 其下的段落。
- 关系直接从解析出的 DOM/树结构获得，无需额外计算。LlamaIndex 的 `HierarchicalNodeParser` 即生成从粗到细的多层节点树，每层节点记录 source 节点 id。

**4. 存储层的落地**
- 向量库中通常用标量字段承载映射：如 `parent_id`、`group_id`、`document_id`（Milvus 标量过滤、pgvector 同表同字段、Weaviate 交叉引用）。
- 也可以用独立的映射表/清单（chunk_id ↔ parent_id ↔ file_id）维护，便于增量更新时级联重建。

**5. 查询时组装**
- 检索只对子块做向量相似度召回，命中后通过 `parent_id` 拉取父块全文（可带上下文窗口）再送入 LLM——这是该机制的核心价值：兼顾检索精度（小块）与上下文完整性（大块）。

**不确定点**：以上为业界常见做法，不同框架细节有差异（如块 ID 用 UUID 还是内容哈希、是否维护映射表）；你当前知识库里没有相关文献，若需要我基于某篇具体文档回答，可以告诉我文档名。

## Retrieved Contexts

0.1830.1270.217TLRLF40.7550.7130.7940.9920.9770.9920.7370.8220.7570.2140.2160.263Ours0.9060.8310.9060.9820.9520.9820.7840.8560.7990.3450.3040.366Table 1: Clustering performance of different traditional methods across various datasets, where N/A indicates program errorsor timeouts.It can be observed that our method generally achieves better performance compared to existing methods.priors or inadequately exploit inter-view relationships, thuslimiting applicability to complex MVC scenarios.Alter-natively, to avoid reliance on explicit constraints or post-processing feature fusion, we employ a contrastive strategyto extract discriminative consistency information.To achieve this, we adopt a view-shared label projectionhead fl({Zv}Vv=1; Wl) to derive the clustering assignmentmatrix Pv ∈Rk×n from {Zv}Vv=1:Pv = fl(Zv; Wl).(9)Subsequently, contrastive learning is employed to enhanceconsistency of Pv ∈Rk×n across views.The primary goalof contrastive learning is to maximize the similarity betweenpositive pairs (features from the same sample across dif-ferent views) and minimize the similarity between negativepairs (features from different samples across all views), thusencouraging discriminat

---

We first independently obtain high-level semantic information for each view using view-specific feature extraction modules.Then, we utilize a parameter-sharing label MLP to derive the clustering assignments foreach view.By employing contrastive training, we compel the network to capture consistency information across different views.Finally, the clustering assignments are achieved end-to-end.et al.2023; Su et al.2024).A broad category of traditionalmodels can be expressed as:minAv,ZvVXv=1fv(Xv, Av, Zv) + ϕv(Av) + ψv(Zv),s.t.Av ∈Xv, Zv ∈Yv,(1)where Xv ∈Rmv×n, and ϕ and ψ represent different regu-larization terms.The sets Xv and Yv denote the feasible re-gions for Av and Zv, respectively.For models based on dif-ferent prior assumptions, Av and Zv have varying interpre-tations.For instance, in anchor-based subspace MVC meth-ods, Av represents the anchor matrix, and Zv represents therepresentation matrix.In matrix factorization-based MVCmethods, Av represents the basis matrix, and Zv representsthe coefficient matrix.Traditional methods generally achieve consistency be-tween views in two ways.The first approach explicitly con-strains the representations or assignment matrices across dif

---

However, thisstrict constraint may overlook the noise and discrepanciesnaturally occurring between views, potentially limiting theeffectiveness of the representations (Zhou et al.2024).The second approach adopts relaxed constraints, allowingeach view to have its own representation matrix Zv (Konget al.2025; Zhang et al.2023; Kang et al.2020).After ob-taining view-specific representations, an additional fusionstep is often performed to achieve consistency (e.g., concate-nating columns and applying spectral clustering).Althoughthese methods achieve some degree of consistency betweenviews, they fail to fully exploit the inter-view relationshipsand suffer from the computational overhead of the fusionstep like SVD (Wan et al.2024; Liu et al.2022).Another challenge for traditional methods is obtainingclustering assignments after achieving consistent represen-tations.Existing methods typically rely on clustering algo-

---

Alter-natively, to avoid reliance on explicit constraints or post-processing feature fusion, we employ a contrastive strategyto extract discriminative consistency information.To achieve this, we adopt a view-shared label projectionhead fl({Zv}Vv=1; Wl) to derive the clustering assignmentmatrix Pv ∈Rk×n from {Zv}Vv=1:Pv = fl(Zv; Wl).(9)Subsequently, contrastive learning is employed to enhanceconsistency of Pv ∈Rk×n across views.The primary goalof contrastive learning is to maximize the similarity betweenpositive pairs (features from the same sample across dif-ferent views) and minimize the similarity between negativepairs (features from different samples across all views), thusencouraging discriminative and consistent multi-view rep-resentations.To this end, we construct positive pairs fromfeatures of the same sample across different views, and nega-tive pairs from features of different samples across all views.Formally, for each sample i, pairs {(pai , pbi) | a ̸= b} con-stitute positive samples, whereas pairs {(pai , pbj) | i ̸= j}are treated as negative samples.

---

The regularization coefficient λr balances the trade-offbetween the contrastive loss and the regularization term.Finally, the overall clustering assignment P is obtained bya weighted sum of the individual view assignments:P =VXv=1γvPPv,(11)where 0 ≤γvP ≤1 is the weight for the v-th view, andPVv=1 γvP = 1.We simply set the view weights equally, asis commonly done in deep MVC methods.The complete op-timization procedure for BONE is outlined in Algorithm 1.16070DatasetMFLVCCVCLDCMVCOursACC NMI Purity Params ACC NMI Purity Params ACC NMI Purity Params ACC NMI Purity ParamsHandWrite0.859 0.864 0.85928M0.968 0.929 0.96827M0.901 0.822 0.90121M0.977 0.944 0.97755KBDGP0.990 0.967 0.99011M0.990 0.967 0.9909M0.991 0.971 0.9918M0.992 0.973 0.99218KMRSC0.795 0.711 0.79519M0.910 0.820 0.91011M0.586 0.501 0.61015M0.938 0.881 0.93831KCOIL200.628 0.733 0.64724M0.750 0.816 0.76728M0.757 0.841 0.78221M0.769 0.844 0.790 227KCaltech5V0.747 0.681 0.

---

Formally, for each sample i, pairs {(pai , pbi) | a ̸= b} con-stitute positive samples, whereas pairs {(pai , pbj) | i ̸= j}are treated as negative samples.The contrastive loss for{Pv}Vv=1 is then formulated as:s(i, v, v′) = −logexp d(pvi , pv′i )/τn,VXj=1,u=11(j,u)̸=(i,v) exp d(pvi , puj )/τ,Lreg = 1VVXv=1 1kkXi=1qvi log qvi,LP =1nVn,VXi=1v=1 1V −1VXv′=1v′̸=vs(i, v, v′)+ λrLreg,(10)where d(pi, pj) =⟨pi,pj⟩∥pi∥∥pj∥denotes the cosine similaritybetween two clustering assignment vectors.The functions(i, v, v′) denotes the contrastive score, and the temperaturecoefficient τ controls the scale of similarity values (Chenet al.2020).The empirical cluster-assignment distributionqvi =1nPnj=1 pvij, which measures the average fraction ofsamples assigned to cluster i in view v.The regularizationterm Lreg is an entropy-based regularizer, encouraging a bal-anced use of clusters and thereby preventing degenerate so-lutions where most samples collapse into only a few clus-ters.The regularization coefficient λr balances the trade-offbetween the contrastive loss and the regularization term.

---

across different datasets, with the best and second-best re-16071(a) ACC(b) NMI(c) PurityFigure 3: Detailed training processes of different deep methods on the YouTubeFace50 dataset, where all methods except oursare pre-trained for 200 epochs.It can be observed that BONE can quickly achieve clustering performance comparable to existingdeep methods, without the need for any pre-training procedure.sults highlighted in bold and underlined, respectively.It canbe observed that our method outperforms existing methodson the majority of datasets, while showing comparable re-sults on the remaining datasets, even without the introduc-tion of explicit consistency or additional constraint assump-tions.This improvement is attributed to the feature extrac-tion capabilities of the neural network, which alleviates therepresentational limitations of classical methods by extract-ing high-level semantic representation from representationsobtained by optimization.Our method does not rely on ex-plicit consistency assumptions or post-processing feature fu-sion to obtain view consistency information, making it morerobust to complex MVC scenarios characterized by largemodality discrepancies or the presenc

---

6:Extract high-level semantic features using (6).7:end for8:Solve for the assignments {Pv}Vv=1 using (9).9:Compute the loss using (10) and backpropagate.10: end for11: Obtain the final cluster assignments from (11).Output: Cluster assignments P.Parameter ComplexityIn our proposed method, the parameters to be optimizedmainly consist of two components: the view-specific fea-ture extraction modules {{gv,le }Ll=1, Av0}Vv=1 and the labelprojection head fl.Specifically, the label projection headis a single fully connected layer structured as r →k.Consequently, the total number of parameters is r(V Lr +PVv=1 mv+k).Given that r is typically set as a small integer(commonly a few times the number of clusters k), the overallparameter complexity of BONE remains substantially lowercompared to existing deep MVC methods.ExperimentsThis section evaluates the effectiveness of the proposedmethod through clustering experiments conducted on sev-eral common datasets, including BDGP (Liu et al.2024b),HandWrite (Chen et al.2024), MNIST-USPS, COIL20, Cal-tech5V (Xu et al.2022), MSRC (Winn and Jojic 2005),ALOI (Zhang, Huang, and Wang 2023), CCV (Jiang et al.2011), YouTubeFace50 (Wan et al.2023).All experim

---

Bridging Optimization and Neural Networks for Efficient Multi-view ClusteringHuilang Xu1, Xiang-Xiang Su1, Simin Chen1, Guang-Yong Chen1*, Xing Chen1*1College of Computer and Data Science, Fuzhou University, Fuzhou, Chinaxuhuilang1999@outlook.com, sxxdyx0619@163.com, 241020071@fzu.edu.cn,cgykeda@mail.ustc.edu.cn, chenxing@fzu.edu.cnAbstractMulti-view clustering (MVC) seeks to uncover the intrinsicgroup structures embedded in multi-view data, which has at-tracted considerable attention in recent years.Existing ap-proaches predominantly concentrate on incorporating suit-able model priors to capture consistency across views.How-ever, these explicit constraints often fail to hold in scenar-ios involving significant modal differences between views orthe presence of noise, thereby limiting the efficacy of thesemethods in more complex contexts.To address these issues,this paper introduces BONE, a lightweight and interpretableMVC framework that Bridges Optimization and Neural net-works for Efficient MVC.By leveraging learnable param-eters to extract high-level features from low-level featuresderived through classical optimization, BONE integrates theconsistency information across views wit

---

; and Li, Y.2025.Robust multi-view subspace clustering via neighborembedding on manifold and low-rank representation learn-ing.Expert Systems with Applications, 267: 125831.Li, C.; Zhang, B.; Hong, D.; Yao, J.; Jia, X.; Plaza, A.; andChanussot, J.2024a.Interpretable networks for hyperspec-tral anomaly detection: A deep unfolding solution.IEEETransactions on Geoscience and Remote Sensing.Li, L.; Pan, Y.; Liu, J.; Liu, Y.; Liu, X.; Li, K.; Tsang, I.W.;and Li, K.2024b.BGAE: Auto-encoding multi-view bipar-tite graph clustering.IEEE Transactions on Knowledge andData Engineering, 36(8): 3682–3696.Li, X.; Zhang, H.; Wang, R.; and Nie, F.2020.Multiviewclustering: A scalable and parameter-free bipartite graph fu-sion method.IEEE Transactions on Pattern Analysis andMachine Intelligence, 44(1): 330–344.Liang, J.; Dong, X.; Wang, P.; Xu, J.; Wu, D.; and Nie, F.2025.Multi-view graph clustering via dual view-cluster-order interactivity mining.IEEE Transactions on Circuitsand Systems for Video Technology.Lin, R.; Li, J.; Du, S.; Wang, S.; and Zhang, L.2025.OIMGC-Net: optimization-inspired interpretablemulti-view graph clustering network.In Proceedings of the33rd ACM International Conference on Mu

## Reference Excerpt

[image-20260408115740220](attachment/image-20260408115740220.png)## RAG系统流程文档解析 (Parsing) -> 分块 (Chunking) -> 向量化 (Embedding) -> 存入向量数据库 (Vector DB) -> 用户提问查询 -> 检索 (Retrieval) -> 结合 Prompt 送入 LLM 生成答案。## 向量检索算法![image-20260408162730013](attachment/image-20260408162730013.png)## 父子块分块策略，子块对应的父块合父块对应的子块的关系要如何记录在工程落地中，父子块（Parent-Child Chunking）的映射关系本质上是一个**关系型数据设计**。

---

png)## 父子块分块策略，子块对应的父块合父块对应的子块的关系要如何记录在工程落地中，父子块（Parent-Child Chunking）的映射关系本质上是一个**关系型数据设计**。由于大模型 RAG 系统的特殊性，主流的实现方案是通过 **唯一标识符（ID）+ 元数据（Metadata）** 来建立绑定，并通常采用**双层存储架构（Two-Tier Storage）**。### 1.核心架构：双层存储分离为了兼顾“检索精度”和“存储效率”，我们通常不会把冗长的父块文本和子块的向量挤在同一个数据库的同一张表里。

---

核心架构：双层存储分离为了兼顾“检索精度”和“存储效率”，我们通常不会把冗长的父块文本和子块的向量挤在同一个数据库的同一张表里。- **底层（检索层）：向量数据库（Vector DB）**。例如 Milvus, Qdrant, Chroma 等。这里**只存子块**的 Embedding 向量、子块文本片段，以及至关重要的 Metadata（其中包含指向父块的 ID）。- **顶层（内容层）：键值/文档数据库（KV/Document Store）**。例如 Redis, MongoDB，或者在轻量级本地 Agent 项目中直接用 SQLite 或本地 JSON 文件。这里**只存父块**的完整文本，以 `parent_id` 作为主键（Key）。### 2.

---

### 2.数据结构设计（Schema）在你的 Python 后端处理逻辑中，数据切分和入库时需要构建类似如下的数据字典结构：**写入向量数据库的子块数据（Child Chunk）：**JSON```{"child_id": "child_001_a","embedding": [0.12, -0.45, 0.89, ...],"content": "该聚类算法在处理高维噪声数据时表现出极强的鲁棒性。","metadata": {"parent_id": "doc_001_paragraph_3",  // 核心：指向父块的外键"source_file": "research_paper.pdf","chunk_index": 1}}```**写入 KV/文档数据库的父块数据（Parent Chunk）：**JSON```{"parent_id": "doc_001_paragraph_3",    // 核心：主键"content": "在多视图学习框架中，数据往往伴随大量噪声。

---

pdf","chunk_index": 1}}```**写入 KV/文档数据库的父块数据（Parent Chunk）：**JSON```{"parent_id": "doc_001_paragraph_3",    // 核心：主键"content": "在多视图学习框架中，数据往往伴随大量噪声。该聚类算法在处理高维噪声数据时表现出极强的鲁棒性。实验证明，通过引入隐式正则化模块，能够有效剥离异常视图的干扰...","child_ids": ["child_001_a", "child_001_b", "child_001_c"], // 可选：父到子的反向映射"metadata": {"author": "Huilang","publish_date": "2026-03"}}```### 3.

---

","child_ids": ["child_001_a", "child_001_b", "child_001_c"], // 可选：父到子的反向映射"metadata": {"author": "Huilang","publish_date": "2026-03"}}```### 3.工程化检索的完整工作流 (Workflow)当用户发起一个提问时，系统是如何利用这套映射关系的呢？1.

## Source IDs

a0543971-3a7b-477b-82a9-c79654f02d31, 01d42082-2719-4e87-b10f-c84e4a2a8b8c, 414b066a-d1bf-4ce7-becd-7af6bc6ec9e6, 376325aa-8e06-43e0-a449-18d23e30283d, de37ef77-f0e4-4293-b949-cdc9e2460730, 14558b92-2a3a-4db4-9f3b-d630e10b89d9, a0060f6c-e41e-4bd2-8fdb-e8f1f14b7e9d, d4adec8f-0b69-433d-911c-62bb90d88123, baef7e91-9917-4332-b1c5-eefb253c9eac, 7155e454-6ea9-4950-87b2-c51c575f704d

## Metadata

{
  "question_type": "",
  "paper_title": "面试常见问题",
  "ttfb_ms": 1528,
  "total_latency_ms": 24987,
  "tool_calls": 3,
  "token_count": 1,
  "status": "done",
  "missing_context_count": 0
}