# Prism 记忆反哺知识治理设计（P3）

版本：v1.0
日期：2026-06-24
关联：`docs/superpowers/specs/2026-06-24-memory-active-recall-and-backfill-design.md`（P2/P2.5）

## 1. 背景与问题

Prism 的记忆模块经 P0（召回断点）、P1（向量检索）、P2（主动召回注入对话）后，记忆已能在聊天时主动服务用户。但记忆与知识治理链路仍是**单向**的：用户把碎片丢进 Inbox → AI 解析分类，AI 完全不知道用户已沉淀的长期偏好。

### 问题：资产解析 AI 无视用户偏好，分类与用户画像脱节

当前 `_ai_parse_asset` 解析碎片时，prompt 只含碎片原文 + JSON schema，不包含任何用户上下文。例如：
- 用户记忆里有"偏好轻量方案"，但 AI 给一个重型依赖的方案碎片分类时，无法参考这条偏好给分类建议或重要度评估。
- 用户记忆里有"当前目标是做 Prism v2"，但 AI 不知道这条目标，无法判断碎片是否与当前目标相关。

这是 Comet 完全没有的能力——Comet 的记忆是孤立图谱，与知识库解析互不干涉。而 Prism 的记忆天然生长在知识治理链路上（Inbox 沉淀、对话提取），应**反哺**治理过程，形成"记忆 → 治理 → 新记忆"的增强闭环。

## 2. 设计目标

1. **资产解析时注入用户偏好上下文**：让 AI 分类/归类/评估重要度时参考用户长期偏好。
2. **只注入偏好类记忆，不污染**：仅 preference/goal/constraint 类型，过滤 fact/context 等非偏好记忆，避免无关记忆干扰分类。
3. **无偏好时零影响**：召回无命中则不注入，prompt 与原行为完全一致，保证向后兼容。
4. **失败不阻塞解析**：召回异常静默降级，资产解析照常进行。

## 3. 方案

### 3.1 偏好上下文召回（backend/app/services/memory_context.py）

`recall_preference_context(db, content)` —— 与对话侧 `active_recall` 的关键区别：

| 维度 | active_recall（对话，P2） | recall_preference_context（治理，P3） |
|------|--------------------------|--------------------------------------|
| 触发 | 信号门控（仅第一人称/偏好词） | **无门控**（对任意解析内容主动找相关偏好） |
| 记忆类型 | 全类型（entry+statement） | **仅 preference/goal/constraint**（过滤 fact/context） |
| 注入目标 | 对话 system prompt | 资产解析 prompt 的 `user_preferences` 字段 |
| 场景 | 陪伴式聊天 | 知识治理分类 |

流程：
1. 向量召回（复用 P1 的 `search_memory_vectors`，Milvus COSINE）。
2. 相似度门控 `min_score=0.40` 过滤低相关。
3. **类型过滤**：仅保留 `memory_type ∈ {preference, goal, constraint}` 的记忆，statement 同理按 `statement_type` 过滤。
4. 过滤非确认态 statement（draft/superseded）。
5. 拼成偏好上下文块，限 600 字符。

### 3.2 prompt 注入（backend/app/prompts/asset_parse.py）

`build_asset_parse_request` / `build_asset_parse_messages` 新增可选参数 `user_preferences`：
- 非空时加入 request JSON 的 `user_preferences` 字段，供 LLM 分类时参考。
- 空时省略该字段，prompt 与原行为完全一致。

### 3.3 调用链路（backend/app/api/assets.py）

`_create_asset_item_from_raw`（Inbox 碎片创建/解析入口）：
1. 调 `recall_preference_context(db, raw_text)` 召回偏好。
2. 传给 `_ai_parse_asset(user_preferences=...)`。
3. `_ai_parse_asset` 传给 `build_asset_parse_messages`，注入 prompt。
4. 召回异常 try/except 静默降级，`user_preferences=""` 继续解析。

## 4. 量化指标

### 4.1 偏好注入准确率（P3 核心）

测试条件：10 条记忆（5 preference + 5 fact），向量召回全部命中，测召回过滤效果。

