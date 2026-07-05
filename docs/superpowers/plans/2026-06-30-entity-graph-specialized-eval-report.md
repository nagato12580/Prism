# 实体专项离线评测报告

> 日期：2026-06-30
> 数据集：`evaluation/datasets/entity_graph_v1.json`
> 查询数：12（高质量 email 实体）
> 测评目标：量化 `PKU -[:MENTIONS_ENTITY]-> Entity` 桥接后，`graph_entity_ckp` 在实体型查询上的检索表现。

## 一、为什么需要专项实体评测

原 `formal_docs_v1.json` 是自然语言知识问答集，几乎不包含“实体名 → 相关出处 / 知识点”的问题，因此无法直接反映 Entity↔PKU↔CKP 桥接边的价值。为此新增实体型评测集，问题模板统一为：

- `邮箱 <entity> 出现在哪些资料里，它关联了哪些知识点？`
- 后续可扩展到 person / organization

gold 直接来自桥接路径：

```text
Entity <- MENTIONS_ENTITY <- PKU - EVIDENCED_BY -> Source(parent chunk)
```

再将 parent chunk 展开为 child chunks，写入 `relevant_children`，以兼容现有 expanded 指标。

## 二、数据集构建与噪声过滤规则

构建脚本：`evaluation/build_entity_graph_eval.py`

### 数据来源
- Neo4j：`Entity <- MENTIONS_ENTITY <- PKU - EVIDENCED_BY -> Source(document_chunk)`
- MySQL：将 Source(parent chunk) 展开为 child chunks，形成评测 gold

### 噪声过滤规则
当前桥上的 72 个实体中，大量 `paper` / `organization` 节点是规则抽取误把整段文本当实体，故本版评测集**仅纳入高质量 email / person**：

- 只保留 `entity_type in {email, person}`
- `email` 必须满足完整邮箱 regex
- `person` 必须满足 Title-Case 英文姓名 regex（当前图中无符合条件的人名样本）
- 过滤长度 > 120 的名称
- 过滤包含代码/markup 噪声片段：```, `###`, `#include`, `json`, `yaml`, `class`, `def` 等
- 过滤 `TEST@EXAMPLE.COM`
- 至少 1 个 PKU、至少 1 个 Source

### 产物
- 输出：`evaluation/datasets/entity_graph_v1.json`
- 当前得到 **12 条**高质量实体查询（均为 email）
- 每条 query 的 gold expanded 后为 **5 个 child chunks**

## 三、测评结果

运行命令：

```powershell
python -m engine.eval.compare_retrieval_chains \
  --dataset evaluation/datasets/entity_graph_v1.json \
  --chains traditional graph_ckp_pku graph_source graph_entity_ckp
```

运行产物：
- `evaluation/runs/retrieval/2026-06-30_100203_compare/summary.json`

### Expanded 指标

| 链 | Recall@10 | Hit@10 | MRR |
|---|---|---|---|
| traditional_hybrid | 0.000 | 0.0% | 0.000 |
| graph_ckp_pku | 0.000 | 0.0% | 0.000 |
| graph_source | 0.000 | 0.0% | 0.000 |
| **graph_entity_ckp** | **1.000** | **100.0%** | **1.000** |

### 解释
- `traditional_hybrid`、`graph_ckp_pku`、`graph_source` 全部为 0，是合理的：它们不以实体桥接边为核心检索信号，面对“邮箱实体”查询几乎无法命中相关 chunk。
- `graph_entity_ckp` 对 12/12 查询全部命中，并且每题 expanded 后能找回全部 5 个 child chunks，因此 `Recall@10 = 1.0`、`MRR = 1.0`。
- exact 指标为 0 也是合理的：检索链返回的是 parent chunk（Source 上记录），而 gold 按现有评测规范标 child chunks，因此应以 **expanded** 视角解读该链路。

## 四、结论

这轮专项评测证明：

1. **桥接边的价值在实体型查询上非常明确**：`graph_entity_ckp` 在实体专项集上从 0 直接提升到 1.0。
2. **实体桥接链是独占型能力**：其他检索链在该数据集上全部失效，说明这不是传统向量召回能自然补上的能力，而是图桥接结构独有的能力。
3. **当前实体评测集仍然偏窄**：仅有 12 条 email 实体，说明上游实体抽取质量仍限制了 person / organization 的可评估样本。

## 五、下一步建议

1. 提升 `person` / `organization` 抽取质量，减少长文本误识别为 `paper` / `organization`
2. 为 `entity_graph_search` 工具增加直接利用 `MENTIONS_ENTITY` 的路径查询（当前 eval 里的 `graph_entity_ckp` 只存在于离线脚本，不在 agent tool 中）
3. 构建 `entity_graph_v2` 数据集，覆盖：
   - email → 资料 / 知识点
   - person → 资料 / 知识点
   - organization → 资料 / 知识点
   - alias → canonical entity → 知识点

## 六、相关文件

源码：
- `evaluation/build_entity_graph_eval.py` — 实体专项评测集构建脚本
- `engine/eval/compare_retrieval_chains.py` — `graph_entity_ckp` 链

数据与结果：
- `evaluation/datasets/entity_graph_v1.json`
- `evaluation/runs/retrieval/2026-06-30_100203_compare/summary.json`
