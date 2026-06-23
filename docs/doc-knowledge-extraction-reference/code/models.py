"""
数据库模型 — 文档知识抽取管线的数据表结构

三张核心表:
  doc_concepts         — LLM 提取的原始概念（未合并），Stage 2 写入
  doc_knowledge_points — 合并后的最终知识点，Stage 3 写入
  doc_knowledge_relations — 知识点间关系，Stage 3 写入

============ 适配新项目指南 ============
1. 替换 SQLAlchemy 为新项目的 ORM 框架
2. 字段类型和约束需要根据新项目的数据库调整
3. doc_concepts 是中间表（概念→知识点），如果不需要断点续抽可以不用这张表
4. embedding 字段存储 JSON 数组字符串，如果使用独立向量数据库可以去掉这个字段
5. images 字段存储 JSON [{id, caption}]，如果不需要图片功能可以去掉
"""
from datetime import datetime

# ⚠️ 适配点：替换为新项目的 ORM 基类和引擎
# from your_orm import Base, engine


# ═══════════════════════════════════════════════════════════════════
# 1. DocConcept — 原始概念表（中间产物）
# ═══════════════════════════════════════════════════════════════════

class DocConcept:
    """
    LLM 提取的原始概念。

    对应 kmc-wiki concepts 表。
    每个 chunk 提取的概念按名称去重后存入此表。
    后续按 group 字段合并到 doc_knowledge_points（对应 kmc-wiki entries 表）。

    字段说明:
      doc_id      — 来源文档 ID (FK → doc_files)
      title       — 概念名称（中文）
      type        — 概念类型: concept|technique|source|claim|artifact
      description — 具体事实描述（包含数字、条件、阈值等）
      aliases     — 别名，逗号分隔
      group       — 分组名，同 group 的概念在 Stage 3 合并为一个知识点
      category    — 分类
    """
    __tablename__ = 'doc_concepts'

    id: int
    doc_id: int          # FK → doc_files.id
    title: str           # 概念名称 (max 512)
    type: str            # concept|technique|source|claim|artifact (max 32, default='concept')
    description: str     # 具体事实描述 (TEXT)
    aliases: str         # 别名，逗号分隔 (max 1024)
    group: str           # 分组名 (max 256, index)
    category: str        # 分类 (max 128)
    created_at: datetime


# ═══════════════════════════════════════════════════════════════════
# 2. KnowledgePoint — 最终知识点表
# ═══════════════════════════════════════════════════════════════════

class KnowledgePoint:
    """
    合并后的最终知识点。

    字段说明:
      doc_id      — 来源文档 ID（逗号分隔字符串，一个 KP 可能来自多个文档）
      title       — 知识点标题
      description — 精炼描述（100-200 字）
      content     — 结构化 Markdown 文章（LLM 生成）
      category    — 分类
      tags        — 标签，逗号分隔
      aliases     — 别名，逗号分隔
      group       — 分组名
      status      — 状态: 整理中|已发布
      embedding   — 向量 (JSON 数组字符串，如 "[0.1, 0.2, ...]")
      images      — 关联图片 (JSON: [{"id":3,"caption":"流程图"}, ...])
    """
    __tablename__ = 'doc_knowledge_points'

    id: int
    doc_id: str          # 来源文档ID，逗号分隔 (max 512)
    title: str           # 知识点标题 (max 512)
    description: str     # 精炼描述 (TEXT)
    content: str         # Markdown 文章 (TEXT)
    category: str        # 分类 (max 128)
    tags: str            # 标签，逗号分隔 (max 1024)
    aliases: str         # 别名，逗号分隔 (max 1024)
    group: str           # 分组名 (max 256)
    status: str          # 整理中|已发布 (max 16, default='已发布')
    embedding: str | None  # 向量 JSON (TEXT, nullable)
    images: str          # 关联图片 JSON (TEXT, default='')
    created_at: datetime


# ═══════════════════════════════════════════════════════════════════
# 3. KnowledgeRelation — 知识点关系表
# ═══════════════════════════════════════════════════════════════════

class KnowledgeRelation:
    """
    知识点间关系。

    字段说明:
      from_kp_id — 源知识点 ID (FK → doc_knowledge_points)
      to_kp_id   — 目标知识点 ID (FK → doc_knowledge_points)
      type       — 关系类型
      confidence — 置信度 (0.0 ~ 1.0)

    关系类型:
      implements      — A 实现了 B
      extends         — A 扩展了 B
      optimizes       — A 优化了 B
      contradicts     — A 与 B 矛盾
      cites           — A 引用了 B
      prerequisite_of — A 是 B 的前置条件
      trades_off      — A 与 B 存在权衡
      derived_from    — A 派生自 B
    """
    __tablename__ = 'doc_knowledge_relations'

    id: int
    from_kp_id: int     # FK → knowledge_points.id
    to_kp_id: int       # FK → knowledge_points.id
    type: str           # 关系类型 (max 64)
    confidence: float   # 置信度 (default=1.0)
    created_at: datetime


# ═══════════════════════════════════════════════════════════════════
# 4. DocImage — 文档图片表（可选）
# ═══════════════════════════════════════════════════════════════════

class DocImage:
    """
    文档内嵌图片及 LLM 生成的描述。

    ⚠️ 适配点：如果不需要图片功能，可跳过此表
    """
    __tablename__ = 'doc_images'

    id: int
    doc_id: int          # FK → doc_files.id
    image_index: int     # 图片在原文档中的序号 (从1开始)
    storage_path: str    # 存储路径
    caption: str         # LLM 生成的图片描述
    mime_type: str       # MIME 类型
    created_at: datetime


# ═══════════════════════════════════════════════════════════════════
# 5. DocFile — 文档元信息表
# ═══════════════════════════════════════════════════════════════════

class DocFile:
    """
    上传的文档文件元信息。

    ⚠️ 适配点：根据新项目的文件管理需求调整字段
    """
    __tablename__ = 'doc_files'

    id: int
    original_name: str   # 原始文件名
    storage_path: str    # 存储路径
    mime_type: str       # MIME 类型
    status: str          # pending|processing|completed|failed|interrupted
    analyze_stage: str   # 当前分析阶段
    analyze_progress_current: int
    analyze_progress_total: int
    project_id: int      # 所属项目
    tags: str            # 文档级标签
    created_at: datetime
