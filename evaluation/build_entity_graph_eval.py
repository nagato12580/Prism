from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from pathlib import Path

from neo4j import GraphDatabase
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.config import settings
from backend.app.models.knowledge_item import KnowledgeChunk


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
PERSON_RE = re.compile(r"^[A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+)+$")
ORG_HINT_RE = re.compile(
    r"(University|Institute|Laboratory|Lab|School|Department|Ltd\.?|Inc\.?|Corporation|College)",
    re.IGNORECASE,
)
NOISE_RE = re.compile(r"[`{}\[\]<>]|###|```|::|#include|def\s+|class\s+|json|yaml|csv", re.IGNORECASE)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = PROJECT_ROOT / "evaluation" / "datasets" / "entity_graph_v1.json"


def _is_high_quality_entity(entity_type: str, canonical_name: str) -> bool:
    name = (canonical_name or "").strip()
    if not name:
        return False
    if len(name) > 120:
        return False
    if NOISE_RE.search(name):
        return False
    if "TEST@EXAMPLE.COM" in name.upper():
        return False

    if entity_type == "email":
        return bool(EMAIL_RE.fullmatch(name))

    if entity_type == "person":
        if not (bool(PERSON_RE.fullmatch(name)) and len(name.split()) <= 4):
            return False
        # Reject the same stop-word set used during extraction
        lowered = name.lower()
        person_noise = {
            "senior member", "junior member", "associate professor", "assistant professor",
            "corresponding author", "proximal gradient", "stochastic gradient",
            "gradient descent", "beam search", "multi-view", "multi view",
            "deep norm", "post norm", "pre norm",
        }
        if lowered in person_noise:
            return False
        parts = name.split()
        if any(p.lower() in {"member", "professor", "author", "editor", "gradient",
                              "search", "norm"} for p in parts):
            return False
        return True

    if entity_type == "organization":
        if not (bool(ORG_HINT_RE.search(name)) and len(name) <= 80):
            return False
        # Reject copyright boilerplate and other sentence-like fragments that happen
        # to contain an org keyword (e.g. "University").
        lowered = name.lower()
        org_noise_phrases = {
            "licensed use", "downloaded on", "limited to", "authorized",
        }
        if any(phrase in lowered for phrase in org_noise_phrases):
            return False
        # Reject strings that start with a month/year or contain digit-heavy prefixes.
        if re.match(r"^[A-Z]{3,9}\s+\d{4}", name):
            return False
        # Reject if more than 6 whitespace-separated words (sentence, not org name).
        if len(name.split()) > 6:
            return False
        return True

    if entity_type == "paper":
        # Keep only concise title-like paper strings; most current paper entities are noisy long chunks.
        if len(name) > 80:
            return False
        if not any(ch.isalpha() for ch in name):
            return False
        # Reject all-caps metadata-like strings.
        alpha = sum(ch.isalpha() for ch in name)
        upper = sum(ch.isupper() for ch in name)
        if alpha and upper / alpha > 0.8 and len(name.split()) > 8:
            return False
        return True

    return False


def _question_for(entity_type: str, canonical_name: str) -> str:
    if entity_type == "email":
        return f"邮箱 `{canonical_name}` 出现在哪些资料里，它关联了哪些知识点？"
    if entity_type == "person":
        return f"人物 `{canonical_name}` 出现在哪些资料里，它关联了哪些知识点？"
    if entity_type == "organization":
        return f"机构 `{canonical_name}` 出现在哪些资料里，它关联了哪些知识点？"
    return f"实体 `{canonical_name}` 出现在哪些资料里，它关联了哪些知识点？"

def _rows(limit: int) -> Iterable[dict]:
    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
    )
    try:
        with driver.session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(
                """
                MATCH (e:Entity)<-[:MENTIONS_ENTITY]-(p:PKU)-[:EVIDENCED_BY]->(src:Source)
                WHERE src.source_kind = 'document_chunk' AND src.source_id IS NOT NULL
                WITH e,
                     collect(DISTINCT src {source_id: src.source_id, item_id: src.item_id, title: src.title}) AS sources,
                     count(DISTINCT p) AS pku_count,
                     collect(DISTINCT p.id) AS pku_ids
                RETURN e.id AS entity_id,
                       e.canonical_name AS canonical_name,
                       e.entity_type AS entity_type,
                       size(sources) AS chunk_count,
                       pku_count,
                       pku_ids,
                       sources
                ORDER BY chunk_count DESC, pku_count DESC, canonical_name ASC
                LIMIT $limit
                """,
                {"limit": max(limit * 10, 200)},
            )
            for record in result:
                yield dict(record)
    finally:
        driver.close()


