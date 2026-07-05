# 知识图谱为中心的架构迁移计划

> **目标**：将知识图谱从 MySQL 的被动投影副本，提升为知识治理的中心导航和拓扑推理层。MySQL 中的 chunk / assetUnit 保留为内容仓库和来源证据，向量检索（Milvus）保留为语义召回层，CKP/PKU 治理表逐步降级为图谱节点的后端内容索引，最终用户和 RAG 链路都通过图谱导航。

> **原则**：渐进迁移，每阶段可独立交付、可独立验证、可回退。不一步到位废弃 MySQL。

---

## 当前架构（迁移前）

```
chunk/assetUnit → [治理抽取] → PKU/CKP (MySQL) → [手动 backfill] → Neo4j (只读副本)
                                                      ↑
                                               entity_graph_search (engine agent 唯一消费者)

前端图谱页 ──→ GET /knowledge-graph ──→ MySQL join 组装 (不碰 Neo4j)
向量检索    ──→ Milvus (prism_ckp / prism_pku / prism_knowledge / prism_memory)
```

**问题**：
- Neo4j 里有 1447 实体 / 1782 别名 / 2401 提及关系，前端完全看不到
- 前端图谱页和 Neo4j 是两套独立数据源，关系结构不统一
- 投影靠手动脚本，Neo4j 数据会过时
- Entity→Entity 关系（AUTHORED / CO_AUTHOR）数据为空，实体社交网络无法使用

---

## 目标架构（迁移后）

```
                        ┌──────────────┐
                        │   前端图谱    │  用户唯一导航入口（力导向图）
                        └──────┬───────┘
                               │ Cypher / REST
                    ┌──────────▼──────────┐
                    │      Neo4j          │  权威拓扑：节点 + 关系 + 属性 + status
                    │  (中心：图谱为中心)   │  每个节点挂 source_ids[] + embedding_id
                    └──┬───────────────┬──┘
           回查原文     │               │  embedding_id 回查
              ┌────────▼───┐    ┌──────▼──────┐
              │  MySQL     │    │   Milvus    │
              │ chunk 表    │    │  语义检索    │
              │ assetUnit  │    │  (不变)      │
              │ (内容仓库)  │    └─────────────┘
              └────────────┘
```

**关键变化**：
- 图谱节点直接挂 chunk / assetUnit（`:Concept -[:SUPPORTED_BY]-> :Source`），不需要 PKU 中间层
- 节点的 status / confidence / keywords 存在 Neo4j 属性里
- 向量检索不变，节点属性存 `embedding_id` 做桥梁
- MySQL 的 chunk / assetUnit 表保留（本来就是来源），PKU / CKP 治理表逐步废弃

---

## 阶段总览

| 阶段 | 目标 | 风险 | 可回退 |
|------|------|------|--------|
| **Phase 1** | Neo4j 只读导航层：Cypher 接口 + 力导向图前端 | 低 | ✅ 不动 MySQL |
| **Phase 2** | 增量投影：治理写入后自动同步 Neo4j | 中 | ✅ 投影失败不影响 MySQL 写入 |
| **Phase 3** | 图谱为中心的检索：deep search / RAG 改读 Neo4j | 中 | ✅ 可降级回 MySQL |
| **Phase 4** | 治理写入迁移：图谱属性成为权威，MySQL 降级为内容索引 | 高 | ⚠️ 需要数据迁移脚本 |
| **Phase 5** | 废弃 PKU/CKP 治理表，chunk/assetUnit 直接构建图谱 | 高 | ❌ 不可回退 |

---

## Phase 1：Neo4j 只读导航层

> **目标**：新建一个从 Neo4j 直接取子图的接口 + 力导向图前端页面，让用户能看到完整的节点拓扑（包括 Entity / Alias / 实体社交网络），点开节点回查 MySQL 取详情。不改动任何现有 MySQL 链路。

### 文件结构

创建：
- `backend/app/api/graph_explore.py` — Neo4j Cypher 直查接口
- `backend/app/services/graph_query.py` — Cypher 查询服务（子图提取、节点详情、邻居展开）
- `frontend/src/pages/GraphExplorePage.tsx` — 力导向图页面（react-force-graph-2d）
- `frontend/src/app/graphExploreApi.ts` — 图谱探索 API 客户端
- `backend/tests/test_graph_explore_api.py` — 接口测试
- `backend/tests/test_graph_query.py` — Cypher 查询服务测试

