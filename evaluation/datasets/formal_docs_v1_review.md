# formal_docs_v1 Review Checklist

Dataset: `evaluation/datasets/formal_docs_v1.json`
Total queries: 60

Use this file to manually mark weak questions, wrong sources, or entries to remove before benchmark runs.

## q001 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `be865ef7-0a2d-4770-b2f7-5c139db1b73f`
- Relevant child chunks: `6`
- Question: 在RAG系统中，父子块之间的映射关系通常通过什么方式在工程落地中建立

Parent preview: [image-20260408115740220](attachment/image-20260408115740220.png)## RAG系统流程文档解析 (Parsing) -> 分块 (Chunking) -> 向量化 (Embedding) -> 存入向量数据库 (Vector DB) -> 用户提问查询 -> 检索 (Retrieval) -> 结合 Prompt 送入 LLM 生成答案。## 向量检索算法![image-20260408162730013](attachment/image-20260408162730013.png)## 父子块分块策略，子块对应的父块合父块对应的子块的关系要如何记录在工程落地中，父子块（Parent-Child Chunking）的映射关系本质上是一个**关系型数据设计**。由于大模型 RAG 系统的特殊性，主流的实现方案是通过 **唯一标识符（ID）+ 元数据（Metadata）** 来建立绑定，并通常采用**双层存储架构（Two-Tier Storage）**。### 1.核心架构：双层存储分离为了兼顾“检索精度”和“存储效率”，我

## q002 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `95ce1fc4-998a-48ea-ad62-472875dba914`
- Relevant child chunks: `5`
- Question: 在Skill管理中，两阶段调用的第一阶段应检索多少个最相关的Skill

Parent preview: - **长链路依赖推理**：部署 A 之前需要先拉起 B 的数据库迁移，这种时序逻辑在复杂拓扑下容易断裂。## Motion Graphic Agent：概念与架构**Motion Graphic Agent** 是专门生成动态图形（如 After Effects 脚本、Lottie 动画）的智能体。- **架构**：通常采用 **Planner + Coder + Renderer** 模式。1.**Planner**：将视觉描述拆解为时间轴动作（如：0s 缩放，1s 位移）。2.**Coder**：生成特定的脚本（JavaScript/Python），操作 AE 或通过 Canvas 绘图。3.**Renderer**：调用 Headless 浏览器或渲染引擎生成视频/GIF，并由 LLM 进行视觉反馈修正。## SKill是啥## Skill 太多占用上下文？这是典型的 **"Tool Retrieval"** 问题，解决方案是：- **RAG 化 Skill 管理**：不要全塞 Prompt。将所有 Skill 的 Description 存入向量数据库。- **两阶段调用**

## q003 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `en`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `7c362dea-9bfb-42b6-8858-39f8916eb6e7`
- Relevant child chunks: `5`
- Question: What is the LLM-as-a-Judge evaluation method and how does it work

Parent preview: 在实际的 RAG 工业落地中，我们通常会**组合使用**这些指标：1.用**关键词重合度**保底，确保硬核事实（Entity/Fact）不出错。2.用**文本相似度**作为主导，评估模型是否真正理解并回答了问题。3.用 **ROUGE-L** 辅助观察生成的句子结构是否连贯、完整。#### 维度三：Answer Relevance (回答相关性) —— 考察“生成层”的有用性- **核心问题**：大模型的最终回答，真的解答了用户最初的 Query 吗？- **为什么重要**：有时候检索到了相关的文档，模型也忠实地复述了文档，但就是**答非所问**。比如用户问“大理天气如何？”，模型回答“大理是一个美丽的城市”（因为文档里只有这句话）。这时候忠实度很高，但回答相关性极低。------### 2.怎么打分？(Evaluation Methods)知道了要评什么，接下来是怎么评。总不能让人工一条条去读。1.**LLM-as-a-Judge (让大模型当裁判)**：- 这是目前**最绝对的主流**。- 做法是：写一套极其严格的 Prompt，把用户的 Query、系统检索到的 Context 

## q004 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `en`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `3dcb4c24-ab41-44f3-b6a3-b14654881965`
- Relevant child chunks: `5`
- Question: What is the core of Gemini CLI design and what are its optimization points

Parent preview: | ✅ **原生支持**。MCP Server 可以将本地文件系统、数据库、GitHub 仓库等直接映射为大模型可以读取的 URI。模型能像访问本地磁盘一样感知这些数据。|| **Prompts (提示词)** | ❌ 通常硬编码在 Agent 的系统设定里。| ✅ **原生支持**。MCP 允许服务器向客户端提供可复用的、动态的 Prompt 模板。|# 其他题目## Gemini CLI 设计核心与优化**核心**：**流式响应（Streaming）\**与\**多模态文件处理**的极速反馈。**优化点**：1.**缓存层**：对重复的系统指令使用 **Context Caching** 降低成本。2.**终端交互**：增加交互式命令纠错（当命令报错时，自动询问是否让 Gemini 修复）。## 如何设计一个高效的 Agent 上下文维护方案？核心在于 **“分层”** 与 **“动态压缩”**。- **短期记忆（Sliding Window）**：只保留最近 $N$ 轮对话。- **长期记忆（Vector Search）**：将历史对话向量化存入数据库（如 FAISS/Milvu

## q005 - 大模型微调指南

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `en`
- Item ID: `aa67312a-53dd-447b-9084-3e6e08f215e7`
- Parent chunk ID: `057b630a-d05c-4118-86d1-e04b87552669`
- Relevant child chunks: `1`
- Question: What is the recommended workflow for beginners when fine-tuning a model, according to the document

Parent preview: Loss 只能辅助判断训练状态，不能单独代表业务效果。推理结果必须用真实样本验收。```对于新手，最推荐的路线是：```text先用小模型 + 小数据 + LoRA 跑通全流程；再清洗数据、补充样本、分析错例；最后才系统调参和扩大模型规模。```

## q006 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `bc6f2774-9117-4eb4-ab32-ec01da469f9a`
- Relevant child chunks: `6`
- Question: LangSmith链路可观测的核心价值有哪些？请结合文档举例说明如何通过它定位RAG系统中的问题。

Parent preview: 抛弃暴力的字数切分，改用按 Markdown 结构或代码逻辑切分；评估现有的 Embedding 模型是否不适合你的垂直领域（比如用通用模型去嵌数学公式和代码），考虑微调 Embedding 或更换模型。## langsmith链路可观测，具体是怎么做的> **基础接入：** 主要通过配置环境变量来自动拦截并追踪底层的 LLM 和工具调用；对于自己写的非标准函数（如业务清洗、精排逻辑），则加上 `@traceable` 装饰器，确保整条链路监控不断层。>> **核心价值（排障与归因）：**>> - **破解 RAG 黑盒：** 能够可视化查看每一个节点的出入参。如果最终答案报错，我能立刻在 UI 上看清是 FAISS/BM25 没召回目标文档、BGE 精排打分有误，还是大模型胡编乱造，精准定位问题。> - **监控 Agent 流转：** 配合 LangGraph 的图结构，清晰查看意图识别、检索、外部工具以及 Reflection 打分的流转路径是否正确。>>>> **性能优化（闭环）：** 这一点最重要。正是通过观察 LangSmith 的 Latency（延迟）面板，我确认了系统

## q007 - 好未来

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `a436ecb1-8553-4ae0-b8e3-0ed972cdf87b`
- Parent chunk ID: `38f5e47d-055c-4c20-844d-b85d948841e0`
- Relevant child chunks: `6`
- Question: 在GRPO训练中，思考长度与答案正确性之间存在怎样的相关性？请结合短期与长期奖励、探索与利用以及任务复杂度等方面进行解释。

Parent preview: 元强化学习学习如何快速适应新任务的学习方法。如MAML（Model-Agnostic Meta-Learning）。14.强化学习的应用游戏AI、机器人控制、自动驾驶、推荐系统等。每个点都可以进一步展开为更详细的概念讲解和实际应用案例。根据你的具体需求，可以选择深入研究其中的一部分或全部内容。希望这能帮助你更好地准备面试或深化对强化学习的理解！20.问grpo训练过程中思考长度和答案正确性的相关性在讨论 GRPO（Generalized Regularized Policy Optimization） 或任何强化学习（RL）算法时，思考长度（即智能体在做出决策前考虑的步骤数或信息量）与答案正确性之间的关系是一个复杂但有趣的话题。这种关系并不是直接的线性关系，而是受到多种因素的影响。思考长度的概念在强化学习中，“思考长度”可以理解为智能体在采取行动之前评估未来可能状态和奖励的能力。这通常通过以下几个方面体现：规划步数：智能体能够预测其行为对未来几步的影响。记忆机制：智能体是否能够记住过去的状态和动作，并利用这些信息来指导当前决策。模型使用：如果智能体使用环境模型（如世界模型或动态模型），

## q008 - C++编码规范V01.00

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `en`
- Item ID: `5a2a52d3-86e6-4ebb-8c68-d3e238fc4a1c`
- Parent chunk ID: `4047afa3-7714-4f2b-97bc-9e85c4ca3698`
- Relevant child chunks: `5`
- Question: What is the effective date of the C/C++ coding standard document

Parent preview: C/C++编码规范任子行内部资料不得外传1 / 17文控表文件名称C/C++编码规范版本号V01.00文件编码DM-PR-R01生效日期2023-05-01拟制人曾德新、林亚坤流程责任人廖茜文件密级内部公开适用范围任子行、科技开发、任网游所属流程架构L1研发管理L2研发项目管理C/C++编码规范任子行内部资料不得外传2 / 17目录1.目的.........................................................................................................................................32.概述.........................................................................................................................................33.主要内容...........................................

## q009 - 好未来

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `a436ecb1-8553-4ae0-b8e3-0ed972cdf87b`
- Parent chunk ID: `88bcf776-0afa-4dcc-8e89-49548a021db1`
- Relevant child chunks: `5`
- Question: PPO算法中用于限制策略更新幅度的clip范围通常设为多少

Parent preview: 每层Transformer块内部：虽然大多数情况下位置编码只在输入端添加一次，但在某些设计中，为了增强模型对长距离依赖关系的建模能力，可能会选择在每个Transformer块内部重新引入位置编码。不过，这种方法并不常见，因为它增加了计算复杂度，并且可能引发训练不稳定的问题。特殊情况下的其他位置：根据特定应用的需求或者模型架构的设计，位置编码也可能在其他位置被使用。例如，在一些变种模型中，可能会探索将位置编码与其他类型的特征结合，或是采用更复杂的机制来动态生成位置编码等。总的来说，对于大多数Decoder-only模型而言，位置编码主要是在输入嵌入之后一次性加入的。这样做不仅简单有效，而且能够保证在整个网络中传递准确的位置信息。值得注意的是，随着研究的进步，也出现了各种改进的位置编码方法，比如相对位置编码、可学习位置编码等，旨在进一步提升模型性能和灵活性。这些改进方法可能会改变位置编码的具体加载位置或方式，但核心思想依然围绕着如何高效地将位置信息整合进模型之中。好未来面经（熊）59.这里ppo和GRPO是用过，对原理了解吗(了解也跑过)，问GRPO和PPO细节，聊了好一会儿你提到你了解并

## q010 - 大模型微调指南

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `aa67312a-53dd-447b-9084-3e6e08f215e7`
- Parent chunk ID: `f49041e1-9f2a-4c7e-b4ff-f9acb0b1fb39`
- Relevant child chunks: `3`
- Question: 在文本分类任务的最小可行方案中，推荐的数据量是多少

Parent preview: - 清洗低质量回答- 增加高质量示例- 上线 prompt 与训练 prompt 保持一致```------# 第九阶段：推荐实验记录表每次训练都要记录实验配置，否则无法复现。| 实验编号 | 模型     | 数据版本 | 学习率 | epoch | batch | max_length | LoRA r | 验证 F1 | 备注           || -------- | -------- | -------- | ------ | ----- | ----- | ---------- | ------ | ------- | -------------- || exp_001  | qwen-xxx | v1       | 5e-5   | 3     | 4     | 256        | 8      | 0.81    | 初版           || exp_002  | qwen-xxx | v2       | 3e-5   | 4     | 4     | 256        | 8      | 0.84    | 清洗标签后提升 |必须记录：`

