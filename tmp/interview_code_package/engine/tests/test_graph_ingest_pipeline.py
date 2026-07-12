from types import SimpleNamespace


def test_run_graph_ingest_pipeline_orders_shared_steps(monkeypatch):
    from engine.app.graph.pipeline import run_graph_ingest_pipeline

    calls: list[str] = []

    monkeypatch.setattr("engine.app.graph.pipeline.detect_source", lambda env: calls.append("detect") or "document")
    monkeypatch.setattr(
        "engine.app.graph.pipeline.extract_source_graph",
        lambda *args, **kwargs: calls.append("extract") or {"nodes": [], "edges": []},
    )
    monkeypatch.setattr(
        "engine.app.graph.pipeline.persist_source_graph",
        lambda *args, **kwargs: calls.append("persist") or {"nodes": [], "edges": []},
    )
    monkeypatch.setattr(
        "engine.app.graph.pipeline.project_source_graph",
        lambda *args, **kwargs: calls.append("project"),
    )
    monkeypatch.setattr(
        "engine.app.graph.pipeline.analyze_source_graph",
        lambda *args, **kwargs: calls.append("analyze"),
    )

    persisted = run_graph_ingest_pipeline({"source_kind": "document_chunk", "source_id": "c1"})

    assert persisted == {"nodes": [], "edges": []}
    assert calls == ["detect", "extract", "persist", "project", "analyze"]


def test_run_graph_ingest_pipeline_can_skip_to_graph_finalize(monkeypatch):
    from engine.app.graph.pipeline import run_graph_ingest_pipeline

    calls: list[str] = []

    monkeypatch.setattr("engine.app.graph.pipeline.detect_source", lambda env: calls.append("detect") or "document")
    monkeypatch.setattr(
        "engine.app.graph.pipeline.extract_source_graph",
        lambda *args, **kwargs: calls.append("extract") or {"nodes": [], "edges": []},
    )
    monkeypatch.setattr(
        "engine.app.graph.pipeline.persist_source_graph",
        lambda *args, **kwargs: calls.append("persist") or {"nodes": [], "edges": []},
    )
    monkeypatch.setattr(
        "engine.app.graph.pipeline.project_source_graph",
        lambda *args, **kwargs: calls.append("project"),
    )
    monkeypatch.setattr(
        "engine.app.graph.pipeline.analyze_source_graph",
        lambda *args, **kwargs: calls.append("analyze"),
    )

    persisted = run_graph_ingest_pipeline(
        {"source_kind": "document_chunk", "source_id": "c1", "item_id": "item-1", "user_id": "user-1"},
        run_detect=False,
        run_extract=False,
        run_persist=False,
    )

    assert persisted["source_id"] == "c1"
    assert calls == ["project", "analyze"]


def test_document_ingestion_routes_chunk_to_shared_pipeline(monkeypatch):
    from engine.app.ingestion import pipeline as mod

    captured: list[tuple[dict, object, bool, bool, bool]] = []

    monkeypatch.setattr(
        mod,
        "run_graph_ingest_pipeline",
        lambda env, *, db=None, graph_client=None, run_detect=True, run_extract=True, run_persist=True, run_project=True, run_analyze=True: (
            captured.append((env, db, run_project, run_analyze, run_persist)) or {}
        ),
    )

    chunk = SimpleNamespace(id="chunk-1", chunk_text="hello graph")

    mod._ingest_chunk_graph(SimpleNamespace(), "item-1", chunk, user_id="user-1")

    assert len(captured) == 1
    env, db, run_project, run_analyze, run_persist = captured[0]
    assert db is not None
    assert env["source_kind"] == "document_chunk"
    assert env["source_id"] == "chunk-1"
    assert env["item_id"] == "item-1"
    assert env["text"] == "hello graph"
    assert env["user_id"] == "user-1"
    assert run_persist is True
    assert run_project is False
    assert run_analyze is False


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._result

    def delete(self, synchronize_session=False):
        return 0


class _FakeDB:
    def __init__(self, chunks):
        self._chunks = chunks
        self.flush_calls = 0
        self.commit_calls = 0

    def query(self, model):
        model_name = getattr(model, "__name__", "")
        if model_name == "KnowledgeChunk":
            return _FakeQuery(self._chunks)
        return _FakeQuery([])

    def flush(self):
        self.flush_calls += 1

    def commit(self):
        self.commit_calls += 1


