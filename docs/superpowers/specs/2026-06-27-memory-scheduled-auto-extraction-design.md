# Memory Scheduled Auto-Extraction with Intelligent Auto-Confirm

> Date: 2026-06-27
> Status: Design approved, pending implementation
> Scope: Prism 记忆系统 — 定时自动提取 + 多维复合评分自动确认引擎

---

## 1. Problem Statement

### 1.1 Current State

Prism 的记忆提取系统当前有两种触发路径：

1. **手动提取**：用户在 Memory Inbox 页面手动选择会话 → 点击"Extract from session" → LLM 提取 → Draft 进 Inbox → 用户逐条确认/拒绝
2. **即时自动提取**（`MEMORY_EXTRACTION_AUTO_ENABLED=1`）：每条 assistant 消息写入后启动 daemon 线程调用提取服务

### 1.2 Pain Points

| 痛点 | 描述 | 影响 |
|------|------|------|
| **手动选择负担** | 每次需要用户主动打开 Memory Inbox，选择具体会话，点击按钮 | 用户决策疲劳，低活跃期可能完全忘记提取 |
| **即时提取碎片化** | 每条消息触发一次提取，缺乏会话级上下文，容易丢失跨消息的语义 | 提取质量低，重复提取多 |
| **缺乏智能分流** | 当前 auto_confirm 仅基于 LLM 单一 confidence 值判断，不可靠 | 要么全部进 Inbox（审阅负担重），要么误自动确认（不可逆） |
| **无跨会话视角** | 每次提取只看当前会话，无法利用跨会话印证/冲突信号 | 遗漏高频出现的持久性记忆，重复创建相似 draft |
| **无量化反馈** | 无法知道提取效果好不好，缺乏可优化的指标 | 系统改进靠直觉，无法数据驱动 |

### 1.3 Goal

构建一个**定时调度 + 智能决策**的记忆提取系统，让用户从"主动操作者"变为"审核把关人"：

- 系统定时自动扫描近期活跃会话
- 带完整上下文的 LLM 提取（会话摘要 + 语境窗口 + 新消息窗口）
- 多维复合评分引擎决定 auto_confirm / Inbox review / skip
- Embedding 语义级冲突检测与跨会话印证
- 前端角标轻量通知，用户只需访问 Inbox 审核

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                      Backend FastAPI Process                      │
│                                                                   │
│  ┌──────────────────────┐        ┌───────────────────────────┐   │
│  │   APScheduler        │        │   Memory Extraction        │   │
│  │   (BackgroundScheduler)│─────▶│   Service (upgraded)       │   │
│  │                      │        │                           │   │
│  │   Interval: N min    │        │  ┌─────────────────────┐  │   │
│  │   Configurable       │        │  │ 1. Scan sessions    │  │   │
│  └──────────────────────┘        │  │ 2. Gen summary      │  │   │
│                                   │  │ 3. Build prompt     │  │   │
│  ┌──────────────────────┐        │  │ 4. LLM extraction   │  │   │
│  │   Auto-Confirm       │        │  │ 5. Auto-confirm     │  │   │
│  │   Decision Engine    │◀───────│  │ 6. Write result     │  │   │
│  │                      │        │  │ 7. Update watermark │  │   │
│  │  Multi-dim scoring   │        │  └─────────────────────┘  │   │
│  │  + veto rules        │        │                           │   │
│  └──────────────────────┘        └───────────────────────────┘   │
│                                              │                    │
│  ┌──────────────────────┐                   │                    │
│  │   Embedding Service  │◀──────────────────┘                    │
│  │   (Milvus)           │                                         │
│  │                      │                                        │
│  │  Conflict detection  │                                        │
│  │  Corroboration search│                                        │
│  └──────────────────────┘                                         │
└──────────────────────────────────────────────────────────────────┘
```

### 2.1 Module Boundaries

| 层 | 模块 | 职责 |
|----|------|------|
| Scheduling | `services/memory_scheduler.py` (new) | APScheduler 生命周期管理，定时触发，轮次统计 |
| Extraction | `services/memory_extraction.py` (upgrade) | 水位线加载、摘要生成、上下文构建、LLM 调用、多维解析 |
| Decision | `services/memory_extraction.py` → `evaluate_auto_confirm()` | 复合评分计算、一票否决规则、auto-confirm/review/skip 分流 |
| Embedding | `services/memory_vectors.py` (reuse) | 语义搜索用于冲突检测和印证 |
| API | `api/memories.py` | 新增 `GET /drafts/count` |
| Frontend | `MemoryInboxPage.tsx` + `MainLayout.tsx` | 角标轮询，显示待审数量 |

---

## 3. Data Model Changes

### 3.1 ChatSession (extend)

```sql
ALTER TABLE chat_session ADD COLUMN summary TEXT COMMENT 'LLM 生成的会话摘要，每次提取后增量更新';
ALTER TABLE chat_session ADD COLUMN last_extracted_message_id CHAR(36) COMMENT '上次提取到的最后一条消息 ID，作为水位线';
ALTER TABLE chat_session ADD COLUMN last_extracted_at DATETIME COMMENT '上次触发提取的时间';
```

```python
# models/chat.py
class ChatSession(Base):
    # ... existing fields ...
    summary = Column(Text, default="", comment="LLM 生成的会话摘要")
    last_extracted_message_id = Column(CHAR(36), default="", comment="提取水位线")
    last_extracted_at = Column(DateTime, nullable=True, comment="上次提取时间")
