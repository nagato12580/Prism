# 图检索与 CKP/PKU 治理链路桥接改造报告（Level 1-3）

> 日期：2026-06-30
> 数据集：`evaluation/datasets/formal_docs_v1.json`（60 题）
> 改造目标：在 Neo4j 中建立 Entity↔PKU 的显式桥接边，将实体子图与治理子图从"隐式 3 跳、几乎断开"变为"显式 1 跳、大面积连通"，并新增融合检索链量化收益。

## 一、改造前现状

```
Entity -MENTIONED_IN→ Source(chunk_id)              ← 实体投影
CKP -SUPPORTED_BY→ PKU -EVIDENCED_BY→ Source(chunk_id)  ← 治理投影
```

两条投影共享 Source 节点，但：
- **无显式边** Entity↔PKU，需 3 跳 `Entity→Source←PKU←CKP` 才能连通
- **共享 Source 仅 3 个**：实体抽取覆盖 880 个 chunk（含 child），PKU 抽取只覆盖 97 个 parent chunk，重叠仅 3
- PKU 全部指向 parent chunk（97 个），EntityMention 754 个在 child chunk / 126 个在 parent chunk → child 上的实体无法与 parent 上的 PKU 匹配

## 二、改造内容

### Level 1：显式建边 `PKU -[:MENTIONS_ENTITY]-> Entity`

**原理**：实体和 PKU 从同一份源文本抽取，共享 `(source_kind, source_id)`。投影时按此键 join。

**改动**：
| 文件 | 改动 |
|---|---|
| `backend/app/services/graph_projection.py` | 新增 `project_pku_entity_mentions(db, graph, user_id)` + `GraphProjectionResult.pku_entity_mention_count` |
| `backend/scripts/backfill_entity_graph.py` | 投影后调用桥接函数 |
| `backend/tests/test_graph_projection.py` | 4 个新测试 |

### Level 2：Child→Parent 归并扩大覆盖

**根因**：PKU 只从 parent chunk 抽取（97 个），实体抽取跑全部 chunk（880 个），754 个实体在 child chunk 上，与 PKU 的 parent chunk 不匹配。

**修法**：`project_pku_entity_mentions` 中，对 `source_kind=document_chunk` 的 EntityMention，查 `KnowledgeChunk.parent_id`，将 child chunk 的实体归并到 parent chunk 后再与 PKU 匹配。

**改动**：
| 文件 | 改动 |
|---|---|
| `backend/app/services/graph_projection.py` | 桥接函数增加 child→parent 查表归并逻辑 |
| `backend/tests/test_graph_projection.py` | 新增 `test_project_pku_entity_mentions_rolls_up_child_to_parent` |

### Level 3：新增 `graph_entity_ckp` 融合检索链

**改动**：
| 文件 | 改动 |
|---|---|
| `engine/eval/compare_retrieval_chains.py` | 新增 `_graph_entity_ckp` 检索链（Cypher 双路径：Entity→PKU→CKP→Source + CKP→PKU→Source） |

**Cypher 双路径**：
- **Path A（实体→知识）**：query 词匹配 Entity canonical_name → `MENTIONS_ENTITY` → PKU → `EVIDENCED_BY` → Source chunk
- **Path B（知识→出处）**：query 词匹配 CKP title → `SUPPORTED_BY` → PKU → `EVIDENCED_BY` → Source chunk

## 三、量化结果

### 桥接覆盖面（L1 vs L2）

| 指标 | L1（无归并） | L2（child→parent 归并） | 提升 |
|---|---|---|---|
| MENTIONS_ENTITY 边 | 74 | **458** | 6.2x |
| 可达 Entity | 11 | **72** | 6.5x |
| 可达 PKU | 28 | **227** | 8.1x |
| 可达 CKP | 11 | **31** | 2.8x |
| 可达 document chunk | 3 | **32** | 10.7x |

### 检索链对比（expanded，60 题）

| 链 | Recall@10 | Hit@10 | MRR |
|---|---|---|---|
| traditional_hybrid | 0.511 | 95.0% | 0.863 |
| graph_ckp_pku（L0 基线） | 0.030 | 3.3% | 0.008 |
| graph_source（L0 基线） | 0.030 | 3.3% | 0.010 |
| **graph_entity_ckp（L3 新链）** | **0.100** | **10.0%** | **0.107** |

