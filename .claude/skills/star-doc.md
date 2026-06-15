---
name: star-doc
description: After completing a bug fix or feature, generate a STAR-format markdown documentation file in docs/ with before/after metrics.
---

# STAR Documentation Skill

When the user says "写文档", "记录一下", "总结改动", "生成STAR文档", "落盘文档", or after a significant feature is completed, execute this skill.

## Steps

### 1. Collect Metrics

Run diagnostic commands to gather quantitative before/after data:

- For retrieval changes: `python -c "..." ` to measure vector/BM25 scores and latency
- For API changes: curl the relevant endpoints and measure response times
- For frontend changes: run `npx tsc --noEmit` to verify zero errors
- For database changes: query row counts, migration status
- For any change: `git diff --stat HEAD` to count changed files/lines

### 2. Write STAR Document

Save to `docs/YYYY-MM-DD-<feature-slug>.md` using this template:

```markdown
# [功能名称] - STAR 记录

> 日期: YYYY-MM-DD
> 作者: Claude

## Situation (情境)
[改动前的问题 — 用户遇到了什么困扰？系统行为是什么？]

## Task (任务)
[要解决的具体需求 — 用户想要什么？目标是什么？]

## Action (行动)

### 改动文件清单
| 文件 | 改动 | 说明 |
|------|------|------|

### 关键技术决策
[为什么这样做？有什么 trade-off？]

## Result (结果)

### 功能验证
| 功能 | 状态 | 说明 |
|------|------|------|

### 性能指标
| 指标 | 修复前 | 修复后 | 提升 |
|------|--------|--------|------|

### 构建状态
- TypeScript: X 错误
- Python 语法: 通过/失败
- 代码增量: +X / -Y 行

### 总结
[自由格式，总结本次改动的价值和后续方向]
```

### 3. Key Principles

- **Quantify everything**: Every metric must have before/after numbers, not just qualitative descriptions
- **Run actual diagnostics**: Don't guess numbers — execute commands to measure real values
- **Be honest about failures**: If something didn't improve (e.g., BM25 Chinese = 0), document it and note the path forward
- **Keep it focused**: One document per feature/bug-fix session, not per individual commit
