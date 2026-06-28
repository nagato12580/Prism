import json

from engine.app.agent.deep_search.judge import JudgeAgent
from engine.app.agent.deep_search.schemas import EvidencePoolSnapshot, EvidenceRecord


def _snapshot():
    return EvidencePoolSnapshot(
        total_count=1,
        records=[
            EvidenceRecord(
                evidence_id="e1",
                strategy="source_backtrack",
                source_kind="document_chunk",
                source_id="chunk-1",
                pku_id="pku-1",
                ckp_id="ckp-1",
                statement="Scope-first retrieval avoids full chunk search.",
                final_score=0.82,
            )
        ],
    )


def _strong_snapshot():
    return EvidencePoolSnapshot(
        total_count=2,
        records=[
            EvidenceRecord(
                evidence_id="e1",
                strategy="source_backtrack",
                source_kind="document_chunk",
                source_id="chunk-1",
                pku_id="pku-1",
                ckp_id="ckp-1",
                statement="Scope-first retrieval avoids full chunk search.",
                final_score=0.82,
            ),
            EvidenceRecord(
                evidence_id="e2",
                strategy="source_backtrack",
                source_kind="personal_asset_unit",
                source_id="unit-2",
                pku_id="pku-2",
                ckp_id="ckp-1",
                statement="Judge can request more evidence when coverage is incomplete.",
                final_score=0.76,
            ),
        ],
    )


def _ungrounded_snapshot():
    return EvidencePoolSnapshot(
        total_count=1,
        records=[
            EvidenceRecord(
                evidence_id="e1",
                strategy="pku_requery",
                source_kind="",
                source_id="",
                pku_id="pku-1",
                ckp_id="ckp-1",
                statement="A PKU summary exists but no source-backed chunk was found.",
                final_score=0.7,
            )
        ],
    )


def test_judge_uses_configured_llm_model(monkeypatch):
    calls = []

    def fake_chat(messages, *, model=None, api_base=None, api_key=None):
        calls.append({"messages": messages, "model": model, "api_base": api_base, "api_key": api_key})
        return json.dumps(
            {
                "status": "complete",
                "coverage_score": 0.91,
                "grounding_score": 0.92,
                "source_diversity_score": 0.4,
                "conflict_score": 1.0,
                "structure_score": 0.8,
                "overall_score": 0.86,
                "missing": [],
                "directives": [],
            }
        )

    monkeypatch.setattr("engine.app.agent.deep_search.judge.chat", fake_chat)
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MODEL", "judge-model")
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_API_BASE", "http://judge.local/v1")
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_API_KEY", "judge-key")
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MIN_OVERALL_SCORE", 0.72)
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MIN_SOURCE_EVIDENCE", 1)

    verdict = JudgeAgent().evaluate("Should this answer?", _snapshot(), iteration=1)

    assert verdict.status == "complete"
    assert verdict.overall_score == 0.86
    assert calls[0]["model"] == "judge-model"
    assert calls[0]["api_base"] == "http://judge.local/v1"
    assert calls[0]["api_key"] == "judge-key"


