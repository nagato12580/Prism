# Prism 双链路知识治理实施确认

> Source architecture: `docs/knowledge_architecture_dual_chain_design.md`
> Scope: 传统 RAG 链路与碎片知识治理链路的高层结构化落地。

## 1. 当前实现状态

当前代码已经具备三块基础能力：

1. 文档知识库
   - `KnowledgeFile`：上传资源元数据。
   - `KnowledgeItem`：文档解析后的知识条目。
   - `KnowledgeChunk`：Engine 向量化后的 RAG chunk。

2. 碎片资产层
   - `PersonalAssetItem`：用户粘贴、链接、评论、截图文本等碎片，经 AI 解析后，用户确认前后都保存在同一张表。
   - `status=pending_review` 表示待确认。
   - `status=confirmed` 表示进入个人资产层。

3. Agent 工具
   - `knowledge_search`：搜索传统 RAG chunk。
   - `asset_search` / `asset_overview` / `asset_related`：搜索已确认的 `PersonalAssetItem`。

当前缺口是：文档链路和碎片链路还没有统一到 `PersonalKnowledgeUnit` 与 `CanonicalKnowledgePoint`，因此跨来源治理、证据回溯、冲突发现、图谱治理都还没有稳定落点。

## 2. 目标结构

本轮改造采用双链路，不纳入 Wiki 链路。

```text
传统 RAG：
KnowledgeFile / KnowledgeItem
  -> KnowledgeChunk
  -> PersonalKnowledgeUnit
  -> CanonicalKnowledgePoint

碎片治理：
PersonalAssetItem
  -> PersonalKnowledgeUnit
  -> CanonicalKnowledgePoint
```

为了降低风险，第一阶段不立即重命名或替换旧表：

```text
KnowledgeFile   先作为 DocumentSource 的兼容实现
KnowledgeChunk  先作为 DocumentChunk 的兼容实现
```

后续如果需要，可以再新增正式 `document_sources` / `document_chunks`，或者把旧表迁移过去。

## 3. 关键边界

### 3.1 PersonalAssetItem

`PersonalAssetItem` 是碎片链路的原始资产层，不是最终稳定知识点。

它保存：

- 原始文本
- 来源信息
- 原始标签
- 关键词索引
- AI 解析字段
- 用户编辑后的字段
- 审核状态

确认后仍然只是“可信个人资产”，不会直接变成传统知识库文档。

### 3.2 PersonalKnowledgeUnit, PKU

PKU 是统一的候选知识单元。

它可以来自：

- `source_kind=document_chunk`
- `source_kind=personal_asset_item`

PKU 必须保留来源身份，不能把文档事实和个人观点混在一起。

示例：

```text
文档 PKU：
Metadata filtering allows retrieval systems to restrict results by source.

碎片 PKU：
我认为个人知识库不能只靠向量检索，应该结合 metadata filter。
```

这两条可以关联同一个 CKP，但不应该被粗暴合并成同一种证据。

### 3.3 CanonicalKnowledgePoint, CKP

CKP 是统一知识点层，也是未来知识图谱的主要节点。

CKP 不替代原文，不替代 PKU，只负责表达归一后的稳定知识主题。

示例：

```text
CKP：
个人知识库适合采用 metadata filter 辅助检索。
```

## 4. 第一阶段落地策略

第一阶段目标是打通闭环，而不是追求完美抽取。

### 4.1 新增治理模型

新增：

- `PersonalKnowledgeUnit`
- `CanonicalKnowledgePoint`
- `PKUCanonicalLink`
- `CanonicalRelation`

暂不新增正式 `DocumentSource` / `DocumentChunk`，先复用现有文档表。

原因：

- 现有上传、解析、向量化链路依赖 `KnowledgeItem` / `KnowledgeChunk`。
- 直接替换会影响面过大。
- PKU/CKP 是更上层的治理能力，可以先无侵入接入。

### 4.2 碎片确认后触发治理

当用户确认 `PersonalAssetItem` 后：

```text
PersonalAssetItem(status=confirmed)
  -> extract PKU
  -> canonicalize PKU
  -> create or link CKP
```

