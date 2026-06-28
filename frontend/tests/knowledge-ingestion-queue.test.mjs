import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const api = readFileSync(resolve(root, 'src/app/api.ts'), 'utf8')
const page = readFileSync(resolve(root, 'src/pages/KnowledgePage.tsx'), 'utf8')
const retryGovernanceHandler = page.slice(
  page.indexOf('const handleRetryGovernance'),
  page.indexOf('const handleIngestTopic'),
)

assert.match(api, /ingestTopicResources:/)
assert.match(api, /retryGovernance:/)
assert.match(api, /\/governance\/retry/)
assert.match(api, /governance_status/)
assert.match(page, /handleIngestTopic/)
assert.match(page, /handleRetryGovernance/)
assert.match(retryGovernanceHandler, /const topicId = activeTopicId/)
assert.match(retryGovernanceHandler, /activeTopicIdRef\.current !== topicId/)
assert.match(page, /partial-complete/)
assert.match(page, /text-invalid/)
assert.match(page, /governance_progress_current/)
assert.match(page, /onRetryGovernance/)
assert.match(page, /activeTopicIdRef|requestTokenRef|loadResourcesForTopic/)
assert.match(page, /const selectTopic = \(topicId: string \| null\) =>/)
assert.match(page, /onSelect=\{\(\) => selectTopic\(topic\.id\)\}/)
assert.doesNotMatch(page, /legacy-failed/)
assert.doesNotMatch(page, /if \(activeTopicId === topic\.id\)/)
