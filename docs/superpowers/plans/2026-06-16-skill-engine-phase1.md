# Skill Engine Phase 1 — 最小闭环实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Prism 构建 Skill Engine 最小闭环：用户可触发多步骤任务（检索→总结→写 Wiki），每步有状态记录、失败可见、结果可回放。

**Architecture:** 在现有 `engine/app/` + `backend/app/` 结构上扩展，新增 `engine/app/skill/` 模块承载 Skill Engine 核心逻辑，新增 `backend/app/models/task.py` 承载 Task/TaskStep/Artifact 数据模型。工具层统一到 `engine/app/tools/`，通过 `ToolRegistry` 注册和发现。Phase 1 只做预设 Skill 执行，暂不引入 Auto Planner。

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy (MySQL), Pydantic v2, LangChain (现有 agent loop), YAML (Skill 模板)

---

## 目录改造方案

### 改造前（当前结构）

```
engine/app/
  agent/
    runner.py            # LangChainAgentRunner
    events.py
    prompts.py
    rag/agentic.py
    tools/               # 4 个内置工具，BUILTIN_REGISTRY
      base.py, clarify.py, datetime.py, knowledge.py, web_search.py
  api/chat.py, ingest.py, wiki.py
  chat/answer.py
  retrieval/...
  ...
backend/app/
  models/
    chat.py, knowledge_item.py, wiki.py
  schemas/...
  api/chat.py, knowledge.py, upload.py, wiki.py
  services/  (不存在——当前无 service 层)
  ...
```

### 改造后（Phase 1 新增）

```
engine/app/
  skill/                              # NEW: Skill Engine 核心模块
    __init__.py                       # 导出 public API
    engine.py                         # SkillEngine 主入口：组装并运行 skill
    router.py                         # TaskRouter：判断请求是否进入 Skill 模式
    matcher.py                        # SkillMatcher：关键词 + 语义匹配预设 Skill
    parser.py                         # SkillParser：解析 YAML/JSON 模板为 SkillDefinition
    executor.py                       # StepExecutor：逐步执行、状态记录、重试
    artifact_store.py                 # ArtifactStore：步骤产物落盘与查询
    templates/                        # NEW: 预设 Skill 模板
      research_and_wiki.yaml          # "检索→总结→写 Wiki" 示例模板
  tools/                              # NEW: 统一工具层（从 agent/tools/ 迁出并扩展）
    __init__.py                       # ToolRegistry 单例 + register_tool
    base.py                           # ToolSpec、ToolResult、ToolContext 数据模型
    knowledge_search.py               # MOVED: 从 agent/tools/knowledge.py，保持兼容
    wiki_upsert.py                    # NEW: 写入/更新 Wiki 文档
    mcp_tool_call.py                  # NEW (Phase 1 stub): 统一 MCP 工具调用入口
    clarify.py                        # MOVED: 从 agent/tools/clarify.py
    datetime.py                       # MOVED: 从 agent/tools/datetime.py
    web_search.py                     # MOVED: 从 agent/tools/web_search.py (保持 disabled)
  agent/
    runner.py                         # MODIFY: 集成 SkillEngine，LLM 可调用 execute_skill
    tools/                            # MODIFY: 改为 re-export engine/app/tools/
      __init__.py                     # from engine.app.tools import ...
    ...

backend/app/
  models/
    task.py                           # NEW: Task、TaskStep、Artifact 三张表
    mcp.py                            # NEW: McpServerConfig 表（预留 Phase 3）
  schemas/
    task.py                           # NEW: TaskCreate、TaskOut、TaskStepOut、ArtifactOut
  services/                           # NEW: service 层目录
    __init__.py
    task_service.py                   # NEW: Task 创建、状态更新、步骤查询
  api/
    tasks.py                          # NEW: /api/v1/tasks CRUD + 步骤状态查询
    __init__.py                       # MODIFY: 注册 tasks router
  utils/
    auto_migrate.py                   # MODIFY: 添加新表的 CREATE TABLE IF NOT EXISTS
```

### 关键设计决策

1. **工具层统一到 `engine/app/tools/`**：当前工具散落在 `engine/app/agent/tools/`，语义上工具不属于 agent 内部，应为独立模块。原路径保留兼容 re-export，不破坏现有 agent runner 的 import。
2. **Skill Engine 独立于 Agent Runner**：`engine/app/skill/` 是独立的执行引擎，`runner.py` 通过 `execute_skill` 工具将多步骤任务委托给 SkillEngine。不做"大一统 agent"。
3. **所有工具输出 `ToolResult`**：统一契约，包含 `success`、`data`、`artifacts`、`error`、`next_hints`，Planner 和 Executor 只依赖这个接口。
4. **Phase 1 只做预设 Skill**：Auto Planner (Phase 2) 的目录和接口预留，但不实现。

---

## 数据模型 (ER)

```
Task (task)
  - id: CHAR(36) PK
  - user_id: VARCHAR(128)
  - mode: VARCHAR(16)         # chat | rag | skill
  - title: VARCHAR(256)
  - original_input: TEXT
  - status: VARCHAR(16)       # queued | running | paused | failed | completed
  - route_reason: VARCHAR(128)
  - skill_name: VARCHAR(128) NULL   # 匹配到的预设 skill 名
  - final_answer: TEXT NULL
  - created_at: DATETIME
  - updated_at: DATETIME

TaskStep (task_step)
  - id: CHAR(36) PK
  - task_id: CHAR(36) FK -> task.id
  - step_index: INT
  - step_name: VARCHAR(128)
  - step_type: VARCHAR(32)    # tool_call | llm_transform | retrieval | decision | human_approval | persist
  - tool_name: VARCHAR(128) NULL
  - input_payload: JSON
  - output_payload: JSON NULL
  - status: VARCHAR(16)       # queued | running | completed | failed | skipped
  - retry_count: INT DEFAULT 0
  - error_message: TEXT NULL
  - started_at: DATETIME NULL
  - finished_at: DATETIME NULL

Artifact (artifact)
  - id: CHAR(36) PK
  - task_id: CHAR(36) FK -> task.id
  - step_id: CHAR(36) FK NULL -> task_step.id
  - artifact_type: VARCHAR(32)  # json | markdown | image | text | wiki_draft
  - title: VARCHAR(256)
  - content: MEDIUMTEXT
  - metadata_json: JSON NULL
  - created_at: DATETIME
```

