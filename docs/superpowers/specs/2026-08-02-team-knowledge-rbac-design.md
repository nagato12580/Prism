# 团队知识库 RBAC 权限设计

Date: 2026-08-02

## 目标

将 Prism 的知识库从当前“个人所有、owner 可见”模型升级为支持团队贡献与管理员分配权限的 RBAC 模型。

目标行为：

- 普通成员可以创建个人知识库，默认私有且对自己完全可控。
- 个人库只有经 owner 提交、管理员确认后，才进入团队共享治理。
- 团队库由管理员分配每个成员在每个知识库上的角色。
- 成员只有被授权后，才能在知识库页面看到团队库。
- Chat 检索、知识库检索和图谱查看都只能基于用户可见知识库。
- 图谱构建、索引重建、成员授权等高影响操作必须按角色收紧。
- Engine 不直接判断团队角色，只信 Backend 签发的授权 scope。

本文只定义权限模型、状态机、边界和验收标准，不包含实施计划或代码。

## 调研依据

### Yuxi 可参考点

调研版本：`xerrors/Yuxi` `4bca27add619729085f3acfe314fe09e9b3f81fe`。

Yuxi 的成熟设计提供了三个可参考点：

1. 用户具有平台角色和部门信息：`superadmin / admin / user` 与 `department_id`。
2. 知识库通过 `share_config` JSON 控制可见范围：`global / department / user`。
3. Agent 知识库工具在 `query_kb`、`open_kb_document`、`download_kb_file` 前，都会校验目标知识库是否在当前用户可见集合内。

关键文件：

- `backend/package/yuxi/utils/share_config.py`
- `backend/package/yuxi/knowledge/manager.py`
- `backend/package/yuxi/agents/toolkits/kbs/tools.py`
- `backend/server/routers/knowledge_router.py`
- `backend/server/routers/graph_router.py`

### Prism 当前基础

Prism 已具备更适合强隔离的基础：

- `KnowledgeTopic` 已有 `tenant_id`、`owner_user_id`、`kb_uid`。
- `KnowledgeAccessPolicy.require_read/manage` 已集中封装知识库权限判断，但当前只支持 owner。
- Chat Backend proxy 已经计算 `allowed_kb_uids`，并签名为 `AuthorizedKnowledgeScope` 传给 Engine。
- Engine 知识库工具已经把 `allowed_kb_uids` 作为唯一授权来源。
- 单库检索和图谱 API 已经通过 Backend 进入，适合统一接入新的 Policy。

因此，Prism 不应直接照搬 Yuxi 的 `share_config` JSON，而应在保留 signed scope 的基础上，引入正式的库级 membership 表。

## 核心概念

### 团队角色

团队角色是用户在租户内的基础权限。

```text
admin
member
```

`admin`：

- 管理团队成员。
- 管理所有知识库。
- 接收或拒绝个人库提交为团队库。
- 分配任意团队库的成员权限。
- 删除团队库。

`member`：

- 创建和管理自己的个人库。
- 查看、检索、编辑自己拥有的个人库。
- 只能看到被授权的团队库。
- 不能直接管理团队成员。
- 不能直接将库共享给其他团队成员。

### 知识库治理状态

知识库存在三个治理状态。

```text
personal
pending_transfer
managed
```

`personal`：

- 普通成员创建的新知识库默认状态。
- 只有 owner 可见。
- owner 对该库有完整所有权：查看、检索、上传、编辑、删除、构建图谱、重建索引。

`pending_transfer`：

- owner 已提交给管理员确认。
- 该库尚未进入团队共享。
- owner 仍可见，并可继续上传、编辑和完善内容。
- owner 不能删除该库，避免管理员审核对象消失。
- owner 可撤回提交，状态回到 `personal`。
- admin 可在管理后台看到待确认列表。

`managed`：

- admin 已确认接收，知识库进入团队治理。
- 库级成员权限由 admin 分配。
- 原 owner 默认获得该库 `editor` 角色。
- 团队成员只有被授权后才能看到和使用该库。

状态流转：

```text
personal -> pending_transfer -> managed
personal <- pending_transfer
```

允许动作：

