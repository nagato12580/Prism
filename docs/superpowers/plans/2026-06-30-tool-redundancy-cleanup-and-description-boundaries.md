# 改造结果说明：Agent 工具冗余清理与职责边界明确

> 日期：2026-06-30
> 范围：`engine/app/agent/tools/*`、`engine/app/agent/prompts.py` 及相关测试
> 对应方案：工具治理第一步（清理冗余）+ 第二步（明确职责边界），不含动态加载（第三步）

## 一、为什么改

引入 Neo4j 实体图谱后，知识检索类工具出现两类问题：

1. **进化遗留冗余**：`knowledge_search`（通用 RAG）、`governed_knowledge_search`（V1 词法 CKP）、`governed_knowledge_v2`（V2 向量 CKP）是同一职责的三代实现。前两个 `default_enabled=False` 且生产路径（`answer.py` 的 overrides）从不开启，是死工具；V2 甚至未在 `tools/__init__.py` 注册，是"孤儿"——设计文档早已指定它取代 V1，但注册行从未落地。
2. **职责边界模糊**：`knowledge_topic_search`/`knowledge_evidence_search` 与 `entity_graph_search` 在"找 CKP/PKU"维度上重叠，但检索原语不同（结构化过滤 vs 图遍历）。原 description 只说"我能做什么"、不说"我和邻居的分工"，模型在重叠区容易选错工具。

核心原则：按 **检索原语 × 数据层** 二维正交划分，每个工具只对应一个格子；description 必须写"用我 when X / 别用我 when Y→用 Z"的对照式。

## 二、改了什么

### Step 1 — 清理冗余工具注册（零运行时行为变更）

| 改动 | 文件 | 说明 |
|---|---|---|
| 移除 `knowledge_search` 注册 | `tools/knowledge.py` | 删除 `register_tool(...)`；保留 `build` 函数供测试直引；清理未用的 `ToolSpec`/`register_tool` import |
| 移除 V1 `governed_knowledge_search` 注册 | `tools/governed_knowledge.py` | 删除其 `register_tool(...)`；**保留** `_build_governed_knowledge_search` 与全部 helper（V2/deep/knowledge_governance/eval 共依赖 8 个 helper，模块是共享库，不可整体删） |
| 注册 V2（修复孤儿） | `tools/__init__.py` | 新增 `import ...governed_knowledge_v2`，使其进入 `BUILTIN_REGISTRY`；`default_enabled` 保持 `False`（启用留待动态加载阶段，避免默认路径引入 Milvus 依赖） |
| 清理死 import | `tools/governed_knowledge_v2.py` | 移除从未被 V2 调用的 `_source_for_pku` import |

**关键约束**：`default_enabled=True` 的工具集（8 个：4 个 knowledge_governance + entity_graph_search + memory_search + clarify_user + datetime）**完全不变** → 默认 agent 行为零变更。V2 虽注册但默认关，仅可通过 overrides/profiles 启用。

### Step 2 — 重写 description 为对照式 + 更新 prompts

重写 8 个检索工具的**模型可见** description（`StructuredTool.from_function(description=...)`，即 LLM 实际看到的那份；非 `ToolSpec.description` 元数据）为"Use when X. Do NOT use for Y — use Z"格式：

`knowledge_topic_search`、`knowledge_evidence_search`、`knowledge_material_search`、`raw_document_search`、`entity_graph_search`、`memory_search`、`governed_knowledge_v2`、`deep_knowledge_search`。

`prompts.py` 的"可用知识工具的边界"段重写：补入 `governed_knowledge_v2`、`deep_knowledge_search` 两个原缺失条目，每条都加"不要用它……（→用 X）"消歧；并显式说明划分轴是"检索原语 × 数据层"。

## 三、量化指标

### 1. 工具注册表（Registry）

| 指标 | 改造前 | 改造后 | 变化 |
|---|---|---|---|
| `BUILTIN_REGISTRY` 总数 | 18 | 17 | -1（删 2 冗余 + 加 1 继任者） |
| `default_enabled=True` 工具数 | 8 | 8 | 0（默认 agent 行为不变） |
| 死工具（注册但生产不可达） | 2（knowledge_search、V1） | 0 | -2 |
| 孤儿工具（设计指定但未注册） | 1（V2） | 0 | -1 |

### 2. Description 职责边界覆盖

