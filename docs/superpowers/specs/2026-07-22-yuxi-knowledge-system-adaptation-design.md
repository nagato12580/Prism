# Prism 知识库系统原生适配设计

Date: 2026-07-22

## 目标

在不复制 Yuxi 技术债的前提下，将其完整的知识库产品设计迁移到 Prism：覆盖知识库与文档生命周期、解析与分块、Milvus + Elasticsearch + Neo4j 检索、Rerank、Agent Skill 与工具、引用、图谱构建与治理、知识导图、检索评估、任务容错和 React 管理页面。

本设计供后续 Agent 编写实施计划并改造 `H:\Agent\Project\Prism\prism`。本文只定义目标行为、边界与验收标准，不包含实现代码。

## 已确认决策

1. 采用“Prism 原生适配”，不直接复制 Yuxi 模块。
2. 只建设自建知识库；Dify、Notion 只读连接器不做。
3. Neo4j 知识图谱纳入第一阶段完整实现。
4. Prism Backend 负责控制面；Prism Engine 负责 AI/RAG 数据面。
5. 原始文件第一阶段继续使用 Prism 本地 `uploads_data` 持久卷，通过 `FileStorage` 接口隔离实现；不迁移业务文件到 MinIO/S3。
6. 第一阶段不扩建完整用户、组织和角色平台；保留当前单用户形态，但移除业务代码中的硬编码主体，并预留租户边界。
7. 知识库不映射进 Agent 沙箱；聊天附件也不会自动进入知识库。
8. Yuxi 的 LightRAG 描述不是当前运行能力，不迁移。

## 调查依据

### Yuxi 当前事实

- 知识库运行时实际注册 Milvus、Dify、Notion，LightRAG 未注册：`Yuxi-main/backend/package/yuxi/knowledge/runtime.py:12`。
- Milvus 支持向量、BM25、混合检索、可选 Rerank 与图检索：`Yuxi-main/backend/package/yuxi/knowledge/implementations/milvus.py:82`、`:889`。
- 文件状态是 `uploaded/parsing/parsed/error_parsing/indexing/indexed/error_indexing`：`Yuxi-main/backend/package/yuxi/knowledge/base.py:32`。
- Agent 知识工具由内置 `knowledge-base` Skill 按需加载：`Yuxi-main/backend/package/yuxi/agents/skills/buildin/knowledge-base/SKILL.md:7`。
- 工具包括 `list_kbs`、`query_kb`、`search_file`、`find_kb_document`、`open_kb_document`、`get_mindmap`：`Yuxi-main/backend/package/yuxi/agents/toolkits/kbs/tools.py:462`。
- 知识库不会映射为沙箱目录：`Yuxi-main/docs/agents/sandbox-architecture.md:106`。
- 管理页面包括文件、检索、图谱、思维导图和评估，但文件 Chunk 只读：`Yuxi-main/web/src/views/DataBaseInfoView.vue:1`、`Yuxi-main/web/src/components/FileDetailModal.vue:1`。

### Prism 当前事实

- 三进程共享 MySQL；Backend 管 CRUD/解析/队列，Engine 管 AI/RAG：`CLAUDE.md`、`docs/GRAPH_CHAIN_ARCHITECTURE.md`。
- 原文件保存在本地上传目录；解析正文在 MySQL；没有业务 MinIO/S3 client。
- 已有 `KnowledgeTopic`、`KnowledgeFile`、`KnowledgeItem`、`KnowledgeChunk`：`backend/app/models/knowledge_item.py:20`。
- 已有可重试任务表 `KnowledgeJob`：`backend/app/models/knowledge_job.py:14`。
- 已有 Entity/Alias/Mention/Relation 和 PKU/CKP 治理模型：`backend/app/models/entity.py:17`、`backend/app/models/knowledge_governance.py:16`。
- 现有统一检索是 Dense + ES BM25 + 图扩展 + Rerank + Agentic Rewrite：`engine/app/retrieval/unified.py:251`、`engine/app/agent/rag/agentic.py:50`。
- 当前权限仍固定使用 `default-user`：`backend/app/api/knowledge.py:30`。
- 当前前端入口为 `/knowledge`、`/chat`、`/graph`：`frontend/src/app/routes.tsx:16`。

## Yuxi 能力取舍矩阵

