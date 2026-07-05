# Prism 离线测评指标与复跑指南

> 日期：2026-07-01
> 目的：汇总当前系统的离线检索指标，并说明后续优化后如何复跑同一套测评集，保证前后对比可追踪、可复现。

---

## 一、当前离线测评集

Prism 当前主要有两套检索离线评测集：

| 数据集 | 路径 | 查询数 | 评估目标 |
|---|---|---:|---|
| `formal_docs_v1` | `evaluation/datasets/formal_docs_v1.json` | 60 | 通用知识问答检索（自然语言问题 -> 相关 chunk） |
| `entity_graph_v1` | `evaluation/datasets/entity_graph_v1.json` | 24 | 实体专项检索（实体名 -> 相关出处 / CKP/PKU 支持链路） |

### `formal_docs_v1` 的定位
- 面向：知识问答、主题/证据/出处检索
- gold：`relevant_children`（child chunk）
- 适合比较：
  - `traditional_hybrid`
  - `governed_ckp_pku`
  - `governed_evidence`
  - `graph_ckp_pku`
  - `graph_source`
  - `graph_entity_ckp`

### `entity_graph_v1` 的定位
- 面向：实体型问题，例如
  - “`Yanchao Tan` 出现在哪些资料里？”
  - “`xuchao@cis.pku.edu.cn` 关联了哪些知识点？”
- gold：通过
  - `Entity <- MENTIONS_ENTITY <- PKU - EVIDENCED_BY -> Source(parent chunk)`
  - 再展开为 child chunks
- 适合比较：
  - `graph_entity_ckp`
  - `traditional_hybrid`（做对照）

---

## 二、当前核心离线指标

### 2.1 实体专项集 `entity_graph_v1`（最新）

运行产物：
- `evaluation/runs/retrieval/2026-06-30_153239_compare/summary.json`
- 数据集：`evaluation/datasets/entity_graph_v1.json`
- 查询数：24

#### 指标

| 链 | exact R@10 | expanded R@10 | expanded Hit@10 | expanded MRR | 说明 |
|---|---:|---:|---:|---:|---|
| `graph_entity_ckp` | 0.000 | **0.958** | **95.8%** | **0.903** | 当前实体查询主力链 |
| `traditional_hybrid` | 0.020 | 0.020 | 8.3% | 0.046 | 仅作对照，几乎无效 |

#### 更完整指标

##### `graph_entity_ckp`
- exact
  - `recall@5 = 0.000`
  - `recall@10 = 0.000`
  - `mrr = 0.000`
- expanded
  - `recall@5 = 0.929`
  - `recall@10 = 0.958`
  - `precision@5 = 0.875`
  - `precision@10 = 0.458`
  - `mrr = 0.903`
  - `hit@10 = 95.8%`

##### `traditional_hybrid`
- exact / expanded（相同）
  - `recall@5 = 0.014`
  - `recall@10 = 0.020`
  - `precision@5 = 0.008`
  - `precision@10 = 0.008`
  - `mrr = 0.046`
  - `hit@10 = 8.3%`

#### 解读
- 实体专项集上，`graph_entity_ckp` 是唯一有效链
- exact 指标为 0 是**正常的**：图链返回的是 parent chunk，而 gold 最终按 child chunk 比较，所以应看 **expanded** 指标
- 当前 `graph_entity_ckp` 在 24 条实体型 query 上：
  - `95.8% Hit@10`
  - `0.958 Recall@10`
  - 说明桥接链已经进入可用状态

---

### 2.2 通用知识集 `formal_docs_v1`（图链对照）

运行产物：
- `evaluation/runs/retrieval/2026-06-30_091512_compare/summary.json`
- 数据集：`evaluation/datasets/formal_docs_v1.json`
- 查询数：60

#### 指标

| 链 | exact R@10 | expanded R@10 | expanded Hit@10 | expanded MRR | 说明 |
|---|---:|---:|---:|---:|---|
| `traditional_hybrid` | **0.511** | **0.511** | **95.0%** | **0.863** | 当前最强通用基线 |
| `graph_ckp_pku` | 0.000 | 0.030 | 3.3% | 0.008 | 纯图 CKP→PKU→Source 覆盖很低 |
| `graph_source` | 0.009 | 0.030 | 3.3% | 0.010 | 纯 Source 图索引效果很弱 |
| `graph_entity_ckp` | 0.000 | 0.100 | 10.0% | 0.107 | 有增益，但更适合实体型问题 |

#### 更完整指标

##### `traditional_hybrid`
- exact / expanded（相同）
  - `recall@5 = 0.427`
  - `recall@10 = 0.511`
  - `precision@5 = 0.427`
  - `precision@10 = 0.258`
  - `mrr = 0.863`
  - `hit@10 = 95.0%`

