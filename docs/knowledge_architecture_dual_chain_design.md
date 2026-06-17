# 个人知识库双链路改造设计文档

## 1. 背景

当前知识系统需要同时支持两类知识来源：

1. **传统 RAG 知识链路**

   ```text
   DocumentSource -> PersonalKnowledgeUnit -> CanonicalKnowledgePoint
   ```

   主要处理上传文档、PDF、网页、技术文档、论文、书籍等外部资料。

2. **碎片知识链路**

   ```text
   PersonalAssetItem -> PersonalKnowledgeUnit -> CanonicalKnowledgePoint
   ```

   主要处理用户日常输入的碎片记录、想法、实验记录、问题、测试结论、项目笔记等个人知识材料。

本次改造不处理 Wiki 链路：

```text
DocumentSource -> PersonalAssetItem -> PersonalKnowledgeUnit
```

Wiki 链路暂时不纳入系统设计，后续可以作为独立扩展。

---

## 2. 设计目标

本次改造目标是建立统一的知识组织架构，使传统 RAG 文档知识和碎片化个人知识最终都收敛到统一的 `L2: Canonical Knowledge Layer`。

核心目标：

1. 保留原始来源，保证所有回答都可以回溯证据。
2. 将不同来源抽取为统一的 `PersonalKnowledgeUnit`。
3. 将语义相同或相关的 PKU 归一到 `CanonicalKnowledgePoint`。
4. 支持跨来源关系发现，例如：
   - 文档支持个人观点
   - 文档定义个人碎片中提到的概念
   - 个人实验反驳文档结论
   - 多条碎片共同支持一个稳定知识点
5. Agent 检索时优先检索 L2，再回溯 PKU 和原始来源。
6. 避免把文档事实、个人观点、实验观察和 LLM 归纳混在一起。

---

## 3. 非目标

本次改造不实现：

1. Wiki 链路。
2. 完整知识图谱可视化。
3. 多用户权限系统。
4. 自动真伪判断系统。
5. 复杂版本控制 UI。
6. 人工审核后台。

但底层数据结构需要预留这些能力。

---

## 4. 总体架构

系统分为四层：

```text
L0 Source Layer
  - DocumentSource
  - Raw document chunk
  - Raw personal fragment

L1 Asset Layer
  - PersonalAssetItem
  - DocumentChunk

L1.5 Knowledge Unit Layer
  - PersonalKnowledgeUnit, 简称 PKU

L2 Canonical Knowledge Layer
  - CanonicalKnowledgePoint, 简称 CKP
  - PKU -> CKP link
  - CKP -> CKP relation
```

两条链路统一如下：

```text
传统 RAG 链路：

DocumentSource
  -> DocumentChunk
  -> PersonalKnowledgeUnit
  -> CanonicalKnowledgePoint


碎片知识链路：

PersonalAssetItem
  -> PersonalKnowledgeUnit
  -> CanonicalKnowledgePoint
```

最终 Agent 检索流程：

```text
User Query
  -> query understanding
  -> retrieve CanonicalKnowledgePoint
  -> retrieve linked PersonalKnowledgeUnit
  -> retrieve original DocumentChunk / PersonalAssetItem
  -> answer with evidence
```

---

## 5. 核心概念定义

### 5.1 DocumentSource

`DocumentSource` 表示一个上传文档或外部资料来源。

示例：

```text
PDF
Markdown 文档
网页
技术手册
API 文档
论文
书籍章节
```

它负责保存文档级 metadata。

### 5.2 DocumentChunk

`DocumentChunk` 表示从 `DocumentSource` 切分出来的可检索文本块。

它是传统 RAG 的基础检索单元。

### 5.3 PersonalAssetItem

`PersonalAssetItem` 表示用户自己的碎片化资产。

示例：

```text
一条日常记录
一个实验记录
一个问题
一个灵感
一个项目笔记
一个测试结果
一个 TODO
一个认知变化
```

它不是外部文档，而是用户个人知识材料。

### 5.4 PersonalKnowledgeUnit

`PersonalKnowledgeUnit`，简称 PKU，是从 `DocumentChunk` 或 `PersonalAssetItem` 中抽取出来的候选知识单元。

PKU 应该尽量原子化。

一个 PKU 可以是：

```text
concept              概念
definition           定义
claim                观点
method               方法
rule                 规则
observation          观察
experiment_result    实验结果
decision             决策
problem              问题
question             疑问
pattern              经验模式
constraint           约束
```

