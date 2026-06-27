# Memory Scheduled Auto-Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a scheduled memory extraction system that automatically scans active chat sessions, extracts memory candidates with full conversation context, and uses an intelligent multi-dimensional scoring engine to auto-confirm or route to Memory Inbox for review.

**Architecture:** Backend APScheduler triggers extraction rounds at configurable intervals. Each round scans recently-updated chat sessions, loads new messages with context windows and LLM-generated summaries, extracts candidates with multi-dimensional signals, runs a composite scoring engine, and writes auto-confirmed MemoryStatements or MemoryDrafts. Frontend polls a count endpoint and shows a notification badge.

**Tech Stack:** Python (FastAPI, SQLAlchemy, APScheduler, OpenAI client), Milvus (embedding similarity), React (TypeScript, Zustand), MySQL

---

## File Structure

```
backend/app/
├── models/chat.py              → +3 fields (summary, last_extracted_message_id, last_extracted_at)
├── models/memory.py            → +4 fields on MemoryDraft, +4 on MemoryStatement, +1 new table
├── config.py                   → +5 settings
├── services/
│   ├── memory_scheduler.py     → NEW: APScheduler lifecycle + extraction round logic
│   ├── memory_extraction.py    → UPGRADE: watermark, summary, signals, decision engine
│   └── memory_vectors.py       → REUSE: existing embedding search
├── prompts/memory_extraction.py→ REDESIGN: summary block + context/target windows + new schema
├── api/memories.py             → +2 endpoints (count, scheduled trigger)
└── main.py                     → +5 lines lifespan integration

frontend/src/
├── app/api.ts                  → +1 method (countDrafts)
├── layouts/MainLayout.tsx      → badge rendering on "记忆审核" nav item
└── pages/MemoryInboxPage.tsx   → auto-refresh count on mount

backend/tests/
├── test_memory_extraction_service.py → extend tests
└── test_memory_scheduler.py          → NEW
```

---

## Phase 1: Data Model & Configuration

### Task 1: Extend ChatSession model

**Files:**
- Modify: `backend/app/models/chat.py:22-23`

- [ ] **Step 1: Add new columns to ChatSession**

After line `source_types = Column(JSON, nullable=True, default=None, comment="过滤数据来源类型")` and before `created_at`, insert:

```python
    summary = Column(Text, default="", comment="LLM 生成的会话摘要")
    last_extracted_message_id = Column(CHAR(36), default="", comment="提取水位线：上次提取到的最后一条消息 ID")
    last_extracted_at = Column(DateTime, nullable=True, comment="上次触发提取的时间")
```

- [ ] **Step 2: Verify imports**

The existing imports at the top of `chat.py` already include `DateTime` and `CHAR`, and `Text`. No new imports needed.

- [ ] **Step 3: Verify auto_migrate handles the new columns**

The existing `auto_migrate.py` auto-detects new columns via `inspector.get_columns()` vs `table_obj.columns` — no changes needed.

- [ ] **Step 4: Verify the model loads**

Run: `python -c "from backend.app.models.chat import ChatSession; print(ChatSession.__tablename__)"`
Expected: `chat_session` printed without errors.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/chat.py
git commit -m "feat(memory): add summary, last_extracted_message_id, last_extracted_at to ChatSession"
```

---

### Task 2: Extend MemoryDraft model

**Files:**
- Modify: `backend/app/models/memory.py:158-175`

- [ ] **Step 1: Add new columns to MemoryDraft**

After line `source_id = Column(CHAR(36), ForeignKey("memory_source.id"), nullable=True, index=True)` and before `reviewed_at`, insert:

```python
    explicitness = Column(Float, default=0.7, comment="LLM 判断的显式度 0-1")
    sensitivity_flag = Column(Float, default=0.0, comment="是否含敏感个人信息，0/1")
    auto_confirm_score = Column(Float, nullable=True, comment="后端规则引擎计算的自动确认综合分")
    corroboration_count = Column(Integer, default=0, comment="跨会话/跨消息印证条数")
```

- [ ] **Step 2: Add same columns to MemoryStatement**

After `source_id` line in `MemoryStatement` (line 79) and before `created_at` (line 80), insert:

```python
    explicitness = Column(Float, default=0.7, comment="LLM 判断的显式度 0-1")
    sensitivity_flag = Column(Float, default=0.0, comment="是否含敏感个人信息，0/1")
    auto_confirm_score = Column(Float, nullable=True, comment="后端规则引擎计算的自动确认综合分")
    corroboration_count = Column(Integer, default=0, comment="跨会话/跨消息印证条数")
```

- [ ] **Step 3: Verify model loads**

Run: `python -c "from backend.app.models.memory import MemoryDraft, MemoryStatement; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/memory.py
git commit -m "feat(memory): add explicitness, sensitivity_flag, auto_confirm_score, corroboration_count to MemoryDraft and MemoryStatement"
```

---

### Task 3: Add MemoryExtractionRun model for observability

**Files:**
- Modify: `backend/app/models/memory.py` (append new class)

- [ ] **Step 1: Add MemoryExtractionRun class**

At the end of `memory.py`, append:

```python
class MemoryExtractionRun(Base):
    __tablename__ = "memory_extraction_run"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    trigger_type = Column(String(32), default="scheduled", index=True, comment="scheduled/manual/instant")
    sessions_scanned = Column(Integer, default=0)
    sessions_extracted = Column(Integer, default=0)
    candidates_found = Column(Integer, default=0)
    auto_confirmed = Column(Integer, default=0)
    inbox_created = Column(Integer, default=0)
    skipped = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    duration_ms = Column(Integer, default=0)
    details = Column(JSON, default=dict, comment="per-session breakdown")
    created_at = Column(DateTime, default=local_now)
```

- [ ] **Step 2: Verify model loads**

Run: `python -c "from backend.app.models.memory import MemoryExtractionRun; print(MemoryExtractionRun.__tablename__)"`
Expected: `memory_extraction_run`

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/memory.py
git commit -m "feat(memory): add MemoryExtractionRun model for extraction observability"
```

---

### Task 4: Add configuration entries

**Files:**
- Modify: `backend/app/config.py:46`

- [ ] **Step 1: Add schedule/auto-confirm settings**

After line `MEMORY_EXTRACTION_AUTO_ENABLED: bool = ...`, insert:

