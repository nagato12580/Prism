import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const mainLayout = readFileSync(resolve(root, 'src/layouts/MainLayout.tsx'), 'utf8')
const chatPage = readFileSync(resolve(root, 'src/pages/ChatPage.tsx'), 'utf8')

assert.match(
  mainLayout,
  /const isChatRoute =/,
  'MainLayout should detect the chat route so chat can own its internal scrolling.'
)

assert.match(
  mainLayout,
  /isChatRoute[\s\S]*overflow-hidden/,
  'Chat route should lock outer page scrolling with overflow-hidden.'
)

assert.match(
  chatPage,
  /data-scroll-region="conversation-list"[\s\S]*overflow-y-auto/,
  'Conversation list should be its own vertical scroll region.'
)

assert.match(
  chatPage,
  /data-scroll-region="message-list"[\s\S]*overflow-y-auto/,
  'Message list should be its own vertical scroll region.'
)