- owner 提交：`personal -> pending_transfer`
- owner 撤回：`pending_transfer -> personal`
- admin 接收：`pending_transfer -> managed`
- admin 拒绝：`pending_transfer -> personal`

第一版不支持 `managed -> personal` 自助退回。若未来需要退回，应由 admin 操作，并保留审计记录。

### 库级角色

团队库上的成员权限由库级角色控制。

```text
viewer
contributor
editor
manager
```

角色包含关系：

```text
viewer < contributor < editor < manager
```

团队 `admin` 不需要逐库 membership，天然拥有所有团队库最高权限。

权限矩阵：

| 权限 | viewer | contributor | editor | manager | admin |
|---|---:|---:|---:|---:|---:|
| 看见知识库 | 是 | 是 | 是 | 是 | 是 |
| 检索知识库 | 是 | 是 | 是 | 是 | 是 |
| 查看图谱 | 是 | 是 | 是 | 是 | 是 |
| 查看文件与引用 | 是 | 是 | 是 | 是 | 是 |
| 上传/新增文件 | 否 | 是 | 是 | 是 | 是 |
| 触发解析/索引 | 否 | 是 | 是 | 是 | 是 |
| 构建/重建图谱 | 否 | 否 | 是 | 是 | 是 |
| 编辑库名称、描述、配置 | 否 | 否 | 是 | 是 | 是 |
| 删除文件 | 否 | 否 | 是 | 是 | 是 |
| 管理该库成员授权 | 否 | 否 | 否 | 是 | 是 |
| 删除团队库 | 否 | 否 | 否 | 否 | 是 |
| 接收团队库转移 | 否 | 否 | 否 | 否 | 是 |

进入 `managed` 时，系统自动写入一条 membership：

```text
原 owner -> editor
```

这样原贡献者可以继续维护内容，但不能默认分配其他成员权限。

## 数据模型

### team_members

记录用户在租户内的团队角色。

```text
team_members
- id
- tenant_id
- user_id
- role: admin | member
- status: active | disabled
- created_at
- updated_at
```

约束：

- `(tenant_id, user_id)` 唯一。
- 禁用用户不能登录和访问知识库。
- 第一版可以先由请求头或现有 actor 适配器生成用户身份，但权限查询应面向正式表设计。

### knowledge_base_memberships

记录成员在某个团队库上的角色。

```text
knowledge_base_memberships
- id
- tenant_id
- kb_uid
- user_id
- role: viewer | contributor | editor | manager
- granted_by
- created_at
- updated_at
```

约束：

- `(tenant_id, kb_uid, user_id)` 唯一。
- `kb_uid` 必须属于同一 `tenant_id`。
- membership 只对 `managed` 知识库生效。
- 团队 admin 不需要在每个库写 membership。

### knowledge_topic 扩展

在现有 `KnowledgeTopic` 上扩展治理字段。

```text
knowledge_topic
- governance_status: personal | pending_transfer | managed
- transfer_requested_by
- transfer_requested_at
- transfer_message
- transfer_reviewed_by
- transfer_reviewed_at
- transfer_rejection_reason
```

保留现有字段：

```text
- tenant_id
- owner_user_id
- kb_uid
```

`owner_user_id` 不因进入团队库而被覆盖。它用于保留来源、贡献者和个人所有权历史。团队治理由 `governance_status` 与 membership 表表达。

### 审计日志

建议为权限变更和状态流转记录审计事件。

```text
knowledge_access_audit_logs
- id
- tenant_id
- kb_uid
- actor_id
- action
- target_user_id
- before
- after
- created_at
```

第一版最低要求记录：

- 提交团队库
- 撤回提交
- admin 接收
- admin 拒绝
- 分配成员角色
- 修改成员角色
- 移除成员授权
- 删除团队库

## 权限判定策略

统一扩展 `KnowledgeAccessPolicy`，避免每个 API 自己拼权限逻辑。

核心方法：

```text
visible_kb_uids(actor) -> list[str]
list_visible(actor) -> query
require_read(actor, kb_uid)
require_contribute(actor, kb_uid)
require_edit(actor, kb_uid)
require_manage_members(actor, kb_uid)
require_delete(actor, kb_uid)
require_admin(actor)
```

