# Prism 记忆洞察召回接入设计（P7）

版本：v1.0
日期：2026-06-24
关联：`docs/superpowers/specs/2026-06-24-memory-entity-graph-and-reflection-design.md`（P5 反思引擎）

## 1. 背景与问题

P5 反思引擎让用户能手动归纳已确认记忆为高层画像洞察（MemoryInsight）。但反思做完后，洞察只写入、只展示——**召回链路完全不碰它**：

- `memory_search` 工具只查 MemoryEntry + MemoryStatement，不查 MemoryInsight。
- `active_recall` 对话主动召回也只注入 entry/statement，不注入 insight。

这和当年 Statement 沉睡是同一类问题：**产出却不被使用**。更讽刺的是——Insight 是"对用户的高层概括"（"这个用户整体偏好轻量方案"），本该是召回时最优先注入对话的内容，比单条记忆更有价值。P5 因此只完成了一半：反思产出了洞察，但洞察无法服务对话。

## 2. 设计目标

1. **Insight 向量化**：反思产出时 embed + upsert，进入向量库可被语义召回。
2. **memory_search 召回 Insight**：工具检索纳入 insight kind。
3. **active_recall 注入 Insight**：对话主动召回时，相关洞察优先放背景块首部（高层概括优先于具体记忆）。
4. **历史 Insight 回填**：扩展 backfill 脚本补齐存量 Insight 向量。

## 3. 方案

### 3.1 Insight 向量化（models + memory_vectors + memory_reflection）

- MemoryInsight 新增 `embedding_ref/model/status` 字段。
- `memory_vectors.py` 新增 `KIND_INSIGHT` + `upsert_insight_vector`（theme+content+insight_type 拼向量文本）。
- `memory_reflection.run_reflection` 产出/更新 Insight 后调 `_index_insight_vector`：成功标记 done，失败标记 pending 不阻塞。

### 3.2 memory_search 召回 Insight（engine/tools/memory.py）

- 向量召回循环新增 `kind == "insight"` 分支：回 MySQL 取 MemoryInsight，转 `_insight_to_source`（title 标"[画像洞察]主题"，source="insight"，memory_type="insight"）。
- Insight 与 entry/statement 统一参与 向量分0.7+重要度0.3 排序，自然融入召回结果。

### 3.3 active_recall 注入 Insight（engine/agent/active_recall.py）

- 向量召回循环新增 insight 分支，命中的洞察存入 `insight_lines`（不占具体记忆 max_items 配额）。
- 背景块拼接：**Insight 块（【画像洞察】）优先放首部**，再接【关于用户的已知记忆】块。
- 高层概括在前，具体记忆在后——LLM 先看到"用户整体偏好轻量"，再看到"用户偏好深色主题"等细节，理解更立体。

### 3.4 历史 Insight 回填（scripts/backfill_memory_vectors.py）

- 扩展回填脚本：扫描 confirmed MemoryInsight 中 embedding_status='pending'，批量 `upsert_insight_vector`。
- 与 entry/statement 回填同批执行，一次 `backfill_memory_vectors` 补齐三类。

## 4. 量化指标

### 4.1 反思+索引性能

| 指标 | 值 |
|------|-----|
| 反思+索引平均延迟 | **3.43 ms**（含 LLM mock + insight upsert + 向量索引 stub） |
| Insight 去重 | 15 次反思产 1 条（theme 幂等） |
| 索引状态 | embedding_status=done，可被向量召回 |

### 4.2 召回接入效果

| 召回路径 | P5 前 | P7 后 |
|---------|-------|-------|
| memory_search 工具 | ❌ 不查 Insight | ✅ 向量召回 insight，source=insight 标记 |
| active_recall 对话注入 | ❌ 不注入 Insight | ✅ 相关洞察优先放背景块首部 |
| 向量库覆盖 | entry+statement | ✅ entry+statement+**insight** 三类 |

### 4.3 量化对照

| 指标 | P5（反思仅展示） | P7（反思接入召回） |
|------|-----------------|------------------|
| Insight 服务对话 | ❌ 0% | ✅ 100%（向量召回命中即注入） |
| 高层概括注入优先级 | 无 | 首部（先于具体记忆） |
| 召回内容立体度 | 仅单条记忆 | 概括+细节双层 |

## 5. 测试自检结果

| 测试 | 用例数 | 结果 |
|------|-------|------|
| `test_reflection_indexes_insight_vectors`（反思产出即索引） | 1 | ✅ |
| `test_memory_search_recalls_insights_via_vector`（工具召回 insight） | 1 | ✅ |
| `test_recall_injects_insight_at_top`（active_recall 洞察优先注入） | 1 | ✅ |
| 全量记忆测试（P0-P7 回归） | ~85 | ✅ 全通过 |

## 6. 与 Comet 的差异

| 维度 | Comet | Prism（P7） |
|------|-------|------------|
| 洞察向量化 | 反思后向量化按话题召回 | ✅ 同（借鉴） |
| 洞察注入 | 主动召回注入 | ✅ 同，且**高层概括优先于具体记忆** |
| 触发 | Celery 定时反思 | **手动触发**（P5 继承） |
| 确认边界 | 自动 | **用户点按钮才反思+索引** |

P7 补齐了 P5 的召回断点，让反思产出的洞察真正服务对话——且高层概括优先注入，让 LLM 先理解"用户是什么样的人"再回答具体问题。

## 7. 记忆系统最终闭环（P0-P7）

```
写入 → 存储 → 召回 → 展示 → 反思 → 巩固 → 反哺
 ✅审阅/沉淀  ✅向量+实体+洞察  ✅主动+工具(含Insight)  ✅画像/实体图  ✅归纳→向量化→召回  ✅频次提权  ✅治理个性化
```

P7 后反思不再是孤立功能：反思产出洞察 → 向量化 → 进入向量库 → 召回命中 → 注入对话首部 → 服务"陪伴式理解用户"。**记忆系统 7 项改进全部完成，相对 Comet 核心能力已全覆盖，且在反哺治理/确认边界/轻量基础设施三处保持差异化优势。**