| 能力 | Yuxi 当前状态 | Prism 决策 |
|---|---|---|
| Milvus 文档知识库 | 完整 CRUD、入库和检索 | 第一阶段完整实现，复用 Prism 模型与 Engine |
| Dify / Notion | 只读连接器 | 明确不做 |
| LightRAG | 已不受支持 | 不做 |
| 本地文件/多文件上传 | 已实现 | 完整实现，增加逐文件进度、取消与错误详情 |
| 文件夹上传 | 前端逐文件队列；后端遗留死接口 | 以浏览器目录枚举实现，保留相对路径，不复制死接口 |
| URL 导入 | 已实现 | 完整实现，沿用 Prism 已有 URL 能力并增加相同状态机 |
| Workspace 导入 | Yuxi 特有 | 不做；Prism 没有等价工作区资源边界 |
| Markdown 直接创建 | 已实现 | 作为文本资源上传形式支持，不单建重复领域模型 |
| 解析器/OCR 注册表 | 多种本地/远端实现 | 建 Parser Registry；首期适配 Prism 已部署解析器，能力由后端动态返回 |
| 六种分块 Preset | general/qa/book/laws/semantic/separator | 沿用策略概念；结合 Prism 父子 Chunk 实现并保存配置快照 |
| Dense / Keyword / Hybrid | Milvus 内完成 | Dense 用 Milvus，Keyword 用 Elasticsearch，一次性 RRF 融合 |
| Rerank | 可选 | 完整实现，并修复 Prism 当前 UUID 代替正文的问题 |
| 图谱构建与检索 | Milvus + Neo4j + PG | 第一阶段完整实现，MySQL 事实源 + Outbox 投影 |
| Mindmap | 文件元数据生成、支持增量 | 完整实现，版本化保存，Agent 可读 |
| 示例问题 | 基于文件列表生成 | 完整实现为后台任务；以代表性 Chunk + 元数据生成，可保存为评估样例 |
| Query Test / 参数配置 | 已实现 | 迁入“检索实验室” |
| RAG Evaluation | 数据集、运行、指标 | 第一阶段完整实现 |
| 文件预览/Markdown/Chunk | 只读 | 完整实现只读预览；Chunk 在线编辑不做 |
| 知识库导出 | 数据与可选向量导出 | 第一阶段只导出配置、清单、Markdown、评估和图事实；向量导出暂缓 |
| CLI 批量上传 | 已实现 | 暂缓；先稳定 Public REST，后续 CLI 复用同一 API |
| Dashboard 统计 | 已实现 | 知识库列表与详情提供必要统计；不单建全局 BI 项目 |

## 1. 总体架构

### 1.1 Backend：控制面

职责：

- 外部认证适配、知识库级授权和安全响应装配。
- 知识库、文件、任务、评估和配置的 MySQL 元数据。
- `FileStorage`：上传 staging、正式文件、Markdown、预览与解析资源。
- MySQL Job 事实状态和 Redis 命令投递。
- Public REST、Job SSE、Chat Engine 代理。
- 删除、重建和配置变更等危险操作的入口校验。

Backend 不负责：Embedding、向量检索、融合、Rerank、LLM 图谱抽取或 Agent 工具执行。

### 1.2 Engine：数据面

职责：

- Parser Registry、OCR、Markdown 标准化。
- 父子分块与其他 Preset。
- Embedding、Milvus、Elasticsearch 索引与查询。
- Dense/BM25/Graph 融合与 Rerank。
- 实体/关系抽取、图投影、图分析和 PKU/CKP 治理。
- Knowledge Skill、知识工具、Agentic Judge/Rewrite。
- 对话 NDJSON 流。

Engine 不重新判断用户角色。它只消费 Backend 签发的 `ActorContext` 与 `allowed_kb_uids`，并在每个工具和查询入口强制执行范围 Guard。

### 1.3 Frontend：体验面

- 知识库管理页面只调用 Backend。
- Prism 当前 Chat 流可在迁移期保持，但最终由 Backend 代理 Engine，避免浏览器依赖内部协议。
- Job 使用“快照 + SSE 增量”；Chat 继续使用 NDJSON。

## 2. 领域模型与 MySQL

### 2.1 KnowledgeTopic 作为 KnowledgeBase 聚合根

不新建平行 `knowledge_base` 表。演进现有 `knowledge_topic`：

- 保留自增 `id` 作为数据库内部键。
- 新增公开稳定 `kb_uid`，使用 Prism 现有惯例的 UUID v4 字符串（MySQL `CHAR(36)`）并加唯一索引。
- `tenant_id`、`owner_user_id` 非空；当前适配器填充默认主体。
- `name`、`description`、`status`、`deleted_at`、`version`。
- `embedding_profile`、`parser_config`、`chunk_config`、`retrieval_config`、`graph_config`。
- `active_index_generation`、`active_graph_generation`。
- `mindmap`、`mindmap_version`、`mindmap_generated_at`。
- `sample_questions`、`sample_questions_version`。

配置更新使用乐观锁 `version`。模型或分块配置变化不会原地篡改活动索引，而是创建新 generation。