个人库规则：

- `personal`：只有 `owner_user_id == actor.actor_id` 可读和管理。
- `pending_transfer`：owner 可读、贡献、编辑，但不能删除；admin 可读并审核。
- `managed`：owner 不再天然获得最高权限，按 membership 决定；进入 managed 时已自动给原 owner `editor`。

admin 规则：

- admin 可读所有 `personal`、`pending_transfer` 和 `managed` 库，但普通产品列表可按视图区分。
- admin 可管理所有 `managed` 库和所有 `pending_transfer` 审核。
- admin 可删除团队库。
- admin 是否能直接编辑个人库内容，第一版作为管理能力允许，但前端应默认把个人库和团队库分区展示，减少误操作。

成员规则：

- member 可完全管理自己的 `personal` 库。
- member 对自己的 `pending_transfer` 库可继续上传和编辑，但不可删除。
- member 对 `managed` 库按 membership 角色判断。
- member 不能给自己的库直接分配团队成员权限；必须先提交 admin 接收为 `managed`。

## Backend API 影响

### 知识库列表

`GET /knowledge-bases`

返回 actor 可见知识库：

- member：自己的 `personal`、自己的 `pending_transfer`、被授权的 `managed`。
- admin：全部，可按 tab/filter 区分个人库、待接收、团队库。

响应应包含：

```text
governance_status
owner_user_id
my_role
can_read
can_contribute
can_edit
can_manage_members
can_delete
```

前端不应自行推导高风险权限，按钮状态以后端返回能力为准。

### 个人库提交与撤回

新增：

```text
POST /knowledge-bases/{kb_uid}/transfer-request
DELETE /knowledge-bases/{kb_uid}/transfer-request
```

规则：

- 只有 owner 可提交和撤回。
- 只有 `personal` 可提交。
- 只有 `pending_transfer` 可撤回。
- 提交后 owner 不能删除库。

### 管理员审核

新增：

```text
GET /admin/knowledge-transfer-requests
POST /admin/knowledge-transfer-requests/{kb_uid}/accept
POST /admin/knowledge-transfer-requests/{kb_uid}/reject
```

接收规则：

- 只有 admin 可接收。
- 状态必须是 `pending_transfer`。
- 状态更新为 `managed`。
- 自动授予原 owner `editor`。
- 写审计日志。

拒绝规则：

- 只有 admin 可拒绝。
- 状态回到 `personal`。
- 保存拒绝原因。
- 写审计日志。

### 团队库成员授权

新增：

```text
GET /knowledge-bases/{kb_uid}/members
PUT /knowledge-bases/{kb_uid}/members/{user_id}
DELETE /knowledge-bases/{kb_uid}/members/{user_id}
```

规则：

- `manager` 或 admin 可查看和修改成员授权。
- 只有 `managed` 库可设置团队成员授权。
- admin 可设置任意成员角色。
- manager 可分配 `viewer/contributor/editor`，是否可分配 `manager` 第一版建议只允许 admin。
- 不能通过 membership 降低 admin 的全局权限。

### 知识库内容操作

现有上传、文件管理、解析、索引、图谱构建接口接入 Policy：

- 上传文件：`require_contribute`
- 触发解析/索引：`require_contribute`
- 编辑库信息：`require_edit`
- 删除文件：`require_edit`
- 构建/重建图谱：`require_edit`
- 删除个人库：owner 可删除，但 `pending_transfer` 禁止删除。
- 删除团队库：admin only。

### 检索 API

单库检索：

```text
POST /knowledge-bases/{kb_uid}/retrieval/query
```

必须先 `require_read(actor, kb_uid)`。

多库或 Chat 检索：

- Backend 先计算 actor 可读库集合。
- 用户请求的 `kb_uids` 必须是可读集合子集。
- Backend 签发 `AuthorizedKnowledgeScope.allowed_kb_uids`。
- Engine 只在 `allowed_kb_uids` 范围内检索。

### 图谱 API

图谱查看：

- 单库图谱必须 `require_read`。
- 多库图谱必须按 actor 可读库集合过滤。

图谱构建/重建：

- 必须 `require_edit`。

