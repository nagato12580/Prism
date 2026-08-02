# Chat Context Pruning Design

## 背景

当前 chat 链路里，前端会把当前会话中可用的非 streaming 消息作为 `history` 发给后端。agent loop 会把这份 history 全量拼进模型上下文。这个行为在短会话里有利于多轮理解，但在长会话里会导致上下文持续膨胀，增加成本、延迟和跑满模型窗口的风险。

同时，意图识别阶段虽然函数签名接收 `history`，但实际分类输入主要是当前 `query`。这会导致 `继续`、`这些方法的出处呢`、`它们分别是什么` 这类依赖前文的短追问被误判，进而漏挂 `knowledge` 工具组。

本设计目标是：不改变前端协议和现有 agent loop 行为边界，先在后端引入两套上下文策略：

- intent classify 使用最近 5 轮完整对话。
- agent loop 在上下文低于阈值时继续使用全量 history，超过阈值后切换为“早期摘要 + 最近 10 轮完整对话”。

## 目标

- 修复意图识别只看当前 query 导致的工具组误判。
- 避免长会话中 agent loop 永远注入全量 history。
- 保留短会话和中等长度会话的完整上下文体验。
- 保留最近对话原文，使“这些、它、继续、刚才那个”等指代仍可被模型理解。
- continuation 继续作为结构化状态独立传递，不依赖摘要文本。

## 非目标

- 不重做通用 Reference Resolver。
- 不引入结构化 referent/entity working state。
- 不改变知识库工具授权和 scope 签发逻辑。
- 不裁剪工具返回证据。
- 不改变长期记忆写入、active recall 或 graph insights 的语义。
- 第一版不修改前端发送 history 的协议。

## 术语

- `turn`：一个 user 消息以及其后的 assistant 消息。实现上允许用最近若干条 `user/assistant` 消息近似，但需要尽量保持成对上下文。
- `intent recent history`：用于意图识别的最近 5 轮完整对话。
- `loop history`：进入 agent loop 的历史上下文。
- `older_history_summary`：当 loop history 超过阈值后，对最近 10 轮之前的早期历史生成的摘要。
- `continuation`：当前已有的文档续读状态，包含 `objective`、`kb_uid`、`file_uid`、`next_offset`。

## 当前链路

当前关键链路如下：

1. 前端 `buildAgentHistory(messages, historyContent)` 构造 history，过滤 streaming 消息。
2. 前端调用 `/api/v1/chat/answer`，把 `query`、`history`、`kb_uids` 等字段发给后端代理。
3. 后端代理签发 `X-Prism-Knowledge-Scope` 后转发给 engine。
4. engine `answer_stream()` 调用 `classify_intent(query, history)` 决定工具组。
5. engine 创建 runner，并调用 `runner.stream(query, history, ...)`。
6. runner `_build_messages()` 把 system prompt、active recall、graph insights、continuation、history、current query 拼成最终模型消息。

问题集中在两处：

- `classify_intent()` 实际没有把最近对话上下文作为分类输入。
- `_build_messages()` 无条件拼接全量 history。

## 设计概览

上下文策略按阶段拆分：

| 阶段 | 策略 | 原因 |
| --- | --- | --- |
| Intent classify | 最近 5 轮完整 user + assistant | 只需要近场语义来判断工具组，避免分类输入过长 |
| Agent loop 未达阈值 | 全量 history | 保留现有行为，不提前损失上下文 |
| Agent loop 达到 80% 阈值 | 早期摘要 + 最近 10 轮完整 history | 控制上下文长度，同时保留近场指代原文 |

## Intent Classify 策略

意图识别固定使用最近 5 轮完整对话。

输入结构：

```json
{
  "query": "这些方法的出处呢",
  "recent_history": [
    {"role": "user", "content": "我的论文的对比方法有哪些"},
    {"role": "assistant", "content": "你的论文里提到的对比方法包括 LMVSC、FPMVS、FDAGF、ALPC、DCMVSC、DMAC、PCMVSC、Large-MVC、BONE。"}
  ]
}
```

分类 prompt 需要明确：

- 结合当前 query 和最近 5 轮完整对话判断。
- 当前 query 出现“这些、它、它们、继续、刚才那个、这篇、上述”等指代或省略表达时，优先用 recent history 补全语义。
- 如果最近 5 轮围绕知识库、文档、论文、上传资料、参考文献、表格或章节展开，当前短追问默认继承该任务域。
- 如果最近 assistant 刚列出一组对象，用户追问“出处、分别、展开、继续、对比”，应按同一任务继续判断。
- 输出仍保持现有结构：`groups`、`kb_specs`、`reasoning`。

第一版只需要把 `history` 裁剪为最近 5 轮后拼入分类模型输入，不需要引入独立的 query rewrite。

## Agent Loop 动态裁剪策略

agent loop 默认继续使用完整 history。只有预计上下文达到模型窗口 80% 时进入压缩模式。

### Full History Mode

触发条件：

```text
estimated_tokens(system + active_recall + graph_insights + continuation + full_history + query)
< max_context_tokens * 0.8
```

行为：

- 使用完整 history。
- 不生成 `older_history_summary`。
- 保持当前 `_build_messages()` 的语义顺序。

### Compressed History Mode

触发条件：

```text
estimated_tokens(system + active_recall + graph_insights + continuation + full_history + query)
>= max_context_tokens * 0.8
```

行为：

- 保留最近 10 轮完整 `user + assistant`。
- 最近 10 轮之前的早期历史压缩成 `older_history_summary`。
- 当前 query 原样保留。
- continuation 作为独立 system message 注入。
- active recall 和 graph insights 保持现有逻辑。

## Loop 消息拼接顺序

