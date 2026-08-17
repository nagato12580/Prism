# Ragas Bad Case: q002

**Question:** 在Skill管理中，两阶段调用的第一阶段应检索多少个最相关的Skill

**Tags:** retrieval_failure, ragas_failed

## Scores

{
  "response_relevancy": 0.9893908680316602
}

## Answer

关于Skill管理中两阶段调用的第一阶段应检索多少个最相关的Skill，这个问题没有一个绝对固定的答案，具体数量取决于你的系统设计、任务复杂度以及所使用的模型上下文窗口等约束。

不过，从常见的工程实践和通用设计原则来看：

- **常见取值范围**：第一阶段通常检索 **5～10 个** 最相关的 Skill 作为候选集。其中，**top-5** 和 **top-10** 是两种最常见的设定。
- **两阶段的目的**：第一阶段侧重于“召回”，即尽量把可能相关的 Skill 都捞出来，避免漏掉正确项；第二阶段侧重于“精排”或最终选择，从候选中选出最合适的那一个（或少数几个）来实际调用。
- **取舍考量**：
  - 数量太少（如仅1～3个）：可能会遗漏真正合适的 Skill，导致调用错误或失败。
  - 数量太多（如20个以上）：会给第二阶段带来不必要的噪声，增加计算开销，并可能超出模型的上下文限制。
- **动态调整**：一些系统会根据用户查询的模糊程度或当前可用 Skill 总数动态调整候选数。若 Skill 库本身不大，可能第一阶段直接全部候选即可。

如果你是在某个特定课程、文档或框架的背景下提出这个问题，建议优先查阅该资料中给出的明确数值或推荐配置。若没有额外说明，采用 **top-5 至 top-10** 作为第一阶段的检索数量是较为稳妥的通用做法。

## Retrieved Contexts



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



## Metadata

{
  "question_type": "",
  "paper_title": "面试常见问题",
  "ttfb_ms": 1810,
  "total_latency_ms": 39212,
  "tool_calls": 8,
  "token_count": 1,
  "status": "done",
  "missing_context_count": 0
}