### 2.2 KnowledgeFile

复用现有文件表，补充：

- `file_uid` 稳定公开 ID。
- `kb_uid`/Topic 外键作用域。
- `storage_uri`，不向客户端返回真实路径。
- `relative_path`、`original_filename`、`media_type`、`content_sha256`、`size_bytes`。
- `parser_config_snapshot`、`chunk_config_snapshot`。
- 分离的 `parse_status`、`index_status`、`graph_status`。
- `parsed_content_version`、`active_index_generation`。
- 每阶段 `error_code`、`error_message`、时间戳和最后 Job ID。
- `deleted_at` tombstone。

保留旧 MD5 用于兼容查询，但新去重与幂等以 SHA-256 为准。

### 2.3 KnowledgeItem 与 KnowledgeChunk

继续使用“文件 → 逻辑文档 → Chunk”三层：

- Item 保存规范化 Markdown、摘要、来源类型和内容版本。
- Chunk 新增 `chunk_uid`、`kb_uid`、`file_uid`、`generation`。
- 保留父子 Chunk，修复 `parent_id` 的领域/外键约束。
- 保存页码、字符位置、token 位置、标题路径等结构化位置。
- `embedding_id` 不再作为唯一同步依据；外部索引统一使用 `chunk_uid + generation`。

### 2.4 KnowledgeJob

复用现有表，补充：

- `tenant_id`、`kb_uid`、`file_uid`。
- `idempotency_key` 唯一约束。
- `payload`、`result` JSON。
- `lease_owner`、`lease_expires_at`、`heartbeat_at`。
- `cancel_requested_at`、`canceled_by`。
- `attempt`、`max_attempts`、`next_run_at`。
- `stage`、`progress_current`、`progress_total`。
- 结构化 `error_code`、`error_message`、`retryable`。

Redis 只传递 Job ID/命令；MySQL 才是任务事实来源。

### 2.5 图谱与评估

- 复用 Entity/Alias/Mention/Relation、PKU/CKP 和社区表。
- 所有唯一约束、查询和投影增加 `tenant_id + kb_uid` 作用域。
- Mention 必须回链 `file_uid/item_id/chunk_uid` 和 evidence span。
- 新增 Evaluation Dataset、Dataset Item、Run、Run Item。
- Run 保存不可变 Retrieval Config、模型版本和索引 generation 快照。

### 2.6 迁移机制

正式引入 Alembic。现有 `auto_migrate` 只能创建表、加列和少量约束，不足以处理回填、索引变更和可逆迁移：`backend/app/utils/auto_migrate.py:6`。

SQLite 只验证 ORM 和纯逻辑。MySQL 方言、迁移、唯一约束竞争、`SELECT FOR UPDATE`、事务隔离必须使用真实 MySQL 集成测试。

## 3. 主体与权限

定义：

```text
Request -> ActorContextProvider -> KnowledgeAccessPolicy -> Repository -> EngineCommand
```

`ActorContext` 至少包含：

- `actor_id`
- `tenant_id`
- `roles`
- `request_id`

当前 `ActorContextProvider` 可返回兼容主体，但 `api/knowledge.py`、Repository 和 Engine 禁止自行回退 `default-user`。

第一阶段权限：

- Owner 可管理、检索和删除自己的知识库。
- 非 Owner 默认无访问。
- 管理 API、检索 API、Mindmap、Graph、Evaluation、Agent Tool 使用同一个 Policy。
- 表中预留成员/ACL 扩展边界，但第一阶段不做组织与成员 UI。

AgentRun 由 Backend 签发只读 `AuthorizedKnowledgeScope`：

- `actor_id`
- `tenant_id`
- `allowed_kb_uids`
- `expires_at`
- `run_id`
- 签名/内部服务认证

模型不能通过工具参数覆盖这些字段。

## 4. 文件、解析与索引状态机

### 4.1 文档主流程

```text
STAGED -> REGISTERED -> PARSED -> CHUNKED -> INDEXING -> INDEXED -> GRAPH_READY
```

这些是聚合视图，不用一个自由字符串承载所有阶段。每个阶段使用受控枚举：

- `pending`
- `running`
- `succeeded`
- `failed`
- `stale`
- `skipped`

### 4.2 上传 Saga

1. Backend 将文件写入同一卷的 staging 区并流式计算 SHA-256。
2. 校验扩展名、大小、媒体类型和去重策略。
3. 创建 STAGED 文件记录与 Job。
4. `FileStorage.commit()` 在同一文件系统原子移动到正式 key。
5. 更新为 REGISTERED 并投递解析命令。
6. 定时 Reaper 清理超时 staging 文件和无引用记录。

