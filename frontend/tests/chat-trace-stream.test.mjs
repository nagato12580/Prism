import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const api = readFileSync(resolve(root, 'src/app/api.ts'), 'utf8')
const chatPage = readFileSync(resolve(root, 'src/pages/ChatPage.tsx'), 'utf8')
const chatStore = readFileSync(resolve(root, 'src/app/chatStore.ts'), 'utf8')

const traceStreamFixture = [
  '{"type":"trace","data":{"trace_id":"trace-1"}}',
  '{"type":"tool_call","data":{"tool":"raw_document_search","query":"q"}}',
  '{"type":"tool_result","data":{"tool":"raw_document_search","status":"success","summary":"found","evidence_items":[{"evidence_id":"document_chunk:c1","chunk_id":"c1","excerpt":"text"}]}}',
  '{"type":"token","data":"answer"}',
  '{"type":"done"}',
].join('\n')

assert.match(traceStreamFixture, /"type":"trace"/, 'Fixture should include the trace stream event.')
assert.match(traceStreamFixture, /"evidence_items"/, 'Fixture should include tool evidence items.')

assert.match(api, /export interface TraceBindRequest\s*{[\s\S]*session_id:\s*string[\s\S]*assistant_message_id:\s*string[\s\S]*}/)
assert.match(api, /export interface TraceBindResponse\s*{[\s\S]*trace_id:\s*string[\s\S]*status:\s*string[\s\S]*}/)
assert.match(api, /export const traceApi\s*=\s*{[\s\S]*bindMessage:\s*\(traceId:\s*string,\s*data:\s*TraceBindRequest\)[\s\S]*\/traces\/\$\{traceId\}\/bind-message[\s\S]*exportTrace:\s*\(traceId:\s*string\)[\s\S]*\/traces\/\$\{traceId\}\/export/)

assert.match(chatStore, /export interface EvidenceItem\s*{[\s\S]*evidence_id:\s*string[\s\S]*chunk_id\?:\s*string[\s\S]*metadata\?:\s*Record<string,\s*unknown>[\s\S]*}/)
assert.match(chatStore, /evidenceItems\?:\s*EvidenceItem\[]/, 'Tool runs should store normalized evidence items.')
assert.match(chatStore, /traceId\?:\s*string/, 'Messages should keep the engine trace id.')
assert.match(chatStore, /export function normalizeEvidenceItems\(value:\s*unknown\):\s*EvidenceItem\[] \| undefined/, 'Evidence normalizer should be exported.')
assert.match(chatStore, /normalizeEvidenceItems\(run\.evidenceItems \?\? run\.evidence_items\)/, 'Persisted tool runs should restore evidence items.')
assert.match(chatStore, /const traceId = typeof process\?\.trace_id === 'string' \? process\.trace_id : undefined[\s\S]*traceId,/, 'Persisted messages should restore process.trace_id.')
assert.match(chatStore, /setLastTraceId:\s*\(traceId:\s*string,\s*sessionId\?:\s*string,\s*messageId\?:\s*string\)\s*=>\s*void/)

assert.match(chatPage, /traceApi/, 'ChatPage should import and use traceApi.')
assert.match(chatPage, /normalizeEvidenceItems/, 'ChatPage should import and use normalizeEvidenceItems.')
assert.match(chatPage, /trace_id:\s*message\.traceId \|\| null/, 'Assistant process snapshots should include trace_id.')
assert.match(chatPage, /let traceId:\s*string \| null = null/, 'send should track the current stream trace id.')
assert.match(chatPage, /if \(msg\.type === 'trace'\)\s*{[\s\S]*traceId = safeString\(msg\.data\?\.trace_id\)[\s\S]*setLastTraceId\(traceId,\s*sessionId,\s*assistantMessageId\)[\s\S]*persistAssistantProcessSnapshot\(sessionId,\s*assistantPersistedId\)/, 'Trace stream events should update state and process snapshots.')
assert.match(chatPage, /evidenceItems:\s*normalizeEvidenceItems\(msg\.data\?\.evidence_items\)/, 'Tool results should persist normalized evidence items.')
assert.match(chatPage, /session_id:\s*sessionId/, 'Engine answer requests should include session_id.')
assert.match(chatPage, /user_message_id:\s*userMessageId/, 'Engine answer requests should include user_message_id.')
assert.match(chatPage, /traceApi\.bindMessage\(traceId,\s*{[\s\S]*session_id:\s*sessionId[\s\S]*assistant_message_id:\s*assistantPersistedId[\s\S]*}\)\.catch\(\(\) => {}\)/, 'Completed assistant messages should be bound to their trace.')
