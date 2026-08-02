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

const routes = readFileSync(resolve(root, 'src/app/routes.tsx'), 'utf8')
const layout = readFileSync(resolve(root, 'src/layouts/MainLayout.tsx'), 'utf8')
const page = readFileSync(resolve(root, 'src/features/team/pages/TeamAdminPage.tsx'), 'utf8')
const transfersTab = readFileSync(resolve(root, 'src/features/team/pages/TransfersReviewTab.tsx'), 'utf8')
const kbsTab = readFileSync(resolve(root, 'src/features/team/pages/TeamKbsTab.tsx'), 'utf8')
const membersTab = readFileSync(resolve(root, 'src/features/team/pages/TeamMembersTab.tsx'), 'utf8')

assert.match(routes, /team\/admin/, 'routes should define the team admin route.')
assert.match(layout, /团队管理/, 'MainLayout should show a team management nav entry.')
assert.match(page, /待接收/, 'TeamAdminPage should show the transfers review tab.')
assert.match(page, /团队库授权/, 'TeamAdminPage should show the team KBs tab.')
assert.match(page, /成员管理/, 'TeamAdminPage should show the members tab.')
assert.match(transfersTab, /listTransferRequests/, 'Transfers tab should call listTransferRequests.')
assert.match(transfersTab, /acceptTransfer/, 'Transfers tab should call acceptTransfer.')
assert.match(transfersTab, /rejectTransfer/, 'Transfers tab should call rejectTransfer.')
assert.match(kbsTab, /KnowledgeMembersPanel/, 'Team KBs tab should reuse the members panel.')
assert.match(membersTab, /teamAdminApi\.listMembers/, 'Members tab should list team members.')
assert.match(membersTab, /teamAdminApi\.addMember/, 'Members tab should add members.')
assert.match(membersTab, /teamAdminApi\.updateMember/, 'Members tab should update members.')
assert.match(membersTab, /teamAdminApi\.removeMember/, 'Members tab should remove members.')
