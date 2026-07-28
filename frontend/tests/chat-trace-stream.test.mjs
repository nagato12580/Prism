import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const api = readFileSync(resolve(root, 'src/app/api.ts'), 'utf8')
const chatPage = readFileSync(resolve(root, 'src/pages/ChatPage.tsx'), 'utf8')
const chatRequestPayload = readFileSync(resolve(root, 'src/pages/chatRequestPayload.ts'), 'utf8')
const chatStore = readFileSync(resolve(root, 'src/app/chatStore.ts'), 'utf8')
const graphRagHelper = readFileSync(resolve(root, 'src/app/graphrag.ts'), 'utf8')

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
assert.match(api, /export interface GraphRagExplain\s*{[\s\S]*why:\s*string[\s\S]*evidence_type:\s*'EXTRACTED' \| 'INFERRED'[\s\S]*source_marker\?:\s*string[\s\S]*}/, 'API models should type GraphRAG explanations.')
assert.match(api, /export interface GraphRagPathStep\s*{[\s\S]*label\?:\s*string[\s\S]*edge_type\?:\s*string[\s\S]*node_id\?:\s*string[\s\S]*}/, 'API models should type graph path steps.')
assert.match(api, /export interface GraphRagPathRoute\s*{[\s\S]*source_marker\?:\s*string[\s\S]*matched_entity_ids\?:\s*string\[][\s\S]*steps:\s*GraphRagPathStep\[][\s\S]*}/, 'API models should type graph path routes.')
assert.match(api, /export type GraphRagPathEntry = GraphRagPathStep \| GraphRagPathRoute/, 'API models should expose the graph path entry union.')
assert.match(api, /export interface GraphRagPayload\s*{[\s\S]*source:\s*{[\s\S]*source_kind:\s*string[\s\S]*source_id:\s*string[\s\S]*item_id\?:\s*string \| null[\s\S]*chunk_id\?:\s*string \| null[\s\S]*display_title\?:\s*string[\s\S]*}[\s\S]*path:\s*GraphRagPathEntry\[][\s\S]*explain:\s*GraphRagExplain[\s\S]*}/, 'API models should type GraphRAG payloads with structured graph paths.')
assert.match(api, /export const traceApi\s*=\s*{[\s\S]*bindMessage:\s*\(traceId:\s*string,\s*data:\s*TraceBindRequest\)[\s\S]*\/traces\/\$\{traceId\}\/bind-message[\s\S]*exportTrace:\s*\(traceId:\s*string\)[\s\S]*\/traces\/\$\{traceId\}\/export/)

assert.match(chatStore, /export interface EvidenceItem\s*{[\s\S]*evidence_id:\s*string[\s\S]*chunk_id\?:\s*string[\s\S]*metadata\?:\s*Record<string,\s*unknown>[\s\S]*}/)
assert.match(chatStore, /evidenceItems\?:\s*EvidenceItem\[]/, 'Tool runs should store normalized evidence items.')
assert.match(chatStore, /traceId\?:\s*string/, 'Messages should keep the engine trace id.')
assert.match(chatStore, /export function normalizeEvidenceItems\(value:\s*unknown\):\s*EvidenceItem\[] \| undefined/, 'Evidence normalizer should be exported.')
assert.match(chatStore, /normalizeEvidenceItems\(run\.evidenceItems \?\? run\.evidence_items\)/, 'Persisted tool runs should restore evidence items.')
assert.match(chatStore, /graph_path:\s*Array\.isArray\(item\.metadata\.graph_path\)\s*\?\s*item\.metadata\.graph_path\s*:\s*undefined/, 'Evidence metadata should retain graph_path arrays during restore.')
assert.match(chatStore, /graph_explain:\s*isPlainRecord\(item\.metadata\.graph_explain\)\s*\?\s*item\.metadata\.graph_explain\s*:\s*undefined/, 'Evidence metadata should retain graph_explain objects during restore.')
assert.match(chatStore, /evidence_type:\s*typeof item\.metadata\.evidence_type === 'string'\s*\?\s*item\.metadata\.evidence_type\s*:\s*undefined/, 'Evidence metadata should retain evidence_type during restore.')
assert.match(chatStore, /const traceId = typeof process\?\.trace_id === 'string' \? process\.trace_id : undefined[\s\S]*traceId,/, 'Persisted messages should restore process.trace_id.')
assert.match(chatStore, /setLastTraceId:\s*\(traceId:\s*string,\s*sessionId\?:\s*string,\s*messageId\?:\s*string\)\s*=>\s*void/)

assert.match(chatPage, /traceApi/, 'ChatPage should import and use traceApi.')
assert.match(chatPage, /normalizeEvidenceItems/, 'ChatPage should import and use normalizeEvidenceItems.')
assert.match(chatPage, /trace_id:\s*message\.traceId \|\| null/, 'Assistant process snapshots should include trace_id.')
assert.match(chatPage, /let traceId:\s*string \| null = null/, 'send should track the current stream trace id.')
assert.match(chatPage, /processPersistenceQueuesRef/, 'Assistant process persistence should keep per-message ordering state.')
assert.match(chatPage, /queueAssistantProcessSnapshot/, 'Stream process snapshots should be queued instead of fire-and-forget.')
assert.match(chatPage, /flushAssistantProcessSnapshot/, 'Final assistant persistence should wait for or supersede queued snapshots.')
assert.match(chatPage, /graph_explain/, 'ChatPage should read graph explanation metadata.')
assert.match(chatPage, /graph_path/, 'ChatPage should read graph path metadata.')
assert.match(chatPage, /evidence_type/, 'ChatPage should surface evidence type metadata.')
assert.match(chatPage, /GraphRagPathEntry/, 'ChatPage should consume structured graph path types.')
assert.match(chatPage, /graphPathLabels/, 'ChatPage should use the shared graph path label helper.')
assert.match(chatPage, /formatEvidenceTypeLabel|evidenceTypeLabel/, 'ChatPage should use the shared evidence type vocabulary helper.')
assert.match(graphRagHelper, /图推断|\\u56fe\\u63a8\\u65ad|Graph inference/, 'Shared helper should expose the inferred-evidence label.')
assert.match(graphRagHelper, /直接证据|\\u76f4\\u63a5\\u8bc1\\u636e|Direct evidence/, 'Shared helper should expose the direct-evidence label.')
assert.match(chatPage, /if \(msg\.type === 'trace'\)\s*{[\s\S]*traceId = safeString\(msg\.data\?\.trace_id\)[\s\S]*setLastTraceId\(traceId,\s*sessionId,\s*assistantMessageId\)[\s\S]*queueAssistantProcessSnapshot\(sessionId,\s*assistantPersistedId\)/, 'Trace stream events should update state and queue process snapshots.')
assert.match(chatPage, /evidenceItems:\s*normalizeEvidenceItems\(msg\.data\?\.evidence_items\)/, 'Tool results should persist normalized evidence items.')
assert.match(chatPage, /session_id:\s*sessionId/, 'Engine answer requests should include session_id.')
assert.match(chatPage, /let engineUserMessageId = userMessageId/, 'Engine user id should start with the optimistic id as fallback.')
assert.match(chatPage, /const persistedUserMessage = await userPersistPromise[\s\S]*replaceMessageId\(sessionId,\s*userMessageId,\s*persistedUserMessage\.id\)[\s\S]*engineUserMessageId = persistedUserMessage\.id/, 'User persistence should update local state and engine id before answering.')
assert.match(chatPage, /body:\s*JSON\.stringify\(buildChatRequestPayload\(\{[\s\S]*engineUserMessageId[\s\S]*\}\)\)/, 'Engine answer requests should be built through the production payload helper with the current engine user id.')
assert.match(chatRequestPayload, /user_message_id:\s*engineUserMessageId/, 'The production payload helper should serialize the persisted user_message_id when available.')
assert.match(chatPage, /await flushAssistantProcessSnapshot\(sessionId,\s*assistantPersistedId\)/, 'Final assistant persistence should wait for queued process snapshots before returning.')
assert.match(chatPage, /await traceApi\.bindMessage\(traceId,\s*{[\s\S]*session_id:\s*sessionId[\s\S]*assistant_message_id:\s*assistantPersistedId[\s\S]*}\)/, 'Completed assistant messages should be bound to their trace after final persistence.')

assert.match(chatStore, /const normalizedScore = typeof item\.score === 'number'\s*\? item\.score\s*:\s*typeof item\.score === 'string'\s*\? Number\(item\.score\)\s*:\s*NaN/, 'Evidence score strings should be coerced to numbers.')
assert.match(chatStore, /metadata: isPlainRecord\(item\.metadata\)/, 'Evidence metadata should accept only plain object records.')

async function runLatestProcessWinsSimulation() {
  const writes = []
  let latest = null
  let running = null

  const queue = (snapshot, delay) => {
    latest = { snapshot, delay }
    if (!running) {
      running = (async () => {
        while (latest) {
          const pending = latest
          latest = null
          await new Promise((resolve) => setTimeout(resolve, pending.delay))
          writes.push(pending.snapshot)
        }
        running = null
      })()
    }
    return running
  }

  queue({ step: 'early' }, 20)
  queue({ step: 'final', trace_id: 'trace-1', evidenceItems: [{ evidence_id: 'e1' }] }, 1)
  await running
  assert.deepEqual(writes.at(-1), { step: 'final', trace_id: 'trace-1', evidenceItems: [{ evidence_id: 'e1' }] })
}

await runLatestProcessWinsSimulation()
