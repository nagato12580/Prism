from engine.app.agent.continuation import (
    AgentContinuation,
    continuation_from_history,
    is_bare_continuation,
    resolve_effective_objective,
)


STATE = {
    "version": 1,
    "objective": "层次锚定的超参数怎么设置？",
    "kb_uid": "kb-a",
    "file_uid": "file-a",
    "next_offset": 35766,
    "has_more_after": True,
}


def test_bare_continuation_allowlist_is_narrow():
    for query in ("继续", "  继续读？  ", "继续读取", "接着读！", "往下读。"):
        assert is_bare_continuation(query)

    assert not is_bare_continuation("继续找学习率并比较各数据集")


def test_latest_assistant_state_resolves_hyperparameter_objective():
    history = [
        {"role": "user", "content": "层次锚定的超参数怎么设置？"},
        {"role": "assistant", "content": "是否继续？", "continuation": STATE},
    ]

    state = continuation_from_history(history)

    assert state == AgentContinuation(**STATE)
    assert resolve_effective_objective("继续", history, state) == STATE["objective"]
    assert state.to_dict() == STATE


def test_older_state_does_not_activate_when_latest_assistant_lacks_state():
    history = [
        {"role": "user", "content": "层次锚定的超参数怎么设置？"},
        {"role": "assistant", "content": "旧回答", "continuation": STATE},
        {"role": "assistant", "content": "最新回答"},
    ]

    assert continuation_from_history(history) is None


def test_malformed_version_99_state_falls_back_to_last_substantive_user_question():
    history = [
        {"role": "user", "content": "层次锚定的超参数怎么设置？"},
        {"role": "assistant", "content": "是否继续？", "continuation": {"version": 99}},
    ]

    state = continuation_from_history(history)

    assert state is None
    assert resolve_effective_objective("继续", history, state) == "层次锚定的超参数怎么设置？"


def test_substantive_current_query_supersedes_state():
    state = AgentContinuation(**STATE)

    assert (
        resolve_effective_objective("继续找学习率并比较各数据集", [], state)
        == "继续找学习率并比较各数据集"
    )


def test_invalid_cursor_completion_and_empty_strings_are_not_resumable():
    for field, value in (
        ("version", True),
        ("next_offset", True),
        ("has_more_after", False),
        ("objective", ""),
        ("kb_uid", ""),
        ("file_uid", ""),
    ):
        malformed = {**STATE, field: value}
        assert continuation_from_history([{"role": "assistant", "continuation": malformed}]) is None


def test_state_text_is_truncated_to_public_contract_bounds():
    oversized = {
        **STATE,
        "objective": "o" * 8001,
        "kb_uid": "k" * 129,
        "file_uid": "f" * 129,
    }

    state = continuation_from_history([{"role": "assistant", "continuation": oversized}])

    assert state is not None
    assert len(state.objective) == 8000
    assert len(state.kb_uid) == 128
    assert len(state.file_uid) == 128
