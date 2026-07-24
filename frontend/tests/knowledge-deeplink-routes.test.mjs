import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')

function read(rel) {
  return readFileSync(resolve(root, rel), 'utf8')
}

const routesSrc = read('src/app/routes.tsx')

test('routes register deep-link knowledge workspace under /knowledge/:kbUid', () => {
  // Nested kb workspace with files/retrieval/graph/governance/mindmap/evaluation/settings
  for (const tab of ['files', 'retrieval', 'graph', 'governance', 'mindmap', 'evaluation', 'settings']) {
    assert.match(routesSrc, new RegExp(`path:\\s*['\"]${tab}['\"]`), `route tab ${tab} must be registered`)
  }
  assert.match(routesSrc, /path:\s*['"]:kbUid['"]/)
  // Index redirect of selected KB lands on files (no global tab store).
  assert.match(routesSrc, /Navigate to=["']files["']/)
})

test('the legacy /knowledge index page is preserved as the KB list', () => {
  // The index route must still render a knowledge listing page.
  assert.match(routesSrc, /path:\s*['"]knowledge['"]/)
})

test('KnowledgeShell reads kbUid from params and renders an Outlet', () => {
  const shell = read('src/features/knowledge/components/KnowledgeShell.tsx')
  assert.match(shell, /useParams/)
  assert.match(shell, /kbUid/)
  assert.match(shell, /<Outlet/)
})

test('workspace store keeps only transient selections keyed by kbUid', () => {
  const store = read('src/features/knowledge/stores/knowledgeWorkspaceStore.ts')
  // Transient selections keyed by kbUid; no persisted sensitive data.
  assert.match(store, /selectedFileUids/)
  assert.match(store, /drawerByKb/)
  // The store must NOT persist tokens/evidence/secrets.
  assert.doesNotMatch(store, /localStorage/)
  assert.doesNotMatch(store, /persist/)
  assert.doesNotMatch(store, /sessionStorage/)
})

test('knowledge deep-link pages exist and expose a data-testid for restoration', () => {
  for (const tab of ['files', 'retrieval', 'graph', 'governance', 'mindmap', 'evaluation', 'settings']) {
    const page = read(`src/features/knowledge/pages/Knowledge${capitalize(tab)}Page.tsx`)
    assert.match(
      page,
      new RegExp(`data-testid=["']knowledge-${tab}-page["']`),
      `page ${tab} must expose data-testid knowledge-${tab}-page`,
    )
  }
})

function capitalize(s) {
  return s.charAt(0).toUpperCase() + s.slice(1)
}
