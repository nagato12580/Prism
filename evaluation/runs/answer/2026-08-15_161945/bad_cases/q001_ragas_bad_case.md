# Ragas Bad Case: q001

**Question:** 在RAG系统中，父子块之间的映射关系通常通过什么方式在工程落地中建立

**Tags:** retrieval_failure, ragas_failed

## Scores

{
  "response_relevancy": 0.9378639355476293
}

## Answer

这是一个通用技术问题，不涉及你的知识库内容，我直接基于工程实践回答。

# 结论

父子块映射关系在工程落地中最常见的做法是：**在文档切分阶段同步生成子块，并在每个子块上写入指向父块的元数据字段（如 `parent_id`），检索时通过该字段回溯父块**。

# 常见实现方式

## 1. 切分时建立映射（核心做法）

父块先按语义/结构边界切好（如标题、段落、章节），再对每个父块内部按更细粒度切出子块（如固定 token 窗口、句子），子块携带 `parent_id` 元数据：

- 父块：`chunk_id = P1`，内容为整个段落
- 子块：`chunk_id = C1-1, C1-2...`，每个子块 metadata 中写 `parent_id = P1`

## 2. 依赖现成框架的分层切分

工程上很少手写，通常直接用框架内置的分层解析器：

- **LangChain**：`ParentDocumentRetriever` + 两级 splitter（如 `RecursiveCharacterTextSplitter` 分别设大小粒度），切分时自动维护子块 → 父块映射
- **LlamaIndex**：`HierarchicalNodeParser`（按标题层级递归切分）或 `SentenceWindowNodeParser`（窗口句子块），节点间自动写入 parent/child 关系

## 3. 存储层的表达方式

- **向量库**：在向量记录的 metadata 字段中存 `parent_id`、`doc_id`、层级号，检索子块后按 metadata 回溯
- **关系型/文档库**：单独建 chunk 表，用外键或嵌套结构维护父子关系，便于批量和增量更新

# 检索时的典型用法

1. **子块做 embedding 检索** → 小粒度保证召回率（命中率高、噪声小）
2. **命中后回溯父块** → 将整个父块作为上下文输入 LLM，保证信息完整
3. 可选的优化：父块也单独向量化，用于先粗筛再细检，或做去重/过滤

# 工程注意点

- **同步更新**：父块重新切分时，所有子块的 `parent_id` 必须级联更新，否则会出现悬空引用
- **ID 稳定性**：建议用稳定且可重算的 chunk ID（如文档 ID + 位置哈希），而不是依赖数据库自增主键
- **父块大小控制**：父块不宜过大，否则超出 LLM 上下文窗口，一般控制在 1~2 个语义段落或 1000~2000 token

# 不确定点

以上是通用实践总结，不针对你具体的代码库或数据。如果你告诉我你用的是哪种框架（LangChain / LlamaIndex / 自研）和向量库，我可以给出更具体的落地方案。

## Retrieved Contexts



## Reference Excerpt

[image-20260408115740220](attachment/image-20260408115740220.png)## RAG系统流程文档解析 (Parsing) -> 分块 (Chunking) -> 向量化 (Embedding) -> 存入向量数据库 (Vector DB) -> 用户提问查询 -> 检索 (Retrieval) -> 结合 Prompt 送入 LLM 生成答案。## 向量检索算法![image-20260408162730013](attachment/image-20260408162730013.png)## 父子块分块策略，子块对应的父块合父块对应的子块的关系要如何记录在工程落地中，父子块（Parent-Child Chunking）的映射关系本质上是一个**关系型数据设计**。

---

png)## 父子块分块策略，子块对应的父块合父块对应的子块的关系要如何记录在工程落地中，父子块（Parent-Child Chunking）的映射关系本质上是一个**关系型数据设计**。由于大模型 RAG 系统的特殊性，主流的实现方案是通过 **唯一标识符（ID）+ 元数据（Metadata）** 来建立绑定，并通常采用**双层存储架构（Two-Tier Storage）**。### 1.核心架构：双层存储分离为了兼顾“检索精度”和“存储效率”，我们通常不会把冗长的父块文本和子块的向量挤在同一个数据库的同一张表里。

---

核心架构：双层存储分离为了兼顾“检索精度”和“存储效率”，我们通常不会把冗长的父块文本和子块的向量挤在同一个数据库的同一张表里。- **底层（检索层）：向量数据库（Vector DB）**。例如 Milvus, Qdrant, Chroma 等。这里**只存子块**的 Embedding 向量、子块文本片段，以及至关重要的 Metadata（其中包含指向父块的 ID）。- **顶层（内容层）：键值/文档数据库（KV/Document Store）**。例如 Redis, MongoDB，或者在轻量级本地 Agent 项目中直接用 SQLite 或本地 JSON 文件。这里**只存父块**的完整文本，以 `parent_id` 作为主键（Key）。### 2.

---

### 2.数据结构设计（Schema）在你的 Python 后端处理逻辑中，数据切分和入库时需要构建类似如下的数据字典结构：**写入向量数据库的子块数据（Child Chunk）：**JSON```{"child_id": "child_001_a","embedding": [0.12, -0.45, 0.89, ...],"content": "该聚类算法在处理高维噪声数据时表现出极强的鲁棒性。","metadata": {"parent_id": "doc_001_paragraph_3",  // 核心：指向父块的外键"source_file": "research_paper.pdf","chunk_index": 1}}```**写入 KV/文档数据库的父块数据（Parent Chunk）：**JSON```{"parent_id": "doc_001_paragraph_3",    // 核心：主键"content": "在多视图学习框架中，数据往往伴随大量噪声。

---

pdf","chunk_index": 1}}```**写入 KV/文档数据库的父块数据（Parent Chunk）：**JSON```{"parent_id": "doc_001_paragraph_3",    // 核心：主键"content": "在多视图学习框架中，数据往往伴随大量噪声。该聚类算法在处理高维噪声数据时表现出极强的鲁棒性。实验证明，通过引入隐式正则化模块，能够有效剥离异常视图的干扰...","child_ids": ["child_001_a", "child_001_b", "child_001_c"], // 可选：父到子的反向映射"metadata": {"author": "Huilang","publish_date": "2026-03"}}```### 3.

---

","child_ids": ["child_001_a", "child_001_b", "child_001_c"], // 可选：父到子的反向映射"metadata": {"author": "Huilang","publish_date": "2026-03"}}```### 3.工程化检索的完整工作流 (Workflow)当用户发起一个提问时，系统是如何利用这套映射关系的呢？1.

## Source IDs



## Metadata

{
  "question_type": "",
  "paper_title": "面试常见问题",
  "ttfb_ms": 3693,
  "total_latency_ms": 17649,
  "tool_calls": 0,
  "token_count": 1,
  "status": "done",
  "missing_context_count": 0
}