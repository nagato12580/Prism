# 分层 CKP/PKU 渐进式召回链路设计

## 背景

当前 `governed_evidence` 链路已经引入 CKP 向量召回、CKP 词面召回和 PKU 向量召回，相比早期 `governed_ckp_pku` 有明显提升。但最新评测也暴露出一个结构性问题：当前链路仍然偏“全局混排”，PKU 向量可以直接把语义相近但主题不准的证据拉进候选池，导致正确证据被噪声挤下去。

同时，CKP 的 `summary` / `canonical_statement` 字段目前更像“结论型摘要”，例如：

```text
Python 项目建议采用分层项目结构：app/包含主应用代码，models/、services/、repositories/、utils/、tests/等模块。
```

这类字段适合人读，但不适合作为向量召回主入口。用户真实问题可能是“FastAPI 项目 service 和 repository 怎么拆”“Python 后端目录怎么设计”，这些表达不会稳定出现在 summary 中。如果继续把父 CKP 或普通 CKP summary 当作向量匹配核心，会出现抽象层级越高、细节丢失越严重的问题。

因此，本阶段将治理检索链路改造为“渐进式披露”结构：

```text
父 CKP：目录路由层，只圈定主题范围
子 CKP：语义匹配层，用多向量入口匹配用户问法
PKU：证据层，返回具体事实与原文证据
全局 PKU：低权重兜底，只在局部召回不足时补充
LLM rerank：第一阶段不启用，等待离线指标验证后再决定
```

## 设计目标

第一阶段目标不是直接追求最终回答质量，而是把检索结构变得更稳、更可解释，并通过离线评测验证是否提升。

核心目标：

1. 降低全局 PKU vector 直接混排带来的噪声。
2. 避免父 CKP summary 过度抽象导致的向量误召回。
3. 让召回路径可解释：命中了哪个父 CKP、哪个子 CKP、哪个 PKU。
4. 让子 CKP 支持多个语义入口，而不是一个 summary 向量承载所有问法。
5. 保留全局 PKU vector 兜底能力，但不能让它破坏分层主链路。
6. 第一阶段不引入 query-time LLM rerank，先看离线指标。

## 非目标

第一阶段不做以下事情：

1. 不把父 CKP summary 作为向量召回主入口。
2. 不在父 CKP 层做 LLM 相关度判断。
3. 不在查询时对大量 CKP/PKU 调用 LLM rerank。
4. 不重建整套 PKU 抽取逻辑。
5. 不直接把传统 hybrid chunk 召回混入 governed 结果中。
6. 不把 `normalized_statement` 改成语义改写字段；它继续承担规范化和去重职责。

## 分层职责

### 父 CKP：目录路由层

父 CKP 不负责语义理解，也不负责证据返回。父 CKP 的职责是回答：

```text
用户问题大概率属于哪些主题目录？
```

父层查询时完全使用关键词、实体、别名和子节点聚合字段，不使用向量，不使用 LLM。

父 CKP 可参与匹配的字段：

```text
title
aliases
keywords
entities
concepts
domains
extra_meta.child_title_terms
extra_meta.child_keyword_terms
extra_meta.child_entity_terms
extra_meta.child_concept_terms
```

推荐父层 TopN：

```text
parent_top_n = 8
```

选择 8 而不是 3 的原因是父层纯关键词依赖词表质量，第一阶段需要给子层留出足够召回空间，避免父层过早截断。

### 子 CKP：语义匹配层

子 CKP 负责承接用户问题和主题语义之间的匹配。子 CKP 不应该只依赖一个 summary 向量，而应维护多个召回入口。

子 CKP 需要维护的检索字段建议放在 `extra_meta` 中：

```json
{
  "topic_level": "child",
  "retrieval_terms": [],
  "retrieval_queries": [],
  "key_facts": [],
  "summary_dirty": false,
  "summary_updated_at": ""
}
```

字段含义：

```text
retrieval_terms
  用于关键词/BM25/词面覆盖率匹配。

retrieval_queries
  LLM 离线生成的可能用户问法，用于向量召回。

key_facts
  子 CKP 下关键事实、规则、方法、约束的短句集合，用于向量召回和调试解释。

summary
  面向展示和辅助理解，不作为唯一向量入口。
```

### PKU：证据层

PKU 是最终事实与证据层。PKU 不再作为全局强插队入口，而是在命中的子 CKP 范围内进行局部混合召回。

PKU 层主要使用：

```text
statement
normalized_statement
evidence_span
keywords
entities
concepts
PKU vector score
PKUCanonicalLink confidence
PKU confidence
child CKP score
```

其中：

```text
statement
  原始知识陈述或 LLM 抽取出的知识句，适合展示和语义匹配。

normalized_statement
  statement 的空白规范化版本，用于去重、hash 和稳定匹配，不应改成语义摘要。

evidence_span
  更接近原文证据，适合事实型问题。
```