修改：
- `backend/app/api/__init__.py` — 注册 graph_explore 路由
- `frontend/src/app/routes.tsx` — 添加 `/graph/explore` 路由
- `frontend/src/layouts/MainLayout.tsx` — 导航栏添加"图谱探索"入口
- `frontend/package.json` — 添加 `react-force-graph-2d` 依赖

### Task 1.1：Cypher 子图查询服务

**Files:**
- Create: `backend/app/services/graph_query.py`
- Test: `backend/tests/test_graph_query.py`

实现以下查询函数（全部参数化 Cypher，不拼接）：

```python
def explore_subgraph(driver, database, *, node_types: list[str], limit: int, user_id: str) -> dict
    # 返回指定节点类型的子图（nodes + links）
    # node_types 过滤: ["CKP","PKU","Source","Entity","Alias","TopicGroup"]
    # 按 user_id 过滤
    # 每种类型最多 limit 个节点，附带它们之间的所有边

def get_node_detail(driver, database, node_id: str) -> dict
    # 返回单个节点的完整属性 + 一跳邻居节点和边

def expand_neighbors(driver, database, node_id: str, depth: int = 1) -> dict
    # 返回指定节点的 N 跳邻居子图（用于点击展开）

def search_nodes(driver, database, query: str, node_types: list[str], limit: int) -> dict
    # 按标签/名称模糊搜索节点，返回匹配节点 + 它们之间的关系
```

节点返回格式统一：
```python
{
  "nodes": [{"id", "label", "type", "properties": {...}}],
  "links": [{"source", "target", "type", "properties": {...}}],
  "stats": {"node_count", "link_count", "type_counts": {...}}
}
```

- [ ] **Step 1**：写 `test_graph_query.py`，用 FakeNeo4jDriver（mock session.run 返回固定 records）测试每个函数的 Cypher 正确性和结果组装
- [ ] **Step 2**：运行 RED，确认 import 失败
- [ ] **Step 3**：实现 `graph_query.py`
- [ ] **Step 4**：运行 GREEN
- [ ] **Step 5**：提交

### Task 1.2：图谱探索 REST 接口

**Files:**
- Create: `backend/app/api/graph_explore.py`
- Modify: `backend/app/api/__init__.py`
- Test: `backend/tests/test_graph_explore_api.py`

端点设计：

| 方法 | 路径 | 查询参数 | 返回 |
|------|------|---------|------|
| GET | `/api/v1/graph/explore` | `types`（逗号分隔）, `limit`, `q` | 子图 JSON |
| GET | `/api/v1/graph/explore/nodes/{node_id}` | — | 节点详情 + 一跳邻居 |
| GET | `/api/v1/graph/explore/nodes/{node_id}/expand` | `depth` | N 跳邻居子图 |

节点详情接口在返回 Neo4j 属性的同时，按节点 `ref_id` 回查 MySQL 取完整内容（CKP 的 statement/summary、PKU 的 statement、chunk 的 chunk_text、assetUnit 的 content）。

- [ ] **Step 1**：写 `test_graph_explore_api.py`，mock graph_query 服务测试端点响应格式
- [ ] **Step 2**：运行 RED
- [ ] **Step 3**：实现 `graph_explore.py`，注册路由
- [ ] **Step 4**：运行 GREEN
- [ ] **Step 5**：提交

### Task 1.3：力导向图前端页面

**Files:**
- Create: `frontend/src/pages/GraphExplorePage.tsx`
- Create: `frontend/src/app/graphExploreApi.ts`
- Modify: `frontend/src/app/routes.tsx`
- Modify: `frontend/src/layouts/MainLayout.tsx`
- Modify: `frontend/package.json`

功能设计：
- 使用 `react-force-graph-2d`（canvas 渲染，可承载 1000+ 节点）
- 节点按类型着色：CKP 蓝 / PKU 紫 / Source 绿 / Entity 橙 / Alias 粉 / TopicGroup 青
- 顶部类型过滤器（checkbox 切换显示哪些节点类型）
- 搜索框 → 调 `search_nodes` 高亮匹配节点
- 点击节点 → 右侧栏显示节点详情（Neo4j 属性 + MySQL 回查内容）+ 一跳邻居列表
- 双击节点 → 调 `expand_neighbors` 展开其二跳邻居
- 边按类型着色/线型：实线（SUPPORTED_BY / ALIAS_OF）、虚线（EVIDENCED_BY / MENTIONED_IN）、粗线（AUTHORED / CO_AUTHOR）
- 缩放/拖拽/力导向自动布局

