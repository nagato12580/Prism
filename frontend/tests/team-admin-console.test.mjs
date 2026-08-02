import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const teamAdmin = readFileSync(resolve(root, 'src/features/team/api/teamAdmin.ts'), 'utf8')

assert.match(teamAdmin, /TeamRole/, 'teamAdmin should define a TeamRole type.')
assert.match(teamAdmin, /TeamMemberStatus/, 'teamAdmin should define a TeamMemberStatus type.')
assert.match(teamAdmin, /listMembers/, 'teamAdminApi should expose listMembers.')
assert.match(teamAdmin, /addMember/, 'teamAdminApi should expose addMember.')
assert.match(teamAdmin, /updateMember/, 'teamAdminApi should expose updateMember.')
assert.match(teamAdmin, /removeMember/, 'teamAdminApi should expose removeMember.')
