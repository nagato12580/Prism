# Prism M3 AI Asset Draft 与 Chat 闭环设计

## 1. 目标

M3 的目标不是简单给 Chat 增加几个检索工具，而是建立个人知识治理闭环：

```text
任意输入
  -> RawItem
  -> AI Parse
  -> Editable AssetDraft
  -> 用户审阅修正
  -> PersonalAsset / MemoryEntry
  -> Index
  -> Relation
  -> Chat Agent 使用
  -> 反馈回写
```

用户体验目标：

> 用户只需要粘贴或上传任意内容，Prism 自动解析并生成可编辑的知识资产草稿。用户确认后，内容才进入正式知识资产、记忆或关系网络，并能被 Chat Agent 自主检索和复用。

## 2. 设计原则

1. **AI-first 解析**：任意上传或粘贴的内容优先由 AI 解析，用户不需要先选择来源、类型或分类。
2. **用户确认入库**：AI 只能生成建议，不能绕过审阅直接污染正式知识库、长期记忆或关系网络。
3. **草稿可编辑**：标题、来源、分类、标签、摘要、资产类型、关联知识点、扩展知识点都必须允许用户修改。
4. **统一资产治理**：Inbox 只是摄入入口。确认后的知识、笔记、观点、资源应进入统一的个人知识资产层。
5. **记忆边界独立**：长期记忆不混入普通知识资产，先通过独立 memory 查询工具接入，未来升级图谱记忆。
6. **Agent 自主调用工具**：Chat Agent 不靠关键词硬路由，而是根据工具描述自主判断是否检索资产、记忆或文档。
7. **渐进式复杂度**：M3 第一版先做可用闭环和弱关联，不引入 Neo4j 或用户自定义外部动作工具。

## 3. 范围

### 3.1 M3 第一版包含

- AI 解析任意 RawItem，生成结构化 `AssetDraft`。
- `AssetDraft` 支持用户编辑。
- AI 解析结果包含分层置信度和理由。
- 用户确认后落库为 `PersonalAsset` 或 `MemoryEntry`。
- AI 提出的关联知识点、扩展知识点只作为草稿建议展示，用户确认后才落库。
- 新增资产索引，让 Chat 能检索已确认 PersonalAsset。
- 新增 Chat Agent 工具：
  - `asset_search`
  - `asset_overview`
  - `asset_related`
  - `memory_search`
- 保留现有 `knowledge_search`，作为上传文档/向量化 chunk 的证据型 RAG 兜底。
- Chat 使用资产后的基础反馈回写，例如记录引用、提升重要性或生成待确认建议。

### 3.2 M3 第一版不包含

- 用户自定义任意外部 API 工具。
- 用户自定义代码执行。
- 自动写入长期记忆。
- 未确认关系自动进入正式关系网络。
- 完整图谱记忆。
- 复杂多 Agent 编排。
- 全平台自动抓取。

## 4. 核心概念

### 4.1 RawItem

RawItem 是用户粘贴或上传的原始材料。它只表示“进入系统的原始输入”，不代表已经被治理。

已有 `InboxRawItem` 可以继续承担这个职责。

关键字段：

- `id`
- `user_id`
- `title`
- `content`
- `source_url`
- `source_platform`
- `source_type`
- `status`
- `created_at`

### 4.2 AssetDraft

AssetDraft 是 AI 对 RawItem 解析后的可编辑草稿。它是审阅台的核心对象。

建议字段：

- `id`
- `raw_item_id`
- `user_id`
- `title`
- `summary`
- `asset_kind`
- `source_type`
- `source_platform`
- `source_url`
- `category`
- `tags`
- `extracts`
- `suggested_relations`
- `suggested_extensions`
- `confidence`
- `rationale`
- `status`
- `created_at`
- `updated_at`

其中：