---

## Phase 1 实施任务

### Task 1: 数据模型与数据库迁移

**Files:**
- Create: `backend/app/models/task.py`
- Create: `backend/app/models/mcp.py` (Phase 3 预留)
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/utils/auto_migrate.py`

- [ ] **Step 1: 编写 Task/TaskStep/Artifact SQLAlchemy 模型**

在 `backend/app/models/task.py` 新建：

```python
"""Skill Engine task, step, and artifact models."""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from backend.app.database import Base


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Task(Base):
    __tablename__ = "task"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    user_id = Column(String(128), nullable=False, default="default-user")
    mode = Column(String(16), nullable=False, default="skill")
    title = Column(String(256), nullable=True)
    original_input = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="queued")
    route_reason = Column(String(128), nullable=True)
    skill_name = Column(String(128), nullable=True)
    final_answer = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    steps = relationship("TaskStep", back_populates="task", order_by="TaskStep.step_index")
    artifacts = relationship("Artifact", back_populates="task")


class TaskStep(Base):
    __tablename__ = "task_step"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    task_id = Column(String(36), ForeignKey("task.id"), nullable=False)
    step_index = Column(Integer, nullable=False)
    step_name = Column(String(128), nullable=False)
    step_type = Column(String(32), nullable=False)
    tool_name = Column(String(128), nullable=True)
    input_payload = Column(JSON, nullable=True)
    output_payload = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False, default="queued")
    retry_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    task = relationship("Task", back_populates="steps")


class Artifact(Base):
    __tablename__ = "artifact"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    task_id = Column(String(36), ForeignKey("task.id"), nullable=False)
    step_id = Column(String(36), ForeignKey("task_step.id"), nullable=True)
    artifact_type = Column(String(32), nullable=False)
    title = Column(String(256), nullable=True)
    content = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("Task", back_populates="artifacts")
```

在 `backend/app/models/mcp.py` 新建（Phase 3 预留，Phase 1 只建表）：

```python
"""MCP server configuration model (reserved for Phase 3)."""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Text
from backend.app.database import Base


class McpServerConfig(Base):
    __tablename__ = "mcp_server_config"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(128), nullable=False)
    transport_type = Column(String(32), nullable=False, default="sse")
    server_url = Column(String(512), nullable=False)
    auth_type = Column(String(32), nullable=True)
    auth_config_json = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 2: 更新 models/__init__.py 导出**

```python
# 在现有 import 之后追加
from backend.app.models.task import Task, TaskStep, Artifact
from backend.app.models.mcp import McpServerConfig

__all__ = [
    # ... existing exports ...
    "Task",
    "TaskStep",
    "Artifact",
    "McpServerConfig",
]
```

- [ ] **Step 3: 更新 auto_migrate.py 添加新表**

在 `backend/app/utils/auto_migrate.py` 的 `AUTO_TABLES` 或等效位置，确保新模型被 `Base.metadata.create_all` 覆盖——如果现有机制已使用 `Base.metadata.create_all(bind=engine)`，则无需额外改动；搜索确认后若需显式注册则追加。

- [ ] **Step 4: 运行迁移验证**

```bash
python -c "from backend.app.database import engine, Base; from backend.app.models import *; Base.metadata.create_all(bind=engine); print('OK')"
```

Expected: `OK`（表不存在则创建，已存在则跳过）

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/task.py backend/app/models/mcp.py backend/app/models/__init__.py backend/app/utils/auto_migrate.py
git commit -m "feat: add Task/TaskStep/Artifact/McpServerConfig models and migration"
```

---

### Task 2: ToolSpec/ToolResult 统一工具契约

**Files:**
- Create: `engine/app/tools/base.py`
- Create: `engine/app/tools/__init__.py`

- [ ] **Step 1: 编写 ToolSpec 和 ToolResult Pydantic 模型**

在 `engine/app/tools/base.py`：

```python
"""Unified tool contracts for the Skill Engine."""
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ToolSpec:
    """Immutable specification for a registered tool."""
    name: str
    category: str                          # knowledge | mcp | multimodal | builtin
    description: str
    input_schema: dict                      # JSON Schema for input params
    output_schema: dict                     # JSON Schema for output
    require_approval: bool = False
    handler: Optional[Callable] = None      # async callable(ctx, **params) -> ToolResult


@dataclass
class ToolResult:
    """Unified return type for all tool invocations."""
    success: bool
    data: dict = field(default_factory=dict)
    artifacts: list[dict] = field(default_factory=list)
    error: Optional[str] = None
    next_hints: list[str] = field(default_factory=list)

    @classmethod
    def ok(cls, data: dict, artifacts: list[dict] = None, next_hints: list[str] = None) -> "ToolResult":
        return cls(success=True, data=data, artifacts=artifacts or [], next_hints=next_hints or [])

    @classmethod
    def fail(cls, error: str, data: dict = None) -> "ToolResult":
        return cls(success=False, data=data or {}, error=error)


@dataclass
class ToolContext:
    """Context passed to tool handlers at invocation time."""
    task_id: Optional[str] = None
    step_id: Optional[str] = None
    user_id: str = "default-user"
    db_session: Any = None                  # SQLAlchemy session for tools that need DB access
    extra: dict = field(default_factory=dict)
```

- [ ] **Step 2: 编写 tools/__init__.py 注册表**

在 `engine/app/tools/__init__.py`：

```python
"""Unified tool registry for the Skill Engine."""
from typing import Dict, List, Optional
from engine.app.tools.base import ToolSpec, ToolResult, ToolContext


_registry: Dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> ToolSpec:
    """Register a tool spec. Raises ValueError on duplicate name."""
    if spec.name in _registry:
        raise ValueError(f"Tool '{spec.name}' is already registered.")
    _registry[spec.name] = spec
    return spec