## q011 - 好未来

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `a436ecb1-8553-4ae0-b8e3-0ed972cdf87b`
- Parent chunk ID: `996a3b64-ea59-4d13-bc56-cce52e4d0e96`
- Relevant child chunks: `6`
- Question: 策略迭代和值迭代的主要区别是什么

Parent preview: 包括策略迭代和值迭代等方法，用于解决已知模型的MDP问题。策略迭代：交替进行策略评估和策略改进。值迭代：直接更新价值函数直到收敛，然后从中提取最优策略。5.蒙特卡洛方法不需要环境模型，通过采样轨迹来估计价值函数。主要技术包括首次访问MC和每次访问MC。6.时序差分学习（TD Learning）好未来面经（熊）18状态价值函数的贝尔曼方程:这个公式的直观含义是：状态 ss 的价值，等于在该状态下，按照策略 ππ 选择动作 aa 的概率，乘以（执行该动作获得的即时奖励 RR，加上未来状态 s′s′ 的价值乘以折扣因子 γγ）的总和。动作价值函数的贝尔曼方程:这个公式的含义是：在状态 ss 执行动作 aa 的价值，等于执行该动作的即时奖励 RR，加上未来可能进入的状态 s′s′ 下，按照策略 ππ 选择后续动作所能获得的期望价值。TD 学习通过采样得到真实的下一个状态，然后用当前对该状态价值的估计来更新当前状态的价值结合了动态规划和蒙特卡洛的优点，如TD(0)，SARSA，Q-learning等。TD(0)：基于当前预测与下一个状态的预测之间的差异更新价值函数。SARSA：一种在线策略TD学

## q012 - C++编码规范V01.00

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `5a2a52d3-86e6-4ebb-8c68-d3e238fc4a1c`
- Parent chunk ID: `fb81fe95-3977-486e-bfad-1019ca2d3870`
- Relevant child chunks: `5`
- Question: 根据C++编码规范，数据库表存储引擎必须使用什么

Parent preview: ............................143.2.8.内存管理.........................................................................................................163.2.9.代码编辑、编译、审查.................................................................................174.支持文件...............................................................................................................................175.文件履历.................................................................................................................

## q013 - python_coding_standards

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `1e8927d1-f559-4747-bac4-a8417c813eea`
- Parent chunk ID: `09081604-7fd4-4ffb-82fb-d43d6827103a`
- Relevant child chunks: `5`
- Question: 在Python编码规范中，当函数参数过多时，文档推荐使用哪种方式来封装参数

Parent preview: def get_active_users(limit: int = 100) -> list[User]:...```### 5.1 使用内置泛型Python 3.9+ 推荐使用内置泛型：```python# 推荐names: list[str] = []metadata: dict[str, str] = {}```### 5.2 避免滥用 `Any````python# 不推荐from typing import Anydef process(data: Any) -> Any:...# 推荐@dataclassclass OrderPayload:product_id: intquantity: intdef process_order(data: OrderPayload) -> Order:...```## 6.函数设计### 6.1 函数应职责单一一个函数只做一件清晰的事情。```python# 不推荐def create_user_and_send_email_and_write_log(data: dict) -> None:...# 推荐def create_user

## q014 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `3d3124c8-002c-47b9-a6d6-539176ff6c5c`
- Relevant child chunks: `5`
- Question: 处理Tavily返回的超长内容时，Map-Reduce策略具体包含哪三个核心阶段

Parent preview: ## 如果 Tavily 返回了 3 个非常长的网页内容，加起来超过了你的 LLM 上下文限制（Context Window），你的 `_llm_synthesize` 会崩溃或截断关键信息。你怎么处理？”我会引入 **Map-Reduce 总结策略**。先对每个搜索结果进行独立的 `Summary`（Map 阶段），提取与 query 相关的核心片段，然后再汇总给 LLM 生成最终答案（Reduce 阶段）。或者使用支持长文本的模型，但在调用前会通过 `tiktoken` 库预估长度并进行智能切片。”## Map-Reduce## 1.Map-Reduce 的三个核心阶段#### **第一阶段：Split (切分)**将长文档或多个搜索结果拆分成若干个较小的“分片”（Chunks）。每个分片的大小要确保配合 Prompt 后依然远小于 LLM 的 Token 限制。#### **第二阶段：Map (各自总结)****并行**地对每个分片进行处理。- **动作**：LLM 接收分片 A，提取出与用户问题相关的要点；同时处理分片 B，提取要点。- **结果**：你得到了 N 个简短的“中

## q015 - 大模型微调指南

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `aa67312a-53dd-447b-9084-3e6e08f215e7`
- Parent chunk ID: `7a8a2f37-3a88-412c-816a-98789410f26f`
- Relevant child chunks: `5`
- Question: 在大模型微调中，评估指标应当如何正确组合使用

Parent preview: ## 2.训练集和验证集必须严格分开错误：```text先 tokenize 再随意切分，导致重复样本泄漏。```正确：```text先去重、清洗、切分，再分别 tokenize。```------## 3.评估指标需组合使用错误：```text只看 Accuracy。```正确：```text同时看 Accuracy、Precision、Recall、F1、混淆矩阵。```------## 4.不要用测试集调参测试集只能在最后使用。错误：```text每次调完参数都在 test 上看效果。```后果：```text测试集被间接污染，最终指标不可信。```------## 5.不要盲目增加 epochepoch 越多不一定越好。常见现象：```text训练 loss 继续下降，验证 F1 开始下降。```这通常说明过拟合。------## 6.不要忽略线上数据分布训练数据如果和线上输入差异太大，模型上线会掉点。例如：```text训练数据是人工整理后的标准句子；线上数据是错别字、口语、emoji、长句、上下文缺失。```解决方式：```text训练集中加入真实线上样本。```-----

## q016 - 好未来

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `a436ecb1-8553-4ae0-b8e3-0ed972cdf87b`
- Parent chunk ID: `4fff061b-ac08-4278-8b44-36546644cd98`
- Relevant child chunks: `5`
- Question: 在Transformer模型的解码优化中，束搜索（Beam Search）是如何工作的

Parent preview: 个较短的片段，并设计适当的拼接机制来保持上下文一致性。特殊标记：使用特殊的标记（如 [SEP]  或 [CLS] ）来区分不同的推理步骤或子任务。动态填充：根据批次内最长序列进行填充，避免固定最大长度带来的内存浪费。2.解码优化在 Transformer 模型中进行解码优化，特别是针对长链推理任务，可以从以下几个方面入手：a.改进解码策略i.贪婪搜索 vs.束搜索贪婪搜索：每一步选择概率最高的单词作为下一个输出，简单但容易陷入局部最优。束搜索（Beam Search）：维护多个候选路径，在每一步扩展这些路径并保留前 \(k\) 个最有可能的结果，从而增加找到全局最优解的概率。ii.Top-k 和 Nucleus SamplingTop-k Sampling：每次从概率最大的前 \(k\) 个词中随机选择一个作为下一个输出。Nucleus Sampling：只考虑累积概率达到某个阈值的部分词汇进行采样，平衡多样性和质量。iii.温度调节使用温度参数调整 softmax 输出的概率分布，较高的温度使分布更平滑，鼓励探索；较低的温度则使其更尖锐，倾向于选择高概率词。b.模型结构调整i.引入稀

