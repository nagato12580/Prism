import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const chatPage = readFileSync(resolve(root, 'src/pages/ChatPage.tsx'), 'utf8')

assert.match(
  chatPage,
  /onClarifySelect\(option\.label\.trim\(\) \|\| option\.value\)/,
  'Clarify option clicks should send only the selected option text, not the assistant question.'
)

assert.match(
  chatPage,
  /function historyContent\(message: Message\)[\s\S]*message\.clarify\.question/,
  'History serialization should include the assistant clarify question for follow-up turns.'
)

assert.match(
  chatPage,
  /knowledge_search:\s*'检索知识库'/,
  'knowledge_search should render as a user-friendly tool label.'
)

assert.match(
  chatPage,
  /chat:\s*'闲聊'/,
  'chat status should have a user-friendly label for normal conversation.'
)