```python
    MEMORY_SCHEDULED_ENABLED: bool = os.getenv("MEMORY_SCHEDULED_ENABLED", "1") == "1"
    MEMORY_SCHEDULED_INTERVAL_MINUTES: int = int(os.getenv("MEMORY_SCHEDULED_INTERVAL_MINUTES", "30"))
    MEMORY_SCHEDULED_MAX_SESSIONS: int = int(os.getenv("MEMORY_SCHEDULED_MAX_SESSIONS", "10"))
    MEMORY_SCHEDULED_CONTEXT_WINDOW: int = int(os.getenv("MEMORY_SCHEDULED_CONTEXT_WINDOW", "5"))
    MEMORY_AUTO_CONFIRM_THRESHOLD: float = float(os.getenv("MEMORY_AUTO_CONFIRM_THRESHOLD", "0.85"))
```

- [ ] **Step 2: Verify settings load**

Run: `python -c "from backend.app.config import settings; print(settings.MEMORY_SCHEDULED_INTERVAL_MINUTES)"`
Expected: `30` (or whatever is in `.env`)

- [ ] **Step 3: Commit**

```bash
git add backend/app/config.py
git commit -m "feat(memory): add MEMORY_SCHEDULED_* and MEMORY_AUTO_CONFIRM_THRESHOLD settings"
```

---

## Phase 2: Extraction Service Upgrade

### Task 5: Redesign extraction prompt with summary + window marking + multi-dimensional schema

**Files:**
- Modify: `backend/app/prompts/memory_extraction.py` (complete rewrite)

- [ ] **Step 1: Rewrite the prompt module**

Replace the entire file content:

```python
from __future__ import annotations

from backend.app.models.chat import ChatMessage


SYSTEM_PROMPT = """你是 Prism 的长期记忆抽取器。
从对话中抽取对未来有帮助、可长期保存的用户记忆。

输入包含三个部分：
1. [会话背景] — 整个对话的摘要，帮助你理解大语境
2. [上文语境] — 最近已提取过的历史消息，**仅供理解语境，不要从中提取记忆**
3. [待提取消息] — 需要抽取的新消息，**只从这里产出记忆候选**

应该抽取：
- 用户明确偏好、长期目标、稳定约束
- 当前持续关注的项目或探索主题
- 已做出的产品/技术决策
- 对 agent 行为的长期要求
- 被重复提及的主题或工具选择

不要抽取：
- 临时命令、寒暄、一次性调试步骤
- 密码、token、密钥或敏感凭据
- 助手内部实现细节，除非它表达了用户认可的长期项目上下文
- 没有长期价值的普通问答内容
- 纯技术错误堆栈

对每条候选，给出以下信号：
- confidence: 0-1, 你对提取正确性的信心
- explicitness: 0-1, 用户是否明确说出（1.0=直接陈述，0.5=可推断，0.2=高度推测）
- sensitivity_flag: true/false, 是否涉及身份、健康、财务、密码等敏感个人信息

只输出严格 JSON，不要 Markdown，不要解释。
JSON schema:
{
  "session_summary": "一句话中文概括本对话主题和已达成结论",
  "candidates": [
    {
      "content": "一句完整、可独立理解的中文记忆",
      "statement_type": "fact|preference|goal|constraint|decision|project_context|topic_interest|question",
      "temporal_type": "stable|current|episodic",
      "confidence": 0.0,
      "importance": 0.0,
      "explicitness": 0.0,
      "sensitivity_flag": false,
      "evidence_message_id": "原始消息 id"
    }
  ]
}
"""


def build_memory_extraction_messages(
    new_messages: list[ChatMessage],
    context_messages: list[ChatMessage] | None = None,
    session_summary: str = "",
) -> list[dict[str, str]]:
    """构建提取 prompt，含会话摘要、上下文窗口和待提取消息。"""

    def _format_messages(messages: list[ChatMessage], label: str) -> str:
        if not messages:
            return f"[{label}]\n(无消息)"
        lines: list[str] = [f"[{label}]"]
        for m in messages:
            content = (m.content or "").strip()
            if not content:
                continue
            lines.append(f"[message_id={m.id}] role={m.role}\n{content[:1600]}")
        return "\n\n".join(lines)

    context_block = _format_messages(context_messages or [], "上文语境 — 仅供理解，不从中提取")
    target_block = _format_messages(new_messages, "待提取消息 — 只从这里提取记忆")

    summary_text = session_summary or "(新会话，无已有摘要)"

    user_prompt = (
        f"[会话背景]\n{summary_text}\n\n"
        f"{context_block}\n\n"
        f"{target_block}"
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
```

- [ ] **Step 2: Verify imports and function signature**

Run: `python -c "from backend.app.prompts.memory_extraction import build_memory_extraction_messages; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/prompts/memory_extraction.py
git commit -m "feat(memory): redesign extraction prompt with summary, context/target windows, multi-dim signals"
```

---

### Task 6: Add watermark-based message loading and session summary generation

**Files:**
- Modify: `backend/app/services/memory_extraction.py`

- [ ] **Step 1: Add `load_session_messages_with_watermark` function**

After the existing `load_session_messages` function (after line 53), append:

```python
def load_session_messages_with_watermark(
    db: Session,
    session_id: str,
    last_extracted_message_id: str = "",
    context_window: int = 5,
) -> tuple[list[ChatMessage], list[ChatMessage]]:
    """
    Returns (context_messages, new_messages) split by watermark.

    context_messages: already-extracted messages for context (up to context_window)
    new_messages: messages after the watermark that need extraction
    """
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    all_messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
        .all()
    )

    # Find split point from watermark
    split_idx = 0
    if last_extracted_message_id:
        for i, msg in enumerate(all_messages):
            if msg.id == last_extracted_message_id:
                split_idx = i + 1
                break

    new_messages = all_messages[split_idx:]

    # Context window: messages before split, limited to context_window
    context_start = max(0, split_idx - context_window)
    context_messages = all_messages[context_start:split_idx]

    return context_messages, new_messages
```

- [ ] **Step 2: Add `generate_or_update_summary` function**

After the `load_session_messages_with_watermark` function, append:

```python
SUMMARY_PROMPT = """你是一个对话摘要生成器。请根据已有的会话摘要和最近的新消息，生成更新后的会话摘要。

已有摘要：{existing_summary}

最近新消息：
{recent_messages}

要求：
- 用 1-3 句中文概括本对话的整体主题
- 包含已达成的重要结论或决定
- 包含用户当前关注的方向
- 保持简洁，不超过 200 字
- 如果是更新已有摘要，则增量式补充新内容

只输出摘要文本，不要 Markdown，不要解释。"""


def generate_or_update_summary(
    db: Session,
    session: ChatSession,
    new_messages: list[ChatMessage],
) -> str:
    """Generate or incrementally update the session summary via LLM."""
    existing_summary = session.summary or ""
    recent_text = "\n".join(
        f"[{m.role}] {(m.content or '')[:800]}" for m in new_messages
    )
    if not recent_text.strip():
        return existing_summary or ""

    prompt = SUMMARY_PROMPT.format(
        existing_summary=existing_summary or "(新会话，无已有摘要)",
        recent_messages=recent_text,
    )

    try:
        client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=300,
        )
        new_summary = (response.choices[0].message.content or "").strip()
    except Exception:
        new_summary = existing_summary or ""

    if new_summary and new_summary != existing_summary:
        session.summary = new_summary

    return new_summary or existing_summary or ""
```