def get(name: str) -> Optional[ToolSpec]:
    """Get a registered tool by name."""
    return _registry.get(name)


def list_all(category: Optional[str] = None) -> List[ToolSpec]:
    """List registered tools, optionally filtered by category."""
    specs = list(_registry.values())
    if category:
        specs = [s for s in specs if s.category == category]
    return specs


def list_names(category: Optional[str] = None) -> List[str]:
    """List registered tool names, optionally filtered by category."""
    return [s.name for s in list_all(category)]


def clear():
    """Clear all registered tools (for testing)."""
    _registry.clear()
```

- [ ] **Step 3: Commit**

```bash
git add engine/app/tools/
git commit -m "feat: add ToolSpec/ToolResult contracts and ToolRegistry"
```

---

### Task 3: 迁移现有工具到统一注册表

**Files:**
- Modify: `engine/app/agent/tools/__init__.py` (改为 re-export)
- Modify: `engine/app/tools/__init__.py` (注册现有工具)
- Create: `engine/app/tools/knowledge_search.py`
- Create: `engine/app/tools/clarify.py`
- Create: `engine/app/tools/datetime.py`
- Create: `engine/app/tools/web_search.py`

- [ ] **Step 1: 注册现有 knowledge_search 工具**

在 `engine/app/tools/knowledge_search.py`：

```python
"""Knowledge search tool — searches Prism's indexed knowledge via RAG."""
from engine.app.tools.base import ToolSpec, ToolResult, ToolContext


async def _handler(ctx: ToolContext, query: str, top_k: int = 5) -> ToolResult:
    """Invoke hybrid RAG search."""
    from engine.app.agent.rag.agentic import AgenticRagRunner
    rag = AgenticRagRunner()
    result = await rag.run(query)
    return ToolResult.ok(
        data={"answer": result.evidence, "sources": result.sources, "status": result.status},
        artifacts=[{"type": "search_result", "query": query, "answer": result.evidence}],
    )


knowledge_search_spec = ToolSpec(
    name="knowledge_search",
    category="knowledge",
    description="在 Prism 索引知识库中执行混合语义+关键词搜索，返回相关片段和来源。",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索查询"},
            "top_k": {"type": "integer", "default": 5, "description": "返回结果数"},
        },
        "required": ["query"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "sources": {"type": "array"},
            "status": {"type": "string"},
        },
    },
    handler=_handler,
)
```

用同样的模式在 `engine/app/tools/clarify.py`、`datetime.py`、`web_search.py` 中创建包装（复用现有逻辑，封装为 `async def _handler(ctx, **params) -> ToolResult`）。

- [ ] **Step 2: 在 tools/__init__.py 中注册所有工具**

```python
# 在 engine/app/tools/__init__.py 末尾追加：
from engine.app.tools.knowledge_search import knowledge_search_spec
from engine.app.tools.clarify import clarify_spec
from engine.app.tools.datetime import datetime_spec
from engine.app.tools.web_search import web_search_spec

for spec in [knowledge_search_spec, clarify_spec, datetime_spec, web_search_spec]:
    try:
        register(spec)
    except ValueError:
        pass  # 测试环境可能重复导入
```

- [ ] **Step 3: 更新 agent/tools/__init__.py 为 re-export**

```python
"""Re-export unified tool layer for backward compatibility with existing agent runner."""
from engine.app.tools import list_all, get as get_tool
from engine.app.tools.base import ToolContext, ToolSpec, ToolResult

# 保持原 BUILTIN_REGISTRY 兼容性
BUILTIN_REGISTRY = {s.name: s for s in list_all()}

# 保持原 build_enabled_tools 可用
def build_enabled_tools(ctx, overrides=None):
    from engine.app.tools import list_all as _list
    from langchain_core.tools import StructuredTool
    tools = []
    for spec in _list():
        if overrides and spec.name in overrides and not overrides[spec.name]:
            continue
        if spec.handler:
            t = StructuredTool.from_function(
                coroutine=spec.handler,
                name=spec.name,
                description=spec.description,
            )
            tools.append(t)
    return tools
```

- [ ] **Step 4: 验证现有 agent runner 不受影响**

```bash
cd engine && python -c "from engine.app.agents.tools import build_enabled_tools, BUILTIN_REGISTRY; print(len(BUILTIN_REGISTRY), 'tools registered')"
```

Expected: `4 tools registered`

- [ ] **Step 5: Commit**

```bash
git add engine/app/tools/ engine/app/agent/tools/
git commit -m "refactor: migrate tools to unified registry under engine/app/tools/"
```

---

### Task 4: Skill 模板格式与解析器

**Files:**
- Create: `engine/app/skill/__init__.py`
- Create: `engine/app/skill/parser.py`
- Create: `engine/app/skill/templates/research_and_wiki.yaml`

- [ ] **Step 1: 定义 SkillDefinition 和 StepDefinition 数据类**

在 `engine/app/skill/parser.py`：

```python
"""Skill template parser — YAML/JSON → SkillDefinition."""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import yaml
from pathlib import Path


@dataclass
class StepDefinition:
    """One step in a skill template."""
    name: str
    step_type: str          # tool_call | llm_transform | retrieval | decision | human_approval | persist
    tool_name: Optional[str] = None
    input_type: str = "original"     # original | previous | step_ref
    input_step: Optional[int] = None # 当 input_type=step_ref 时引用
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillDefinition:
    """Parsed skill template ready for execution."""
    name: str
    description: str
    keywords: List[str] = field(default_factory=list)
    scenario: str = ""
    steps: List[StepDefinition] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str) -> "SkillDefinition":
        """Parse a YAML skill template file."""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls._from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "SkillDefinition":
        """Parse a dict into SkillDefinition (used by from_yaml and API)."""
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict) -> "SkillDefinition":
        steps = []
        for s in data.get("steps", []):
            steps.append(StepDefinition(
                name=s["name"],
                step_type=s.get("step_type", "tool_call"),
                tool_name=s.get("tool_name"),
                input_type=s.get("input_type", "original"),
                input_step=s.get("input_step"),
                params=s.get("params", {}),
            ))
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            keywords=data.get("keywords", []),
            scenario=data.get("scenario", ""),
            steps=steps,
        )


