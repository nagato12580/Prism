"""Clean up all knowledge base data: MySQL + Neo4j + Milvus."""
from __future__ import annotations

import os
import sys
import pymysql
from pymilvus import connections, utility

MYSQL = {
    "host": "localhost",
    "port": 13306,
    "user": "root",
    "password": os.environ.get("MYSQL_ROOT_PASSWORD", "change-me"),
    "database": "prism_db",
}

TABLES = [
    # ingestion
    "knowledge_topic", "knowledge_item", "knowledge_chunk", "knowledge_file", "knowledge_job",
    # entity
    "knowledge_entity", "entity_alias", "entity_mention", "entity_relation",
    # governance
    "personal_knowledge_unit", "canonical_knowledge_point", "pku_canonical_link",
    "pku_relation", "canonical_relation",
    # graph
    "graph_community", "graph_insight_summary",
    # assets
    "personal_asset", "personal_asset_item", "personal_asset_unit",
    "asset_relation", "extension_point", "asset_usage_event",
    # memory
    "memory_entry", "memory_source", "memory_statement", "memory_entity",
    "memory_relation", "memory_event", "memory_insight", "memory_draft",
    "memory_extraction_run",
    # wiki
    "wiki_document", "wiki_concept", "wiki_knowledge_point",
    "wiki_knowledge_relation", "wiki_image", "wiki_extraction_log",
    # agent traces
    "agent_trace", "agent_trace_step", "agent_trace_evidence",
]

COLLECTION = "prism_knowledge"


def cleanup_mysql():
    conn = pymysql.connect(**MYSQL)
    cur = conn.cursor()
    cur.execute("SET FOREIGN_KEY_CHECKS=0")
    for t in TABLES:
        try:
            cur.execute(f"TRUNCATE TABLE `{t}`")
            print(f"  [MySQL] TRUNCATE {t} ✓")
        except Exception as e:
            print(f"  [MySQL] SKIP {t}: {e}")
    cur.execute("SET FOREIGN_KEY_CHECKS=1")
    conn.commit()
    conn.close()
    # verify
    conn2 = pymysql.connect(**MYSQL)
    cur2 = conn2.cursor()
    cur2.execute("""
        SELECT table_name, table_rows
        FROM information_schema.tables
        WHERE table_schema = %s AND table_name IN ({})
    """.format(",".join(["%s"] * len(TABLES))), [MYSQL["database"]] + TABLES)
    rows = cur2.fetchall()
    total = sum(r[1] or 0 for r in rows)
    print(f"  [MySQL] Remaining rows total: {total}")
    conn2.close()


def cleanup_milvus():
    connections.connect(host="localhost", port="19530")
    if utility.has_collection(COLLECTION):
        utility.drop_collection(COLLECTION)
        print(f"  [Milvus] Dropped collection: {COLLECTION}")
    else:
        print(f"  [Milvus] Collection '{COLLECTION}' not found, skip")
    connections.disconnect("default")


if __name__ == "__main__":
    print("=== Cleaning MySQL ===")
    cleanup_mysql()

    print("\n=== Cleaning Milvus ===")
    cleanup_milvus()

    print("\n=== Neo4j ===")
    print("  Run: docker exec prism-neo4j-entity-graph cypher-shell -u neo4j -p password 'MATCH (n) DETACH DELETE n'")
    print("  (Already cleared in a previous step — skipping)")

    print("\nDone. Knowledge base is clean.")