- `asset_kind` 是开放字符串，例如 `knowledge`、`opinion`、`resource`、`task`、`idea`。
- `extracts` 保存 AI 提取的知识点、观点、行动项、问题等。
- `suggested_relations` 保存待确认关联建议。
- `suggested_extensions` 保存待确认扩展知识点。
- `confidence` 是分层置信度对象。

### 4.3 PersonalAsset

PersonalAsset 是用户确认后的个人知识资产。它不是 RawItem，也不是临时草稿，而是进入治理闭环的正式对象。

建议字段：

- `id`
- `user_id`
- `asset_kind`
- `title`
- `body`
- `summary`
- `category`
- `tags`
- `source_type`
- `source_platform`
- `source_url`
- `media_type`
- `metadata`
- `capabilities`
- `source_raw_item_id`
- `source_draft_id`
- `source_ref_type`
- `source_ref_id`
- `importance`
- `status`
- `created_at`
- `updated_at`

说明：

- `asset_kind`、`source_type`、`media_type` 保持开放字符串，便于未来支持音频、视频、截图、邮件、会议纪要等来源。
- `metadata` 保存来源特有信息，例如 GitHub repo、视频时间戳、音频说话人、OCR 坐标等。
- `capabilities` 保存资产能力，例如 `searchable`、`summarizable`、`has_transcript`、`has_ocr_text`。

### 4.4 MemoryEntry

MemoryEntry 保存用户长期偏好、目标、约束和上下文。它与 PersonalAsset 保持边界独立。

M3 第一版只允许从 AssetDraft 中生成待确认的记忆建议。用户确认后写入 MemoryEntry。

未来图谱记忆可以在 MemoryEntry 基础上扩展：

```text
MemoryEntry
  -> MemoryNode
  -> MemoryEdge
  -> personal_memory_search / graph_memory_query
```

### 4.5 AssetRelation

AssetRelation 表达 PersonalAsset 之间的显式关系。

建议字段：

- `id`
- `user_id`
- `from_asset_id`
- `to_asset_id`
- `relation_type`
- `reason`
- `confidence`
- `source_draft_id`
- `status`
- `created_at`

关系类型：

- `similar_to`
- `supports`
- `contradicts`
- `extends`
- `mentions`
- `derived_from`

M3 第一版中，AI 只生成 `suggested_relations`。用户确认后才创建 `AssetRelation`。

### 4.6 ExtensionPoint

ExtensionPoint 是 AI 提出的“值得继续研究或拓展”的知识点。

建议字段：

- `id`
- `user_id`
- `asset_id`
- `title`
- `reason`
- `suggested_kind`
- `confidence`
- `status`
- `created_at`

M3 第一版中，AI 只生成 `suggested_extensions`。用户确认后可以：

- 创建待研究任务。
- 创建新的 PersonalAsset 草稿。
- 忽略该扩展点。

## 5. AI Parse 输出

AI Parser 对 RawItem 的输出必须是严格 JSON。

建议结构：

```json
{
  "title": "问题分解能力比追模型更重要",
  "asset_kind": "opinion",
  "source": {
    "type": "comment",
    "platform": "manual",
    "url": ""
  },
  "summary": "这段评论强调学习 AI 的关键是问题分解能力。",
  "extracts": [
    {
      "type": "claim",
      "content": "学习 AI 最重要的不是追模型，而是建立问题分解能力。",
      "confidence": 0.91
    }
  ],
  "tags": ["AI", "学习方法", "问题分解"],
  "category": "AI 学习",
  "suggested_relations": [
    {
      "target_asset_id": "asset-id",
      "relation_type": "supports",
      "reason": "都强调 AI 学习中的思维方法。",
      "confidence": 0.72
    }
  ],
  "suggested_extensions": [
    {
      "title": "如何训练问题分解能力",
      "reason": "原文提出了方向，但没有展开方法。",
      "confidence": 0.78
    }
  ],
  "confidence": {
    "overall": 0.86,
    "classification": 0.9,
    "source": 0.65,
    "extraction": 0.88,
    "relation": 0.72,
    "extension": 0.78
  },
  "rationale": "内容表现为观点型评论，适合沉淀为观点资产。"
}
```