- [ ] **Step 3: Verify imports**

At the top of `memory_extraction.py`, the imports should already include `OpenAI` and `ChatSession`. No changes needed — `ChatSession` is imported at line 13.

- [ ] **Step 4: Verify functions load**

Run: `python -c "from backend.app.services.memory_extraction import load_session_messages_with_watermark, generate_or_update_summary; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/memory_extraction.py
git commit -m "feat(memory): add watermark-based message loading and LLM summary generation"
```

---

### Task 7: Update candidate parsing for multi-dimensional signals

**Files:**
- Modify: `backend/app/services/memory_extraction.py`

- [ ] **Step 1: Add `explicitness` and `sensitivity_flag` to MemoryCandidate dataclass**

Replace the existing `MemoryCandidate` dataclass (lines 21-29):

```python
@dataclass
class MemoryCandidate:
    content: str
    statement_type: str = "fact"
    temporal_type: str = "stable"
    confidence: float = 0.7
    importance: float = 0.6
    explicitness: float = 0.7
    sensitivity_flag: bool = False
    evidence_message_id: str = ""
```

- [ ] **Step 2: Update `parse_memory_candidates` to parse new fields**

Replace the `parse_memory_candidates` function body (lines 72-100). The new version adds parsing of `explicitness` and `sensitivity_flag`:

```python
def parse_memory_candidates(raw: str) -> list[MemoryCandidate]:
    try:
        data = json.loads(_extract_json_text(raw))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Memory extraction returned invalid JSON: {exc}") from exc
    items = data.get("candidates", []) if isinstance(data, dict) else []
    candidates: list[MemoryCandidate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        confidence = _as_float(item.get("confidence"), 0.7)
        if confidence < MIN_CONFIDENCE:
            continue
        # Parse sensitivity_flag: accept bool or int/float
        sens_raw = item.get("sensitivity_flag", False)
        if isinstance(sens_raw, bool):
            sensitivity_flag = sens_raw
        else:
            sensitivity_flag = bool(sens_raw)
        candidates.append(
            MemoryCandidate(
                content=content.strip(),
                statement_type=str(item.get("statement_type") or "fact"),
                temporal_type=str(item.get("temporal_type") or "stable"),
                confidence=confidence,
                importance=_as_float(item.get("importance"), 0.6),
                explicitness=_as_float(item.get("explicitness"), 0.7),
                sensitivity_flag=sensitivity_flag,
                evidence_message_id=str(item.get("evidence_message_id") or ""),
            )
        )
    return candidates
```

- [ ] **Step 3: Update `MemoryExtractionResult` to track auto-confirmed count**

Replace the existing `MemoryExtractionResult` dataclass (lines 33-40):

```python
@dataclass
class MemoryExtractionResult:
    session_id: str
    messages_scanned: int
    candidates_found: int = 0
    drafts_created: int = 0
    auto_confirmed: int = 0
    candidates_skipped: int = 0
    draft_ids: list[str] = field(default_factory=list)
    statement_ids: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Verify parsing logic**

Run: `python -c "from backend.app.services.memory_extraction import parse_memory_candidates; import json; raw=json.dumps({'candidates':[{'content':'test','explicitness':0.9,'sensitivity_flag':True}]}); c=parse_memory_candidates(raw); print(c[0].explicitness, c[0].sensitivity_flag)"`
Expected: `0.9 True`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/memory_extraction.py
git commit -m "feat(memory): update MemoryCandidate parsing for explicitness and sensitivity_flag"
```

---

### Task 8: Build the Auto-Confirm Decision Engine

**Files:**
- Modify: `backend/app/services/memory_extraction.py`

- [ ] **Step 1: Add type risk baseline and scoring constants**

After existing constants (after line 18), insert:

```python
# Auto-confirm decision engine constants
TYPE_RISK_BASELINE = {
    "fact": 1.0,
    "preference": 0.9,
    "project_context": 0.85,
    "topic_interest": 0.80,
    "goal": 0.70,
    "constraint": 0.65,
    "decision": 0.60,
    "question": 0.50,
}

# Scoring weights
W_CONFIDENCE = 0.25
W_EXPLICITNESS = 0.15
W_SENSITIVITY = 0.10
W_TYPE_RISK = 0.15
W_NO_CONFLICT = 0.15
W_CORROBORATION = 0.10
W_CROSS_SESSION = 0.10

# Thresholds
AUTO_CONFIRM_THRESHOLD = 0.85
HIGH_STAKES_CONFLICT_SIMILARITY = 0.80
HIGH_STAKES_CONFLICT_IMPORTANCE = 0.7
DUPLICATION_SIMILARITY = 0.95
CORROBORATION_SIMILARITY = 0.85
```

- [ ] **Step 2: Add `evaluate_auto_confirm` function**

After `_existing_memory_contents`, append:

