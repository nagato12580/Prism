# Wiki 文档知识抽取 — 架构设计文档

## 1. 概述

将 cake-master 项目的「文档→结构化知识」管线集成到 Prism，为用户提供独立的上传入口和 Wiki 知识浏览页面。管线的核心思路是：**让 LLM 在一次调用中同时完成知识提取、归类、关联三件事**，后续代码只做机械性的去重、合并、持久化。

### 参考实现

`docs/doc-knowledge-extraction-reference/` — 来自 cake-master 项目的三阶段知识抽取管线。

### 关键设计决策（从参考保持）

1. **三阶段管线**：Extract(LLM提取概念) → Merge(按group合并) → Write(LLM生成文章)
2. **LLM 同时输出概念+关系+分组**：一次调用完成提取+归类+关联
3. **group 字段作为合并信号**：LLM 自己判断哪些细粒度概念应该合并成一篇完整文章
4. **同名概念去重+描述拼接**：不同 chunk 提取到同名概念时合并描述
5. **断点续抽**：每阶段完成后持久化，中断后可从断点恢复

## 2. 需求决策总结

| 维度 | 决策 |
|------|------|
| 集成模式 | 可选模式，独立于现有摄入管线 |
| 数据模型 | 复用 knowledge_file 存文件 + 新建 6 张 wiki 专用表 |
| 管线阶段 | 全部实现（概念提取 + 合并 + 描述/文章生成 + 图片识别 + 关系 + 断点续抽） |
| 触发方式 | 独立上传入口 |
| 展示页面 | 新增 `/wiki` 路由，独立 Wiki 页面 |
| RAG 检索 | 暂不接入，仅独立浏览（后续单独设计） |
| 管线位置 | Engine 进程内 |
| 工作分支 | dev |

## 3. 整体架构

```
Frontend (:5173)
  │
  ├── /wiki                    → WikiPage.tsx
  ├── /wiki/upload             → WikiUploadPage.tsx
  ├── /wiki/documents/:id      → WikiDocDetail.tsx
  ├── /wiki/points/:id         → WikiPointDetail.tsx
  │
  ├── POST /api/v1/upload?source_type=wiki  → Backend (:5175)
  │     └── 保存文件 → 创建 knowledge_file + wiki_document → 返回 id
  │
  ├── POST /api/v1/wiki/extract   → Backend → Engine (:5180)
  │     └── Engine 异步执行三阶段管线
  │           Stage 0:   文件解析（复用现有 file_parser）
  │           Stage 1.5: 图片语义识别（视觉 LLM）
  │           Stage 2:   文本切块 → LLM 提取概念+关系 → 去重
  │           Stage 3:   按 group 合并 → 创建知识点 + 关系
  │           Stage 3.5a: 描述生成
  │           Stage 3.5b: 文章生成
  │           (不做向量化)
  │
  ├── GET  /api/v1/wiki/documents         → Backend → MySQL
  │     GET  /api/v1/wiki/documents/:id    → Backend → MySQL
  │     GET  /api/v1/wiki/points           → Backend → MySQL
  │     GET  /api/v1/wiki/points/:id       → Backend → MySQL
  │     GET  /api/v1/wiki/points/:id/relations → Backend → MySQL
  │     DELETE /api/v1/wiki/documents/:id  → Backend → MySQL
```

**架构原则：**
- Engine 只负责管线计算，不直接暴露 wiki CRUD API
- Backend 负责所有 CRUD，通过内部 HTTP 调用 Engine 触发提取
- 提取是异步的：Backend 收到 extract 请求后立即返回，Engine 后台执行
- 前端通过轮询 `GET /api/v1/wiki/documents/:id` 获取进度
- 文件上传统一走 `POST /api/v1/upload`，通过 `source_type=wiki` 区分

## 4. 数据模型

### 4.1 复用表：`knowledge_file`

现有知识文件表，`source_type` 新增 `wiki` 值。无需新增字段。

### 4.2 新建表

