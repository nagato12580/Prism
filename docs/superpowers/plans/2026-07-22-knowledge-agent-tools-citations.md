# Knowledge Agent Tools and Citation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Prism agents six authorized, typed knowledge tools and enforce that every `[Kx]` citation resolves to Evidence produced in the current run.

**Architecture:** Backend signs an `AuthorizedKnowledgeScope` when starting a Chat/Agent run. Engine verifies it before building ToolContext; tool inputs never accept actor/tenant, and all tools use one typed envelope and the retrieval/Evidence services from Plan 3.

**Tech Stack:** FastAPI, Pydantic 2, HMAC-SHA256 service tokens, LangChain StructuredTool, MySQL, NDJSON, pytest

---

## Prerequisite

Complete Foundation, Ingestion, and Retrieval/Evaluation plans. Do not reimplement retrieval in a tool.

## File Structure

- Create: `backend/app/security/knowledge_scope.py` — sign run scope.
- Create: `engine/app/security/__init__.py`
- Create: `engine/app/security/knowledge_scope.py` — verify run scope.
- Modify: `engine/app/agent/tools/base.py` — ToolContext includes verified scope.
- Create: `engine/app/agent/tools/contracts.py` — generic typed envelope.
- Create: `engine/app/agent/tools/knowledge_base.py` — six tool builders.
- Modify: `engine/app/agent/tools/__init__.py` — register only stable tools.
- Create: `engine/app/agent/knowledge_skill.py` — Skill instructions/activation policy.
- Modify: `engine/app/agent/prompts.py` and `engine/app/agent/runner.py` — bind Skill/tools consistently.
- Create: `engine/app/agent/citations.py` — assign and validate Evidence IDs.
- Modify: `engine/app/agent/tools/evidence.py` and `engine/app/agent/trace.py` — persist canonical Evidence.
- Modify: `engine/app/agent/events.py` and `engine/app/api/chat.py` — versioned Evidence/health events.
- Create: `backend/app/api/agent_chat_proxy.py` — authorized Backend proxy.
- Modify: `backend/app/api/chat.py` — persistence integration.
- Create/modify tests listed below.

## Task 1: Sign and Verify AuthorizedKnowledgeScope

**Files:**
- Create: `backend/app/security/knowledge_scope.py`
- Create: `engine/app/security/knowledge_scope.py`
- Modify: `backend/app/config.py`
- Modify: `engine/app/config.py`
- Create: `backend/tests/test_knowledge_scope_signing.py`
- Create: `engine/tests/test_knowledge_scope_verification.py`

- [ ] **Step 1: Write failing token tests**

```python
def test_scope_round_trip_and_expiry(monkeypatch):
    from backend.app.security.knowledge_scope import AuthorizedKnowledgeScope, sign_scope
    from engine.app.security.knowledge_scope import ExpiredKnowledgeScope, verify_scope

    scope = AuthorizedKnowledgeScope(
        actor_id="alice", tenant_id="tenant-a", allowed_kb_uids=("kb-a",), run_id="run-1", expires_at=200,
    )
    token = sign_scope(scope, secret="secret")
    assert verify_scope(token, secret="secret", now=100).allowed_kb_uids == ("kb-a",)
    try:
        verify_scope(token, secret="secret", now=201)
    except ExpiredKnowledgeScope:
        pass
    else:
        raise AssertionError("expired scope accepted")


def test_scope_signature_rejects_tampering():
    token = make_scope_token().replace("kb-a", "kb-b")
    with pytest.raises(InvalidKnowledgeScope):
        verify_scope(token, secret="secret", now=100)
```

- [ ] **Step 2: Run and verify missing modules**

Run: `python -m pytest backend/tests/test_knowledge_scope_signing.py engine/tests/test_knowledge_scope_verification.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement canonical JSON + HMAC token**

```python
# backend/app/security/knowledge_scope.py
import base64, hashlib, hmac, json
from pydantic import BaseModel, ConfigDict


class AuthorizedKnowledgeScope(BaseModel):
    model_config = ConfigDict(frozen=True)
    actor_id: str
    tenant_id: str
    allowed_kb_uids: tuple[str, ...]
    run_id: str
    expires_at: int


