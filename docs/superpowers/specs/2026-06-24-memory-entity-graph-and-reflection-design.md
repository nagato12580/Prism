# Prism 记忆图谱激活与反思引擎设计（P4-P5）

版本：v1.0
日期：2026-06-24
关联：`docs/superpowers/specs/2026-06-24-memory-feedback-to-governance-design.md`（P3）

## 1. 背景与问题

经 P0-P3，Prism 记忆链路已闭环：写入（审阅/沉淀）→ 向量存储 → 召回（主动+工具）→ 展示（画像/图谱）。但仍有两块空壳：

### 问题 A：记忆图谱是假图谱，无真实实体关联

`MemoryEntity`/`MemoryRelation` 模型早已建好却零写入。前端记忆图谱页只是按 `memory_type` 分组的卡片图，用户看到的"图谱"与真实记忆关联无关——无法回答"Prism 这个实体关联了我哪些记忆"。

对比 Comet：抽取三元组建 Neo4j 图谱，有四层溯源、社区聚类、ontology 规范化。但那是通用图谱的过度工程，Prism 作为个人知识治理助手只需"看清实体关联了哪些记忆"，无需完整图数据库。

### 问题 B：画像只有事实堆，无高层理解

`MemoryInsight` 模型空壳。用户确认了 50 条记忆，画像页只是按类型罗列，用户无法一眼看出"Prism 对我的整体理解是什么"。Comet 用 Celery 定时跑反思归纳洞察，但 Prism 无 Celery 基础设施，且自动归纳不符合"AI 建议、用户确认"原则。

## 2. 设计目标

1. **激活实体模型，但保持轻量**：记忆确认时抽核心实体存 MemoryEntity，记忆共享实体自动成关系。不引入 Neo4j，用现有 MySQL。
2. **图谱页升级为真实实体-记忆关联图**：用户能看到实体节点 + 实体间关系 + 实体关联的记忆。
3. **反思手动触发，不自动**：用户点按钮才归纳洞察，符合确认原则，避开定时任务。
4. **不追求 Comet 的图谱完备性**：不做四层溯源、社区聚类、ontology 规范化。

## 3. 方案

### 3.1 P4 实体抽取与关联（backend/app/services/memory_entity.py）

`extract_and_link_entities(db, content, source_id, statement_id)`：
- LLM 抽 1-4 个核心实体（人/项目/技术/主题/产品），过滤宽泛词。
- 按 name+user_id upsert MemoryEntity：已存在则 mention_count+1、合并 source_ids；新建则 status=confirmed。
- 同一条记忆抽出的多个实体间挂 `related_to` 关系（共享记忆天然相关），去重防重复。
- 抽取失败静默返回空，不阻塞记忆确认。

**注入点**：`memories.py` confirm/supersede 后调 `_link_statement_entities`；`assets.py` 沉淀 MemoryEntry 后调 `extract_and_link_entities`。均 try/except 包裹。

**与 Comet 差异**：
- Comet：Neo4j 图谱 + 三元组（subject-predicate-object）+ 四层溯源 + 实体融合算法。
- Prism：MySQL 表 + 实体 upsert + related_to 简单关联 + mention_count 频次。够看清关联，不建图数据库。

### 3.2 P4 图谱页升级（frontend/src/pages/MemoryGraphPage.tsx）

双模式切换：
- **实体图（默认）**：实体节点环形分布，实体间 related_to 关系画实线边，每个实体外侧挂其关联的记忆节点（虚线边）。选中实体显示实体详情 + 关联记忆列表。
- **类型图（回退）**：原按 memory_type 分组的卡片图（无实体数据时自动回退）。
- 搜索过滤、选中详情面板、空状态提示完备。

### 3.3 P5 反思引擎（backend/app/services/memory_reflection.py）

`run_reflection(db)` 手动触发：
1. 收集已确认记忆（entry + confirmed statement，各取前 60 条按重要度降序）。
2. 记忆少于 4 条跳过（`too_few_memories`）。
3. LLM 归纳 2-4 条高层洞察（theme + content + importance）。
4. 按 theme upsert MemoryInsight（同主题更新不重复堆叠），status=confirmed。
5. LLM 不可用/异常静默跳过。

**API**：`POST /memories/reflect`（手动触发）+ `GET /memories/insights`（列表）。

**画像页集成**：顶部"画像洞察"卡片 + "生成洞察"按钮（记忆<4 条禁用），展示 theme/content/importance。

**与 Comet 差异**：
- Comet：Celery 定时反思，自动归纳，向量化洞察按话题召回。
- Prism：手动触发，用户决定何时归纳，符合"AI 建议、用户确认"。洞察暂不向量化（P5 范围克制，后续可扩展）。

## 4. 量化指标

### 4.1 P4 实体抽取

测试条件：15 次抽取调用，每次抽 3 个实体（Prism/Milvus/RAG），不同 source_id。