##### `graph_ckp_pku`
- expanded
  - `recall@10 = 0.030`
  - `precision@10 = 0.015`
  - `mrr = 0.008`
  - `hit@10 = 3.3%`

##### `graph_source`
- exact
  - `recall@10 = 0.009`
  - `mrr = 0.009`
- expanded
  - `recall@10 = 0.030`
  - `precision@10 = 0.015`
  - `mrr = 0.010`
  - `hit@10 = 3.3%`

##### `graph_entity_ckp`
- expanded
  - `recall@5 = 0.094`
  - `recall@10 = 0.100`
  - `precision@5 = 0.100`
  - `precision@10 = 0.053`
  - `mrr = 0.107`
  - `hit@10 = 10.0%`

#### 解读
- `traditional_hybrid` 仍然是通用知识问答的最强基线
- 图链在通用问答上不是替代品，而是**补充信号**
- `graph_entity_ckp` 对于概念/实体相关问题有帮助，但不适合作为通用主检索器

---

### 2.3 历史治理链基线 `formal_docs_v1`（旧基线）

运行产物：
- `evaluation/runs/retrieval/2026-06-22_170217_compare/summary.json`

#### 指标

| 链 | expanded R@10 | expanded Hit@10 | expanded MRR | 说明 |
|---|---:|---:|---:|---|
| `traditional_hybrid` | 0.516 | 95.0% | 0.856 | 历史通用基线 |
| `governed_ckp_pku` | 0.281 | 28.3% | 0.207 | V1 CKP→PKU 词法链 |
| `governed_evidence` | **0.602** | **61.7%** | **0.475** | 历史最强治理证据链 |

#### 解读
- `governed_evidence` 在治理知识检索上仍然非常强
- 若未来要优化治理层工具（如 `knowledge_evidence_search` / `governed_knowledge_v2`），应继续拿这一组指标做对照

---

## 三、当前综合结论

### 3.1 如果问“当前系统最强的通用检索是什么？”
答案是：
- **`traditional_hybrid`**
  - `formal_docs_v1` 上 `R@10 = 0.511`
  - `Hit@10 = 95.0%`
  - `MRR = 0.863`

### 3.2 如果问“当前系统最强的实体检索是什么？”
答案是：
- **`graph_entity_ckp`**
  - `entity_graph_v1` 上 `expanded R@10 = 0.958`
  - `expanded Hit@10 = 95.8%`
  - `expanded MRR = 0.903`

### 3.3 如果问“图链值不值得保留？”
答案是：**值得，但定位要清楚**
- 图链不是通用知识问答主引擎
- 图链是：
  - 实体型查询主链
  - 知识治理图的补充信号
  - `entity_graph_search` 工具的核心能力来源

---

## 四、后续优化后如何复跑同一套测评集

统一入口脚本：

```powershell
python -m engine.eval.compare_retrieval_chains --help
```

CLI 参数：
- `--dataset DATASET`
- `--output-root OUTPUT_ROOT`
- `--chains ...`
- `--verbose`

当前支持的 chain：
- `traditional`
- `governed`
- `governed_evidence`
- `bottom_up`
- `governed_v2`
- `page_index`
- `graph_ckp_pku`
- `graph_source`
- `graph_entity_ckp`

### 4.1 复跑通用知识集

#### 推荐命令（当前图链对照）

```powershell
python -m engine.eval.compare_retrieval_chains \
  --dataset evaluation/datasets/formal_docs_v1.json \
  --chains traditional graph_ckp_pku graph_source graph_entity_ckp
```

#### 如果要和历史治理基线对比

```powershell
python -m engine.eval.compare_retrieval_chains \
  --dataset evaluation/datasets/formal_docs_v1.json \
  --chains traditional governed governed_evidence
```

### 4.2 复跑实体专项集

#### 推荐命令

```powershell
python -m engine.eval.compare_retrieval_chains \
  --dataset evaluation/datasets/entity_graph_v1.json \
  --chains graph_entity_ckp traditional
```

### 4.3 需要 verbose 产物时

```powershell
python -m engine.eval.compare_retrieval_chains \
  --dataset evaluation/datasets/entity_graph_v1.json \
  --chains graph_entity_ckp traditional \
  --verbose
```

`--verbose` 会额外输出带召回 chunk 文本的 JSON，便于人工分析 badcase。

### 4.4 输出位置

默认输出到：

```text
evaluation/runs/retrieval/<timestamp>_compare/
```

其中关键文件：
- `summary.json`：总指标
- `detailed_exact.csv`：exact 逐题指标
- `detailed_expanded.csv`：expanded 逐题指标
- `verbose_*.json`：带文本的详细召回结果（仅 `--verbose`）

