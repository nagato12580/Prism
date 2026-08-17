# Ragas Bad Case: q002

**Question:** 在Skill管理中，两阶段调用的第一阶段应检索多少个最相关的Skill

**Tags:** off_topic, missing_context, below_threshold:faithfulness, below_threshold:response_relevancy, below_threshold:context_recall

## Scores

{
  "faithfulness": 0.7142857142857143,
  "response_relevancy": 0.0,
  "context_precision": 0.8666666666377778,
  "context_recall": 0.0
}

## Answer

根据当前提供的工具返回结果，其中没有任何关于“Skill管理”、“两阶段调用”或“检索多少个最相关Skill”的内容。所有证据均围绕多视图聚类（Multi-view Clustering）方法、算法、实验数据等展开，与用户问题不相关。因此，基于现有证据无法回答该问题，也不能推断出任何有关Skill检索数量的信息。

## Retrieved Contexts

0.1830.1270.217TLRLF40.7550.7130.7940.9920.9770.9920.7370.8220.7570.2140.2160.263Ours0.9060.8310.9060.9820.9520.9820.7840.8560.7990.3450.3040.366Table 1: Clustering performance of different traditional methods across various datasets, where N/A indicates program errorsor timeouts.It can be observed that our method generally achieves better performance compared to existing methods.priors or inadequately exploit inter-view relationships, thuslimiting applicability to complex MVC scenarios.Alter-natively, to avoid reliance on explicit constraints or post-processing feature fusion, we employ a contrastive strategyto extract discriminative consistency information.To achieve this, we adopt a view-shared label projectionhead fl({Zv}Vv=1; Wl) to derive the clustering assignmentmatrix Pv ∈Rk×n from {Zv}Vv=1:Pv = fl(Zv; Wl).(9)Subsequently, contrastive learning is employed to enhanceconsistency of Pv ∈Rk×n across views.The primary goalof contrastive learning is to maximize the similarity betweenpositive pairs (features from the same sample across dif-ferent views) and minimize the similarity between negativepairs (features from different samples across all views), thusencouraging discriminat

---

7001NMI0.72350.82890.83660.8426Purity0.46550.74310.74050.7544Time Cost83+3009s 582+374s 424+7498s7+80sParameters20M25M16M156KTable 3: Clustering performance of various deep MVCmethods on the YouTubeFace50 dataset.Our methoddemonstrates comparable performance to existing methodswhile significantly reducing time expenditure.Experimental SetupFor our method, the number of layers L is set between 2and 5.The setting of r follows the strategy commonly usedin traditional methods, with values set as k× [1, 2, 3, 4, 5].The batch size b is set to values in [128, 256, 512].We per-form grid search to determine the optimal values for thesethree parameters.All remaining parameters were fixed con-sistently across datasets: regularization coefficients α = 0.1and β = 0.1, contrastive loss temperature parameter τ = 1,clustering assignment regularization coefficient λr = 1,number of training epochs E = 100, and maximum itera-tions for the initialization matrix optimization set to 100.Tovalidate the proposed method, we compare it with classicaland deep MVC methods, including: LMVSC (Kang et al.2020), SFMC (Li et al.2020), FPMVS-CAG (Wang et al.2021b), FDAGF (Zhang et al.2023), AWMVC (Wan et al.2023), 

---

rithms (like K-means) to obtain the final assignments.How-ever, this decoupling of the learning process from the finalassignment can lead to performance degradation (Liu et al.2021).Moreover, K-means is computationally expensive onlarge-scale datasets and highly sensitive to initializations,which limits its applicability in complex scenarios.Furthermore, several works have explored the incorpo-ration of learnable parameters into the update processes ofclassical methods to enhance performance (Du et al.2025;Lin et al.2025; Wang et al.2021a).However, they still relyon explicit prior constraints to extract view-consistent repre-sentations and depend on extra post-processing steps, mak-ing them inadequate for handling complex MVC scenarios.Deep Learning-based MethodsDeep learning-based methods typically adopt a data-drivenapproach, training autoencoders to extract features from theoriginal multi-view data (Fang et al.2023).The pre-trainingphase is usually guided by reconstruction loss (Trosten et al.2023), defined as:Lpre =VXv=1nXi=1∥xvi −f vd (f ve (xvi ; Wve); Wvd)∥22,(2)where f ve and f vd represent the encoder and decoder forthe v-th view, respectively, and Wve and Wvd are learnabl