PKU 是 L2 归一化的输入。

### 5.5 CanonicalKnowledgePoint

`CanonicalKnowledgePoint`，简称 CKP，是统一知识点层的核心节点。

CKP 用于表达一个经过语义归一后的稳定知识点。

它不是原文，也不是简单摘要，而是对多个 PKU 的统一表达。

示例：

```text
CKP: 个人知识库适合采用混合检索
```

它可以由多个 PKU 支持：

```text
PKU A：用户碎片中提到纯向量检索误召回
PKU B：上传文档中定义 metadata filtering
PKU C：实验记录显示 metadata filter 改善检索结果
```

---

## 6. 数据模型设计

### 6.1 `document_sources`

用于保存上传文档或外部资料来源。

```sql
id                      string primary key
title                   string
source_type             enum('pdf', 'markdown', 'webpage', 'docx', 'text', 'other')
uri                     string nullable
file_path               string nullable
author                  string nullable
created_at_source       datetime nullable
ingested_at             datetime
metadata                jsonb
content_hash            string
status                  enum('pending', 'processed', 'failed')
```

说明：

- `content_hash` 用于文档去重。
- `metadata` 可保存页数、语言、标签等额外信息。

### 6.2 `document_chunks`

用于保存文档切片。

```sql
id                      string primary key
document_source_id      string foreign key references document_sources(id)
chunk_index             integer
text                    text
token_count             integer
page_start              integer nullable
page_end                integer nullable
section_title           string nullable
metadata                jsonb
embedding_id            string nullable
created_at              datetime
```

说明：

- `DocumentChunk` 是传统 RAG 链路的原始证据单位。
- 每个 chunk 可以生成 embedding。
- 每个 chunk 可以进一步抽取多个 PKU。

### 6.3 `personal_asset_items`

用于保存用户碎片化知识资产。

```sql
id                      string primary key
asset_type              enum(
                          'note',
                          'idea',
                          'experiment',
                          'test_result',
                          'bug',
                          'question',
                          'decision',
                          'todo',
                          'reflection',
                          'project_note',
                          'other'
                        )
title                   string nullable
text                    text
source                  string nullable
created_at_source       datetime nullable
ingested_at             datetime
metadata                jsonb
content_hash            string
status                  enum('pending', 'processed', 'failed')
embedding_id            string nullable
```

说明：

- `PersonalAssetItem` 是碎片知识链路的原始资产。
- 它必须保留用户原文。
- 可以给原始碎片本身生成 embedding，用于细节检索。

### 6.4 `personal_knowledge_units`

用于保存从文档或碎片中抽取出的候选知识单元。

```sql
id                      string primary key

source_kind             enum('document_chunk', 'personal_asset_item')
source_id               string

unit_type               enum(
                          'concept',
                          'definition',
                          'claim',
                          'method',
                          'rule',
                          'observation',
                          'experiment_result',
                          'decision',
                          'problem',
                          'question',
                          'pattern',
                          'constraint',
                          'example',
                          'other'
                        )

statement               text
normalized_statement    text

subject                 string nullable
predicate               string nullable
object                  string nullable

polarity                enum('positive', 'negative', 'neutral', 'unknown')
modality                enum('fact', 'opinion', 'hypothesis', 'recommendation', 'question', 'decision', 'observation', 'unknown')

domains                 jsonb
entities                jsonb
concepts                jsonb
keywords                jsonb

scope                   jsonb
conditions              jsonb
evidence_span           text nullable

confidence              float
llm_model               string nullable
created_at              datetime
updated_at              datetime

embedding_id            string nullable
status                  enum('active', 'merged', 'deprecated', 'rejected')
```

说明：

- `source_kind + source_id` 指向来源。
- 如果来自文档，`source_kind = document_chunk`。
- 如果来自碎片，`source_kind = personal_asset_item`。
- `statement` 是原始抽取表达。
- `normalized_statement` 是标准化后的表达。
- `modality` 用于区分事实、观点、假设、建议、问题等。

### 6.5 `canonical_knowledge_points`

用于保存 L2 统一知识点。