## q017 - 好未来

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `a436ecb1-8553-4ae0-b8e3-0ed972cdf87b`
- Parent chunk ID: `2242b6bd-eb20-4756-b5c1-1d592a221bd7`
- Relevant child chunks: `6`
- Question: 在好未来的面经中，为什么选择用高斯分布初始化A，而不是让A为0

Parent preview: 所以我们让 B 从 0 开始慢慢学，而 A 提供一个“稳定的输入信号”。如果反过来，A为0 ，B的梯度取决于A，A的梯度取决于B，一开始更新B的梯度的时候不会进行更新，会导致梯度卡住，不会进行更新。为什么A选高斯分布目的是为了把输入信号有效地“编码”到低维空间中，让B有更有效的信号去学习。使用 高斯分布初始化 A，可以让输入特征经过 A 后保留一定的多样性，便于后续的 B 学习有用的信息。好未来面经（熊）2理论上来说AB只要点积为0 都可以符合要求，AB两个都不为0点积为0也是可以的，就是要在不断梯度更新的过程中去贴近最终的值，实际过程中B为0,A为高斯，会更便捷初始化，也可以让权重更新更快。5.大模型用Layernorm为什么不用batchnorm1.序列长度变化LayerNorm是在特征维度上进行归一化的，因此它不依赖于批量大小或序列长度。相反，BatchNorm要求固定的批量大小和输入尺寸，这使得它不太适合处理变长序列的数据（会将输入序列pad到统一长度，用mask忽略padding的影响，通常是pad到最大长度）。2.模型稳定性与性能梯度传播：在训练深度网络时，LayerNor

## q018 - 大模型微调指南

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `aa67312a-53dd-447b-9084-3e6e08f215e7`
- Parent chunk ID: `1c47194f-9296-49e9-baaa-97a158a882cc`
- Relevant child chunks: `6`
- Question: lora_dropout的默认值是多少

Parent preview: lora_dropout=0.05,target_modules=["q_proj", "v_proj"],bias="none",task_type="CAUSAL_LM")```分类任务可以使用：```pythontask_type="SEQ_CLS"```------## 3.训练参数建议| 参数                        | 新手起点       | 说明                  || --------------------------- | -------------- | --------------------- || learning_rate               | 5e-5           | LoRA 分类任务常用起点 || epochs                      | 3–5            | 数据少时不要太多      || batch_size                  | 按显存设置     | 先从 1、2、4、8 试    || gradient_accumulation_ste

## q019 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `c2ca6f6a-983b-49a0-bc7d-bb493e3a93e5`
- Relevant child chunks: `5`
- Question: BLEU指标在评估大模型生成的答案时，其核心逻辑是什么

Parent preview: **核心逻辑**：计算大模型“生成的答案”中，有多少个词组（N-gram）在“标准答案”中也出现了。它极其惩罚“胡言乱语”——如果模型生成了一大段废话，哪怕里面包含了正确答案，BLEU 分数也会被大幅拉低。**例子**：- 标准答案：“大理的烤肉很好吃。”- 生成答案 1：“大理的烤肉很好吃。” (BLEU 极高)- 生成答案 2：“大理的烤肉很好吃，而且昨天下雨了，我还买了一顶帽子。” (虽然包含了正确信息，但因为废话太多，精准度下降，BLEU 分数会很低)**在 RAG 中的局限**：BLEU 是典型的“字面匹配”指标。由于现代大模型经常使用同义词或改变句式，BLEU 往往会给出偏低的分数。工业界现在更倾向于使用我们之前提到的基于语义向量的相似度（如 BERTScore）来替代纯字面的 BLEU。##### 2.文本相似度 (Semantic Similarity / 基于向量的语义重合)这是在 RAG 评估中最具现代感、也最抗“大模型改写”干扰的指标。通常使用 **BERTScore** 或 **Embedding 余弦相似度** 来计算。- **核心逻辑**：抛弃字面上的比对，

## q020 - C++编码规范V01.00

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `en`
- Item ID: `5a2a52d3-86e6-4ebb-8c68-d3e238fc4a1c`
- Parent chunk ID: `d6bf5e42-1e90-495e-8fc4-016a3e7a9bc0`
- Relevant child chunks: `5`
- Question: What is the rule regarding the use of spaces after keywords like if, for, and while

Parent preview: 2.程序的排版3.2.2.1.空行1)在每个类声明之后、每个函数定义结束之后都要加空行2)在一个函数体内，逻揖上密切相关的语句之间不加空行，其它地方应加空行分隔3.2.2.2.代码行1)一行代码只做一件事情，如只定义一个变量，或只写一条语句。这样的代码容易阅读，C/C++编码规范任子行内部资料不得外传8 / 17并且方便于写注释2)if、for、while、do 等语句自占一行，执行语句不得紧跟其后。不论执行语句有多少都要加{}。这样可以防止书写失误3)尽可能在定义变量的同时初始化该变量（就近原则）。如果变量的引用处和其定义处相隔比较远，变量的初始化很容易被忘记。如果引用了未被初始化的变量，可能会导致程序错误3.2.2.3.代码行内的空格1)关键字之后要留空格。像if、for、while 等关键字之后应留一个空格再跟左括号‘（’，以突出关键字。函数名之后不要留空格，紧跟左括号‘（’，以与关键字区别2)‘（’向后紧跟，‘）’、‘，’、‘;’向前紧跟，紧跟处不留空格。‘，’之后要留空格，如Function(x, y, z)。如果‘;’不是一行的结束符号，其后要留空格，如for(initia

## q021 - 好未来

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `a436ecb1-8553-4ae0-b8e3-0ed972cdf87b`
- Parent chunk ID: `c8b79ea1-2c47-4a94-88d6-5f1ae2d09299`
- Relevant child chunks: `5`
- Question: PreNorm和PostNorm在定义和优缺点上有什么区别

Parent preview: DeepNorm是对LayerNorm的一种改进，旨在支持非常深的网络结构。通过调整公式中的参数，DeepNorm能够有效地训练具有上千层的模型。7.prenorm和postnorm区别Pre-Normalization (PreNorm)定义: 在残差连接前应用Layer Normalization。具体来说，在进行任何加权求和操作之前，先对输入数据进行规范化处理。优点:梯度更稳定: 通过预先归一化输入，使得每一层的输入分布更加一致，有助于梯度下降过程中的稳定性。加速收敛: 实验表明，PreNorm有时可以帮助模型更快地收敛。简化调参: 相比之下，使用PreNorm可能需要较少的调整超参数的工作量。缺点:表现可能不如PostNorm: 在某些情况下，特别是当任务特别复杂时，PreNorm的表现可能不如PostNorm理想。需要额外技巧: 使用PreNorm时，为了保证训练效果，有时需要引入额外的技术手段，如残差缩放(residual scaling)，以防止梯度爆炸或消失问题。Post-Normalization (PostNorm)定义: 在残差连接后应用Layer Normali

## q022 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `c49ff211-b1f4-4e64-b880-710419ea58af`
- Relevant child chunks: `5`
- Question: 在RAG系统中，递归字符分块策略适用于哪些场景

Parent preview: | **维度**     | **Schema (模式/蓝图)**                                     | **Metadata (元数据/标签)**                 || ------------ | ---------------------------------------------------------- | ------------------------------------------ || **定义**     | 定义数据的**结构和规则**                                   | 描述具体数据的**属性和特征**               || **关注点**   | 格式、类型（Type）、是否必填                               | 业务信息、来源、状态、时间戳               || **修改频率** | **极低**（改 Schema 通常叫“数据库迁移”，容易引起系统崩溃） | **极高**（随每一条新数据的产生而动态生成） 

## q023 - C++编码规范V01.00

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `5a2a52d3-86e6-4ebb-8c68-d3e238fc4a1c`
- Parent chunk ID: `1cab8a39-2d0a-4ec0-ab76-0851edba6b5f`
- Relevant child chunks: `5`
- Question: C++编码规范中建议使用什么结构来防止头文件被重复引用

Parent preview: h”为后缀，C 程序的定义文件以“.c”为后缀，C++程序的定义文件通常以“.cpp”为后缀（也有一些系统以“.cc”或“.cxx”为后缀）。3.2.1.1.工程目录结构1) 工程本身的文件、项目编译生成的中间文件放一个文件夹2) 最终生成的目标文件单独放一个文件夹3) 如果有工程依赖的库文件等单独放一个文件夹4) 用户代码文件放单独一个文件夹，或者将头文件和源文件单独分开放置5) 如果某些头文件是私有的，它不会被用户的程序直接引用，则没有必要公开其“声明”，为了加强信息隐藏，这些私有的头文件可以和定义文件存放于同一个目录。3.2.1.2.版权和版本的声明1)程序文件（包括头文件和源文件）头部应进行注释，注释必须列出：版权说明、文件名称、功能、与其它文件的关系、修订记录等对于修订记录暂不做强制要求。示例：下面这段头文件的头注释比较标准，当然，并不局限于此格式，但上述信息建议要包含在内。/**********************************************************************Copyright (c), Surfilter Networ

## q024 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `bf92531b-d313-4367-9b9f-5ddc68eeac0d`
- Relevant child chunks: `5`
- Question: 在文档更新策略中，当发现同名文档但 Hash 改变时，系统会执行哪些操作

Parent preview: 如果发现新文档，直接切分向量化写入；如果发现同名文档但 Hash 改变，则触发更新操作（先按照原始 Document ID 删除旧的 Chunks，再写入新的 Chunks）。- **软删除 (Soft Delete)：** 对于下线的业务文档，在向量库中通过 Metadata 字段（如 `is_active=False`）进行标记，检索时在过滤条件中直接屏蔽，比物理删除性能更好且支持回滚。## 为什么决定选用 RAG 这个技术框架选择 RAG 主要是为了在工程落地时实现**“高可用”**与**“低成本”**的平衡，核心原因有三点：1.**精准治幻觉，结果可溯源：** 大模型本质是概率预测，极易产生事实错误。RAG 相当于给模型提供“开卷考试”，强制它基于检索到的知识（比如具体的行程数据或业务规则）作答，保证复杂场景下的准确率，且答案能给出明确引用。2.**知识动态更新，成本极低：** 相比高昂且容易遗忘的“全量微调（Fine-tuning）”，RAG 实现了知识存储与逻辑推理的解耦。外部数据一变，只需更新底层的向量库即可实时生效，极其敏捷。3.**完美契合 Agent 架构：** 在

## q025 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `65291676-c23d-4b99-a429-9b4e4ff96b55`
- Relevant child chunks: `3`
- Question: 在检索结果与问题不相关时，应该采取哪些措施来防止模型胡编乱造

Parent preview: - 只给真正能支撑答案的证据片段## 13.如果检索出来的文档和问题不相关，模型开始胡编怎么办？面试官实际在问：- 检索失败时你有没有“不要乱答”的机制- 你有没有 grounded generation 的意识你要答的核心：- 先判断证据是否足够回答- 如果证据不足，不继续正常生成- 走 query rewrite、重检索、追问澄清、拒答或人工介入- 提示词里明确要求“只能基于证据回答”## 14.如果检索出来的文档毫不相关，应该如何改进？面试官实际在问：- 你有没有系统性排查能力- 你是不是只会调 top-k你要答的核心排查顺序：- query rewrite / 关键词归一化- hybrid retrieval- chunk 切分- embedding / rerank- 拒答保护机制## 15.如果检索关联性不高，能不能引入知识图谱？面试官实际在问：- 你有没有更结构化的召回增强思路- 你知不知道知识图谱的边界你要答的核心：- 可以，但不是替代 RAG，而是**增强结构化召回**- 特别适合实体关系强、多跳查询、跨文档关联明显的场景- 做法是：实体抽取 → 实体链接 → 图谱扩

## q026 - C++编码规范V01.00

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `en`
- Item ID: `5a2a52d3-86e6-4ebb-8c68-d3e238fc4a1c`
- Parent chunk ID: `c5b87c53-8770-4733-9aa7-e597ac483c77`
- Relevant child chunks: `6`
- Question: What should be done immediately after allocating memory with malloc or new according to the C++ coding standard

Parent preview: 不能影响模块功能的实现仔细考查模块或函数出错处理及模块的性能要求并进行完善通过分解或合并函数来改进软件结构考查函数的规模，过大的要进行分解降低函数间接口的复杂度不同层次的函数调用要有较合理的扇入、扇出函数功能应可预测提高函数内聚。（单一功能的函数内聚最高）3.2.7.5.使用断言1)使用断言捕捉不应该发生的非法情况2)在函数的入口处，使用断言检查参数的有效性（合法性）3.2.8.内存管理3.2.8.1.内存分配方式1)建议使用calloc 申请内存，尽量不要使用malloc2)申请内存大小必须大于03)用malloc 或new 申请内存之后，应该立即检查指针值是否为NULL，防止使用指针值C/C++编码规范任子行内部资料不得外传17 / 17为NULL 的内存4)使用指针前进行判断合法性，应考虑到为空的情况的处理5)用free 或delete 释放了内存之后，立即将指针设置为NULL，防止产生“野指针”3.2.8.2.内存释放1)C/C++中要求使用delete 和free 分别对应于new 和malloc 申请的动态内存空间进行释放2)申请的内存一定需要释放，有且仅能

## q027 - C++编码规范V01.00

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `en`
- Item ID: `5a2a52d3-86e6-4ebb-8c68-d3e238fc4a1c`
- Parent chunk ID: `17262962-f17f-47bb-9849-b53f78799377`
- Relevant child chunks: `5`
- Question: What is the section number for "函数设计" in the C/C++ development specification according to the document

Parent preview: .................43.1.4.索引设计规范...................................................................................................43.2.C/C++开发规范.........................................................................................................53.2.1.文件结构...........................................................................................................53.2.2.程序的排版.......................................................................................................73.2.3.命名规则........

## q028 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `9bd8d97a-71f2-4459-831f-6ea69de3c849`
- Relevant child chunks: `5`
- Question: RAG架构中的HyDE技术是如何缓解提问与文档表述的语义鸿沟的

Parent preview: 长上下文更像是一张巨大的“静态快照”。如果使用长上下文，你每次都需要把最新的世界状态全量灌入模型，这在工程上是灾难性的。而 RAG 架构（或者广义上的 Tool Calling 检索）可以按需、动态地拉取当前最新的切片信息。**2.灾难性的多轮对话延迟** 在 Agent 解决复杂任务的过程中，往往需要反复地规划、反思、查错和重试。如果底座是一个长上下文模型，每次内部状态机的流转都要带着几十万字的代码库或参考文档重新做一遍推理，不仅系统响应会卡顿到无法使用，本地环境的显存或 API 的并发限制也会瞬间崩溃。**3.“大海捞针”与“Lost in the Middle”效应** 虽然现在的模型号称能处理 1M Token，但在实际的“大海捞针”（Needle In A Haystack）测试中，当关键信息位于长文本的中部，且需要结合多处散落的细节进行复杂逻辑推理时，大模型的准确率依然会出现显著下降。## RAG 检索优化与多阶段召回**Query 处理层 (Query Transformation)：**- **Query Rewrite (重写)：** 用户输入往往存在指代不明（如“它

## q029 - python_coding_standards

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `1e8927d1-f559-4747-bac4-a8417c813eea`
- Parent chunk ID: `a96a0bd4-169f-47c7-93e7-48ac536f3902`
- Relevant child chunks: `5`
- Question: 根据Git提交规范，'refactor'类型代表什么含义

Parent preview: class Money:amount: floatcurrency: str```### 10.2 需要校验时使用 Pydantic```pythonfrom pydantic import BaseModel, Fieldclass UserCreate(BaseModel):email: strage: int = Field(ge=0)```## 11.测试规范推荐使用 `pytest`。### 11.1 测试文件命名```texttests/test_user_service.pytest_order_service.py```### 11.2 测试函数命名应描述行为```pythondef test_create_user_should_normalize_email():user = create_user(email=" TEST@EXAMPLE.COM ")assert user.email == "test@example.com"```### 11.3 使用 Arrange-Act-Assert 结构```pythondef test_calculate_total