#### `wiki_document` — Wiki 管线特有数据

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | CHAR(36) PK | UUID |
| `file_id` | CHAR(36) FK | → knowledge_file.id |
| `status` | VARCHAR(20) | pending / processing / completed / failed |
| `extract_stage` | VARCHAR(50) | 当前阶段名 |
| `progress_current` | INT | 当前进度 |
| `progress_total` | INT | 总进度 |
| `user_id` | CHAR(36) | 用户 ID，默认 'default-user' |
| `created_at` | DATETIME | |

#### `wiki_concept` — 原始概念（Stage 2 中间产物）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | CHAR(36) PK | UUID |
| `document_id` | CHAR(36) FK | → wiki_document.id |
| `name` | VARCHAR(512) | 概念名称（中文） |
| `type` | VARCHAR(32) | concept / technique / source / claim / artifact |
| `description` | TEXT | 具体事实描述（含数字、条件、阈值等） |
| `aliases` | VARCHAR(1024) | 别名，逗号分隔 |
| `group_name` | VARCHAR(256) | LLM 分配的分组名，同组概念 Stage 3 合并 |
| `category` | VARCHAR(128) | 分类 |
| `created_at` | DATETIME | |

#### `wiki_knowledge_point` — 最终知识点（Stage 3 产物）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | CHAR(36) PK | UUID |
| `document_id` | CHAR(36) FK | → wiki_document.id |
| `title` | VARCHAR(512) | 知识点标题 |
| `description` | TEXT | 精炼描述（100-200 字，Stage 3.5a 生成） |
| `content` | TEXT | 结构化 Markdown 文章（Stage 3.5b 生成） |
| `category` | VARCHAR(128) | 分类 |
| `tags` | VARCHAR(1024) | 标签，逗号分隔 |
| `aliases` | VARCHAR(1024) | 别名，逗号分隔 |
| `group_name` | VARCHAR(256) | 分组名 |
| `status` | VARCHAR(16) | 整理中 / 已发布 |
| `images` | TEXT | 关联图片 JSON: `[{"id":"uuid","caption":"描述"},...]` |
| `user_id` | CHAR(36) | 用户 ID，默认 'default-user' |
| `created_at` | DATETIME | |

#### `wiki_knowledge_relation` — 知识点关系

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | CHAR(36) PK | UUID |
| `from_point_id` | CHAR(36) FK | → wiki_knowledge_point.id |
| `to_point_id` | CHAR(36) FK | → wiki_knowledge_point.id |
| `type` | VARCHAR(64) | implements / extends / optimizes / contradicts / cites / prerequisite_of / trades_off / derived_from |
| `confidence` | FLOAT | 置信度 0.0 ~ 1.0，默认 1.0 |
| `created_at` | DATETIME | |

#### `wiki_image` — 文档内嵌图片（Stage 1.5）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | CHAR(36) PK | UUID |
| `document_id` | CHAR(36) FK | → wiki_document.id |
| `image_index` | INT | 图片在原文档中的序号（从 1 开始） |
| `storage_path` | VARCHAR(500) | 存储路径 |
| `caption` | TEXT | 视觉 LLM 生成的图片描述 |
| `mime_type` | VARCHAR(100) | MIME 类型 |
| `created_at` | DATETIME | |

#### `wiki_extraction_log` — 管线日志

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | CHAR(36) PK | UUID |
| `document_id` | CHAR(36) FK | → wiki_document.id |
| `stage` | VARCHAR(50) | 阶段名 |
| `message` | TEXT | 日志内容 |
| `status` | VARCHAR(16) | info / warning / error |
| `progress_current` | INT | 当前进度 |
| `progress_total` | INT | 总进度 |
| `created_at` | DATETIME | |

### 4.3 实体关系图

```
knowledge_file (复用)          wiki_document (新建)
┌──────────────────┐          ┌──────────────────────┐
│ id (PK)          │←──1:1──│ id (PK)              │
│ original_name    │         │ file_id (FK)         │
│ storage_path     │         │ status               │
│ mime_type        │         │ extract_stage        │
│ content_text     │         │ progress_current     │
│ source_type='wiki'│        │ progress_total       │
│ ...              │         │ user_id              │
└──────────────────┘         │ created_at           │
                             └──────────┬────────────┘
                                        │ 1:N
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
            wiki_concept        wiki_knowledge_point   wiki_image
            (Stage 2 中间)       (Stage 3 最终)        (图片)

            wiki_knowledge_relation  (知识点关系)
            wiki_extraction_log      (管线日志)
```