def sign_scope(scope: AuthorizedKnowledgeScope, secret: str) -> str:
    payload = json.dumps(scope.model_dump(), sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return f"{base64.urlsafe_b64encode(payload).decode().rstrip('=')}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"
```

Engine verifier decodes, recomputes signature with `hmac.compare_digest`, validates Pydantic shape and expiry. Secret is required from environment in non-test mode; never log token/payload.

- [ ] **Step 4: Run and commit**

```bash
python -m pytest backend/tests/test_knowledge_scope_signing.py engine/tests/test_knowledge_scope_verification.py -v
git add backend/app/security/knowledge_scope.py engine/app/security backend/app/config.py engine/app/config.py backend/tests/test_knowledge_scope_signing.py engine/tests/test_knowledge_scope_verification.py
git commit -m "feat(agent): 增加签名知识库运行范围"
```

## Task 2: Define One Typed Tool Envelope

**Files:**
- Create: `engine/app/agent/tools/contracts.py`
- Create: `engine/tests/test_knowledge_tool_contracts.py`

- [ ] **Step 1: Write failing envelope tests**

```python
def test_tool_envelope_serializes_success_and_error():
    from engine.app.agent.tools.contracts import ToolEnvelope, ToolProblem

    ok = ToolEnvelope.ok({"items": []}, trace_id="trace-1")
    assert ok.model_dump()["status"] == "ok"
    error = ToolEnvelope.error(ToolProblem(code="KB_NOT_ALLOWED", message="denied", retryable=False), "trace-2")
    assert error.error.code == "KB_NOT_ALLOWED"
    assert error.data is None
```

- [ ] **Step 2: Run and verify missing contract**

Run: `python -m pytest engine/tests/test_knowledge_tool_contracts.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement generic Pydantic envelope**

```python
from typing import Generic, Literal, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class ToolWarning(BaseModel):
    code: str
    message: str


class ToolProblem(BaseModel):
    code: str
    message: str
    retryable: bool = False


class ToolEnvelope(BaseModel, Generic[T]):
    status: Literal["ok", "no_hits", "degraded", "error"]
    data: T | None = None
    warnings: list[ToolWarning] = Field(default_factory=list)
    error: ToolProblem | None = None
    trace_id: str

    @classmethod
    def ok(cls, data: T, trace_id: str):
        return cls(status="ok", data=data, trace_id=trace_id)

    @classmethod
    def error(cls, problem: ToolProblem, trace_id: str):
        return cls(status="error", error=problem, trace_id=trace_id)
```

Add `no_hits` and `degraded` constructors. Domain errors map to these envelopes; unexpected exceptions remain Tool execution errors and are traced.

- [ ] **Step 4: Run and commit**

```bash
python -m pytest engine/tests/test_knowledge_tool_contracts.py -v
git add engine/app/agent/tools/contracts.py engine/tests/test_knowledge_tool_contracts.py
git commit -m "feat(agent): 统一知识工具返回契约"
```

## Task 3: Implement the Six Read-Only Knowledge Tools

**Files:**
- Create: `engine/app/agent/tools/knowledge_base.py`
- Modify: `engine/app/agent/tools/base.py`
- Modify: `engine/app/agent/tools/__init__.py`
- Create: `engine/tests/test_knowledge_base_tools.py`

- [ ] **Step 1: Write failing authorization and shape tests**

```python
def test_query_kb_rejects_kb_outside_run_scope(tool_context):
    tool_context.knowledge_scope = scope(allowed=("kb-a",))
    tool = build_tools(tool_context)["query_kb"]
    result = tool.invoke({"kb_uid": "kb-b", "query_text": "secret"})
    assert result["status"] == "error"
    assert result["error"]["code"] == "KB_NOT_ALLOWED"


def test_list_kbs_returns_safe_fields_only(tool_context):
    result = build_tools(tool_context)["list_kbs"].invoke({})
    assert set(result["data"]["items"][0]) == {"kb_uid", "name", "description", "status"}


def test_open_document_is_windowed(tool_context):
    result = build_tools(tool_context)["open_kb_document"].invoke({"kb_uid": "kb-a", "file_uid": "file-a", "offset": 0, "window_size": 500})
    assert result["data"]["has_more_after"] is True
    assert "storage_uri" not in str(result)
```

- [ ] **Step 2: Run and verify missing tools**

Run: `python -m pytest engine/tests/test_knowledge_base_tools.py -v`

Expected: FAIL.

- [ ] **Step 3: Add verified scope to ToolContext**

```python
@dataclass
class ToolContext:
    db: Session
    trace_id: str
    run_id: str
    knowledge_scope: AuthorizedKnowledgeScope
    retrieval_service: RetrievalService
```

Keep other existing ToolContext dependencies. Add one guard:

```python
def require_allowed_kb(ctx: ToolContext, kb_uid: str) -> None:
    if kb_uid not in ctx.knowledge_scope.allowed_kb_uids:
        raise KnowledgeToolDenied(kb_uid)
```

- [ ] **Step 4: Implement exact input schemas and tools**

```python
class QueryKbInput(BaseModel):
    kb_uid: str
    query_text: str = Field(min_length=1, max_length=4000)
    mode: Literal["standard", "deep"] = "standard"
    file_filter: tuple[str, ...] = ()


class SearchFileInput(BaseModel):
    kb_uid: str | None = None
    query: str | None = None
    cursor: str | None = None
    limit: int = Field(default=50, ge=1, le=300)
    media_types: tuple[str, ...] = ()


class FindDocumentInput(BaseModel):
    kb_uid: str
    file_uid: str
    patterns: list[str] = Field(min_length=1, max_length=20)
    use_regex: bool = False
    case_sensitive: bool = False
    max_windows: int = Field(default=5, ge=1, le=20)
    window_size: int = Field(default=80, ge=1, le=200)


class OpenDocumentInput(BaseModel):
    kb_uid: str
    file_uid: str
    line: int | None = Field(default=None, ge=1)
    offset: int | None = Field(default=None, ge=0)
    window_size: int = Field(default=500, ge=1, le=2000)
```

Build/register exactly: `list_kbs`, `query_kb`, `search_file`, `find_kb_document`, `open_kb_document`, `get_mindmap`. Search uses real database cursor pagination; find is keyword/regex and labels itself non-semantic.

- [ ] **Step 5: Remove overlapping knowledge tools from model-visible registry**

Keep old tool functions only as internal adapters until cutover. `entity_graph_search`, governed knowledge variants, material/raw searches, and separate deep tool must not be simultaneously visible to the model.

- [ ] **Step 6: Run and commit**

```bash
python -m pytest engine/tests/test_knowledge_base_tools.py engine/tests/test_agent_tools.py engine/tests/test_deep_knowledge_search_tool.py -v
git add engine/app/agent/tools engine/tests/test_knowledge_base_tools.py engine/tests/test_agent_tools.py
git commit -m "feat(agent): 增加六个授权知识工具"
```

## Task 4: Bind Knowledge Skill and Tool Visibility Consistently

**Files:**
- Create: `engine/app/agent/knowledge_skill.py`
- Modify: `engine/app/agent/prompts.py`
- Modify: `engine/app/agent/runner.py`
- Modify: `engine/app/agent/tools/__init__.py`
- Create: `engine/tests/test_knowledge_skill.py`

- [ ] **Step 1: Write failing registry/prompt consistency test**

```python
def test_knowledge_skill_declares_only_registered_tools():
    from engine.app.agent.knowledge_skill import KNOWLEDGE_TOOL_NAMES, render_knowledge_skill
    from engine.app.agent.tools import registered_tool_names

    assert set(KNOWLEDGE_TOOL_NAMES) <= set(registered_tool_names())
    prompt = render_knowledge_skill()
    assert "query_kb" in prompt
    assert "entity_graph_search" not in prompt
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest engine/tests/test_knowledge_skill.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement Skill instructions**

`render_knowledge_skill()` must instruct the model to list when scope is unknown, query first, open for context, find for exact terms, search_file for filenames, mindmap for structure, and cite Evidence IDs. It must state tools are read-only and attachments are separate.

Runner includes the Skill only when `allowed_kb_uids` is non-empty and binds the same six tools. There is no filesystem-read activation requirement in Prism.

- [ ] **Step 4: Run and commit**

```bash
python -m pytest engine/tests/test_knowledge_skill.py engine/tests/test_agent_runner.py -v
git add engine/app/agent/knowledge_skill.py engine/app/agent/prompts.py engine/app/agent/runner.py engine/app/agent/tools/__init__.py engine/tests/test_knowledge_skill.py
git commit -m "feat(agent): 绑定知识 Skill 与工具可见性"
```

## Task 5: Assign and Validate Current-Run Citations

**Files:**
- Create: `engine/app/agent/citations.py`
- Modify: `engine/app/agent/tools/evidence.py`
- Modify: `engine/app/agent/trace.py`
- Create: `engine/tests/test_citation_validation.py`
- Modify: `engine/tests/test_agent_evidence.py`

- [ ] **Step 1: Write failing citation tests**

```python
def test_assigns_stable_short_ids_in_first_seen_order():
    from engine.app.agent.citations import CitationRegistry

    registry = CitationRegistry()
    assert registry.register(evidence("chunk-b")) == "K1"
    assert registry.register(evidence("chunk-a")) == "K2"
    assert registry.register(evidence("chunk-b")) == "K1"


def test_unknown_citation_is_reported_not_resolved():
    registry = registry_with("K1")
    result = registry.validate("Answer [K1] and [K9]")
    assert result.valid_ids == ("K1",)
    assert result.invalid_ids == ("K9",)
```

- [ ] **Step 2: Run and verify missing registry**

Run: `python -m pytest engine/tests/test_citation_validation.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement run-local CitationRegistry**

Registry keys Evidence by `(kb_uid, file_uid, chunk_uid, index_generation)`, assigns `K1...`, injects IDs into Evidence sent to the model, parses citations with `\[K\d+\]`, and returns valid/invalid lists. Invalid citations remain visible in trace warnings and are not converted to source cards.

- [ ] **Step 4: Persist Evidence snapshot before answer completion**

Trace persistence stores Evidence DTO and short ID for the current run. It never re-resolves against a later active generation.

- [ ] **Step 5: Run and commit**

```bash
python -m pytest engine/tests/test_citation_validation.py engine/tests/test_agent_evidence.py engine/tests/test_agent_trace_recorder.py -v
git add engine/app/agent/citations.py engine/app/agent/tools/evidence.py engine/app/agent/trace.py engine/tests/test_citation_validation.py engine/tests/test_agent_evidence.py
git commit -m "feat(agent): 增加可验证的知识引用"
```

## Task 6: Version Chat NDJSON and Proxy Through Backend

**Files:**
- Modify: `engine/app/agent/events.py`
- Modify: `engine/app/api/chat.py`
- Create: `backend/app/api/agent_chat_proxy.py`
- Modify: `backend/app/api/chat.py`
- Modify: `backend/app/api/__init__.py`
- Create: `engine/tests/test_chat_event_contract_v2.py`
- Create: `backend/tests/test_agent_chat_proxy.py`

- [ ] **Step 1: Write failing event/proxy tests**

```python
def test_sources_event_contains_seq_trace_health_and_evidence():
    event = sources_event(seq=4, trace_id="t1", run_id="r1", evidence=[evidence("K1")], retrieval_health={"dense": "ok"})
    assert event["seq"] == 4
    assert event["evidence"][0]["evidence_id"] == "K1"
    assert event["retrieval_health"]["dense"] == "ok"


def test_backend_proxy_signs_only_authorized_kbs(client, fake_engine):
    response = client.post("/api/v1/chat/answer", json={"query": "x", "kb_uids": ["kb-a", "kb-forbidden"]})
    assert response.status_code == 403
    assert fake_engine.calls == []
```

- [ ] **Step 2: Run and verify failures**

Run: `python -m pytest engine/tests/test_chat_event_contract_v2.py backend/tests/test_agent_chat_proxy.py -v`

Expected: FAIL.

- [ ] **Step 3: Add monotonic event metadata**

Every NDJSON event includes `seq`, `trace_id`, `run_id`, and `event_version=2`. Sources include canonical Evidence/health/warnings. Error events use code/message/retryable and never include stack/provider payload.

- [ ] **Step 4: Implement streaming proxy**

Backend resolves requested/default KBs with `KnowledgeAccessPolicy`, signs AuthorizedKnowledgeScope, forwards request to Engine using `httpx.AsyncClient.stream`, persists message/process snapshots, and streams bytes without buffering the whole answer. Client disconnect cancels upstream request.

- [ ] **Step 5: Run and commit**

```bash
python -m pytest engine/tests/test_chat_event_contract_v2.py backend/tests/test_agent_chat_proxy.py backend/tests/test_chat_api.py engine/tests/test_answer_stream_agent.py -v
git add engine/app/agent/events.py engine/app/api/chat.py backend/app/api/agent_chat_proxy.py backend/app/api/chat.py backend/app/api/__init__.py engine/tests/test_chat_event_contract_v2.py backend/tests/test_agent_chat_proxy.py
git commit -m "feat(agent): 代理并版本化知识问答事件"
```

## Plan Verification

- [ ] Run all focused tests from Tasks 1–6.
- [ ] Run full existing Agent/Chat suites.
- [ ] Verify a forbidden `kb_uid` is rejected before Engine retrieval.
- [ ] Verify no Tool input schema includes `actor_id` or `tenant_id`.
- [ ] Verify every emitted source card ID is present in persisted current-run Evidence.
- [ ] Verify NDJSON event sequences are monotonic and upstream cancellation works.
- [ ] Record commits in roadmap.
