# 个人 AI 助手 Skill Engine 设计文档

> **日期**: 2026-06-16
> **目标读者**: Claude Code / 后端开发 / 架构设计者
> **状态**: 可实施设计
> **适用对象**: 个人 AI 助手中的任务规划、工具调用、MCP 编排、结果沉淀能力

---

## 1. 目标

为个人 AI 助手设计一套可落地的 `Skill Engine`，让助手不只会“回答问题”，还能够把复杂目标拆成步骤，调用知识检索、MCP 工具、多模态能力和外部 API，执行后输出结构化结果，并把有价值的信息沉淀回知识库。

该设计文档的目标不是描述抽象理念，而是为 Claude Code 提供足够明确的实现边界、模块职责、数据结构、接口约定和实施顺序，使其能够直接在你的项目中开始设计与改造。

---

## 2. 背景与设计判断

### 2.1 为什么个人助手需要 Skill Engine

如果你的助手只做单轮问答，那么它最多是：

- 一个聊天界面
- 一个带检索的 RAG 问答器
- 一个能偶尔调工具的函数调用机器人

但你明确希望它具备以下能力：

- 知识问答
- 多模态问答
- 接入 MCP 帮你操作东西
- 把结果沉淀为 Wiki

这四类能力一旦并存，系统就会出现一个核心问题：

> 用户提出的是目标，不是单一问题；系统必须决定“先做什么、后做什么、结果如何流转、何时结束、哪些结果需要沉淀”。

因此需要一个显式的任务执行层，而不是把所有能力直接塞进一个大 prompt。

### 2.2 本仓库中最值得复用的参考实现

当前仓库已有一套较成熟的多步骤执行骨架，建议作为直接参考：

- Skill 引擎入口: [engine/engines/skill/engine.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/engine.py:17)
- Skill 模板解析: [engine/engines/skill/parser.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/parser.py:17)
- Skill 匹配器: [engine/engines/skill/matcher.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/matcher.py:8)
- 自动规划器: [engine/engines/skill/auto_planner.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/auto_planner.py:49)
- 执行器: [engine/engines/skill/executor.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/executor.py:54)
- 执行评估器: [engine/engines/skill/planner.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/planner.py:24)
- API 注册表: [engine/engines/skill/api_registry.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/api_registry.py:10)
- MCP 客户端: [backend/app/utils/mcp_client.py](/data1/WORKSPACE_CSM/cake/backend/app/utils/mcp_client.py:20)

### 2.3 对现有实现的技术判断

现有实现最有价值的设计，不是 prompt 本身，而是以下工程方法：

1. `预设 Skill` 和 `自动规划` 两条路径并存。
2. 规划结果不是自然语言，而是结构化步骤。
3. 规划结果会被代码校验，而不是完全信任模型。
4. 每一步都有独立状态、产物、重试和失败处理。
5. 上一步的结构化输出可以成为下一步的输入。
6. 最终结果可以落盘、可回放、可沉淀。

这正是个人 AI 助手从“会聊”走向“会做事”的关键。

---

## 3. 设计范围

### 3.1 在范围

- 任务分类与路由
- 预设 Skill 模板执行
- 自动规划执行
- 工具注册与调用
- MCP 工具接入
- 多模态工具接入
- 步骤执行状态管理
- 结果结构化保存
- 结果回写知识库/Wiki 的挂钩

### 3.2 不在范围

- 具体某个 MCP Server 的业务实现
- 向量库和 Wiki 的详细数据建模
- 前端交互细节
- 图数据库高级能力

这些由另一份知识沉淀文档定义。

---

## 4. 目标架构

### 4.1 总体拓扑

```text
User
  -> Assistant API
  -> Task Router
     -> Chat Mode
     -> RAG QA Mode
     -> Skill Engine Mode

Skill Engine
  -> Skill Matcher
  -> Auto Planner
  -> Step Executor
  -> Tool Registry
     -> Knowledge Retrieval Tools
     -> MCP Tools
     -> Multimodal Tools
     -> Built-in Utility Tools
  -> Result Store
  -> Knowledge Sink / Wiki Sink
```

### 4.2 设计原则

1. `Skill Engine` 是“任务执行层”，不是单纯的 LLM 包装层。
2. LLM 负责理解、规划、评估，但不直接控制底层系统状态。
3. 所有可调用能力必须注册成显式工具，统一输入输出契约。
4. 步骤之间尽量传结构化结果，而不是只传文本。
5. 可以失败，但失败必须可追踪、可恢复、可解释。

---

## 5. 目标能力分层

### 5.1 L0: 对话与路由层

负责判断请求属于哪一类：

- 普通闲聊
- 直接知识问答
- 多模态问答
- 需要外部操作的任务
- 需要多步骤执行的任务