文件夹上传由浏览器枚举文件并保留 `relative_path`，仍调用同一个单文件协议，不建立 Yuxi 已失效的 `/upload-folder` 特殊端点。

### 4.3 Redis Worker 语义

- 交付语义：至少一次。
- 正确性来源：幂等键、条件抢占、租约和版本。
- Worker 使用 Compare-And-Set 将 Job 从 queued 变为 claimed/running。
- Heartbeat 维持租约；过期 Job 可以重新领取。
- 取消是协作式的；阶段边界检查 `cancel_requested_at`。
- 不支持格式、配置非法、维度冲突、权限失败不重试。
- 429、连接重置、超时和依赖暂时不可用使用指数退避 + jitter。

### 4.4 Generation 发布

重索引不得先删除旧索引：

1. 为新配置创建 generation。
2. 将新 Chunk 写入 Milvus 和 Elasticsearch，均携带 generation。
3. 校验数量、向量维度、文档映射和抽样查询。
4. MySQL 原子切换 `active_index_generation`。
5. 后台清理旧 generation。

任一新写失败时删除未发布 generation，旧索引继续服务。

### 4.5 删除

1. 先写 tombstone，使资源立即不可见。
2. 投递幂等清理 Job。
3. 清理 Milvus、ES、图 Mentions/Outbox 投影、本地文件和 MySQL 子记录。
4. 每个步骤记录 checkpoint，可从失败位置续跑。
5. 清理完成后物理删除文件领域记录；任务审计信息继续保存在 `KnowledgeJob`，不长期保留可被业务查询的文件墓碑。

## 5. 检索策略

### 5.1 单轮顺序

```text
Query Plan
  -> parallel(Dense, BM25, Graph)
  -> one Weighted RRF
  -> batch load child texts
  -> Rerank
  -> Small-to-Big parent/neighbor expansion
  -> Evidence DTO
```

修正 Prism 当前行为：

- 不再把已经融合的 Hybrid 列表作为一路再次 RRF。
- Rerank 前先加载正文，不把 `chunk_id` UUID 当文档。
- 三路均前置做租户、知识库、generation 和来源过滤。
- 图候选必须遵循 Topic/File/Source 范围。
- 每路返回健康状态；异常不转成空数组。

### 5.2 索引布局

Milvus 标量字段至少包括：

- `tenant_id`
- `kb_uid`
- `file_uid`
- `item_id`
- `chunk_uid`
- `source_type`
- `generation`
- `embedding_model_version`

必须使用原生 pre-filter。禁止继续依赖“MySQL allowed item IDs + 召回后过滤”。

Milvus collection 不按单个知识库创建，也不继续使用一个固定维度的全局 collection。新增 `VectorIndexRegistry`：

- `embedding_profile_id = hash(provider + model + dimension + metric + normalization)`。
- 每个 Profile 对应一个文档 collection：`prism_kb_<profile_hash>`。
- 图实体/关系向量使用独立 collection：`prism_graph_<profile_hash>`。
- 同一 collection 内以 `tenant_id + kb_uid + generation` 原生过滤。
- 知识库切换 Embedding Profile 必须创建新 generation，校验后再切换，不能在原 collection 原地混用向量空间。

Elasticsearch 文档使用同一组作用域字段，以 `kb_uid` 做 routing，并使用活动 generation 过滤。保留 IK 分词与 BM25，增加标题/正文分字段权重；MySQL + jieba 全表扫描不作为生产 fallback。

Neo4j 的 Seed、Path、Community、God/Surprising 查询全部带 `tenant_id + kb_uid`，证据最终回到 `chunk_uid`。

### 5.3 默认参数

- Dense candidates: 50
- BM25 candidates: 50
- Graph candidates: 30
- Weighted RRF: `k=60`
- 默认权重：Dense 0.45 / BM25 0.35 / Graph 0.20
- Rerank top N: 20
- 最终 Evidence: 8
- Agentic iterations: 最多 3

图谱未 ready 时，在 Dense/BM25 间重新归一化权重。模型相关阈值默认关闭，由具体 Embedding/Rerank Profile 显式配置，避免跨模型使用不可比较阈值。

### 5.4 Agentic Rewrite

- 标准模式默认单轮。
- 深度模式允许 LLM Judge 判断证据是否充分并给出不同的 `rewrite_query`。
- 只有新查询与当前查询归一化后不同才进入下一轮。
- 跨轮 Evidence 累积去重，不覆盖上一轮。
- `depth`、`limit` 和模式必须真正进入 Runner 配置，不再只写进 Prompt。

### 5.5 故障状态

