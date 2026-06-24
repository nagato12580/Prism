# Governed Knowledge V2 — 向量优先检索方案设计

> 状态：设计中  
> 日期：2026-06-24  
> 约束：不修改现有代码逻辑，仅新增文件或复用现有组件

## 1. 背景与问题

### 1.1 现有 governed_knowledge_search 的问题

当前 `engine/app/agent/tools/governed_knowledge.py` 的检索链路：

```
query → 分词 → MySQL 拉 CKP(最多80条) → 子串匹配打分 → 回溯 PKU → 回溯来源
```

核心缺陷：

| 问题 | 影响 |
|------|------|
| **无语义匹配** | `term in text` 子串包含，"低秩适配"命不中 "LoRA fine-tuning" |
| **召回上限 80 条** | CKP 超过 80 条后，相关知识点不在"最近更新80条"里就永远检索不到 |
| **CKP 向量库闲置** | `prism_ckp` 已建好向量，但聊天检索不用，只在入库归并时用 |
| **语义空间不一致** | CKP 是归一陈述（结论式），用户 query 是问句，embedding 空间不对齐 |
| **信息有损** | CKP.canonical_statement 是多 PKU 归并压缩，非原文 |

### 1.2 核心洞察

**越靠近用户问句语义空间的那一层（原文 chunk），信息损耗越小；越往上归一的那一层（CKP），损耗越大。**

当前架构把向量库建在了 chunk 层（`prism_knowledge`，已有且在用）和 CKP 层（`prism_ckp`，仅入库用），而聊天检索却用纯关键词打分在 CKP 层做——既没用向量，又用了信息损耗最大的层。

**正确用法**：检索在底层（chunk 原文，语义空间最对齐、0 损耗），归一在上层（CKP/PKU 做聚合、去重、证据组织）。

## 2. 方案设计

### 2.1 核心思路：Chunk 向量召回 → 反查 PKU → 聚合 CKP

```
用户 query
  │
  ├─① 向量召回 chunk（复用 prism_knowledge + embed_query + search_vectors）
  │   hits: [{chunk_id(child), item_id, score}]
  │
  ├─② child→parent 映射（复用 KnowledgeChunk.parent_id 模式）
  │   child_chunk_id → parent_chunk_id
  │
  ├─③ 反查 PKU（PersonalKnowledgeUnit.source_kind='document_chunk', source_id=parent_id）
  │   parent_chunk_id → [PKU...]
  │
  ├─④ 聚合 CKP（PKUCanonicalLink.pku_id → canonical_id）
  │   [PKU...] → {CKP_id: [PKU...]}
  │
  ├─⑤ CKP 打分（向量分数 + PKU 数量 + 置信度）
  │   排序取 top limit
  │
  ├─⑥ 构建证据包（复用 _build_evidence_bundle：CKP→linked_pkus→raw_sources）
  │
  ├─⑦ 资产兜底（复用 _score_fields 对 PersonalAssetUnit 打分）
  │
  └─⑧ 返回 JSON（与现有工具同 shape，runner 无感知）
```

### 2.2 为什么这样设计

| 设计决策 | 理由 |
|---------|------|
| 向量召回用 chunk 原文 | chunk_text 是原文，与用户问句语义空间最对齐，0 信息损耗 |
| 不用 CKP 向量做召回 | CKP 是归一陈述，与问句空间不一致，信息有损 |
| CKP/PKU 做聚合层 | 发挥其真正价值：跨源去重、证据组织、置信度/状态/父子层级 |
| 复用 prism_knowledge 向量库 | 已建好、已在用、向量空间与入库一致（同 embedding 模型） |
| child→parent 映射 | Milvus 只存 child chunk，PKU 从 parent chunk 抽取，必须映射 |
| 保留资产兜底 | 个人资产无向量库，用词项打分兜底，保证覆盖面 |

### 2.3 CKP 打分公式

每个 CKP 的得分由"哪些 chunk 经哪些 PKU 追溯到它"决定：

```
ckp_score = max_chunk_score                       # 最强向量信号（主权重）
          + pku_hit_count * 0.15                  # 命中 PKU 数量（覆盖度）
          + avg_link_confidence * 0.10            # 关联置信度
          + ckp.confidence * 0.10                 # CKP 自身置信度
```