def build_dataset(limit: int) -> dict:
    engine = create_engine(settings.DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()

    queries: list[dict] = []
    kept: list[dict] = []
    skipped: list[dict] = []

    try:
        for row in _rows(limit):
            canonical_name = str(row.get("canonical_name") or "")
            entity_type = str(row.get("entity_type") or "")
            sources = list(row.get("sources") or [])
            chunk_count = int(row.get("chunk_count") or 0)
            pku_count = int(row.get("pku_count") or 0)

            if chunk_count < 1 or pku_count < 1:
                skipped.append({"reason": "insufficient_support", **row})
                continue
            if not _is_high_quality_entity(entity_type, canonical_name):
                skipped.append({"reason": "noise_filtered", **row})
                continue

            # Entity-centric eval currently focuses on crisp, name-like entities.
            if entity_type not in {"email", "person", "organization"}:
                skipped.append({"reason": "entity_type_not_in_eval_scope", **row})
                continue

            relevant_children: list[dict] = []
            seen_chunk_ids: set[str] = set()
            for src in sources:
                source_id = str(src.get("source_id") or "")
                if not source_id:
                    continue
                child_chunks = (
                    db.query(KnowledgeChunk)
                    .filter(KnowledgeChunk.parent_id == source_id, KnowledgeChunk.chunk_type == "child")
                    .order_by(KnowledgeChunk.chunk_index.asc(), KnowledgeChunk.created_at.asc(), KnowledgeChunk.id.asc())
                    .all()
                )
                if child_chunks:
                    for child in child_chunks:
                        if child.id in seen_chunk_ids:
                            continue
                        seen_chunk_ids.add(child.id)
                        relevant_children.append(
                            {
                                "chunk_id": str(child.id),
                                "item_id": child.item_id,
                                "source_kind": "document_chunk",
                                "chunk_text": child.chunk_text or "",
                            }
                        )
                else:
                    chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == source_id).first()
                    if chunk and chunk.id not in seen_chunk_ids:
                        seen_chunk_ids.add(chunk.id)
                        relevant_children.append(
                            {
                                "chunk_id": str(chunk.id),
                                "item_id": chunk.item_id,
                                "source_kind": "document_chunk",
                                "chunk_text": chunk.chunk_text or "",
                            }
                        )

            if len(relevant_children) < 1:
                skipped.append({"reason": "insufficient_chunks_after_filter", **row})
                continue

            qid = f"eq{len(queries) + 1:03d}"
            query = {
                "id": qid,
                "question": _question_for(entity_type, canonical_name),
                "language": "zh",
                "entity_name": canonical_name,
                "entity_type": entity_type,
                "entity_id": row.get("entity_id"),
                "relevant_children": relevant_children,
                "meta": {
                    "expected_path": "Entity<-MENTIONS_ENTITY<-PKU-[:EVIDENCED_BY]->Source",
                    "pku_count": pku_count,
                    "chunk_count": chunk_count,
                    "pku_ids": row.get("pku_ids") or [],
                },
            }
            queries.append(query)
            kept.append({"entity_name": canonical_name, "entity_type": entity_type, "chunk_count": chunk_count, "pku_count": pku_count, "gold_child_count": len(relevant_children)})
            if len(queries) >= limit:
                break
    finally:
        db.close()

    return {
        "meta": {
            "name": "entity_graph_v1",
            "description": "Entity-centric retrieval eval built from Neo4j MENTIONS_ENTITY bridge edges",
            "total_queries": len(queries),
            "query_type": "entity-centric",
            "built_at": "2026-06-30",
            "filter_rules": {
                "allowed_entity_types": ["email", "person", "organization"],
                "max_name_length": 120,
                "reject_noise_regex": NOISE_RE.pattern,
                "min_chunk_count": 1,
                "min_pku_count": 1,
                "notes": "paper entities are restricted to concise title-like strings; TEST@EXAMPLE.COM and code/markup fragments are filtered out",
            },
        },
        "queries": queries,
        "build_debug": {
            "kept": kept,
            "skipped_count": len(skipped),
            "sample_skipped": skipped[:20],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build entity-centric eval dataset from graph bridge edges")
    parser.add_argument("--limit", type=int, default=12, help="Maximum number of eval queries to emit")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUT), help="Output dataset path")
    args = parser.parse_args()

    dataset = build_dataset(limit=args.limit)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")

    print(out)
    print(f"queries={dataset['meta']['total_queries']}")
    for q in dataset["queries"][:10]:
        print(f"{q['id']} | {q['entity_type']} | {q['entity_name']} | rel_chunks={len(q['relevant_children'])}")


if __name__ == "__main__":
    main()