def load_skills_from_dir(dir_path: str) -> List[SkillDefinition]:
    """Load all .yaml/.yml skill templates from a directory."""
    skills = []
    for p in Path(dir_path).glob("*"):
        if p.suffix in (".yaml", ".yml"):
            skills.append(SkillDefinition.from_yaml(str(p)))
    return skills
```

- [ ] **Step 2: 编写预设 Skill 模板**

在 `engine/app/skill/templates/research_and_wiki.yaml`：

```yaml
name: research_and_wiki
description: 收集某个主题的信息，提炼结论并沉淀为 Wiki
keywords:
  - 调研
  - 总结
  - wiki
  - 整理
  - 分析
scenario: |
  适用于用户希望收集资料、整理结论并沉淀到知识库的场景。
steps:
  - name: 检索已有知识
    step_type: retrieval
    tool_name: knowledge_search
    input_type: original
    params:
      query: "{{task}}"
      top_k: 5

  - name: 归纳结构化要点
    step_type: llm_transform
    input_type: previous
    params:
      schema: topic_summary_v1
      instruction: "将上一步的检索结果归纳为 3-5 个结构化要点，每个要点包含标题和内容。"

  - name: 生成 Wiki 草稿
    step_type: llm_transform
    input_type: previous
    params:
      schema: wiki_article_v1
      instruction: "将结构化要点整理为一篇 Wiki 格式的知识文章，包含概述、要点详述和总结。"

  - name: 保存 Wiki
    step_type: persist
    tool_name: wiki_upsert
    input_type: previous
    params:
      title: "{{task}}"
```

- [ ] **Step 3: 编写单元测试验证解析**

```bash
# 在 engine/tests/ 下创建 test_skill_parser.py
cd engine && python -c "
from engine.app.skill.parser import SkillDefinition
skill = SkillDefinition.from_yaml('engine/app/skill/templates/research_and_wiki.yaml')
assert skill.name == 'research_and_wiki'
assert len(skill.steps) == 4
assert skill.steps[0].tool_name == 'knowledge_search'
print('PASS')
"
```

Expected: `PASS`

- [ ] **Step 4: Commit**

```bash
git add engine/app/skill/__init__.py engine/app/skill/parser.py engine/app/skill/templates/
git commit -m "feat: add SkillDefinition parser and research_and_wiki template"
```

---

### Task 5: Skill Matcher（预设 Skill 匹配）

**Files:**
- Create: `engine/app/skill/matcher.py`

- [ ] **Step 1: 实现关键词 + LLM 语义匹配**

在 `engine/app/skill/matcher.py`：

```python
"""Skill matcher — matches user intent to a preset Skill template."""
from typing import List, Optional
from engine.app.skill.parser import SkillDefinition


class SkillMatcher:
    """Match user queries to skill templates by keyword overlap."""

    def __init__(self, skills: List[SkillDefinition]):
        self._skills = skills

    def match(self, user_input: str) -> Optional[SkillDefinition]:
        """Return the best matching skill, or None if no match."""
        best = None
        best_score = 0
        user_lower = user_input.lower()

        for skill in self._skills:
            score = sum(1 for kw in skill.keywords if kw in user_lower)
            if score > best_score:
                best_score = score
                best = skill

        if best_score > 0:
            return best
        return None

    def has_match(self, user_input: str) -> bool:
        return self.match(user_input) is not None
```

- [ ] **Step 2: 验证匹配逻辑**

```bash
cd engine && python -c "
from engine.app.skill.parser import SkillDefinition
from engine.app.skill.matcher import SkillMatcher
import yaml, pathlib

skills = []
for p in pathlib.Path('engine/app/skill/templates').glob('*.yaml'):
    skills.append(SkillDefinition.from_yaml(str(p)))

m = SkillMatcher(skills)
assert m.match('帮我调研一下量子计算') is not None      # '调研' matches
assert m.match('你好') is None                           # no keyword
assert m.has_match('把这个整理成 wiki')
print('PASS')
"
```

Expected: `PASS`

- [ ] **Step 3: Commit**

```bash
git add engine/app/skill/matcher.py
git commit -m "feat: add SkillMatcher for preset skill keyword matching"
```

---

### Task 6: Artifact Store（产物持久化）

**Files:**
- Create: `engine/app/skill/artifact_store.py`
- Modify: `engine/app/skill/__init__.py` (if needed)

- [ ] **Step 1: 实现 ArtifactStore**

在 `engine/app/skill/artifact_store.py`：

```python
"""Artifact store — persists step artifacts to DB and retrieves them."""
from typing import List, Optional
from sqlalchemy.orm import Session
from backend.app.models.task import Artifact
import uuid


class ArtifactStore:
    """CRUD wrapper for Artifact model."""

    def __init__(self, db: Session):
        self._db = db

    def save(self, task_id: str, step_id: Optional[str],
             artifact_type: str, title: str, content: str,
             metadata: dict = None) -> Artifact:
        """Persist a new artifact."""
        a = Artifact(
            id=str(uuid.uuid4()),
            task_id=task_id,
            step_id=step_id,
            artifact_type=artifact_type,
            title=title,
            content=content,
            metadata_json=metadata or {},
        )
        self._db.add(a)
        self._db.commit()
        return a

    def list_by_task(self, task_id: str) -> List[Artifact]:
        """List all artifacts for a task, oldest first."""
        return (
            self._db.query(Artifact)
            .filter(Artifact.task_id == task_id)
            .order_by(Artifact.created_at.asc())
            .all()
        )

    def get(self, artifact_id: str) -> Optional[Artifact]:
        return self._db.query(Artifact).filter(Artifact.id == artifact_id).first()