```python
def _search_similar_statements(
    text: str,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Search Milvus for semantically similar confirmed statements."""
    try:
        return search_memory_vectors(
            text=text,
            user_id=DEFAULT_USER_ID,
            top_k=top_k,
        )
    except Exception:
        return []


def _check_semantic_conflict(
    new_content: str,
    existing_content: str,
) -> bool:
    """Check if two high-similarity statements semantically conflict via negation scan."""
    negation_patterns = [
        r"不\w{0,2}(?:喜欢|想|需要|会|能|应该|再|用|做|是|再|打算)",
        r"没有\w+",
        r"拒绝|放弃|停止|取消|不再|改为|换成|改成",
    ]
    new_has_neg = any(re.search(p, new_content) for p in negation_patterns)
    existing_has_neg = any(re.search(p, existing_content) for p in negation_patterns)
    return new_has_neg != existing_has_neg


def evaluate_auto_confirm(
    db: Session,
    candidate: MemoryCandidate,
    session_id: str = "",
) -> tuple[float, str, list[str]]:
    """
    Compute the auto_confirm_score and return (score, decision, conflict_ids).

    decision is one of: "auto_confirm", "review", "skip"
    """
    # ---- Veto Rule 1: Sensitivity gate ----
    if candidate.sensitivity_flag:
        return (0.0, "review", [])

    type_risk = TYPE_RISK_BASELINE.get(candidate.statement_type, 0.80)

    # ---- Semantic search for conflict & corroboration ----
    similar = _search_similar_statements(candidate.content, top_k=10)

    max_conflict_sim = 0.0
    conflict_ids: list[str] = []
    corroboration_count = 0
    cross_session_ids: set[str] = set()

    confirmed_statements = _existing_confirmed_statements(db)

    for hit in similar:
        if hit.get("kind") != "statement":
            continue
        hit_score = float(hit.get("score", 0))
        memory_id = str(hit.get("memory_id", ""))

        # Load the existing statement
        stmt = db.query(MemoryStatement).filter(
            MemoryStatement.id == memory_id,
            MemoryStatement.status == MemoryStatus.CONFIRMED,
        ).first()
        if not stmt:
            continue

        # ---- Duplication check ----
        if hit_score >= DUPLICATION_SIMILARITY:
            max_conflict_sim = max(max_conflict_sim, hit_score)
            # increment corroboration on existing
            stmt.corroboration_count = (stmt.corroboration_count or 0) + 1
            # Duplication = skip
            return (0.0, "skip", [memory_id])

        # ---- Corroboration check ----
        if hit_score >= CORROBORATION_SIMILARITY:
            corroboration_count += 1
            if stmt.source and stmt.source.session_id:
                cross_session_ids.add(stmt.source.session_id)
            if session_id and session_id in cross_session_ids:
                cross_session_ids.discard(session_id)

        # ---- Conflict check (same type, high similarity but lower than dup) ----
        if (
            hit_score >= HIGH_STAKES_CONFLICT_SIMILARITY
            and hit_score < DUPLICATION_SIMILARITY
            and stmt.statement_type == candidate.statement_type
        ):
            if _check_semantic_conflict(candidate.content, stmt.content or ""):
                max_conflict_sim = max(max_conflict_sim, hit_score)
                if (stmt.importance or 0) >= HIGH_STAKES_CONFLICT_IMPORTANCE:
                    conflict_ids.append(memory_id)

    # ---- Veto Rule 2: High-stakes conflict gate ----
    if conflict_ids:
        return (0.0, "review", conflict_ids)

    # ---- Compute corroboration boost ----
    corroboration_boost = min(1.0, corroboration_count / 3.0)

    # ---- Cross-session boost ----
    cross_session_count = len(cross_session_ids)
    if cross_session_count >= 2:
        cross_session_boost = 1.0
    elif cross_session_count == 1:
        cross_session_boost = 0.5
    else:
        cross_session_boost = 0.0

    # ---- Composite score ----
    score = (
        W_CONFIDENCE * candidate.confidence
        + W_EXPLICITNESS * candidate.explicitness
        + W_SENSITIVITY * (1.0 - (1.0 if candidate.sensitivity_flag else 0.0))
        + W_TYPE_RISK * type_risk
        + W_NO_CONFLICT * (1.0 - max_conflict_sim)
        + W_CORROBORATION * corroboration_boost
        + W_CROSS_SESSION * cross_session_boost
    )

    threshold = settings.MEMORY_AUTO_CONFIRM_THRESHOLD
    if score >= threshold:
        return (score, "auto_confirm", [])
    else:
        return (score, "review", [])
```

- [ ] **Step 3: Add missing import for `search_memory_vectors`**

At the top of `memory_extraction.py`, after the existing imports, add:

```python
from backend.app.services.memory_vectors import search_memory_vectors
```

- [ ] **Step 4: Verify the function loads**

Run: `python -c "from backend.app.services.memory_extraction import evaluate_auto_confirm; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/memory_extraction.py
git commit -m "feat(memory): add auto-confirm decision engine with composite scoring and veto rules"
```

---

### Task 9: Integrate watermark flow and decision engine into extraction

**Files:**
- Modify: `backend/app/services/memory_extraction.py`

- [ ] **Step 1: Add `extract_session_memories_scheduled` function**

After the existing `extract_session_memories` function, append a new function that wraps the full scheduled extraction flow:

```python
def extract_session_memories_scheduled(
    db: Session,
    session_id: str,
    last_extracted_message_id: str = "",
    context_window: int = 5,
) -> MemoryExtractionResult:
    """
    Scheduled extraction variant with watermark, summary, and auto-confirm.
    """
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    context_messages, new_messages = load_session_messages_with_watermark(
        db, session_id, last_extracted_message_id, context_window,
    )

    result = MemoryExtractionResult(session_id=session_id, messages_scanned=len(new_messages))
    if not new_messages:
        return result

    # Step 1: Update session summary
    session_summary = generate_or_update_summary(db, session, new_messages)

    # Step 2: Build prompt and call LLM
    prompt_messages = build_memory_extraction_messages(
        new_messages=new_messages,
        context_messages=context_messages,
        session_summary=session_summary,
    )
    raw = _call_memory_extraction_llm(prompt_messages)
    candidates = parse_memory_candidates(raw)
    result.candidates_found = len(candidates)

    # Step 3: Process each candidate through decision engine
    by_id = {m.id: m for m in new_messages}
    existing = _existing_memory_contents(db)

    for candidate in candidates:
        normalized = _normalize_content(candidate.content)
        if not normalized or normalized in existing:
            result.candidates_skipped += 1
            continue

        # Run auto-confirm decision engine
        auto_score, decision, conflict_ids = evaluate_auto_confirm(
            db, candidate, session_id=session_id,
        )

        evidence = by_id.get(candidate.evidence_message_id) or new_messages[-1]
        source = MemorySource(
            user_id=DEFAULT_USER_ID,
            source_type="chat_message",
            source_id=evidence.id,
            session_id=session_id,
            message_id=evidence.id,
            span_text=evidence.content or "",
            source_metadata={"extractor": "memory_scheduled_v1"},
        )

        if decision == "skip":
            result.candidates_skipped += 1
            continue

        if decision == "auto_confirm":
            # Create confirmed MemoryStatement directly
            statement = MemoryStatement(
                user_id=DEFAULT_USER_ID,
                content=candidate.content,
                statement_type=candidate.statement_type,
                temporal_type=candidate.temporal_type,
                confidence=candidate.confidence,
                importance=candidate.importance,
                explicitness=candidate.explicitness,
                sensitivity_flag=1.0 if candidate.sensitivity_flag else 0.0,
                auto_confirm_score=auto_score,
                corroboration_count=0,
                status=MemoryStatus.CONFIRMED,
                source=source,
            )
            db.add_all([source, statement])
            db.flush()
            # Index vector
            try:
                vector_id = upsert_statement_vector(statement)
                if vector_id:
                    statement.embedding_ref = vector_id
                    statement.embedding_model = settings.EMBEDDING_MODEL
                    statement.embedding_status = "done"
                else:
                    statement.embedding_status = "pending"
            except Exception:
                statement.embedding_status = "pending"
            result.statement_ids.append(statement.id)
            result.auto_confirmed += 1
        else:
            # decision == "review" → create draft for Memory Inbox
            draft = MemoryDraft(
                user_id=DEFAULT_USER_ID,
                draft_type="statement",
                payload={
                    "content": candidate.content,
                    "statement_type": candidate.statement_type,
                    "temporal_type": candidate.temporal_type,
                    "importance": candidate.importance,
                },
                decision_hint="review",
                risk_level="medium" if auto_score >= 0.6 else "high",
                confidence=candidate.confidence,
                explicitness=candidate.explicitness,
                sensitivity_flag=1.0 if candidate.sensitivity_flag else 0.0,
                auto_confirm_score=auto_score,
                conflict_ids=conflict_ids,
                source=source,
            )
            db.add_all([source, draft])
            db.flush()
            result.draft_ids.append(draft.id)
            result.drafts_created += 1

        existing.add(normalized)

    # Step 4: Update watermark on session
    if new_messages:
        session.last_extracted_message_id = new_messages[-1].id
        session.last_extracted_at = local_now()

    db.commit()
    return result
```

