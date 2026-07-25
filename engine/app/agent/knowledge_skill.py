"""Knowledge Skill: model-facing instructions for the six authorized tools.

The Skill is bound to the agent run only when the verified
``AuthorizedKnowledgeScope`` carries a non-empty ``allowed_kb_uids`` (Task 4
runner wiring). It instructs the model to use exactly the six read-only tools,
to cite the ``evidence_id`` values returned in the current run, and to treat
attachments as a separate channel.
"""
from __future__ import annotations

from engine.app.agent.tools.knowledge_base import KNOWLEDGE_TOOL_NAMES  # noqa: F401  (re-exported)


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

Policy:
- For uploaded资料, 文档, papers, files, or knowledge-base questions, use query_kb first. Use memory_search only when the user's remembered preferences, goals, constraints, project background, or prior personal context are needed to interpret the answer.
- Separate evidence types in the final answer: knowledge-base facts must be grounded in query_kb/open_kb_document evidence; memory_search may provide user context but must not replace document evidence.
- Prefer query_kb first. Use open_kb_document / find_kb_document only to read context the semantic evidence already pointed at.
- Citation rule: every factual claim needs a citation to an evidence_id returned by these tools in this run. Reuse only the evidence_id values present in the current tool results; do not invent, back-fill, or carry over evidence ids from memory or earlier runs.
- These tools are read-only: they never create, edit, or delete knowledge. Uploaded attachments are a separate channel and are not retrieved by these tools.
- If no authorized knowledge base can answer, say so explicitly rather than fabricating sources.
"""


def render_knowledge_skill() -> str:
    """Return the canonical Knowledge Skill instructions text."""
    return _SKILL_TEMPLATE


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
