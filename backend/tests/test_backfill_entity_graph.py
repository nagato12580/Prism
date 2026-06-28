from dataclasses import dataclass
from types import SimpleNamespace

from backend.scripts import backfill_entity_graph


@dataclass
class FakeChunk:
    id: str
    item_id: str
    chunk_text: str | None


class FakeColumn:
    def asc(self):
        return f"{id(self)}:asc"


class FakeQuery:
    def __init__(self, chunks):
        self.chunks = chunks
        self.limit_value = None
        self.order_by_args = None

    def order_by(self, *args):
        self.order_by_args = args
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def all(self):
        if self.limit_value is None:
            return list(self.chunks)
        return list(self.chunks[: self.limit_value])


class FakeDB:
    def __init__(self, chunks):
        self.chunks = chunks
        self.commit_called = False
        self.rollback_called = False
        self.close_called = False
        self.queries = []

    def query(self, model):
        self.queries.append(model)
        return FakeQuery(self.chunks)

    def commit(self):
        self.commit_called = True

    def rollback(self):
        self.rollback_called = True

    def close(self):
        self.close_called = True


def install_fake_session(monkeypatch, db):
    created_engines = []

    def fake_create_engine(url):
        engine = SimpleNamespace(url=url)
        created_engines.append(engine)
        return engine

    def fake_sessionmaker(bind):
        assert bind is created_engines[-1]
        return lambda: db

    monkeypatch.setattr(backfill_entity_graph, "create_engine", fake_create_engine)
    monkeypatch.setattr(backfill_entity_graph, "sessionmaker", fake_sessionmaker)
    monkeypatch.setattr(backfill_entity_graph.settings, "DATABASE_URL", "mysql://test")
    return created_engines


def test_backfill_entity_graph_dry_run_extracts_chunks_and_skips_graph(monkeypatch, capsys):
    chunk = FakeChunk(id="chunk-1", item_id="item-1", chunk_text="Ada Lovelace wrote notes.")
    db = FakeDB([chunk])
    created_engines = install_fake_session(monkeypatch, db)
    calls = []

    monkeypatch.setattr(
        backfill_entity_graph.KnowledgeChunk,
        "created_at",
        FakeColumn(),
    )
    monkeypatch.setattr(backfill_entity_graph.KnowledgeChunk, "id", FakeColumn())
    monkeypatch.setattr(
        backfill_entity_graph,
        "extract_and_settle_entities",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    def fail_graph_client():
        raise AssertionError("GraphClient should not be constructed during dry run")

    monkeypatch.setattr(backfill_entity_graph, "GraphClient", fail_graph_client)

    result = backfill_entity_graph.main(["--dry-run", "--limit", "1"])

    assert result == 0
    assert len(created_engines) == 1
    assert len(calls) == 1
    assert calls[0] == (
        (db,),
        {
            "source_kind": "document_chunk",
            "source_id": "chunk-1",
            "item_id": "item-1",
            "chunk_id": "chunk-1",
            "text": "Ada Lovelace wrote notes.",
        },
    )
    assert db.rollback_called is True
    assert db.commit_called is False
    assert db.close_called is True
    assert capsys.readouterr().out == "dry-run extracted entities from 1 chunks\n"


def test_backfill_entity_graph_commits_and_projects_graph(monkeypatch, capsys):
    chunks = [
        FakeChunk(id="chunk-1", item_id="item-1", chunk_text="Ada Lovelace wrote notes."),
        FakeChunk(id="chunk-2", item_id="item-1", chunk_text=None),
    ]
    db = FakeDB(chunks)
    install_fake_session(monkeypatch, db)
    extraction_calls = []
    projection_calls = []

    monkeypatch.setattr(backfill_entity_graph.KnowledgeChunk, "created_at", FakeColumn())
    monkeypatch.setattr(backfill_entity_graph.KnowledgeChunk, "id", FakeColumn())
    monkeypatch.setattr(
        backfill_entity_graph,
        "extract_and_settle_entities",
        lambda *args, **kwargs: extraction_calls.append((args, kwargs)),
    )

    class FakeGraphClient:
        closed = False

        def close(self):
            type(self).closed = True

    monkeypatch.setattr(backfill_entity_graph, "GraphClient", FakeGraphClient)

    def fake_project_ckp_graph(project_db, graph):
        projection_calls.append(("ckp", project_db, graph))
        return SimpleNamespace(
            ckp_count=3,
            pku_count=5,
            entity_count=0,
            source_count=7,
            relation_count=11,
        )

    def fake_project_entity_graph(project_db, graph):
        projection_calls.append(("entity", project_db, graph))
        return SimpleNamespace(
            ckp_count=0,
            pku_count=0,
            entity_count=13,
            source_count=17,
            relation_count=19,
        )

    monkeypatch.setattr(backfill_entity_graph, "project_ckp_graph", fake_project_ckp_graph)
    monkeypatch.setattr(backfill_entity_graph, "project_entity_graph", fake_project_entity_graph)

    result = backfill_entity_graph.main(["--limit", "2"])

    assert result == 0
    assert db.commit_called is True
    assert db.rollback_called is False
    assert db.close_called is True
    assert FakeGraphClient.closed is True
    assert len(extraction_calls) == 2
    assert extraction_calls[1][1]["text"] == ""
    assert [call[0] for call in projection_calls] == ["ckp", "entity"]
    assert "ckp_count=3" in capsys.readouterr().out


def test_parse_args_supports_limit_and_dry_run():
    args = backfill_entity_graph.parse_args(["--limit", "10", "--dry-run"])

    assert args.limit == 10
    assert args.dry_run is True