- [ ] **Step 1**：安装 `react-force-graph-2d` 依赖
- [ ] **Step 2**：创建 `graphExploreApi.ts`（API 客户端 + 类型定义）
- [ ] **Step 3**：创建 `GraphExplorePage.tsx`（力导向图 + 类型过滤 + 搜索 + 详情侧栏）
- [ ] **Step 4**：注册路由 `/graph/explore`，添加导航入口
- [ ] **Step 5**：typecheck + 浏览器验证
- [ ] **Step 6**：提交

### Task 1.4：Phase 1 验证

- [ ] 运行后端 `graph_explore` + `graph_query` 测试
- [ ] 浏览器打开 `/graph/explore`，确认能看到 Neo4j 中的 Entity / Alias / CKP / PKU 节点
- [ ] 点击节点确认详情侧栏显示 MySQL 回查内容
- [ ] 双击节点确认邻居展开
- [ ] 确认现有 `/graph` 页面和 MySQL 链路完全不受影响

---

## Phase 2：增量投影

> **目标**：治理流程写入 MySQL 后自动同步到 Neo4j，不再依赖手动 backfill。Neo4j 数据实时性得到保障。

### 文件结构

创建：
- `backend/app/services/graph_sync.py` — 增量同步服务（单节点/单边 upsert + 事件钩子）
- `backend/tests/test_graph_sync.py` — 同步服务测试

修改：
- `backend/app/services/knowledge_governance.py` — 在 settle 函数的 `db.commit()` 后调用增量同步
- `backend/app/services/entity_extraction.py` — 在 entity settle 后调用增量同步
- `backend/app/config.py` — `GRAPH_SYNC_ENABLED` 开关（默认 True，可降级关闭）

### Task 2.1：增量同步服务

**Files:**
- Create: `backend/app/services/graph_sync.py`
- Test: `backend/tests/test_graph_sync.py`

实现细粒度同步函数（只同步变更的节点/边，不全量重投影）：

```python
def sync_ckp_upserted(db, graph, ckp_id: str) -> None
    # upsert 单个 :CKP 节点 + 其 SUPPORTED_BY 边（关联的 PKU）

def sync_pku_upserted(db, graph, pku_id: str) -> None
    # upsert 单个 :PKU 节点 + 其 EVIDENCED_BY 边（Source 节点）+ 其 SUPPORTED_BY 边（关联的 CKP）

def sync_entity_upserted(db, graph, entity_id: str) -> None
    # upsert 单个 :Entity 节点 + 其 Alias 节点 + ALIAS_OF 边

def sync_entity_mention_upserted(db, graph, mention_id: str) -> None
    # upsert Source 节点 + MENTIONED_IN 边

def sync_entity_relation_upserted(db, graph, relation_id: str) -> None
    # upsert Entity→Entity 边

def sync_ckp_deprecated(db, graph, ckp_id: str) -> None
    # 删除/标记 :CKP 节点及其关联边
```

每个函数幂等（MERGE 语义），失败时 log warning 不抛异常（不影响 MySQL 写入事务）。

- [ ] **Step 1**：写 `test_graph_sync.py`，用 FakeGraph 测试每个同步函数的 upsert/relate 调用
- [ ] **Step 2**：运行 RED
- [ ] **Step 3**：实现 `graph_sync.py`
- [ ] **Step 4**：运行 GREEN
- [ ] **Step 5**：提交

### Task 2.2：治理流程接入增量同步

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Modify: `backend/app/services/entity_extraction.py`
- Modify: `backend/app/config.py`

在以下位置插入同步调用（`GRAPH_SYNC_ENABLED` 开关控制）：

- `settle_personal_asset_unit_to_governance` 的 `db.commit()` 后 → 同步新建的 PKU / CKP / 关系
- `settle_document_item_to_governance` 的每个 chunk `db.commit()` 后 → 同步该 chunk 的 PKU / CKP / entity
- `extract_and_settle_entities` 的 entity/alias/mention/relation upsert 后 → 同步 entity 图

- [ ] **Step 1**：在 `knowledge_governance.py` settle 函数末尾插入 `sync_*` 调用
- [ ] **Step 2**：在 `entity_extraction.py` settle 末尾插入 `sync_*` 调用
- [ ] **Step 3**：添加 `GRAPH_SYNC_ENABLED` 配置
- [ ] **Step 4**：运行现有 governance / entity 测试，确认不破坏
- [ ] **Step 5**：新增测试验证同步被调用
- [ ] **Step 6**：提交