```sql
id                      string primary key

canonical_type          enum(
                          'concept',
                          'definition',
                          'claim',
                          'method',
                          'rule',
                          'problem',
                          'decision',
                          'pattern',
                          'experiment_result',
                          'question',
                          'constraint',
                          'other'
                        )

title                   string
canonical_statement     text
summary                 text nullable

aliases                 jsonb
domains                 jsonb
entities                jsonb
concepts                jsonb
keywords                jsonb

scope                   jsonb
conditions              jsonb

status                  enum('draft', 'stable', 'disputed', 'deprecated')
confidence              float

created_at              datetime
updated_at              datetime

embedding_id            string nullable
metadata                jsonb
```

说明：

- CKP 是 agent 默认检索的主层。
- CKP 应该有 embedding。
- CKP 不直接替代 PKU 和原文。

### 6.6 `pku_canonical_links`

用于保存 PKU 和 CKP 之间的关系。

```sql
id                      string primary key

pku_id                  string foreign key references personal_knowledge_units(id)
canonical_id            string foreign key references canonical_knowledge_points(id)

relation_type           enum(
                          'same_as',
                          'supports',
                          'contradicts',
                          'extends',
                          'example_of',
                          'defines',
                          'explains',
                          'applies_to',
                          'derived_from',
                          'background_for',
                          'variant_of',
                          'related_to'
                        )

role                    enum(
                          'origin',
                          'support',
                          'evidence',
                          'example',
                          'contradiction',
                          'definition_source',
                          'external_reference',
                          'personal_claim',
                          'personal_observation',
                          'experiment_evidence',
                          'background'
                        )

confidence              float
reason                  text nullable
created_at              datetime
updated_at              datetime
```

说明：

- 只有 `relation_type = same_as` 时，PKU 才被视为该 CKP 的语义等价表达。
- 其他关系不合并，只挂边。
- 该表是来源可追溯性的核心。

### 6.7 `canonical_relations`

用于保存 CKP 与 CKP 之间的关系。

```sql
id                      string primary key

source_canonical_id     string foreign key references canonical_knowledge_points(id)
target_canonical_id     string foreign key references canonical_knowledge_points(id)

relation_type           enum(
                          'broader_than',
                          'narrower_than',
                          'part_of',
                          'has_part',
                          'supports',
                          'contradicts',
                          'explains',
                          'causes',
                          'enables',
                          'requires',
                          'uses',
                          'applies_to',
                          'implemented_by',
                          'alternative_to',
                          'complements',
                          'derived_from',
                          'replaces',
                          'refines',
                          'deprecated_by',
                          'earlier_view_of',
                          'later_view_of',
                          'related_to'
                        )

confidence              float
reason                  text nullable
created_at              datetime
updated_at              datetime
metadata                jsonb
```

说明：

- 该表构成 L2 的知识关系图。
- 可以先实现最小关系集：
  - `supports`
  - `contradicts`
  - `uses`
  - `part_of`
  - `related_to`
  - `refines`

### 6.8 Embeddings

如果当前系统已有向量库，可以不单独建该表。但逻辑上需要支持以下对象的 embedding：

```text
DocumentChunk
PersonalAssetItem
PersonalKnowledgeUnit
CanonicalKnowledgePoint
```

推荐 embedding 策略：

```text
DocumentChunk:
  embedding(text)

PersonalAssetItem:
  embedding(text)

PersonalKnowledgeUnit:
  embedding(normalized_statement + entities + concepts)

CanonicalKnowledgePoint:
  embedding(title + canonical_statement + aliases + concepts)
```

---

## 7. 两条链路的处理流程

### 7.1 传统 RAG 链路

输入：

```text
DocumentSource
```

流程：

```text
1. ingest_document
2. split_document_into_chunks
3. embed_document_chunks
4. extract_pku_from_document_chunks
5. embed_pku
6. canonicalize_pku_to_ckp
7. create_or_update_ckp
8. create_pku_canonical_links
9. update_canonical_relations
```

伪代码：

```python
def process_document_source(document_source_id: str):
    source = load_document_source(document_source_id)

    chunks = split_document(source)
    save_document_chunks(chunks)

    for chunk in chunks:
        embed(chunk)

        pkus = extract_pku_from_document_chunk(chunk)

        for pku in pkus:
            save_pku(pku)
            embed(pku)
            canonicalize_pku(pku.id)
```

文档 PKU 的默认角色：

```text
definition_source
external_reference
background
support
```

文档 PKU 的默认 modality：

```text
fact
definition
method
rule
external_claim
```