---

## 五、如果后续你要优化，推荐的评测流程

### 5.1 优化图链 / 实体链时

适用场景：
- `entity_graph_search`
- `project_pku_entity_mentions`
- `entity_extraction.py`
- `graph_entity_ckp`

#### 必跑

```powershell
python -m evaluation.build_entity_graph_eval --limit 25
python -m engine.eval.compare_retrieval_chains \
  --dataset evaluation/datasets/entity_graph_v1.json \
  --chains graph_entity_ckp traditional
```

#### 关注指标
- `expanded recall@10`
- `expanded hit@10`
- `expanded mrr`
- `query count` 是否变化
- person / organization 是否增加、且是否更干净

### 5.2 优化治理检索链时

适用场景：
- `knowledge_evidence_search`
- `governed_knowledge_v2`
- `knowledge_material_search`
- PKU/CKP 向量策略

#### 必跑

```powershell
python -m engine.eval.compare_retrieval_chains \
  --dataset evaluation/datasets/formal_docs_v1.json \
  --chains traditional governed governed_evidence governed_v2
```

#### 关注指标
- `expanded recall@10`
- `expanded precision@10`
- `expanded mrr`
- `expanded hit@10`

### 5.3 优化通用混合检索时

适用场景：
- hybrid / BM25 / Milvus embedding / parent-child expansion

#### 必跑

```powershell
python -m engine.eval.compare_retrieval_chains \
  --dataset evaluation/datasets/formal_docs_v1.json \
  --chains traditional graph_entity_ckp graph_ckp_pku graph_source
```

#### 关注指标
- `traditional_hybrid` 是否上升
- `graph_entity_ckp` 是否对知识集有附加增益

---

## 六、推荐的评测决策规则

为了后续 agent 或开发者能快速判断优化是否有效，建议用下面的标准：

### 规则 A：优化实体图链
只有同时满足以下条件，才算有效提升：
- `entity_graph_v1` 上 `graph_entity_ckp expanded recall@10` 不下降
- `hit@10` 不下降
- `person / organization` 的 query 样本数不下降，或质量更高

### 规则 B：优化治理检索链
只有同时满足以下条件，才算有效提升：
- `formal_docs_v1` 上 `governed_evidence / governed_v2` 的 `expanded recall@10` 上升
- `precision@10` 不明显恶化
- `MRR` 不下降

### 规则 C：优化通用主检索
只有当以下条件满足时，才算值得合入：
- `traditional_hybrid` 在 `formal_docs_v1` 上 `R@10` 高于当前 0.511
- 或在不降低 `traditional_hybrid` 的情况下，让 `fusion(traditional + graph)` 更高

---

## 七、优化 Checklist

下面这份 checklist 适合后续每次改检索、改实体抽取、改图投影时直接照着执行。

### 7.1 变更前

- 明确本次改动属于哪一类：
  - 通用检索
  - 治理检索
  - 图桥接 / 实体检索
  - 实体抽取质量
- 记录当前基线 run：
  - 通用集：`2026-06-30_091512_compare`
  - 实体集：`2026-06-30_153239_compare` 及之后的最新重建结果
- 明确要优化的主指标：
  - `expanded recall@10`
  - `expanded hit@10`
  - `expanded mrr`
  - `precision@10`
- 如果改动涉及实体抽取或桥接边：
  - 先确认是否需要重跑 `backfill_entity_graph`
  - 先确认是否需要重建 `entity_graph_v1.json`

### 7.2 变更中

- 先跑定向单测，而不是一开始全量回填
- 任何影响图链的改动都至少验证：
  - `backend/tests/test_graph_projection.py`
  - `backend/tests/test_graph_sync.py`
  - `engine/tests/test_entity_graph_search_tool.py`
- 任何影响实体抽取的改动都至少补一个：
  - 正例测试
  - badcase 回归测试
- 任何改动都必须保留旧 run 的对照，不要覆盖旧产物目录

### 7.3 变更后

- 通用检索改动：重跑 `formal_docs_v1.json`
- 图桥接 / 实体检索改动：
  1. 重跑 `backfill_entity_graph`
  2. 重建 `entity_graph_v1.json`
  3. 重跑实体专项评测
- 记录以下结果：
  - 运行命令
  - run 目录路径
  - summary.json 核心指标
  - 与上个基线 run 的 delta
  - 典型 badcase 是否被修复

---

## 八、发布前验收标准

下面是建议直接作为"是否允许合并 / 发布"的 gate。

### 8.1 通用检索改动（发布 gate）

必须满足：