团队库图谱不能因为用户只在前端看不到而在后端泄漏。所有图谱查询都必须使用 Policy 或 signed scope。

## Engine 边界

Engine 不接收浏览器身份，也不查询团队角色。

Engine 只接受 Backend 签名 scope：

```text
actor_id
tenant_id
allowed_kb_uids
run_id
expires_at
```

要求：

- 任意工具参数里的 `kb_uid` 必须属于 `allowed_kb_uids`。
- 无 scope 时不启用知识库工具。
- Engine 返回证据时只返回公共来源字段，不返回租户内部路径或未授权库元数据。
- 图谱扩展、chunk 加载、文档打开、下载原文都必须重复校验 `allowed_kb_uids`。

Prism 现有 signed scope 机制应保留并强化，不退回到 Yuxi 那种只在工具层缓存可见库列表的模式。

## Frontend 影响

知识库页面建议分区：

- 我的个人库
- 提交中
- 团队库
- 管理员：待接收

个人库卡片：

- owner 可看到“提交为团队库”。
- `pending_transfer` 显示“等待管理员确认”和“撤回提交”。
- `pending_transfer` 隐藏或禁用删除入口。

团队库详情：

- 显示当前用户角色。
- 依据后端返回的 `can_*` 能力控制按钮。
- `viewer` 不显示上传、编辑、重建图谱按钮。
- `contributor` 可上传和索引，但不能改库配置或建图。
- `editor` 可编辑库信息、管理文件、建图。
- `manager` 可打开成员授权面板。
- admin 可打开所有管理面板，并可删除团队库。

管理员页面：

- 成员管理：设置用户团队角色 `admin/member`。
- 待接收知识库：查看提交者、库名、描述、统计、提交说明，执行接收/拒绝。
- 团队库授权：为成员分配库级角色。

## 安全与一致性

必须满足：

- 前端只做体验控制，后端 Policy 是最终边界。
- 列表、详情、上传、删除、检索、图谱、Agent 工具使用同一套权限判定。
- admin 与 owner 权限差异要在 Policy 中集中表达。
- `pending_transfer` 不能删除库。
- `managed` 后原 owner 默认 `editor`，不是 `manager`。
- 团队库删除只允许 admin。
- 查询响应不能泄漏不可见库的名称、文件名、引用或图谱节点。
- 权限变更后，新的请求必须即时生效；已签发的 Chat scope 允许在短 TTL 内继续使用，TTL 应保持较短。

## 测试与验收

后端测试：

- member 创建库后只有自己可见。
- 另一个 member 看不到该个人库。
- owner 提交后状态为 `pending_transfer`，仍可编辑但不可删除。
- owner 可撤回提交。
- admin 可看到待接收列表。
- admin 接收后状态为 `managed`，原 owner 获得 `editor`。
- 未授权 member 看不到 managed 库。
- 授权 `viewer` 后可列表、详情、检索、看图谱，但不能上传。
- 授权 `contributor` 后可上传和触发索引，但不能建图或改配置。
- 授权 `editor` 后可建图、编辑、删文件，但不能授权成员。
- 授权 `manager` 后可授权成员，但不能删除团队库。
- admin 可删除团队库。
- Chat scope 只包含 actor 可读且本次选择的库。
- Engine 拒绝 scope 外的 `kb_uid`。

前端测试：

- 知识库列表按个人库、提交中、团队库展示。
- `pending_transfer` 禁用删除入口。
- 不同角色只显示对应操作按钮。
- 管理员能看到待接收入口和成员授权入口。
- 对话页知识库选择器只列出可读库。

集成测试：

- 使用真实 MySQL 验证 membership 唯一约束、状态流转事务和并发接收。
- 使用 Backend -> Engine 签名 scope 验证 Chat 检索不会越权。
- 使用图谱 API 验证未授权用户不能看到节点、边、统计和标签。

## 非目标

第一版不做：

- 部门共享。
- 用户自助申请访问。
- 团队库退回个人库。
- 文件级或 chunk 级权限。
- 每个知识库自定义角色名。
- 外部 OIDC 组织同步。
- 复杂 ABAC 条件策略。

这些能力可以在正式 membership 与审计基础上扩展。