第一版 PKU 抽取采用规则兜底：

- 优先使用 AI 解析出的 `extracts`
- 没有 extracts 时使用 `summary/body/raw_text`
- 生成 1 到 3 条 PKU

后续再替换成 LLM 严格 JSON 抽取。

### 4.3 文档向量化后触发治理

当 `KnowledgeItem` 被 Engine ingest 生成 `KnowledgeChunk` 后：

```text
KnowledgeChunk
  -> extract PKU
  -> canonicalize PKU
  -> create or link CKP
```

第一版可以每个 parent chunk 或 child chunk 生成 1 条 PKU，先保证文档证据能进入治理层。

### 4.4 CKP 归一策略

第一版先用保守规则：

1. 根据 normalized title / statement 做关键词召回。
2. 如果高度相似，建立 `same_as`。
3. 如果只是同主题，建立 `related_to` 或 `supports`。
4. 无候选时创建新 CKP。

重要原则：

```text
只有 same_as 才代表语义归并。
supports / defines / contradicts / related_to 只挂边，不合并。
```

## 5. Agent 检索演进

当前：

```text
knowledge_search 搜文档 chunk
asset_search 搜已确认碎片资产
```

目标：

```text
personal_knowledge_search / governance_search
  -> search CKP
  -> retrieve linked PKU
  -> backtrack KnowledgeChunk / PersonalAssetItem
  -> return evidence bundle
```

第一阶段不删除旧工具。

建议工具边界：

- `knowledge_search`：传统文档 chunk 兜底搜索。
- `asset_search`：个人原始资产细节搜索，适合“我之前保存的评论/记录原话是什么”。
- `governed_knowledge_search`：统一治理层搜索，适合“我的知识库里关于 X 的稳定结论、证据和关联是什么”。

这样比把所有东西塞进一个 `asset_search` 更清楚，也方便后续图谱接入。

## 6. 图谱接入方式

后续知识图谱应该主要建在 CKP 层。

```text
CanonicalKnowledgePoint --canonical_relations--> CanonicalKnowledgePoint
```

PKU 与原始来源作为证据层：

```text
CKP
  <- PKUCanonicalLink
  <- PersonalKnowledgeUnit
  <- KnowledgeChunk / PersonalAssetItem
```

好处：

- 图谱节点更稳定。
- 原始碎片不会污染图谱。
- 文档事实、个人观点、实验记录可以作为不同 role 的证据挂到同一个知识点。
- 冲突和观点变化可以通过关系表达，而不是覆盖旧知识。

## 7. 推荐实施顺序

### M1：治理数据层

- 新增 PKU / CKP / link / relation 模型。
- 加最小 schema 与测试。
- 不接入业务流程。

### M2：碎片链路接入

- `confirm PersonalAssetItem` 后生成 PKU。
- PKU 归一到 CKP。
- 增加 source backtracking 测试。

### M3：文档链路接入

- `ingest KnowledgeItem` 后基于 `KnowledgeChunk` 生成 PKU。
- PKU 归一到 CKP。
- 保留旧 RAG 搜索。

### M4：统一检索工具

- 新增 `governed_knowledge_search`。
- 返回 CKP + PKU + raw source evidence bundle。
- Agent prompt 改成优先自主判断是否调用治理层工具。

### M5：关系治理与图谱预留

- 支持 CKP relation。
- 支持 `supports` / `contradicts` / `related_to` / `refines`。
- 后续再做图谱可视化或图谱记忆。

## 8. 需要确认的实现选择

建议默认选择：

1. 第一阶段复用 `KnowledgeFile/KnowledgeItem/KnowledgeChunk`，不急着新增 `DocumentSource/DocumentChunk`。
2. 确认 `PersonalAssetItem` 后自动生成 PKU/CKP。
3. 文档 `ingest` 成功后自动生成 PKU/CKP。
4. 新增独立 `governed_knowledge_search`，不把 `asset_search` 扩成万能工具。
5. 图谱先落在 CKP relation，不直接对原始碎片建图。

如果以上选择成立，下一步从 M1 开始实现。