## 5. 管线阶段详解

### Stage 0: 文件解析
- 复用 Backend 现有 `utils/file_parser.py` 解析 PDF/DOCX/XLSX/PPTX/MD/TXT
- 结果存入 `knowledge_file.content_text`

### Stage 1.5: 图片语义识别（可选）
- 文档内嵌图片 → base64 → 视觉 LLM → 中文描述
- 更新文本中的 `[图片N]` 占位符为 `[图片N: 描述]`
- 结果存入 `wiki_image` 表

### Stage 2: 概念提取（核心阶段）
- 文本按 section 边界切块（MAX=4000 字符，overlap=200）
- ThreadPoolExecutor 并发调用 LLM（并发度 3）
- 每个 chunk 返回 `{concepts[], relations[]}` JSON
- 按 name 去重（同名概念合并描述和别名）
- 结果写入 `wiki_concept` 表
- 提示词：参考 `extraction_engine.py` 中的提取提示词，适配 Prism 通用知识库场景

### Stage 3: 知识点合并
- 按 `group` 字段分组：同组概念合并为一个 KnowledgePoint
- 无 group 的概念独立成 KnowledgePoint
- 关系名称解析（概念名 → 知识点名，通过 alias_map）
- 结果写入 `wiki_knowledge_point` + `wiki_knowledge_relation`

### Stage 3.5a: 描述生成
- 对缺少 description 的知识点 → LLM 生成 100-200 字精炼描述

### Stage 3.5b: 文章生成
- 对缺少 content 的知识点 → LLM 生成结构化 Markdown 文章
- 文章结构：`# 标题` → `## 概述` → `## 关键要点` → `## 适用场景` → `## 注意事项`
- 可引用 `doc_image://{id}` 嵌入图片
- 更新 `wiki_knowledge_point.status` → '已发布'

### 断点续抽
- 每个阶段完成后持久化
- 检查逻辑：
  - `wiki_knowledge_point` 已存在 → 跳过 Stage 0-3，从描述/文章继续
  - `wiki_concept` 已存在 → 跳过 Stage 0-2，从 Stage 3 继续
  - 都不存在 → 从头开始

### 暂不做：向量化（Stage 4）
- 后续专门设计 RAG 接入方案时再实现

## 6. API 设计

### 6.1 上传（复用现有）

```
POST /api/v1/upload
  Content-Type: multipart/form-data
  body: { file, source_type: "wiki" }
  → 创建 knowledge_file (source_type=wiki)
  → 同时创建 wiki_document 关联
  → 返回 { file_id, wiki_doc_id }
```

### 6.2 触发提取

```
POST /api/v1/wiki/extract
  body: { doc_id }
  → Backend 内部 POST Engine /api/v1/wiki/extract
  → Engine 异步执行管线
  → Backend 立即返回 { doc_id, status: "processing" }
```

### 6.3 查询 API

```
GET  /api/v1/wiki/documents              → wiki 文档列表（含进度）
GET  /api/v1/wiki/documents/:id           → 单文档详情 + 进度 + extraction_logs
GET  /api/v1/wiki/points?doc_id=:id      → 某文档的知识点列表
GET  /api/v1/wiki/points/:id             → 单知识点详情（含 Markdown 文章）
GET  /api/v1/wiki/points/:id/relations   → 某知识点的关联关系
DELETE /api/v1/wiki/documents/:id         → 删除文档及所有关联数据（级联删除）
```

### 6.4 Engine 内部端点

```
POST /api/v1/wiki/extract  (Engine :5180)
  body: { doc_id, file_id }
  → Engine 读取 knowledge_file.content_text
  → 异步执行 Stage 1.5→2→3→3.5
  → 结果写入 wiki_* 表
  → 更新 wiki_document.status
```

## 7. 前端设计

### 7.1 路由

