import pytest

from backend.app.services.graph_client import GraphClient


class FakeTx:
    def __init__(self):
        self.queries = []

    def run(self, query, **params):
        self.queries.append((query, params))


class FakeSession:
    def __init__(self):
        self.tx = FakeTx()
        self.database = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute_write(self, fn, *args, **kwargs):
        return fn(self.tx, *args, **kwargs)


class FakeDriver:
    def __init__(self):
        self.session_obj = FakeSession()
        self.closed = False

    def session(self, database=None):
        self.session_obj.database = database
        return self.session_obj

    def close(self):
        self.closed = True


def test_execute_read_timeout_uses_explicit_transaction_without_managed_retry():
    events = []
    class Result:
        def data(self):
            events.append("data")
            return [{"value": 1}]
    class Tx:
        def run(self, query, **params):
            events.append(("run", query, params))
            return Result()
        def commit(self): events.append("commit")
        def close(self): events.append("close")
    class Session(FakeSession):
        def begin_transaction(self, *, timeout):
            events.append(("begin", timeout))
            return Tx()
        def execute_read(self, _fn, **_kwargs):
            raise AssertionError("managed transaction must not be used with a deadline")
    driver = FakeDriver()
    driver.session_obj = Session()

    rows = GraphClient(driver=driver)._execute_read("RETURN $value AS value", {"value": 1}, timeout=2.5)

    assert rows == [{"value": 1}]
    assert events == [
        ("begin", 2.5), ("run", "RETURN $value AS value", {"value": 1}),
        "data", "commit", "close",
    ]


def test_upsert_ckp_emits_merge_with_params_and_database():
    driver = FakeDriver()
    client = GraphClient(driver=driver, database="prism")

    client.upsert_ckp(
        {
            "id": "ckp1",
            "user_id": "user1",
            "title": "Graph projection",
            "ckp_type": "concept",
            "status": "active",
            "confidence": 0.9,
        }
    )

    query, params = driver.session_obj.tx.queries[0]
    assert "MERGE (n:CKP {id: $id})" in query
    assert params["id"] == "ckp1"
    assert params["title"] == "Graph projection"
    assert driver.session_obj.database == "prism"


def test_upsert_entity_emits_merge_and_sets_names():
    driver = FakeDriver()
    client = GraphClient(driver=driver)

    client.upsert_entity(
        {
            "id": "entity1",
            "user_id": "user1", "tenant_id": "t1", "kb_uid": "kb1", "graph_generation": "gg1",
            "entity_type": "person",
            "canonical_name": "Ada Lovelace",
            "normalized_key": "ada_lovelace",
            "status": "active",
            "confidence": 0.8,
        }
    )

    query, params = driver.session_obj.tx.queries[0]
    assert "MERGE (n:Entity {id: $id})" in query
    assert "canonical_name: $canonical_name" in query
    assert "normalized_key: $normalized_key" in query
    assert params["canonical_name"] == "Ada Lovelace"
    assert params["normalized_key"] == "ada_lovelace"


def test_relate_emits_match_merge_and_props():
    driver = FakeDriver()
    client = GraphClient(driver=driver)

    client.relate("Entity", "e1", "AUTHORED", "Entity", "paper1", {"confidence": 0.8})

    query, params = driver.session_obj.tx.queries[0]
    assert "MATCH (a:Entity {id: $start_id})" in query
    assert "MATCH (b:Entity {id: $end_id})" in query
    assert "MERGE (a)-[r:AUTHORED]->(b)" in query
    assert "SET r += $props" in query
    assert params == {
        "start_id": "e1",
        "end_id": "paper1",
        "props": {"confidence": 0.8},
    }


