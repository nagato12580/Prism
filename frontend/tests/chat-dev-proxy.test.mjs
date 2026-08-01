import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')

test('chat answer dev proxy goes through backend authorization proxy', () => {
  const config = readFileSync(resolve(root, 'vite.config.ts'), 'utf8')
  const nginx = readFileSync(resolve(root, '../docker/nginx/default.conf'), 'utf8')
  const chatProxyLine = config
    .split(/\r?\n/)
    .find((line) => line.includes("'/api/v1/chat/answer'"))

  assert.ok(chatProxyLine, 'vite config must define an explicit chat answer proxy')
  assert.match(chatProxyLine, /127\.0\.0\.1:5175/)
  assert.doesNotMatch(chatProxyLine, /127\.0\.0\.1:5180/)
  assert.match(
    nginx,
    /location = \/api\/v1\/chat\/answer \{[^}]*backend:5175/,
    'production nginx must route chat answer through backend authorization proxy',
  )
  assert.doesNotMatch(
    nginx,
    /location = \/api\/v1\/chat\/answer \{[^}]*engine:5180/,
    'production nginx must not bypass the backend authorization proxy for chat answer',
  )
})
