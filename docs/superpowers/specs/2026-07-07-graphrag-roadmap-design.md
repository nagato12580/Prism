# GraphRAG Roadmap Design

- 日期：2026-07-07
- 状态：草案
- 主题：把 Prism 当前“统一知识空间 + 实体图 + 混合检索”演进成更完整的 GraphRAG 系统

## 1. 背景

Prism 当前已经具备 GraphRAG 的若干基础能力，但仍处在“图可用、未完全图优先”的阶段。

当前已具备的基础包括：

1. 文档 chunk 与 `PersonalAssetUnit` 已可进入统一实体图。
2. Stage A 已能从文本中抽取实体与关系。
3. 图分析层已接入 graphify 的若干能力，如 community、god node、surprising connection。
4. 检索链路已不再是纯向量检索，已经有图扩展参与召回。
5. `/graph` 页面已经从 CKP/PKU 工作台转向统一图探索器。

当前仍存在的主要问题包括：

1. 图构建入口仍然分散，文档与资产两条链路没有统一编排层。
2. 图检索结果尚未完整具备 `query / path / explain` 三类能力。
3. `EXTRACTED / INFERRED` 这类“诚实边”语义还没有完全进入回答与前端展示层。
4. 图分析结果虽然存在，但更多是在“后台增强检索”，还没有成为一套完整的可解释、可运营能力。
5. 系统整体上还不像 graphify 那样，把 detect、extract、build、analyze、export 严格拆成统一阶段。

## 2. 目标

本设计的目标不是把 Prism 改造成 graphify 的复制品，而是吸收 graphify 最适合 GraphRAG 的设计，使 Prism 成为一个：

1. 以统一知识图为核心中枢；
2. 同时支持文档与个人资产知识；
3. 可以解释“为什么命中、如何连通、哪些是直接证据、哪些是推断关系”；
4. 同时适合 Agent 检索、前端图探索、知识治理运营；
5. 能持续演进的 GraphRAG 系统。

一句话目标：

> 让 Prism 从“图参与检索的知识系统”演进成“图是第一等检索与解释底座的 GraphRAG 系统”。

## 3. 非目标

本轮路线图不追求以下事项：

1. 不把 Prism 改造成 graphify 的本地 CLI 产品形态。
2. 不要求一次性重写现有 ingest / retrieval / graph 页面。
3. 不要求在 P0 就统一所有来源类型，如 code、image、video。
4. 不要求在 P0 或 P1 阶段完全去除现有数据库投影结构。
5. 不把这份路线图等同于详细实施计划；后续仍需单独拆 plan。

## 4. 设计原则

### 4.1 均衡推进

采用“均衡推进”策略，而不是“纯检索优先”或“纯建图优先”。

含义是：

1. 每一阶段都同时推进建图与检索；
2. 每一阶段都形成一个能独立验证的闭环；
3. 不允许出现“图建得很复杂但问答没收益”；
4. 也不允许出现“检索逻辑越补越多，但图底座仍然散乱”。

### 4.2 统一知识空间优先

所有设计都围绕统一知识空间展开：

1. `document_chunk` 与 `personal_asset_unit` 应当是同一图中的两类 source。
2. 实体节点应该可以挂接多个来源。
3. 检索、展示、会话恢复、trace 都应消费同一种 source/provenance 结构。

### 4.3 诚实边原则

GraphRAG 不应把图推断伪装成原文事实。

因此：

1. 图中的关系必须明确区分直接抽取与推断关系。
2. 回答层必须知道某条关系是 `EXTRACTED` 还是 `INFERRED`。
3. 前端和 trace 最终都要能展示这种差异。

### 4.4 图是产品，不只是索引

图不只是为了给检索做额外召回，也应该能成为：

1. 可浏览的探索器；
2. 可诊断的知识治理工作台；
3. 可解释的证据组织层；
4. 可导出的分析产物层。

## 5. 从 graphify 借鉴的核心设计

本路线图主要借鉴 graphify 的以下设计，而非照搬其完整产品：

1. 统一阶段化流水线：`detect -> extract -> build_graph -> cluster -> analyze -> export`
2. “诚实边”模型：显式区分 `EXTRACTED` 与 `INFERRED`
3. 图分析结果作为一等能力：community、god node、surprising connection、diagnostics
4. `query / path / explain` 三类图消费方式
5. 图产物的多出口：给机器的结构化输出、给人的报告/解释、给前端的可交互视图

Prism 不直接照搬 graphify 的部分包括：

1. 本地 CLI / local-first 产品形态
2. code-first / AST-first 的主使用场景
3. 以导出 `graph.json` / `graph.html` 为第一目标的交互模式

## 6. 三期路线图

---

## P0：最小 GraphRAG 闭环

### 6.1 目标

让图不再只是“后台召回增强器”，而真正进入问答主链路，形成最小 GraphRAG 闭环。

一句话：

> 先让图“能回答、能解释、能回源”。

### 6.2 范围

P0 只做最小闭环，不重写建图架构，但必须补齐图检索和图解释的统一契约。

### 6.3 核心改造点

#### A. 统一图检索返回契约

