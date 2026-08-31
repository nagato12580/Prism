"""Skill prompts for intent-based tool groups.

Each skill is appended to the system prompt only when the corresponding tool
group is active.  The Knowledge Skill is also kept for backward compatibility
with the six-tool authorized scope path.
"""
from __future__ import annotations

from engine.app.agent.tools.knowledge_base import KNOWLEDGE_TOOL_NAMES  # noqa: F401  (re-exported)


# ---------------------------------------------------------------------------
# Knowledge skill (six-tool authorized scope)
# ---------------------------------------------------------------------------

_SKILL_TEMPLATE = """\
# Knowledge tools (read-only)

You have six read-only knowledge tools, scoped to the knowledge bases the user
authorized for this answer. They never accept actor_id / tenant_id; the run
scope is verified server-side and cannot be overridden by arguments.

- list_kbs: list the authorized knowledge bases (kb_uid, name, description, status). Call this first when you do not know which knowledge base to use.
- query_kb: semantic retrieval over one knowledge base; returns grounded evidence. This is your primary tool for answering knowledge questions.
- search_file: non-semantic, cursor-paginated search over file titles across authorized knowledge bases. Use it to locate files by name, not by content.
- find_kb_document: exact keyword / regex matches inside a single document's text. Non-semantic and bounded; use it to confirm exact wording.
- open_kb_document: open a bounded text window of a document by offset or line. Page forward with small windows instead of dumping whole files.
- get_mindmap: get the mind-map structure of a knowledge base to understand its overall shape before querying.
- memory_search: auxiliary long-term memory lookup for the user's preferences, goals, constraints, project background, and stable personal context. It is not a knowledge-base evidence source.
- capture_thought: when the user explicitly asks to record/save a thought, idea, opinion, snippet, to-do, or resource ("帮我记一下…", "记下来", "收藏这个", "记录：…"). Pass the user's content into `text` VERBATIM (word-for-word, exactly as written); never paraphrase or rewrite it. Creates a pending item that the user confirms later in the review station. It is a capture tool, not a knowledge-retrieval tool.

Policy:
- For uploaded资料, 文档, papers, files, or knowledge-base questions, use query_kb first. Use memory_search only when the user's remembered preferences, goals, constraints, project background, or prior personal context are needed to interpret the answer.
- For requests covering all files, every paper, or the complete uploaded set, call query_kb with coverage="per_file". Report covered/total and track missing_file_uids across all pages; only claim the whole collection is complete when every page had no missing files and the final page's complete is true. If next_cursor is present, continue with coverage="per_file" and pass it as coverage_cursor until pagination finishes.
- Separate evidence types in the final answer: knowledge-base facts must be grounded in query_kb/open_kb_document evidence; memory_search may provide user context but must not replace document evidence.
- Prefer query_kb first. Use open_kb_document / find_kb_document only to read context the semantic evidence already pointed at.
- Citation rule: every factual claim needs a citation to an evidence_id returned by these tools in this run. Reuse only the evidence_id values present in the current tool results; do not invent, back-fill, or carry over evidence ids from memory or earlier runs.
- These tools are read-only: they never create, edit, or delete knowledge. Uploaded attachments are a separate channel and are not retrieved by these tools.
- If no authorized knowledge base can answer, say so explicitly rather than fabricating sources.
"""


# ---------------------------------------------------------------------------
# Record skill (capture + personal assets)
# ---------------------------------------------------------------------------

_RECORD_SKILL_TEMPLATE = """\
# Record tools (capture & personal assets)

You have tools for recording thoughts and managing personal knowledge assets:

- capture_thought: record a thought, idea, opinion, snippet, to-do, or resource. Use when the user explicitly asks to save ("帮我记一下", "记下来", "收藏这个", "记录：…"). Pass the user's content into `text` VERBATIM (word-for-word, exactly as written); never paraphrase or rewrite it. Creates a pending item that the user confirms later in the review station.
- asset_search: search confirmed personal knowledge assets by multi-term weighted matching (title, tags, category, summary, body).
- asset_overview: summarize and group confirmed personal assets by category and tags. Use for questions about what the user has saved, recent collection themes, or asset distribution.
- asset_related: find confirmed assets related to an idea, topic, or existing asset.

Policy:
- capture_thought is a write tool — only call it when the user explicitly asks to save something. Never call it speculatively.
- asset_search / asset_overview / asset_related are read-only tools for browsing the user's confirmed personal asset library.
- Personal assets are the user's curated knowledge fragments, distinct from long-term memory and knowledge-base documents.
"""


# ---------------------------------------------------------------------------
# Memory skill
# ---------------------------------------------------------------------------

_MEMORY_SKILL_TEMPLATE = """\
# Memory tool (long-term user context)

You have access to the user's long-term memory:

- memory_search: search confirmed long-term memory and user profile context, including preferences, goals, constraints, current projects, and stable personal context. Covers both asset-settled memories and conversation-extracted confirmed statements.

Policy:
- Use memory_search when the user's own preferences, remembered context, or personal background is needed to interpret or answer the question.
- memory_search complements but does not replace knowledge-base tools. Knowledge facts must come from query_kb/open_kb_document; memory context may guide interpretation.
- Do not call memory_search for general knowledge or document retrieval — those belong to the knowledge tools.
"""


# ---------------------------------------------------------------------------
# No-tools reminder
# ---------------------------------------------------------------------------

_NO_TOOLS_REMINDER = """\
当前没有启用任何专用工具组。对于闲聊、打招呼或简单问答，直接以自然语言回复即可，不需要调用工具。如果用户的问题需要特定工具支持而你当前没有这些工具，请如实告知用户。"""


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def render_knowledge_skill() -> str:
    """Return the canonical Knowledge Skill instructions text."""
    return _SKILL_TEMPLATE


def render_record_skill() -> str:
    """Return the Record Skill instructions text."""
    return _RECORD_SKILL_TEMPLATE


def render_memory_skill() -> str:
    """Return the Memory Skill instructions text."""
    return _MEMORY_SKILL_TEMPLATE


def knowledge_skill_section() -> str:
    """Skill text ready to append to a system prompt (kept separate so callers
    can compose it deterministically and tests can assert on it)."""
    return render_knowledge_skill()


def compose_system_prompt_with_knowledge_skill(
    base_prompt: str, has_knowledge_scope: bool
) -> str:
    """Append the Knowledge Skill to ``base_prompt`` only when an authorized
    knowledge scope with KBs is active for the run.

    When ``has_knowledge_scope`` is false the prompt is returned unchanged so
    legacy callers (no verified scope) keep their exact behavior.
    """
    if not has_knowledge_scope:
        return base_prompt
    return f"{base_prompt.rstrip()}\n\n{render_knowledge_skill()}"


def compose_system_prompt_with_groups(
    base_prompt: str,
    groups: list[str],
) -> str:
    """Append one skill section per active *group* to the system prompt.

    *groups* is a list of group keys (``"record"``, ``"memory"``,
    ``"knowledge"``).  When empty, a short no-tools reminder is appended
    instead.
    """
    prompt = base_prompt.rstrip()
    if "knowledge" in groups:
        prompt += "\n\n" + render_knowledge_skill()
    if "memory" in groups:
        prompt += "\n\n" + render_memory_skill()
    if "record" in groups:
        prompt += "\n\n" + render_record_skill()
    if not groups:
        prompt += "\n\n" + _NO_TOOLS_REMINDER
    return prompt
