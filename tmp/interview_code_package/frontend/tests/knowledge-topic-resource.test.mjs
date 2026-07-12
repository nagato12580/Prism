import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const api = readFileSync(resolve(root, 'src/app/api.ts'), 'utf8')
const page = readFileSync(resolve(root, 'src/pages/KnowledgePage.tsx'), 'utf8')

assert.match(api, /interface KnowledgeTopic/, 'API client exposes KnowledgeTopic type.')
assert.match(api, /interface KnowledgeResource/, 'API client exposes KnowledgeResource type.')
assert.match(api, /listTopics:/, 'API client lists topics.')
assert.match(api, /uploadResource:/, 'API client uploads resources into a topic.')
assert.match(page, /data-testid="knowledge-topic-sidebar"/, 'Knowledge page renders a topic sidebar.')
assert.match(page, /data-testid="knowledge-resource-filter"/, 'Knowledge page renders media type filters.')
assert.match(page, /duplicate_resource_in_topic/, 'Knowledge page maps duplicate upload errors.')