```

- [ ] **Step 2: 验证写入/读取**

```bash
cd backend && python -c "
from backend.app.database import SessionLocal
from engine.app.skill.artifact_store import ArtifactStore
db = SessionLocal()
store = ArtifactStore(db)
# 需要先有 task，此处只验证导入正常
print('ArtifactStore imported OK')
db.close()
"
```

- [ ] **Step 3: Commit**

```bash
git add engine/app/skill/artifact_store.py
git commit -m "feat: add ArtifactStore for step artifact persistence"
```

---

### Task 7: Step Executor（步骤执行器）

**Files:**
- Create: `engine/app/skill/executor.py`

- [ ] **Step 1: 实现 StepExecutor 核心循环**

在 `engine/app/skill/executor.py`：

```python
"""Step executor — executes skill steps sequentially with state tracking."""
import asyncio
import time
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from engine.app.skill.parser import SkillDefinition, StepDefinition
from engine.app.tools import get as get_tool
from engine.app.tools.base import ToolResult, ToolContext
from engine.app.skill.artifact_store import ArtifactStore
from backend.app.models.task import Task, TaskStep
import uuid


class StepExecutor:
    """Executes a SkillDefinition step by step, recording state to DB."""

    MAX_RETRIES = 2

    def __init__(self, db: Session, llm_client=None):
        self._db = db
        self._llm = llm_client
        self._artifacts = ArtifactStore(db)

    async def execute(self, task: Task, skill: SkillDefinition) -> str:
        """Execute all steps of a skill. Returns the final answer text."""
        step_results: Dict[int, ToolResult] = {}

        for i, step_def in enumerate(skill.steps):
            step_record = self._create_step_record(task.id, i + 1, step_def)
            step_record.status = "running"
            step_record.started_at = datetime.utcnow()
            self._db.commit()

            result = None
            for retry in range(self.MAX_RETRIES + 1):
                try:
                    result = await self._execute_one(step_def, task, step_results)
                    break
                except Exception as e:
                    if retry < self.MAX_RETRIES:
                        step_record.retry_count = retry + 1
                        self._db.commit()
                        await asyncio.sleep(1.0)
                    else:
                        step_record.status = "failed"
                        step_record.error_message = str(e)
                        step_record.finished_at = datetime.utcnow()
                        self._db.commit()
                        raise

            step_record.output_payload = {"data": result.data, "success": result.success}
            step_record.status = "completed" if result.success else "failed"
            step_record.finished_at = datetime.utcnow()
            self._db.commit()

            step_results[i + 1] = result

            if result.artifacts:
                for a in result.artifacts:
                    self._artifacts.save(
                        task_id=task.id,
                        step_id=step_record.id,
                        artifact_type=a.get("type", "json"),
                        title=a.get("title", step_def.name),
                        content=str(a),
                        metadata=a,
                    )

            if step_def.step_type == "human_approval":
                return "⏸️ 任务需要人工确认后继续。"

        final = step_results.get(len(skill.steps))
        return final.data.get("content", str(final.data)) if final else ""

    async def _execute_one(self, step_def: StepDefinition, task: Task,
                           previous_results: Dict[int, ToolResult]) -> ToolResult:
        """Execute a single step, dispatching by step_type."""
        if step_def.step_type in ("tool_call", "retrieval", "persist"):
            tool = get_tool(step_def.tool_name)
            if not tool or not tool.handler:
                return ToolResult.fail(f"Tool '{step_def.tool_name}' not found")
            params = self._resolve_params(step_def.params, task, previous_results)
            ctx = ToolContext(task_id=task.id, user_id=task.user_id, db_session=self._db)
            return await tool.handler(ctx, **params)

        elif step_def.step_type == "llm_transform":
            return await self._execute_llm_transform(step_def, task, previous_results)

        elif step_def.step_type == "decision":
            return ToolResult.ok(data={"decision": "continue"})

        elif step_def.step_type == "human_approval":
            return ToolResult.ok(data={"status": "awaiting_approval"}, next_hints=["waiting_for_user"])

        return ToolResult.fail(f"Unknown step_type: {step_def.step_type}")

    async def _execute_llm_transform(self, step_def: StepDefinition, task: Task,
                                     previous_results: Dict[int, ToolResult]) -> ToolResult:
        """Use LLM to transform previous step output."""
        if not self._llm:
            # Fallback: if no LLM client, pass through previous result
            prev = previous_results.get(step_def.input_step or len(previous_results))
            return ToolResult.ok(data=prev.data if prev else {})

        prev = previous_results.get(step_def.input_step or len(previous_results))
        prev_text = str(prev.data) if prev else ""

        instruction = step_def.params.get("instruction", "Summarize the following:")
        prompt = f"{instruction}\n\nInput:\n{prev_text}"

        # Use the LLM client (DeepSeek-compat) to transform
        response = await self._llm.chat(prompt)
        content = response.get("content", response) if isinstance(response, dict) else str(response)

        return ToolResult.ok(
            data={"content": content},
            artifacts=[{"type": "llm_transform", "title": step_def.name, "content": content}],
        )

    def _resolve_params(self, params: dict, task: Task,
                        previous_results: Dict[int, ToolResult]) -> dict:
        """Resolve {{task}} and {{stepN.field}} references in params."""
        resolved = {}
        for k, v in params.items():
            if isinstance(v, str):
                v = v.replace("{{task}}", task.original_input)
                for step_num, result in previous_results.items():
                    v = v.replace(f"{{{{step{step_num}.data}}}}", str(result.data))
            resolved[k] = v
        return resolved

    def _create_step_record(self, task_id: str, index: int, step_def: StepDefinition) -> TaskStep:
        step = TaskStep(
            id=str(uuid.uuid4()),
            task_id=task_id,
            step_index=index,
            step_name=step_def.name,
            step_type=step_def.step_type,
            tool_name=step_def.tool_name,
            input_payload=step_def.params,
            status="queued",
        )
        self._db.add(step)
        self._db.commit()
        return step