建议规则：

- 简单事实问答优先走 `RAG QA`
- 明确指令型任务优先走 `Skill Engine`
- 图片/文件输入自动附加多模态上下文
- 含“帮我整理/分析/生成/调用/抓取/更新/同步”等词时，偏向 Skill 路由

### 5.2 L1: Skill 定义层

参考现有 `SkillDefinition` 和 `StepDefinition`：
[parser.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/parser.py:23)

目标是保留这种结构化模板能力，但将其泛化到你的个人助手。

建议的数据模型：

```yaml
name: project_research_and_wiki
description: 收集某个主题的信息，提炼结论并沉淀为 wiki
keywords:
  - 调研
  - 总结
  - wiki
scenario: |
  适用于用户希望收集资料、整理结论并沉淀到知识库的场景。
steps:
  - name: 检索已有知识
    step_type: tool_call
    tool_name: knowledge_search
    input_type: original
    params:
      query: "{{task}}"
  - name: 补充联网或 MCP 信息
    step_type: tool_call
    tool_name: mcp_web_fetch
    input_type: original
    params:
      query: "{{task}}"
  - name: 归纳结构化要点
    step_type: llm_transform
    input_type: previous
    params:
      schema: topic_summary_v1
  - name: 生成 wiki 草稿
    step_type: llm_transform
    input_type: previous
    params:
      schema: wiki_article_v1
  - name: 保存 wiki
    step_type: tool_call
    tool_name: wiki_upsert
    input_type: previous
```

### 5.3 L2: 自动规划层

预设 Skill 覆盖不了的任务，由自动规划器负责。

现有参考实现做得对的地方：

- 先拿可用 API 列表
- 让 LLM 输出 JSON plan
- 用代码验证 plan
- 验证失败后触发自修正

参考代码：
[auto_planner.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/auto_planner.py:149)

对你的项目，自动规划器建议输出如下结构：

```json
{
  "reasoning": "用户希望先调研，再整理，再沉淀为 wiki，因此需要先检索知识与外部工具，再生成文章并保存。",
  "steps": [
    {
      "step": 1,
      "tool": "knowledge_search",
      "params": {
        "query": "${user.task}"
      },
      "description": "检索本地知识库"
    },
    {
      "step": 2,
      "tool": "mcp_tool_call",
      "params": {
        "server": "browser",
        "tool_name": "search",
        "query": "${user.task}"
      },
      "description": "调用 MCP 进行补充搜索"
    },
    {
      "step": 3,
      "tool": "llm_structured_transform",
      "params": {
        "schema": "wiki_article_v1",
        "sources": "${step1.results} + ${step2.results}"
      },
      "description": "整理为 wiki 草稿"
    },
    {
      "step": 4,
      "tool": "wiki_upsert",
      "params": {
        "title": "${step3.title}",
        "content": "${step3.content}"
      },
      "description": "保存 wiki"
    }
  ]
}
```

### 5.4 L3: 执行层

执行器需要保留当前仓库的几个优点：

- 每步有 `step_id`
- 每步有 `input snapshot`
- 每步有 `result snapshot`
- 支持 `retry`
- 支持 `pause/resume`
- 支持流式输出中间进度

现有参考：
[executor.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/executor.py:61)

但建议对你的项目做三点改造：

1. 不要绑定“结果转表”这种数据库场景专属机制，改成通用 `artifact store`。
2. 步骤类型不要只保留 `query_analysis/query/report`，改为通用任务类型。
3. 引入统一的 `ToolResult` 和 `Artifact` 模型。

建议步骤类型：

- `tool_call`
- `llm_transform`
- `retrieval`
- `decision`
- `human_approval`
- `persist`

### 5.5 L4: 工具层

工具必须统一注册，不允许 Planner 直接自由生成调用代码。

参考当前 `ApiRegistry`：
[api_registry.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/api_registry.py:10)

建议改为四大类工具：

1. 知识工具
   - `knowledge_search`
   - `knowledge_get`
   - `wiki_upsert`
   - `wiki_search`
   - `memory_lookup`

2. MCP 工具
   - `mcp_list_servers`
   - `mcp_list_tools`
   - `mcp_tool_call`

3. 多模态工具
   - `image_understand`
   - `document_understand`
   - `audio_transcribe`
   - `video_keyframe_summarize`

4. 内置工具
   - `structured_extract`
   - `markdown_render`
   - `task_note_append`
   - `artifact_save`

### 5.6 L5: 沉淀层

Skill Engine 的终点不应该只是把结果返回给用户，而应该允许：

- 写入对话记录
- 写入任务记录
- 写入 Wiki
- 写入长期记忆
- 写入待办或外部系统

这就是它和普通 Agent 最大的差别。

---

