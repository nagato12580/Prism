# 文档知识抽取管线 — 架构设计文档

## 1. 概述

本管线实现了"上传文档 → 自动提取结构化知识"的完整流程。核心思路是：**让 LLM 在一次调用中同时完成知识提取、归类、关联三件事**，后续代码只做机械性的去重、合并、持久化。

## 2. 整体架构

```
文档上传
  │
  ▼
Stage 0: 文件解析
  PDF/DOCX/XLSX/PPTX → 文本提取 + 图片提取
  输出: text (纯文本) + images (图片列表)
  │
  ▼
Stage 1.5: 图片语义识别（可选）
  图片 → base64 → 视觉 LLM → 中文描述
  [图片N] 占位符 → [图片N: 描述]
  │
  ▼
Stage 2: 概念提取 ← 核心阶段
  text → 按 section 边界切块 (MAX=4000字符, overlap=200)
       → ThreadPoolExecutor 并发调用 LLM
       → 每个 chunk 返回 {concepts[], relations[]} JSON
       → 按 name 去重（同名概念合并描述和别名）
       → 写入 doc_concepts 表
  │
  ▼
Stage 3: 知识点合并
  doc_concepts → 按 group 字段分组
               → 同组概念合并为一个 KnowledgePoint
               → 无 group 的概念独立成 KnowledgePoint
               → 关系名称解析（概念名 → 知识点评名）
               → 写入 doc_knowledge_points + doc_knowledge_relations 表
  │
  ▼
Stage 3.5a: 描述生成
  对缺少 description 的 KP → LLM 生成 100-200 字描述
  │
  ▼
Stage 3.5b: 文章生成
  对缺少 content 的 KP → LLM 生成结构化 Markdown 文章
  可引用 doc_image://{id} 嵌入图片
  │
  ▼
Stage 4: 向量化
  对缺少 embedding 的 KP
  → 拼接 title + description + content[:500] 为文本
  → 批量调用 Embedding API → 写入 KP.embedding (JSON)
  │
  ▼
Stage 5: 自定义 LLM 阶段（可选）
  如标签分类、合规检查等，从 pipeline 模板配置加载
```

## 3. 核心阶段详解

### 3.1 Stage 2: 概念提取 — 最关键的设计

**一次 LLM 调用产出三种结构化数据**：

```
输入：4000 字符的文档文本片段
     ↓
LLM 处理（提示词: extract_knowledge_points.txt）
     ↓
输出 JSON:
{
  "concepts": [
    {
      "name": "香烟入境限额",           // 知识点名称（中文）
      "type": "claim",                 // 类型: concept|technique|source|claim|artifact
      "group": "入境物品限额",          // 可选分组（同组概念后续合并）
      "description": "居民旅客携带烟草制品入境，限400支香烟...",  // 具体事实
      "aliases": ["携带香烟", "烟草限额"],
      "category": "海关规定",
      "tags": ["入境", "香烟", "限额"]
    }
  ],
  "relations": [
    {
      "from": "超额申报流程",
      "to": "海关放行",
      "type": "prerequisite_of",       // 8种关系类型之一
      "confidence": 0.9
    }
  ]
}
```

**概念的含义**：
- 概念 = 一个独立的、可验证的知识单元（如"香烟入境限400支"）
- 概念不是文本片段，而是 LLM 理解后重新组织的结构化知识
- 每个概念都要求包含具体的数字、条件、阈值等可验证事实

**同名去重策略**：
不同 chunk 可能提到同一概念 → `_merge_concepts` 按 name 去重：
- 同名概念合并 description（拼接，不重复的部分追加）
- 合并 aliases（收集所有别名）
- 保留首次出现的 group 和 category

**section 边界感知的分块器** (`_chunk_text`)：
- 按 Markdown 标题、数字编号、流程节点、中文序号等识别 section 边界
- MAX_CHUNK_SIZE=4000, OVERLAP_SIZE=200, MIN_CHUNK_SIZE=300
- 长段落继续按空行切分
- 相邻 chunk 之间加 200 字符重叠防止边界截断

### 3.2 Stage 3: group 字段的作用

group 是 LLM 在提取概念时**自动生成**的分组指令：

```
LLM 提取时:
  "香烟入境限额"  group="烟草入境规定"  ─┐
  "雪茄入境限额"  group="烟草入境规定"  ─┤
  "烟丝入境限额"  group="烟草入境规定"  ─┤ 合并为一个知识点:
  "超额申报流程"  group="烟草入境规定"  ─┤ name="烟草入境规定"
  "未申报处罚"    group="烟草入境规定"  ─┘ desc=各子概念描述的拼接

  "研发岗位职级"  group=""              ─── 独立知识点（无 group）
```

合并函数 `_merge_groups`：
- 有 group → 同组概念合并：group 名作为 title，各成员的 "name：description" 拼成整体 description
- 无 group → 每个概念独立成为一个知识点

**为什么这样设计**：LLM 理解语义，知道哪些概念是同一主题的不同方面。这比基于文本距离或嵌入相似度的机械合并更准确。

### 3.3 关系提取

8 种关系类型，同样是 LLM 从文本中提取：