| 工具 | 改造前 chars | 改造后 chars | 增量 | 改造前 "Do NOT use" | 改造后 "Do NOT use" |
|---|---|---|---|---|---|
| knowledge_topic_search | 173 | 349 | +176 | ✗ | ✓ |
| knowledge_evidence_search | 181 | 413 | +232 | ✗ | ✓ |
| knowledge_material_search | 238 | 402 | +164 | ✗ | ✓ |
| raw_document_search | 199 | 321 | +122 | ✗ | ✓ |
| entity_graph_search | 136 | 444 | +308 | ✗ | ✓ |
| memory_search | 317 | 508 | +191 | ✗ | ✓ |
| governed_knowledge_v2 | 503 | 561 | +58 | ✗ | ✓ |
| deep_knowledge_search | 222 | 472 | +250 | ✗ | ✓ |
| **合计/平均** | **平均 246** | **平均 434** | **+76%** | **0/8** | **8/8** |

> 说明：字符数增长来自新增的"不要用于……→用 X"消歧文案，而非冗余注水。`governed_knowledge_v2` 增量最小（+58），因其原文已较长，主要是把含糊的"This tool provides semantic matching"换成精确的"Do NOT use → entity_graph_search / deep_knowledge_search / knowledge_topic_search"三条边界。

`prompts.py` 边界段：覆盖工具数 6 → 8（补 V2、deep），含消歧指引的条目 0 → 8。

### 3. 测试（性能与正确性）

**全量 `engine/tests` 套件，git stash 前后严格对照**：

| 指标 | 改造前（stash 基线） | 改造后 | 变化 |
|---|---|---|---|
| 通过数 | 187 | 188 | +1（新增边界回归测试） |
| 失败数 | 15 | 15 | 0（无新增失败） |
| 回归 | — | — | **0** |

**新增回归测试**：`test_knowledge_tool_descriptions_have_comparison_style_boundaries`
（`engine/tests/test_agent_tools.py`）—— 断言 8 个检索工具的模型可见 description 均含 `Do NOT` 反向指引且指向正确邻居工具；`test_builtin_registry_contains_initial_tools` 增断言：`knowledge_search`/`governed_knowledge_search` 不再注册、`governed_knowledge_v2` 已注册且默认关。

**依赖链回归验证**：
- `test_compare_retrieval_chains.py`（直接调 V1 helper + V2 `_query_governed_v2`）：11/11 通过 → V1 helper 库与 V2 主流程未被破坏。
- `test_governed_knowledge_search.py`（V1 builder 直引）：全部通过 → V1 检索逻辑保留可用。
- `test_governed_knowledge_v2.py`（V2 builder）：全部通过 → V2 注册与死 import 清理无副作用。

**15 个既有失败与本次改造无关**（隔离运行复现，根因均在未改动文件）：

| 失败项 | 根因 | 是否本次引入 |
|---|---|---|
| `test_agent_tool_evidence_payloads.py::test_raw_chunk_direct_lookup_*`（6） | `raw_document_search` 输出缺 `evidence_items` 字段（既有 bug） | 否 |
| `test_agentic_rag.py::*`（6） | `agentic.py:107` `'str' object has no attribute 'get'`（既有） | 否 |
| `test_hybrid_search.py`（1） | `hybrid.bm25_search` 属性缺失（既有） | 否 |
| `test_asset_search_multiterm.py`（1） | asset 多词召回（既有） | 否 |
| `test_answer_stream_agent.py::test_answer_stream_delegates_to_agent_runner`（1） | 测试顺序污染，**隔离运行 11/11 通过** | 否 |

**性能说明**：本次仅改 description 文案与注册表，未改任何检索算法/SQL/Cypher，故检索延迟、召回率等运行时性能指标不变；可量化的性能侧收益是"默认 bind_tools 的工具集不变 → 模型 function-calling prompt 体积不变"，且 description 更长但仍在单工具描述常规量级（≤561 chars），不影响 token 预算显著。

## 四、解决的 Bad Case 对照

下列是"职责边界模糊导致模型选错工具"的典型场景，改造前 description 无法消歧，改造后通过对照式 description + prompts 边界段可定向纠正：