## 6. 模块设计

### 6.1 建议目录结构

如果你的个人助手项目采用 `backend + engine` 双服务架构，建议新增或改造成如下结构：

```text
assistant/
  backend/
    app/
      api/
        chat.py
        tasks.py
        wiki.py
        knowledge.py
        mcp.py
      models/
        task.py
        task_step.py
        wiki_entry.py
        knowledge_item.py
      services/
        task_service.py
        wiki_service.py
        knowledge_service.py
  engine/
    engines/
      skill/
        engine.py
        router.py
        matcher.py
        parser.py
        auto_planner.py
        executor.py
        evaluator.py
        registry.py
        artifact_store.py
        templates/
      rag/
      multimodal/
    tools/
      knowledge_search.py
      wiki_upsert.py
      mcp_call.py
      image_understand.py
```

### 6.2 核心实体

#### Task

```python
Task(
  id,
  user_id,
  mode,              # chat | rag | skill
  title,
  original_input,
  status,            # queued | running | paused | failed | completed
  route_reason,
  final_answer,
  created_at,
  updated_at,
)
```

#### TaskStep

```python
TaskStep(
  id,
  task_id,
  step_index,
  step_name,
  step_type,
  tool_name,
  input_payload,
  output_payload,
  status,            # queued | running | failed | completed | skipped
  retry_count,
  started_at,
  finished_at,
)
```

#### Artifact

```python
Artifact(
  id,
  task_id,
  step_id,
  artifact_type,     # json | markdown | image | text | wiki_draft
  title,
  content,
  metadata,
  created_at,
)
```

### 6.3 工具注册契约

所有工具统一遵循：

```python
class ToolSpec(BaseModel):
    name: str
    category: str
    description: str
    input_schema: dict
    output_schema: dict
    require_approval: bool = False

class ToolResult(BaseModel):
    success: bool
    data: dict
    artifacts: list[dict] = []
    error: str | None = None
    next_hints: list[str] = []
```

这样 Planner 和 Executor 不需要知道具体工具内部实现。

---

## 7. MCP 集成设计

### 7.1 参考实现

当前仓库已经有基础 MCP 客户端封装：
[mcp_client.py](/data1/WORKSPACE_CSM/cake/backend/app/utils/mcp_client.py:20)

已有能力：

- SSE transport
- Streamable HTTP transport
- `tools/list`
- `tools/call`

这是一个良好的底层起点，但还不够直接给 Skill Engine 使用。

### 7.2 目标设计

新增 `McpRegistry` 和 `McpToolAdapter`：

```text
McpServerConfig
  -> McpConnectionFactory
  -> McpRegistry
  -> McpToolAdapter
  -> ToolRegistry
```

#### 建议数据表

```python
McpServerConfig(
  id,
  name,
  transport_type,      # sse | streamable_http
  server_url,
  auth_type,
  auth_config_json,
  enabled,
  created_at,
)
```

#### 运行机制

1. 系统启动时加载所有启用的 MCP Server。
2. 为每个 Server 执行 `initialize` 或 `connect`。
3. 拉取 `tools/list`。
4. 将远端 MCP tool 映射为本地 ToolRegistry 中的逻辑工具。
5. Executor 调用时只调用 `mcp_tool_call` 统一入口。

### 7.3 对 Claude Code 的实现要求

- 不要让 Planner 直接依赖具体 MCP server 名称。
- 先做“工具发现 + 映射层”，再做执行。
- 所有 MCP 调用必须记录输入参数、输出结果和错误信息。
- 涉及副作用的 MCP 工具必须支持人工确认。

---

## 8. 执行流程设计

### 8.1 主流程

```text
收到用户请求
  -> 路由判断是否进入 Skill Engine
  -> 尝试匹配预设 Skill
     -> 匹配成功: 按 Skill 模板执行
     -> 匹配失败: 进入 Auto Planner
  -> 生成结构化步骤
  -> 校验步骤
  -> 逐步执行
     -> 记录 step 状态
     -> 产出 artifact
     -> 评估结果
     -> 决定 continue / adjust / retry / abort
  -> 汇总最终结果
  -> 如有需要，沉淀为 wiki / memory / note
  -> 返回用户
```

### 8.2 结果评估

当前仓库的 `PlannerDecision` 值得保留：
[planner.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/planner.py:12)

建议沿用：

- `continue`
- `adjust`
- `retry`
- `abort`

但评估维度改为通用：

- 是否拿到了结果
- 结果是否为空
- 结果是否满足 schema
- 结果是否足以支持下一步
- 是否需要用户补充信息

### 8.3 用户确认点

对于以下情况，必须允许中断等待确认：

- 将内容写入外部系统
- 删除/覆盖知识库内容
- 调用高风险 MCP 工具
- 发消息、下单、执行脚本、修改文件