压缩模式下推荐顺序：

```text
1. system prompt
2. older_history_summary system message
3. active recall system message
4. graph insights system message
5. continuation system message
6. recent 10 turns history messages
7. current user query
```

说明：

- `older_history_summary` 是会话上下文，不是长期记忆。
- active recall 仍使用 `effective_query` 触发，不依赖摘要。
- 最近 10 轮保留原文，避免指代、约束、语气和短追问信息丢失。
- current query 永远不压缩。

## 摘要内容规范

摘要不是流水账，只保留会影响后续回答的信息。

摘要模板：

```text
会话早期摘要：
- 用户当前主要任务：
- 已确认的对象、文档或范围：
- 已得到的关键结论：
- assistant 已列出的关键对象或中间结果：
- 尚未解决的问题：
- 用户明确给出的约束或偏好：
```

必须保留：

- 用户明确确认过的目标和约束。
- 已定位的知识库、文档、文件名、章节、对象或范围。
- assistant 已经给出的关键列表、结论和中间判断。
- 后续可能被“这些、它、继续、上面那个、刚才那些”指代的对象。
- 未完成任务和待续问题。

不要保留：

- 寒暄。
- 重复追问。
- 无关闲聊。
- 大段文档原文。
- 无影响的失败工具调用细节。
- 已被后续消息否定或替换的临时推测。

## 摘要缓存策略

首次进入 compressed history mode 时生成摘要，并缓存到会话状态。

建议缓存结构：

```json
{
  "history_summary": "会话早期摘要：...",
  "summary_until_message_id": "msg_xxx",
  "summary_updated_at": "2026-08-02T20:30:00+08:00"
}
```

后续轮次仍处于压缩模式时：

- 不从全量 history 重新摘要。
- 使用旧摘要 + 新被挤出最近 10 轮窗口的消息做增量摘要。
- 更新 `summary_until_message_id`。
- 最近 10 轮始终保留原文，不进入摘要。

第一版可以先在后端内存或 message process 中保存摘要；如果需要跨页面恢复和长期会话复用，再扩展到持久化 session 字段。

## Token 估算策略

第一版用字符数粗估，避免引入 tokenizer 依赖：

```text
estimated_tokens = ceil(total_chars / 3)
```

推荐配置项：

```python
INTENT_RECENT_TURNS = 5
LOOP_RECENT_TURNS = 10
CONTEXT_COMPRESSION_THRESHOLD = 0.8
MAX_SUMMARY_TOKENS = 1200
DEFAULT_MAX_CONTEXT_TOKENS = 32000
MIN_LOOP_RECENT_TURNS = 6
```

`max_context_tokens` 优先从模型配置读取；读取不到时使用 `DEFAULT_MAX_CONTEXT_TOKENS`。

后续可以替换成真实 tokenizer，但不影响本策略接口。

## Continuation 规则

continuation 不进入摘要，也不被裁剪。

规则：

- 最新 assistant 的 continuation 必须单独保留。
- 即使对应 assistant 消息落入早期摘要范围，continuation 仍作为结构化状态注入。
- 用户发“继续”时，优先使用 continuation 的 `objective`、`kb_uid`、`file_uid`、`next_offset`。
- 摘要可以描述“之前正在读取某文档”，但不能替代 continuation cursor。

## 降级策略

如果摘要生成失败：

- 本轮使用最近 10 轮完整 history。
- 记录 warning 日志。
- 不阻断回答。

如果压缩后仍然超过窗口预算：

- 先缩短摘要到更低 token 预算。
- 如果仍超限，把最近 10 轮降到最近 6 轮。
- current query 和 continuation 永远不裁剪。
- 如果仍然超限，返回可解释错误，说明当前会话上下文过长，需要用户缩小问题范围。

## 组件边界

推荐落地边界：

- `answer_stream` 负责 intent 阶段最近 5 轮裁剪。
- `LangChainAgentRunner` 负责 loop 阶段动态裁剪，因为它最接近最终 message 拼接，并且能看到 system prompt、active recall、graph insights 和 continuation。
- 前端继续发送完整 history，第一版不改前端协议。

建议新增或调整的内部函数：

- `recent_turn_history(history, turns)`：从 history 中截取最近 N 轮完整对话。
- `estimate_message_tokens(messages_or_text)`：粗估上下文 token。
- `prepare_loop_history(history, query, fixed_context_parts)`：根据阈值返回 full history 或 compressed history。
- `summarize_older_history(existing_summary, older_messages)`：生成或增量更新早期摘要。

## 测试要求

Intent classify 测试：

- 当前 query 为“这些方法的出处呢”，recent history 中 assistant 列出方法时，应启用 `knowledge`。
- 当前 query 为“继续”，recent history 显示上一轮在读文档时，应启用 `knowledge`。
- 当前 query 为普通闲聊，recent history 无知识任务时，不应误启用 `knowledge`。

Loop 裁剪测试：

- 估算 token 低于 80% 时，runner 使用完整 history。
- 估算 token 达到 80% 时，runner 注入 `older_history_summary` 和最近 10 轮 history。
- continuation 即使来自早期 assistant，也仍被单独注入。
- 摘要生成失败时，本轮降级为最近 10 轮 history，且不抛出用户可见异常。

## 验收标准

- 长会话不会无条件把全量 history 注入 agent loop。
- 短会话和中等长度会话保持现有完整上下文行为。
- 意图识别能利用最近 5 轮 assistant 输出理解短追问。
- `继续` 和文档续读不因 history 裁剪丢失 continuation。
- 触发压缩时，模型上下文中同时存在早期摘要和最近 10 轮原文。
- 失败降级可观测，但不阻断正常回答。