### Task 2.3：Phase 2 验证

- [ ] 确认一个新文档完成治理后，Neo4j 中自动出现对应的 CKP/PKU/Entity 节点
- [ ] 确认确认一个 assetUnit 后，Neo4j 中自动出现对应节点
- [ ] 确认 `GRAPH_SYNC_ENABLED=0` 时同步被跳过，治理正常完成
- [ ] 确认同步失败时治理不受影响（MySQL 写入成功）

---

## Phase 3：图谱为中心的检索

> **目标**：deep search 和 RAG 链路从 MySQL 直查改为 Neo4j 图谱遍历 + Milvus 向量融合。检索结果有拓扑溯源，不再只是孤立片段。

### 文件结构

创建：
- `engine/app/retrieval/graph_retrieval.py` — 图谱检索服务（Cypher 多跳遍历 + 向量融合）
- `engine/tests/test_graph_retrieval.py` — 检索服务测试

修改：
- `engine/app/agent/deep_search/executors.py` — `pku_graph_expansion` / `source_backtrack` 改用 Cypher
- `engine/app/agent/tools/governed_knowledge.py` — RRF 融合增加图谱邻居信号
- `engine/app/agent/tools/entity_graph_search.py` — 扩展 Cypher 返回 CKP/PKU 上下文（不只 Entity）

### Task 3.1：图谱检索服务

**Files:**
- Create: `engine/app/retrieval/graph_retrieval.py`
- Test: `engine/tests/test_graph_retrieval.py`

实现：
```python
def graph_expansion_search(driver, database, seed_node_ids: list[str], depth: int, limit: int) -> dict
    # 从种子节点出发，N 跳遍历收集邻居节点和边
    # 返回 {nodes, links, sources}

def vector_graph_fusion(driver, database, milvus_results: list[dict], depth: int, limit: int) -> dict
    # 向量检索结果 → 节点 ID → 图谱邻居扩展
    # 融合向量分数 + 拓扑距离权重
    # 返回增强后的检索结果（带拓扑路径溯源）
```

- [ ] **Step 1**：写 `test_graph_retrieval.py`
- [ ] **Step 2**：运行 RED
- [ ] **Step 3**：实现 `graph_retrieval.py`
- [ ] **Step 4**：运行 GREEN
- [ ] **Step 5**：提交

### Task 3.2：deep search executors 改用图谱

**Files:**
- Modify: `engine/app/agent/deep_search/executors.py`
- Modify: `engine/tests/test_deep_search_executors.py`

将 `pku_graph_expansion` 和 `source_backtrack` 从 MySQL join 查询改为 Cypher 遍历。保留 MySQL 查询作为降级路径（`GRAPH_RETRIEVAL_ENABLED` 开关控制）。

- [ ] **Step 1**：修改 executors 调用 `graph_retrieval`
- [ ] **Step 2**：更新测试（mock Cypher 返回）
- [ ] **Step 3**：运行 GREEN
- [ ] **Step 4**：提交

### Task 3.3：governed_knowledge_search 融合图谱信号

**Files:**
- Modify: `engine/app/agent/tools/governed_knowledge.py`
- Modify: `engine/tests/test_governed_knowledge_search.py`

在 RRF 融合中增加第四个信号：图谱邻居（向量命中的 CKP/PKU 的一跳邻居节点）。权重分配调整。

- [ ] **Step 1**：在 RRF 中增加图谱邻居信号
- [ ] **Step 2**：更新测试
- [ ] **Step 3**：运行 GREEN
- [ ] **Step 4**：提交

### Task 3.4：Phase 3 验证

- [ ] 对比迁移前后的检索结果质量（同一个问题的 RAG 回答）
- [ ] 确认图谱遍历能发现向量检索遗漏的关联节点
- [ ] 确认 `GRAPH_RETRIEVAL_ENABLED=0` 时降级回 MySQL 检索

---

## Phase 4：治理写入迁移

> **目标**：Neo4j 节点属性（status / confidence / keywords / topic_level）成为权威来源，MySQL 的 CKP/PKU 表降级为内容索引。治理操作（确认/合并/废弃）写 Neo4j 属性，MySQL 仅存原文和向量锚点。

### 文件结构

创建：
- `backend/app/services/graph_governance.py` — 图谱治理操作（在 Neo4j 上设置 status / 合并节点 / 废弃节点）
- `backend/scripts/migrate_governance_to_graph.py` — 数据迁移脚本（MySQL status → Neo4j 属性）
- `backend/tests/test_graph_governance.py` — 治理操作测试

