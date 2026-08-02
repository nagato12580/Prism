import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const api = readFileSync(resolve(root, 'src/features/knowledge/api/knowledgeBases.ts'), 'utf8')
const indexPage = readFileSync(resolve(root, 'src/features/knowledge/pages/KnowledgeIndexPage.tsx'), 'utf8')

assert.match(api, /governance_status:\s*KnowledgeGovernanceStatus/, 'KnowledgeBase should expose governance_status.')
assert.match(api, /can_contribute:\s*boolean/, 'KnowledgeBase should expose can_contribute.')
assert.match(api, /requestTransfer/, 'API should include transfer request action.')
assert.match(api, /acceptTransfer/, 'API should include admin accept transfer action.')
assert.match(api, /updateMember/, 'API should include member role update action.')

assert.match(indexPage, /我的个人库/, 'Knowledge index should show a personal libraries section.')
assert.match(indexPage, /提交中/, 'Knowledge index should show pending transfer libraries.')
assert.match(indexPage, /团队库/, 'Knowledge index should show managed team libraries.')
assert.match(indexPage, /can_delete/, 'Delete affordance should be capability-driven.')
assert.match(indexPage, /requestTransfer/, 'Personal libraries should expose transfer request action.')
assert.match(indexPage, /withdrawTransfer/, 'Pending transfer libraries should expose withdraw action.')

const shell = readFileSync(resolve(root, 'src/features/knowledge/components/KnowledgeShell.tsx'), 'utf8')

assert.match(shell, /can_manage_members/, 'Knowledge shell should expose member management by capability.')
assert.match(shell, /KnowledgeMembersPanel/, 'Knowledge shell should render a members panel.')
assert.match(shell, /my_role/, 'Knowledge shell should display or use the current user role.')