## q030 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `en`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `56762f0a-bcc6-49a1-9fae-224d964fc33a`
- Relevant child chunks: `5`
- Question: What are the key differences between Tavily and Bing MCP / Bing Search API in terms of design intent, data purity, and MCP integration

Parent preview: **暂停/执行**：程序解析 LLM 输出，本地执行函数，获取结果。4.**反馈**：将工具结果喂回给 LLM，由 LLM 生成最终自然语言回答。## 项目中AI贡献的代码占比AI（如 GitHub Copilot, Cursor 或基于大模型的辅助工具）贡献了大约 30%-40% 的**基础和样板代码**（如正则匹配、API 封装、基础单测）。但核心的业务逻辑（如多 Agent 的状态切换、RAG 的召回策略调整、本地模型的显存优化与加载逻辑）是由你自主设计和把控的。## Tavily 搜索工具是如何实现的它是一个**专为 AI Agent 设计的搜索引擎聚合器**。**请求转发与聚合**：当你调用 `search.invoke` 时，Tavily 后端会同时向 Google、Bing、DuckDuckGo 等多个传统搜索引擎发送请求。**AI 特化过滤（关键）**：- **去噪**：传统搜索返回的是完整的 HTML（含广告、导航栏）。Tavily 会自动剥离这些，只保留核心文本内容。- **重排序（Reranking）**：它会根据 query 的语义对结果进行重新打分，优先返回最

## q031 - 好未来

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `a436ecb1-8553-4ae0-b8e3-0ed972cdf87b`
- Parent chunk ID: `24f49a0c-31fa-48eb-8edc-993532c352c9`
- Relevant child chunks: `5`
- Question: 在评估RAG系统时，建议按照哪五个步骤进行

Parent preview: 意义：尽管耗时较长，但能提供更直观、全面的质量反馈。3.整体系统的评测端到端性能定义：从输入查询开始，直到生成最终输出的整个流程的性能评估。意义：确保各个组件协同工作良好，提供一致且高质量的结果。响应时间定义：从发出请求到收到回复所需的时间。意义：影响用户体验，特别是在实时应用场景中尤为重要。资源消耗定义：系统运行期间所占用的计算资源（如CPU/GPU使用率、内存占用、网络带宽等）。意义：帮助理解系统的可扩展性和成本效益。实际操作建议当你准备评测一个 RAG 系统时，可以按照以下步骤进行：1.数据集选择：选取适合你应用场景的数据集作为测试基准。例如，如果你正在开发一个问答系统，可以选择公开的问答数据集如SQuAD。2.设定基线模型：为了对比改进效果，建立一个简单的基线模型（比如仅用检索或仅用生成的方法）。3.实施评测方案：根据上述提到的不同指标，设计并执行评测实验。注意记录详细的实验设置和结果。4.分析结果：比较不同模型的表现，识别出优势和不足之处。必要时调整模型参数或架构以优化性能。5.持续迭代：基于初步结果，不断调整和优化系统，重复评测过程直至达到满意的性能水平。好未来面经（熊）1

## q032 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `aa888d1d-cb58-43e2-be7f-6993048ef4e5`
- Relevant child chunks: `5`
- Question: 在Plan-and-Solve模式中，任务被分解成什么结构来确保工程鲁棒性