```

- [ ] **Step 2: Commit**

```bash
git add engine/app/skill/executor.py
git commit -m "feat: add StepExecutor with state tracking and retry"
```

---

### Task 8: Skill Engine 主入口

**Files:**
- Create: `engine/app/skill/engine.py`
- Modify: `engine/app/skill/__init__.py`

- [ ] **Step 1: 实现 SkillEngine 组装类**

在 `engine/app/skill/engine.py`：

```python
"""Skill Engine main entry point — orchestrates matching → execution → persistence."""
from typing import Optional, List, AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from sqlalchemy.orm import Session

from engine.app.skill.parser import SkillDefinition, load_skills_from_dir
from engine.app.skill.matcher import SkillMatcher
from engine.app.skill.executor import StepExecutor
from engine.app.skill.artifact_store import ArtifactStore
from backend.app.models.task import Task
import uuid
from datetime import datetime


class EngineMode(Enum):
    CHAT = "chat"
    RAG = "rag"
    SKILL = "skill"


@dataclass
class SkillEngineResult:
    mode: EngineMode
    task_id: Optional[str] = None
    skill_name: Optional[str] = None
    final_answer: str = ""
    artifacts: list = field(default_factory=list)


class SkillEngine:
    """Top-level orchestrator for the Skill Engine.

    Usage:
        engine = SkillEngine(db_session, llm_client, skills_dir="engine/app/skill/templates")
        result = await engine.process(user_input="帮我调研量子计算并沉淀为 wiki")
    """

    def __init__(self, db: Session, llm_client=None, skills_dir: str = None):
        self._db = db
        self._llm = llm_client
        self._artifacts = ArtifactStore(db)
        self._skills: List[SkillDefinition] = []
        self._matcher: Optional[SkillMatcher] = None

        if skills_dir:
            self._skills = load_skills_from_dir(skills_dir)
            self._matcher = SkillMatcher(self._skills)

    def route(self, user_input: str) -> EngineMode:
        """Classify user input: chat, rag, or skill."""
        skill_keywords = ["帮我", "整理", "分析", "生成", "调用", "抓取", "更新", "同步", "调研", "总结", "wiki", "沉淀"]
        has_skill = any(kw in user_input for kw in skill_keywords)
        if has_skill and self._matcher and self._matcher.has_match(user_input):
            return EngineMode.SKILL

        if "?" in user_input or "?" in user_input or len(user_input) > 20:
            return EngineMode.RAG

        return EngineMode.CHAT

    async def process(self, user_input: str) -> SkillEngineResult:
        """Route, match, and execute."""
        mode = self.route(user_input)

        if mode != EngineMode.SKILL:
            return SkillEngineResult(mode=mode, final_answer="")

        skill = self._matcher.match(user_input)
        if not skill:
            return SkillEngineResult(mode=EngineMode.RAG, final_answer="")

        task = self._create_task(user_input, skill)
        executor = StepExecutor(self._db, self._llm)

        try:
            task.status = "running"
            self._db.commit()

            final = await executor.execute(task, skill)
            task.status = "completed"
            task.final_answer = final
            self._db.commit()

            artifacts = self._artifacts.list_by_task(task.id)
            return SkillEngineResult(
                mode=EngineMode.SKILL,
                task_id=task.id,
                skill_name=skill.name,
                final_answer=final,
                artifacts=[{"id": a.id, "type": a.artifact_type, "title": a.title} for a in artifacts],
            )
        except Exception as e:
            task.status = "failed"
            task.final_answer = f"执行失败: {e}"
            self._db.commit()
            return SkillEngineResult(mode=EngineMode.SKILL, task_id=task.id, final_answer=task.final_answer)

    def _create_task(self, user_input: str, skill: SkillDefinition) -> Task:
        task = Task(
            id=str(uuid.uuid4()),
            user_id="default-user",
            mode="skill",
            title=skill.description[:256],
            original_input=user_input,
            status="queued",
            route_reason=f"matched preset skill: {skill.name}",
            skill_name=skill.name,
        )
        self._db.add(task)
        self._db.commit()
        return task
```

- [ ] **Step 2: 更新 skill/__init__.py**

```python
"""Skill Engine — task planning and execution for personal AI assistant."""
from engine.app.skill.engine import SkillEngine, SkillEngineResult, EngineMode
from engine.app.skill.parser import SkillDefinition, StepDefinition, load_skills_from_dir
from engine.app.skill.matcher import SkillMatcher
from engine.app.skill.executor import StepExecutor
from engine.app.skill.artifact_store import ArtifactStore

__all__ = [
    "SkillEngine",
    "SkillEngineResult",
    "EngineMode",
    "SkillDefinition",
    "StepDefinition",
    "SkillMatcher",
    "StepExecutor",
    "ArtifactStore",
    "load_skills_from_dir",
]
```

- [ ] **Step 3: Commit**

```bash
git add engine/app/skill/engine.py engine/app/skill/__init__.py
git commit -m "feat: add SkillEngine main entry point with routing and execution"
```

---

### Task 9: wiki_upsert 工具实现

**Files:**
- Create: `engine/app/tools/wiki_upsert.py`
- Modify: `engine/app/tools/__init__.py` (注册)

- [ ] **Step 1: 实现 wiki_upsert 工具**

在 `engine/app/tools/wiki_upsert.py`：

```python
"""Wiki upsert tool — creates or updates a Wiki document from task output."""
from engine.app.tools.base import ToolSpec, ToolResult, ToolContext
from backend.app.models.wiki import WikiDocument
import uuid