## 子 CKP 多向量设计

子 CKP 使用独立多向量 collection，而不是继续混用 `prism_ckp`。

建议新增 collection：

```text
prism_child_ckp_retrieval
```

每条向量代表一个召回入口，而不是一个 CKP 只有一个向量。

向量类型：

```text
summary
key_fact
retrieval_query
```

向量记录 metadata：

```json
{
  "id": "vector row id",
  "ckp_id": "child ckp id",
  "parent_ckp_id": "parent ckp id",
  "user_id": "default-user",
  "vector_kind": "summary | key_fact | retrieval_query",
  "source_text": "向量化的原始文本",
  "source_hash": "source_text hash"
}
```

查询时根据父 CKP 召回结果限制子 CKP 搜索范围：

```text
query
  -> parent CKP keyword recall
  -> parent_ckp_ids
  -> child CKP vector search where parent_ckp_id in parent_ckp_ids
  -> 聚合到 child_ckp_id
```

同一个 child CKP 多条向量命中时可以加分，但需要设置上限，避免一个 CKP 因为向量条目多而刷屏。

推荐子 CKP 初始评分：

```text
child_score =
  0.45 * best_vector_score
+ 0.25 * keyword_overlap_score
+ 0.15 * parent_score
+ 0.10 * vector_kind_boost
+ 0.05 * ckp_confidence
```

`vector_kind_boost` 建议：

```text
retrieval_query 命中：高
key_fact 命中：中高
summary 命中：中
```

原因是 `retrieval_query` 更接近用户真实问法，`key_fact` 更适合具体事实，`summary` 更适合宽泛语义。

## 查询流程

第一阶段完整查询流程：

```text
1. 解析 query terms
2. 父 CKP 纯关键词/实体召回 Top 8
3. 通过 canonical_relation.subtopic_of 找父 CKP 下的子 CKP
4. 在命中父 CKP 范围内做子 CKP 多向量召回
5. 子 CKP 结合 retrieval_terms 做关键词补分
6. 每个父 CKP 保留 Top 3 子 CKP，全局去重重排
7. 只从命中子 CKP 的 PKUCanonicalLink 拉局部 PKU
8. 局部 PKU 做关键词 + vector + link confidence 混合排序
9. 如果局部结果不足或置信度低，触发全局 PKU vector 兜底
10. 返回 PKU evidence、source backtracking、expanded_sources
```

推荐初始参数：

```text
parent_top_n = 8
child_top_per_parent = 3
child_global_top_n = 12
local_pku_top_n = 20
final_evidence_top_n = 10
fallback_pku_top_n = 10
```

这些参数必须写入评测 summary，便于后续调参。

## 父 CKP 关键词召回

父层分数建议由字段权重组成：

```text
title / aliases 命中：最高
entities 命中：很高
child_title_terms 命中：高
keywords / concepts 命中：中
domains 命中：低
```

推荐初始权重：

```text
title: 5.0
aliases: 4.5
entities: 4.0
child_title_terms: 3.5
child_entity_terms: 3.5
keywords: 3.0
child_keyword_terms: 3.0
concepts: 2.5
child_concept_terms: 2.5
domains: 1.0
```

父层召回只做目录路由，不返回 evidence。父 CKP 命中原因需要保留：

```json
{
  "parent_ckp_id": "...",
  "parent_title": "...",
  "parent_score": 0.0,
  "matched_terms": [],
  "match_reasons": []
}
```

## PKU 局部召回与兜底

### 局部 PKU 主通道

局部 PKU 候选来自命中子 CKP 的 `PKUCanonicalLink`。

推荐局部 PKU 初始分数：

```text
local_pku_score =
  0.35 * evidence_statement_keyword_score
+ 0.25 * pku_vector_score
+ 0.20 * child_ckp_score
+ 0.10 * link_confidence
+ 0.10 * pku_confidence
```

`evidence_statement_keyword_score` 应覆盖：

```text
statement
normalized_statement
evidence_span
keywords
entities
concepts
```

### 全局 PKU 低权重兜底

全局 PKU vector 保留，但只作为兜底，不作为主召回。

触发条件：

```text
父 CKP 召回为空
子 CKP 召回为空
局部 PKU 数量少于 min_evidence
局部 PKU 最高分低于阈值
```

推荐初始参数：

```text
min_evidence = 5
local_pku_min_score = 0.25
global_pku_fallback_weight = 0.25
```

全局兜底进入结果时必须标记路径：

```json
{
  "retrieval_path": "global_pku_fallback"
}
```

局部主通道结果标记：

```json
{
  "retrieval_path": "parent_child_local_pku"
}
```

## 索引更新机制