统一所有图相关命中结果的数据结构，至少覆盖：

1. `hit`
2. `source`
3. `path`
4. `explain`
5. `evidence_type`
6. `source_kind`
7. `source_id`

这样无论命中来自：

1. 直接 hybrid 召回；
2. 图 1-hop / 2-hop 扩展；
3. community 扩展；
4. surprising 扩展；

都能被同一消费层解释。

#### B. 让 `EXTRACTED / INFERRED` 进入问答层

当前系统已在抽取/分析阶段使用分层语义，但这套语义必须进入：

1. unified retrieval 输出；
2. Agent evidence bundle；
3. final answer 引用；
4. 前端 source/explain 展示。

要求：

1. 直接证据优先回答；
2. 推断关系只能作为补充导航，不能伪装成原文证据；
3. 当答案依赖图推断时，UI 与 trace 必须可见。

#### C. 补足 `query / path / explain`

P0 的 GraphRAG 不要求复杂分析，但必须形成三类基础消费能力：

1. `query`：查一个实体/主题关联到哪些 source
2. `path`：查两个实体/主题如何通过图连通
3. `explain`：解释某个 source 或答案为什么被命中

#### D. 统一 provenance / source 结构

`document_chunk` 与 `personal_asset_unit` 的图命中结果都必须映射成统一 source 对象，以保证：

1. 前端知识搜索工具展示一致；
2. 会话持久化恢复一致；
3. trace 持久化一致；
4. Agent 最终引用一致。

#### E. 前端补最小 explain 展示

P0 不要求前端变成完整工作台，但必须让用户看见：

1. 命中的实体
2. 命中的来源
3. 命中的关系路径
4. 哪些边是 inferred

### 6.4 P0 验收标准

满足以下条件视为完成：

1. 图命中结果能以统一结构返回并被前端消费；
2. `EXTRACTED / INFERRED` 会进入 evidence 层；
3. 用户能从回答或前端看到“为什么命中这个 source”；
4. `document_chunk` 与 `personal_asset_unit` 的 source 显示与恢复一致；
5. GraphRAG 已经不再只是“隐藏在检索内部的图扩展”。

---

## P1：统一建图流水线

### 7.1 目标

把当前分散的入图链路整理成更接近 graphify 的统一流水线，同时增强抽取质量和稳定性。

一句话：

> 再让图“建得稳、建得统一、建得可诊断”。

### 7.2 范围

P1 重点不在前端，而在内部图构建编排、抽取模式与中间表示。

### 7.3 核心改造点

#### A. 建统一 `detect -> extract -> build -> analyze` 编排器

当前文档链路与资产链路的核心问题不是功能缺失，而是：

1. 入口不同；
2. 编排分散；
3. 中间表示不统一。

P1 需要一个统一内部管线，负责：

1. 接收来源对象
2. 识别来源类型
3. 预处理/切分
4. 调用抽取
5. 持久化图中间产物
6. 投图
7. 调用分析

文档和资产之间只保留 source adapter 差异，不保留主流程差异。

#### B. 引入统一中间图 schema

当前中间层过于贴近数据库表结构。

P1 需要引入显式中间图 schema，例如：

1. `nodes`
2. `edges`
3. `provenance`
4. `confidence`
5. `extraction_mode`
6. `source_ref`

这个 schema 的作用不是替换数据库，而是成为：

1. 抽取输出的统一契约
2. 分析层输入的统一契约
3. 导出层和诊断层的统一契约

#### C. 建立“双模抽取”

这是最值得借 graphify 的一条。

原则：

1. 结构化信号优先走确定性抽取；
2. LLM 抽取负责补充语义实体与关系；
3. 尽量避免把低成本、低歧义结构信息全部丢给模型。

首批可纳入确定性抽取的内容：

1. 标题、章节、列表
2. 文档 metadata
3. asset 字段结构
4. parent/child chunk 结构
5. 明确链接、引用、标签、分类

#### D. 抽取质量诊断

P1 必须开始系统化诊断以下问题：

1. 泛词实体
2. 代词实体
3. 悬空边
4. source 无法回源
5. 社区塌缩
6. 低信息实体过多

这些诊断结果至少要能：

1. 记录日志；
2. 用于人工排查；
3. 为后续图工作台提供基础数据。

#### E. 分析结果稳定化

P1 还要继续强化 graph analysis 稳定性：

1. `community_id` 尽量稳定
2. `is_god` 不因轻微重算剧烈抖动
3. surprising 边不要过度爆炸
4. 图更新不应造成前端认知大幅跳变

### 7.4 P1 验收标准

满足以下条件视为完成：

1. 文档与资产共享一套主图流水线；
2. 分析层输入有统一 schema；
3. 系统不再完全依赖 LLM 做所有图抽取；
4. 常见坏抽取能被系统性诊断；
5. 图分析结果在重复运行下更稳定。

---

## P2：graphify 化完善

### 8.1 目标

在已有统一图底座和 GraphRAG 闭环基础上，把图提升为一个可解释、可运营、可导出的产品层。

一句话：

> 最后让图“长成产品”，而不只是底层能力。

### 8.2 范围

