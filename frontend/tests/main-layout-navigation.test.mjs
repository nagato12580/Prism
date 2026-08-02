import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const mainLayout = readFileSync(resolve(root, 'src/layouts/MainLayout.tsx'), 'utf8')
const routes = readFileSync(resolve(root, 'src/app/routes.tsx'), 'utf8')

assert.doesNotMatch(
  mainLayout,
  /to=['"]\/wiki['"]/,
  'Main navigation should not expose the Wiki module while it is disabled.',
)

assert.doesNotMatch(
  mainLayout,
  /label=['"]Wiki['"]|label:\s*['"]Wiki['"]/,
  'Main navigation should not render a Wiki label while the module is disabled.',
)

assert.match(
  mainLayout,
  /to:\s*['"]\/records\/review['"][\s\S]*label:\s*['"]记录审核['"]/,
  'Main navigation should expose record review under the records section.',
)

assert.match(
  mainLayout,
  /to:\s*['"]\/records\/merge['"][\s\S]*label:\s*['"]记录合并['"]/,
  'Main navigation should expose record merge under the records section.',
)

assert.doesNotMatch(
  mainLayout,
  /to:\s*['"]\/review['"]|to=['"]\/review['"]|to:\s*['"]\/assets['"]|to=['"]\/assets['"]/,
  'Main navigation should use the records routes instead of top-level review/assets routes.',
)

assert.match(
  routes,
  /path:\s*['"]records['"][\s\S]*path:\s*['"]review['"][\s\S]*<InboxPage \/>[\s\S]*path:\s*['"]merge['"][\s\S]*<AssetsPage \/>/,
  'Routes should group review and merge pages under /records.',
)

assert.match(
  routes,
  /path:\s*['"]review['"][\s\S]*<Navigate to=['"]\/records\/review['"] replace \/>[\s\S]*path:\s*['"]assets['"][\s\S]*<Navigate to=['"]\/records\/merge['"] replace \/>/,
  'Legacy review/assets routes should redirect to the records routes.',
)