- `no_hits`：所有必需通道正常但无命中。
- `degraded`：部分通道、Rerank 或 Judge 降级，仍有可用结果。
- `unavailable`：必要检索通道均不可用。
- `invalid_request`：授权范围、过滤或配置非法。

## 6. Evidence 与引用

统一 Evidence DTO：

- `evidence_id`
- `tenant_id`、`kb_uid`
- `file_uid`、`item_id`、`chunk_uid`、`parent_chunk_uid`
- `display_title`、`original_filename`
- `excerpt`
- `page_start/page_end`
- `char_start/char_end`
- 每路 `raw_score/raw_rank`
- `rrf_score`
- `rerank_score`、`rerank_model`
- `retrieval_channels`
- `graph_path`、`graph_explanation`、`evidence_type`
- `index_generation`
- `degradation_flags`

每轮回答将 Evidence 映射为短 ID，如 `K1`。模型只能使用 `[K1]` 引用。本轮输出结束后校验引用 ID：未知引用被标记为无效，不允许前端生成虚假来源卡。

点击引用时，Frontend 使用公开 ID 调 Backend 打开文件、页码和版本化原文窗口。

## 7. Knowledge Skill 与工具

### 7.1 工具集合

1. `list_kbs()`
   - 返回当前 AgentRun 可见知识库的 `kb_uid/name/description/status`。
   - 不接受 dummy 参数，不返回配置密钥或内部路径。
2. `query_kb(kb_uid, query_text, mode="standard", file_filter=None)`
   - 调用统一检索；返回 Evidence 与通道健康状态。
3. `search_file(kb_uid=None, query=None, cursor=None, limit=50, media_types=None)`
   - MySQL 服务端分页；total/has_more 必须基于完整查询语义。
4. `find_kb_document(kb_uid, file_uid, patterns, use_regex=False, case_sensitive=False, max_windows=5, window_size=80)`
   - 关键词/Regex 原文定位，不宣称语义检索。
5. `open_kb_document(kb_uid, file_uid, line=None, offset=None, window_size=500)`
   - 打开版本化 Markdown 窗口；返回前后分页标志。
6. `get_mindmap(kb_uid)`
   - 通过同一 Tool Guard 校验授权，返回导图版本和生成时间。

### 7.2 统一工具结果

```json
{
  "status": "ok | no_hits | degraded | error",
  "data": {},
  "warnings": [],
  "error": null,
  "trace_id": "..."
}
```

领域预期错误返回结构化 `error.code/message/retryable`。程序错误仍作为 Tool 执行失败记录，不能伪装成普通中文字符串。

### 7.3 Skill 行为

Knowledge Skill 向模型说明：

- 不知道 KB 时先 `list_kbs`。
- 具体问题先 `query_kb`。
- 片段不足时使用 `open_kb_document`。
- 精确术语/章节定位使用 `find_kb_document`。
- 文件名发现使用 `search_file`。
- 知识结构问题使用 `get_mindmap`。
- 事实回答必须引用本轮 Evidence。

Prism 现有 Agentic RAG 作为 `query_kb` 内部编排服务，不再向模型暴露语义重叠的多套知识检索工具。

### 7.4 沙箱与附件边界

- KB 文件不挂载到 Agent 文件系统。
- 工具不返回 `storage_uri`、宿主机路径或租户字段。
- 聊天附件属于会话文件，不自动入库。
- “保存到知识库”必须是显式用户操作，并进入正常上传/解析状态机。
- Agent 知识工具只读；不能创建、删除、重建或修改 KB。

## 8. 知识图谱

### 8.1 事实源与投影

MySQL 是抽取事实、证据和治理状态的事实源。Neo4j 与图向量索引是可重建投影。

构建流程：

```text
Active Chunk Selection
  -> Structured LLM Extraction
  -> Entity/Relation Normalization
  -> MySQL Entity/Mention/Relation commit
  -> Transactional Outbox
  -> Neo4j + Graph Vector projection
```

Outbox 与事实数据在同一 MySQL 事务提交。Projector 使用事件 ID 幂等写入并记录 cursor、attempt 和错误。`graph_status=ready` 要求必要投影追平；有失败事件时为 `degraded`。

`active_graph_generation` 表示图抽取配置版本，而不是每次新增文件都复制一份全图：

- Extractor Model、Prompt 或 Schema 变化时创建新 graph generation；全部抽取与必要投影完成后原子切换。
- 同一配置下新增/修改文件使用当前 graph generation，只增加新的 Chunk extraction revision 和 Outbox 事件。
- 查询同时过滤 active graph generation 与 active Mention revision，避免读取旧配置或已被文件更新替换的证据。

### 8.2 增量与删除