| 指标 | 值 |
|------|-----|
| 实体抽取平均延迟 | **7.67 ms**（含 LLM mock + DB upsert） |
| 唯一实体数 | **3**（15 次调用 3 个 name，正确去重） |
| mention_count 去重 | Prism 提及 **15** 次（同实体累加不重建） |
| 关系去重 | **3** 条 related_to（3 实体 C(3,2)=3 对，重复调用不新增） |
| 宽泛词过滤 | name 为空/空白被过滤 |
| 抽取异常降级 | LLM 异常返回空列表，不阻塞记忆确认 |

### 4.2 P5 反思引擎

测试条件：10 次反思调用，每次产 2 条洞察（技术偏好/学习习惯）。

| 指标 | 值 |
|------|-----|
| 反思平均延迟 | **6.63 ms**（含 LLM mock + DB upsert） |
| 唯一洞察数 | **2**（10 次调用 theme 去重，幂等 upsert） |
| 同主题更新 | 后调用覆盖先调用 content（幂等不堆叠） |
| 记忆不足保护 | <4 条记忆跳过（`too_few_memories`） |
| LLM 异常降级 | 返回 `no_llm_or_empty`，不抛错 |
| 草稿过滤 | 仅确认态 statement 进入反思输入 |

### 4.3 图谱页升级效果

| 改进前 | 改进后 |
|--------|--------|
| 按类型分组的卡片图，节点重叠 | 实体-记忆关联图，网格块布局无重叠 |
| 无真实关联关系 | 实体间 related_to 实线 + 实体-记忆虚线 |
| 无法看实体关联了哪些记忆 | 选中实体显示关联记忆列表 |
| 单一视图 | 实体图/类型图双模式切换 |

## 5. 测试自检结果

| 测试文件 | 用例数 | 结果 |
|---------|-------|------|
| `test_memory_entity.py`（抽取/upsert/去重/关系/异常） | 6 | ✅ |
| `test_memory_reflection.py`（归纳/upsert/不足/异常/草稿过滤/列表） | 7 | ✅ |
| `test_memory_context.py`（P3 回归） | 7 | ✅ |
| `test_asset_parse_preferences.py`（P3 回归） | 4 | ✅ |
| `test_memory_vectors.py`（P1 回归） | 5 | ✅ |
| `test_backfill_memory_vectors.py`（P2.5 回归） | 5 | ✅ |
| `test_memories_api.py` | 2 | ✅ |
| `test_memory_extraction_service.py`（P6 回归） | 8 | ✅ |
| `test_assets_api.py`（含 P3 + autouse stub） | 7 | ✅ |
| `test_memory_phase1_api.py`（含 stub） | 9 | ✅ |
| `test_active_recall.py`（P2 回归） | 9 | ✅ |
| `test_agent_tools.py`（P0/P1 回归） | 8 | ✅ |
| **合计** | **77** | ✅ 全通过 |

注：全量累加运行超时（环境 Milvus 真实连接慢），各文件单独均绿。为 api 测试新增 autouse fixture stub 掉向量索引/实体抽取，避免真实外部调用。

## 6. 与 Comet 的差异总结

| 维度 | Comet | Prism（P4-P5） |
|------|-------|----------------|
| 记忆结构化 | Neo4j 图谱 + 三元组 + 四层溯源 + 社区聚类 | **MySQL 轻量实体 + related_to 关联**，不建图数据库 |
| 图谱可视化 | 完整图谱 + 社区子图 | **实体-记忆关联图**，看清实体关联了哪些记忆即可 |
| 反思触发 | Celery 定时自动 | **手动触发**，符合"AI 建议、用户确认" |
| 洞察向量化 | 向量化按话题召回 | 暂不向量化（P5 克制，后续可扩展） |
| ontology | 规范化实体类型/predicate | 开放字符串 + 简单 type 元数据 |

Prism 的克制：不追求图谱完备性，只激活已建模型让图谱页变成真实关联图；反思不自动跑，用户主动归纳。两者都贴合"个人知识治理助手"定位——够用、可控、不引入重型基础设施。

## 7. 完整记忆系统现状（P0-P5）

```
写入 → 存储 → 召回 → 展示 → 反思 → 闭环
 ✅审阅/沉淀  ✅向量+模型  ✅主动+工具  ✅画像/实体图  ✅洞察归纳  ✅反哺治理
```

记忆增强循环完整：碎片入库时 P3 注入偏好个性化分类 → 沉淀记忆 P0/P1 → 对话 P2 主动召回 → 审阅确认 P6 冲突检测 → 抽实体 P4 建关联图 → 手动反思 P5 归纳洞察 → 洞察+记忆反哺下一轮治理。

## 8. 后续 P6（巩固提权，未实现）

依赖 access_count 频次追踪基础设施（当前记忆无访问计数），需先加召回命中回写 access_count，再做按频次/importance 提示高频记忆标长期。纳入下轮。
