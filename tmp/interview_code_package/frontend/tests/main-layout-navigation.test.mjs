import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import assert from 'node:assert/strict'

const root = resolve(import.meta.dirname, '..')
const mainLayout = readFileSync(resolve(root, 'src/layouts/MainLayout.tsx'), 'utf8')

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