- Extraction Key：`kb_uid + chunk_uid + content_hash + extractor_config_hash`。
- 只重新抽取变化 Chunk。
- 文件删除只移除该文件的活跃 Mentions。
- Entity/Relation 无任何活跃 Mention 后才进入删除投影。
- “重建投影”只重放 MySQL/Outbox，不调用 LLM。
- “重新抽取”创建新 extraction generation，会产生模型费用。

### 8.3 图检索

1. Alias/normalized name 精确匹配。
2. Entity/Relation 图向量召回。
3. 标准模式 1-hop；深度模式 2-hop + Community + PPR/God/Surprising。
4. 过滤 `tenant_id + kb_uid + generation`。
5. 按 Seed 相似度、边置信度和路径长度衰减评分。
6. 通过 Mention 回链 Chunk，加入统一 RRF。

### 8.4 可信度

- Extracted Relation 必须保存文件、Chunk、evidence span、模型/Prompt 版本和 confidence。
- Inferred Path 必须标记为 `INFERRED` 并返回完整路径，不能伪装为文档明确陈述。
- 默认只有 active/approved PKU/CKP 参与回答。
- 图失败不阻断文本入库与 Dense/BM25 检索。

## 9. Mindmap、示例问题与评估

### 9.1 Mindmap

- 输入使用文件树、标题路径和有限代表性摘要，不只依赖前 20 个文件。
- 作为后台 Job 生成并版本化。
- 支持增量 diff：新增、删除、移动、重命名。
- 纯删除可以确定性修改树，不调用 LLM。
- `get_mindmap` 返回当前 active 版本。

### 9.2 示例问题

- 从文件元数据与分层采样的代表性 Chunk 生成。
- 保存生成时的 KB generation、模型与 Prompt 版本。
- 检索实验室可以将问题一键保存为 Evaluation Dataset Item。
- 文件变化只标记 sample questions stale，不在页面轮询中自动反复调用模型。

### 9.3 RAG Evaluation

支持：

- JSONL 数据集导入/导出。
- 基于 Chunk 生成测试问题。
- Gold Chunk、Gold Answer。
- Recall@K、MRR、NDCG 等检索指标。
- 可选生成答案与 Judge 指标。
- Run 固定 Retrieval Config、模型与 generation，保证结果可比较。
- Run 在后台执行，支持取消、进度和逐题失败。

## 10. Public API 与事件

### 10.1 Public REST 资源

统一前缀：`/api/v1/knowledge-bases`。

资源组：

- Knowledge Base CRUD / stats / settings
- Files upload / register / list / detail / preview / download / delete
- Parse / index / graph commands
- Jobs snapshot / cancel / retry
- Retrieval query / test / config
- Graph config / build / projection rebuild / re-extract / reset / subgraph
- Mindmap get / diff / generate
- Sample questions get / generate
- Evaluation datasets / runs
- Accessible KBs for Agent configuration

所有 `{kb_uid}` 入口先调用同一个 `KnowledgeAccessPolicy`。

### 10.2 Job SSE

事件：

- `job.created`
- `job.claimed`
- `job.progress`
- `job.succeeded`
- `job.failed`
- `job.canceled`

字段至少包含：`seq/event_id/job_id/kb_uid/file_uid/stage/progress/status/timestamp/error`。

客户端重连流程：先 GET Job 快照，再从最新序号订阅 SSE。Redis Streams 承载短期事件并设置 24 小时/每 Job 10000 条的双重保留上限；MySQL Job 始终是恢复事实源。

### 10.3 Chat NDJSON

保留 Prism 的 `agent_status/tool_call/tool_result/trace/clarify/sources/token/error/title/done`，统一补充：

- `seq`
- `trace_id`
- `run_id`
- Retrieval channel health
- Evidence DTO
- Degradation warnings

### 10.4 错误契约

```json
{
  "error": {
    "code": "VECTOR_INDEX_UNAVAILABLE",
    "message": "向量检索暂时不可用",
    "retryable": true,
    "details": {"channel": "dense"},
    "trace_id": "..."
  }
}
```

API 不返回模型密钥、内部 URL、真实文件路径或完整堆栈。

## 11. React 信息架构

### 11.1 路由

- `/knowledge`
- `/knowledge/:kbUid/files`
- `/knowledge/:kbUid/retrieval`
- `/knowledge/:kbUid/graph`
- `/knowledge/:kbUid/governance`
- `/knowledge/:kbUid/mindmap`
- `/knowledge/:kbUid/evaluation`
- `/knowledge/:kbUid/settings`

Topic/KB 选择进入 URL，支持刷新恢复、分享和浏览器前进后退。

### 11.2 文件工作台

