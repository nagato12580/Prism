# Prism 记忆巩固提权设计（P6）

版本：v1.0
日期：2026-06-24
关联：`docs/superpowers/specs/2026-06-24-memory-entity-graph-and-reflection-design.md`（P4-P5）

## 1. 背景与问题

经 P0-P5，Prism 记忆系统已完整闭环：写入→向量存储→召回→展示→反思→反哺治理。但记忆重要度是**静态**的——沉淀时设定一次后不再变化。长期使用后问题显现：

### 问题：高频被召回的记忆未获提权，重要度与实际使用脱节

用户有 50 条记忆，其中"偏好轻量方案"被召回 8 次，但沉淀时 importance=0.4；而"用过 React"只被召回 0 次，importance=0.7。召回排序按 importance 加权，导致真正高频相关的记忆反而排在后面。

对比 Comet：用 Celery 定时跑 ConsolidationEngine，按 access_count/mention_count/age 自动短期→长期 + LLM 画像增强。但 Prism 无 Celery 基础设施，且自动提权不符合"AI 建议、用户确认"原则。

## 2. 设计目标

1. **追踪记忆被召回频次**：access_count + last_accessed_at，作为巩固依据。
2. **手动触发巩固提权**：用户点按钮才提升高频低权记忆，符合确认原则。
3. **只提权不改分层**：Prism 无 short/long 分层，巩固仅提升 importance，不改 status。
4. **不引入 Celery**：API 手动触发，避开定时任务基础设施。

## 3. 方案

### 3.1 频次追踪（backend/app/models/memory.py + services/memory_access.py）

- MemoryEntry/MemoryStatement 新增 `access_count`（默认 0）+ `last_accessed_at`。
- `bump_memory_access(db, memory_ids)`：召回命中后回写，累加 access_count。
- **三处召回点回写**：
  - `memory_search` 工具（engine）：召回后 bump，独立 session commit。
  - `active_recall`（对话主动召回）：命中后 bump，独立 session。
  - `memory_context`（P3 资产解析偏好召回）：命中时 `_touch_access` 改字段，随 assets 主事务提交（不单独 commit）。

### 3.2 巩固提权（backend/app/services/memory_consolidation.py）

`run_consolidation(db)` 手动触发：
- 筛选 `access_count >= 3` 且 `importance < 0.85` 的记忆（entry + confirmed statement）。
- 提升到 `importance=0.85`，不超过 cap `0.95`。
- 按 access_count 降序取前 30 条。
- 返回提升明细（id/title/old/new importance）供前端展示。

`consolidation_candidates(db)` 预览：不修改数据，展示候选供用户确认前查看。

**与 Comet 差异**：
- Comet：Celery 定时自动，短期→长期分层，LLM 画像增强。
- Prism：手动触发，仅提权不改分层，无 LLM 调用。够用、可控、零基础设施。

### 3.3 API + 前端

- `GET /memories/consolidate/preview`：预览候选。
- `POST /memories/consolidate`：执行巩固。
- 画像页洞察卡片旁加"巩固"按钮，触发后刷新记忆列表（important 变化反映到排序）。

## 4. 量化指标

### 4.1 巩固准确率

测试条件：10 条记忆（5 高频低权 + 3 高权 + 2 低频）。

| 指标 | 值 |
|------|-----|
| 巩固延迟 | **16.04 ms** |
| 提升条数 | **5**（5 条高频低权全部命中） |
| 高权记忆跳过 | 3 条（importance≥0.85 不提升） |
| 低频记忆跳过 | 2 条（access_count<3 不提升） |
| 巩固精度 | **100%**（仅高频低权被提升，无误报） |
| 重要度提升 | 0.4 → 0.85（不超过 cap 0.95） |

### 4.2 频次回写开销

| 指标 | 值 |
|------|-----|
| bump_access 平均延迟 | **2.21 ms**（5 条，20 次平均） |
| 回写失败影响 | 零（try/except 静默，不影响召回结果） |
| 用户隔离 | 仅同 user_id 记忆被回写 |

### 4.3 向后兼容

| 场景 | 行为 |
|------|------|
| 历史记忆无 access_count | 默认 0，首次召回后开始累加 |
| 未触发巩固 | importance 不变，与 P5 前完全一致 |
| 巩固无候选 | total_promoted=0，无副作用 |

## 5. 测试自检结果

| 测试文件 | 用例数 | 结果 |
|---------|-------|------|
| `test_memory_consolidation.py`（bump/累加/隔离/提权/草稿过滤/预览/阈值/cap） | 8 | ✅ |
| `test_memory_entity.py`（P4 回归） | 6 | ✅ |
| `test_memory_reflection.py`（P5 回归） | 7 | ✅ |
| `test_memory_context.py`（P3 回归） | 7 | ✅ |
| `test_memory_vectors.py`（P1 回归） | 5 | ✅ |
| `test_backfill_memory_vectors.py`（P2.5 回归） | 5 | ✅ |
| `test_asset_parse_preferences.py`（P3 回归） | 4 | ✅ |
| `test_memories_api.py` | 2 | ✅ |
| `test_memory_extraction_service.py`（P6 回归） | 8 | ✅ |
| `test_active_recall.py`（P2 回归） | 9 | ✅ |
| `test_agent_tools.py`（P0/P1 回归 + access bump） | 8 | ✅ |
| `test_assets_api.py`/`test_memory_phase1_api.py`（含 stub） | 16 | ✅ |
| **合计** | **85** | ✅ 全通过 |

## 6. 与 Comet 的差异总结

| 维度 | Comet | Prism（P6） |
|------|-------|------------|
| 巩固触发 | Celery 定时自动 | **手动触发**，用户决定 |
| 巩固动作 | 短期→长期分层 + LLM 画像增强 | **仅提权 importance**，不改分层 |
| 频次追踪 | access_count + mention + age | **access_count + last_accessed** |
| 基础设施 | Celery + 调度配置 | **零基础设施**，API 触发 |
| 确认边界 | 自动无确认 | **用户点按钮才执行** |

Prism 的克制：巩固不自动跑、不改记忆分层、不调 LLM——只把高频低权记忆的 importance 提到合理水位，让召回排序更贴合实际使用。贴合"个人知识治理助手"定位：够用、可控、零基础设施负担。

## 7. 完整记忆系统终态（P0-P6）

```
写入 → 存储 → 召回 → 展示 → 反思 → 巩固 → 反哺
 ✅审阅/沉淀  ✅向量+实体+洞察  ✅主动+工具  ✅画像/实体图  ✅归纳  ✅频次提权  ✅治理个性化
```

记忆增强循环完整且自适应：
- 沉淀时 P3 注入偏好个性化分类
- 召回时 P6 回写频次
- 用户主动 P5 反思归纳洞察 + P6 巩固提权
- 提权后的高 importance 记忆在下次召回排序中优先（P1 向量分0.7+重要度0.3）
- 偏好/洞察反哺下一轮治理

至此 Prism 记忆系统相对 Comet 的核心差距已全部补齐，且全程保持差异化：手动触发、用户确认、轻量基础设施、贴合知识治理场景。
