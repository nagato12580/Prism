# Prism Inbox → 分类 → 审阅 → 沉淀 MVP 设计

## 目标

把 Prism 从“问答系统”扩展出第一条个人信息消化链路：用户把评论、文章片段、视频链接、想法等丢进 Inbox，Prism 生成分类建议和待审阅卡片，用户确认后沉淀到知识库、记事本或轻量记忆。

## MVP 范围

- 新增统一收件箱 `inbox_raw_item`
- 新增审阅卡片 `inbox_review_item`
- 新增零散记事 `notebook_note`
- 新增轻量长期记忆 `memory_entry`
- 后端提供采集、分类、审阅、沉淀 API
- 前端新增 `/inbox` 工作台
- 分类优先调用 LLM，失败时使用规则兜底

暂不做：

- 自动创建 Wiki 文档管线
- 视频/网页正文抓取
- 向量化与主动召回
- Neo4j 图谱

## 数据流

```text
用户粘贴/转发内容
  -> POST /api/v1/inbox/items
  -> 保存 RawItem
  -> 分类器生成 ReviewItem
  -> 前端审阅
  -> approve
     knowledge -> KnowledgeItem
     opinion/resource/idea -> NotebookNote
     memory -> MemoryEntry
```

## 分类结果

分类器输出：

- `kind`: `knowledge | opinion | resource | task | memory | idea | chat`
- `title`: 审阅卡标题
- `summary`: 摘要
- `suggested_action`: `make_wiki | save_note | save_resource | remember | review_later | ignore`
- `category`: 主题分类
- `tags`: 标签
- `rationale`: 为什么这样处理
- `confidence`: 0-1

## 沉淀策略

| kind/action | MVP 沉淀位置 |
| --- | --- |
| knowledge / make_wiki | `knowledge_item`，`source_type=inbox` |
| opinion / idea | `notebook_note` |
| resource | `notebook_note`，`note_type=resource` |
| memory / remember | `memory_entry` |
| task / review_later | `notebook_note`，`note_type=task` |

## 后续升级

- knowledge 审阅通过后可触发 Wiki 知识点生成
- resource 可异步抓取网页/视频元数据
- memory 可接入主动召回与 Agent 工具
- review queue 可支持批量操作