def test_document_stage_a_processes_all_chunks_then_finalizes_graph_once(monkeypatch):
    from engine.app.ingestion import pipeline as mod

    processed: list[str] = []
    finalizations: list[dict] = []
    db = _FakeDB(
        [
            SimpleNamespace(id="chunk-1", chunk_text="chunk 1"),
            SimpleNamespace(id="chunk-2", chunk_text="chunk 2"),
        ]
    )

    monkeypatch.setattr(mod.settings, "ENTITY_EXTRACT_ENABLED", True)
    monkeypatch.setattr(
        mod,
        "_ingest_chunk_graph",
        lambda db, item_id, chunk, *, user_id: processed.append(chunk.id) or {},
    )
    monkeypatch.setattr(
        mod,
        "run_graph_ingest_pipeline",
        lambda env, *, db=None, graph_client=None, run_detect=True, run_extract=True, run_persist=True, run_project=True, run_analyze=True: (
            finalizations.append(
                {
                    "env": env,
                    "run_detect": run_detect,
                    "run_extract": run_extract,
                    "run_persist": run_persist,
                    "run_project": run_project,
                    "run_analyze": run_analyze,
                }
            )
            or env
        ),
    )

    mod._run_stage_a_for_item(db, "item-1", "user-1")

    assert processed == ["chunk-1", "chunk-2"]
    assert db.commit_calls == 1
    assert len(finalizations) == 1
    assert finalizations[0]["env"]["item_id"] == "item-1"
    assert finalizations[0]["env"]["source_id"] == "chunk-2"
    assert finalizations[0]["run_detect"] is False
    assert finalizations[0]["run_extract"] is False
    assert finalizations[0]["run_persist"] is False
    assert finalizations[0]["run_project"] is True
    assert finalizations[0]["run_analyze"] is True


def test_document_stage_a_swallows_graph_finalize_errors_after_chunk_settle(monkeypatch):
    from engine.app.ingestion import pipeline as mod

    processed: list[str] = []
    db = _FakeDB(
        [
            SimpleNamespace(id="chunk-1", chunk_text="chunk 1"),
            SimpleNamespace(id="chunk-2", chunk_text="chunk 2"),
        ]
    )

    monkeypatch.setattr(mod.settings, "ENTITY_EXTRACT_ENABLED", True)
    monkeypatch.setattr(
        mod,
        "_ingest_chunk_graph",
        lambda db, item_id, chunk, *, user_id: processed.append(chunk.id) or {},
    )
    monkeypatch.setattr(
        mod,
        "run_graph_ingest_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("graph boom")),
    )

    mod._run_stage_a_for_item(db, "item-1", "user-1")

    assert processed == ["chunk-1", "chunk-2"]
    assert db.commit_calls == 1


def test_document_stage_a_continues_after_single_chunk_graph_failure(monkeypatch):
    from engine.app.ingestion import pipeline as mod

    processed: list[str] = []
    finalizations: list[str] = []
    db = _FakeDB(
        [
            SimpleNamespace(id="chunk-1", chunk_text="chunk 1"),
            SimpleNamespace(id="chunk-2", chunk_text="chunk 2"),
            SimpleNamespace(id="chunk-3", chunk_text="chunk 3"),
        ]
    )

    def fake_ingest_chunk_graph(db, item_id, chunk, *, user_id):
        processed.append(chunk.id)
        if chunk.id == "chunk-2":
            raise RuntimeError("graph boom")
        return {}

    monkeypatch.setattr(mod.settings, "ENTITY_EXTRACT_ENABLED", True)
    monkeypatch.setattr(mod, "_ingest_chunk_graph", fake_ingest_chunk_graph)
    monkeypatch.setattr(
        mod,
        "run_graph_ingest_pipeline",
        lambda env, *, db=None, graph_client=None, run_detect=True, run_extract=True, run_persist=True, run_project=True, run_analyze=True: (
            finalizations.append(env["source_id"]) or env
        ),
    )

    mod._run_stage_a_for_item(db, "item-1", "user-1")

    assert processed == ["chunk-1", "chunk-2", "chunk-3"]
    assert db.commit_calls == 1
    assert finalizations == ["chunk-3"]


def test_asset_ingestion_routes_unit_to_shared_pipeline(monkeypatch):
    from backend.app.api import assets as mod

    captured: list[tuple[dict, object]] = []

    monkeypatch.setattr(mod, "_asset_unit_entity_graph_text", lambda unit: "asset body")
    monkeypatch.setattr(
        mod,
        "run_graph_ingest_pipeline",
        lambda env, *, db=None, graph_client=None: captured.append((env, db)) or {},
    )

    unit = SimpleNamespace(id="unit-1", user_id="user-2")

    mod._ingest_asset_unit_entity_graph(SimpleNamespace(), unit)

    assert len(captured) == 1
    env, db = captured[0]
    assert db is not None
    assert env["source_kind"] == "personal_asset_unit"
    assert env["source_id"] == "unit-1"
    assert env["item_id"] == "unit-1"
    assert env["text"] == "asset body"
    assert env["user_id"] == "user-2"