---

tions from low-level semantic representations obtained viaclassical optimization models, thereby efficiently integrat-ing cross-view consistency without relying on explicit pri-ors or post-processing feature fusion, and eliminating thenecessity for pre-training or post-processing clustering pro-cedures.Specifically, our method offers the following ad-vantages (as shown in Figure 1):• Compared to traditional methods, (a) it avoids explicitconsistency constraints or post-processing feature fusionby effectively leveraging learnable parameters to inte-grate consistency information, thereby enhancing clus-tering performance; (b) it directly obtains clustering as-signments in an end-to-end manner, eliminating depen-dence on post-processing clustering steps; (c) it requiresonly a small part of the data to train the network, cir-cumventing the computational overhead associated withcomplex matrix operations in large-scale scenarios.• Compared to deep learning methods, (a) it extracts high-level semantic representations from low-level representa-tions obtained via classical optimization, achieving com-parable or better performance with substantially fewerparameters (approximately 1%); (b) it

---

778 0.51018M0.895 0.932 0.90323M0.928 0.956 0.93214M0.784 0.856 0.799 397KCCV0.290 0.302 0.33027M0.278 0.275 0.32225M0.347 0.335 0.39624M0.345 0.304 0.366 863KTable 2: Performance of different deep MVC methods across various datasets.It can be observed that our method achievescomparable or even better performance to existing methods, while utilizing only 1% of their parameter complexity.Algorithm 1: The optimization process of BONE.Input: Multi-view dataset {Xv}Vv=1; Number of clusters k,layers L; Dimension of representation r; Model penaltycoefficients α and β; Contrastive loss temperature coef-ficient τ; Cluster assignment regularization coefficientλr; Batch size b; Number of training epochs E.1: Initialize {Av0}Vv=1 by solving (7).2: for e = 1 to E do3:for l = 1 to L do4:Solve for semantic features {Zv,l}Vv=1 using (4).5:Update the base matrix {Av,l}Vv=1 using (5).6:Extract high-level semantic features using (6).7:end for8:Solve for the assignments {Pv}Vv=1 using (9).9:Compute the loss using (10) and backpropagate.10: end for11: Obtain the final cluster assignments from (11).Output: Cluster assignments P.

---

6:Extract high-level semantic features using (6).7:end for8:Solve for the assignments {Pv}Vv=1 using (9).9:Compute the loss using (10) and backpropagate.10: end for11: Obtain the final cluster assignments from (11).Output: Cluster assignments P.Parameter ComplexityIn our proposed method, the parameters to be optimizedmainly consist of two components: the view-specific fea-ture extraction modules {{gv,le }Ll=1, Av0}Vv=1 and the labelprojection head fl.Specifically, the label projection headis a single fully connected layer structured as r →k.Consequently, the total number of parameters is r(V Lr +PVv=1 mv+k).Given that r is typically set as a small integer(commonly a few times the number of clusters k), the overallparameter complexity of BONE remains substantially lowercompared to existing deep MVC methods.ExperimentsThis section evaluates the effectiveness of the proposedmethod through clustering experiments conducted on sev-eral common datasets, including BDGP (Liu et al.2024b),HandWrite (Chen et al.2024), MNIST-USPS, COIL20, Cal-tech5V (Xu et al.2022), MSRC (Winn and Jojic 2005),ALOI (Zhang, Huang, and Wang 2023), CCV (Jiang et al.2011), YouTubeFace50 (Wan et al.2023).All experim

---

, contrastive loss and self-16068representation loss (Wang et al.2025b)) to capture the con-sistency between multi-view data.Based on the training strategy, deep MVC methods canbe divided into two categories: non-contrastive (Wang et al.2025a, 2024; Xu et al.2021) and contrastive methods (Xuet al.2022; Chen et al.2023; Cui et al.2024; Lu et al.2024;Wang et al.2025b).Due to the remarkable success of con-trastive learning in unsupervised learning (Hu et al.2024),contrastive deep MVC methods have gained more attentionin recent years and typically achieve better clustering results(Cui et al.2024).However, these methods heavily rely on theassumption that autoencoders can effectively extract seman-tic features, which requires a complex training process andresults in higher computational costs (Trosten et al.2023).The Proposed MethodThis section provides a detailed description of BONE(shown in Figure 2).Our goal is to develop a lightweight andinterpretable one-step MVC method that bridges the clas-sical models’ priors with the feature extraction capabilitiesof neural networks.The proposed method requires no pre-processing or post-processing clustering steps and thus isbetter adapted to ha