解析失败时，系统必须生成最低可用草稿：

- title 取用户标题或正文前 40 字。
- asset_kind 为 `idea`。
- summary 为正文简短摘要。
- confidence.overall 不高于 0.4。
- rationale 说明使用了兜底解析。

## 6. 审阅与编辑

AssetDraft 审阅台需要支持编辑：

- 标题
- 摘要
- 资产类型
- 来源类型
- 来源平台
- 来源链接
- 分类
- 标签
- 提取内容
- 关联知识点
- 关系类型
- 扩展知识点
- 是否生成长期记忆建议

用户操作：

- 保存为 PersonalAsset
- 保存为 MemoryEntry
- 同时保存资产并创建待确认记忆
- 确认部分关联
- 忽略部分关联
- 确认部分扩展点
- 忽略部分扩展点
- 重新 AI 解析
- 忽略草稿

确认后才允许写入正式表：

```text
AssetDraft
  -> PersonalAsset
  -> AssetRelation
  -> ExtensionPoint
  -> MemoryEntry
```

## 7. 索引与检索

### 7.1 Asset Index

PersonalAsset 确认后必须进入可检索索引。

M3 第一版可以先使用数据库 LIKE/全文搜索加标签聚合；如果已有向量化能力稳定，也可以在确认后异步向量化。

索引文本建议包括：

- title
- summary
- body
- extracts.content
- tags
- category
- source_platform

### 7.2 弱关联

M3 第一版先做弱关联：

- 相同 tag
- 相同 category
- 相同 source_platform
- 标题/摘要关键词相似
- AI suggested_relations 经用户确认

显式 AssetRelation 只来自用户确认。

## 8. Agent 工具边界

### 8.1 asset_search

搜索已确认 PersonalAsset。

适用问题：

- 用户保存过哪些资料。
- 用户之前沉淀过哪些观点。
- 某个主题下有哪些知识资产。
- 某个资源、观点、知识点是否已被保存。

返回内容必须包含：

- `asset_id`
- `asset_kind`
- `title`
- `summary`
- `source_type`
- `source_platform`
- `tags`
- `category`
- `score`

### 8.2 asset_overview

对已确认 PersonalAsset 做概览和聚合。

适用问题：

- “我之前发给你的评论都围绕什么内容？”
- “我最近保存最多的是哪些主题？”
- “我的 Agent 相关资料大概分成哪几类？”

返回内容：

- summary
- topic/category/tag 分布
- representative_assets
- time range

### 8.3 asset_related

查找某段内容或某个 asset 与已有资产的关联。

适用问题：

- “这条观点和我之前哪些内容有关？”
- “这个 GitHub 项目和我保存过的 Agent 资料有什么关系？”

M3 第一版使用弱关联和已确认 AssetRelation。

### 8.4 memory_search

搜索长期记忆和用户画像。

适用问题：

- 用户偏好。
- 用户目标。
- 用户约束。
- 当前项目上下文。
- 长期关注主题。

M3 第一版搜索 `MemoryEntry`。未来接图谱记忆。

### 8.5 knowledge_search

保留现有工具，负责上传文档、向量化 chunk、证据型 RAG 搜索。

它不负责普通资产概览，也不负责长期记忆。

### 8.6 工具选择

Agent 不使用关键词硬路由。系统提示只描述工具能力边界：

- 需要已确认个人知识资产时，可使用 `asset_search`、`asset_overview`、`asset_related`。
- 需要用户长期偏好、目标、约束时，可使用 `memory_search`。
- 需要上传文档中的证据细节时，可使用 `knowledge_search`。
- 不需要个人资料时，可以直接回答。

## 9. Chat 使用后的反馈回写