def test_judge_falls_back_when_llm_not_configured(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM judge should not be called")

    monkeypatch.setattr("engine.app.agent.deep_search.judge.chat", fail_if_called)
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MODEL", "")
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MIN_OVERALL_SCORE", 0.72)
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MIN_SOURCE_EVIDENCE", 1)

    verdict = JudgeAgent().evaluate("Should this answer?", _snapshot(), iteration=1)

    assert verdict.status in {"complete", "incomplete"}
    assert verdict.overall_score > 0


def test_judge_falls_back_when_llm_returns_invalid_json(monkeypatch):
    monkeypatch.setattr("engine.app.agent.deep_search.judge.chat", lambda *a, **k: "not json")
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MODEL", "judge-model")
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_API_BASE", "")
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_API_KEY", "")
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MIN_OVERALL_SCORE", 0.72)
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MIN_SOURCE_EVIDENCE", 1)

    verdict = JudgeAgent().evaluate("Should this answer?", _snapshot(), iteration=1)

    assert verdict.status in {"complete", "incomplete"}
    assert verdict.overall_score > 0


def test_llm_judge_complete_is_gated_by_configured_threshold(monkeypatch):
    monkeypatch.setattr("engine.app.agent.deep_search.judge.chat", lambda *a, **k: json.dumps({
        "status": "complete",
        "coverage_score": 0.8,
        "grounding_score": 0.83,
        "source_diversity_score": 0.5,
        "conflict_score": 1.0,
        "structure_score": 0.9,
        "overall_score": 0.79,
        "missing": [],
        "directives": [],
    }))
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MODEL", "judge-model")
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MIN_OVERALL_SCORE", 0.85)
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MIN_SOURCE_EVIDENCE", 1)

    verdict = JudgeAgent().evaluate("Should this answer?", _strong_snapshot(), iteration=1)

    assert verdict.status == "incomplete"
    assert verdict.overall_score == 0.79
    assert "Judge overall score 0.79 is below required threshold 0.85." in verdict.missing
    assert [directive.strategy for directive in verdict.directives] == ["pku_graph_expansion"]


def test_completion_gate_adds_directive_after_third_iteration(monkeypatch):
    monkeypatch.setattr("engine.app.agent.deep_search.judge.chat", lambda *a, **k: json.dumps({
        "status": "incomplete",
        "coverage_score": 0.8,
        "grounding_score": 0.83,
        "source_diversity_score": 0.5,
        "conflict_score": 1.0,
        "structure_score": 0.9,
        "overall_score": 0.81,
        "missing": [],
        "directives": [],
    }))
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MODEL", "judge-model")
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MIN_OVERALL_SCORE", 0.9)
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MIN_SOURCE_EVIDENCE", 1)

    verdict = JudgeAgent().evaluate("Should this answer?", _strong_snapshot(), iteration=4)

    assert verdict.status == "incomplete"
    assert verdict.overall_score == 0.81
    assert [directive.strategy for directive in verdict.directives] == ["pku_graph_expansion"]


def test_completion_gate_plans_scoped_chunk_search_when_grounding_is_weak(monkeypatch):
    monkeypatch.setattr("engine.app.agent.deep_search.judge.chat", lambda *a, **k: json.dumps({
        "status": "incomplete",
        "coverage_score": 0.8,
        "grounding_score": 0.35,
        "source_diversity_score": 0.7,
        "conflict_score": 1.0,
        "structure_score": 0.9,
        "overall_score": 0.68,
        "missing": [],
        "directives": [],
    }))
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MODEL", "judge-model")
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MIN_OVERALL_SCORE", 0.9)
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MIN_SOURCE_EVIDENCE", 1)

    verdict = JudgeAgent().evaluate("Should this answer?", _strong_snapshot(), iteration=2)

    assert verdict.status == "incomplete"
    assert [directive.strategy for directive in verdict.directives] == ["scoped_chunk_search"]


def test_completion_gate_plans_pku_requery_when_coverage_is_weak(monkeypatch):
    monkeypatch.setattr("engine.app.agent.deep_search.judge.chat", lambda *a, **k: json.dumps({
        "status": "incomplete",
        "coverage_score": 0.3,
        "grounding_score": 0.8,
        "source_diversity_score": 0.7,
        "conflict_score": 1.0,
        "structure_score": 0.9,
        "overall_score": 0.62,
        "missing": [],
        "directives": [],
    }))
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MODEL", "judge-model")
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MIN_OVERALL_SCORE", 0.9)
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MIN_SOURCE_EVIDENCE", 1)

    verdict = JudgeAgent().evaluate("Should this answer?", _strong_snapshot(), iteration=2)

    assert verdict.status == "incomplete"
    assert [directive.strategy for directive in verdict.directives] == ["pku_requery"]


def test_completion_gate_plans_source_backtrack_when_source_evidence_missing(monkeypatch):
    monkeypatch.setattr("engine.app.agent.deep_search.judge.chat", lambda *a, **k: json.dumps({
        "status": "incomplete",
        "coverage_score": 0.7,
        "grounding_score": 0.2,
        "source_diversity_score": 0.2,
        "conflict_score": 1.0,
        "structure_score": 0.8,
        "overall_score": 0.6,
        "missing": [],
        "directives": [],
    }))
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MODEL", "judge-model")
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MIN_OVERALL_SCORE", 0.9)
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MIN_SOURCE_EVIDENCE", 1)

    verdict = JudgeAgent().evaluate("Should this answer?", _ungrounded_snapshot(), iteration=2)

    assert verdict.status == "incomplete"
    assert [directive.strategy for directive in verdict.directives] == ["source_backtrack"]


def test_deterministic_judge_uses_configured_threshold(monkeypatch):
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MODEL", "")
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MIN_OVERALL_SCORE", 0.9)
    monkeypatch.setattr("engine.app.agent.deep_search.judge.settings.DEEP_SEARCH_JUDGE_MIN_SOURCE_EVIDENCE", 1)

    verdict = JudgeAgent().evaluate("Should this answer?", _strong_snapshot(), iteration=1)

    assert verdict.status == "incomplete"
    assert verdict.overall_score < 0.9
    assert verdict.directives
