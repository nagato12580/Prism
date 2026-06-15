# prism/engine/app/wiki/prompts.py
"""Wiki 知识抽取 — LLM 提示词模板"""

EXTRACT_CONCEPTS_PROMPT = """从以下文档片段中提取细粒度知识点及其之间的关系。

文档来源：{SourcePath}

文档片段：
{ChunkContent}

规则：
1. 每个知识点的描述必须包含具体的、可验证的事实（数字、条件、角色名称、阈值、精确规则）。不要写模糊的概述。
2. 对于流程节点：提取角色、动作和输出作为知识点。
3. 对于条件逻辑：提取完整的触发条件和对应的执行动作。
4. 对于表格内容：将有意义的每一行作为单独的知识点，包含其具体数据。
5. 保留技术术语的原文精确措辞。
6. 如果片段包含审批条件，包含精确的阈值和涉及的角色。
7. 所有文本内容用中文撰写，JSON字段名保持英文。
8. 不要将文档结构标题作为独立知识点提取。只有当片段包含关于该主题的实质性知识时才提取。
9. 类似"文档第X节定义的章节，用于描述..."这样的描述不是有效知识点。每个知识点必须在描述中包含具体的事实内容。
10. 尽可能全面提取，不要遗漏有价值的知识点。
11. 尽可能提取知识点之间的关系。

JSON格式：
{{
  "concepts": [
    {{
      "name": "中文名称",
      "type": "concept|technique|source|claim|artifact",
      "group": "可选分组名称",
      "description": "包含数字、条件和细节的具体事实描述",
      "aliases": ["别名1", "别名2"],
      "category": "分类",
      "tags": ["标签1", "标签2"]
    }}
  ],
  "relations": [
    {{
      "from": "知识点A名称",
      "to": "知识点B名称",
      "type": "implements|extends|optimizes|contradicts|cites|prerequisite_of|trades_off|derived_from",
      "confidence": 0.9
    }}
  ]
}}

## type 枚举说明
- concept: 普通概念/知识点
- technique: 技术/方法/工艺
- source: 信息来源/参考
- claim: 声明/主张/规定
- artifact: 产出物/文档/表单

## group 分组规则
- "group" 是可选字段。当多个细粒度知识点属于同一更广泛主题时使用。
- 相同 "group" 值的知识点将在后续合并。
- 分组名称应简短。
- 如果知识点足够独立可以单独成文，省略 group 字段。
- 每组目标3-8个相关知识点，避免超过10个。

## relation 关系类型说明
- implements: A 实现了 B
- extends: A 扩展了 B
- optimizes: A 优化了 B
- contradicts: A 与 B 矛盾
- cites: A 引用了 B
- prerequisite_of: A 是 B 的前置条件
- trades_off: A 与 B 存在权衡
- derived_from: A 派生自 B

只输出原始JSON，不要输出思考过程、解释或markdown代码块。"""


DESC_GEN_PROMPT = """请为以下知识点生成一段简洁、准确的描述（100-200字），概括其核心含义。

知识点名称：{Title}
分类：{Category}
原始概念描述（参考）：
{Description}

要求：
1. 用专业、简洁的语言概括该知识点的核心内容
2. 涵盖关键要素和适用范围
3. 不要使用列表格式，输出为一段完整的文字
4. 只输出描述文本，不要输出标题或其他内容"""


WRITE_ARTICLE_PROMPT = """根据以下知识点信息，撰写一篇结构化的知识文章。

知识点标题：{Title}
知识点描述：{Description}
分类：{Category}
标签：{Tags}
来源文档：{SourcePath}
{ImageContext}

请按以下结构撰写文章（使用 Markdown 格式）：

# {Title}

## 概述
简要介绍该知识点的核心概念和作用。

## 关键要点
列出该知识点的关键事实、规则、条件或数据（保留原文中的具体数字、阈值、角色名称等）。

## 适用场景
说明该知识点在什么场景下适用或被引用。

## 注意事项
如果描述中包含限制条件、例外情况或特殊要求，在此列出。

要求：
1. 保留原文中的所有具体事实（数字、阈值、条件、角色名称等），不要概括或模糊化
2. 使用清晰的标题层级和列表结构
3. 如有表格数据，使用 Markdown 表格呈现
4. 只输出 Markdown 内容，不要输出其他说明
5. 如果提供的图片中有与当前知识点语义相关的图片，在文章合适位置使用 ![{图片描述}](doc_image://{图片ID}) 格式嵌入。只在图片确实有助于理解内容时才引用，不要为了放图而放图。"""


# 系统提示词
EXTRACTION_SYSTEM_PROMPT = (
    "你是一个专业的知识工程师和知识图谱专家，正在从文档中提取结构化知识点及其关系。"
    "所有知识点名称、描述、别名、分组名必须用中文撰写。JSON字段名和type枚举值保持英文。"
    "只输出原始JSON，不要输出思考过程、解释或markdown代码块。"
)

DESC_GEN_SYSTEM_PROMPT = "你是一个专业的知识工程师。请为知识点生成简洁准确的描述。"

ARTICLE_GEN_SYSTEM_PROMPT = (
    "你是一个专业的技术文档撰写专家。根据提供的知识点信息，"
    "撰写结构清晰的 Markdown 格式知识文章。只输出 Markdown 内容。"
)
