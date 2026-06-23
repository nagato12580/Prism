# PKU 向量检索链路设计

## 背景

上一阶段新增了 `governed_evidence` 链路，把 CKP/PKU 从纯语义治理结构推进到证据召回层。测评结果显示，新链路相比原 `governed_ckp_pku` 有明显提升：

```text
governed_ckp_pku
Expanded Recall@10: 0.281
Expanded Hit@10:    28.3%
Expanded MRR:       0.207

governed_evidence
Expanded Recall@10: 0.632
Expanded Hit@10:    65.0%
Expanded MRR:       0.492
```

但失败样本也暴露出一个核心问题：很多细粒度答案只存在于 PKU 的 `statement`、`normalized_statement` 或 `evidence_span` 中，不一定存在于 CKP 的标题、摘要或标准表述里。

因此，继续微调 CKP 排序的收益有限。下一阶段应该给 PKU 增加独立向量检索能力，让 query 可以直接命中具体证据，再从 PKU 回溯到 CKP 和原文 chunk。

## 当前状态

`PersonalKnowledgeUnit` 模型已经有向量相关字段：

```text
embedding_ref
embedding_model
embedding_status
```

但目前只有 CKP 有完整向量服务：

```text
backend/app/services/ckp_vectors.py
```

当前缺口：

1. 没有 `prism_pku` 向量集合。
2. 没有 `upsert_pku_vector()`。
3. 没有 `search_pku_vectors()`。
4. PKU 创建后没有刷新向量。
5. 历史 PKU 没有 backfill 向量。
6. `governed_evidence` 查询时没有 PKU vector recall。

## 设计目标

新增一条 PKU 向量召回路径：

```text
query
  -> PKU vector recall
  -> PKU -> CKP link 回溯
  -> 融入 CKP 候选集
  -> 提升对应 PKU evidence score
  -> 返回 parent chunk evidence
  -> expanded metric 展开到 child chunk
```

目标不是让 PKU 替代 CKP，而是让 PKU 成为细粒度证据入口。

CKP 继续负责：

- 语义归并
- 稳定知识点表达
- 跨来源知识组织
- 候选知识主题路由

PKU 负责：

- 具体事实陈述
- evidence span 承载
- 原文证据回溯
- 细粒度问答命中

## 向量集合设计

新增 Milvus collection：

```text
prism_pku
```

字段建议：

```text
id              vector row id
embedding       FLOAT_VECTOR
pku_id          PKU id
user_id         用户 id
unit_type       claim / definition / opinion 等
source_kind     document_chunk / personal_asset_unit / personal_asset_item
source_id       原始来源 id
```

索引参数与 CKP 保持一致：

```text
index_type: IVF_FLAT
metric_type: COSINE
nlist: 128
nprobe: 32
```

## PKU 向量文本

PKU embedding text 应该面向“用户会怎么问”，而不是只保存结构化字段。

建议拼接：

```text
statement
normalized_statement
evidence_span
subject / predicate / object
keywords
concepts
entities
domains
unit_type
source_kind
```

其中优先级最高的是：

1. `statement`
2. `normalized_statement`
3. `evidence_span`
4. `keywords`
5. `concepts`

原因：

- `statement` 是 PKU 的可读陈述。
- `evidence_span` 更接近原文，适合细粒度事实问答。
- `keywords/concepts/entities` 可以补充短 query 的语义锚点。

## 写入链路

新增服务：

```text
backend/app/services/pku_vectors.py
```

核心函数：

```python
upsert_pku_vector(pku: PersonalKnowledgeUnit) -> str
search_pku_vectors(*, text: str, user_id: str, unit_type: str = "", source_kind: str = "", top_k: int = 20) -> list[dict]
```

在 `backend/app/services/knowledge_governance.py` 中新增：

```python
_refresh_pku_vector(pku)
```

在 PKU 创建后调用：

- `_create_or_get_document_pku_from_extracted`
- `_create_or_get_asset_pku`
- 其他创建 `PersonalKnowledgeUnit` 的入口

刷新逻辑：

```text
upsert 成功:
  embedding_ref = vector id
  embedding_model = settings.EMBEDDING_MODEL
  embedding_status = done

upsert 失败:
  embedding_status = failed

未配置 embedding provider:
  embedding_status = pending
```

## 历史数据 backfill

因为当前库里已经有大量 PKU，所以需要补向量脚本：

```text
backend/scripts/backfill_pku_vectors.py
```