| type | 含义 | 示例 |
|------|------|------|
| `implements` | A 实现了 B | "双因子认证" implements "安全登录" |
| `extends` | A 扩展了 B | "电子申报" extends "申报方式" |
| `optimizes` | A 优化了 B | "快速通道" optimizes "入境流程" |
| `contradicts` | A 与 B 矛盾 | "地方规定" contradicts "国家规定" |
| `cites` | A 引用了 B | "罚款标准" cites "海关法第X条" |
| `prerequisite_of` | A 是 B 的前置 | "填写申报单" prerequisite_of "海关放行" |
| `trades_off` | A 与 B 权衡 | "速度" trades_off "准确性" |
| `derived_from` | A 派生自 B | "罚款计算" derived_from "税率表" |

关系在 Stage 3 合并后做名称解析：LLM 返回的概念名通过 alias_map 映射到合并后的 KnowledgePoint，然后写入 `doc_knowledge_relations` 表。

### 3.4 Stage 3.5b: 文章生成

用提示词 `write_knowledge_point.txt`，让 LLM 将零散的概念描述整理成结构化 Markdown 文章：

```markdown
# 烟草入境规定

## 概述
烟草入境规定明确了居民旅客携带烟草制品的限额...

## 关键要点
- 香烟：限400支
- 雪茄：限100支
- 烟丝：限500克

## 适用场景
居民旅客入境时适用...

## 注意事项
超出限额需申报并缴税...
```

同时解析 LLM 输出的 `doc_image://{id}` 引用，将关联图片 ID 存入 `KnowledgePoint.images`。

### 3.5 断点续抽

管线支持中断后恢复，每个阶段完成后都会持久化到数据库：

```
检查逻辑:
  existing_kps 存在? → 跳过 Stage 0-3, 从描述/文章/向量化继续
  existing_concepts 存在? → 跳过 Stage 0-2, 从 Stage 3 继续
  都不存在 → 从头开始
```

## 4. 关键设计决策

### 4.1 为什么 LLM 一次调用产出概念+关系+分组？

- **选择**：单次 LLM 调用同时输出 concepts、relations、group
- **原因**：LLM 在理解文本时已经建立了概念间的关联和层级。让 LLM 在同一个上下文中完成提取+归类+关联，比分开调用再对齐更准确
- **代价**：输出结构复杂，需要 JSON 修复处理格式异常

### 4.2 为什么 group 字段由 LLM 生成而非代码计算？

- **选择**：LLM 在提取概念时直接给出 group 分组
- **原因**：LLM 理解语义，知道"香烟限额"和"雪茄限额"属于同一主题。基于文本相似度或关键词聚类的机械分组无法达到同样精度
- **代价**：依赖 LLM 的判断质量，需要提示词中明确分组规则（每组 3-8 个，避免超过 10 个）

### 4.3 为什么同名概念去重用描述拼接而非覆盖？

- **选择**：`_merge_concepts` 将同名概念的描述拼接（`existing_desc + '; ' + new_desc`）
- **原因**：不同 chunk 可能描述同一概念的不同方面。拼接能保留更多信息，后续由文章生成阶段的 LLM 整理
- **代价**：如果同名概念实际是不相关的歧义词，会被错误合并

### 4.4 为什么阶段 3.5a 和 3.5b 分开？

- **选择**：先生成描述(3.5a)，再生成文章(3.5b)
- **原因**：描述是文章的输入。如果概念合并后 description 是多个子概念描述的粗拼接，LLM 可能还需要重新整理。先让 LLM 生成精炼描述，再以此为基础生成文章，质量更好

## 5. 数据表依赖

| 表名 | 用途 | 写入阶段 |
|------|------|---------|
| doc_files | 文档元信息（原文件名、状态、进度） | 上传时创建，各阶段更新 |
| doc_concepts | LLM 提取的原始概念（未合并） | Stage 2 |
| doc_knowledge_points | 合并后的最终知识点 | Stage 3 |
| doc_knowledge_relations | 知识点间关系 | Stage 3 |
| doc_images | 文档内嵌图片及 LLM 描述 | Stage 1.5 |
| doc_analyze_logs | 管线执行日志 | 各阶段 |
| doc_engine_prompt_config | 提示词模板（DB 优先） | 各 LLM 阶段读取 |
| embedding_config | Embedding API 配置 | Stage 4 读取 |

## 6. 在新项目中复用时需要调整的参数

| 参数 | 当前值 | 调整建议 |
|------|--------|---------|
| MAX_CHUNK_SIZE | 4000 字符 | 根据 LLM 上下文窗口调整（建议 context/4） |
| OVERLAP_SIZE | 200 字符 | 5% 的 chunk 大小 |
| MIN_CHUNK_SIZE | 300 字符 | 太小的 chunk 没有足够上下文 |
| 文档并发度 | 5 | 由 CPU 和磁盘 IO 决定 |
| 知识点并发度 | 3 | 由 LLM API 限流策略决定 |
| concept type 枚举 | concept/technique/source/claim/artifact | 根据领域重定义 |
| relation type 枚举 | 8种 | 根据领域增减 |
| 描述长度 | 100-200 字 | 根据知识点的粒度调整 |
| section 边界模式 | 7 种正则 | 根据文档格式增减 |
| 断点续抽阈值 | 任意阶段 | 如需更细粒度可增加检查点 |