def test_upsert_alias_derives_id_and_relates_alias_id_to_entity_id():
    driver = FakeDriver()
    client = GraphClient(driver=driver)

    client.upsert_alias(
        {"key": "ada", "surface_text": "Ada", "entity_id": "entity1", "tenant_id": "t1", "kb_uid": "kb1", "graph_generation": "gg1"}
    )

    alias_query, alias_params = driver.session_obj.tx.queries[0]
    rel_query, rel_params = driver.session_obj.tx.queries[1]
    assert "MERGE (n:Alias {id: $id})" in alias_query
    assert "key: $key" in alias_query
    assert alias_params["surface_text"] == "Ada"
    assert alias_params["id"] == "entity1:ada"
    assert alias_params["key"] == "ada"
    assert alias_params["entity_id"] == "entity1"
    assert alias_params["graph_generation"] == "gg1"
    assert "MATCH (a:Alias {id: $start_id})" in rel_query
    assert "MATCH (b:Entity {id: $end_id})" in rel_query
    assert "MERGE (a)-[r:ALIAS_OF]->(b)" in rel_query
    assert rel_params == {
        "start_id": "entity1:ada",
        "end_id": "entity1",
        "props": {},
    }


def test_upsert_alias_same_key_for_different_entities_uses_distinct_ids():
    driver = FakeDriver()
    client = GraphClient(driver=driver)

    client.upsert_alias(
        {"key": "ada", "surface_text": "Ada", "entity_id": "entity1", "tenant_id": "t1", "kb_uid": "k1", "graph_generation": "g1"}
    )
    client.upsert_alias(
        {"key": "ada", "surface_text": "Ada", "entity_id": "entity2", "tenant_id": "t1", "kb_uid": "k1", "graph_generation": "g1"}
    )

    first_alias_params = driver.session_obj.tx.queries[0][1]
    second_alias_params = driver.session_obj.tx.queries[2][1]
    assert first_alias_params["id"] == "entity1:ada"
    assert second_alias_params["id"] == "entity2:ada"
    assert first_alias_params["id"] != second_alias_params["id"]


@pytest.mark.parametrize(
    ("start_label", "rel_type", "end_label"),
    [
        ("Unsafe", "AUTHORED", "Entity"),
        ("Entity", "DROP_REL", "Entity"),
        ("Entity", "AUTHORED", "Unsafe"),
    ],
)
def test_relate_rejects_invalid_labels_or_relationship_types_before_query(
    start_label, rel_type, end_label
):
    driver = FakeDriver()
    client = GraphClient(driver=driver)

    with pytest.raises(ValueError):
        client.relate(start_label, "e1", rel_type, end_label, "e2")

    assert driver.session_obj.tx.queries == []


def test_close_closes_driver():
    driver = FakeDriver()
    client = GraphClient(driver=driver)

    client.close()

    assert driver.closed is True


def test_source_upsert_and_delete_are_scoped_by_tenant_kb_and_item():
    driver = FakeDriver()
    client = GraphClient(driver=driver)
    client.upsert_scoped_source({"id": "document_chunk:c1", "tenant_id": "t1", "kb_uid": "kb1",
                          "graph_generation": "gg1", "file_uid": "f1", "source_type": "document",
                          "source_kind": "document_chunk", "source_id": "c1", "item_id": "i1", "title": "Doc"})
    client.delete_item_sources_generation("t1", "kb1", "gg1", "i1")
    upsert_query, upsert_params = driver.session_obj.tx.queries[0]
    delete_query, delete_params = driver.session_obj.tx.queries[1]
    assert "MERGE (n:ScopedSource {id: $id, tenant_id: $tenant_id, kb_uid: $kb_uid, graph_generation: $graph_generation})" in upsert_query
    assert "kb_uid: $kb_uid" in upsert_query
    assert "graph_generation: $graph_generation" in upsert_query
    assert "file_uid: $file_uid" in upsert_query and "source_type: $source_type" in upsert_query
    assert "MATCH (s:ScopedSource" in delete_query
    assert "tenant_id: $tenant_id, kb_uid: $kb_uid, graph_generation: $graph_generation, item_id: $item_id" in delete_query
    assert delete_params == {"tenant_id": "t1", "kb_uid": "kb1", "graph_generation": "gg1", "item_id": "i1"}