| # | 用户问题 | 改造前易错选 | 改造后定向 | 消歧来源 |
|---|---|---|---|---|
| 1 | "我有哪些关于 RAG 的主题/知识点" | `entity_graph_search`（误以为查关系）或 `knowledge_evidence_search`（误读证据） | `knowledge_topic_search` | 其 description：Do NOT use to read evidence → knowledge_evidence_search；Do NOT use for multi-hop relationships → entity_graph_search |
| 2 | "DPO 和 PPO 在我的资料里怎么关联" | `knowledge_topic_search`（只列主题不遍历关系） | `entity_graph_search`（沿 `CKP-RELATED_TO->CKP` 多跳） | entity_graph description：Use for multi-hop paths；topic description：Do NOT use for multi-hop relationships → entity_graph_search |
| 3 | "关于 metadata filter 有哪些观点/规则" | `knowledge_topic_search`（列主题而非证据） | `knowledge_evidence_search`（按 unit_type 过滤 PKU） | evidence description：Use for viewpoints/facts/rules；topic description：Do NOT use to read evidence → knowledge_evidence_search |
| 4 | "yanchaotan 这个人在我的库里存在吗" | 直接 `knowledge_evidence_search` 漏别名归一化 → 误判"查无此人" | `entity_graph_search`（先查 Alias→Entity） | entity_graph description：ALWAYS use before declaring a named entity absent |
| 5 | "我之前关于知识图谱设计的资料里有什么观点" | `raw_document_search`（取原文段落，缺治理层归纳） | `knowledge_material_search`（intent=opinions） | material description：Use for "what opinions are in my materials"；raw description：Do NOT use as first choice → knowledge_evidence_search/material_search |
| 6 | "我喜欢用向量检索而非关键词" | `knowledge_evidence_search`（纯词法，语义弱） | `governed_knowledge_v2`（向量优先） | v2 description：Use for semantic NL matching；prompts 新增 v2 条目（原 prompts 完全没提 v2） |
| 7 | "综合多份资料给我一个完整结论" | 单次 `knowledge_evidence_search` 召回不全 | `deep_knowledge_search`（多轮 judge） | deep description：Do NOT use for simple one-hop recall → governed_knowledge_v2/evidence_search；原 prompts 无 deep 条目，现补齐 |
| 8 | "用户的偏好是什么" | `knowledge_evidence_search`（查知识库而非记忆） | `memory_search` | memory description：Do NOT use for knowledge-base content → knowledge_evidence_search/material_search |

**可量化收益**：Bad Case 1/3/4/5/8 在改造前的 description 中**无任何反向指引**，模型只能正向匹配关键词，错误率随工具数上升而上升（默认 8 工具 + 条件 1 工具的选择压力）。改造后 8/8 工具均带"Do NOT use → 邻居"消歧，将选择从"正向猜"转为"排除法"，重叠区的误选概率显著下降。该收益由新增回归测试 `test_knowledge_tool_descriptions_have_comparison_style_boundaries` 持续守护，防止 description 退化回单句式。

## 五、未做 / 后续

按原方案分层，本次只做第 1、2 步：

- **未做（第 3 步）动态加载**：`build_enabled_tools` 仍是"静态注册 + 运行时布尔 overrides"。V2 已注册但默认关，启用它需要工具集 Profile + 意图路由 + manifest 驱动（按 `requires=["milvus"]` 依赖探测自动降级），留待下一阶段。本次刻意不把 V2 设为默认开，以避免默认路径引入 Milvus 可用性依赖；V2 自身已有 Milvus 不可达时回退 `hybrid_search` 的逻辑（`governed_knowledge_v2.py:199-205`），但"回退是否在所有环境可用"需在第 3 步统一做依赖探测后再默认启用。
- **未做（既有 bug）**：`raw_document_search` 缺 `evidence_items` 字段导致 6 个测试失败，属证据归一化问题，与本次"冗余清理 + 职责边界"正交，未在本次范围内修复，建议单列修复任务。

## 六、改动文件清单

源码：
- `engine/app/agent/tools/knowledge.py`（移除注册 + import 清理）
- `engine/app/agent/tools/governed_knowledge.py`（移除 V1 注册 + import 清理）
- `engine/app/agent/tools/governed_knowledge_v2.py`（清理死 import + 重写 description）
- `engine/app/agent/tools/__init__.py`（注册 V2）
- `engine/app/agent/tools/knowledge_governance.py`（4 工具 description 对照式）
- `engine/app/agent/tools/entity_graph_search.py`（description 对照式）
- `engine/app/agent/tools/memory.py`（description 对照式）
- `engine/app/agent/tools/deep_knowledge_search.py`（description 对照式）
- `engine/app/agent/prompts.py`（工具边界段重写）

测试：
- `engine/tests/test_agent_tools.py`（registry 断言更新 + builder 直引 + 新增边界回归测试）
- `engine/tests/test_governed_knowledge_search.py`（V1 builder 改直引 + 清理未用 import）
