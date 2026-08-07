"""One-time maintenance script: reattribute all legacy data to a target user.

Before user isolation existed, every content row was written with
``user_id='default-user'`` / ``tenant_id IN ('default-user','legacy-personal',
'team','tenant-a')``. This script moves all of that data under a single target
user (default ``nizhenshigoule@gmail.com``), then re-keys the vector/full-text
indexes (Milvus + Elasticsearch + Neo4j) so retrieval still works after the
MySQL ``tenant_id``/``user_id`` change.

Usage (from repo root, with backend/engine stopped for a clean window):

    python backend/scripts/migrate_ownership_to_user.py --dry-run      # preview
    python backend/scripts/migrate_ownership_to_user.py --apply        # MySQL only
    python backend/scripts/migrate_ownership_to_user.py --apply --indexes  # + Milvus/ES/Neo4j

Safety:
  - MySQL changes run inside a single transaction; ``--dry-run`` only prints
    row counts and the exact statements that would run.
  - ``--indexes`` is best-effort and idempotent (upsert by the same primary
    key / update-by-query); failure there degrades retrieval but never breaks
    MySQL data. Re-run it any time.
  - Take a mysqldump backup before ``--apply``:
        mysqldump prism_db > backups/prism_db_pre_isolation_<date>.sql
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from backend.app.config import settings  # noqa: E402

# ── Config ──────────────────────────────────────────────────────────────
LEGACY_USERS = ("default-user",)
LEGACY_TENANTS = ("default-user", "legacy-personal", "team", "tenant-a", "")
ORPHAN_INBOX_UIDS = (
    "d6735ec4-9524-5ebf-9333-705bcfa815ca",  # legacy-personal empty system inbox
    "24b11cf2-587e-5be9-8e8a-6475daaa85dc",  # team tenant empty system inbox (smoke residue)
)
GRAPH_SMOKE_KB_UIDS = (
    "14ca9073-2fad-4a90-833a-7c366504bb7a",
    "5295ad67-0ff7-4e05-b63a-f96a206b5e6f",
    "8c316846-d55b-4539-b8f2-51368a89a79f",
    "9579a8ad-8280-42d3-9ee9-b1495c0ac1af",
    "7569bdcd-f7fd-47a9-bea4-db0f9d8b3b2a",
)

USER_SCOPED_TABLES = (
    "chat_session",
    "memory_entry",
    "memory_source",
    "memory_statement",
    "memory_entity",
    "memory_relation",
    "memory_event",
    "memory_insight",
    "memory_draft",
    "memory_extraction_run",
    "personal_asset",
    "personal_asset_item",
    "personal_asset_unit",
    "asset_relation",
    "extension_point",
    "asset_usage_event",
    "personal_knowledge_unit",
    "canonical_knowledge_point",
    "pku_canonical_link",
    "pku_relation",
    "canonical_relation",
    "wiki_document",
    "wiki_knowledge_point",
    "graph_community",
    "graph_insight_summary",
    "notebook_note",
)

TENANT_SCOPED_TABLES = (
    "knowledge_item",
    "knowledge_file",
    "knowledge_chunk",
    "knowledge_job",
    "knowledge_graph_generation",
    "graph_extraction_revision",
    "graph_outbox_event",
    "graph_projection_cursor",
    "knowledge_citation",
    "evaluation_dataset",
    "evaluation_dataset_item",
    "evaluation_run",
    "evaluation_run_item",
)


def _in_old(a) -> str:
    vals = ", ".join(f"'{v}'" for v in LEGACY_TENANTS)
    return f"{a} IN ({vals})"


def _run_mysql(engine, apply: bool) -> list[str]:
    statements: list[str] = []
    with engine.connect() as conn:
        # ── cleanup: orphan system inboxes + graph-smoke junk ──
        all_uids = ORPHAN_INBOX_UIDS + GRAPH_SMOKE_KB_UIDS
        uid_list = ", ".join(f"'{u}'" for u in all_uids)
        # capture children so deletes stay consistent
        child_tables = {
            "knowledge_file": "kb_uid",
            "knowledge_chunk": "kb_uid",
            "knowledge_job": "kb_uid",
            "graph_extraction_revision": "kb_uid",
            "graph_outbox_event": "kb_uid",
            "graph_projection_cursor": "kb_uid",
            "knowledge_graph_generation": "kb_uid",
            "evaluation_run": "kb_uid",
            "evaluation_dataset": "kb_uid",
        }
        for table, col in child_tables.items():
            statements.append(
                f"DELETE FROM {table} WHERE {col} IN ({uid_list})"
            )
        statements.append(
            f"DELETE FROM knowledge_topic WHERE kb_uid IN ({uid_list})"
        )
        statements.append(
            "DELETE FROM team_member WHERE user_id IN ('1747407811@qq.com')"
        )
        statements.append("DELETE FROM knowledge_access_audit_log")

        # ── user-scoped reattribute ──
        u_vals = ", ".join(f"'{v}'" for v in LEGACY_USERS)
        for table in USER_SCOPED_TABLES:
            statements.append(
                f"UPDATE {table} SET user_id='{TARGET}' WHERE user_id IN ({u_vals})"
            )

        # ── tenant-scoped reattribute ──
        for table in TENANT_SCOPED_TABLES:
            statements.append(
                f"UPDATE {table} SET tenant_id='{TARGET}' WHERE {_in_old('tenant_id')}"
            )

        # ── knowledge_topic: owner + legacy user col ──
        statements.append(
            f"UPDATE knowledge_topic SET tenant_id='{TARGET}', owner_user_id='{TARGET}', "
            f"user_id='{TARGET}' WHERE {_in_old('tenant_id')}"
        )
        # knowledge_item/file legacy user col (nullable)
        for table in ("knowledge_item", "knowledge_file"):
            statements.append(
                f"UPDATE {table} SET user_id='{TARGET}' "
                f"WHERE user_id IN ({u_vals}) OR user_id IS NULL"
            )
        # entity family: knowledge_entity has user_id + tenant_id
        statements.append(
            f"UPDATE knowledge_entity SET user_id='{TARGET}' WHERE user_id IN ({u_vals})"
        )
        statements.append(
            f"UPDATE knowledge_entity SET tenant_id='{TARGET}' WHERE {_in_old('tenant_id')}"
        )
        for table in ("entity_alias", "entity_mention", "entity_relation"):
            statements.append(
                f"UPDATE {table} SET tenant_id='{TARGET}' WHERE {_in_old('tenant_id')}"
            )

        if apply:
            for stmt in statements:
                conn.execute(text(stmt))
            conn.commit()
    return statements


def _migrate_milvus(engine, target: str) -> dict:
    """Re-key vector rows whose tenant_id/user_id is legacy to *target*.

    Idempotent: each row is upserted by its existing primary key with only the
    identity fields changed (embeddings preserved).
    """
    from pymilvus import Collection, connections, utility

    stats = {"document_rows": 0, "memory_rows": 0, "pku_rows": 0, "ckp_rows": 0}
    host = settings.MILVUS_HOST or "localhost"
    port = int(settings.MILVUS_PORT or 19530)
    if not connections.has_connection("default"):
        connections.connect("default", host=host, port=port)

    # Collect the exact kb_uids that are being re-homed (alive topics now under target).
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT kb_uid FROM knowledge_topic WHERE tenant_id=:t AND deleted_at IS NULL"),
            {"t": target},
        ).fetchall()
    target_kb_uids = {r[0] for r in rows}

    # ── document chunk collections prism_kb_* ──
    for name in utility.list_collections():
        if not name.startswith("prism_kb_"):
            continue
        collection = Collection(name)
        collection.load(timeout=60)
        migrated = _rekey_collection(
            collection,
            scope_filter=lambda expr_old: (
                f'(tenant_id == "{expr_old}")' if expr_old else 'tenant_id == ""'
            ),
            identity_kind="tenant",
            target=target,
            extra_guard=lambda r: r.get("kb_uid") in target_kb_uids,
        )
        stats["document_rows"] += migrated
    return stats


def _rekey_collection(collection, *, scope_filter, identity_kind: str, target: str, extra_guard=None) -> int:
    """Upsert rows owned by a legacy tenant/user under the new identity.

    Reads rows in pages by the legacy identity expression, rewrites the identity
    field, and upserts with the SAME primary key (so no re-embedding is needed).
    """
    from pymilvus import Collection

    total = 0
    legacy = ("default-user", "legacy-personal", "team", "tenant-a", "")
    for old in legacy:
        expr = scope_filter(old)
        offset = 0
        while True:
            try:
                hits = collection.query(
                    expr=expr,
                    output_fields=["*"],
                    offset=offset,
                    limit=4096,
                    timeout=60,
                )
            except Exception as exc:
                print(f"  [milvus] query failed for {expr}: {exc}")
                break
            if not hits:
                break
            payload = []
            for row in hits:
                if extra_guard and not extra_guard(row):
                    continue
                new_row = dict(row)
                if identity_kind == "tenant":
                    new_row["tenant_id"] = target
                else:
                    new_row["user_id"] = target
                payload.append(new_row)
            if payload:
                collection.upsert(payload, timeout=60)
                total += len(payload)
            if len(hits) < 4096:
                break
            offset += len(hits)
    return total


def _migrate_es(engine, target: str) -> dict:
    """Re-key Elasticsearch ``prism_chunks_v2`` docs to *target* tenant.

    Docs are matched by (kb_uid, tenant_id) across ALL generations (ES generation
    is the topic's active_index_generation, not the MySQL chunk generation).
    """
    from elasticsearch import Elasticsearch

    es = Elasticsearch([settings.ES_HOST or "http://127.0.0.1:9200"])
    index = "prism_chunks_v2"
    if not es.indices.exists(index=index):
        return {"es_rows": 0}
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT kb_uid FROM knowledge_topic WHERE tenant_id=:t AND deleted_at IS NULL"),
            {"t": target},
        ).fetchall()
    total = 0
    for (kb_uid,) in rows:
        for old in ("default-user", "legacy-personal", "team", "tenant-a"):
            body = {
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"kb_uid": kb_uid}},
                            {"term": {"tenant_id": old}},
                        ]
                    }
                },
                "script": {
                    "source": "ctx._source.tenant_id = params.t",
                    "params": {"t": target},
                },
            }
            try:
                resp = es.update_by_query(
                    index=index,
                    routing=kb_uid,
                    refresh=True,
                    body=body,
                    conflicts="proceed",
                )
                total += int(resp.get("updated", 0))
            except Exception as exc:
                print(f"  [es] update_by_query failed kb={kb_uid} old={old}: {exc}")
    return {"es_rows": total}


def _migrate_neo4j(target: str) -> dict:
    """Re-key Neo4j scoped graph nodes to *target* tenant.

    Scoped node ids are ``{tenant}:{kb}:{gen}:{...}``. Both ``tenant_id`` and the
    id prefix are rewritten in place (relationships are node references, so the
    graph structure is preserved).
    """
    try:
        from neo4j import GraphDatabase
    except Exception as exc:
        print(f"  [neo4j] driver unavailable: {exc}")
        return {"neo4j_nodes": 0, "skipped": True}
    uri = settings.NEO4J_URI or "bolt://localhost:7687"
    user = settings.NEO4J_USERNAME or "neo4j"
    pwd = settings.NEO4J_PASSWORD or "password"
    total = 0
    try:
        driver = GraphDatabase.driver(uri, auth=(user, pwd))
        with driver.session() as session:
            for old in ("default-user", "legacy-personal"):
                result = session.run(
                    """
                    MATCH (n)
                    WHERE (n:ScopedEntity OR n:ScopedAlias OR n:ScopedSource)
                      AND n.tenant_id = $old
                    SET n.tenant_id = $target,
                        n.id = $target + substring(n.id, size(n.tenant_id))
                    RETURN count(n) AS c
                    """,
                    old=old,
                    target=target,
                )
                for record in result:
                    total += int(record["c"] or 0)
        driver.close()
    except Exception as exc:
        print(f"  [neo4j] re-key failed: {exc}")
        return {"neo4j_nodes": 0, "skipped": True, "error": str(exc)}
    return {"neo4j_nodes": total}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="nizhenshigoule@gmail.com")
    parser.add_argument("--dry-run", action="store_true", help="print statements and row counts only")
    parser.add_argument("--apply", action="store_true", help="execute the MySQL migration")
    parser.add_argument("--indexes", action="store_true", help="also re-key Milvus/ES/Neo4j (requires --apply)")
    args = parser.parse_args()

    global TARGET
    TARGET = args.target

    engine = create_engine(settings.DATABASE_URL, connect_args={"connect_timeout": 10}, future=True)

    print(f"=== Reattributing legacy data to {TARGET} ===")
    statements = _run_mysql(engine, apply=args.apply)

    with engine.connect() as conn:
        print("\n-- row counts to be affected --")
        for table, col in (("chat_session", "user_id"),):
            n = conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {col}='default-user'")).scalar()
            print(f"  {table}.{col} legacy: {n}")
        for table in USER_SCOPED_TABLES:
            n = conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE user_id='default-user'")).scalar()
            print(f"  {table}.user_id legacy: {n}")
        for table in TENANT_SCOPED_TABLES:
            n = conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {_in_old('tenant_id')}")).scalar()
            print(f"  {table}.tenant_id legacy: {n}")

    if not args.apply:
        print(f"\n[DRY-RUN] {len(statements)} statements would run (see below). Pass --apply to execute.")
        for s in statements:
            print("  SQL:", s)
        print("Use --apply --indexes to also re-key Milvus/Elasticsearch/Neo4j.")
        return

    print(f"\nApplied {len(statements)} MySQL statements.")

    if args.indexes:
        print("\n-- re-keying Milvus --")
        try:
            print(_migrate_milvus(engine, TARGET))
        except Exception as exc:
            print(f"  [milvus] skipped: {exc}")
        print("\n-- re-keying Elasticsearch --")
        try:
            print(_migrate_es(engine, TARGET))
        except Exception as exc:
            print(f"  [es] skipped: {exc}")
        print("\n-- re-keying Neo4j --")
        print(_migrate_neo4j(TARGET))
    else:
        print("Skipped index re-keying (pass --indexes to also update Milvus/ES/Neo4j).")


if __name__ == "__main__":
    main()