Parent preview: 缺点是容易陷入死循环 (Agent Loop)。**Plan-and-Solve (规划与执行)：** 适用于复杂长任务。先调用 LLM 将任务分解为有向无环图 (DAG) 或线性子任务列表，然后由执行器逐个处理。这种模式的工程鲁棒性更高，因为状态是可控的。**工程约束 (Pydantic & JSON Schema)：** 为了保证大模型输出的稳定解析，必须强制模型输出 JSON，并在代码侧使用如 Pydantic 定义严格的数据校验模型。一旦解析失败，触发自动重试 (Retry) 和修正 Prompt。## 多Agent执行策略的智能选择和切换**基于 Router 的静态路由：** 引入一个前置的“分类器 Agent”。它不执行具体任务，只负责意图识别，将请求分发给下游的 Specialist Agents。**状态机/图驱动 (如 LangGraph 思想)：** 在工程上，多 Agent 不应是自由对话（容易失控）。应将 Agent 节点化，定义明确的边（状态转移条件）。比如，Agent A 执行完，状态树变更为 `status: "code_generated"`，系统根据

## q033 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `685631cc-4b4e-4454-8aaa-089f44d268e4`
- Relevant child chunks: `5`
- Question: 请问在Agent记忆系统中，短期记忆和长期记忆分别对应哪些技术实现

Parent preview: 在喂给 LLM 之前，先用轻量级手段“洗数据”。- **做法**：- **清理 HTML**：去掉所有 Tags、Scripts、Styles（Tavily 已经帮你做了一部分）。- **语义去重**：如果三篇报道说的是同一件事，只留最全的那篇。- **摘要先行**：先调用一个廉价模型（如 GPT-4o-mini 或本地 Qwen-1.5B）把每篇文章缩减到 200 字。------### 5.改变交互范式：Refine (迭代优化)如果逻辑极度复杂，不能简单合并。- **做法**：1.把第一块内容给 LLM，得到一个初始答案。2.把第二块内容 + 初始答案再给 LLM，让它“根据新信息更新答案”。3.以此类推。- **优点**：精度最高，答案最细腻。- **缺点**：**串行执行**，无法并行，响应时间（Latency）极长。## 记忆的分类一个成熟的 Agent 记忆系统通常分为三层：- **感官记忆（Sensory Memory）**：- **对应技术**：当前的 Prompt 上下文（Context Window）。- **特点**：极其短暂，对话一清空就没了。- **短期记忆

## q034 - 好未来

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `a436ecb1-8553-4ae0-b8e3-0ed972cdf87b`
- Parent chunk ID: `0890a31a-a718-47fb-8129-08f80e788f1c`
- Relevant child chunks: `5`
- Question: vLLM Profiling的主要目的是什么

Parent preview: 利用 PRM 对中间步骤的判断来做剪枝和选择；最终选出一条“最有可能成功”的推理路径作为输出。15.写了vllm问了 vllm profill 是做什么的也问了lora微调整体流程怎么进行的(一面的一些lora八股)看起来你在准备或已经进行了一场技术面试，涉及到了 vLLM 和 LoRA（Low-RankAdaptation）。让我们来详细解答这两个方面的问题。vLLM Profiling 是做什么的？vLLM 是一个用于高效训练和推理大型语言模型（LLMs）的框架，它特别强调了在保持高性能的同时减少资源消耗。Profiling（性能剖析） 是评估和优化程序性能的关键步骤，尤其是在处理大规模数据集和复杂模型时尤为重要。好未来面经（熊）12vLLM Profiling 的主要目的包括：1.性能瓶颈分析：识别出哪些部分是计算密集型或内存密集型的，从而确定优化的重点。2.资源利用效率：了解CPU、GPU、内存等资源的使用情况，确保它们被充分利用。3.时间消耗分布：分析在整个训练或推理过程中各个阶段的时间消耗，比如前向传播、反向传播、数据加载等。4.调优指导：基于profiling的结果，调整

## q035 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `en`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `5e876c0c-83d5-47aa-b839-211d3591fff1`
- Relevant child chunks: `6`
- Question: What is the execution order of `__new__` and `__init__` when creating an object in Python

Parent preview: - 每次执行到 `yield` 时，函数会“暂停”并返回一个值。- 下一次调用时，它会从上次暂停的地方继续运行，保留之前的所有变量状态。## 装饰器又是啥装饰器就是一个“包装盒”，它能在不修改原函数代码的情况下，给原函数动态增加新的功能。**代码复用（DRY原则）：** 像日志记录、权限校验、耗时统计这种“通用逻辑”，写一次装饰器，到处都能用。**无侵入性：** 保持了核心算法逻辑的干净。想加功能就加上 `@`，不想用了直接注释掉这一行，丝毫不影响核心代码运行。自己动手写一个装饰器，其实就像是做一个“俄罗斯套娃”。它的核心逻辑非常简单：**写一个函数，接收一个旧函数作为参数，然后在内部把它包装一下，最后返回一个增强版的新函数。**```pythonfrom functools import wrapsdef my_custom_decorator(func):@wraps(func)def wrapper(*args, **kwargs):# 1.在函数执行前做点什么（比如权限校验、数据预处理）# 2.执行原函数result = func(*args, **kwargs)# 3.在函数

## q036 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `7f837269-5563-44b3-9707-2d1c093656de`
- Relevant child chunks: `6`
- Question: 为什么要引入 LangGraph

Parent preview: __new__(cls)# 如果已经有了，就直接返回已有的实例return cls._instance# 测试config1 = SystemConfig()config2 = SystemConfig()print(config1 is config2)  # 输出: True (它们在内存中是同一个对象)```#### 继承并定制不可变类型 (Immutable Types)像 `int`、`str`、`tuple` 这样的内置类型是**不可变**的。这意味着对象一旦创建，就不能再修改。如果你想继承它们并修改初始值，不能在 `__init__` 里做（因为那时对象已经创建定型了），**必须在 `__new__` 里拦截**。## 可变数据类型和不可变类型有哪些## python的垃圾回收机制# 设计模式# 后端# fastapi和django有啥区别# 面试真题## 网宿科技## 为什么要引入 LangGraph？面试官实际在问：- 普通 workflow / 状态机能不能做- 你上 LangGraph 是不是为了炫框架- 它到底带来了什么不可替代的工程价值你要答的核心：- 普通 

## q037 - 好未来

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `a436ecb1-8553-4ae0-b8e3-0ed972cdf87b`
- Parent chunk ID: `0c3fd6f7-6820-462f-ae49-c0a31f534ceb`
- Relevant child chunks: `5`
- Question: GRPO 是如何通过 KL 正则化和熵正则化间接影响智能体思考长度的

Parent preview: GRPO 是一种基于策略梯度的方法，旨在通过显式建模策略更新过程中的 KL 散度来控制策略的变化幅度。尽管 GRPO 并不直接规定智能体的思考长度，但它可以通过以下方式间接影响这一属性：KL 正则化：通过限制新旧策略之间的差异，GRPO 可以帮助智能体逐步改进其策略，而不是一次性做出大幅调整。这对于需要长时间积累经验的任务尤其重要，因为它减少了策略突变的风险。熵正则化：一些版本的 GRPO 可能会引入熵正则项，鼓励智能体保持一定的探索性。这意味着即使在思考长度有限的情况下，智能体仍然有机会发现新的、潜在更有价值的行为模式。实验与评估为了具体分析 GRPO 训练过程中思考长度与答案正确性之间的关系，你可以设计一系列实验：好未来面经（熊）211.变量控制：固定其他条件不变，仅改变智能体的思考长度（例如，通过调整规划步数或记忆容量）。2.性能指标：记录不同思考长度下的累积奖励、收敛速度以及最终策略的质量。思考长度与答案正确性之间的关系并非一成不变，而是依赖于具体的任务需求、环境特征及算法实现细节。在 GRPO 或其他强化学习框架下，找到合适的思考长度对于优化智能体的表现至关重要。通过系统化的

## q038 - 好未来

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `a436ecb1-8553-4ae0-b8e3-0ed972cdf87b`
- Parent chunk ID: `1f2f4747-ceef-4367-bc9a-c8333cd70a9b`
- Relevant child chunks: `5`
- Question: GRPO和PPO在更新机制上的主要区别是什么

Parent preview: PPO 的扩展，强调了策略更新过程中对 KL 散度的显式建模与正则化。✅ 基本思想：GRPO 的核心在于：不再使用 clip 机制；而是直接对新旧策略之间的 KL 散度进行建模，并将其作为正则项加入到损失函数中；可以看作是 TRPO / PPO 的统一形式，更灵活地控制策略更新的幅度。🔑 核心公式（Policy Loss）：或者也可以写成：（取决于具体变体，是否使用熵正则化）其中：第一项是策略梯度项；第二项是对旧策略的 KL 正则化或 entropy regularization；或  是调节权重的超参数。✅ 特点：优点缺点更加理论统一，可解释性更强需要估计 KL 或 entropy，计算稍复杂可以自动调整策略更新的大小对 KL/entropy 估计的质量敏感更容易结合其他目标（如探索最大化）相比 PPO，社区支持略少🔄 三、GRPO vs PPO：核心区别对比维度PPOGRPOL(θ) = Et[A​ log πθ(a​∣s​) −tttλD​(π​∣∣π​)]KLθ​oldθL(θ) = Et[A​ log πθ(a​∣s​)] −tttβH(π​)θλβ好未来面经（熊）7更新机制

## q039 - python_coding_standards

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `1e8927d1-f559-4747-bac4-a8417c813eea`
- Parent chunk ID: `c7b37408-77f5-4d82-92a9-57a999a4d59e`
- Relevant child chunks: `5`
- Question: Python编程规范中推荐使用哪种工具进行代码格式化？并说明行宽限制是多少