- 服务端分页、目录/相对路径、状态过滤、批量选择。
- 多文件与文件夹上传、URL 导入、逐文件进度、取消、失败详情和重试。
- 批量解析、批量索引、图谱构建。
- Document Drawer：原文件、Markdown、Chunk、处理历史。
- Chunk 第一阶段只读。

### 11.3 检索实验室

- Standard/Deep 模式。
- 临时覆盖 Query Config，不污染持久设置。
- 展示每路 raw rank/score、RRF、Rerank、Graph Path 和降级状态。
- 将查询和 Evidence 保存为评估样例。

### 11.4 图谱与治理

- 复用 Prism Entity/Source 双视图、Graph Canvas 和 Inspector。
- 增加 KB scope、构建/投影状态、过滤、图路径解释。
- 恢复并路由现有 Governance Workbench。
- “重建投影”与“重新抽取”使用不同按钮和费用提示。

### 11.5 Chat 引用闭环

```text
Retrieval Scope Picker
  -> Tool Timeline
  -> Assistant [K1]
  -> Evidence Drawer
  -> highlighted document window or graph path
```

Tool Evidence 与最终 Sources 合并成一套组件。不同通道分数显示原始含义，不包装成统一“匹配百分比”。

### 11.6 前端代码边界

```text
features/knowledge/
  api/
  stores/
  pages/
  components/
features/chat/
  RetrievalScopePicker
  ToolRunTimeline
  EvidenceList
  CitationCard
features/graph/
  GraphCanvas
  GraphControls
  GraphInspector
  GovernanceWorkbench
```

拆分当前巨型 `api.ts`、KnowledgePage 和 GraphPage。建立共享 Button、Input、Badge、Card、Dialog、Progress、Toast、Tabs、EmptyState；继续使用 Prism token、Tailwind 和 Lucide。

Job 进度使用 SSE；只有 SSE 不可用时才指数退避轮询，不再每 3 秒全量刷新资源列表。

## 12. 观测、安全与运行边界

### 12.1 Trace

每次入库/查询串联：

- `trace_id`
- `request_id`
- `run_id`
- `job_id`
- `kb_uid`
- `file_uid`
- `generation`

Span 覆盖解析、分块、Embedding、Milvus、ES、Neo4j、RRF、Rerank、Judge、投影和引用解析。

### 12.2 指标

- 队列深度、租约超时、重试率和取消率。
- 各阶段成功率与耗时。
- Milvus/ES 文档数与 active generation 一致性。
- Outbox Projection Lag 和失败事件数。
- 各召回通道候选数、空命中率、降级率。
- Rerank/Judge 耗时与失败率。
- 引用解析成功率和无效引用率。

### 12.3 日志

结构化日志可以包含公开资源 ID 和错误码，禁止包含：

- 文档正文或大段 Chunk。
- API Key/Token。
- `storage_uri` 真实路径。
- 完整 `ActorContext`。
- Provider 原始错误响应中的敏感字段。

## 13. 测试策略

### 13.1 Unit

- 状态机合法/非法转换。
- Job 条件抢占、租约和幂等键。
- Parser/Chunk Preset 与配置快照。
- Weighted RRF、去重、正文 Rerank 顺序。
- Tool Guard 与 KB 越权。
- Evidence/Citation 校验。
- Outbox Projector 幂等。
- 文件删除 Mention/孤儿实体规则。

### 13.2 Contract

- Public Pydantic Schema。
- Backend -> Redis Command。
- Worker payload/result。
- Backend -> Engine 同步检索。
- Job SSE 和 Chat NDJSON 事件版本。
- Frontend DTO 生成或 TypeScript 契约测试。

### 13.3 Integration

真实容器运行：

- MySQL migration、锁、唯一约束竞争。
- Redis 至少一次交付、重复投递和 worker crash 恢复。
- Milvus pre-filter、generation 切换与维度校验。
- Elasticsearch IK/BM25、routing、generation 与故障恢复。
- Neo4j scope、Outbox 重放、增量删除和路径证据。
- Rerank provider 协议与结果长度校验。

### 13.4 E2E

1. 创建 KB -> 上传 -> 解析 -> 索引 -> Query -> 引用打开。
2. 新索引构建失败，旧 generation 仍返回结果。
3. ES 故障时返回 degraded，不是 no_hits。
4. Milvus + ES 都失败时返回 unavailable。
5. 两个 KB 含相似内容，不发生跨 KB 命中。
6. 图谱构建、图检索、Evidence 回链。
7. 删除一个文件，只删除其 Mention，不误删其他文件实体。
8. 重放 Outbox 后 Neo4j/Milvus 图投影收敛。
9. Job 取消与失败重试。
10. Evaluation Run 固定配置和 generation。

### 13.5 Load