`graph_entity_ckp` 相比 L0 图链：R@10 提升 3.3x（0.030→0.100），Hit@10 提升 3x（3.3%→10.0%）。

### 融合分析（best-of recall）

| 融合组合 | Recall@10 | vs traditional 增量 |
|---|---|---|
| traditional 单独 | 0.511 | — |
| fusion trad + graph_entity_ckp | **0.554** | **+0.043 (+8.4%)** |
| fusion trad + all_graph | **0.574** | **+0.063 (+12.3%)** |

### graph_entity_ckp 召回深度优势的 5 题

| 查询 | 问题 | trad R@10 | gec R@10 |
|---|---|---|---|
| q001 | RAG 系统中父子块映射关系如何在工程落地中建立 | 0.33 | **1.0** |
| q012 | C++ 编码规范中数据库表存储引擎必须使用什么 | 0.6 | **1.0** |
| q021 | PreNorm 和 PostNorm 在定义和优缺点上的区别 | 0.8 | **1.0** |
| q029 | Git 提交规范中 'refactor' 类型代表什么含义 | 0.2 | **1.0** |
| q057 | 微调大模型的数据理解阶段需要明确哪四个问题 | 0.5 | **1.0** |

这 5 题均为**规则/概念型问题**，CKP 节点聚合了该概念的全部证据单元，图遍历一次召回完整相关 chunk（5/5），而传统向量只召回语义最相似的子集。

### 覆盖盲区（传统漏检的 3 题，图链仍无法补上）

q005/q010/q015 的相关 chunk 不在图的可达集（32 chunk 覆盖不足），需进一步扩大 PKU 抽取范围或将更多 chunk 投影到图。

## 四、测试

| 套件 | 结果 |
|---|---|
| `backend/tests/test_graph_projection.py` | **19/19 通过**（含 5 个新桥接测试） |
| `backend/tests/test_graph_sync.py` | **3/3 通过**（自动投影开关、三层投影顺序、best-effort 失败隔离） |
| 合计 | **22/22 通过** |

新增测试覆盖：
- 基本桥接（shared source_id 匹配）
- 一 PKU 多实体
- 无匹配 PKU 跳过
- deprecated 节点跳过
- **child→parent 归并**（child chunk 实体桥接到 parent chunk 的 PKU）

## 五、改动文件清单

源码：
- `backend/app/services/graph_projection.py` — `project_pku_entity_mentions` 函数 + child→parent 归并 + `pku_entity_mention_count` 字段
- `backend/app/services/graph_sync.py` — 新增 best-effort 自动投影封装；受 `ENTITY_GRAPH_ENABLED` 控制，默认关闭
- `backend/scripts/backfill_entity_graph.py` — 调用桥接投影
- `engine/app/jobs/worker.py` — 文档治理 job `mark_done` 提交后触发自动投影，不回滚治理结果
- `backend/app/api/assets.py` — 资产单元 confirm 提交后触发自动投影
- `engine/eval/compare_retrieval_chains.py` — `graph_entity_ckp` 检索链

测试：
- `backend/tests/test_graph_projection.py` — 5 个新测试
- `backend/tests/test_graph_sync.py` — 3 个新测试

## 六、运行产物

| 文件 | 说明 |
|---|---|
| `evaluation/runs/retrieval/2026-06-30_091512_compare/summary.json` | traditional + graph_ckp_pku + graph_source + graph_entity_ckp 全链对比 |

## 七、后续

- **覆盖盲区**：3 题漏检的根因是 PKU 抽取覆盖仅 97 parent chunk（820 PKU），实体覆盖 880 chunk。扩大 PKU 抽取范围或补充 LLM 抽取可减少盲区。
- **实体检索测评集**：golden 数据集为自然语言知识问题，不含实体型查询（如"谭彦超出现在哪些资料"）。建议新建实体检索测评集以量化 Entity→PKU→CKP 路径的实体查询能力。
- **生产自动投影**：已接入文档 governance worker 与资产单元 confirm API。默认由 `ENTITY_GRAPH_ENABLED=0` 关闭；开启后在 SQL 提交成功后 best-effort 投影 CKP/PKU、Entity/Alias/Source 与 `MENTIONS_ENTITY` 桥接边，投影失败只记录日志，不影响治理成功结果。
