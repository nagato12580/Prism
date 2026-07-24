from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from typing import Any

from engine.app.config import settings

from ..extraction.stage_a import extract_stage_a_parallel
from .analyzer import run_analysis
from .schema import GraphSourceEnvelope
from backend.app.services.entity_extraction import settle_entity_candidates
from backend.app.services.graph_client import GraphClient
from backend.app.services.graph_facts import GraphFactScope, GraphFactWriter
from backend.app.services.graph_projection import project_asset_unit_entities, project_item_entities

# Extractor config identity: model + prompt version. Hashed into the extraction
# revision key so a model/prompt change (Plan 5) re-extracts under a new graph
# generation. Pinned as a constant until the graph generation plan introduces
# versioned extractor configs.
_EXTRACTOR_CONFIG_SALT = "stage_a:v1"


def _extractor_config_hash() -> str:
    model = settings.ENTITY_EXTRACT_MODEL or ""
    return sha256(f"{model}|{_EXTRACTOR_CONFIG_SALT}".encode("utf-8")).hexdigest()


def _content_hash(text: str) -> str:
    return sha256((text or "").encode("utf-8")).hexdigest()


def run_graph_ingest_pipeline(
    env: dict,
    *,
    db=None,
    graph_client=None,
    run_detect: bool = True,
    run_extract: bool = True,
    run_persist: bool = True,
    run_project: bool = True,
    run_analyze: bool = True,
) -> dict:
    payload = dict(env)
    detected = detect_source(payload) if run_detect else str(payload.get("detected") or payload.get("source_kind") or "")
    extracted = extract_source_graph(payload, detected, db=db) if run_extract else {**payload, "detected": detected}
    persisted = persist_source_graph(extracted, db=db) if run_persist else extracted
    if run_project:
        project_source_graph(persisted, db=db, graph_client=graph_client)
    if run_analyze:
        analyze_source_graph(persisted, db=db, graph_client=graph_client)
    return persisted


def detect_source(env: dict) -> str:
    return GraphSourceEnvelope.model_validate(env).source_kind


def extract_source_graph(env: dict, detected: str, db=None) -> dict:
    envelope = GraphSourceEnvelope.model_validate(env)
    if not envelope.text.strip():
        return {
            **envelope.model_dump(),
            "detected": detected,
            "candidates": [],
        }
    per_source = extract_stage_a_parallel([(envelope.source_id, envelope.text)])
    return {
        **envelope.model_dump(),
        "detected": detected,
        "candidates": per_source.get(envelope.source_id, []),
    }


def persist_source_graph(extracted: dict, db=None) -> dict:
    """Settle extracted candidates to scoped MySQL facts + outbox events.

    document_chunk routes through ``GraphFactWriter`` so fact changes and
    outbox events commit atomically; projectors apply them to Neo4j/Milvus
    asynchronously. personal_asset_unit keeps the legacy unscoped settle path
    until the asset-layer cutover.
    """
    if db is None:
        return extracted
    candidates = list(extracted.get("candidates") or [])
    source_kind = str(extracted.get("source_kind") or "")
    if source_kind == "document_chunk":
        graph_generation = str(extracted.get("graph_generation") or "")
        tenant_id = str(extracted.get("tenant_id") or "")
        kb_uid = str(extracted.get("kb_uid") or "")
        if graph_generation and tenant_id and kb_uid:
            scope = GraphFactScope(
                tenant_id=tenant_id,
                kb_uid=kb_uid,
                file_uid=str(extracted.get("file_uid") or ""),
                item_id=str(extracted.get("item_id") or ""),
                chunk_uid=str(extracted.get("chunk_uid") or extracted.get("source_id") or ""),
                graph_generation=graph_generation,
            )
            try:
                GraphFactWriter(db).settle(
                    scope,
                    candidates,
                    content_hash=_content_hash(extracted.get("text") or ""),
                    extractor_config_hash=_extractor_config_hash(),
                    model_version=settings.ENTITY_EXTRACT_MODEL or "",
                    prompt_version=_EXTRACTOR_CONFIG_SALT,
                )
                db.flush()
            except Exception:
                # Failure isolation: graph fact settlement never breaks
                # ingestion. Projector lag / retry is handled out of band.
                raise
            return extracted
    # Legacy / asset-unit path: unscoped settle (no outbox events).
    if not candidates:
        return extracted
    settle_entity_candidates(
        db,
        candidates,
        source_kind=source_kind,
        source_id=str(extracted.get("source_id") or ""),
        item_id=extracted.get("item_id"),
        chunk_id=extracted.get("source_id") if source_kind == "document_chunk" else None,
        user_id=_source_user_id(extracted),
    )
    db.flush()
    return extracted


def project_source_graph(persisted: dict, db=None, graph_client=None) -> None:
    """Project only personal_asset_unit entities directly to Neo4j.

    document_chunk projection is now driven by the outbox projectors
    (engine.app.graph.neo4j_projector) so Neo4j is never written before the
    MySQL fact/outbox transaction commits. The legacy direct projection for
    document_chunk is intentionally not called here anymore.
    """
    if db is None:
        return
    source_kind = str(persisted.get("source_kind") or "")
    if source_kind != "personal_asset_unit":
        return
    user_id = _source_user_id(persisted)
    with _graph_client_scope(graph_client) as client:
        project_asset_unit_entities(
            db,
            client,
            asset_unit_id=str(persisted.get("source_id") or ""),
            user_id=user_id,
        )


def analyze_source_graph(persisted: dict, db=None, graph_client=None) -> None:
    if db is None or not settings.GRAPH_ANALYSIS_ENABLED:
        return
    with _graph_client_scope(graph_client) as client:
        run_analysis(db, client, user_id=_source_user_id(persisted))


def _source_user_id(payload: dict[str, Any]) -> str:
    return str(payload.get("user_id") or "default-user")


@contextmanager
def _graph_client_scope(graph_client):
    if graph_client is not None:
        yield graph_client
        return
    client = GraphClient()
    try:
        yield client
    finally:
        client.close()
