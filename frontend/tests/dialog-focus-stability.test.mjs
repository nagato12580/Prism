import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const dialogSource = readFileSync(resolve(root, 'src/components/ui/Dialog.tsx'), 'utf8')
const knowledgeIndexSource = readFileSync(resolve(root, 'src/features/knowledge/pages/KnowledgeIndexPage.tsx'), 'utf8')

assert.match(
  dialogSource,
  /const onCloseRef = useRef\(onClose\)/,
  'Dialog should keep the latest onClose in a ref so unstable parent callbacks do not restart focus management.',
)
assert.match(
  dialogSource,
  /if \(e\.key === 'Escape'\) onCloseRef\.current\(\)/,
  'Dialog escape handling should call the latest onClose ref.',
)
assert.match(
  dialogSource,
  /}, \[open\]\)/,
  'Dialog focus management should only run when open changes, not after every input keystroke.',
)
assert.match(
  knowledgeIndexSource,
  /<Dialog open=\{createOpen\}[\s\S]*title="新建知识库"/,
  'Knowledge index should use the shared Dialog for the create knowledge base form.',
)
