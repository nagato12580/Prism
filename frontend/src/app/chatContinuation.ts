import type { AgentContinuation, Message } from './chatStore'

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function normalizeAgentContinuation(value: unknown): AgentContinuation | undefined {
  if (!isPlainRecord(value) || value.version !== 1) return undefined

  const objective = typeof value.objective === 'string' ? value.objective.trim() : ''
  const kbUid = typeof value.kb_uid === 'string' ? value.kb_uid.trim() : ''
  const fileUid = typeof value.file_uid === 'string' ? value.file_uid.trim() : ''
  if (!objective || !kbUid || !fileUid || kbUid.length > 128 || fileUid.length > 128) {
    return undefined
  }
  if (!Number.isInteger(value.next_offset) || (value.next_offset as number) < 0) return undefined
  if (value.has_more_after !== true) return undefined

  return {
    version: 1,
    objective: objective.slice(0, 8_000),
    kb_uid: kbUid,
    file_uid: fileUid,
    next_offset: value.next_offset as number,
    has_more_after: true,
  }
}

function defaultHistoryContent(message: Message) {
  if (message.role === 'assistant' && message.clarify) {
    const options = message.clarify.options.map((option) => option.label).filter(Boolean).join('\n')
    return [message.content, message.clarify.question, options].filter(Boolean).join('\n')
  }
  return message.content
}

export function buildAgentHistory(
  messages: Message[],
  contentForMessage: (message: Message) => string = defaultHistoryContent,
) {
  const historyMessages = messages.filter((message) => !message.streaming)
  let latestAssistantIndex = -1
  for (let index = historyMessages.length - 1; index >= 0; index -= 1) {
    if (historyMessages[index].role === 'assistant') {
      latestAssistantIndex = index
      break
    }
  }

  return historyMessages.map((message, index) => {
    const continuation = index === latestAssistantIndex
      ? normalizeAgentContinuation(message.agentContinuation)
      : undefined
    return {
      role: message.role,
      content: contentForMessage(message),
      ...(continuation ? { continuation } : {}),
    }
  })
}

export function buildAssistantProcess(message: Message) {
  return {
    trace_id: message.traceId || null,
    agent_status: message.agentStatus || null,
    tool_runs: message.toolRuns || [],
    thinking_steps: message.thinkingSteps || [],
    agent_continuation: message.agentContinuation || null,
  }
}

export function applyAgentContinuationEvent(
  value: unknown,
  setContinuation: (continuation: AgentContinuation) => void,
  persistSnapshot?: () => void,
) {
  const continuation = normalizeAgentContinuation(value)
  if (!continuation) return false

  setContinuation(continuation)
  persistSnapshot?.()
  return true
}