### 7.2 碎片知识链路

输入：

```text
PersonalAssetItem
```

流程：

```text
1. ingest_personal_asset_item
2. embed_personal_asset_item
3. extract_pku_from_personal_asset_item
4. embed_pku
5. canonicalize_pku_to_ckp
6. create_or_update_ckp
7. create_pku_canonical_links
8. update_canonical_relations
```

伪代码：

```python
def process_personal_asset_item(asset_id: str):
    asset = load_personal_asset_item(asset_id)

    embed(asset)

    pkus = extract_pku_from_personal_asset_item(asset)

    for pku in pkus:
        save_pku(pku)
        embed(pku)
        canonicalize_pku(pku.id)
```

个人碎片 PKU 的默认角色：

```text
personal_claim
personal_observation
experiment_evidence
decision_record
question_source
```

个人碎片 PKU 的默认 modality：

```text
opinion
hypothesis
observation
decision
question
experiment_result
```

---

## 8. PKU 抽取规则

### 8.1 PKU 抽取原则

每个 PKU 应该尽量满足：

```text
1. 原子性：只表达一个概念、观点、方法、结论或问题。
2. 可判断性：能够判断其是否支持、冲突、定义或扩展其他知识。
3. 可回源：必须能追溯到原始 source_id。
4. 可归一：必须生成 normalized_statement。
5. 带类型：必须有 unit_type。
6. 带语气：必须有 modality。
7. 带置信度：必须有 confidence。
```

### 8.2 文档 PKU 抽取 Prompt

```text
你是知识抽取器。请从下面的文档片段中抽取 PersonalKnowledgeUnit。

要求：
1. 每个知识单元只表达一个独立知识点。
2. 优先抽取定义、方法、规则、事实、约束、外部观点。
3. 不要加入文档没有表达的内容。
4. 如果只是背景信息，可以标记为 background。
5. 输出 JSON 数组。
6. 每个对象必须包含：
   - unit_type
   - statement
   - normalized_statement
   - subject
   - predicate
   - object
   - polarity
   - modality
   - domains
   - entities
   - concepts
   - keywords
   - scope
   - conditions
   - evidence_span
   - confidence

文档片段：
{{chunk_text}}
```

### 8.3 碎片 PKU 抽取 Prompt

```text
你是个人知识抽取器。请从下面的用户碎片记录中抽取 PersonalKnowledgeUnit。

要求：
1. 保留用户的个人观点、观察、问题、实验结论、决策和 TODO。
2. 不要把个人观点改写成客观事实。
3. 如果内容是猜测，modality 使用 hypothesis。
4. 如果内容是实验结果，unit_type 使用 experiment_result 或 observation。
5. 如果内容是问题，unit_type 使用 question。
6. 每个知识单元只表达一个独立知识点。
7. 输出 JSON 数组。
8. 每个对象必须包含：
   - unit_type
   - statement
   - normalized_statement
   - subject
   - predicate
   - object
   - polarity
   - modality
   - domains
   - entities
   - concepts
   - keywords
   - scope
   - conditions
   - evidence_span
   - confidence

用户碎片：
{{asset_text}}
```

---

## 9. PKU 到 CKP 的归一流程

### 9.1 总流程

```text
1. 输入新 PKU
2. 标准化 PKU
3. 检索候选 CKP
4. LLM 判断 PKU 与候选 CKP 的关系
5. 根据规则执行：
   - attach to existing CKP
   - create new CKP
   - create relation only
   - mark conflict
   - create variant
6. 更新 CKP embedding
7. 更新 CKP relation graph
```

### 9.2 候选 CKP 召回

对新 PKU 使用多路召回：

```text
1. embedding search over CKP
2. keyword search over CKP title / aliases / statement
3. entity match
4. concept match
5. relation graph neighbor expansion
```

候选数量建议：

```text
top_k_embedding = 10
top_k_keyword = 10
top_k_entity = 10
final_candidates = 20
```

---

## 10. CKP 合并与关联规则

### 10.1 可以合并到同一个 CKP 的条件

只有同时满足以下条件，才允许 `relation_type = same_as`：

```text
1. unit_type 和 canonical_type 兼容。
2. normalized_statement 表达同一个核心含义。
3. subject 可以归一为同一个对象。
4. polarity 一致。
5. modality 不冲突。
6. scope 基本一致。
7. conditions 不冲突。
8. 不是一个是观点、另一个是证据。
9. 不是一个是概念、另一个是方法。
10. 置信度高于阈值。
```

