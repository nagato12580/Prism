import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const chatPage = readFileSync(resolve(root, 'src/pages/ChatPage.tsx'), 'utf8')
const chatStore = readFileSync(resolve(root, 'src/app/chatStore.ts'), 'utf8')

assert.match(
  chatStore,
  /startedAtMs\?: number/,
  'Thinking steps should remember when each stage started so elapsed time can be calculated.',
)

assert.match(
  chatStore,
  /const now = Date\.now\(\)/,
  'Stage updates should capture the current timestamp once per transition.',
)

assert.match(
  chatStore,
  /latencyMs: step\.latencyMs \?\? \(step\.startedAtMs !== undefined \? now - step\.startedAtMs : undefined\)/,
  'Closing a running stage should preserve existing latency or calculate elapsed time from startedAtMs.',
)

assert.match(
  chatStore,
  /startedAtMs: now/,
  'New agent and tool stages should store their start timestamp.',
)

assert.match(
  chatStore,
  /latencyMs: updated\.latencyMs \?\? \(step\.startedAtMs !== undefined \? now - step\.startedAtMs : undefined\)/,
  'Finishing a tool stage should calculate latency when the backend did not provide one.',
)

assert.match(
  chatPage,
  /formatLatency\(stepLatencyMs\(step,\s*nowMs\)\)/,
  'The thinking panel should render stage latencies next to each step.',
)

assert.match(
  chatPage,
  /stepLatencyMs\(step,\s*nowMs\)/,
  'The thinking panel should derive live elapsed time for a running step that has not finished yet.',
)

assert.match(
  chatPage,
  /window\.setInterval\(\(\) => setNowMs\(Date\.now\(\)\),\s*1000\)/,
  'The thinking panel should refresh live stage elapsed time while a timed step is running.',
)