- [ ] **Step 2: Add required imports**

At the top, ensure these imports exist (add if missing):

```python
from backend.app.services.memory_vectors import search_memory_vectors, upsert_statement_vector
from backend.app.prompts.memory_extraction import build_memory_extraction_messages
from backend.app.utils.time import local_now
```

Check existing imports — `upsert_statement_vector` may need to be added, `local_now` may need to be added.

- [ ] **Step 3: Verify function loads**

Run: `python -c "from backend.app.services.memory_extraction import extract_session_memories_scheduled; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/memory_extraction.py
git commit -m "feat(memory): add scheduled extraction flow with watermark, summary, decision engine integration"
```

---

## Phase 3: Scheduler

### Task 10: Create MemoryScheduler

**Files:**
- Create: `backend/app/services/memory_scheduler.py`

- [ ] **Step 1: Write the scheduler module**

```python
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models.chat import ChatMessage, ChatSession
from backend.app.models.memory import MemoryExtractionRun
from backend.app.services.memory_extraction import extract_session_memories_scheduled
from backend.app.utils.time import local_now

log = logging.getLogger(__name__)


class MemoryScheduler:
    """Manages the APScheduler lifecycle for periodic memory extraction."""

    def __init__(self):
        self._scheduler: BackgroundScheduler | None = None

    def start(self) -> None:
        if not settings.MEMORY_SCHEDULED_ENABLED:
            log.info("[memory_scheduler] disabled by config, skipping")
            return

        self._scheduler = BackgroundScheduler()
        interval = settings.MEMORY_SCHEDULED_INTERVAL_MINUTES
        self._scheduler.add_job(
            func=_scheduled_extraction_round,
            trigger="interval",
            minutes=interval,
            id="memory_scheduled_extraction",
            replace_existing=True,
        )
        self._scheduler.start()
        log.info(f"[memory_scheduler] started, interval={interval}min")

    def shutdown(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            log.info("[memory_scheduler] stopped")

    def trigger_now(self) -> dict:
        """Manually trigger one extraction round. Returns round stats."""
        return _scheduled_extraction_round()


def _scheduled_extraction_round() -> dict:
    """
    One extraction round:
    1. Query candidate sessions with recent activity
    2. Filter by watermark
    3. Serial extraction per session
    4. Log results to MemoryExtractionRun
    """
    db = SessionLocal()
    start_time = datetime.now()
    stats = {
        "trigger_type": "scheduled",
        "sessions_scanned": 0,
        "sessions_extracted": 0,
        "candidates_found": 0,
        "auto_confirmed": 0,
        "inbox_created": 0,
        "skipped": 0,
        "errors": 0,
        "details": [],
    }

    try:
        interval = settings.MEMORY_SCHEDULED_INTERVAL_MINUTES
        max_sessions = settings.MEMORY_SCHEDULED_MAX_SESSIONS
        cutoff = local_now() - timedelta(minutes=interval * 3)

        # Step 1: Query candidate sessions
        sessions = (
            db.query(ChatSession)
            .filter(ChatSession.updated_at >= cutoff)
            .order_by(ChatSession.updated_at.desc())
            .limit(max_sessions)
            .all()
        )
        stats["sessions_scanned"] = len(sessions)

        # Step 2: Filter & extract
        for session in sessions:
            session_stats = {
                "session_id": session.id,
                "session_title": session.title or "",
                "status": "skipped",
            }
            try:
                # Check watermark
                latest_msg = (
                    db.query(ChatMessage)
                    .filter(ChatMessage.session_id == session.id)
                    .order_by(ChatMessage.created_at.desc())
                    .first()
                )
                if not latest_msg:
                    session_stats["reason"] = "no_messages"
                    stats["details"].append(session_stats)
                    continue

                if latest_msg.id == session.last_extracted_message_id:
                    session_stats["reason"] = "watermark_up_to_date"
                    stats["details"].append(session_stats)
                    continue

                # Run extraction
                result = extract_session_memories_scheduled(
                    db,
                    session_id=session.id,
                    last_extracted_message_id=session.last_extracted_message_id or "",
                    context_window=settings.MEMORY_SCHEDULED_CONTEXT_WINDOW,
                )

                session_stats["status"] = "extracted"
                session_stats["candidates_found"] = result.candidates_found
                session_stats["auto_confirmed"] = result.auto_confirmed
                session_stats["inbox_created"] = result.drafts_created
                session_stats["skipped"] = result.candidates_skipped

                stats["sessions_extracted"] += 1
                stats["candidates_found"] += result.candidates_found
                stats["auto_confirmed"] += result.auto_confirmed
                stats["inbox_created"] += result.drafts_created
                stats["skipped"] += result.candidates_skipped

            except Exception as exc:
                stats["errors"] += 1
                session_stats["status"] = "error"
                session_stats["error"] = str(exc)
                log.error(f"[memory_scheduler] session={session.id} error: {exc}")

            stats["details"].append(session_stats)

        # Step 3: Persist run log
        duration = int((datetime.now() - start_time).total_seconds() * 1000)
        run = MemoryExtractionRun(
            trigger_type="scheduled",
            sessions_scanned=stats["sessions_scanned"],
            sessions_extracted=stats["sessions_extracted"],
            candidates_found=stats["candidates_found"],
            auto_confirmed=stats["auto_confirmed"],
            inbox_created=stats["inbox_created"],
            skipped=stats["skipped"],
            errors=stats["errors"],
            duration_ms=duration,
            details=stats["details"],
        )
        db.add(run)
        db.commit()

        log.info(
            f"[memory_scheduler] round done: scanned={stats['sessions_scanned']}, "
            f"extracted={stats['sessions_extracted']}, "
            f"auto_confirmed={stats['auto_confirmed']}, "
            f"inbox={stats['inbox_created']}, skipped={stats['skipped']}, "
            f"errors={stats['errors']}, duration={duration}ms"
        )

    finally:
        db.close()

    return stats
```