推荐阈值：

```text
same_as_threshold = 0.85
link_threshold = 0.65
```

### 10.2 不允许合并的情况

以下情况不允许合并，只允许建立关系：

```text
1. 同主题但不同侧面。
2. 一个是概念，一个是方法。
3. 一个是观点，一个是证据。
4. 一个是问题，一个是回答。
5. 一个是实验结果，一个是一般结论。
6. 适用范围不同。
7. 条件不同。
8. 结论方向相反。
9. 来源身份会被混淆。
```

### 10.3 关系判断 Prompt

```text
你是知识归一化判断器。请判断一个新的 PersonalKnowledgeUnit 与候选 CanonicalKnowledgePoint 的关系。

你必须严格遵守：
1. 只有语义完全等价时，才使用 same_as。
2. 同主题但不同侧面，不要 same_as，使用 related_to / part_of / supports / extends。
3. 个人观点和文档证据不要直接合并，除非它们表达的是同一个定义或事实。
4. 冲突内容必须使用 contradicts。
5. 如果新 PKU 是例子，使用 example_of。
6. 如果新 PKU 是定义，使用 defines。
7. 如果新 PKU 是证据，使用 supports 或 contradicts。
8. 如果没有合适 CKP，应建议 create_new。

输入：
New PKU:
{{pku_json}}

Candidate CKP:
{{ckp_json}}

输出 JSON：
{
  "decision": "attach_existing | create_new | link_only | mark_conflict | create_variant",
  "relation_type": "same_as | supports | contradicts | extends | example_of | defines | explains | applies_to | derived_from | background_for | variant_of | related_to",
  "role": "origin | support | evidence | example | contradiction | definition_source | external_reference | personal_claim | personal_observation | experiment_evidence | background",
  "should_merge": true | false,
  "confidence": 0.0,
  "reason": "",
  "scope_match": true | false,
  "polarity_match": true | false,
  "modality_conflict": true | false
}
```

---

## 11. CKP 创建规则

当没有合适的候选 CKP 时，新建 CKP。

创建 CKP 的输入：

```text
PKU.normalized_statement
PKU.unit_type
PKU.entities
PKU.concepts
PKU.scope
PKU.conditions
PKU.keywords
```

CKP 字段生成规则：

```text
canonical_type = map_pku_type_to_canonical_type(PKU.unit_type)
title = concise title generated from normalized_statement
canonical_statement = normalized_statement
summary = optional short explanation
aliases = entities + concepts + generated aliases
domains = PKU.domains
entities = PKU.entities
concepts = PKU.concepts
keywords = PKU.keywords
scope = PKU.scope
conditions = PKU.conditions
status = draft
confidence = PKU.confidence
```

新建后创建链接：

```text
PKU -> CKP
relation_type = same_as 或 derived_from
role = origin
```

---

## 12. CKP 更新规则

当新 PKU 挂到已有 CKP 后，需要更新 CKP。

### 12.1 `same_as`

如果新 PKU 与 CKP 是 `same_as`：

```text
1. 将 PKU 挂到 CKP。
2. 合并 aliases。
3. 合并 entities。
4. 合并 concepts。
5. 合并 keywords。
6. 如新 PKU 带来更清晰表达，可以更新 canonical_statement。
7. 更新 updated_at。
8. 重新计算 CKP embedding。
```

### 12.2 `supports`

如果新 PKU 支持 CKP：

```text
1. 创建 pku_canonical_link。
2. relation_type = supports。
3. role = evidence / support / external_reference / experiment_evidence。
4. 不改写 canonical_statement，除非该证据显著增强或修正 scope。
```

### 12.3 `contradicts`

如果新 PKU 与 CKP 冲突：

```text
1. 创建 pku_canonical_link。
2. relation_type = contradicts。
3. role = contradiction。
4. 将 CKP.status 设置为 disputed，除非冲突置信度很低。
5. 不删除原 CKP。
```

### 12.4 `extends` / `variant_of`

如果新 PKU 扩展或变体化已有 CKP：

```text
1. 如果扩展内容足够独立，创建新的 CKP。
2. 在两个 CKP 之间创建 canonical_relations。
3. relation_type = refines / extends / related_to / applies_to。
```

---