async def _handler(ctx: ToolContext, title: str, content: str, tags: list = None) -> ToolResult:
    """Create a new Wiki document draft from task output."""
    db = ctx.db_session
    if not db:
        return ToolResult.fail("No database session available")

    doc = WikiDocument(
        id=str(uuid.uuid4()),
        title=title,
        content=content,
        status="draft",
        user_id=ctx.user_id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return ToolResult.ok(
        data={"id": doc.id, "title": doc.title, "status": doc.status},
        artifacts=[{"type": "wiki_draft", "id": doc.id, "title": title}],
        next_hints=["wiki document created, ready for review"],
    )


wiki_upsert_spec = ToolSpec(
    name="wiki_upsert",
    category="knowledge",
    description="将任务结果保存为 Wiki 知识文档草稿，供后续编辑和完善。",
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Wiki 文档标题"},
            "content": {"type": "string", "description": "Markdown 格式的文档内容"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表"},
        },
        "required": ["title", "content"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "title": {"type": "string"},
            "status": {"type": "string"},
        },
    },
    handler=_handler,
)
```

- [ ] **Step 2: 注册 wiki_upsert 工具**

在 `engine/app/tools/__init__.py` 追加：

```python
from engine.app.tools.wiki_upsert import wiki_upsert_spec
try:
    register(wiki_upsert_spec)
except ValueError:
    pass
```

- [ ] **Step 3: Commit**

```bash
git add engine/app/tools/wiki_upsert.py engine/app/tools/__init__.py
git commit -m "feat: add wiki_upsert tool for persisting task results as Wiki documents"
```

---

### Task 10: mcp_tool_call 工具 (Phase 1 Stub)

**Files:**
- Create: `engine/app/tools/mcp_tool_call.py`
- Modify: `engine/app/tools/__init__.py` (注册)

- [ ] **Step 1: 实现 MCP 调用 stub**

在 `engine/app/tools/mcp_tool_call.py`：

```python
"""MCP tool call — unified entry point for MCP server tools (Phase 1 stub)."""
from engine.app.tools.base import ToolSpec, ToolResult, ToolContext


async def _handler(ctx: ToolContext, server: str, tool_name: str, arguments: dict = None) -> ToolResult:
    """Phase 1 stub: MCP integration is not yet implemented.
    Returns a clear message so the planner knows this capability is pending.
    """
    return ToolResult(
        success=False,
        data={},
        error=f"MCP 工具调用尚未实现 (Phase 3)。请求: server={server}, tool={tool_name}",
        next_hints=["MCP integration is planned for Phase 3"],
    )


mcp_tool_call_spec = ToolSpec(
    name="mcp_tool_call",
    category="mcp",
    description="调用外部 MCP (Model Context Protocol) 服务器的工具。Phase 1: 占位，尚未实现。",
    input_schema={
        "type": "object",
        "properties": {
            "server": {"type": "string", "description": "MCP server 名称"},
            "tool_name": {"type": "string", "description": "要调用的工具名称"},
            "arguments": {"type": "object", "description": "工具参数"},
        },
        "required": ["server", "tool_name"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "result": {"type": "string"},
        },
    },
    handler=_handler,
)
```

- [ ] **Step 2: 注册 mcp_tool_call**

在 `engine/app/tools/__init__.py` 追加：

```python
from engine.app.tools.mcp_tool_call import mcp_tool_call_spec
try:
    register(mcp_tool_call_spec)
except ValueError:
    pass
```

- [ ] **Step 3: Commit**

```bash
git add engine/app/tools/mcp_tool_call.py engine/app/tools/__init__.py
git commit -m "feat: add mcp_tool_call stub for Phase 3 MCP integration"
```

---

### Task 11: Task API 路由与 Service 层

**Files:**
- Create: `backend/app/schemas/task.py`
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/task_service.py`
- Create: `backend/app/api/tasks.py`
- Modify: `backend/app/api/__init__.py`

- [ ] **Step 1: 编写 Task Pydantic Schemas**

在 `backend/app/schemas/task.py`：

```python
"""Pydantic schemas for Task, TaskStep, Artifact."""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class TaskStepOut(BaseModel):
    id: str
    step_index: int
    step_name: str
    step_type: str
    tool_name: Optional[str] = None
    status: str
    retry_count: int = 0
    error_message: Optional[str] = None
    input_payload: Optional[dict] = None
    output_payload: Optional[dict] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ArtifactOut(BaseModel):
    id: str
    artifact_type: str
    title: Optional[str] = None
    content: Optional[str] = None
    metadata_json: Optional[dict] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TaskOut(BaseModel):
    id: str
    user_id: str
    mode: str
    title: Optional[str] = None
    original_input: str
    status: str
    route_reason: Optional[str] = None
    skill_name: Optional[str] = None
    final_answer: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TaskDetailOut(TaskOut):
    steps: List[TaskStepOut] = []
    artifacts: List[ArtifactOut] = []


class TaskCreate(BaseModel):
    title: Optional[str] = None
    original_input: str = Field(..., min_length=1)
    mode: str = "skill"
```

- [ ] **Step 2: 编写 TaskService**

在 `backend/app/services/task_service.py`：

```python
"""Service layer for Task CRUD and query."""
from typing import List, Optional
from sqlalchemy.orm import Session, joinedload
from backend.app.models.task import Task, TaskStep, Artifact
import uuid
from datetime import datetime


class TaskService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, user_id: str, original_input: str, mode: str = "skill",
               title: str = None, route_reason: str = None) -> Task:
        task = Task(
            id=str(uuid.uuid4()),
            user_id=user_id,
            mode=mode,
            title=title,
            original_input=original_input,
            status="queued",
            route_reason=route_reason,
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def get(self, task_id: str) -> Optional[Task]:
        return self.db.query(Task).filter(Task.id == task_id).first()

    def get_with_steps(self, task_id: str) -> Optional[Task]:
        return (
            self.db.query(Task)
            .options(joinedload(Task.steps), joinedload(Task.artifacts))
            .filter(Task.id == task_id)
            .first()
        )

    def list_by_user(self, user_id: str = "default-user", limit: int = 20) -> List[Task]:
        return (
            self.db.query(Task)
            .filter(Task.user_id == user_id)
            .order_by(Task.created_at.desc())
            .limit(limit)
            .all()
        )

    def update_status(self, task_id: str, status: str, final_answer: str = None):
        task = self.get(task_id)
        if task:
            task.status = status
            if final_answer is not None:
                task.final_answer = final_answer
            task.updated_at = datetime.utcnow()
            self.db.commit()

    def delete(self, task_id: str) -> bool:
        task = self.get(task_id)
        if task:
            self.db.delete(task)
            self.db.commit()
            return True
        return False
```