---

(8)We then use the resulting Avinit as initial values for the learn-able parameters Av0.Remark: The problem in (7) is intended to provide an ap-proximate initialization rather than an exact solution.It canefficiently be solved through random sampling and limitediterations, making it well-suited for large-scale scenarios.Consistency Feature Fusion ModuleAfter obtaining the view-specific representations {Zv}Vv=1,the key challenge is to effectively fuse them and obtain thefinal clustering assignments.Traditional methods typicallyemploy explicit consistency constraints or post-processingfeature fusion.However, these methods either impose strict16069MethodHandwriteBDGPMRSCCOIL20ACCNMIPurityACCNMIPurityACCNMIPurityACCNMIPurityLMVSC0.6710.6510.7080.5560.3040.5560.3520.3080.3750.6920.7920.706SFMC0.7570.8680.7820.3780.3520.3790.6000.6030.6380.7480.8930.788FPMVS-CAG0.8230.7920.8230.5560.3760.5900.8050.6880.8050.6020.7800.633FDAGF0.8230.7940.8230.5250.3680.5470.7390.6570.7490.7400.8370.760AWMVC0.8750.7930.8770.4780.2970.4780.6660.5560.6680.7720.8480.774RCAGL0.7940.8270.8400.5180.3450.5260.7760.6800.7760.

---

We first independently obtain high-level semantic information for each view using view-specific feature extraction modules.Then, we utilize a parameter-sharing label MLP to derive the clustering assignments foreach view.By employing contrastive training, we compel the network to capture consistency information across different views.Finally, the clustering assignments are achieved end-to-end.et al.2023; Su et al.2024).A broad category of traditionalmodels can be expressed as:minAv,ZvVXv=1fv(Xv, Av, Zv) + ϕv(Av) + ψv(Zv),s.t.Av ∈Xv, Zv ∈Yv,(1)where Xv ∈Rmv×n, and ϕ and ψ represent different regu-larization terms.The sets Xv and Yv denote the feasible re-gions for Av and Zv, respectively.For models based on dif-ferent prior assumptions, Av and Zv have varying interpre-tations.For instance, in anchor-based subspace MVC meth-ods, Av represents the anchor matrix, and Zv represents therepresentation matrix.In matrix factorization-based MVCmethods, Av represents the basis matrix, and Zv representsthe coefficient matrix.Traditional methods generally achieve consistency be-tween views in two ways.The first approach explicitly con-strains the representations or assignment matrices across dif

---

