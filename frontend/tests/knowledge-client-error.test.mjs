import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { dirname, join, resolve } from 'node:path'
import { execFileSync } from 'node:child_process'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tsc = resolve(root, 'node_modules/typescript/bin/tsc')

async function loadClient() {
  // client.ts imports contracts.ts. tsc with bundler resolution omits the .js
  // extension in output, which Node ESM cannot resolve, so compile both and
  // rewrite the bare specifier to an explicit .js extension.
  const outDir = mkdtempSync(join(tmpdir(), 'prism-kb-client-'))
  try {
    execFileSync(
      process.execPath,
      [
        tsc,
        'src/features/knowledge/api/client.ts',
        'src/features/knowledge/api/contracts.ts',
        '--module',
        'ESNext',
        '--target',
        'ES2020',
        '--moduleResolution',
        'bundler',
        '--outDir',
        outDir,
      ],
      { cwd: root, stdio: 'pipe' },
    )
    const clientPath = resolve(outDir, 'client.js')
    let src = readFileSync(clientPath, 'utf8')
    src = src.replace(/from\s+["']\.\/contracts["']/g, "from './contracts.js'")
    writeFileSync(clientPath, src)
    const moduleUrl = pathToFileURL(clientPath).href
    return await import(moduleUrl)
  } finally {
    rmSync(outDir, { recursive: true, force: true })
  }
}

function jsonResponse(body, status, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

test('requestJSON preserves typed error state, retryability and trace id', async () => {
  const { requestJSON, ApiProblem } = await loadClient()
  globalThis.fetch = () =>
    Promise.resolve(
      jsonResponse(
        {
          error: {
            code: 'RETRIEVAL_UNAVAILABLE',
            message: 'down',
            retryable: true,
            trace_id: 'trace-1',
            details: { channel: 'dense' },
          },
        },
        503,
      ),
    )
  await assert.rejects(
    () => requestJSON('/knowledge-bases/kb-a/retrieval/query', { method: 'POST' }),
    (err) => {
      assert.ok(err instanceof ApiProblem, 'should be ApiProblem')
      assert.equal(err.code, 'RETRIEVAL_UNAVAILABLE')
      assert.equal(err.retryable, true)
      assert.equal(err.traceId, 'trace-1')
      assert.equal(err.status, 503)
      return true
    },
  )
})

test('requestJSON maps legacy {detail} bodies to a readable problem', async () => {
  const { requestJSON, ApiProblem } = await loadClient()
  globalThis.fetch = () =>
    Promise.resolve(jsonResponse({ detail: { code: 'duplicate_topic_name', message: '重名' } }, 409))
  await assert.rejects(
    () => requestJSON('/knowledge-bases', { method: 'POST' }),
    (err) => {
      assert.equal(err.code, 'duplicate_topic_name')
      assert.equal(err.status, 409)
      assert.equal(err.retryable, false)
      return true
    },
  )
})

test('requestJSON returns undefined for 204', async () => {
  const { requestJSON } = await loadClient()
  globalThis.fetch = () => Promise.resolve(new Response(null, { status: 204 }))
  const result = await requestJSON('/x')
  assert.equal(result, undefined)
})

test('isAccessError flags 403 and 404 only', async () => {
  const { ApiProblem } = await loadClient()
  assert.equal(new ApiProblem(403, 'X', 'm').isAccessError(), true)
  assert.equal(new ApiProblem(404, 'X', 'm').isAccessError(), true)
  assert.equal(new ApiProblem(503, 'X', 'm').isAccessError(), false)
})