def test_scoped_entity_identity_and_relationship_allow_same_id_to_coexist():
    driver = FakeDriver()
    client = GraphClient(driver=driver)
    base = {"id": "shared", "user_id": "u", "entity_type": "concept", "canonical_name": "Shared",
            "normalized_key": "shared", "status": "active", "confidence": 1.0}
    for kb, generation in (("k1", "g1"), ("k2", "g1"), ("k1", "g2")):
        client.upsert_scoped_entity({**base, "tenant_id": "t1", "kb_uid": kb, "graph_generation": generation})
    client.relate_scoped("ScopedEntity", "shared", "RELATED_TO", "ScopedEntity", "shared", {},
                         scope={"tenant_id": "t1", "kb_uid": "k1", "graph_generation": "g1"})
    for query, _ in driver.session_obj.tx.queries[:3]:
        assert "MERGE (n:ScopedEntity {id: $id, tenant_id: $tenant_id, kb_uid: $kb_uid, graph_generation: $graph_generation})" in query
    relationship_query = driver.session_obj.tx.queries[3][0]
    assert "MATCH (a:ScopedEntity {id: $start_id, tenant_id: $tenant_id, kb_uid: $kb_uid, graph_generation: $graph_generation})" in relationship_query
    assert "MATCH (b:ScopedEntity {id: $end_id, tenant_id: $tenant_id, kb_uid: $kb_uid, graph_generation: $graph_generation})" in relationship_query


def test_all_generation_cleanup_deletes_scoped_and_legacy_sources():
    driver = FakeDriver(); client = GraphClient(driver=driver)
    client.delete_item_sources_all_generations("t", "k", "i")
    queries = [query for query, _ in driver.session_obj.tx.queries]
    assert len(queries) == 2
    assert "MATCH (s:ScopedSource" in queries[0]
    assert "MATCH (s:Source" in queries[1]


def test_personal_asset_unit_graph_cleanup_deletes_source_edges_and_orphan_entities():
    driver = FakeDriver()
    client = GraphClient(driver=driver)

    client.delete_personal_asset_unit_graph("unit-a", user_id="user-a", entity_ids=["entity-a"])

    queries = [query for query, _ in driver.session_obj.tx.queries]
    params = [params for _, params in driver.session_obj.tx.queries]
    assert len(queries) == 3
    assert "WHERE r.source_kind = $source_kind AND r.source_id = $source_id" in queries[0]
    assert "MATCH (s:Source {id: $source_node_id})" in queries[1]
    assert "WHERE e.id IN $entity_ids AND NOT (e)--()" in queries[2]
    assert params[0]["source_kind"] == "personal_asset_unit"
    assert params[0]["source_id"] == "unit-a"
    assert params[0]["source_node_id"] == "personal_asset_unit:unit-a"
    assert params[0]["entity_ids"] == ["entity-a"]


def test_legacy_entity_alias_source_and_relationship_contract_remains_unscoped():
    driver = FakeDriver()
    client = GraphClient(driver=driver)
    client.upsert_entity({"id": "e", "user_id": "u", "entity_type": "concept", "canonical_name": "E",
                          "normalized_key": "e", "status": "active", "confidence": 1.0})
    client.upsert_alias({"id": "a", "key": "e", "surface_text": "E", "entity_id": None})
    client.upsert_source({"id": "s", "tenant_id": "", "kb_uid": "", "source_kind": "legacy",
                          "source_id": "s", "item_id": "i", "title": "S"})
    client.relate("Entity", "e", "MENTIONED_IN", "Source", "s")
    queries = [query for query, _ in driver.session_obj.tx.queries]
    assert "MERGE (n:Entity {id: $id})" in queries[0]
    assert "MERGE (n:Alias {id: $id})" in queries[1]
    assert "MERGE (n:Source {id: $id})" in queries[2]
    assert "MATCH (a:Entity {id: $start_id})" in queries[3]