- 10 万文件时服务端分页和筛选。
- 大批量上传采用有界并发，不一次创建全部 Future/Promise。
- 多 Worker 抢占同一 Job。
- 高并发 Query 下 Milvus/ES/Neo4j 连接池与总 deadline。

## 14. 迁移与发布

### 14.1 实施顺序

1. Alembic、稳定 UID、ActorContext、FileStorage、Job 增强。
2. 上传/解析/分块状态机和 generation 索引。
3. 三路召回、一次 RRF、正文 Rerank、Evidence。
4. Knowledge Skill、六工具、Citation/Chat。
5. 图谱 Outbox/Projection、Graph/Governance UI。
6. Mindmap、示例问题、Evaluation、Settings。
7. 旧数据切换与遗留路径清理。

### 14.2 旧数据迁移

```text
Expand schema
  -> backfill kb_uid/file_uid/chunk_uid and tenant/owner
  -> map local storage_path to storage_uri
  -> build new index generation beside legacy indexes
  -> backfill graph kb scope and outbox projection
  -> verify counts and sampled queries
  -> switch read feature flag
  -> monitor
  -> remove legacy indexes and code paths
```

不长期双写。切换前可以影子查询比较旧/新结果，但新链路成为事实来源后应删除临时兼容分支。

## 15. 风险清单

1. Prism 当前没有真实认证；若未来多用户接入时遗漏 ActorContext，将形成越权。所有领域入口必须先收敛到 Policy。
2. 现有图谱全图分析每次入库可能昂贵；第一阶段保留能力但改为 Job/dirty-batch 调度，并暴露进度。
3. Milvus collection 当前缺少 scope/generation 字段；必须旁路建新 schema，不能原地假设兼容。
4. 当前 ES 异常被吞成空数组；迁移时必须修改错误传播，否则无法实现健康状态。
5. 当前 Rerank 很可能输入 UUID；必须以集成测试证明 Provider 收到正文。
6. 现有 graph seed/expand 缺 KB 过滤；这是上线阻断级安全问题。
7. 当前 SQLite mock 测试不能证明真实基础设施链路；关键验收必须跑真实服务。
8. 本地持久卷适合单机/固定部署；FileStorage 边界必须保持，以便后续横向扩展时迁移对象存储。
9. 全量功能跨度较大，必须按可运行切片实施；每一阶段都应保持 Chat 主链路可用。

## 16. 明确不做

- Dify、Notion 或其他只读知识连接器。
- LightRAG。
- 第一阶段迁移业务文件到 MinIO/S3。
- 完整组织、部门、成员、角色管理产品。
- Chunk 在线编辑、多人协作和版本合并 UI。
- 把知识库文件映射到 Agent 沙箱。
- 让 Agent 修改、删除或重建知识库。
- 长期维护旧/新双写链路。
- 第一阶段导出 Milvus 向量文件。
- 第一阶段新增 CLI 客户端。

## 17. 验收标准

1. Prism 可以创建知识库、上传文件/目录/URL、解析、分块、索引、预览和删除。
2. 所有异步阶段有 Job ID、结构化状态、进度、取消、重试和可恢复错误。
3. 新 generation 失败不影响旧索引查询。
4. Dense、BM25、Graph 使用统一授权与 KB scope；测试证明无跨库召回。
5. 三路只融合一次，Rerank 明确接收正文并保留分数。
6. no_hits、degraded、unavailable、invalid_request 对 API、工具和 UI 含义一致。
7. 六个知识工具使用统一 typed envelope，Mindmap 不可越权。
8. Agent 回答的每个 `[Kx]` 都能解析到本轮 Evidence，并打开对应原文。
9. 图谱实体/关系可回链文件、Chunk 和 evidence span；推断路径明确标识。
10. 文件删除和 KB 删除可重复执行，并最终清理 MySQL、Milvus、ES、Neo4j 和本地文件。
11. React 页面具备可深链路由、文件工作台、检索实验室、图谱/治理、Mindmap、Evaluation 和 Settings。
12. SQLite 单测、真实 MySQL/Redis/Milvus/ES/Neo4j 集成测试及核心 E2E 全部通过。

## 18. 后续实施要求

后续 Agent 必须先使用 `superpowers:writing-plans` 将本设计拆成多个可独立验证的实施计划，再使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 执行。不要把全部能力作为一个不可审查的大提交。

建议至少拆为六个计划：

1. Foundation / Schema / Actor / Storage / Jobs
2. Ingestion Lifecycle / Generation Indexing
3. Unified Retrieval / Evidence / Evaluation Core
4. Knowledge Skill / Tools / Chat Citation
5. Graph Outbox / Projection / Governance
6. React Knowledge Product / Cutover