## 13. Agent 检索设计

### 13.1 检索入口

建议提供以下检索函数：

```python
search_canonical_knowledge(query, filters=None, top_k=10)

search_personal_knowledge_units(query, filters=None, top_k=20)

search_document_chunks(query, filters=None, top_k=20)

search_personal_assets(query, filters=None, top_k=20)

get_sources_for_canonical(canonical_id)

get_related_canonical_points(canonical_id, relation_types=None, depth=1)
```

### 13.2 默认检索策略

普通问题默认走：

```text
1. search_canonical_knowledge
2. get_sources_for_canonical
3. rerank PKU and sources
4. answer
```

### 13.3 细节问题

如果用户问的是：

```text
原话是什么？
哪篇文档提到？
我当时怎么写的？
某个参数是多少？
某次测试结果是什么？
```

则优先检索：

```text
DocumentChunk
PersonalAssetItem
PersonalKnowledgeUnit
```

### 13.4 复杂问题

如果用户问的是：

```text
我以前的观点有没有变化？
这个结论有没有文档支持？
有没有相互矛盾的记录？
这个想法和上传文档有什么关系？
```

则并行检索：

```text
1. CKP
2. PKU
3. DocumentChunk
4. PersonalAssetItem
5. CKP relations
```

---

## 14. 回答生成要求

Agent 回答时必须区分来源身份。

推荐回答结构：

```text
根据你的个人碎片记录……
根据上传文档……
两者共同指向……
存在的冲突是……
我的推断是……
```

禁止：

```text
1. 把用户观点说成文档事实。
2. 把文档事实说成用户观点。
3. 把 LLM 归纳说成原始证据。
4. 只引用 CKP，不回溯 PKU 或原始来源。
```

---

## 15. 最小可行实现范围

第一阶段只实现以下能力：

### 数据表

```text
document_sources
document_chunks
personal_asset_items
personal_knowledge_units
canonical_knowledge_points
pku_canonical_links
canonical_relations
```

### 处理链路

```text
DocumentSource -> DocumentChunk -> PKU -> CKP
PersonalAssetItem -> PKU -> CKP
```

### 检索

```text
CKP vector search
PKU vector search
DocumentChunk vector search
PersonalAssetItem vector search
metadata filter
source backtracking
```

### 关系

第一阶段只支持：

```text
same_as
supports
contradicts
extends
example_of
defines
related_to
```

CKP 到 CKP 关系第一阶段只支持：

```text
supports
contradicts
uses
part_of
related_to
refines
```

---

## 16. 模块拆分建议

建议代码模块如下：

```text
src/
  knowledge/
    models/
      document_source.py
      document_chunk.py
      personal_asset_item.py
      personal_knowledge_unit.py
      canonical_knowledge_point.py
      relations.py

    ingestion/
      document_ingestor.py
      personal_asset_ingestor.py

    chunking/
      document_chunker.py

    extraction/
      document_pku_extractor.py
      personal_pku_extractor.py
      prompts.py

    canonicalization/
      candidate_retriever.py
      relation_judge.py
      canonicalizer.py
      merge_rules.py

    retrieval/
      canonical_search.py
      pku_search.py
      source_search.py
      hybrid_search.py

    graph/
      canonical_relation_builder.py
      source_backtracker.py

    services/
      document_pipeline.py
      personal_asset_pipeline.py
      agent_retrieval_service.py
```

---

## 17. 核心服务接口

### 17.1 文档入库

```python
def ingest_document(
    title: str,
    content: str,
    source_type: str,
    metadata: dict | None = None,
) -> str:
    """
    Create DocumentSource, split into DocumentChunk,
    extract PKUs, canonicalize PKUs into CKPs.
    Return document_source_id.
    """
```

### 17.2 碎片入库

```python
def ingest_personal_asset(
    text: str,
    asset_type: str = "note",
    title: str | None = None,
    metadata: dict | None = None,
) -> str:
    """
    Create PersonalAssetItem,
    extract PKUs, canonicalize PKUs into CKPs.
    Return personal_asset_item_id.
    """
```

### 17.3 PKU 归一

```python
def canonicalize_pku(pku_id: str) -> list[str]:
    """
    Retrieve candidate CKPs.
    Judge relation between PKU and candidates.
    Attach to existing CKP or create new CKP.
    Return affected canonical IDs.
    """
```

### 17.4 Agent 检索