M3 第一版只做轻量反馈回写：

- 记录 Chat 回答引用了哪些 asset。
- 用户点赞或继续追问某个 asset 时，提高该 asset 的 `importance`。
- 当 Chat 过程中发现可能的新记忆或新关系，只生成 `AssetDraft` 或待确认建议，不直接写正式记忆或关系。

建议新增 `AssetUsageEvent`：

- `id`
- `user_id`
- `session_id`
- `message_id`
- `asset_id`
- `usage_type`
- `created_at`

`usage_type` 可包括：

- `cited`
- `opened`
- `followed_up`
- `confirmed_useful`

## 10. 与现有系统关系

### 10.1 Inbox

Inbox 仍是摄入入口。已有 `InboxRawItem` 和 `InboxReviewItem` 可以逐步演进：

- `InboxRawItem` 继续作为 RawItem。
- `InboxReviewItem` 可迁移为或兼容 AssetDraft。
- 旧的 approve 行为需要升级为“确认 AssetDraft 并创建 PersonalAsset/MemoryEntry/Relation/Extension”。

### 10.2 KnowledgeItem

已有 `KnowledgeItem` 可以继续存在。M3 后：

- 新的知识类沉淀优先进入 PersonalAsset。
- 如需要兼容旧页面，可同步创建 KnowledgeItem，或让 Knowledge 页面读取 PersonalAsset。
- 旧 KnowledgeItem 可通过迁移脚本回填为 PersonalAsset。

### 10.3 NotebookNote

NotebookNote 表达观点、资源、灵感、稍后看。M3 后：

- 可以逐步被 PersonalAsset 覆盖。
- 第一版可继续写 NotebookNote，同时创建 PersonalAsset 以降低迁移风险。

### 10.4 MemoryEntry

MemoryEntry 保持独立。AssetDraft 可以生成记忆建议，但需要用户确认后写入。

### 10.5 Engine Chat

Engine 新增 asset/memory 工具注册。

现有 `knowledge_search` 保留，作为 RAG 兜底工具。

## 11. 非功能需求

### 11.1 可控性

AI 建议永远不直接落入正式资产、记忆或关系。用户确认是硬边界。

### 11.2 可解释性

AI 解析、分类、关联、扩展建议必须展示理由和置信度。

### 11.3 可扩展性

资产类型、来源类型、媒介类型保持开放字符串，不用硬编码枚举锁死。

### 11.4 可回溯性

PersonalAsset、MemoryEntry、AssetRelation、ExtensionPoint 必须能追溯到 RawItem 和 AssetDraft。

### 11.5 隐私

MemoryEntry 和个人资产默认私有。未来多用户版本必须按 user_id 隔离。

## 12. 成功标准

M3 第一版完成后，用户应能：

1. 粘贴任意内容，让 AI 自动生成可编辑 AssetDraft。
2. 查看 AI 的分类、来源、摘要、关联、扩展建议和置信度。
3. 修改草稿后确认入库。
4. 在 Chat 中询问“我之前发给你的评论都围绕什么内容？”，Agent 能调用 `asset_overview` 并回答。
5. 在 Chat 中询问“我之前对 Prism 第一版有什么偏好？”，Agent 能调用 `memory_search` 并回答。
6. 在 Chat 中使用已确认资产后，系统能记录基础 usage event。

## 13. 待决策问题

1. M3 第一版是否创建真实 `PersonalAsset` 表，还是先用兼容视图聚合 KnowledgeItem/NotebookNote？
2. AssetDraft 是新表，还是复用并扩展 `InboxReviewItem`？
3. 知识类草稿确认后是否继续同步创建 `KnowledgeItem` 以兼容现有 Knowledge 页面？
4. Asset Index 第一版使用数据库搜索，还是确认后立即向量化？
5. 审阅台第一版是否支持批量确认关联和扩展点？
6. Chat 前端是否需要显示 asset tool sources 的新样式？