Parent preview: # Python 编程规范> 适用范围：本规范适用于 Python 3.10+ 项目，覆盖代码风格、命名、类型标注、异常处理、日志、测试、项目结构与工程化配置。## 1.基本原则- **可读性优先**：代码首先是写给人看的，其次才是给机器执行的。- **保持一致**：同一项目内的命名、格式、目录结构和工具配置应保持一致。- **简单明确**：优先选择直接、清晰、低复杂度的实现。- **显式优于隐式**：避免隐藏副作用、魔法变量和过度动态行为。- **自动化约束**：使用格式化、静态检查和测试工具减少人工审查成本。## 2.代码格式推荐使用 `black` 统一格式化代码，使用 `ruff` 做 lint 检查。### 2.1 缩进使用 4 个空格缩进，不使用 Tab。```pythondef calculate_total(price: float, quantity: int) -> float:return price * quantity```### 2.2 行宽推荐最大行宽为 88 字符，与 `black` 默认配置一致。```python# 推荐result = proces

## q040 - 好未来

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `a436ecb1-8553-4ae0-b8e3-0ed972cdf87b`
- Parent chunk ID: `ca850b02-d9f9-4b04-a0a3-776c096afb72`
- Relevant child chunks: `2`
- Question: 如何使用T5模型进行束搜索解码

Parent preview: model = AutoModelForSeq2SeqLM.from_pretrained("t5-small")# 输入文本好未来面经（熊）24input_text = "translate English to German: How are you?"# Tokenize inputinput_ids = tokenizer.encode(input_text, return_tensors="pt")# Beam search decodingbeam_outputs = model.generate(input_ids,max_length=50,num_beams=5,early_stopping=True)# Decode outputfor beam_output in beam_outputs:print(tokenizer.decode(beam_output, skip_special_tokens=True))这段代码展示了如何使用 T5 模型进行束搜索解码。你可以进一步调整参数或添加自定义逻辑以满足特定需求。希望这些信息能帮助你更好地理解和实现 LongCoT

## q041 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `34f229bb-e764-4a27-991d-857611cad2eb`
- Relevant child chunks: `5`
- Question: 静态文档和动态交互作为数据源有什么区别

Parent preview: | **数据源** | 静态文档（PDF、维基） | 动态交互（用户的习惯、历史决定） || **时效性** | 固定的知识            | 随时间进化的个人画像             || **目标**   | 找答案                | 懂用户（个性化）                 |## *Pydantic*又是啥Pydantic 是 Python 中最流行的“数据验证和设置管理”库。它利用 Python 的类型提示（Type Hints）来强制校验数据格式。# Mysql## MySQL 中的事务隔离级别有哪些？隔离级别越高，数据越安全，但并发性能越低：1.**读未提交 (Read Uncommitted)**：有脏读风险。2.**读已提交 (Read Committed)**：解决脏读，有不可重复读风险（大多数数据库默认）。3.**可重复读 (Repeatable Read)**：解决不可重复读（MySQL 默认，通过 MVCC 解决）。4.**串行化 (Serializable)**：最高级别，解决幻读，但并发极差。## 什么是索引覆盖？当一条

## q042 - C++编码规范V01.00

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `5a2a52d3-86e6-4ebb-8c68-d3e238fc4a1c`
- Parent chunk ID: `e455a3de-d117-4c6b-8c40-5a014eb398f7`
- Relevant child chunks: `5`
- Question: 在C++编码规范中，修饰符*和&应当紧靠什么位置

Parent preview: 程序的分界符‘{’和‘}’应独占一行并且位于同一列，同时与引用它们的语句左对齐2){ }之内的代码块在‘{’右边数格处左对齐3.2.2.5.长行拆分1)代码行最大长度宜控制在70 至80 个字符以内。2)长表达式要在低优先级操作符处拆分成新行，操作符放在新行之首（以便突出操作符）。拆分出的新行要进行适当的缩进，使排版整齐，语句可读。C/C++编码规范任子行内部资料不得外传10 / 173.2.2.6.修饰符的位置应当将修饰符* 和＆紧靠变量名例如：char*name;int*x, y;// 此处y 不会被误解为指针3.2.2.7.注释1)C 语言的注释符为“/*…*/”。而在C++语言中，程序块的注释常采用“/*…*/”，行注释一般采用“//…”。注释通常用于：版本、版权声明函数接口说明重要的代码行或段落提示2)注释的位置应与被描述的代码相邻，可以放在代码的上方或右方，不可放在下方3)当代码比较长，特别是有多重嵌套时，应当在一些段落的结束处加注释，便于阅读C/C++编码规范任子行内部资料不得外传11 / 173.2.2.8.类的版式3.2.3.命名规则3.2.3.1.共性规则1)

## q043 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `a77d5fe1-c6e4-41dd-91b9-24c86c8d054d`
- Relevant child chunks: `6`
- Question: 在NDCG指标中，IDCG代表什么？它的作用是什么

Parent preview: 所以我们需要找一个“完美参考系”，算出在**最理想情况下的排序**（即把最相关的排第一，次相关的排第二）所得到的 DCG，这叫 **IDCG** (Ideal DCG)。最后，用你系统的 DCG 除以完美的 IDCG，就得到了 0 到 1 之间的相对分数：$$NDCG@K = \frac{DCG_K}{IDCG_K}$$NDCG 越接近 1，说明你的排序越完美。##### 检索排序指标：MRR (Mean Reciprocal Rank / 平均倒数排名)这是评估 RAG 系统**检索环节**的一个极其经典且严格的指标。它与我们之前聊过的 NDCG 类似，都是看“排名”，但 MRR 的性格更“霸道”。- **核心逻辑**：它**只关心第一个真正相关的文档排在第几名**。只要第一个找对了，后面的文档无论多糟糕它都不在乎。- **计算公式**：$$MRR = \frac{1}{|Q|} \sum_{i=1}^{|Q|} \frac{1}{rank_i}$$*(其中 $|Q|$ 是查询的总次数，$rank_i$ 是第 $i$ 次查询中，**第一个**相关文档出现的位置)*#### 维度二：F

## q044 - 好未来

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `a436ecb1-8553-4ae0-b8e3-0ed972cdf87b`
- Parent chunk ID: `99887fcf-15f5-4d35-969e-ce7ce3646e03`
- Relevant child chunks: `5`
- Question: 在RAG系统的检索组件评测中，常用的指标有哪些

Parent preview: 预处理阶段：准备你的文档集合，并为每篇文档生成多个向量表示。2.索引构建：创建一个高效的索引结构，以便快速查找最相关的向量。3.查询处理：当接收到一个新的查询时，计算该查询与索引中所有向量之间的相似度得分。4.结果合并与重排：由于可能存在多个向量对应同一个文档的情况，因此需要设计机制来合并这些得分，并重新排序以确定最终的检索结果列表。5.传递给生成器：将选定的相关文档或段落传递给 RAG 的生成器部分，生成最终的答案或回复。通过这种方式，你可以有效地利用多向量检索技术来增强 RAG 模型的表现，特别是在处理复杂或专业领域的查询时。这不仅提升了检索的准确性，也为生成模型提供了更为丰富和精确的信息基础。18.问了一个rag系统如何评测评测 Retrieval-Augmented Generation (RAG) 系统的效果是确保其在实际应用中能够有效工作的关键步骤。评估 RAG 系统通常涉及多个维度，包括检索组件的性能、生成组件的质量以及整体系统的效率和实用性。下面是一些常见的评测方法和指标：1.检索组件的评测好未来面经（熊）15召回率（Recall）定义：在所有相关的文档中，系统成功检索

## q045 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `en`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `2ca6c71c-b9e7-4166-a6b7-f0e1c754ad39`
- Relevant child chunks: `6`
- Question: What is the difference between pruning and quantization in model compression

Parent preview: # LLM## LLM 产生幻觉的原因及工程解决方案**原因：** LLM 本质是自回归的 Next-Token 预测器，它没有事实数据库，只有概率分布。当它遇到长尾知识或训练数据冲突时，会生成概率上合理但事实上错误的内容。**工程解决方案：**- **Grounding (上下文锚定)：** 强制使用 RAG 提供的事实作为唯一知识源。- **Prompt 约束工程：** 添加安全护栏指令（e.g., `"Strictly answer ONLY using the provided context.If the answer is not present, reply with 'I don't know'."`）。- **Self-Correction (自我反思机制)：** 在生成答案后，不直接返回给用户，而是引入一个轻量级的 Critic Agent，将“生成的答案”与“检索到的原文”进行对比校验，若发现事实冲突则触发重写。-## 长文本生成的技术方案如果要求 Agent 生成万字长文，直接一次性生成必定会导致内存溢出、注意力衰减（Lost in the middle）或超时

## q046 - 大模型微调指南

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `aa67312a-53dd-447b-9084-3e6e08f215e7`
- Parent chunk ID: `66e3e8e5-bad7-4168-96da-60af04222bdf`
- Relevant child chunks: `5`
- Question: 全量微调、LoRA和QLoRA分别有什么优缺点

Parent preview: 推荐使用 instruction / input / output 或 messages 格式。### 单轮格式```json{"instruction": "请判断用户问题的类别","input": "我的快递为什么还没到？","output": "物流问题"}```### 对话格式```json{"messages": [{"role": "system", "content": "你是一个客服意图识别助手。"},{"role": "user", "content": "我的快递为什么还没到？"},{"role": "assistant", "content": "物流问题"}]}```------## 4.定义标签映射分类任务必须建立 label 与 id 的映射。```pythonlabel2id = {"物流问题": 0,"退款问题": 1,"账号问题": 2,"其他": 3}id2label = {0: "物流问题",1: "退款问题",2: "账号问题",3: "其他"}```注意：```text训练、验证、测试、推理必须使用同一份 label2id / id2label