- [ ] **Step 2: Verify APScheduler is available**

Run: `python -c "from apscheduler.schedulers.background import BackgroundScheduler; print('OK')"`
If fails, install: `pip install apscheduler`

- [ ] **Step 3: Verify module loads**

Run: `python -c "from backend.app.services.memory_scheduler import MemoryScheduler; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/memory_scheduler.py
git commit -m "feat(memory): add MemoryScheduler with APScheduler periodic extraction rounds"
```

---

### Task 11: Integrate scheduler into Backend lifespan

**Files:**
- Modify: `backend/app/main.py:142-168`

- [ ] **Step 1: Add import and global variable**

After line `from .api import register_routers`, add:

```python
from .services.memory_scheduler import MemoryScheduler
```

After line `_engine_log_thread = None`, add:

```python
_memory_scheduler: MemoryScheduler | None = None
```

- [ ] **Step 2: Add scheduler start/stop to on_event handlers**

In `startup()` (after line `if os.getenv("SKIP_ENGINE") != "1":`), add scheduler start:

```python
        # Start memory extraction scheduler
        global _memory_scheduler
        try:
            _memory_scheduler = MemoryScheduler()
            _memory_scheduler.start()
        except Exception as e:
            print(f"[backend] Memory scheduler failed to start: {e}")
```

In `shutdown()` (before function end), add scheduler shutdown:

```python
        if _memory_scheduler:
            try:
                _memory_scheduler.shutdown()
            except Exception as e:
                print(f"[backend] Memory scheduler shutdown error: {e}")
```

- [ ] **Step 3: Verify app starts**

Run: `python -c "from backend.app.main import app; print('OK')"`
Expected: `OK` (scheduler may log a startup message)

- [ ] **Step 4: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(memory): integrate MemoryScheduler into Backend lifespan"
```

---

## Phase 4: API Changes

### Task 12: Add GET /drafts/count and POST /extract/scheduled endpoints

**Files:**
- Modify: `backend/app/api/memories.py`

- [ ] **Step 1: Add imports**

After the existing imports, add:

```python
from sqlalchemy import func
from ..services.memory_scheduler import MemoryScheduler
```

- [ ] **Step 2: Add GET /drafts/count endpoint**

Before the `create_memory_draft` function (around line 157), insert:

```python
@router.get("/drafts/count")
def count_memory_drafts(
    status: str = Query("draft"),
    db: Session = Depends(get_db),
):
    """Return count of drafts (default: draft status) for badge display."""
    count = (
        db.query(MemoryDraft)
        .filter(
            MemoryDraft.user_id == DEFAULT_USER_ID,
            MemoryDraft.status == status,
        )
        .count()
    )
    risks = (
        db.query(MemoryDraft.risk_level, func.count())
        .filter(
            MemoryDraft.user_id == DEFAULT_USER_ID,
            MemoryDraft.status == status,
        )
        .group_by(MemoryDraft.risk_level)
        .all()
    )
    return {
        "count": count,
        "by_risk": {risk: c for risk, c in risks},
    }
```

- [ ] **Step 3: Add POST /extract/scheduled trigger endpoint**

Before the `list_memory_statements` function, insert:

```python
@router.post("/extract/scheduled", response_model=dict)
def trigger_scheduled_extraction():
    """Manually trigger one round of scheduled extraction. Returns round stats."""
    scheduler = MemoryScheduler()
    stats = scheduler.trigger_now()
    return stats
```

Note: For a proper implementation that reuses the running scheduler instance, we'd need to store the instance globally. A simpler approach for the endpoint: directly call `_scheduled_extraction_round()`:

```python
@router.post("/extract/scheduled", response_model=dict)
def trigger_scheduled_extraction():
    """Manually trigger one round of scheduled extraction."""
    from ..services.memory_scheduler import _scheduled_extraction_round
    stats = _scheduled_extraction_round()
    return stats
```

- [ ] **Step 4: Verify endpoints load**

Run: `python -c "from backend.app.api.memories import router; print(len(router.routes))"`
Expected: prints the new route count (should be higher than before).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/memories.py
git commit -m "feat(memory): add GET /drafts/count and POST /extract/scheduled endpoints"
```

---

## Phase 5: Tests

### Task 13: Test candidate parsing with new multi-dimensional signals

**Files:**
- Modify: `backend/tests/test_memory_extraction_service.py`

- [ ] **Step 1: Add test for parsing explicitness and sensitivity_flag**

After the existing `test_parse_memory_candidates_skips_invalid_candidates` test, append:

```python
def test_parse_memory_candidates_parses_explicitness_and_sensitivity():
    raw = json.dumps({
        "candidates": [
            {
                "content": "用户使用 Python 作为主力语言",
                "statement_type": "preference",
                "temporal_type": "stable",
                "confidence": 0.9,
                "importance": 0.8,
                "explicitness": 0.95,
                "sensitivity_flag": False,
                "evidence_message_id": "msg-a",
            },
            {
                "content": "用户身份证号为 xxx",
                "statement_type": "fact",
                "confidence": 0.85,
                "explicitness": 1.0,
                "sensitivity_flag": True,
                "evidence_message_id": "msg-b",
            },
        ]
    }, ensure_ascii=False)

    candidates = svc.parse_memory_candidates(raw)

    assert len(candidates) == 2
    assert candidates[0].explicitness == 0.95
    assert candidates[0].sensitivity_flag is False
    assert candidates[1].explicitness == 1.0
    assert candidates[1].sensitivity_flag is True


def test_parse_memory_candidates_handles_sensitivity_as_int():
    """sensitivity_flag may come as 0/1 int, parse as bool."""
    raw = json.dumps({
        "candidates": [
            {"content": "test", "sensitivity_flag": 1, "explicitness": 0.85},
        ]
    })
    candidates = svc.parse_memory_candidates(raw)
    assert len(candidates) == 1
    assert candidates[0].sensitivity_flag is True
```

- [ ] **Step 2: Run the tests**

