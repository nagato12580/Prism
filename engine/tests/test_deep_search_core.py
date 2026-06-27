from engine.app.agent.deep_search.a2a import AgentCard, Artifact, Message, Task
from engine.app.agent.deep_search.evidence_pool import EvidencePool
from engine.app.agent.deep_search.schemas import EvidenceRecord


def test_a2a_models_export_stable_payloads():
    card = AgentCard(name="SearcherAgent", role="searcher", capabilities=["scope", "evidence"])
    task = Task(task_id="task-1", goal="answer question", depth="standard")
    message = Message(
        sender="orchestrator",
        recipient="searcher",
        task_id=task.task_id,
        content={"query": "metadata filters"},
    )
    artifact = Artifact(
        artifact_id="artifact-1",
        task_id=task.task_id,
        kind="scope",
        payload={"seed_ckp_ids": ["ckp-1"]},
    )

    assert card.to_dict() == {
        "name": "SearcherAgent",
        "role": "searcher",
        "capabilities": ["scope", "evidence"],
        "metadata": {},
    }
    assert task.to_dict()["depth"] == "standard"
    assert message.to_dict()["content"]["query"] == "metadata filters"
    assert artifact.to_dict()["payload"]["seed_ckp_ids"] == ["ckp-1"]


def test_evidence_pool_dedupes_by_source_and_keeps_higher_score():
    pool = EvidencePool()
    lower = EvidenceRecord(
        evidence_id="e-low",
        strategy="source_backtrack",
        source_kind="document_chunk",
        source_id="chunk-1",
        pku_id="pku-1",
        ckp_id="ckp-1",
        statement="Metadata filters restrict retrieval.",
        retrieval_score=0.4,
        relation_confidence=0.5,
        knowledge_confidence=0.5,
        source_quality=0.8,
    )
    higher = lower.model_copy(
        update={
            "evidence_id": "e-high",
            "strategy": "scoped_chunk_search",
            "retrieval_score": 0.9,
            "relation_confidence": 0.8,
        }
    )

    pool.add_many([lower, higher])
    snapshot = pool.snapshot()

    assert snapshot.total_count == 1
    assert snapshot.records[0].evidence_id == "e-high"
    assert snapshot.records[0].final_score > lower.final_score


def test_evidence_pool_scoring_penalizes_weak_expansion_paths():
    pool = EvidencePool()
    direct = EvidenceRecord(
        evidence_id="direct",
        strategy="source_backtrack",
        source_kind="document_chunk",
        source_id="chunk-1",
        pku_id="pku-1",
        ckp_id="ckp-1",
        statement="PKU has direct source evidence.",
        retrieval_score=0.7,
        relation_confidence=0.9,
        knowledge_confidence=0.8,
        source_quality=1.0,
        coverage_bonus=0.2,
        scope_distance=0,
        relation_type="same_as",
    )
    related = EvidenceRecord(
        evidence_id="related",
        strategy="pku_graph_expansion",
        source_kind="document_chunk",
        source_id="chunk-2",
        pku_id="pku-2",
        ckp_id="ckp-2",
        statement="PKU is only related through graph expansion.",
        retrieval_score=0.7,
        relation_confidence=0.9,
        knowledge_confidence=0.8,
        source_quality=1.0,
        coverage_bonus=0.2,
        scope_distance=2,
        relation_type="related_to",
    )
    contradicts = related.model_copy(
        update={
            "evidence_id": "contradicts",
            "source_id": "chunk-3",
            "pku_id": "pku-3",
            "relation_type": "contradicts",
        }
    )

    pool.add_many([related, direct, contradicts])
    records = pool.snapshot().records

    assert [record.evidence_id for record in records] == ["direct", "contradicts", "related"]
    assert records[0].final_score > records[-1].final_score
    assert records[1].final_score > records[2].final_score