- `formal_docs_v1` 上 `traditional_hybrid expanded recall@10` **不低于 0.511**
- `formal_docs_v1` 上 `traditional_hybrid expanded hit@10` **不低于 95.0%**
- `formal_docs_v1` 上 `traditional_hybrid expanded mrr` **不低于 0.863 - 0.01**

若是图增强类改动，还应满足至少一条：

- `graph_entity_ckp expanded recall@10` **高于 0.100**
- 或 `traditional + graph` 融合结果优于当前基线

### 8.2 治理检索改动（发布 gate）

必须满足：

- `governed_evidence` / `governed_v2` 的 `expanded recall@10` **不下降**
- `expanded precision@10` **不明显下降**（建议阈值：不低于基线 - 0.02）
- `expanded hit@10` **不下降**

### 8.3 实体图链改动（发布 gate）

必须满足：

- `entity_graph_v1` 上 `graph_entity_ckp expanded hit@10` **不低于 95.0%**
- `entity_graph_v1` 上 `graph_entity_ckp expanded recall@10` **不低于 0.95**
- `entity_graph_v1` 上 `graph_entity_ckp expanded mrr` **不低于 0.90**
- `traditional_hybrid` 在该数据集上依然显著落后（用于证明图链独占价值，不要求上升）

若变更涉及实体抽取质量，还必须满足：

- 高质量样本数（query count）**不下降**
- `person / organization` 样本数不下降，或虽下降但噪声显著减少并有文档说明
- 关键噪声 badcase（如 `Senior Member` / `Proximal Gradient`）不回归

### 8.4 自动投影 / 图同步改动（发布 gate）

必须满足：

- `test_graph_projection.py` 全绿
- `test_graph_sync.py` 全绿
- `test_entity_graph_search_tool.py` 全绿
- 至少执行一次手动：
  - `python -m backend.scripts.backfill_entity_graph`
  - 并确认 `pku_entity_mention_count` 非 0

---

## 九、当前建议作为“版本基线”的指标

为了后面优化便于比较，建议把下面这组指标作为当前基线：

### 通用知识集基线（推荐）
- Run：`2026-06-30_091512_compare`
- Dataset：`formal_docs_v1.json`
- `traditional_hybrid`
  - `expanded recall@10 = 0.511`
  - `expanded hit@10 = 95.0%`
  - `expanded mrr = 0.863`
- `graph_entity_ckp`
  - `expanded recall@10 = 0.100`
  - `expanded hit@10 = 10.0%`
  - `expanded mrr = 0.107`

### 实体专项集基线（推荐）
- Run：`2026-06-30_153239_compare`（旧 24 query 版）
  - `graph_entity_ckp expanded recall@10 = 0.958`
  - `hit@10 = 95.8%`
  - `mrr = 0.903`
- Run：`2026-06-30_153239_compare` 之后经人名/组织清洗，当前最新应以重建后的 `entity_graph_v1.json` +
  `2026-06-30_153239_compare` / `2026-06-30_144942_compare` / `2026-06-30_140420_compare` 为历史参照，
  **你后续优化建议直接以最新数据集重新跑并记录新 timestamp run 作为新基线**。

> 说明：`entity_graph_v1` 目前是随规则重建的数据集，query 数会随实体质量变化（12 → 13 → 20 → 24）。这类数据集要把“样本数变化”和“指标变化”一起看，不能只看单个 R@10。

---

## 十、建议的发布记录模板

每次优化后，建议在 PR 或 handoff 文档中按这个模板记录：

```md
### Retrieval Eval Record

- Change type: 通用检索 / 治理检索 / 图桥接 / 实体抽取
- Dataset(s): formal_docs_v1 / entity_graph_v1
- Commands run:
  - `python -m engine.eval.compare_retrieval_chains ...`
- New run dir:
  - `evaluation/runs/retrieval/<timestamp>_compare/`
- Baseline run dir:
  - `evaluation/runs/retrieval/<previous_timestamp>_compare/`
- Key deltas:
  - `traditional_hybrid expanded recall@10`: 0.511 -> 0.524 (+0.013)
  - `graph_entity_ckp expanded hit@10`: 95.8% -> 100.0% (+4.2%)
- Sample count change:
  - `entity_graph_v1`: 24 -> 26
- Badcases checked:
  - `Senior Member` not extracted as person
  - `Proximal Gradient` not extracted as person
- Decision:
  - Pass / Fail
```

---

## 十一、当前结论一句话

> 当前系统的离线指标表现是：**通用知识问答靠 `traditional_hybrid`，实体型检索靠 `graph_entity_ckp`**；后续优化应继续复用 `formal_docs_v1.json` 和 `entity_graph_v1.json` 这两套评测集，并按本文中的命令和指标口径进行前后对比。