P2 重点是产品化、解释能力、导出能力和社区级 GraphRAG。

### 8.3 核心改造点

#### A. 图导出层

构建统一图导出能力，支持：

1. 子图 JSON
2. explain payload
3. path payload
4. graph diagnostics report
5. 社区摘要导出

这一步对应 graphify 的 export/report 思想，但会适配 Prism 的知识系统结构。

#### B. 社区级 GraphRAG

检索扩展不再只围绕 seed entity，而是围绕 graph community 组织：

1. query 匹配 seed entity
2. 根据 seed 的 `community_id` 找同社区代表实体
3. 再回源到 source
4. 形成更好的跨文档、跨资产综合问答

#### C. surprising / bridge retrieval

把 surprising edge 从“图分析彩蛋”升级为正式召回信号，用于：

1. 隐性关联发现
2. 多跳答案补全
3. 用户探索式提问

#### D. 图工作台

把 `/graph` 或相关图页面逐步升级成工作台，支持：

1. 社区总览
2. god node 总览
3. 可疑实体与坏抽取诊断
4. source coverage
5. graph health
6. 按社区/来源钻取

#### E. Agent 原生图解释

最终让 Agent 能原生构造基于图的解释，而不只是附 source：

1. 为什么这几个来源会被一起引用
2. 它们通过哪些实体关系相连
3. 哪部分是直接证据
4. 哪部分是图推断

### 8.4 P2 验收标准

满足以下条件视为完成：

1. 图存在稳定导出形态；
2. 社区级 GraphRAG 可用于实际问答；
3. surprising/bridge 类信号能产生真实召回价值；
4. 图工作台可用于人工治理与排查；
5. Agent 可以输出图解释，而非只输出引用列表。

## 9. 三期之间的关系

### 9.1 为什么 P0 要先做

因为如果图还不能直接为回答提供：

1. 命中解释
2. path
3. provenance
4. EXTRACTED / INFERRED 区分

那么继续大做建图，只会让系统越来越复杂，却无法立即验证图是否真的提升回答质量。

### 9.2 为什么 P1 必须紧跟 P0

因为如果没有统一建图流水线：

1. 文档和资产会继续漂成两套图逻辑；
2. source/provenance 一致性会越来越脆；
3. 后续 explain/export/workbench 都会被底层分裂拖住。

### 9.3 为什么 P2 放最后

因为 P2 主要是能力放大和产品化，不应该在：

1. GraphRAG 还没有最小回答闭环；
2. 图流水线还没统一；

之前过早投入。

## 10. 推荐执行顺序

推荐顺序严格如下：

1. P0：先让图真正进入问答与解释主链路
2. P1：再统一建图流水线与质量诊断
3. P2：最后做社区级 GraphRAG、导出与图工作台

一句话版本：

1. P0：先让图能回答
2. P1：再让图建得稳
3. P2：最后让图长成产品

## 11. 风险与约束

### 11.1 复杂度风险

GraphRAG 最容易失败的方式是：

1. 图分析越来越复杂；
2. 检索收益却不明显；
3. 用户看不到解释收益；
4. 工程维护成本暴涨。

因此每一期都必须带着明确验收标准推进，而不是“先多做点图能力再说”。

### 11.2 误把推断当证据的风险

这是 GraphRAG 的核心风险之一。

如果 `INFERRED` 边与 `EXTRACTED` 边没有严格分层，最终回答就会出现：

1. 把图分析结果说成原文事实
2. 把隐性关联说成明确陈述
3. 让用户误解出处

所以“诚实边原则”是贯穿三期的红线。

### 11.3 多来源一致性风险

如果 `document_chunk` 与 `personal_asset_unit` 的 source/provenance 不能统一，后续会同时影响：

1. 检索融合
2. 前端展示
3. trace 恢复
4. 图 explain

因此这项能力必须在 P0 就解决，而不能拖到后面。

## 12. 最终结论

这份路线图的核心判断是：

1. Prism 目前已经拥有 GraphRAG 的基础骨架；
2. 真正缺的不是“再加一个图数据库”，而是把图变成第一等检索与解释底座；
3. graphify 最值得借的不是完整产品外壳，而是它对阶段化流水线、诚实边、图分析和 explain/export 的设计意识；
4. 采用 `P0 -> P1 -> P2` 的均衡推进路线，可以在不推翻现有系统的前提下，把 Prism 稳定演进成成熟 GraphRAG。

## 参考

- [2026-07-06-graphify-prism-comparison.md](H:/Agent/Project/Prism/prism/docs/2026-07-06-graphify-prism-comparison.md:1)
- [2026-07-03-universal-graph-index-design.md](H:/Agent/Project/Prism/prism/docs/superpowers/specs/2026-07-03-universal-graph-index-design.md:1)
- [2026-07-05-stepA-hardening-stepB-graphify-analysis-design.md](H:/Agent/Project/Prism/prism/docs/superpowers/specs/2026-07-05-stepA-hardening-stepB-graphify-analysis-design.md:1)
- graphify README: https://github.com/Graphify-Labs/graphify
- graphify architecture: https://github.com/Graphify-Labs/graphify/blob/v8/ARCHITECTURE.md