## q047 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `1f62beea-0a8e-44ec-82e9-baa0f7c2dbd2`
- Relevant child chunks: `5`
- Question: 请比较LangChain和LlamaIndex在核心定位上的不同。

Parent preview: 这一步的核心是**改写**，让系统能搜到更全、更准的信息。- **发散与融合**：利用 `Multi-Query` 把一个问题换着花样问几次，再用 `RAG Fusion` 把搜回来的结果重新交叉排序，以此兜底。**向量检索 (Dense Retrieval，如 BGE)**：懂语义，但可能忽略精确关键词。**关键词检索 (Sparse Retrieval，如 BM25)**：词汇匹配极准，但不懂同义词。**互惠排名融合 (Reciprocal Rank Fusion, 简称 RRF)** 是一种简单、优雅且在工业界极其有效的**多路召回融合算法**。$$RRF\_Score(d) = \sum_{r \in R} \frac{1}{k + r(d)}$$- **化繁为简**：遇到包含多个条件的长问题，用 `Decomposition` 拆成几步去搜。- **抽象化**：遇到太细节搜不到的问题，用 `Step Back` 提炼出宏观概念再搜。- **以假乱真**：著名的 `HyDE` 策略，让大模型先“瞎编”一个答案，用这个具有标准格式的假答案作为向量去搜真实的文档，这对长尾问题的匹配

## q048 - python_coding_standards

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `1e8927d1-f559-4747-bac4-a8417c813eea`
- Parent chunk ID: `e92f5999-d6fa-43fa-9917-c6faa77e0e84`
- Relevant child chunks: `2`
- Question: 在代码审查中，除了检查代码格式和命名外，还应关注哪些设计质量方面

Parent preview: - 代码是否易读、命名是否清晰？- 是否存在重复逻辑？- 函数是否过长或职责过多？- 是否有必要的类型标注？- 异常处理是否具体、可靠？- 日志是否足够定位问题？- 是否泄露敏感信息？- 是否有对应测试？- 是否存在明显性能问题？- 是否符合项目已有风格？## 18.推荐命令```bash# 安装开发依赖pip install black ruff pytest mypy pre-commit# 格式化black .# Lint 检查并自动修复ruff check .--fix# 类型检查mypy app# 运行测试pytest# 安装 Git hookpre-commit install```## 19.不推荐做法汇总- 使用 `from module import *`。- 在业务代码中大量使用 `print()`。- 捕获 `Exception` 后静默忽略。- 函数参数过多、职责过杂。- 魔法数字散落在代码中。- 在代码中硬编码密钥、密码和环境配置。- 对外部输入缺少校验。- 缺少测试或只测试正常路径。- 为了复用而过度抽象。## 20.总结良好的 Python 代码应具备以下

## q049 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `en`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `a06d5f37-a76c-430d-a4ab-c471a2a79d6e`
- Relevant child chunks: `6`
- Question: What are the four steps involved in calculating NDCG

Parent preview: 评估的核心维度：RAG 三元组 (The RAG Triad)这三个维度将 RAG 的流程拆解得清清楚楚：#### 维度一：Context Relevance (上下文相关性) —— 考察“检索层”- **核心问题**：系统从知识库里找出来的文本块（Chunks），对于回答用户的问题有用吗？里面有没有掺杂太多废话？- **为什么重要**：这就是我们在讨论“三层索引”和“BGE”时试图解决的问题。如果召回的上下文全是噪音，大模型再聪明也没用（Garbage in, garbage out）。- **传统指标辅助**：在这个维度，通常还会结合搜索领域的经典指标，如 **Recall@K**（该找的资料有没有都在前 K 个里）和 **NDCG**（最相关的资料有没有排在最前面）。> Recall@K (召回率@K): 是一个二分类指标（相关 vs 不相关）。它**不关心排名先后**，只要相关的文档出现在了前 K 个里面，就算成功。>> NDCG (Normalized Discounted Cumulative Gain / 归一化折损累计增益)：NDCG 就是专门用来评估“排序质量”的。$

## q050 - 好未来

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `a436ecb1-8553-4ae0-b8e3-0ed972cdf87b`
- Parent chunk ID: `4a805af6-2387-4f47-9082-63da30e91103`
- Relevant child chunks: `5`
- Question: 请比较行为克隆和随机策略探索两种冷启动方法的优缺点。

Parent preview: 用了多少步回报？我可以根据你的经历给出更有针对性的分析 😄10.开放问题:rl训练要冷启动，思考数据要如何构造在强化学习（Reinforcement Learning, RL）的冷启动阶段，构造合适的训练数据是一个关键挑战。冷启动指的是在没有任何先前经验或数据的情况下开始训练模型的过程。对于RL来说，这意味着需要从零开始探索环境并收集能够指导策略改进的经验数据。以下是几种构建和处理初始训练数据的方法：1.随机策略探索方法：使用随机策略与环境互动，即在每个决策点上随机选择动作。优点：简单易行，不需要任何先验知识。缺点：效率较低，可能需要大量交互才能覆盖有意义的状态空间部分。2.行为克隆（Behavior Cloning）方法：如果可以获得专家行为的数据集，则可以使用这些数据作为初始训练数据。通过模仿学习，模型尝试复制专家的行为。优点：可以快速获得高质量的初始策略。缺点：依赖于可用的专家数据，且可能无法很好地泛化到未见过的情况。3.自监督预训练方法：利用大规模无标签数据进行自监督学习，以预先训练模型的部分组件（如特征提取器），然后在此基础上进行RL训练。优点：有助于提高模型对环境的理解能力

## q051 - 好未来

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `a436ecb1-8553-4ae0-b8e3-0ed972cdf87b`
- Parent chunk ID: `15df4c6f-9aac-4383-bc08-501c7689f8f7`
- Relevant child chunks: `5`
- Question: 在RAG模型中，多向量检索有哪些潜在优势

Parent preview: 最终，在测试集上评估模型的表现，确保其泛化能力。6.部署一旦模型达到了满意的性能，就可以将其部署到生产环境中，用于实际的任务，如文本分类、问答系统等。在面试中讨论 LoRA 时，可能会涉及到更深入的技术细节，例如如何选择 \(A\) 和 \(B\) 的维度大小、不同初始化策略的影响、以及与其他微调方法（如Fine-tuning、Adapter等）相比的优势和局限性。理解这些内容不仅能帮助你更好地回答面试问题，也能加深你对模型微调的理解。17.还有问了rag里我写的多向量检索在讨论 Retrieval-Augmented Generation (RAG) 模型中的多向量检索时，我们首先需要理解 RAG 的基本概念以及它如何利用检索组件来增强生成模型的能力。RAG是一种结合了信息检索和序列到序列（Seq2Seq）模型的方法，旨在通过从大型语料库中检索相关信息来提高生成任务的质量。RAG 简介RAG 主要由两部分组成：1.检索器（Retriever）：用于从大规模文档集合中检索与输入查询最相关的文档或段落。2.生成器（Generator）：基于检索到的信息生成最终的输出文本。在传统的 RAG

## q052 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `607433ef-6344-4aa9-b142-677c55fc0740`
- Relevant child chunks: `5`
- Question: 对于需要极高准确率的企业内部知识库，文档推荐使用哪种分块策略

Parent preview: - **工程挑战：** 对于排版复杂的 PDF（多栏、穿插图片和复杂表格），准确提取结构极其困难，通常需要借助视觉大模型（如使用 OCR + 版面分析模型）来前置处理。#### 4.基于代码的 AST 分块 (Code AST Chunking)- **实现原理：** 处理代码文件时，不能按行切，否则会破坏函数体。需使用抽象语法树（Abstract Syntax Tree, AST）解析工具，以类（Class）或函数（Function）为最小粒度进行切割。- **适用场景：**- **AI 辅助编程 Agent**、代码库问答系统、API 文档检索。#### 5.语义分块 (Semantic Chunking)- **实现原理：** 不依赖标点符号，而是利用 Embedding 模型计算相邻句子的“语义相似度”。如果两句话的向量夹角非常小，说明它们在讲同一件事，就合并入同一个 Chunk；如果发现相邻两句话的相似度突然骤降（超过设定的阈值），说明话题发生转变，就在此处进行切割。- **适用场景：**- 逻辑复杂、长篇大论且没有明显排版结构的文档（如深度研究报告、学术论文正文）。- **

## q053 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `55c76298-d667-4b52-a0d3-a674e766d558`
- Relevant child chunks: `6`
- Question: 如果LLM的评分阈值一直很低，应该采取哪些措施，而不是继续让它反思

Parent preview: - LLM 的自主性主要体现在局部决策，不体现在全流程自由规划## 6.相比纯后端实现，LLM 的优势是什么？面试官实际在问：- 如果不用 LLM，后端规则能不能做- LLM 的价值是否真实存在你要答的核心：- workflow 负责确定性流程- LLM 负责**自然语言理解、偏好提取、弱结构决策、开放式结果组织**- 不是让 LLM 替代后端，而是补足规则难以穷举的部分## 7.如果每次阈值打分都很低怎么办？面试官实际在问：- 同一个 LLM 又生成又评分，会不会自嗨- 你的反思循环会不会不收敛你要答的核心：- 连续低分不是继续反思，而是**失败信号**- 低分可能来自检索不足、需求不清、模型能力不足、评分器偏差- 这时应该进入补检索、重规划、澄清问题、降级或人工介入，而不是无限循环## 8.如果一直低分，怎么定位是哪一步有问题？面试官实际在问：- 你有没有诊断链路- 你是不是只会“低分→再来一轮”你要答的核心：- 不看总分，要看**分项原因**- 将问题拆到检索、生成、评估几个阶段- 用中间产物和日志做模块级定位## 9.你说每一步都检查，效率不是太低了吗？面试官实际在问：- 你有

