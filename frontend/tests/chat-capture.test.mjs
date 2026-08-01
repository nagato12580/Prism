import assert from 'node:assert/strict'

// Mirrors the label map used in ChatPage's thinking panel (toolLabel()).
function toolLabel(tool) {
  const labels = {
    chat: '闲聊',
    knowledge_search: '检索知识库',
    capture_thought: '记录想法',
    clarify_user: '补充信息',
    retrieve: '检索',
    search: '搜索',
    rerank: '重排',
    synthesize: '生成',
    tool: '工具',
  }
  return labels[tool] ?? tool
}

assert.equal(toolLabel('capture_thought'), '记录想法')
assert.equal(toolLabel('knowledge_search'), '检索知识库')
assert.equal(toolLabel('clarify_user'), '补充信息')
assert.equal(toolLabel('unknown_tool'), 'unknown_tool')

// Builds the capture feedback chip state from a capture_thought tool_result.
function captureChipFromToolResult(summary, status = 'ok') {
  if (status === 'error') return null
  return { summary: summary || '已记录，等待你在审核台确认入库。' }
}

assert.deepEqual(captureChipFromToolResult('已记录「季度复盘」，等待你在审核台确认入库。'), {
  summary: '已记录「季度复盘」，等待你在审核台确认入库。',
})
assert.equal(captureChipFromToolResult('', 'error'), null)

console.log('chat-capture.test.mjs OK')