```
/wiki                        → WikiPage.tsx（文档列表 + 知识点浏览）
/wiki/upload                 → WikiUploadPage.tsx（独立上传入口）
/wiki/documents/:id          → WikiDocDetail.tsx（单文档进度 + 知识点列表）
/wiki/points/:id             → WikiPointDetail.tsx（知识点文章阅读）
```

### 7.2 页面结构

**WikiPage (`/wiki`)** — 主入口，左右分栏：
- 左侧：文档列表（卡片式，显示文件名、状态图标、进度条、知识点数量）
- 右侧：选中文档的知识点列表（卡片式，显示标题、分类、关系数）
- 顶部操作栏：「+ 上传文档」按钮

**WikiUploadPage (`/wiki/upload`)** — 上传页：
- 拖拽/选择文件区域
- 上传后自动跳转到对应 WikiDocDetail 页面

**WikiDocDetail (`/wiki/documents/:id`)** — 文档详情：
- 管线进度条（阶段名 + 进度条）
- 管线日志流（实时展示 extraction_log）
- 知识点列表（完成后展示）

**WikiPointDetail (`/wiki/points/:id`)** — 文章阅读：
- Markdown 文章渲染（复用现有 Markdown 组件）
- 元信息区：分类 / 标签 / 来源文档
- 关联知识点列表（含关系类型标注）

### 7.3 组件树

```
WikiPage
├── WikiDocList          // 左侧：文档卡片列表
│   └── WikiDocCard      // 单文档卡片（文件名、状态、进度）
└── WikiPointList        // 右侧：知识点列表
    └── WikiPointCard    // 单知识点卡片（标题、分类、关系数）

WikiUploadPage
├── FileUploadZone       // 拖拽/选择文件区
└── UploadProgress       // 上传进度

WikiDocDetail
├── DocProgress          // 管线进度条
├── ExtractionLogList    // 管线日志流
└── WikiPointList        // 知识点列表

WikiPointDetail
├── MarkdownRenderer     // 文章渲染（复用现有）
├── PointMeta            // 分类/标签/来源
└── RelationList         // 关联知识点列表
```

## 8. 实施范围

### 需要新建的文件

| 层 | 文件 | 用途 |
|----|------|------|
| Backend | `backend/app/models/wiki.py` | 6 个 Wiki ORM 模型 |
| Backend | `backend/app/schemas/wiki.py` | Wiki API 请求/响应 Schema |
| Backend | `backend/app/api/wiki.py` | Wiki CRUD + Engine 触发 |
| Engine | `engine/app/wiki/__init__.py` | |
| Engine | `engine/app/wiki/prompts.py` | 提取 + 文章生成提示词 |
| Engine | `engine/app/wiki/extraction_engine.py` | 三阶段管线核心逻辑 |
| Engine | `engine/app/api/wiki.py` | Engine 侧 extract 端点 |
| Frontend | `frontend/src/pages/WikiPage.tsx` | Wiki 主页 |
| Frontend | `frontend/src/pages/WikiUploadPage.tsx` | Wiki 上传页 |
| Frontend | `frontend/src/pages/WikiDocDetail.tsx` | 文档详情页 |
| Frontend | `frontend/src/pages/WikiPointDetail.tsx` | 知识点阅读页 |
| Frontend | `frontend/src/app/wikiStore.ts` | Wiki 状态管理 |

### 需要修改的文件

| 层 | 文件 | 改动 |
|----|------|------|
| Backend | `backend/app/api/upload.py` | source_type=wiki 时创建 wiki_document |
| Backend | `backend/app/models/__init__.py` | 导出新模型 |
| Backend | `backend/app/main.py` | 注册 wiki router |
| Backend | `backend/app/utils/auto_migrate.py` | 追加 6 张 wiki 表 |
| Engine | `engine/app/main.py` 或 `engine/run.py` | 注册 wiki router |
| Frontend | `frontend/src/app/routes.tsx` | 追加 4 条路由 |
| Frontend | `frontend/src/app/api.ts` | 追加 wiki API 调用函数 |

## 9. 待后续设计

- Wiki 知识点向量化 + 接入 RAG 检索（`knowledge_search` 工具）
- Wiki 知识点关系图谱可视化
