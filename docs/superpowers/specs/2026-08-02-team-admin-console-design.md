# 团队管理控制台设计

Date: 2026-08-02

## 背景

团队知识库 RBAC 已合入 `codex/knowledge-system-full`：后端具备治理状态机（`personal → pending_transfer → managed`）、库级角色（`viewer/contributor/editor/manager`）、团队角色（`admin/member`），以及完整的 transfer/members 后端 API 和前端 API 方法。但**管理员操作界面缺失**：`listTransferRequests`/`acceptTransfer`/`rejectTransfer` 等前端方法全是死代码，用户实际看不到任何可以执行接收/拒绝/成员授权的控制台。

本设计新增一个「团队管理」管理员控制台，覆盖设计文档要求的完整三块能力：

1. **待接收审核**：列出 `pending_transfer` 库，接收/拒绝。
2. **团队库授权**：给任意团队库添加/改/删成员角色。
3. **成员管理**：管理团队成员角色（`admin/member`）与状态（`active/disabled`）。

## 目标行为

- 管理员可以在一个页面完成"接收团队库 → 授权成员 → 管理团队成员"的完整治理流程。
- 非管理员看到入口但进入后收到 403，前端降级为"无权访问"。
- 团队成员管理是完整 CRUD，带"至少保留一个 admin"和"不能操作自己"的保护。

## 架构

```
侧边导航「管理」分组
   └─ 团队管理 (/team/admin) → TeamAdminPage
         ├─ 标签页 1「待接收审核」→ TransfersReviewTab
         ├─ 标签页 2「团队库授权」→ TeamKbsTab
         └─ 标签页 3「成员管理」→ TeamMembersTab
```

后端保持单一授权边界：所有 `/team/admin/*` 路由用现有 `KnowledgeAccessPolicy.is_team_admin(actor)` 守卫。前端只渲染能力，不自行推导权限。

## 后端

### 新增路由组 `backend/app/api/team_admin.py`

router prefix `/team/admin`，全部路由先调用 `KnowledgeAccessPolicy.is_team_admin(actor)`，非 admin 抛 `ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", "Admin access required")`。

| 路由 | 行为 |
|---|---|
| `GET /members` | 列当前租户所有 `team_member`，返回 `{items, total}` |
| `POST /members` | 添加成员。body `{user_id, role, status?}`。角色校验 `TeamRole`，status 校验 `active/disabled`（默认 active）。租户内已存在则 409 |
| `PUT /members/{user_id}` | 改角色/状态。body `{role?, status?}`。自我保护见下 |
| `DELETE /members/{user_id}` | 移除成员。自我保护见下 |

成员 CRUD 逻辑放 service（建议放 `backend/app/services/knowledge_rbac.py` 或新建 `team_members.py`），含事务与审计日志（复用 `KnowledgeAccessAuditLog`，action 如 `team_member.add` / `team_member.update` / `team_member.remove`）。

### 保护规则

- **不能操作自己**：`PUT`/`DELETE` 目标是 `actor.actor_id` 时抛 409（`SELF_OPERATION_DENIED`）。
- **至少保留一个 admin**：`PUT` 将 admin 降级为 member，或 `DELETE`/禁用 admin 前，校验该租户 `status=active` 的 admin 数量；若移除后为 0，抛 409（`LAST_ADMIN_OPERATION_DENIED`）。
- 角色值必须属于 `TeamRole`（`admin`/`member`）；status 属于 `active`/`disabled`。

### 复用现有 API

- 待接收审核：`GET /knowledge-bases/admin/transfer-requests`、`POST .../accept`、`POST .../reject`（已存在，直接调用）。
- 团队库授权：`GET /knowledge-bases`（过滤 `managed`）、`GET/PUT/DELETE /knowledge-bases/{kb_uid}/members[/{user_id}]`（已存在）。

### 后端测试

新建 `backend/tests/test_team_admin_api.py`：
- 非 admin 访问 `/team/admin/*` 全部 403。
- admin 添加/列出/改角色/移除成员成功。
- 重复添加同 user_id 409。
- 操作自己 409。
- 降级/移除最后一个 active admin 409。
- 审计日志写入。
- 现有 `test_knowledge_rbac_api.py` 与 `test_knowledge_access.py` 必须保持通过。

## 前端

### 新增 API `frontend/src/features/team/api/teamAdmin.ts`

