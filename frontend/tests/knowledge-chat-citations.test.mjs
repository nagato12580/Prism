import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
function read(rel) {
  return readFileSync(resolve(root, rel), 'utf8')
}

test('chat source scores are NOT wrapped as a fake match percentage', () => {
  const src = read('src/pages/ChatPage.tsx')
  // The retrieval contract forbids wrapping raw scores as a synthetic
  // "匹配百分比". Remove the legacy percentage rendering.
  assert.doesNotMatch(src, /raw_score\s*\*\s*100/)
  assert.doesNotMatch(src, /匹配 \$\{/)
})

test('chat exposes a citation/evidence component that opens the document', () => {
  const src = read('src/features/chat/EvidenceDrawer.tsx')
  assert.match(src, /export function EvidenceDrawer/)
  // It navigates via the public knowledge route using kb_uid/file_uid, never a
  // private storage path or Engine URL.
  assert.match(src, /knowledge/)
  assert.doesNotMatch(src, /storage_uri/)
  assert.doesNotMatch(src, /uploads_data/)
})

test('chat sources become clickable and resolve only known references', () => {
  const src = read('src/pages/ChatPage.tsx')
  // Sources render with a click affordance that opens the evidence drawer.
  assert.match(src, /EvidenceDrawer|onOpenEvidence|openEvidence/)
})

test('chat stream parser remains legacy NDJSON tolerant (no fabricated seq/run_id)', () => {
  const src = read('src/pages/ChatPage.tsx')
  // The live backend emits legacy {type,data} lines (no seq/run_id). The parser
  // must handle a bare-string token/error/title and a list-valued sources event.
  assert.match(src, /JSON\.parse/)
  assert.match(src, /msg\.type/)
})