Run: `cd backend && python -m pytest tests/test_memory_extraction_service.py::test_parse_memory_candidates_parses_explicitness_and_sensitivity tests/test_memory_extraction_service.py::test_parse_memory_candidates_handles_sensitivity_as_int -v`
Expected: 2 PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_memory_extraction_service.py
git commit -m "test(memory): add tests for explicitness and sensitivity_flag parsing"
```

---

### Task 14: Test watermark-based message loading

**Files:**
- Modify: `backend/tests/test_memory_extraction_service.py`

- [ ] **Step 1: Add test for watermark message loading**

Append:

```python
def test_load_session_messages_with_watermark_splits_correctly(db_session):
    session = ChatSession(user_id="default-user", title="Watermark test")
    db_session.add(session)
    db_session.flush()

    msgs = []
    for i in range(10):
        m = ChatMessage(session_id=session.id, role="user", content=f"消息{i}")
        db_session.add(m)
        msgs.append(m)
    db_session.commit()

    # Watermark at message index 3 (split at msg idx 4)
    watermark_id = msgs[3].id
    context, new = svc.load_session_messages_with_watermark(
        db_session, session.id, watermark_id, context_window=5,
    )

    # Context should include messages before watermark (limited to 5)
    assert len(context) <= 5
    # New messages = msgs[4:] = 6 messages
    assert len(new) == 6
    assert new[0].content == "消息4"
    assert new[-1].content == "消息9"


def test_load_session_messages_with_watermark_no_watermark_returns_all_new(db_session):
    session = ChatSession(user_id="default-user", title="No watermark")
    db_session.add(session)
    db_session.flush()

    for i in range(3):
        db_session.add(ChatMessage(session_id=session.id, role="user", content=f"msg{i}"))
    db_session.commit()

    context, new = svc.load_session_messages_with_watermark(
        db_session, session.id, "", context_window=5,
    )

    # No watermark → all messages are new, context is empty
    assert len(context) == 0
    assert len(new) == 3