修改：
- `backend/app/api/knowledge_graph.py` — `PATCH /knowledge-graph/nodes/{id}` 改为写 Neo4j 属性（同时回写 MySQL 保持兼容）
- `frontend/src/pages/KnowledgeGraphPage.tsx` — workbench 视图改从 Neo4j 取节点列表
- `frontend/src/pages/GraphExplorePage.tsx` — 增加节点编辑/确认/废弃操作

### Task 4.1：图谱治理服务

**Files:**
- Create: `backend/app/services/graph_governance.py`
- Test: `backend/tests/test_graph_governance.py`

实现：
```python
def set_node_status(graph, node_id: str, status: str) -> None
    # 在 Neo4j 节点上设置 status 属性

def merge_nodes(graph, source_id: str, target_id: str) -> None
    # 合并两个节点：迁移所有边到 target，删除 source 节点

def deprecate_node(graph, node_id: str) -> None
    # 废弃节点：设置 status=deprecated，可选删除关联边

def update_node_properties(graph, node_id: str, properties: dict) -> None
    # 更新节点属性（title / summary / keywords / confidence 等）
```

- [ ] **Step 1**：写测试
- [ ] **Step 2**：运行 RED
- [ ] **Step 3**：实现
- [ ] **Step 4**：运行 GREEN
- [ ] **Step 5**：提交

### Task 4.2：数据迁移脚本

**Files:**
- Create: `backend/scripts/migrate_governance_to_graph.py`

将 MySQL CKP/PKU 的 status / confidence / keywords / topic_level 同步到 Neo4j 节点属性。可重复运行（幂等）。

- [ ] **Step 1**：实现迁移脚本
- [ ] **Step 2**：dry-run 验证
- [ ] **Step 3**：执行迁移
- [ ] **Step 4**：提交

### Task 4.3：前端治理操作接入

**Files:**
- Modify: `frontend/src/pages/GraphExplorePage.tsx`
- Modify: `frontend/src/app/graphExploreApi.ts`

在图谱探索页的节点详情侧栏增加：编辑属性、确认、废弃、合并操作按钮。

- [ ] **Step 1**：增加治理操作 UI
- [ ] **Step 2**：typecheck + 浏览器验证
- [ ] **Step 3**：提交

### Task 4.4：Phase 4 验证

- [ ] 确认在图谱页编辑节点属性后，Neo4j 和 MySQL 双写一致
- [ ] 确认废弃节点后图谱中该节点不再显示
- [ ] 确认合并节点后边正确迁移
- [ ] 确认现有治理流程（assetUnit confirm / document governance）不受影响

---

## Phase 5：废弃 PKU/CKP 治理表

> **目标**：chunk / assetUnit 直接构建图谱节点，不再经过 PKU/CKP 中间层。PKU/CKP 治理表标记为 deprecated，不再写入。

> **前提**：Phase 1-4 全部稳定运行至少 2 周，确认图谱作为权威来源无问题。

### 文件结构

创建：
- `backend/app/services/direct_graph_construction.py` — 从 chunk/assetUnit 直接构建图谱节点和关系
- `backend/scripts/migrate_direct_construction.py` — 迁移脚本（将现有 chunk/assetUnit 直接投影为图谱节点）
- `backend/tests/test_direct_graph_construction.py` — 测试

修改：
- `backend/app/services/knowledge_governance.py` — settle 流程改为直接构建图谱节点（跳过 PKU/CKP 中间层）
- `backend/app/services/entity_extraction.py` — 实体抽取结果直接写入图谱
- `backend/app/api/knowledge_graph.py` — GET 接口改为纯 Cypher（不再查 MySQL CKP/PKU 表）
- `backend/app/services/ckp_vectors.py` / `pku_vectors.py` — 向量索引改为以图谱节点 ID 为锚点
- `engine/app/agent/tools/governed_knowledge.py` — 检索改为纯图谱 + 向量融合
- `engine/app/agent/deep_search/executors.py` — 改为纯 Cypher

废弃（标记 deprecated，保留只读兼容）：
- `backend/app/models/knowledge_governance.py` 中的 `PersonalKnowledgeUnit` / `CanonicalKnowledgePoint` / `PKUCanonicalLink` / `PKURelation` / `CanonicalRelation`
- `backend/app/services/knowledge_governance.py` 中的 PKU/CKP 抽取和归并逻辑
- `backend/app/services/ckp_vectors.py` / `pku_vectors.py`

