from engine.app.evaluation.runner import EvaluationItem, run_evaluation


def _evidence(chunk_uid="c1"):
    return {
        "tenant_id": "t1", "kb_uid": "kb1", "file_uid": "f1",
        "chunk_uid": chunk_uid, "display_title": "", "excerpt": "safe",
        "rrf_score": 1.0, "index_generation": "g1",
    }


def test_runner_records_each_item_and_partial_failure():
    items = [EvaluationItem("one", "q1", frozenset({"c1"})), EvaluationItem("two", "q2", frozenset({"c2"}))]

    def retrieve(item):
        if item.item_id == "two":
            raise RuntimeError("transient provider detail")
        return [_evidence()]

    result = run_evaluation(items, retrieve, ks=(1,))
    assert result.status == "succeeded_with_errors"
    assert result.progress_current == 2
    assert result.items[0].evidence[0]["chunk_uid"] == "c1"
    assert result.items[0].metrics["recall@1"] == 1.0
    assert result.items[1].status == "failed"
    assert result.items[1].error == "evaluation item failed"


def test_runner_all_failed_has_failed_status():
    def fail(_item):
        raise RuntimeError("secret")

    result = run_evaluation([EvaluationItem("one", "q", frozenset())], fail)
    assert result.status == "failed"


def test_runner_cancel_stops_items_not_started():
    calls = []
    items = [EvaluationItem(str(i), f"q{i}", frozenset()) for i in range(3)]

    def retrieve(item):
        calls.append(item.item_id)
        return []

    result = run_evaluation(items, retrieve, is_cancelled=lambda: len(calls) == 1)
    assert calls == ["0"]
    assert result.status == "canceled"
    assert result.progress_current == 1


def test_runner_validates_task6_evidence_contract():
    result = run_evaluation(
        [EvaluationItem("one", "q", frozenset({"c1"}))],
        lambda _item: [{"chunk_uid": "c1"}],
        ks=(1,),
    )

    assert result.status == "failed"
    assert result.items[0].status == "failed"
    assert result.items[0].evidence == ()
