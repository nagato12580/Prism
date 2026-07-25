"""Task 4: Knowledge Skill declares exactly the six authorized tools and the
rendered instructions never reference overlapping/demoted tools."""

from engine.app.agent.tools import registered_tool_names


SIX = {
    "list_kbs",
    "query_kb",
    "search_file",
    "find_kb_document",
    "open_kb_document",
    "get_mindmap",
}

# Demoted / superseded tools that must NOT be model-visible via the Skill.
OVERLAPPING = {
    "entity_graph_search",
    "governed_knowledge_search",
    "governed_knowledge_v2",
    "knowledge_topic_search",
    "knowledge_evidence_search",
    "knowledge_material_search",
    "raw_document_search",
    "page_index_get_document",
    "page_index_get_document_structure",
    "page_index_get_page_content",
}


def test_knowledge_tool_names_are_exactly_the_six():
    from engine.app.agent.knowledge_skill import KNOWLEDGE_TOOL_NAMES

    assert set(KNOWLEDGE_TOOL_NAMES) == SIX


def test_knowledge_skill_declares_only_registered_tools():
    from engine.app.agent.knowledge_skill import KNOWLEDGE_TOOL_NAMES

    registered = set(registered_tool_names())
    assert set(KNOWLEDGE_TOOL_NAMES) <= registered


def test_render_knowledge_skill_mentions_each_tool_and_never_overlapping():
    from engine.app.agent.knowledge_skill import render_knowledge_skill

    prompt = render_knowledge_skill()
    for name in SIX:
        assert name in prompt, f"skill prompt missing tool: {name}"
    for name in OVERLAPPING:
        assert name not in prompt, f"skill prompt leaks demoted tool: {name}"


def test_render_knowledge_skill_states_read_only_and_citation_rules():
    from engine.app.agent.knowledge_skill import render_knowledge_skill

    prompt = render_knowledge_skill().lower()
    assert "read-only" in prompt or "只读" in prompt
    assert "evidence" in prompt or "证据" in prompt
    assert "citation" in prompt or "引用" in prompt
    # Cite the evidence ids returned this run, not fabricated ones.
    assert "evidence_id" in prompt or "证据 id" in prompt or "证据id" in prompt


def test_render_knowledge_skill_attachment_separation():
    from engine.app.agent.knowledge_skill import render_knowledge_skill

    prompt = render_knowledge_skill().lower()
    # Attachments/uploads are a separate channel, not retrieved by these tools.
    assert "attachment" in prompt or "附件" in prompt or "上传" in prompt


def test_compose_system_prompt_is_additive_only_when_scope_active():
    from engine.app.agent.knowledge_skill import (
        compose_system_prompt_with_knowledge_skill,
        render_knowledge_skill,
    )

    base = "BASE PROMPT"
    # No scope -> prompt unchanged (legacy callers keep exact behavior).
    assert compose_system_prompt_with_knowledge_skill(base, has_knowledge_scope=False) == base
    composed = compose_system_prompt_with_knowledge_skill(base, has_knowledge_scope=True)
    assert composed.startswith(base)
    assert render_knowledge_skill() in composed


def test_render_knowledge_skill_prioritizes_kb_over_memory_for_document_questions():
    from engine.app.agent.knowledge_skill import render_knowledge_skill

    prompt = render_knowledge_skill()
    assert "memory_search" in prompt
    assert "query_kb" in prompt
    assert "资料" in prompt or "文档" in prompt or "document" in prompt.lower()
    assert "优先" in prompt or "first" in prompt.lower()
