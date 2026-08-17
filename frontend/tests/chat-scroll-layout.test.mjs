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

assert.match(
  chatPage,
  /grid h-full min-h-0 w-full grid-rows-\[auto_minmax\(0,1fr\)\][\s\S]*lg:grid-cols-\[280px_minmax\(0,1fr\)\]/,
  'Chat page should be single-column on mobile while preserving the desktop two-column grid.'
)

assert.match(
  chatPage,
  /data-scroll-region="conversation-list"[\s\S]*overflow-x-auto[\s\S]*overflow-y-hidden[\s\S]*lg:overflow-x-hidden[\s\S]*lg:overflow-y-auto/,
  'Conversation list should scroll horizontally on mobile and vertically on desktop.'
)

assert.match(
  chatPage,
  /className="flex min-w-max gap-2 lg:block lg:min-w-0 lg:space-y-2"/,
  'Session list should render as a horizontal strip on mobile and a vertical list on desktop.'
)

assert.match(
  chatPage,
  /flex w-full min-w-0 flex-wrap items-center gap-2 border-t[\s\S]*sm:flex-nowrap/,
  'Input toolbar should wrap on mobile and stay unwrapped on larger screens.'
)

assert.match(
  chatPage,
  /grid h-full min-h-0 w-full[\s\S]*overflow-hidden/,
  'Chat page root should clip horizontal overflow on mobile.'
)

assert.match(
  chatPage,
  /data-mobile-conversation-strip/,
  'Mobile conversation strip should render a visible horizontal scrollbar rail.'
)

assert.match(
  chatPage,
  /data-scroll-region="message-list"[\s\S]*w-full[\s\S]*overflow-x-hidden/,
  'Message list should stay inside the mobile viewport width.'
)

assert.match(
  chatPage,
  /className=\{cn\('flex min-w-0 w-full overflow-hidden'/,
  'Each message row should be constrained to the chat viewport.'
)

assert.match(
  chatPage,
  /max-w-\[min\(100%,42rem\)\]/,
  'Message bubbles should cap width to their parent on mobile.'
)

assert.match(
  chatPage,
  /className="w-full min-w-0 shrink-0 bg-white\/90/,
  'Input form should not overflow the mobile viewport.'
)

assert.match(
  chatPage,
  /flex w-full min-w-0 flex-wrap items-center/,
  'Input toolbar should constrain controls to the available mobile width.'
)
