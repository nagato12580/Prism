# Graphify 与 Prism 当前图谱链路对照

- 日期：2026-07-06
- 目的：把 `Graphify-Labs/graphify` 的核心阶段，与 Prism 当前“文档/PersonalAssetUnit -> 实体关系抽取 -> 落库 -> 投图 -> 检索/展示”链路做一张可核对的映射表。
- 范围：只比较当前已经存在的实现，不讨论未来理想态。

## 一句话结论

Prism 现在不是在“直接使用 graphify 作为主系统”，而是在两处明显借用了它的思路：

1. Stage A 的实体/关系抽取契约，已经非常 graphify 化。
2. Stage B 的社区、枢纽、surprising connection 分析，已经直接复用了 graphify 的分析函数。

但 Prism 的整体产品形态和 graphify 仍然不同：

1. graphify 更像“本地构图与探索工具”。
2. Prism 更像“在线知识系统”，强调入库、回源证据、统一检索、Agent 回答。

## 总体映射

| graphify 阶段 | graphify 侧含义 | Prism 当前对应实现 | 相同点 | 关键差异 |
|---|---|---|---|---|
| detect | 识别输入材料类型，如 code / docs / pdf / image / video | 文档与资产入口分别由 ingestion 和 API 链路触发 | 都有“先识别来源，再进入统一图处理”这个思路 | Prism 没有一个名为 `detect` 的统一前置层，而是分散在文档上传、chunking、资产确认这两条链路里 |
| extract | 抽实体、关系、证据，形成 `{nodes, edges}` 或同构中间表示 | `engine/app/extraction/stage_a.py` + `engine/app/extraction/prompts.py` | 都把“实体 + 关系抽取”视为建图前的核心步骤 | graphify 更强调确定性抽取和文件结构信息；Prism 当前主链路是 LLM 抽取 |
| build_graph | 用抽取结果构成图 | `backend/app/services/entity_extraction.py` 落库；`backend/app/services/graph_projection.py` 投影到 Neo4j | 都有“中间抽取结果 -> 图节点/边”的转换层 | Prism 先写 MySQL 审计表，再投影 Neo4j；graphify 更偏直接产物图 |
| cluster | 图社区发现 | `engine/app/graph/analyzer.py::run_analysis` | Prism 已直接调用 graphify 的 `cluster(...)` | Prism 的社区结果会回写到 Neo4j 节点属性，并影响后续检索与页面 |
| analyze | god nodes / surprising / diagnostics / path-like insights | `engine/app/graph/analyzer.py`、`engine/app/graph/insights.py` | Prism 已直接复用 graphify 分析函数和概念 | Prism 把这些结果继续用于检索增强、问题建议、治理，而不只是做浏览报告 |
| report / export | 产出 graph.json / graph.html / explain / path | `backend/app/api/unified_graph.py` + `/graph` 页面 + `engine/app/retrieval/unified.py` | 都提供图的可消费视图 | Prism 的主要出口不是静态图报告，而是 Agent 检索、证据返回和统一图页面 |

## 分阶段细表

### 1. detect

| 项目 | graphify | Prism 当前 |
|---|---|---|
| 输入识别 | 明确区分 code、docs、pdf、image、video 等来源 | 主要分成两条入口：文档 ingest、PersonalAssetUnit confirm |
| 入口形态 | 倾向本地扫描或对文件运行构图流程 | 文档链路由 ingestion pipeline 驱动，资产链路由 API confirm 驱动 |
| 是否统一 | 偏统一入口 | 暂时不是统一入口 |

Prism 对应代码：

- 文档侧入口：[engine/app/ingestion/pipeline.py](H:/Agent/Project/Prism/prism/engine/app/ingestion/pipeline.py:205)
- 资产侧入口：[backend/app/api/assets.py](H:/Agent/Project/Prism/prism/backend/app/api/assets.py:437)

结论：

- 思想上相似，都是“先把原始材料纳入图处理流程”。
- 结构上不同，Prism 现在还是双入口，不是一个统一 detect 层。