### Task 5.1：直接图谱构建服务

**Files:**
- Create: `backend/app/services/direct_graph_construction.py`
- Test: `backend/tests/test_direct_graph_construction.py`

从 chunk/assetUnit 直接构建图谱：
```python
def construct_from_chunk(db, graph, chunk_id: str) -> None
    # 1. 从 chunk 文本提取概念节点（替代 PKU）
    # 2. 提取实体节点 + 别名 + 关系（复用 entity_extraction）
    # 3. 创建 (:Concept)-[:SUPPORTED_BY]->(:Source:chunk) 关系
    # 4. 概念之间创建 (:Concept)-[:RELATED_TO]->(:Concept) 关系

def construct_from_asset_unit(db, graph, unit_id: str) -> None
    # 同上，来源为 assetUnit
```

- [ ] **Step 1**：写测试
- [ ] **Step 2**：运行 RED
- [ ] **Step 3**：实现
- [ ] **Step 4**：运行 GREEN
- [ ] **Step 5**：提交

### Task 5.2：治理流程切换

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`

将 settle 函数的 PKU/CKP 抽取路径替换为 `direct_graph_construction` 调用。保留旧路径作为 `LEGACY_GOVERNANCE_ENABLED` 开关的降级。

- [ ] **Step 1**：修改 settle 函数
- [ ] **Step 2**：运行现有 governance 测试（旧路径），确认不破坏
- [ ] **Step 3**：新增测试验证新路径
- [ ] **Step 4**：提交

### Task 5.3：检索链路切换

**Files:**
- Modify: `engine/app/agent/tools/governed_knowledge.py`
- Modify: `engine/app/agent/deep_search/executors.py`
- Modify: `backend/app/services/ckp_vectors.py` / `pku_vectors.py`

向量索引改为以图谱节点 ID 为锚点。检索链路改为纯图谱 + 向量融合。

- [ ] **Step 1**：修改向量服务锚点
- [ ] **Step 2**：修改检索工具
- [ ] **Step 3**：运行测试
- [ ] **Step 4**：提交

### Task 5.4：前端完全切换到图谱

**Files:**
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`

将 `/graph` 页面的 workbench 和 network 视图都改为从 Neo4j 取数据。`/graph/explore` 成为主视图。旧的 `/graph` 可重定向到 `/graph/explore`。

- [ ] **Step 1**：修改前端数据源
- [ ] **Step 2**：typecheck + 浏览器验证
- [ ] **Step 3**：提交

### Task 5.5：Phase 5 验证

- [ ] 端到端验证：新文档 ingest → 图谱自动构建 → 检索能命中 → RAG 回答有溯源
- [ ] 确认 PKU/CKP 表不再有新写入
- [ ] 确认向量检索正常工作（锚点已切换）
- [ ] 确认所有前端页面正常工作

---

## 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| Neo4j 写入事务不如 MySQL 成熟 | 每个阶段都有 feature flag 开关，可降级回 MySQL |
| 向量检索锚点切换导致召回中断 | Phase 5 迁移脚本保证新旧锚点映射，双跑验证 |
| 治理状态丢失 | Phase 4 迁移脚本幂等可重复，先 dry-run |
| 测试套件大面积修改 | 每阶段单独修改相关测试，不跨阶段批量改 |
| 现有用户数据迁移 | 每阶段都有迁移脚本，可分批执行 |
| Neo4j 性能瓶颈 | Phase 1 用 canvas 渲染扛 1000+ 节点；Phase 3 Cypher 查询加 limit |

## 不变的部分

- **MySQL 的 chunk / assetUnit 表**：始终保留，是内容仓库
- **Milvus 向量检索**：始终保留，是语义召回层
- **记忆子系统**（memory.py 模型 + prism_memory 向量）：独立于知识图谱，不受影响
- **entity_extraction 的规则 NER**：复用，只是写入目标从 MySQL 改为 Neo4j

## 估算

| 阶段 | 工作量 | 建议节奏 |
|------|--------|---------|
| Phase 1 | 2-3 天 | 立即开始 |
| Phase 2 | 2-3 天 | Phase 1 验证后 |
| Phase 3 | 3-4 天 | Phase 2 稳定后 |
| Phase 4 | 3-5 天 | Phase 3 验证后 |
| Phase 5 | 5-7 天 | Phase 4 稳定 2 周后 |