```python
def retrieve_for_agent(
    query: str,
    scope: str = "auto",
    filters: dict | None = None,
    top_k: int = 10,
) -> dict:
    """
    Main retrieval entry for agent.
    Default behavior:
    - search CKP
    - retrieve linked PKUs
    - backtrack source chunks/assets
    - return evidence bundle
    """
```

返回结构：

```json
{
  "query": "",
  "canonical_results": [],
  "pku_results": [],
  "source_results": [],
  "relations": [],
  "evidence_bundle": []
}
```

---

## 18. Evidence Bundle 结构

Agent 最终回答不应该只拿 CKP，而应该拿 evidence bundle。

```json
{
  "canonical_id": "",
  "canonical_title": "",
  "canonical_statement": "",
  "linked_pkus": [
    {
      "pku_id": "",
      "statement": "",
      "relation_type": "",
      "role": "",
      "source_kind": "",
      "source_id": "",
      "evidence_span": "",
      "confidence": 0.0
    }
  ],
  "raw_sources": [
    {
      "source_kind": "document_chunk | personal_asset_item",
      "source_id": "",
      "text": "",
      "title": "",
      "metadata": {}
    }
  ],
  "related_canonical_points": []
}
```

---

## 19. 迁移策略

如果当前系统已有传统 RAG 文档库：

```text
1. 保留原 document/chunk 表。
2. 新增 PKU 抽取任务。
3. 对已有 chunk 批量抽取 PKU。
4. 将 PKU 归一到 CKP。
5. 旧 RAG 检索保留，但 agent 默认改为 CKP-first。
```

如果当前系统已有碎片记录：

```text
1. 将原始碎片导入 personal_asset_items。
2. 给每条碎片生成 content_hash。
3. 对碎片批量抽取 PKU。
4. 将 PKU 归一到 CKP。
5. 保留原始碎片作为证据层。
```

---

## 20. 幂等与去重

### 20.1 Source 去重

使用：

```text
content_hash = sha256(normalized_text)
```

如果 content_hash 已存在，则不重复入库。

### 20.2 PKU 去重

PKU 去重依据：

```text
source_kind
source_id
normalized_statement hash
unit_type
```

### 20.3 CKP 去重

CKP 不直接 hash 去重，而通过 canonicalization 判断。

判断依据：

```text
embedding similarity
keyword overlap
entity overlap
concept overlap
LLM same_as 判断
```

---

## 21. 状态机

### 21.1 Source 状态

```text
pending -> processed
pending -> failed
processed -> reprocessing -> processed
```

### 21.2 PKU 状态

```text
active
merged
deprecated
rejected
```

### 21.3 CKP 状态

```text
draft
stable
disputed
deprecated
```

状态更新规则：

```text
1. 新建 CKP 默认为 draft。
2. same_as PKU 数量 >= 3，或有高可信来源支持，可升级为 stable。
3. 出现高置信 contradicts，标记为 disputed。
4. 被新 CKP 替代，标记为 deprecated。
```

---

## 22. 测试用例

### 22.1 文档支持个人观点

输入：

```text
PersonalAssetItem:
我觉得个人知识库不能只靠向量检索，应该结合 metadata filter。

DocumentChunk:
Metadata filtering allows retrieval systems to restrict results by source, date, author, or category.
```

期望：

```text
生成 CKP:
个人知识库适合采用 metadata filter 辅助检索

Personal PKU -> CKP:
relation_type = same_as 或 supports
role = personal_claim

Document PKU -> CKP:
relation_type = defines 或 supports
role = definition_source / external_reference
```

### 22.2 个人实验支持 CKP

输入：

```text
PersonalAssetItem:
今天测试发现，只用 embedding 搜索时召回了很多 AI 相关但不是当前项目的记录，加上 project metadata filter 后结果明显更准。
```

期望：

```text
生成或更新 CKP:
多项目个人知识库中 metadata filter 可以提升检索准确性

PKU relation:
supports

role:
experiment_evidence
```

### 22.3 冲突记录

输入：

```text
PersonalAssetItem A:
一开始我觉得向量检索已经足够。

PersonalAssetItem B:
后来发现纯向量检索在多领域记录里误召回很多，必须使用混合检索。
```

期望：

```text
两个 PKU 不合并。
创建 CKP 或 CKP relation:
A contradicts B
或
A earlier_view_of B
B refines A
```