### 2. extract

| 项目 | graphify | Prism 当前 |
|---|---|---|
| 抽取对象 | 实体、关系、证据、文件级语义结构 | 实体、关系、evidence span |
| 抽取方式 | 倾向确定性解析与结构化抽取，尤其代码图 | 以 LLM Stage A 为主 |
| 抽取输出 | graphify schema 风格的节点/边 | `EntityCandidate` 列表，`kind=entity/relation` |
| 置信度 | 强调分级和分析友好 | 已采用 `EXTRACTED / INFERRED / AMBIGUOUS` 三档 |

Prism 对应代码：

- 抽取入口：[engine/app/extraction/stage_a.py](H:/Agent/Project/Prism/prism/engine/app/extraction/stage_a.py:17)
- Prompt 与 JSON 解析：[engine/app/extraction/prompts.py](H:/Agent/Project/Prism/prism/engine/app/extraction/prompts.py:10)
- 候选结构定义：[backend/app/services/entity_extraction.py](H:/Agent/Project/Prism/prism/backend/app/services/entity_extraction.py:14)

这里最像 graphify 的点：

1. 一次抽取同时产生 `entities` 和 `relations`。
2. 使用离散置信度分层。
3. 抽取结果先进入一个统一中间结构，再继续后处理。

这里最不像 graphify 的点：

1. Prism 当前没有把 code AST、calls、imports、inherits 这类确定性结构边作为主来源。
2. Prism 更像“从知识文本里抽语义实体图”，不是“从工程文件里抽结构图”。

### 3. build_graph

| 项目 | graphify | Prism 当前 |
|---|---|---|
| 图构建位置 | 抽取后直接形成图表示 | 先落 MySQL，再投影到 Neo4j |
| 节点 | 文件、实体、结构元素等 | `KnowledgeEntity`、`Source(document_chunk/personal_asset_unit)`、Alias |
| 边 | relation、structural relation、semantic relation | `MENTIONED_IN`、实体间关系、Alias 关系 |
| 回源 | 保留 source_location/source_file | 通过 `entity_mention.source_kind/source_id/evidence_span` 回源 |

Prism 对应代码：

- 落库主入口：[backend/app/services/entity_extraction.py](H:/Agent/Project/Prism/prism/backend/app/services/entity_extraction.py:106)
- 投影主入口：[backend/app/services/graph_projection.py](H:/Agent/Project/Prism/prism/backend/app/services/graph_projection.py:151)
- 资产投影：[backend/app/services/graph_projection.py](H:/Agent/Project/Prism/prism/backend/app/services/graph_projection.py:275)
- 文档投影：[backend/app/services/graph_projection.py](H:/Agent/Project/Prism/prism/backend/app/services/graph_projection.py:436)

Prism build_graph 的核心特征：

1. `KnowledgeEntity` 是事实源之一。
2. `EntityMention` 保存“这个实体在哪个 chunk / asset unit 里被提到”。
3. `EntityRelation` 保存“实体与实体的关系”。
4. Neo4j 不是唯一真相源，而是派生图。

这和 graphify 最大的区别在于：

- graphify 更偏“图就是主要产物”。
- Prism 更偏“图是从知识数据库投影出来的可检索层”。

### 4. cluster

| 项目 | graphify | Prism 当前 |
|---|---|---|
| 社区发现 | graphify 内置能力 | 已直接调用 graphify |
| 输出 | community grouping | `community_id` 回写到 Neo4j Entity |
| 用途 | 浏览、理解图结构 | 浏览、检索增强、治理增强 |

Prism 对应代码：

- 分析入口：[engine/app/graph/analyzer.py](H:/Agent/Project/Prism/prism/engine/app/graph/analyzer.py:122)
- 社区回写：[backend/app/services/graph_client.py](H:/Agent/Project/Prism/prism/backend/app/services/graph_client.py:198)

关键实现细节：

