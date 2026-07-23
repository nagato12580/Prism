import pytest
from pydantic import ValidationError

from engine.app.retrieval.contracts import (
    Candidate,
    ChannelProblem,
    ChannelResult,
    SearchScope,
)


@pytest.mark.parametrize("field", ["tenant_id", "kb_uid", "index_generation"])
def test_search_scope_requires_non_empty_identity_and_generation(field):
    values = {"tenant_id": "tenant-a", "kb_uid": "kb-a", "index_generation": "g1"}
    values[field] = ""

    with pytest.raises(ValidationError):
        SearchScope(**values)


def test_search_scope_preserves_optional_graph_and_tuple_filters():
    scope = SearchScope(
        tenant_id="tenant-a",
        kb_uid="kb-a",
        index_generation="g1",
        graph_generation="gg1",
        file_uids=("file-a",),
        source_types=("pdf",),
    )

    assert scope.graph_generation == "gg1"
    assert scope.file_uids == ("file-a",)
    assert scope.source_types == ("pdf",)


def test_failed_channel_is_not_no_hits():
    failed = ChannelResult.failed("dense", "VECTOR_INDEX_UNAVAILABLE", retryable=True)
    empty = ChannelResult.ok("dense", [])

    assert failed.health == "failed"
    assert failed.problem == ChannelProblem(code="VECTOR_INDEX_UNAVAILABLE", retryable=True)
    assert empty.health == "ok"
    assert empty.candidates == []
    assert empty.problem is None


def test_failed_channel_requires_a_problem():
    with pytest.raises(ValidationError):
        ChannelResult(channel="dense", health="failed")


def test_degraded_channel_requires_a_problem():
    with pytest.raises(ValidationError):
        ChannelResult(channel="bm25", health="degraded")


def test_ok_channel_rejects_a_problem():
    with pytest.raises(ValidationError):
        ChannelResult(
            channel="graph",
            health="ok",
            problem=ChannelProblem(code="GRAPH_WARNING"),
        )


def test_default_containers_are_not_shared_between_instances():
    first_candidate = Candidate(
        chunk_uid="chunk-a",
        item_id="item-a",
        file_uid="file-a",
        channel="dense",
        raw_score=0.9,
        raw_rank=1,
    )
    second_candidate = Candidate(
        chunk_uid="chunk-b",
        item_id="item-b",
        file_uid="file-b",
        channel="bm25",
        raw_score=0.8,
        raw_rank=2,
    )
    first_result = ChannelResult.ok("dense", [])
    second_result = ChannelResult.ok("dense", [])

    assert first_candidate.metadata is not second_candidate.metadata
    assert first_result.candidates is not second_result.candidates


def test_contract_containers_support_result_aggregation():
    candidate = Candidate(
        chunk_uid="chunk-a",
        item_id="item-a",
        file_uid="file-a",
        channel="dense",
        raw_score=0.9,
        raw_rank=1,
    )
    result = ChannelResult.ok("dense", [])

    candidate.metadata["index_generation"] = "g1"
    result.candidates.append(candidate)

    assert candidate.metadata == {"index_generation": "g1"}
    assert result.candidates == [candidate]