## q054 - 好未来

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `a436ecb1-8553-4ae0-b8e3-0ed972cdf87b`
- Parent chunk ID: `c3507937-e1c1-40d4-b842-042c88cef08b`
- Relevant child chunks: `5`
- Question: 请解释LoRA中A和B矩阵的初始化参数方式及其原因，并说明为什么不能反过来初始化

Parent preview: 好未来面经（熊）1.自我介绍和介绍论文2.deepspeed的原理，提到了ddpDDP 的工作流程简述1.模型复制：每个 GPU 上都有一份完整的模型副本。2.数据划分： 将训练数据平均分配给各个进程。3.前向传播 & 损失计算：每个进程用自己的 mini-batch 独立计算 loss。4.反向传播：各进程分别计算梯度。5.梯度同步：通过 AllReduce 算法将所有进程的梯度进行平均。6.更新参数：每个进程使用平均后的梯度更新自己的模型副本。注意数据需要均匀分布、梯度同步会带来一定的通行开销，与设备数量有关。3.Adapter和lora的区别Adapter：在每层中插入用于下游任务的参数，在微调时将模型主题冻结，仅训练特定于任务的参数，减少训练算力开销特点：在每个Transformer层中插入Adapter模块。Adapter模块通常是轻量级的，因为它们使用了低维度的中间表示。可以独立训练各个Adapter模块，这使得多任务学习变得更加容易。不改变原始模型的权重，只调整Adapter模块中的参数。Lora：通过向预训练模型的权重矩阵上进行操作，通过低秩更新矩阵来实现微调特点：直接

## q055 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `a87597be-a2ee-4ec1-8103-e462906b6044`
- Relevant child chunks: `5`
- Question: 在向量召回后，如何防止给大模型喂入重复的长文本

Parent preview: **第一步（向量召回）：** 用户的 Query 被向量化，进入 Vector DB 进行相似度检索，匹配到得分最高的 Top-K 个**子块**（例如 `child_001_a`, `child_005_b`, `child_001_c`）。2.**第二步（提取与去重）：** 代码层遍历召回的子块，提取出它们的 `metadata.parent_id`。如果多个子块属于同一个父块（例如 `child_001_a` 和 `child_001_c` 都指向 `doc_001_paragraph_3`），需要在内存中对 `parent_id` 进行**去重 (Deduplication)**，防止给大模型喂入重复的长文本。3.**第三步（KV 提取）：** 拿着去重后的 `parent_id` 列表，去 KV Store（如 Redis 或本地 SQLite）中通过 Key 快速查出对应的完整**父块文本**。4.**第四步（组装生成）：** 将获取到的完整父块文本拼接进 Prompt，一并丢给 LLM 生成最终答案。### 4.关于反向映射（父块 -> 子块）你提到“父块对应的子块关系如

## q056 - 好未来

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `a436ecb1-8553-4ae0-b8e3-0ed972cdf87b`
- Parent chunk ID: `67fa8fd0-de2b-48d8-bed8-4c18dd4a105e`
- Relevant child chunks: `5`
- Question: PRM（Process Reward Model）的主要目标是什么

Parent preview: 通过中间步骤推断呢:回了有点不懂✅ 你的理解总结如下：你提到了 CoT（Chain-of-Thought）：即让模型输出推理步骤而不是直接给出答案。对方觉得太泛了，于是引入了：ORM（Outcome Reward Model）：对最终答案打分；好未来面经（熊）10PRM（Process Reward Model）：对中间推理步骤进行打分。然后你们深入讨论到：问：是对“思考过程”打分还是对“答案”打分？答：目前主要是对 answer部分打分，因为答案更容易标注和评估。追问：如果模型没学过某个问题，无法直接得出答案，只能通过中间推理步骤推断呢？这时候你就有点卡住了，不太确定怎么处理。提示问是否了解 MCTS（Monte Carlo Tree Search）？你说了解，并解释了它的原理（比如基于模拟、回溯和探索来选择最优动作），对方回应说他们正在尝试这种方案。🧠 我来帮你补全这个逻辑链条1.为什么对 answer 打分更常见？因为在实际应用中，答案是唯一可验证的部分。我们可以用标准答案或人类评分来给答案打分，从而训练一个 Reward Model（RM）去评估模型输出的好坏。但问题是：如果模

## q057 - 大模型微调指南

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `aa67312a-53dd-447b-9084-3e6e08f215e7`
- Parent chunk ID: `b8dd3beb-52f9-49aa-9b3c-3fc12d05824e`
- Relevant child chunks: `6`
- Question: 在微调大模型的数据理解阶段，需要明确哪四个问题

Parent preview: - # 微调大模型完整指南## 一、微调大模型到底是在做什么微调大模型，本质上是让一个已经具备通用语言能力的预训练模型，进一步适应你的具体业务任务、数据分布和输出格式。常见微调目标可以分为两类：### 1.分类类任务例如：- 情感分类：正面 / 负面 / 中性- 意图识别：咨询价格 / 投诉 / 售后 / 其他- 风险识别：正常 / 涉政 / 色情 / 诈骗 / 暴力- 工单分类：退款 / 物流 / 账号 / 技术问题这类任务通常有明确标签，训练数据格式类似：```json{"text": "这个订单为什么还没发货？","label": "物流问题"}```### 2.生成类任务 / 指令微调任务例如：- 客服问答- 文案生成- 总结改写- 代码生成- 多轮对话- 结构化信息抽取这类任务通常训练模型学会根据 instruction / input 生成 output，数据格式类似：```json{"instruction": "请判断下面用户问题的意图","input": "我的快递三天没动了","output": "物流问题"}```或者：```json{"messages": [{

## q058 - 大模型微调指南

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `aa67312a-53dd-447b-9084-3e6e08f215e7`
- Parent chunk ID: `760beb4d-425d-42c4-972e-7a47eb218284`
- Relevant child chunks: `5`
- Question: 当模型预测置信度在0.60到0.90之间时，应该如何处理

Parent preview: 评估时一定要看混淆矩阵。示例：| 真实 \ 预测 | 物流 | 退款 | 账号 || ----------- | ---- | ---- | ---- || 物流        | 90   | 5    | 5    || 退款        | 12   | 80   | 8    || 账号        | 3    | 4    | 93   |从混淆矩阵可以看出：```text退款问题经常被模型预测成物流问题。```接下来应该回到数据中检查：```text- 退款和物流标签定义是否重叠- 是否存在错标- 是否需要增加区分性样本- 是否需要优化 prompt 或输入字段```------## 5.建立基线不要只看微调后的绝对指标，要和基线比较。常见基线：```text- 原始大模型 zero-shot- 原始大模型 few-shot- 传统机器学习模型，如 TF-IDF + LR- 旧线上模型- 人工规则系统```成功不是“模型训练完了”，而是：```text微调模型稳定超过基线。```------# 第五阶段：推理落地## 1.单条预测分类任务推理流程：```text输入文

## q059 - 面试常见问题

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `en`
- Item ID: `28841883-d42b-4670-a124-c571f73f8d1a`
- Parent chunk ID: `49cbeb99-4597-4ecf-9b5f-6a40d1021abc`
- Relevant child chunks: `6`
- Question: What is the fundamental difference between MCP and traditional Function Calling (FC) in terms of tool integration

Parent preview: 它统一定义了三种核心能力：- `Resources` (资源)：允许模型读取外部文件或数据（类似只读挂载）。- `Tools` (工具)：模型可调用的外部函数（带副作用的执行）。- `Prompts` (提示词模板)：预定义的交互模式。**通信方式：** MCP 底层基于 **JSON-RPC 2.0**。在本地通信场景（如 IDE 插件），通常使用 `stdio`（标准输入输出）进行进程间通信；在远程场景，则使用 `HTTP + SSE` 实现跨网络调用。## MCP 与 Function Calling (FC) 的本质区别**Function Calling 是“能力”，MCP 是“协议栈”。****工程对接差异：**- **FC：** 开发者需要在自己的业务代码里，把所有 API 的定义硬编码成 JSON Schema 喂给大模型。如果新增一个工具，必须修改核心业务代码。- **MCP：** 解耦了工具提供方和模型调用方。你只需要按照 MCP 规范启动一个 SQLite MCP Server 或 GitHub MCP Server，任何支持 MCP 的客户端（如 Claude 

## q060 - C++编码规范V01.00

- [ ] Keep
- [ ] Fix question
- [ ] Remove
- Language: `zh`
- Item ID: `5a2a52d3-86e6-4ebb-8c68-d3e238fc4a1c`
- Parent chunk ID: `0265a7d3-71c3-4324-b4f5-a30a57337e60`
- Relevant child chunks: `7`
- Question: 根据C++编码规范，表设计规范中单实例表个数必须控制在多少个以内

Parent preview: 测试，开发，线上数据库环境必须隔离。3.1.2.表设计规范单实例表个数必须控制在2000 个以内；单表分表个数必须控制在1024 个以内；表必须有主键，推荐使用UNSIGNED 整数为主键；删除无主键的表，如果是row 模式的主从架构，从库会挂住；C/C++编码规范任子行内部资料不得外传4 / 17禁止使用外键，如果要保证完整性，应由应用程序实现，外键使得表之间相互耦合，影响update/delete 等SQL 性能，有可能造成死锁，高并发情况下容易成为数据库瓶颈；将大字段，访问频度低的字段拆分到单独的表中存储，分离冷热数据；表名长度不要超过26 个字符，否则Oracle 相关对象可能会报错。3.1.3.列设计规范根据业务区分使用tinyint/int/bigint ，分别会占用1/4/8 字节；根据业务区分使用char/varchar；字段长度固定，或者长度近似的业务场景，适合使用char ，能够减少碎片，查询性能高；字段长度相差较大，或者更新较少的业务场景，适合使用varchar ，能够减少空间；存储年使用year ，存储日期使用date ，存储时间使用da