1. `run_analysis(...)` 里直接 `from graphify.cluster import cluster, score_all`
2. Prism 做了额外一层 `_remap_communities(...)`，用来稳定社区 id，避免每次重算都漂移

这点是 Prism 的产品化补充，不是 graphify 核心卖点本身。

### 5. analyze

| 项目 | graphify | Prism 当前 |
|---|---|---|
| god nodes | 有 | 有，且已接入检索 |
| surprising connections | 有 | 有，且写回 Neo4j `RELATED_TO {surprising:true}` |
| diagnostics | 有 | 有，日志告警，不阻断 ingest |
| suggested questions | graphify 有相关分析能力 | Prism 结合 graphify 结果做了自己的问题建议和社区标签层 |

Prism 对应代码：

- 分析层：[engine/app/graph/analyzer.py](H:/Agent/Project/Prism/prism/engine/app/graph/analyzer.py:122)
- graph insights：[engine/app/graph/insights.py](H:/Agent/Project/Prism/prism/engine/app/graph/insights.py:1)

直接复用 graphify 的地方：

1. `build_from_json(...)`
2. `cluster(...)`
3. `score_all(...)`
4. `surprising_connections(...)`
5. `diagnose_extraction(...)`

Prism 自己新增的地方：

1. `community_id / is_god / cohesion` 回写 Neo4j
2. `GraphCommunity`、社区标签、建议问题持久化
3. graph-driven governance 信号接入

### 6. report / export / query

| 项目 | graphify | Prism 当前 |
|---|---|---|
| 输出形式 | graph.json / graph.html / path / explain | unified graph API、/graph 页面、统一检索、Agent evidence |
| 用户主要交互 | 看图、explore、query path | 问答检索、来源回溯、图页浏览 |
| path/explain | graph 内部探索能力强 | Prism 更强调 evidence bundle 与 source 回源 |

Prism 对应代码：

- 统一图 API：[backend/app/api/unified_graph.py](H:/Agent/Project/Prism/prism/backend/app/api/unified_graph.py:258)
- 图页：[frontend/src/pages/KnowledgeGraphPage.tsx](H:/Agent/Project/Prism/prism/frontend/src/pages/KnowledgeGraphPage.tsx:559)
- 统一检索：[engine/app/retrieval/unified.py](H:/Agent/Project/Prism/prism/engine/app/retrieval/unified.py:126)
- 图扩展读接口：[backend/app/services/graph_client.py](H:/Agent/Project/Prism/prism/backend/app/services/graph_client.py:135)

Prism 在这一段的明显差异是：

1. 图不是终点，而是检索编排器的一部分。
2. 图分析结果会反过来影响检索召回。
3. 最终用户看到的是“答案 + source”，不是“导出图文件”。

## 按模块对照

### A. 数据模型

| 维度 | graphify | Prism 当前 |
|---|---|---|
| 图主存储 | 自身图对象/导出产物 | MySQL 审计表 + Neo4j 派生图 |
| 核心节点 | 文件、实体、关系对象 | `KnowledgeEntity`、`EntityMention`、`EntityRelation`、`KnowledgeChunk`、`PersonalAssetUnit` |
| 单一真相源 | 更接近图产物 | 更接近关系库 + 源文本 |

结论：

- graphify 更像“图优先”。
- Prism 更像“知识库优先，图为派生索引层”。

### B. 抽取方法

| 维度 | graphify | Prism 当前 |
|---|---|---|
| 主方法 | 结构解析 + 确定性抽取倾向更强 | LLM 抽取更强 |
| 对代码友好 | 很强 | 当前不是重点 |
| 对个人知识/文档知识 | 可做，但不是你这套产品化路径 | 正是主场景 |

结论：

- graphify 更适合“工程/代码/多模态文件构图”。
- Prism 更适合“知识材料治理、回源、Agent 检索”。

### C. 检索使用方式

| 维度 | graphify | Prism 当前 |
|---|---|---|
| 图是否直接用于查询 | 是 | 是 |
| 是否和向量/BM25 混合 | 不是它的主叙事 | 是当前主叙事 |
| 是否输出回源证据 | 有 explain/path | Prism 更系统化，面向 Agent evidence bundle |