- [ ] **Step 3: 编写 Task API 路由**

在 `backend/app/api/tasks.py`：

```python
"""Task management API routes."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.database import get_db
from backend.app.schemas.task import TaskOut, TaskDetailOut, TaskCreate
from backend.app.services.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/", response_model=TaskOut)
def create_task(body: TaskCreate, db: Session = Depends(get_db)):
    svc = TaskService(db)
    task = svc.create(
        user_id="default-user",
        original_input=body.original_input,
        mode=body.mode,
        title=body.title,
    )
    return task


@router.get("/", response_model=List[TaskOut])
def list_tasks(skip: int = 0, limit: int = 20, db: Session = Depends(get_db)):
    svc = TaskService(db)
    return svc.list_by_user(limit=limit)


@router.get("/{task_id}", response_model=TaskDetailOut)
def get_task(task_id: str, db: Session = Depends(get_db)):
    svc = TaskService(db)
    task = svc.get_with_steps(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.delete("/{task_id}")
def delete_task(task_id: str, db: Session = Depends(get_db)):
    svc = TaskService(db)
    if not svc.delete(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True}
```

- [ ] **Step 4: 注册路由**

在 `backend/app/api/__init__.py` 的 `register_routers` 函数中追加：

```python
from backend.app.api.tasks import router as tasks_router
app.include_router(tasks_router, prefix="/api/v1")
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/task.py backend/app/services/ backend/app/api/tasks.py backend/app/api/__init__.py
git commit -m "feat: add Task API routes and service layer"
```

---

### Task 12: 集成 SkillEngine 到现有 Agent Runner

**Files:**
- Modify: `engine/app/agent/runner.py`
- Modify: `engine/app/chat/answer.py`

- [ ] **Step 1: 在 Agent Runner 中集成 SkillEngine 路由**

在 `engine/app/agent/runner.py` 的 `stream` 方法中，在现有 casual chat / RAG 判断之前加入 SkillEngine 路由。修改思路：

```python
# 在 stream() 方法开头附近添加：
from engine.app.skill.engine import SkillEngine, EngineMode
from engine.app.llm.client import chat as llm_chat  # 现有 LLM client

skill_engine = SkillEngine(
    db=db_session,  # 需要传入 DB session
    llm_client=llm_chat,  # 复用现有 LLM client
    skills_dir="engine/app/skill/templates",
)

route_result = await skill_engine.process(query)

if route_result.mode == EngineMode.SKILL:
    # Skill Engine 已完成多步骤执行，返回结果
    yield events.token_event(route_result.final_answer)
    yield events.done_event(task_id=route_result.task_id)
    return
elif route_result.mode == EngineMode.CHAT:
    # 闲聊模式，跳过工具直接回复
    ...
# else: RAG 模式，走现有 agent loop
```

- [ ] **Step 2: 更新 chat/answer.py 传递 DB session**

在 `engine/app/chat/answer.py` 的 `answer_stream` 函数中，确保 `db_session` 可以传递到 `SkillEngine`。当前 `answer_stream` 不直接持有 DB session（DB 在 backend），需要增加依赖注入或从 `ToolContext` 获取。

Phase 1 简化方案：在 `answer_stream` 中创建独立的 DB session 用于 SkillEngine：

```python
from backend.app.database import SessionLocal

# 在 answer_stream 中
db = SessionLocal()
try:
    skill_engine = SkillEngine(db=db, llm_client=..., skills_dir=...)
    # ...
finally:
    db.close()
```

- [ ] **Step 3: 端到端验证脚本**

```python
# test_e2e_skill.py
import asyncio
from backend.app.database import SessionLocal
from engine.app.skill.engine import SkillEngine
from engine.app.llm.client import chat

async def main():
    db = SessionLocal()
    engine = SkillEngine(db=db, llm_client=chat, skills_dir="engine/app/skill/templates")
    result = await engine.process("帮我调研量子计算并整理为 wiki")
    print(f"Mode: {result.mode}")
    print(f"Task ID: {result.task_id}")
    print(f"Skill: {result.skill_name}")
    print(f"Answer: {result.final_answer[:200]}...")
    print(f"Artifacts: {result.artifacts}")
    db.close()

asyncio.run(main())
```

Expected: 能看到 `Mode: skill`、Task ID 非空、有 artifacts 输出。

- [ ] **Step 4: Commit**

```bash
git add engine/app/agent/runner.py engine/app/chat/answer.py
git commit -m "feat: integrate SkillEngine into agent runner and chat answer flow"
```

---

## Phase 2-4 预览（本次不实现）

| Phase | 内容 | 关键新文件 |
|-------|------|-----------|
| Phase 2: 自动规划 | Auto Planner, Plan Validator, 参数引用解析, 评估器与重试 | `engine/app/skill/auto_planner.py`, `evaluator.py` |
| Phase 3: MCP 增强 | MCP 注册中心, 工具动态发现, 多模态工具, 人工确认 | `engine/app/skill/mcp_registry.py`, `backend/app/services/mcp_service.py`, `engine/app/tools/image_understand.py` |
| Phase 4: 长期沉淀 | 自动任务摘要, Wiki 草稿生成, 记忆更新 | `engine/app/skill/sink.py`, `engine/app/tools/memory_upsert.py` |

---

## 验收清单 (Phase 1)

- [ ] 用户可以触发一个多步骤任务（检索→总结→写 Wiki）
- [ ] 系统能区分预设 Skill 和普通对话
- [ ] 所有步骤都有结构化状态记录（task_step 表可查）
- [ ] 工具调用统一经过 ToolRegistry
- [ ] wiki_upsert 可把结果沉淀为 Wiki 文档草稿
- [ ] mcp_tool_call stub 存在且返回明确的 "未实现" 消息
- [ ] 失败任务具备排错信息（error_message 字段）和重试路径（retry_count）
- [ ] Task API 可查询任务详情和步骤状态