当新 PKU 创建或重新挂载到子 CKP 时，不应在写入请求中同步调用 LLM 生成 summary。建议使用 dirty 标记和后台任务。

推荐更新流程：

```text
PKU 新增或重新挂载
  -> 更新子 CKP 的 linked PKU
  -> 标记 child_ckp.extra_meta.summary_dirty = true
  -> 同步更新父 CKP 聚合 terms
  -> 后台任务刷新子 CKP summary / retrieval_terms / retrieval_queries / key_facts
  -> 重建 child CKP retrieval vectors
```

父 CKP 聚合字段可以同步更新，因为它只聚合结构化词表，不需要 LLM：

```text
child_title_terms
child_keyword_terms
child_entity_terms
child_concept_terms
```

子 CKP 的 LLM 生成字段异步更新：

```text
summary
retrieval_terms
retrieval_queries
key_facts
```

## 降级策略

分层召回必须可降级：

```text
父 CKP 关键词召回失败或为空
  -> 触发全局 PKU vector 兜底

子 CKP 多向量 collection 不可用
  -> 使用子 CKP retrieval_terms / title / summary 做词面排序

PKU vector 不可用
  -> 局部 PKU 只使用关键词、link confidence、pku confidence 排序

embedding provider 不可用
  -> 不影响父 CKP 关键词召回和局部 PKU 词面召回
```

## 评测计划

第一阶段必须先跑离线检索指标，不引入 LLM rerank。

需要对比的链路：

```text
traditional_hybrid
governed_ckp_pku
governed_evidence
hierarchical_ckp_pku
```

核心指标：

```text
Expanded Recall@10
Expanded MRR
Expanded Hit@10
Exact Recall@10
Exact MRR
Exact Hit@10
```

新增诊断指标：

```text
parent_ckp_hit_rate
child_ckp_hit_rate
local_pku_coverage_rate
global_fallback_trigger_rate
global_fallback_hit_rate
retrieval_path_distribution
```

评测输出目录继续放在：

```text
evaluation/runs/retrieval/<timestamp>_compare/
```

本阶段成功标准先不写死为必须超过传统 RAG，而是看结构改造是否解决噪声问题：

```text
1. hierarchical_ckp_pku 的 Expanded MRR 高于当前 governed_evidence。
2. hierarchical_ckp_pku 的 Expanded Hit@10 不低于当前 governed_evidence。
3. global_pku_fallback 命中占比可解释，不能成为主要命中来源。
4. 失败样本能定位到父层漏召、子层漏召或 PKU 局部排序问题。
```

## 测试策略

后续实现计划中应覆盖以下测试：

```text
父 CKP 只使用关键词/实体召回，不调用向量服务
父 CKP 可通过 child_* 聚合 terms 命中
子 CKP 多向量可以按 parent_ckp_id 过滤
同一 child CKP 多条向量命中会聚合分数但不会无限刷分
局部 PKU 只来自命中子 CKP 的 link
局部 PKU 不足时触发全局 PKU fallback
全局 PKU fallback 被低权重融合并标记 retrieval_path
PKU vector 失败时链路降级到词面排序
评测 summary 写入分层召回参数和 retrieval_path 分布
```

## 风险

### 父层纯关键词可能漏召

父 CKP 不走向量后，召回质量依赖词表。缓解方式是把子 CKP 标题、关键词、实体、概念持续聚合到父 CKP，而不是依赖父 CKP 自身 summary。

### 子 CKP 多向量增加索引规模

一个子 CKP 会生成多条向量。缓解方式是限制每类字段数量，例如：

```text
summary: 1 条
key_facts: 最多 8 条
retrieval_queries: 最多 8 条
```

### 子 CKP summary/retrieval_queries 生成成本增加

缓解方式是异步 dirty 更新，不阻塞 PKU 入库和用户上传。

### 全局 PKU 兜底污染结果

缓解方式是低权重、条件触发、路径标记，并在评测中单独统计贡献率。

## 第一阶段交付物

第一阶段实现完成后应交付：

1. 子 CKP retrieval 字段生成与刷新逻辑。
2. 子 CKP 多向量 collection 与 upsert/search 服务。
3. 父 CKP 聚合索引字段更新逻辑。
4. `hierarchical_ckp_pku` 查询链路。
5. 全局 PKU vector 低权重兜底。
6. 评测脚本支持新链路和新增诊断指标。
7. 单元测试与集成测试。
8. 中文评测报告。

## 结论

本阶段采用“父 CKP 目录路由、子 CKP 多向量语义匹配、PKU 局部证据召回、全局 PKU 低权重兜底”的渐进式披露结构。

该设计避免把父 CKP summary 当作过度抽象的向量入口，也避免 PKU vector 全局强插队造成噪声。它把检索链路拆成可解释的层级，使后续评测可以明确判断问题出在父层路由、子层语义匹配，还是 PKU 证据排序。