Prism 具体实现：

- hybrid recall + graph expansion + RRF + rerank  
  [engine/app/retrieval/unified.py](H:/Agent/Project/Prism/prism/engine/app/retrieval/unified.py:126)

这意味着：

- graphify 更偏“图探索工具”
- Prism 更偏“GraphRAG 检索系统”

## 你当前已经和 graphify 对齐到什么程度

### 已经明显对齐

1. Stage A 抽取 schema
2. 实体图分析层
3. community / god / surprising 这套图洞察概念
4. 把“图谱不仅是存储，还能反过来指导检索”这件事做起来了

### 还没有对齐

1. 没有统一 detect 层
2. 没有把 code/file structure 这类确定性边作为一等公民
3. 没有以 `graph.json / explain / path` 为第一输出
4. 不是 graphify 那种 local-first 单体图工具架构

### 你自己比 graphify 更重的部分

1. MySQL 审计与回源模型
2. `document_chunk` 与 `personal_asset_unit` 的双来源治理
3. 统一检索编排器
4. Agent 证据返回、source 持久化恢复、前端知识搜索工具接入

## 最终判断

如果用一句更准确的话描述你当前系统和 graphify 的关系：

> Prism 现在是“借用 graphify 的抽取契约与图分析能力，服务于一个更偏知识治理和 Agent 检索的系统”，而不是“把 graphify 整个产品逻辑搬过来”。

更细一点说：

1. 在抽取层，你已经部分 graphify 化。
2. 在分析层，你已经直接 graphify 运行时化。
3. 在系统目标层，你仍然和 graphify 不同，因为你追求的是统一知识空间、证据回源、检索增强和 Agent 可用性。

## 快速导航

- 文档与 chunk 的 Stage A 入口：
  [engine/app/ingestion/pipeline.py](H:/Agent/Project/Prism/prism/engine/app/ingestion/pipeline.py:205)
- PersonalAssetUnit 的 Stage A 入口：
  [backend/app/api/assets.py](H:/Agent/Project/Prism/prism/backend/app/api/assets.py:437)
- Stage A 抽取：
  [engine/app/extraction/stage_a.py](H:/Agent/Project/Prism/prism/engine/app/extraction/stage_a.py:17)
- Stage A prompt / JSON schema：
  [engine/app/extraction/prompts.py](H:/Agent/Project/Prism/prism/engine/app/extraction/prompts.py:10)
- 实体/关系落库：
  [backend/app/services/entity_extraction.py](H:/Agent/Project/Prism/prism/backend/app/services/entity_extraction.py:106)
- Neo4j 投影：
  [backend/app/services/graph_projection.py](H:/Agent/Project/Prism/prism/backend/app/services/graph_projection.py:151)
- graphify 分析接入：
  [engine/app/graph/analyzer.py](H:/Agent/Project/Prism/prism/engine/app/graph/analyzer.py:122)
- 统一图 API：
  [backend/app/api/unified_graph.py](H:/Agent/Project/Prism/prism/backend/app/api/unified_graph.py:258)
- 统一检索：
  [engine/app/retrieval/unified.py](H:/Agent/Project/Prism/prism/engine/app/retrieval/unified.py:126)

## 参考

- graphify README  
  https://raw.githubusercontent.com/Graphify-Labs/graphify/v8/README.md
- graphify ARCHITECTURE  
  https://raw.githubusercontent.com/Graphify-Labs/graphify/v8/ARCHITECTURE.md
- Prism 内部相关设计  
  [2026-07-03-universal-graph-index-design.md](H:/Agent/Project/Prism/prism/docs/superpowers/specs/2026-07-03-universal-graph-index-design.md:1)
  [2026-07-05-stepA-hardening-stepB-graphify-analysis-design.md](H:/Agent/Project/Prism/prism/docs/superpowers/specs/2026-07-05-stepA-hardening-stepB-graphify-analysis-design.md:1)