### 22.4 同主题不同侧面

输入：

```text
PKU A:
metadata filter 用于缩小检索范围。

PKU B:
reranker 用于改善候选结果排序。
```

期望：

```text
不合并。
两个 CKP 都 part_of RAG 检索优化。
```

---

## 23. Codex 改造任务清单

### Task 1：新增数据模型

实现：

```text
DocumentSource
DocumentChunk
PersonalAssetItem
PersonalKnowledgeUnit
CanonicalKnowledgePoint
PKUCanonicalLink
CanonicalRelation
```

### Task 2：实现文档入库链路

实现：

```text
ingest_document
split_document
embed_document_chunk
extract_pku_from_document_chunk
canonicalize_pku
```

### Task 3：实现碎片入库链路

实现：

```text
ingest_personal_asset
embed_personal_asset
extract_pku_from_personal_asset
canonicalize_pku
```

### Task 4：实现 PKU 抽取器

实现两个 extractor：

```text
DocumentPKUExtractor
PersonalAssetPKUExtractor
```

两者共用 PKU schema，但 prompt 不同。

### Task 5：实现 CKP 候选召回

实现：

```text
retrieve_candidate_ckps(pku)
```

召回策略：

```text
embedding search
keyword search
entity match
concept match
```

### Task 6：实现关系判断器

实现：

```text
judge_pku_ckp_relation(pku, candidate_ckp)
```

输出严格 JSON。

### Task 7：实现 canonicalizer

实现：

```text
canonicalize_pku(pku_id)
```

逻辑：

```text
1. 召回候选 CKP
2. 逐个判断关系
3. 根据最高置信结果 attach / link / conflict / create_new
4. 写 pku_canonical_links
5. 必要时写 canonical_relations
6. 更新 CKP embedding
```

### Task 8：实现 Agent 检索服务

实现：

```text
retrieve_for_agent(query, scope='auto')
```

默认：

```text
CKP first
PKU second
source backtracking
relation expansion
```

### Task 9：实现 evidence bundle

Agent 检索返回必须包含：

```text
canonical result
linked PKUs
raw sources
source roles
relation types
confidence
```

### Task 10：新增测试

覆盖：

```text
文档入库
碎片入库
PKU 抽取
CKP 创建
PKU same_as CKP
PKU supports CKP
PKU contradicts CKP
source backtracking
agent retrieval
```

---

## 24. 最终架构原则

本系统必须遵守以下原则：

```text
1. 原文不丢。
2. 来源不混。
3. PKU 是统一输入。
4. CKP 是统一知识点。
5. 只有 same_as 才合并。
6. supports / contradicts / defines / extends 只挂边，不合并。
7. Agent 默认检索 CKP，但回答必须回源。
8. 文档事实、个人观点、实验观察、LLM 归纳必须区分。
9. CKP 是语义归一层，不是原文替代层。
10. L2 统一的是知识点，不是来源库。
```

---

## 25. 推荐第一版交付标准

第一版完成后，系统应支持：

```text
1. 上传文档后自动生成 DocumentSource、DocumentChunk、PKU、CKP。
2. 输入碎片后自动生成 PersonalAssetItem、PKU、CKP。
3. 相同意义的 PKU 可以挂到同一 CKP。
4. 文档 PKU 可以支持或定义个人碎片产生的 CKP。
5. 冲突 PKU 不会被合并。
6. Agent 可以先检索 CKP，再回溯来源。
7. Agent 返回结果能区分：
   - 个人记录
   - 上传文档
   - PKU
   - CKP
   - 关系类型
```

---

## 附录：核心对象关系图

```text
DocumentSource
   |
   v
DocumentChunk
   |
   v
PersonalKnowledgeUnit
   |
   v
PKUCanonicalLink
   |
   v
CanonicalKnowledgePoint
   |
   v
CanonicalRelation
   |
   v
CanonicalKnowledgePoint


PersonalAssetItem
   |
   v
PersonalKnowledgeUnit
   |
   v
PKUCanonicalLink
   |
   v
CanonicalKnowledgePoint
```

最终检索路径：

```text
User Query
   |
   v
CanonicalKnowledgePoint Search
   |
   v
PKUCanonicalLink
   |
   v
PersonalKnowledgeUnit
   |
   v
DocumentChunk / PersonalAssetItem
   |
   v
Grounded Answer
```