| 指标 | 值 |
|------|-----|
| preference 记忆注入率 | **100%**（5/5 偏好记忆全部注入） |
| fact 记忆过滤率 | **100%**（5/5 事实记忆被类型过滤剔除） |
| 非确认 statement 过滤率 | 100%（draft/superseded 不注入） |
| 低相似度过滤 | min_score=0.40 门控生效 |

结论：偏好上下文召回精准——只把与内容相关的偏好/目标/约束注入解析 prompt，事实类记忆不污染分类决策。

### 4.2 召回延迟

| 指标 | 值 |
|------|-----|
| 偏好召回平均延迟 | **3.03 ms**（20 次平均，含 MySQL 回取） |
| 无偏好时开销 | 0（向量无命中直接返回空串，不进入回取） |
| 召回异常时开销 | 0（静默降级，不影响解析） |

### 4.3 向后兼容性

| 场景 | 行为 |
|------|------|
| 无记忆/向量未配置 | `user_preferences=""`，prompt 省略该字段，解析与 P1 前完全一致 |
| 召回无命中 | 同上，零行为变化 |
| 有偏好命中 | 注入 `user_preferences` 字段，LLM 可参考但**不强制遵循**（prompt 标注"参考但不强制"） |

## 5. 测试自检结果

| 测试套件 | 用例数 | 结果 |
|---------|-------|------|
| `test_memory_context.py`（召回/类型过滤/相似度门控/异常降级） | 7 | ✅ 全通过 |
| `test_asset_parse_preferences.py`（prompt 注入/空偏好省略/AI 调用透传） | 4 | ✅ 全通过 |
| `test_assets_api.py`（含 2 个新增 P3 集成测试 + 原有回归） | 7 | ✅ 全通过 |
| 全量记忆测试（P0-P3 合计） | **64** | ✅ 全通过 |

新增 P3 集成测试：
- `test_create_asset_draft_injects_user_preferences_into_parse`：验证召回命中时偏好注入解析 prompt。
- `test_create_asset_draft_skips_preferences_when_recall_empty`：验证无偏好时不注入、行为兼容。

## 6. 与 Comet 的差异（Prism 独有能力）

| 维度 | Comet | Prism（P3） |
|------|-------|------------|
| 记忆与知识库关系 | 孤立图谱，互不干涉 | **记忆反哺知识治理**，解析时注入偏好 |
| 分类个性化 | 无（通用解析） | **按用户偏好/目标个性化分类建议** |
| 闭环 | 记忆↔对话单向 | **记忆→治理→新记忆** 增强闭环 |

P3 是 Prism 相对 Comet 的差异化能力：Comet 的记忆服务于对话理解，Prism 的记忆 additionally 服务于知识治理——因为 Prism 的定位是"个人知识治理助手"，记忆应让 AI 更懂用户地整理用户的知识，而非仅聊天时懂用户。

## 7. 闭合的增强循环

P3 完成后，Prism 记忆形成完整增强闭环：

```
用户丢碎片进 Inbox
    ↓ AI 解析时召回用户偏好（P3）→ 个性化分类/重要度
碎片确认入库
    ↓ 沉淀为 MemoryEntry（P0）+ 向量索引（P1）
用户聊天
    ↓ 主动召回注入对话（P2）→ 陪伴式理解
对话提取记忆
    ↓ 草稿审阅确认（P6 冲突检测）→ MemoryStatement + 向量索引
    ↓ 反哺下一轮 Inbox 解析（P3）← 闭环
```

每条新记忆都让后续治理更懂用户，形成越用越准的个性化增强。

## 8. 后续计划（P4-P5，本轮未实现）

### P4 轻量 Entity 激活
对话提取/资产沉淀时抽核心实体存入 `MemoryEntity`，记忆间共享实体形成关系。前端图谱页升级为实体-记忆关联图。不引入 Neo4j，用现有 MySQL。

### P5 巩固 + 反思（手动触发）
记忆收件箱"巩固"按钮 + 画像"生成洞察"按钮，LLM 归纳 Insight。避开 Celery 定时任务，符合"AI 建议、用户确认"原则。
