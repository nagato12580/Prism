# 文档知识抽取管线 Reference

此目录包含从 cake-master 项目提取的"文档→结构化知识"管线的设计文档和参考代码。

## 使用方式

在新项目中实现类似的文档知识抽取功能时：

1. 先阅读 `DESIGN.md` 了解整体架构和阶段划分
2. 参考 `code/` 目录下的代码实现细节
3. 每个代码文件头部和内部有 `⚠️ 适配点` 注释标注了需要调整的地方

## 核心设计决策（在新项目中应保持）

1. **三阶段管线**：Extract(LLM提取概念) → Merge(按group合并) → Write(LLM生成文章)
2. **LLM 同时输出概念+关系+分组**：一次调用完成提取+归类+关联
3. **group 字段作为合并信号**：LLM 自己判断哪些细粒度概念应该合并成一篇完整文章
4. **同名概念去重+描述拼接**：不同 chunk 提取到同名概念时合并描述
5. **断点续抽**：每阶段完成后持久化，中断后可从断点恢复

## 技术栈要求

| 组件 | 参考实现 | 可替换为 |
|------|---------|---------|
| LLM 调用 | httpx + OpenAI 兼容 API | 任何 OpenAI 兼容 SDK |
| 文本切块 | 自定义 section-boundary-aware chunker | LangChain, LlamaIndex |
| JSON 修复 | json_repair 库 | 自行处理 |
| 并发执行 | ThreadPoolExecutor | asyncio, Celery |
| 数据库 | MySQL + SQLAlchemy | PostgreSQL, MongoDB |
| 提示词管理 | DB 优先 fallback 到文件 | 配置文件/环境变量 |

## 适配新项目时的注意事项

- `extract_knowledge_points.txt` 提示词是整个管线的核心，必须根据新项目的文档领域重写规则
- chunk 大小(4000)和重叠(200)需要根据 LLM 上下文窗口调整
- 并发度(3线程)由 LLM API 的限流策略决定
- 概念的类型枚举(concept|technique|source|claim|artifact)和关系类型枚举需根据领域调整
- 同名去重的描述拼接策略可能不适用于所有场景
- `_strip_thinking` 函数用于清理 Qwen 等模型的 `<think>` 标签