```

### 3.2 MemoryDraft & MemoryStatement (extend)

```sql
ALTER TABLE memory_draft ADD COLUMN explicitness FLOAT DEFAULT 0.7 COMMENT 'LLM 判断的显式度 0-1';
ALTER TABLE memory_draft ADD COLUMN sensitivity_flag TINYINT(1) DEFAULT 0 COMMENT '是否含敏感个人信息';
ALTER TABLE memory_draft ADD COLUMN auto_confirm_score FLOAT COMMENT '后端规则引擎计算的自动确认综合分';
ALTER TABLE memory_draft ADD COLUMN corroboration_count INT DEFAULT 0 COMMENT '跨会话印证条数';

ALTER TABLE memory_statement ADD COLUMN explicitness FLOAT DEFAULT 0.7;
ALTER TABLE memory_statement ADD COLUMN sensitivity_flag TINYINT(1) DEFAULT 0;
ALTER TABLE memory_statement ADD COLUMN auto_confirm_score FLOAT;
ALTER TABLE memory_statement ADD COLUMN corroboration_count INT DEFAULT 0;
```

### 3.3 Extraction Run Log (new table, for observability)

```sql
CREATE TABLE memory_extraction_run (
    id CHAR(36) PRIMARY KEY,
    user_id CHAR(36) DEFAULT 'default-user',
    trigger_type VARCHAR(32) COMMENT 'scheduled / manual / instant',
    sessions_scanned INT DEFAULT 0,
    sessions_extracted INT DEFAULT 0,
    candidates_found INT DEFAULT 0,
    auto_confirmed INT DEFAULT 0,
    inbox_created INT DEFAULT 0,
    skipped INT DEFAULT 0,
    errors INT DEFAULT 0,
    duration_ms INT DEFAULT 0,
    details JSON COMMENT 'per-session breakdown',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 4. Configuration

`.env` 新增项：

```bash
# 定时调度
MEMORY_SCHEDULED_ENABLED=1                          # 是否启用定时提取
MEMORY_SCHEDULED_INTERVAL_MINUTES=30                 # 调度间隔（分钟）
MEMORY_SCHEDULED_MAX_SESSIONS=10                     # 每轮最多扫描会话数
MEMORY_SCHEDULED_CONTEXT_WINDOW=5                    # 上下文窗口消息数

# 自动确认
MEMORY_AUTO_CONFIRM_THRESHOLD=0.85                   # 自动确认分数阈值
```

`config.py` 扩展：

```python
MEMORY_SCHEDULED_ENABLED: bool = os.getenv("MEMORY_SCHEDULED_ENABLED", "1") == "1"
MEMORY_SCHEDULED_INTERVAL_MINUTES: int = int(os.getenv("MEMORY_SCHEDULED_INTERVAL_MINUTES", "30"))
MEMORY_SCHEDULED_MAX_SESSIONS: int = int(os.getenv("MEMORY_SCHEDULED_MAX_SESSIONS", "10"))
MEMORY_SCHEDULED_CONTEXT_WINDOW: int = int(os.getenv("MEMORY_SCHEDULED_CONTEXT_WINDOW", "5"))
MEMORY_AUTO_CONFIRM_THRESHOLD: float = float(os.getenv("MEMORY_AUTO_CONFIRM_THRESHOLD", "0.85"))
```

---

## 5. Auto-Confirm Decision Engine

### 5.1 Decision Architecture

```
LLM 输出 6 维信号 + 后端查询 3 维信号
              │
              ▼
      ┌───────────────────┐
      │  一票否决规则检查    │
      │  (3 条 hard gates) │
      └───────┬───────────┘
              │ pass
              ▼
      ┌───────────────────┐
      │  加权复合评分       │
      │  auto_confirm_score│
      └───────┬───────────┘
              │
    ┌─────────┼─────────┐
    │         │         │
   ≥0.85   <0.85   duplication>0.95
    │         │         │
    ▼         ▼         ▼
 AUTO     INBOX      SKIP
CONFIRM   REVIEW    (update corroboration)
```

### 5.2 LLM Output Signals (6 dimensions, per candidate)

| Signal | Type | Range | Description |
|--------|------|-------|-------------|
| `confidence` | float | 0-1 | LLM 对提取正确性的自评 |
| `explicitness` | float | 0-1 | 用户陈述的显式程度。直接说出=1.0，间接推断=0.3 |
| `sensitivity_flag` | bool | {0,1} | 是否涉及个人敏感信息（身份、健康、财务、密码等） |
| `statement_type` | str | enum | 记忆类型，用于计算 type_risk 基线 |
| `importance` | float | 0-1 | 该记忆的重要程度 |
| `temporal_type` | str | enum | 时效类型，影响稳定性评分 |

### 5.3 Type Risk Baseline (rule-based lookup)

```python
TYPE_RISK_BASELINE = {
    "fact":              1.0,   # 最低风险：客观事实
    "preference":         0.9,   # 低风险：用户偏好
    "project_context":    0.85,  # 低风险：当前项目背景
    "topic_interest":     0.80,  # 中低风险
    "goal":               0.70,  # 中风险：目标可能变化
    "constraint":         0.65,  # 中高风险：约束条件误判影响大
    "decision":           0.60,  # 高风险：决策需要用户确认
    "question":           0.50,  # 最高风险：问题不等于立场
}
```

### 5.4 Backend Query Signals (3 dimensions, per candidate)

| Signal | Source | Computation |
|--------|--------|-------------|
| `semantic_conflict_score` | Milvus vector search | `max(cosine_similarity(candidate_embedding, confirmed_statement_embedding))` 仅计算同 type 且 content 语义矛盾的情况。最高冲突度 |
| `corroboration_boost` | Milvus vector search | `count(similar statements where cosine ≥ 0.85) / 3`, 上限 1.0。与已有记忆语义高度相似的条数 |
| `cross_session_boost` | MySQL query | 该 candidate 内容与已有 statement 的语义匹配来自几个不同 session。0 session = 0, 1 = 0.5, ≥2 = 1.0 |

### 5.5 Composite Scoring Formula

```python
auto_confirm_score = (
    W_CONFIDENCE          * confidence                    # 0.25
    + W_EXPLICITNESS      * explicitness                  # 0.15
    + W_SENSITIVITY       * (1.0 - sensitivity_flag)      # 0.10
    + W_TYPE_RISK         * type_risk_baseline            # 0.15
    + W_NO_CONFLICT       * (1.0 - max_conflict_similarity)# 0.15
    + W_CORROBORATION     * corroboration_boost            # 0.10
    + W_CROSS_SESSION     * cross_session_boost            # 0.10
)
```

**Weights rationale:**

| Weight | Value | Justification |
|--------|-------|---------------|
| W_CONFIDENCE | 0.25 | LLM 判断是核心信号，权重最高 |
| W_EXPLICITNESS | 0.15 | 显式陈述比推断可靠得多 |
| W_SENSITIVITY | 0.10 | 敏感信息反向加权，但不算最高因为有一票否决 |
| W_TYPE_RISK | 0.15 | 不同类型出错代价不同 |
| W_NO_CONFLICT | 0.15 | 语义冲突是强信号 |
| W_CORROBORATION | 0.10 | 跨会话印证增强信心 |
| W_CROSS_SESSION | 0.10 | 来源多样性 |

### 5.6 Veto Rules (一票否决)

```python
# Rule 1: Sensitivity gate
if sensitivity_flag == True:
    → force "review"  (regardless of score)

# Rule 2: High-stakes conflict gate
if max_conflict_similarity > 0.80 AND target_memory.importance >= 0.7:
    → force "review", mark conflict_ids

# Rule 3: Near-duplicate gate
if max_duplication_similarity > 0.95:
    → force "skip", increment corroboration_count on existing statement
```

### 5.7 Threshold & Action

```python
if auto_confirm_score >= 0.85:
    → create MemoryStatement(status="confirmed")
elif auto_confirm_score < 0.85:
    → create MemoryDraft(status="draft")  # enters Memory Inbox
```

---

## 6. Scheduled Extraction Pipeline

### 6.1 Scheduler

```python
# backend/app/services/memory_scheduler.py (NEW FILE)

from apscheduler.schedulers.background import BackgroundScheduler
from backend.app.config import settings

class MemoryScheduler:
    def __init__(self):
        self._scheduler = BackgroundScheduler()

    def start(self):
        if not settings.MEMORY_SCHEDULED_ENABLED:
            return
        self._scheduler.add_job(
            func=_scheduled_extraction_round,
            trigger="interval",
            minutes=settings.MEMORY_SCHEDULED_INTERVAL_MINUTES,
            id="memory_scheduled_extraction",
            replace_existing=True,
        )
        self._scheduler.start()

    def shutdown(self):
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
```

### 6.2 Extraction Round

```python
def _scheduled_extraction_round():
    """
    每一轮执行:
    1. 查询候选会话 (updated_at > now - interval*3, LIMIT 10)
    2. 过滤: last_extracted_message_id != 最新 message.id
    3. 逐个 session 串行执行提取 (避免 LLM 并发过载)
    4. 记录 ExtractionRun 统计日志
    """
    db = SessionLocal()
    try:
        # Step 1: query candidate sessions
        cutoff = local_now() - timedelta(
            minutes=settings.MEMORY_SCHEDULED_INTERVAL_MINUTES * 3
        )
        sessions = (
            db.query(ChatSession)
            .filter(ChatSession.updated_at >= cutoff)
            .order_by(ChatSession.updated_at.desc())
            .limit(settings.MEMORY_SCHEDULED_MAX_SESSIONS)
            .all()
        )

        stats = {"scanned": len(sessions), "extracted": 0,
                 "auto_confirmed": 0, "inbox": 0, "skipped": 0, "errors": 0}

        for session in sessions:
            try:
                # Step 2: check watermark
                latest_msg = (
                    db.query(ChatMessage)
                    .filter(ChatMessage.session_id == session.id)
                    .order_by(ChatMessage.created_at.desc())
                    .first()
                )
                if not latest_msg or latest_msg.id == session.last_extracted_message_id:
                    continue  # no new messages

                # Step 3: run extraction with watermark
                result = extract_session_memories_scheduled(
                    db, session_id=session.id,
                    last_extracted_message_id=session.last_extracted_message_id,
                    context_window=settings.MEMORY_SCHEDULED_CONTEXT_WINDOW,
                )
                stats["extracted"] += 1
                stats["auto_confirmed"] += result.auto_confirmed
                stats["inbox"] += result.inbox_created
                stats["skipped"] += result.skipped

            except Exception as exc:
                stats["errors"] += 1
                log.error(f"[memory_scheduler] session={session.id} error: {exc}")

        # Step 4: persist run log
        db.add(MemoryExtractionRun(
            trigger_type="scheduled",
            sessions_scanned=stats["scanned"],
            sessions_extracted=stats["extracted"],
            auto_confirmed=stats["auto_confirmed"],
            inbox_created=stats["inbox"],
            skipped=stats["skipped"],
            errors=stats["errors"],
            details=stats,
        ))
        db.commit()

    finally:
        db.close()
```

### 6.3 Watermark-Based Message Loading

```python
def load_session_messages_with_watermark(
    db: Session,
    session_id: str,
    last_extracted_message_id: str,
    context_window: int = 5,
) -> tuple[list[ChatMessage], list[ChatMessage]]:
    """
    Returns:
      context_messages: 前 N 条已提取消息（仅供语境）
      new_messages: 上次提取后的新消息（提取目标）
    """
    all_messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
        .all()
    )

    # Find the split point
    split_idx = 0
    if last_extracted_message_id:
        for i, msg in enumerate(all_messages):
            if msg.id == last_extracted_message_id:
                split_idx = i + 1
                break

    new_messages = all_messages[split_idx:]

    # Context window: messages before split point (already extracted)
    context_start = max(0, split_idx - context_window)
    context_messages = all_messages[context_start:split_idx]

    return context_messages, new_messages
```

### 6.4 Session Summary Generation

```python
def generate_or_update_summary(
    db: Session,
    session: ChatSession,
    new_messages: list[ChatMessage],
) -> str:
    """
    生成或增量更新会话摘要。
    - 首次提取：用全部上下文生成摘要
    - 后续提取：在已有摘要基础上增量追加
    """
    existing_summary = session.summary or ""
    recent_text = "\n".join(
        f"[{m.role}] {m.content or ''}" for m in new_messages
    )

    prompt = SUMMARY_PROMPT.format(
        existing_summary=existing_summary or "(新会话，无已有摘要)",
        recent_messages=recent_text,
    )

    client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=300,
    )
    new_summary = response.choices[0].message.content.strip()
    session.summary = new_summary
    return new_summary
```

### 6.5 Extraction Prompt Structure

```
SYSTEM:
你是一个记忆提取系统。你的任务是从对话中提取用户相关的长期记忆。

输入结构：
1. [会话背景] — 本场对话的整体摘要
2. [上文语境] — 最近已提取的消息，仅供理解语境，**不要从中提取**
3. [待提取消息] — 需要提取的新消息，**只从这里产出候选**

对每条候选，必须输出以下信号：
- content: 陈述内容（一句话，中文）
- statement_type: fact | preference | goal | constraint | decision
                 | project_context | topic_interest | question
- temporal_type: stable | current | episodic
- confidence: 0-1，你对提取正确性的信心
- importance: 0-1，对理解用户的重要性
- explicitness: 0-1，用户是否明确说出 (1.0) vs 推断 (0.3)
- sensitivity_flag: true/false，是否涉及身份、健康、财务、密码等敏感信息
- evidence_message_id: 支撑该记忆的消息 ID

不要提取：
- 临时性的一次性指令
- AI 助手实现细节
- 密码/Token/密钥
- 纯技术错误堆栈

USER:
[会话背景]
{session_summary}

[上文语境 — 仅供理解，不从中提取]
{context_messages}

[待提取消息 — 从这里提取记忆]
{new_messages}

输出严格 JSON。
```

### 6.6 Updated LLM Output Schema

```json
{
  "session_summary": "本场对话中，用户在设计 Prism 记忆系统的定时自动提取改造方案。已确定架构方案（Backend APScheduler）、自动确认决策引擎的多维评分体系、embedding 语义冲突检测等关键技术决策...",
  "candidates": [
    {
      "content": "用户希望记忆系统支持定时自动扫描近期活跃会话并提取记忆",
      "statement_type": "preference",
      "temporal_type": "current",
      "confidence": 0.92,
      "importance": 0.85,
      "explicitness": 0.95,
      "sensitivity_flag": false,
      "evidence_message_id": "msg-uuid-here"
    }
  ]
}
```

---

## 7. Embedding-Based Conflict & Corroboration Detection

### 7.1 Algorithm

```python
def evaluate_semantic_signals(
    db: Session,
    candidate: MemoryCandidate,
    statement_type: str,
) -> SemanticSignals:
    """
    对一条 candidate 执行语义搜索，返回冲突度和印证度。
    """
    # Embed the candidate content
    candidate_vector = embed_text(candidate.content)

    # Search existing confirmed statements in Milvus
    similar = search_memory_vectors(
        text=candidate.content,
        user_id=DEFAULT_USER_ID,
        top_k=10,
    )

    # Filter: only same statement_type for conflict detection
    conflict_similarities = []
    corroboration_similarities = []
    cross_session_ids = set()

    for hit in similar:
        if hit["kind"] != KIND_STATEMENT:
            continue

        # Load the full statement from DB
        statement = db.query(MemoryStatement).filter(
            MemoryStatement.id == hit["memory_id"],
            MemoryStatement.status == MemoryStatus.CONFIRMED,
        ).first()

        if not statement:
            continue

        hit_similarity = hit["score"]  # cosine similarity

        if statement.statement_type == statement_type:
            # Same type: check for conflict
            # Conflict = high similarity but contradictory content
            # Detected via LLM pairwise comparison or rule-based negation check
            if hit_similarity >= 0.75:  # candidate for conflict check
                is_conflict = _check_semantic_conflict(
                    candidate.content, statement.content
                )
                if is_conflict:
                    conflict_similarities.append(hit_similarity)
            elif hit_similarity >= 0.85:  # high similarity, likely corroboration
                corroboration_similarities.append(hit_similarity)

                # Track cross-session corroboration
                if statement.source and statement.source.session_id:
                    cross_session_ids.add(statement.source.session_id)

    max_conflict = max(conflict_similarities) if conflict_similarities else 0.0
    corroboration_boost = min(1.0, len(corroboration_similarities) / 3.0)
    cross_session_boost = 0.0
    if len(cross_session_ids) >= 2:
        cross_session_boost = 1.0
    elif len(cross_session_ids) == 1:
        cross_session_boost = 0.5

    return SemanticSignals(
        max_conflict_similarity=max_conflict,
        corroboration_boost=corroboration_boost,
        cross_session_boost=cross_session_boost,
    )
```

### 7.2 Semantic Conflict Detection

```python
def _check_semantic_conflict(
    new_content: str,
    existing_content: str,
) -> bool:
    """
    判断两条高相似度但可能矛盾的陈述是否真的冲突。

    策略：
    1. 快速否定词扫描：如果一条有明确的否定结构而另一条没有
    2. 如果否定词扫描不确定 → 降级跳过冲突标记（宁漏勿错）
    """
    # Quick negation scan
    negation_patterns = [
        r"不\w{0,2}(?:喜欢|想|需要|会|能|应该|再|用|做|是)",
        r"没有\w+",
        r"拒绝|放弃|停止|取消|不再",
        r"改为|换成|改成",
    ]

    new_has_negation = any(
        re.search(p, new_content) for p in negation_patterns
    )
    existing_has_negation = any(
        re.search(p, existing_content) for p in negation_patterns
    )

    # Conflict: one negates while the other doesn't
    if new_has_negation != existing_has_negation:
        return True

    return False
```

---

## 8. API Changes

### 8.1 Draft Count Endpoint (NEW)

```
GET /api/v1/memories/drafts/count?status=draft

Response:
{
  "count": 7,
  "by_risk": {
    "low": 2,
    "medium": 3,
    "high": 2
  }
}
```

```python
@router.get("/drafts/count")
def count_memory_drafts(
    status: str = "draft",
    db: Session = Depends(get_db),
):
    count = (
        db.query(MemoryDraft)
        .filter(
            MemoryDraft.user_id == DEFAULT_USER_ID,
            MemoryDraft.status == status,
        )
        .count()
    )
    # by risk breakdown
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

### 8.2 Scheduled Trigger Endpoint (for manual override)

```
POST /api/v1/memories/extract/scheduled
→ 立即触发一轮定时提取逻辑（可用于测试或手动干预）

Response:
{
  "run_id": "...",
  "sessions_scanned": 5,
  "sessions_extracted": 3,
  "auto_confirmed": 4,
  "inbox_created": 3,
  "skipped": 2,
  "errors": 0
}
```

---

## 9. Frontend Changes

### 9.1 Navigation Badge

[MainLayout.tsx](frontend/src/layouts/MainLayout.tsx#L108-L113) — "记忆审核" 导航项增加角标：

```tsx
function NavItem({
  to, label, icon: Icon, active, isDark = false, onNavigate,
  badge,  // NEW prop
}: { ... badge?: number }) {
  return (
    <NavLink to={to} ...>
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

### 9.2 Badge Polling Hook

```typescript
// frontend/src/app/useMemoryBadge.ts
import { useEffect, useState } from 'react'
import { memoryApi } from '@/app/api'

export function useMemoryBadge(pollMs = 30_000) {
  const [count, setCount] = useState(0)

  useEffect(() => {
    let cancelled = false
    const poll = () => {
      memoryApi.countDrafts('draft')
        .then(res => { if (!cancelled) setCount(res.count) })
        .catch(() => {})
    }
    poll()
    const id = setInterval(poll, pollMs)
    return () => { cancelled = true; clearInterval(id) }
  }, [pollMs])

  return count
}
```

### 9.3 API Client Addition

```typescript
// frontend/src/app/api.ts
export const memoryApi = {
  // ... existing methods ...

  countDrafts: (status = 'draft') =>
    request<{ count: number; by_risk: Record<string, number> }>(
      `/memories/drafts/count?status=${status}`
    ),
}
```

---

## 10. Backend Lifespan Integration

```python
# backend/app/main.py
from backend.app.services.memory_scheduler import MemoryScheduler

_memory_scheduler: MemoryScheduler | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _memory_scheduler
    # Startup
    _memory_scheduler = MemoryScheduler()
    _memory_scheduler.start()
    yield
    # Shutdown
    if _memory_scheduler:
        _memory_scheduler.shutdown()
```

---

## 11. Benchmark & Evaluation Framework

### 11.1 Key Metrics

| Metric | Definition | Target | Measurement |
|--------|-----------|--------|-------------|
| **Review Burden Reduction (RBR)** | 自动确认数 / (自动确认 + Inbox 待审) | ≥ 40% | 系统统计 |
| **Auto-Confirm Precision (ACP)** | 正确自动确认数 / 总自动确认数 | ≥ 95% | 人工抽样审计 |
| **Auto-Confirm Recall (ACR)** | 正确自动确认数 / (正确自动确认 + 误送审阅数) | ≥ 80% | 人工标注+对照 |
| **Extraction Coverage (EC)** | 被提取会话数 / 活跃会话总数 | ≥ 90% | 系统统计 |
| **Time-to-Inbox (TTI)** | 消息发送 → draft 出现在 Inbox 的延迟 | ≤ 35 min (interval+10) | 时间戳差值 |
| **Conflict Detection Precision (CDP)** | 正确标记冲突的候选 / 所有标记冲突的候选 | ≥ 85% | 人工审核 |
| **Duplicate Skip Precision (DSP)** | 正确跳过的近重复 / 所有跳过的 | ≥ 95% | 人工审核 |
| **Per-Session Extraction Efficiency (PSEE)** | 有效产出 (auto_confirm+inbox) / 总候选数 | ≥ 60% | 系统统计 |

### 11.2 Test Dataset Construction

**数据集来源**：从 Prism 生产/开发环境中收集真实对话记录。

```
Dataset: memory-eval-v1

结构:
├── conversations/           # 20 个完整的 ChatSession 导出
│   ├── session_001.json    # 每条消息带 message_id, role, content, created_at
│   ├── session_002.json
│   └── ...
├── annotations/
│   ├── ground_truth.json   # 人工标注的"应提取"记忆列表
│   │   [
│   │     {
│   │       "session_id": "session_001",
│   │       "message_id": "msg-xxx",
│   │       "should_extract": true,
│   │       "extracted_content": "用户偏好 Python 生态开发",
│   │       "statement_type": "preference",
│   │       "should_auto_confirm": true,
│   │       "reason": "用户明确表达了偏好，技术偏好不敏感"
│   │     }
│   │   ]
│   └── conflicts.json      # 人工标注的冲突/印证对
│       [
│         {
│           "statement_a": "用户使用 VSCode",
│           "statement_b": "用户不使用 VSCode 了",
│           "relation": "conflict"
│         }
│       ]
```

### 11.3 A/B Comparison Methodology

```
Baseline (当前系统):
  - 手动触发 POST /memories/extract/session/{id}
  - 单条 confidence 判别，decision_hint 字段
  - 简单 token 重叠 dedup

Variant (本设计):
  - 定时自动扫描 + 水位线增量提取
  - 9 维复合评分 + 一票否决规则
  - Embedding 语义冲突 + 印证检测

Evaluation Protocol:
  1. 用 ground_truth 标注集运行两套系统
  2. 对比每条 candidate 的最终决策
  3. 计算各指标差异
```

### 11.4 Expected Results (Hypothesis)

| Metric | Baseline (est.) | Target (Variant) | Delta |
|--------|-----------------|------------------|-------|
| RBR (Review Burden Reduction) | ~5% (几乎全手动) | ≥ 40% | +35pp |
| ACP (Auto-Confirm Precision) | N/A (基准几乎不自动确认) | ≥ 95% | — |
| EC (Extraction Coverage) | < 30% (用户手动且易忘) | ≥ 90% | +60pp |
| TTI (Time-to-Inbox) | 不可预测（用户决定何时手动触发）| ≤ 35 min | 质变 |
| CDP (Conflict Detection Precision) | ~60% (token 重叠) | ≥ 85% (embedding) | +25pp |

### 11.5 Smoke Test Procedure

```bash
# 1. Prepare test data
python -m backend.scripts.seed_eval_sessions  # 创建 5 个带标注的测试会话

# 2. Run baseline extraction
python -m backend.scripts.eval_baseline \
  --sessions 5 \
  --output eval/results/baseline_$(date +%Y%m%d_%H%M).json

# 3. Run variant extraction
python -m backend.scripts.eval_variant \
  --sessions 5 \
  --output eval/results/variant_$(date +%Y%m%d_%H%M).json

# 4. Compare
python -m backend.scripts.compare_eval \
  --baseline eval/results/baseline_*.json \
  --variant eval/results/variant_*.json \
  --output eval/results/comparison_$(date +%Y%m%d_%H%M).md

# 5. Auto-confirm precision audit (human review)
# Generate a random sample of 50 auto-confirmed statements
# Human annotator marks each as correct/incorrect
python -m backend.scripts.sample_auto_confirmed \
  --count 50 \
  --output eval/audit/sample_$(date +%Y%m%d).json
```

### 11.6 Continuous Monitoring Dashboard (Future)

建议在 Memory Inbox 页面添加一个"统计"标签页：

```
┌─────────────────────────────────────────────┐
│  Memory System Stats (Last 7 Days)           │
│                                              │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ │
│  │ Sessions  │ │ Auto-     │ │ Inbox     │ │
│  │ Scanned   │ │ Confirmed │ │ Pending   │ │
│  │   42      │ │   18      │ │   7       │ │
│  └───────────┘ └───────────┘ └───────────┘ │
│                                              │
│  Auto-Confirm Rate:  ████████░░ 72%          │
│  Avg Confidence:     ████████░░ 0.83         │
│  Extraction Runs:    56 (0 errors)           │
└─────────────────────────────────────────────┘
```

---

## 12. Error Handling & Resilience

| Scenario | Handling |
|----------|----------|
| LLM API 不可用 | 跳过本轮，记录 error 日志，下次重试 |
| LLM 返回无效 JSON | 跳过该 session，记录 parse error 到 ExtractionRun |
| Embedding API 不可用 | 降级：跳过语义信号，仅用规则维度计算 auto_confirm_score；sensitivity_flag=true 仍送审阅 |
| Milvus 不可用 | 降级：semantic_conflict=0, corroboration=0, cross_session=0；仅用 LLM 输出 + type_risk 计算 |
| 单个 session 提取失败 | 不影响同轮其他 session；error count+1，继续 |
| DB 写入失败 | 回滚当前 session 的所有写入，error count+1，继续 |
| Scheduler 异常退出 | 不影响 Backend 正常 API 服务，APScheduler 静默失败 |

---

## 13. Migration & Rollback

### 13.1 Migration

```
1. 数据库迁移：运行 ALTER TABLE 添加新列（所有新列有 DEFAULT，不影响现有数据）
2. 部署新代码
3. Backend 启动时 auto_migrate 自动检测并创建 memory_extraction_run 表
4. MemoryScheduler 自动启动（如 MEMORY_SCHEDULED_ENABLED=1）
```

### 13.2 Rollback

```
1. 设置 MEMORY_SCHEDULED_ENABLED=0 → 停止定时调度
2. 旧代码的 memory_extraction.py 兼容新列（DEFAULT 值保证不报错）
3. 新列保留（向后兼容），可在下次迁移中移除
```

---

## 14. Out of Scope

- 记忆自动合并/去重 UI 增强
- 记忆过期自动归档
- User Profile 全量合成
- Neo4j 图存储迁移
- 多用户隔离的定时策略
- 前端统计仪表盘的完整实现

---

## 15. Implementation Phases

### Phase 1: Core Engine (backend only)

- Data model changes (ChatSession + MemoryDraft/Statement new columns)
- `memory_scheduler.py` — APScheduler lifecycle
- `memory_extraction.py` upgrade — watermark loading, summary generation, new prompt, signal parsing
- Auto-confirm decision engine (scoring + veto rules)
- `GET /drafts/count` endpoint
- `POST /memories/extract/scheduled` trigger endpoint
- `memory_extraction_run` table + logging

### Phase 2: Semantic Signals

- Embedding-based conflict detection integration
- Corroboration search integration
- Fallback paths for embedding/Milvus unavailability

### Phase 3: Frontend

- Navigation badge UI
- Badge polling hook
- Memory Inbox count display

### Phase 4: Evaluation

- Build eval dataset
- Run A/B comparison
- Iterate on weights/thresholds based on results

---

## 16. Key Files Summary

| File | Change | Effort |
|------|--------|--------|
| `backend/app/models/chat.py` | +3 fields on ChatSession | Small |
| `backend/app/models/memory.py` | +4 fields on MemoryDraft, +4 on MemoryStatement, +1 new table | Medium |
| `backend/app/config.py` | +5 settings | Small |
| `backend/app/services/memory_scheduler.py` | **NEW** (~150 LOC) | Medium |
| `backend/app/services/memory_extraction.py` | Major upgrade (~200 LOC delta) | Large |
| `backend/app/prompts/memory_extraction.py` | Prompt redesign (~80 LOC delta) | Medium |
| `backend/app/api/memories.py` | +2 endpoints (~60 LOC) | Small |
| `backend/app/main.py` | +5 lines lifespan integration | Small |
| `frontend/src/app/api.ts` | +1 method | Small |
| `frontend/src/layouts/MainLayout.tsx` | badge prop + rendering | Small |
| `frontend/src/pages/MemoryInboxPage.tsx` | auto-refresh on mount | Small |

---

*Design completed. Next: writing-plans skill for detailed implementation plan.*