- `max_chunk_score`：追溯到该 CKP 的所有 chunk 中最高的向量 cosine 分数（0~1）
- `pku_hit_count`：该 CKP 被命中的不同 PKU 数量
- `avg_link_confidence`：这些 PKU↔CKP link 的平均置信度
- `ckp.confidence`：CKP 自身的置信度

排序：按 `ckp_score` 降序，取 top `limit`。

### 2.4 优雅降级

| 场景 | 行为 |
|------|------|
| 有治理数据（PKU/CKP） | 完整链路：chunk→PKU→CKP 证据包 |
| chunk 命中但无 PKU/CKP | 返回 chunk 原文作为 raw_sources，无 CKP 层 |
| 无 chunk 命中 | 资产兜底：PersonalAssetUnit 词项打分 |
| 全部为空 | status="insufficient" |

## 3. 实现方案

### 3.1 新增文件

| 文件 | 作用 |
|------|------|
| `engine/app/agent/tools/governed_knowledge_v2.py` | 新工具模块，向量优先检索 |
| `engine/tests/test_governed_knowledge_v2.py` | 单元测试 |
| `engine/eval/run_governed_eval.py` | A/B 评测脚本 |

### 3.2 修改文件（仅 1 行新增 import）

| 文件 | 改动 |
|------|------|
| `engine/app/agent/tools/__init__.py` | 末尾加 `import engine.app.agent.tools.governed_knowledge_v2  # noqa: F401` |

### 3.3 复用的现有组件

| 组件 | 来源 | 用途 |
|------|------|------|
| `embed_query` | `engine/app/ingestion/vectorizer.py:23` | query 向量化 |
| `search_vectors` | `engine/app/milvus_client.py:47` | chunk 向量召回 |
| `_build_evidence_bundle` | `governed_knowledge.py:323` | CKP→PKU→raw_sources 证据包 |
| `_source_for_pku` | `governed_knowledge.py:251` | PKU→原始来源回溯 |
| `_append_unique_citations` | `governed_knowledge.py:420` | 引用去重 |
| `_score_fields` | `governed_knowledge.py:170` | 资产兜底打分 |
| `_personal_asset_unit_fields` | `governed_knowledge.py:190` | 资产字段提取 |
| `_personal_asset_unit_result` | `governed_knowledge.py:212` | 资产结果组装 |
| `_KNOWLEDGE_FIELD_WEIGHTS` | `governed_knowledge.py:76` | 资产打分权重 |
| `ToolContext/ToolSpec/register_tool` | `base.py` | 工具注册 |
| child→parent 映射模式 | `answer.py:36-40` | small-to-big |

### 3.4 返回 JSON 结构（与现有工具兼容）

```jsonc
{
  "status": "success" | "insufficient",
  "summary": "...",
  "retrieval_path": "vector_first",
  "chunk_hits": [{chunk_id, item_id, score}],
  "canonical_results": [{canonical_id, title, canonical_statement, ..., score, matched_terms, match_reasons}],
  "evidence_bundle": [{...canonical_results, linked_pkus, raw_sources}],
  "knowledge_results": [...],
  "source_results": [...],
  "sources": [...]
}
```

新增 `retrieval_path: "vector_first"` 字段标识来源，其余结构与现有工具一致，runner 无感知。

## 4. 评测方案

### 4.1 评测目标

对比 **baseline（hybrid_search）** 与 **v2（向量优先 + CKP 聚合）** 在同一黄金数据集上的表现。

### 4.2 黄金数据集

复用 `engine/eval/golden_dataset.json`（60 条，chunk 级 ground truth）。

### 4.3 评测指标

**Chunk 层（两路可比）**：
- recall@5/10/20, precision@5/10/20, hit@5/10/20, ndcg@5/10/20, MRR

**CKP 层（v2 新增能力）**：
- 从 golden 的 `parent_chunk_id` 推导 CKP ground truth（parent→PKU→CKP）
- ckp_hit_rate：返回的 CKP 中有多少命中 ground truth
- ckp_precision：返回 CKP 的精确率

### 4.4 运行方式

```bash
cd engine && python -m eval.run_governed_eval [--dataset golden_dataset.json] [--verbose]
```

输出 `engine/eval/results/<timestamp>/`：
- `comparison.csv`：每条 query 的 baseline vs v2 指标对比
- `summary.json`：聚合统计 + A/B 对比
- `detailed_verbose.json`（--verbose）：含检索结果正文