```ts
export type TeamRole = 'admin' | 'member'
export type TeamMemberStatus = 'active' | 'disabled'

export interface TeamMember {
  user_id: string
  role: TeamRole
  status: TeamMemberStatus
  created_at: string | null
  updated_at: string | null
}

export interface TeamMemberResponse { items: TeamMember[]; total: number }

export const teamAdminApi = {
  listMembers(): Promise<TeamMemberResponse>
  addMember(data: { user_id: string; role: TeamRole; status?: TeamMemberStatus }): Promise<TeamMember>
  updateMember(userId: string, data: { role?: TeamRole; status?: TeamMemberStatus }): Promise<TeamMember>
  removeMember(userId: string): Promise<{ detail: string }>
}
```

### 新增页面 `frontend/src/features/team/pages/TeamAdminPage.tsx`

三标签容器，复用现有 `Dialog`/`Button`/`Badge`/`Input`/`EmptyState`/`ErrorState`/`LoadingState`/`NotFoundState`。每个 tab 独立加载、独立 error state + retry。任一个 tab 收到 403 时整页降级为"无权访问"（复用 `KnowledgeShell` 的 403 处理模式：`NotFoundState` + 返回知识库列表按钮）。

- **待接收审核 TransfersReviewTab**：调 `knowledgeBasesApi.listTransferRequests()`。每项卡片显示库名/提交者 `transfer_requested_by`/描述/提交说明 `transfer_message`/提交时间 `transfer_requested_at`。操作：`接受`（直接调 `acceptTransfer`，成功后刷新）、`拒绝`（弹 Dialog 输入原因，调 `rejectTransfer`）。空态"暂无待接收知识库"。
- **团队库授权 TeamKbsTab**：调 `knowledgeBasesApi.list({limit:200})`，过滤 `governance_status === 'managed'`。每库一行：库名/owner/描述 + 「成员」按钮（弹出现有 `KnowledgeMembersPanel`，kbUid 传入）+ 「进入」链接。空态"暂无团队库"。
- **成员管理 TeamMembersTab**：调 `teamAdminApi.listMembers()`。复用成员面板的行/角色下拉/添加模式，但角色只有 `admin/member` 两档，状态 `active/disabled` 一档。自己的行禁用操作并标注"（我）"。操作：添加/更新（输入 user_id + 角色下拉）、移除、改角色/状态。

### 导航

`frontend/src/layouts/MainLayout.tsx` 新增「管理」分组（`navSections` 和 `NavList` 各加一个分组）：

```
管理
  └─ 团队管理 (/team/admin)
```

图标建议 `ShieldCheck` 或 `Settings`（现有 lucide 图标库）。入口对所有人可见，后端 403 兜底。

### 路由

`frontend/src/app/routes.tsx` 新增：

```tsx
import { TeamAdminPage } from '@/features/team/pages/TeamAdminPage'
// ...
{ path: 'team/admin', element: <TeamAdminPage /> },
```

放在 `MainLayout` 子路由下（与 `/knowledge`、`/memory/inbox` 平级）。

### 前端测试

新建 `frontend/tests/team-admin-console.test.mjs` 源扫描断言：
- `routes.tsx` 包含 `team/admin` 路由。
- `MainLayout.tsx` 包含「管理」分组与「团队管理」入口。
- `TeamAdminPage.tsx` 包含三个标签文本：`待接收`、`团队库授权`、`成员管理`。
- 团队库授权 tab 复用 `KnowledgeMembersPanel`。
- `teamAdminApi` 包含 `listMembers`/`addMember`/`updateMember`/`removeMember`。
- 待接收 tab 调用 `listTransferRequests`/`acceptTransfer`/`rejectTransfer`。

### 前端构建

`cd frontend && pnpm build` 必须通过。`pnpm build` 在本环境会再生成 `tsconfig.tsbuildinfo` 与 `pnpm-lock.yaml`，提交前恢复这两个文件。

## 数据流

1. 用户点「团队管理」→ `TeamAdminPage` 渲染，默认显示第一个 tab。
2. 待接收审核：`listTransferRequests()` → 展示 → 接受/拒绝调用后端 → 刷新。
3. 团队库授权：`list()` 过滤 managed → 点「成员」弹 `KnowledgeMembersPanel` → 内部调 members API → 刷新。
4. 成员管理：`listMembers()` → 展示 → 增改删调用后端 → 刷新。
5. 任一调用 403 → 整页"无权访问"。

## 错误处理

- 后端：403 统一 `ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", ...)`；校验失败 409（`SELF_OPERATION_DENIED` / `LAST_ADMIN_OPERATION_DENIED` / 重复添加）与 422（非法 role/status）。
- 前端：每个 tab 独立 error state + retry；403 降级为无权访问视图；操作失败显示错误文本（`ApiProblem.message`）。

## 非目标

- 团队库退回个人库（`managed → personal`）。
- 部门共享。
- 成员邀请/审批流。
- 前端用户搜索（第一版用 `user_id` 文本输入）。
