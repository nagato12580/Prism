# Prism Inbox → 分类 → 审阅 → 沉淀 MVP 实施计划

**Goal:** 实现一个可用的个人信息收件箱 MVP，让用户粘贴外部资料后获得分类建议，并一键沉淀到知识库、记事本或轻量记忆。

**Architecture:** Backend 负责数据模型、分类和沉淀；Frontend 新增 Inbox 工作台；复用现有 MySQL、KnowledgeItem 和 React 路由。

**Source Spec:** `docs/superpowers/specs/2026-06-17-inbox-review-settlement-design.md`

## Tasks

- [x] 新增 Inbox/Review/Note/Memory ORM 模型
- [x] 新增 Inbox Pydantic schema
- [x] 新增 `/api/v1/inbox` API
- [x] 注册模型和 router
- [x] 新增前端 API 类型
- [x] 新增 `/inbox` 页面
- [x] 注册导航和路由
- [ ] 运行后端测试与前端构建

## MVP API

- `POST /api/v1/inbox/items`
- `GET /api/v1/inbox/items`
- `POST /api/v1/inbox/items/{id}/classify`
- `GET /api/v1/inbox/reviews`
- `POST /api/v1/inbox/reviews/{id}/approve`
- `POST /api/v1/inbox/reviews/{id}/reject`
- `GET /api/v1/inbox/notes`
- `GET /api/v1/inbox/memories`
