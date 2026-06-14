# 计划：对话绑定知识库 + Elasticsearch 混合检索

## 目标

1. 对话页输入框下方增加「选择知识库」按钮，用户可选择主题目录 + 文件类型
2. 用 Elasticsearch 原生 BM25（IK 中文分词）替代当前 MySQL jieba 简单计分，做标准 BM25 全文检索
3. ES BM25 全文检索 + Milvus 向量检索 → min-max 归一化 + 加权融合 → Agentic RAG 问答
   - 融合策略对齐 Comet：向量 0.6 / BM25 0.4，非 RRF（ES match 查询自带 BM25 评分，含 IDF/TF 饱和/字段长度归一化）
4. 检索范围限定在用户选中的主题（topic）内

---

## 架构对比

### 当前
```
ChatPage → POST /chat/answer {query, history}
  → answer_stream → build_agent_runner
    → hybrid_search (MySQL jieba BM25 + Milvus vector, RRF 融合)
```

### 目标
```
ChatPage → POST /chat/answer {query, history, topic_id}
  → answer_stream → build_agent_runner(topic_id)
    → hybrid_search_v2 (ES IK full-text + Milvus vector, 归一化加权融合)
      过滤: topic_id → knowledge_file.item_ids → ES filter + Milvus post-filter
```

---

## 实施步骤

### S1: 基础设施 — ES 服务 + 配置

**docker-compose.yml**: 增加 elasticsearch 服务
- 构建 `docker/es/Dockerfile`（基于 ES 8.17 + analysis-ik 插件）
- ES 端口 9200，单节点模式，1G 堆内存

**docker/es/Dockerfile** (新文件):
```dockerfile
FROM docker.elastic.co/elasticsearch/elasticsearch:8.17.0
RUN bin/elasticsearch-plugin install --batch \
    https://release.infinilabs.com/analysis-ik/stable/elasticsearch-analysis-ik-8.17.0.zip
```

**engine/app/config.py**: 增加 ES 配置
- `ES_HOST`、`ES_USERNAME`、`ES_PASSWORD`

**backend/app/config.py**: 同上

**.env**: 增加 `ES_HOST=http://localhost:9200`

---

### S2: ES 客户端 + 索引管理

**engine/app/es_client.py** (新文件):
- `get_es()` — 同步 ES 客户端单例
- `ensure_index()` — 创建 `prism_chunks` 索引
- `ping()` — 健康检查

**索引 mapping**:
```json
{
  "chunk_id": keyword,
  "item_id": keyword,
  "topic_id": keyword,       // 从 knowledge_file 解析，用于范围过滤
  "content": text (ik_max_word / ik_smart),
  "doc_name": keyword,
  "source_type": keyword,    // document / image / audio / video
  "created_at": date
}
```

---

### S3: 摄入管线改造 — 写入 ES

**engine/app/ingestion/pipeline.py**:
- chunk 文本 + 向量写入 MySQL + Milvus 后，**同步写入 ES**
- 通过 `knowledge_file` 表反查 `item_id` 对应的 `topic_id`
- 写入 ES 文档: `{chunk_id, item_id, topic_id, content, source_type: "document", doc_name}`

---

### S4: ES 全文检索 + 混合检索（替代 BM25）

**engine/app/retrieval/es_search.py** (新文件):
- `es_fulltext_search(query, topic_ids, top_k)` — 用 ES match query + IK 分词做全文检索
- 支持 `topic_id` 过滤

**engine/app/retrieval/hybrid.py** (重构):
- `hybrid_search()` → `hybrid_search_v2()`
- 向量召回: Milvus search（支持 item_id 后置过滤）
- 全文召回: ES search（支持 topic_id 前置过滤）
- 融合: RRF（k=60, 向量 0.6 / BM25 0.4），保持当前 Prism 的融合策略不变
- 保留旧 `hybrid_search` 函数做 fallback

**engine/app/retrieval/vector_search.py** (微调):
- 增加 `allowed_item_ids` 参数，在 Milvus 结果上进行后置过滤

---

### S5: API 链路串联

**engine/app/api/chat.py**:
- `ChatRequest` 增加 `topic_id: Optional[str]`、`source_type: Optional[str]`（默认 `"document"`）

**engine/app/chat/answer.py**:
- `answer_stream(query, history, topic_id, source_type)` — 接收新参数
- `build_agent_runner(topic_id)` — 构造带过滤的搜索闭包
- `_resolve_allowed_item_ids(topic_id)` — 从 `knowledge_file` 查出 topic 下所有 item_id
- 搜索闭包将 `topic_id` 和 `item_ids` 传入 `hybrid_search_v2`

**engine/app/agent/rag/agentic.py**:
- 无需改动（搜索函数通过闭包注入，过滤逻辑对 RAG runner 透明）

---

### S6: 前端 — 知识库选择器 UI + 状态

**frontend/src/app/chatStore.ts**:
- 新增状态: `selectedTopicId`, `selectedTopicName`, `selectedSourceType`
- 新增 actions: `setSelectedTopic`, `setSourceType`, `clearTopic`

**frontend/src/pages/ChatPage.tsx**:
- 输入框下方增加工具栏：
  ```
  [📚 选择知识库 ▼] [已选: 主题名 ✕] [文档 ▾]
  ```
  - 「选择知识库」按钮：点击展开 compact 下拉面板，调用 `knowledgeApi.listTopics()` 列出所有主题
  - 选中后显示 chip 标签（可取消）
  - 文件类型下拉：`全部 | 文档 | 图片 | 音频 | 视频`，当前仅"文档"生效，其余置灰
- `send()` 函数：请求体增加 `topic_id` + `source_type`
- API 类型 `ChatRequest` 也要同步增加字段

**frontend/src/app/api.ts**:
- ChatRequest 类型增加 `topic_id?`、`source_type?`

---

### S7: 端到端验证

1. `docker-compose up -d` 启动全部服务（含 ES）
2. 在知识库页面创建主题 → 上传 PDF/MD/TXT 文档
3. 确认 ES 索引 `prism_chunks` 中有数据（`curl localhost:9200/prism_chunks/_count`）
4. 在对话页面选择该主题 → 提问 → 验证：
   - 检索范围限定在该主题内
   - ES 全文 + Milvus 向量混合生效
   - 回答仅基于该主题文档

---

## 涉及文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `docker-compose.yml` | 修改 | 增加 ES 服务 |
| `docker/es/Dockerfile` | **新建** | ES + IK 镜像 |
| `.env` | 修改 | 增加 ES_HOST |
| `engine/app/config.py` | 修改 | 增加 ES 配置项 |
| `backend/app/config.py` | 修改 | 增加 ES 配置项 |
| `engine/app/es_client.py` | **新建** | ES 客户端 + 索引管理 |
| `engine/app/retrieval/es_search.py` | **新建** | ES 全文检索 |
| `engine/app/retrieval/hybrid.py` | 重构 | ES + Milvus 混合检索 |
| `engine/app/retrieval/vector_search.py` | 修改 | 增加 item_id 过滤 |
| `engine/app/ingestion/pipeline.py` | 修改 | 写入 ES |
| `engine/app/api/chat.py` | 修改 | ChatRequest 增加字段 |
| `engine/app/chat/answer.py` | 修改 | 链路透传 + item_ids 解析 |
| `frontend/src/app/chatStore.ts` | 修改 | 增加 topic 选择状态 |
| `frontend/src/app/api.ts` | 修改 | ChatRequest 类型增加字段 |
| `frontend/src/pages/ChatPage.tsx` | 修改 | 知识库选择器 UI |