命令：

```powershell
python -m backend.scripts.backfill_pku_vectors --user-id default-user --limit 500
```

行为：

1. 扫描 `status == active` 的 PKU。
2. 默认只处理 `embedding_status != done` 或 `embedding_ref` 为空的 PKU。
3. 调用 `upsert_pku_vector()`。
4. 每批提交一次。
5. 输出统计：
   - scanned
   - updated
   - skipped
   - failed

## 查询链路融合

`governed_evidence` 当前链路：

```text
query
  -> CKP vector recall
  -> CKP lexical recall
  -> CKP fusion
  -> linked PKU query-aware rerank
  -> evidence
```

加入 PKU vector 后：

```text
query
  -> CKP vector recall
  -> CKP lexical recall
  -> PKU vector recall
  -> PKU hits 回溯 CKP
  -> CKP/PKU candidate fusion
  -> linked PKU query-aware rerank
  -> evidence
```

PKU vector hit 有两个作用：

1. 把关联 CKP 拉入候选集。
2. 给对应 PKU 的 evidence score 加 boost。

建议第一版融合方式：

```text
pku_vector_score_by_pku_id[pku_id] = vector score
pku_vector_score_by_ckp_id[ckp_id] = max(linked PKU vector score)
```

CKP 融合阶段增加：

```text
pku_vector_weight / (rrf_k + pku_vector_rank + 1)
```

PKU evidence rerank 阶段增加：

```text
0.20 * pku_vector_score
```

同时适当下调原有局部分数，避免总分超过 1 后失去区分度。

## 降级策略

PKU vector search 必须可降级：

- Milvus 不可用：继续使用 CKP vector + lexical。
- embedding provider 不可用：继续使用 lexical。
- PKU collection 不存在：返回空候选，不影响主链路。
- 单个 PKU upsert 失败：标记 `embedding_status = failed`，不影响 PKU 入库。

## 测评目标

当前基线：

```text
governed_evidence
Expanded Recall@10: 0.632
Expanded Hit@10:    65.0%
Expanded MRR:       0.492
```

Phase 2 目标：

```text
Expanded Recall@10 >= 0.70
Expanded Hit@10    >= 75%
Expanded MRR       >= 0.55
```

重点观察失败类型是否减少：

- 英文问题检索中文文档
- 默认值 / 日期 / 章节号
- CKP 标题宽泛但 evidence span 具体
- 细粒度数值类问题

## 测试策略

新增测试：

```text
backend/tests/test_pku_vectors.py
```

覆盖：

- 使用独立 collection `prism_pku`
- upsert 后 flush collection
- search 时按 user_id 过滤
- search 可按 unit_type/source_kind 过滤

扩展测试：

```text
backend/tests/test_document_chunk_pku_extraction.py
backend/tests/test_asset_unit_pku_extraction.py
engine/tests/test_governed_knowledge_search.py
```

覆盖：

- 文档 PKU 创建后刷新向量状态
- asset PKU 创建后刷新向量状态
- `governed_evidence` 使用 PKU vector hit 召回 CKP
- PKU vector hit 能提升对应 evidence 排名
- PKU vector search 失败时链路降级

## 交付物

本阶段完成后应产出：

1. `backend/app/services/pku_vectors.py`
2. PKU 创建后的向量刷新逻辑
3. `backend/scripts/backfill_pku_vectors.py`
4. `governed_evidence` 接入 PKU vector recall
5. 单元测试和集成测试
6. backfill 运行结果
7. 三链路测评结果
8. 中文测评报告

## 风险

1. **向量写入成本增加**
   - 每个 PKU 都要生成 embedding。
   - 需要 backfill 控制批量和失败重试。

2. **查询延迟增加**
   - query-time 同时查 CKP vector 和 PKU vector。
   - 后续需要 query embedding 缓存和批量化。

3. **PKU 向量召回可能带来噪声**
   - 特别是 PKU statement 太短或过宽泛时。
   - 需要通过 rerank 和 CKP link confidence 控制。

4. **历史数据向量状态不一致**
   - backfill 前后要记录统计。
   - 不应该让部分失败 PKU 影响主检索链路。

## 结论

PKU 向量检索是 `governed_evidence` 下一阶段最关键的增强点。

CKP 负责“语义组织”，PKU 负责“证据命中”。只有把 query 直接连到 PKU evidence，才能继续提升细粒度事实问答、数值问答、章节问答和跨语言查询的召回能力。
