import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { dirname, join, resolve } from 'node:path'
import { execFileSync } from 'node:child_process'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const helperSource = 'src/app/latestRequest.ts'
const tsc = resolve(root, 'node_modules/typescript/bin/tsc')

async function loadHelper() {
  const outDir = mkdtempSync(join(tmpdir(), 'prism-latest-request-'))
  try {
    execFileSync(
      process.execPath,
      [
        tsc,
        helperSource,
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
    const moduleUrl = pathToFileURL(resolve(outDir, 'latestRequest.js')).href
    return await import(moduleUrl)
  } finally {
    rmSync(outDir, { recursive: true, force: true })
  }
}

function deferred() {
  let resolvePromise
  let rejectPromise
  const promise = new Promise((resolve, reject) => {
    resolvePromise = resolve
    rejectPromise = reject
  })
  return { promise, resolve: resolvePromise, reject: rejectPromise }
}

test('createLatestRequestRunner ignores stale successes and only finalizes the newest request', async () => {
  const { createLatestRequestRunner } = await loadHelper()
  const runner = createLatestRequestRunner()
  const first = deferred()
  const second = deferred()
  const events = []

  const firstRun = runner.run(
    () => first.promise,
    {
      onStart: () => events.push('start:first'),
      onSuccess: (value) => events.push(`success:first:${value}`),
      onError: (error) => events.push(`error:first:${String(error)}`),
      onFinally: () => events.push('finally:first'),
    },
  )

  const secondRun = runner.run(
    () => second.promise,
    {
      onStart: () => events.push('start:second'),
      onSuccess: (value) => events.push(`success:second:${value}`),
      onError: (error) => events.push(`error:second:${String(error)}`),
      onFinally: () => events.push('finally:second'),
    },
  )

  first.resolve('stale')
  await firstRun
  assert.deepEqual(events, ['start:first', 'start:second'], 'stale request should not update success or loading state')

  second.resolve('fresh')
  await secondRun
  assert.deepEqual(events, ['start:first', 'start:second', 'success:second:fresh', 'finally:second'])
  assert.equal(runner.currentRequestId(), 2)
})

test('createLatestRequestRunner ignores stale errors after a newer request starts', async () => {
  const { createLatestRequestRunner } = await loadHelper()
  const runner = createLatestRequestRunner()
  const first = deferred()
  const second = deferred()
  const events = []

  const firstRun = runner.run(
    () => first.promise,
    {
      onStart: () => events.push('start:first'),
      onSuccess: () => events.push('success:first'),
      onError: (error) => events.push(`error:first:${String(error)}`),
      onFinally: () => events.push('finally:first'),
    },
  )

  const secondRun = runner.run(
    () => second.promise,
    {
      onStart: () => events.push('start:second'),
      onSuccess: (value) => events.push(`success:second:${value}`),
      onError: (error) => events.push(`error:second:${String(error)}`),
      onFinally: () => events.push('finally:second'),
    },
  )

  first.reject(new Error('stale failure'))
  await firstRun
  assert.deepEqual(events, ['start:first', 'start:second'], 'stale request errors should stay suppressed')

  second.resolve('fresh')
  await secondRun
  assert.deepEqual(events, ['start:first', 'start:second', 'success:second:fresh', 'finally:second'])
})