建议新增 `human_approval` 步骤类型，而不是在工具内部静默处理。

---

## 9. 与知识沉淀链路的衔接

Skill Engine 不负责完整实现知识库，但必须内置两个沉淀出口：

1. `wiki_upsert`
2. `memory_upsert`

典型场景：

- 用户说“把这次分析沉淀成 wiki”
- 用户说“把这个方案整理成知识卡片”
- 系统识别任务结果适合长期保存

因此在设计上，Skill Engine 的每个最终 `Artifact` 必须可被知识系统消费。

---

## 10. 实施计划

### Phase 1: 最小闭环

目标：先让系统具备最基本的多步骤执行能力。

实现内容：

- 建立 `Task` / `TaskStep` / `Artifact` 数据模型
- 建立 `ToolRegistry`
- 建立 `SkillDefinition` 文件格式
- 支持预设 Skill 执行
- 提供 3 个基础工具：
  - `knowledge_search`
  - `wiki_upsert`
  - `mcp_tool_call`

验收标准：

- 能执行一个“检索 -> 总结 -> 写 wiki”的任务
- 每个步骤有状态记录
- 失败可见
- 结果可回放

### Phase 2: 自动规划

实现内容：

- Auto Planner
- Plan Validator
- 参数引用解析
- 评估器与重试机制

验收标准：

- 未命中预设 Skill 时，能自动生成有效计划
- 计划中引用的工具都来自注册表
- 错误计划会被拒绝或修正

### Phase 3: MCP 与多模态增强

实现内容：

- MCP 注册中心
- 工具动态发现
- 图片/文档理解工具接入
- 人工确认机制

验收标准：

- 能在任务中混合调用知识搜索、图片理解和 MCP 工具
- 有副作用的操作需要确认

### Phase 4: 长期沉淀

实现内容：

- 自动生成任务摘要
- 自动生成 wiki 草稿
- 自动更新记忆

验收标准：

- 一次复杂任务执行后，可自动生成可编辑的 wiki 草稿

---

## 11. Claude Code 实施说明

Claude Code 应按以下顺序改造项目：

1. 建立 `Task/TaskStep/Artifact` 的后端模型与迁移。
2. 建立 `ToolRegistry` 抽象层，不要直接把工具逻辑写进 Planner。
3. 复用当前仓库 `parser/matcher/auto_planner/executor/planner` 的设计思路，但改成面向个人助手的通用步骤模型。
4. 先实现最小的 3 个工具：`knowledge_search`、`wiki_upsert`、`mcp_tool_call`。
5. 先用预设 Skill 打通闭环，再上 Auto Planner。
6. 引入步骤级日志与 Artifact 持久化，确保可调试。

Claude Code 不应该做的事：

- 不要直接做一个只有 prompt 的“大一统 agent”
- 不要让模型自由拼接任意 HTTP 调用
- 不要跳过工具注册和 schema 校验
- 不要一开始就追求全自动自治

---

## 12. 验收清单

以下条件满足，视为 Skill Engine 第一版设计落地成功：

1. 用户可以触发一个多步骤任务。
2. 系统能区分预设 Skill 和自动规划。
3. 所有步骤都有结构化状态记录。
4. 工具调用统一经过注册表。
5. 至少接入一个 MCP server 并可调用其 tool。
6. 至少一个任务可以把结果沉淀为 Wiki 草稿。
7. 失败任务具备排错信息和重试路径。

---

## 13. 参考代码索引

实现时优先阅读以下代码：

- Skill 引擎入口: [engine/engines/skill/engine.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/engine.py:17)
- Skill 模板解析: [engine/engines/skill/parser.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/parser.py:17)
- Skill 匹配: [engine/engines/skill/matcher.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/matcher.py:8)
- 自动规划: [engine/engines/skill/auto_planner.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/auto_planner.py:49)
- 执行器: [engine/engines/skill/executor.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/executor.py:54)
- 执行评估: [engine/engines/skill/planner.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/planner.py:24)
- API 注册表示例: [engine/engines/skill/api_registry.py](/data1/WORKSPACE_CSM/cake/engine/engines/skill/api_registry.py:10)
- MCP 客户端底层: [backend/app/utils/mcp_client.py](/data1/WORKSPACE_CSM/cake/backend/app/utils/mcp_client.py:20)

---

## 14. 结论

对你的个人 AI 助手，`Skill Engine` 不应被实现成“高级 prompt”，而应被实现成：

> 一个可规划、可执行、可审计、可沉淀的任务操作系统。

这份设计文档定义的是第一版实现路径。后续具体代码改造，应严格围绕“结构化步骤、统一工具层、可追踪状态、结果可沉淀”四条主线推进。