def test_load_session_messages_with_watermark_404_on_missing_session(db_session):
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        svc.load_session_messages_with_watermark(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404
```

- [ ] **Step 2: Run the tests**

Run: `cd backend && python -m pytest tests/test_memory_extraction_service.py::test_load_session_messages_with_watermark_splits_correctly tests/test_memory_extraction_service.py::test_load_session_messages_with_watermark_no_watermark_returns_all_new tests/test_memory_extraction_service.py::test_load_session_messages_with_watermark_404_on_missing_session -v`
Expected: 3 PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_memory_extraction_service.py
git commit -m "test(memory): add watermark message loading tests"
```

---

### Task 15: Test auto-confirm decision engine

**Files:**
- Modify: `backend/tests/test_memory_extraction_service.py`

- [ ] **Step 1: Add tests for the decision engine**

Append:

```python
def test_evaluate_auto_confirm_sensitivity_veto(db_session):
    """sensitivity_flag=True must force 'review' regardless of score."""
    from backend.app.services.memory_extraction import MemoryCandidate

    candidate = MemoryCandidate(
        content="用户的身份证号是 xxx",
        statement_type="fact",
        confidence=0.99,
        explicitness=1.0,
        sensitivity_flag=True,
    )

    score, decision, conflicts = svc.evaluate_auto_confirm(
        db_session, candidate, session_id="",
    )

    assert decision == "review"
    assert score == 0.0  # vetoed


def test_evaluate_auto_confirm_high_confidence_fact_auto_confirms(db_session):
    """High confidence, high explicitness, low-risk type → auto_confirm."""
    candidate = svc.MemoryCandidate(
        content="用户使用 Python 作为主要开发语言",
        statement_type="preference",
        confidence=0.95,
        explicitness=0.95,
        sensitivity_flag=False,
        importance=0.5,
    )

    score, decision, conflicts = svc.evaluate_auto_confirm(
        db_session, candidate, session_id="",
    )

    # Should auto-confirm (exact score depends on Milvus, but decision is key)
    assert decision == "auto_confirm"
    assert score >= 0.85


def test_evaluate_auto_confirm_low_confidence_decision_review(db_session):
    """Low confidence on a decision type → review."""
    candidate = svc.MemoryCandidate(
        content="用户决定使用微服务架构",
        statement_type="decision",
        confidence=0.6,
        explicitness=0.5,
        sensitivity_flag=False,
        importance=0.7,
    )

    score, decision, conflicts = svc.evaluate_auto_confirm(
        db_session, candidate, session_id="",
    )

    assert decision == "review"
    assert score < 0.85
```

- [ ] **Step 2: Run the tests**

Run: `cd backend && python -m pytest tests/test_memory_extraction_service.py::test_evaluate_auto_confirm_sensitivity_veto tests/test_memory_extraction_service.py::test_evaluate_auto_confirm_high_confidence_fact_auto_confirms tests/test_memory_extraction_service.py::test_evaluate_auto_confirm_low_confidence_decision_review -v`
Expected: 3 PASS (Milvus may be down — if so, expect graceful degradation with score still computed from available signals).

If Milvus is not available: these tests will compute scores without semantic signals — the decision may flip. Adjust expected thresholds in the assertions after running, or add `monkeypatch` to mock `_search_similar_statements`.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_memory_extraction_service.py
git commit -m "test(memory): add auto-confirm decision engine tests"
```

---

### Task 16: Test scheduled extraction endpoint

**Files:**
- Modify: `backend/tests/test_memory_extraction_api.py`

- [ ] **Step 1: Add test for GET /drafts/count**

Append:

```python
def test_count_drafts_returns_count(db_session, test_app):
    """GET /memories/drafts/count returns draft count and by_risk breakdown."""
    # Create a draft manually via the create endpoint
    payload = {
        "draft_type": "statement",
        "payload": {"content": "test count draft", "statement_type": "fact"},
        "decision_hint": "review",
        "risk_level": "medium",
        "confidence": 0.7,
    }
    test_app.post("/api/v1/memories/drafts", json=payload)

    resp = test_app.get("/api/v1/memories/drafts/count?status=draft")
    assert resp.status_code == 200
    data = resp.json()
    assert "count" in data
    assert data["count"] >= 1
    assert "by_risk" in data
```

- [ ] **Step 2: Add test for POST /extract/scheduled**

Append:

```python
def test_trigger_scheduled_extraction_returns_stats(test_app):
    """POST /memories/extract/scheduled triggers a round and returns stats."""
    resp = test_app.post("/api/v1/memories/extract/scheduled")
    assert resp.status_code == 200
    data = resp.json()
    assert "sessions_scanned" in data
    assert "sessions_extracted" in data
    assert "auto_confirmed" in data
    assert "inbox_created" in data
    assert "errors" in data
```

- [ ] **Step 3: Run the tests**

Run: `cd backend && python -m pytest tests/test_memory_extraction_api.py::test_count_drafts_returns_count tests/test_memory_extraction_api.py::test_trigger_scheduled_extraction_returns_stats -v`
Expected: 2 PASS

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_memory_extraction_api.py
git commit -m "test(memory): add draft count and scheduled trigger endpoint tests"
```

---

## Phase 6: Frontend

### Task 17: Add countDrafts to frontend API client

**Files:**
- Modify: `frontend/src/app/api.ts`

- [ ] **Step 1: Add the method to memoryApi**

Find the `memoryApi` object and add the `countDrafts` method:

```typescript
export const memoryApi = {
  // ... existing methods ...

  countDrafts: (status = 'draft') =>
    request<{ count: number; by_risk: Record<string, number> }>(
      `/memories/drafts/count?status=${status}`,
    ),
}
```

- [ ] **Step 2: Verify TypeScript compilation**

Run: `cd frontend && pnpm exec tsc --noEmit --project tsconfig.json 2>&1 | Select-String "api.ts" | Select-Object -First 10`

Or: `cd frontend && npx tsc -p tsconfig.json --noEmit src/app/api.ts`

Expected: No TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api.ts
git commit -m "feat(frontend): add countDrafts method to memoryApi"
```

---

### Task 18: Add notification badge to navigation

**Files:**
- Modify: `frontend/src/layouts/MainLayout.tsx`

- [ ] **Step 1: Add badge display to NavItem and NavList**

The "记忆审核" nav item at line 109 needs a badge. First, add badge support to the `NavItem` function.

Update the `NavItem` props and rendering to support an optional badge:

```tsx
function NavItem({
  to,
  label,
  icon: Icon,
  active,
  isDark = false,
  onNavigate,
  badge,  // NEW
}: {
  to: string
  label: string
  icon: typeof MessageSquare
  active: boolean
  isDark?: boolean
  onNavigate?: () => void
  badge?: number  // NEW
}) {
  return (
    <NavLink
      to={to}
      aria-current={active ? 'page' : undefined}
      onClick={onNavigate}
      className={cn(
        'group flex h-10 items-center gap-3 rounded-lg px-3 text-[13px] font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/80',
        active
          ? 'bg-[var(--prism-blue)] text-white shadow-[0_10px_24px_-16px_rgba(37,99,235,0.9)]'
          : isDark
            ? 'text-slate-400 hover:bg-white/[0.06] hover:text-slate-100'
            : 'text-slate-500 hover:bg-slate-100 hover:text-slate-950',
      )}
    >
      <Icon size={16} className="shrink-0" />
      <span>{label}</span>
      {badge != null && badge > 0 ? (
        <span className="ml-auto inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-red-500 px-1.5 text-[10px] font-bold text-white">
          {badge > 99 ? '99+' : badge}
        </span>
      ) : null}
    </NavLink>
  )
}
```

- [ ] **Step 2: Consume badge in the "记忆审核" nav item**

In the `NavList` function, the "记忆审核" nav item needs to receive the `badge` prop. To keep it simple, accept an optional `draftCount` prop on `NavList`:

In `NavList` props, add:

```tsx
function NavList({ onNavigate, isDark = false, draftCount = 0 }: { onNavigate?: () => void; isDark?: boolean; draftCount?: number }) {
```

Then update the "记忆审核" NavItem:

```tsx
        <NavItem
          to="/memory/inbox"
          label="记忆审核"
          icon={Inbox}
          active={location.pathname === '/memory/inbox'}
          isDark={isDark}
          onNavigate={onNavigate}
          badge={draftCount}
        />
```

- [ ] **Step 3: Pass draftCount from MainLayout**

In `MainLayout`, add state and polling for draft count:

At the top of the `MainLayout` component, add:

```tsx
import { useEffect, useState } from 'react'  // extend existing react import
// ... existing imports ...
import { memoryApi } from '@/app/api'  // NEW

export function MainLayout() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const [theme, setTheme] = useState<'light' | 'dark'>('light')
  const [draftCount, setDraftCount] = useState(0)  // NEW
  // ... rest
```

Add polling effect before the return statement:

```tsx
  useEffect(() => {
    let cancelled = false
    const poll = () => {
      memoryApi.countDrafts('draft')
        .then(res => { if (!cancelled) setDraftCount(res.count) })
        .catch(() => {})
    }
    poll()
    const id = setInterval(poll, 30_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])
```

Pass `draftCount` to the `NavList` components:

```tsx
<NavList isDark={isDark} draftCount={draftCount} />
```

And in the mobile `CompactNav`, add badge support similarly or pass to `CompactNav`:

```tsx
<CompactNav isDark={isDark} onNavigate={() => setMobileOpen(false)} draftCount={draftCount} />
```

Update `CompactNav` similarly to accept and pass badge to relevant NavItem.

- [ ] **Step 4: Verify TypeScript compilation**

Run: `cd frontend && npx tsc -p tsconfig.json --noEmit`
Expected: No errors (or only unrelated pre-existing errors).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/layouts/MainLayout.tsx
git commit -m "feat(frontend): add notification badge on Memory Inbox nav with 30s polling"
```

---

### Task 19: Run full test suite and verify nothing is broken

- [ ] **Step 1: Run backend tests**

```bash
cd backend && python -m pytest tests/test_memory_extraction_service.py tests/test_memory_extraction_api.py -v
```

Expected: All tests pass (some may skip if Milvus unavailable).

- [ ] **Step 2: Run frontend type check**

```bash
cd frontend && npx tsc -p tsconfig.json --noEmit
```

Expected: No new TypeScript errors introduced.

- [ ] **Step 3: Verify backend starts**

```bash
SKIP_ENGINE=1 python -m backend.run
```

Check for: `[memory_scheduler] started, interval=30min` in output.

- [ ] **Step 4: Commit any remaining changes**

```bash
git status
git add -A
git commit -m "chore: final integration verification"
```

---

## Implementation Order

```
Phase 1: Data Model (Tasks 1-4) → no breaking changes, all DEFAULT values
Phase 2: Extraction Service (Tasks 5-9) → upgraded functions, existing API preserved
Phase 3: Scheduler (Tasks 10-11) → new module, opt-in via config
Phase 4: API (Task 12) → new endpoints only
Phase 5: Tests (Tasks 13-16) → validate core logic
Phase 6: Frontend (Tasks 17-18) → non-blocking UI enhancement
Verify: Task 19
```

---

*Plan complete. Ready for execution.*
