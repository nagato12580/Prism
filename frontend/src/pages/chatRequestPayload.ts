export interface BuildChatRequestPayloadArgs {
  query: string
  effectiveTopicId: string
  history: unknown[]
  sessionId: string
  engineUserMessageId: string
  deepSearchEnabled: boolean
  deepSearchDepth: string
  includePersonalInbox: boolean
}

export function buildChatRequestPayload({
  query,
  effectiveTopicId,
  history,
  sessionId,
  engineUserMessageId,
  deepSearchEnabled,
  deepSearchDepth,
  includePersonalInbox,
}: BuildChatRequestPayloadArgs) {
  return {
    query,
    kb_uids: [effectiveTopicId],
    history,
    session_id: sessionId,
    user_message_id: engineUserMessageId,
    deep_search_enabled: deepSearchEnabled,
    deep_search_depth: deepSearchDepth,
    mode: deepSearchEnabled ? 'deep' : 'standard',
    include_personal_inbox: includePersonalInbox,
  }
}