We introduce a flexible optimization-guided neural net-work framework for MVC, bridging classical optimiza-tion and deep learning methods, thus providing a novelperspective for designing efficient MVC methods.• Compelling Empirical Evidence.Experiments con-ducted on widely-used MVC datasets demonstrate thatour method achieves clustering performance comparableor superior to existing methods, while using only 1% ofthe parameters and accelerating convergence.Related WorkIn this section, we review the current research on MVCmethods.Consider a multi-view dataset denoted as {Xv ∈Rmv×n}Vv=1, comprising V views and n samples, where mvdenotes the feature dimensionality of the v-th view.Let kdenote the number of clusters, r the dimensionality of thelearned representation.The core challenge in MVC is to ef-fectively balance consistency and complementarity acrossviews.Current MVC approaches can be broadly categorizedinto traditional and deep MVC methods.Traditional MVC MethodsTraditional MVC methods typically solve the MVC prob-lem by designing models with prior assumptions.Thesemethods can be further divided into four main categories:subspace learning-based methods (Zhang et al.2024; Liuet al

---

2022b).Addition-ally, certain priors introduce computationally intensive ma-trix operations, such as singular value decomposition (SVD)arising from orthogonality constraints, restricting scalabil-ity and performance in large-scale settings.Moreover, mosttraditional methods depend on post-processing clustering al-gorithms (e.g., K-means or spectral clustering) to obtain fi-nal assignments, further hindering their efficacy in handlingcomplex scenarios (Chen et al.2024).Deep MVC methods have garnered considerable atten-tion due to their superior feature representation capabilities(Zhou et al.2024).Unlike traditional methods that explic-itly design models, these methods typically employ autoen-coders to implicitly capture features from multi-view datathrough training.They generally adopt a two-stage trainingstrategy: first, pre-training the autoencoder using reconstruc-tion loss, followed by training the network with consistencylosses to capture shared semantic information across views.While these methods often achieve superior performance,they require a substantial number of learnable parametersand multiple rounds of pre-training, resulting in significantcomputational costs (Long et a

---

; and He, L.2022.Multi-level feature learning for contrastive multi-viewclustering.In Proceedings of the IEEE/CVF Conference onComputer Vision and Pattern Recognition, 16051–16060.Yan, J.; Zhang, K.; Sun, Q.; Ge, C.; Wan, W.; Sun, J.; andZhang, H.2025.Spatial–spectral unfolding network withmutual guidance for multispectral and hyperspectral imagefusion.Pattern Recognition, 161: 111277.Yu, S.; Wang, S.; Dong, Z.; Tu, W.; Liu, S.; Lv, Z.; Li, P.;Wang, M.; and Zhu, E.2024.A non-parametric graph clus-tering framework for multi-view data.In Proceedings ofthe AAAI Conference on Artificial Intelligence, volume 38,16558–16567.Yu, Z.; Dong, Z.; Yu, C.; Yang, K.; Fan, Z.; and Chen, C.P.2025.A review on multi-view learning.Frontiers of Com-puter Science, 19(7): 197334.Zhang, C.; Jia, X.; Li, Z.; Chen, C.; and Li, H.2024.Learn-ing cluster-wise anchors for multi-view clustering.In Pro-ceedings of the AAAI Conference on Artificial Intelligence,volume 38, 16696–16704.Zhang, G.-Y.; Huang, D.; and Wang, C.-D.2023.Facilitatedlow-rank multi-view subspace clustering.Knowledge-BasedSystems, 260: 110141.Zhang, P.; Wang, S.; Li, L.

---

Guo, W.; Che, H.; Leung, M.-F.; Jin, L.; and Wen, S.2025.Robust mixed-order graph learning for incomplete multi-view clustering.Information Fusion, 115: 102776.Hu, H.; Wang, X.; Zhang, Y.; Chen, Q.; and Guan, Q.2024.A comprehensive survey on contrastive learning.Neurocom-puting, 610: 128645.Ji, J.; and Feng, S.2025.Anchors crash tensor: efficientand scalable tensorial multi-view subspace clustering.IEEETransactions on Pattern Analysis and Machine Intelligence.Jiang, Y.-G.; Ye, G.; Chang, S.-F.; Ellis, D.; and Loui,A.C.2011.Consumer video understanding: A benchmarkdatabase and an evaluation of human and machine perfor-mance.In Proceedings of the 1st ACM international confer-ence on multimedia retrieval, 1–8.Kang, Z.; Zhou, W.; Zhao, Z.; Shao, J.; Han, M.; and Xu, Z.2020.Large-scale multi-view subspace clustering in lineartime.In Proceedings of the AAAI Conference on ArtificialIntelligence, volume 34, 4412–4419.Kong, J.; Liu, J.; Shang, R.; Zhang, W.; Xu, S.; and Li, Y.2025.Robust multi-view subspace clustering via neighborembedding on manifold and low-rank representation learn-ing.Expert Systems with Applications, 267: 125831.Li, C.; Zhang, B.; Hong, D.; Yao, J.; Jia, X.

---

; and Zhu, E.2024b.Robust and consistent anchor graph learning for multi-viewclustering.IEEE Transactions on Knowledge and Data En-gineering, 36(8): 4207–4219.Liu, S.; Wang, S.; Zhang, P.; Xu, K.; Liu, X.; Zhang, C.; andGao, F.2022.Efficient one-pass multi-view subspace clus-tering with consensus anchors.In Proceedings of the AAAIConference on Artificial Intelligence, volume 36, 7576–7584.Liu, X.; Liu, L.; Liao, Q.; Wang, S.; Zhang, Y.; Tu, W.; Tang,C.; Liu, J.; and Zhu, E.2021.One pass late fusion multi-view clustering.In International Conference on MachineLearning, 6850–6859.PMLR.Long, Z.; Wang, Q.; Ren, Y.; Liu, Y.; and Zhu, C.2025.TL-RLF4MVC: tensor low-rank and low-frequency for scalablemulti-view clustering.IEEE Transactions on Pattern Anal-ysis and Machine Intelligence.Lu, Y.; Lin, Y.; Yang, M.; Peng, D.; Hu, P.; and Peng, X.2024.Decoupled contrastive multi-view clustering withhigh-order random walks.In Proceedings of the AAAI Con-ference on Artificial Intelligence, volume 38, 14193–14201.16073Su, P.; Liu, Y.; Li, S.; Huang, S.; and Lv, J.2024.Robustcontrastive multi-view kernel clustering.

---

; Huang, D.; and Wang, C.-D.2023.Facilitatedlow-rank multi-view subspace clustering.Knowledge-BasedSystems, 260: 110141.Zhang, P.; Wang, S.; Li, L.; Zhang, C.; Liu, X.; Zhu, E.;Liu, Z.; Zhou, L.; and Luo, L.2023.Let the data choose:Flexible and diverse anchor graph fusion for scalable multi-view clustering.In Proceedings of the AAAI Conference onArtificial Intelligence, volume 37, 11262–11269.Zhao, X.; Wang, S.; Liu, X.; and Liang, J.2024a.Multi-view clustering via dynamic unified bipartite graph learning.Pattern Recognition, 156: 110715.Zhao, Z.; Nie, F.; Wang, R.; Wang, Z.; and Li, X.2024b.An balanced, and scalable graph-based multiview clusteringmethod.IEEE Transactions on Knowledge and Data Engi-neering.Zhou, L.; Du, G.; Lue, K.; Wang, L.; and Du, J.2024.Asurvey and an empirical evaluation of multi-view clusteringapproaches.ACM Computing Surveys, 56(7): 1–38.16074

---

Fast parameter-free multi-view subspaceclustering with consensus anchor guidance.IEEE Transac-tions on Image Processing, 31: 556–568.Wang, Y.; Chang, D.; Fu, Z.; Wen, J.; and Zhao, Y.2022b.Graph contrastive partial multi-view clustering.IEEE Trans-actions on Multimedia, 25: 6551–6562.Winn, J.; and Jojic, N.2005.Locus: Learning object classeswith unsupervised segmentation.In Tenth IEEE Interna-tional Conference on Computer Vision (ICCV’05) Volume1, volume 1, 756–763.IEEE.Wu, F.; Zhang, T.; Li, L.; Huang, Y.; and Peng, Z.2024.RP-CANet: Deep unfolding RPCA based infrared small targetdetection.In Proceedings of the IEEE/CVF Winter Confer-ence on Applications of Computer Vision, 4809–4818.Xu, J.; Ren, Y.; Tang, H.; Pu, X.; Zhu, X.; Zeng, M.; andHe, L.2021.Multi-VAE: Learning disentangled view-common and view-peculiar visual representations for multi-view clustering.In Proceedings of the IEEE/CVF Interna-tional Conference on Computer Vision, 9234–9243.Xu, J.; Tang, H.; Ren, Y.; Peng, L.; Zhu, X.; and He, L.2022.Multi-level feature learning for contrastive multi-viewclustering.In Proceedings of the IEEE/CVF Conference onComputer Vision and Pattern Recognition, 16051–16060.Yan, J.; Zhang, 

## Reference Excerpt

- **长链路依赖推理**：部署 A 之前需要先拉起 B 的数据库迁移，这种时序逻辑在复杂拓扑下容易断裂。## Motion Graphic Agent：概念与架构**Motion Graphic Agent** 是专门生成动态图形（如 After Effects 脚本、Lottie 动画）的智能体。- **架构**：通常采用 **Planner + Coder + Renderer** 模式。1.**Planner**：将视觉描述拆解为时间轴动作（如：0s 缩放，1s 位移）。2.**Coder**：生成特定的脚本（JavaScript/Python），操作 AE 或通过 Canvas 绘图。3.**Renderer**：调用 Headless 浏览器或渲染引擎生成视频/GIF，并由 LLM 进行视觉反馈修正。## SKill是啥## Skill 太多占用上下文？

---

## SKill是啥## Skill 太多占用上下文？这是典型的 **"Tool Retrieval"** 问题，解决方案是：- **RAG 化 Skill 管理**：不要全塞 Prompt。将所有 Skill 的 Description 存入向量数据库。- **两阶段调用**：- **Phase 1**：根据 Query 检索最相关的 Top 3-5 个 Skill。- **Phase 2**：仅将这几个 Skill 的完整定义喂给 LLM。## Description 相似导致加载错误？**精细化 Schema 设计**：在 Description 中增加 **"Negative Examples"（反面示例）**，明确说明“本工具不适用于 XXX 场景”。**强类型约束**：通过参数的枚举值或 Pydantic 定义强制区分。

---

**强类型约束**：通过参数的枚举值或 Pydantic 定义强制区分。**Few-shot 演示**：在 Prompt 中针对容易混淆的两个 Skill 提供对比示例（Contrastive Examples）。## 上下文工程要注意的点**噪声过滤**：对话历史中无用的冗余信息（如打招呼、重复报错）必须修剪，否则会稀释注意力。**结构化布局**：使用 Markdown 标签明确区分 `Current Goal`、`Memory`、`Tool Outputs`，这比纯文本更能引导 LLM 推理。## 主流 Agent 设计与 Multi-Agent 架构## 主流设计- **Single Agent**：ReAct (Reason + Act), Plan-and-Execute。- **Multi-Agent**：多智能体协作。## Multi-Agent 实现方案1.

---

## Multi-Agent 实现方案1.**中心化 (Hub-and-Spoke)**：一个 Manager Agent 分配任务给多个 Worker（如 AutoGen）。2.**流水线型 (Sequential/Pipeline)**：A 做完给 B，B 做完给 C（如 LangGraph 的简单链）。3.**协作协议 (Peer-to-Peer)**：Agent 之间动态对话。## Multi-Agent 靠什么交流？**结构化消息 (Structured Messaging)**：通常是 JSON 或经过定义的通信协议（Message Pool）。**共享看板 (Blackboard/State)**：所有 Agent 读写同一个共享的状态对象（State Object），实时感知进度。## Agent项目开发的框架**LangChain**（生态丰富但较重）、**AutoGen**（多智能体对话优秀）或 **MetaGPT**。

---

## Agent项目开发的框架**LangChain**（生态丰富但较重）、**AutoGen**（多智能体对话优秀）或 **MetaGPT**。然后强调你为了更深入理解底层逻辑和工具调用机制，在实际项目中会选择或借鉴 **`hello-agents`** 这类更轻量级的框架。## 推理模式的差异化设计**ReAct (Reason + Act)：** 最主流的模式。工程实现是：Prompt 中定义严格的思考框架 `Thought -> Action -> Observation`。每执行完一步，将结果拼接回 Prompt 中再次请求 LLM，直到输出 `Finish`。

## Source IDs

a0543971-3a7b-477b-82a9-c79654f02d31, cad43543-4da4-4bec-9ebd-45232c2d695b, 889b878e-a9fb-432f-8e4b-9ff3f37e0b0a, 134a259f-72ea-4fbf-a7ed-05f8e4bf61db, e37cc6bf-9094-4cf1-a356-bf128cc3ec97, d4adec8f-0b69-433d-911c-62bb90d88123, 544e4b06-b82b-4389-8271-85be3efc8f11, 2b6e114f-0d56-41d0-87f6-eb12eba0c671, 01d42082-2719-4e87-b10f-c84e4a2a8b8c, 25317a0d-dd74-4805-b354-9a9485d3a17c, 3984925b-ad08-4b6d-bfaa-e7f69f4da2c7, 5105b96c-c51f-466a-ac1b-a8f857995b43, 9f34e164-e454-4fd2-9a72-8052206ad1b9, 1d96dd03-e95f-4f81-bd06-29a496423643, 9d4ff8a9-b978-4878-ae11-f7b93ba7a0dc, 3c310da0-dea1-4e04-bdbf-bdb4d15a7988

## Metadata

{
  "question_type": "",
  "paper_title": "面试常见问题",
  "ttfb_ms": 2541,
  "total_latency_ms": 16614,
  "tool_calls": 7,
  "token_count": 1,
  "status": "done",
  "missing_context_count": 0
}