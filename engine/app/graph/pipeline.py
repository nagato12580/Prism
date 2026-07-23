from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from engine.app.config import settings

from ..extraction.stage_a import extract_stage_a_parallel
from .analyzer import run_analysis
from .schema import GraphSourceEnvelope
from backend.app.services.entity_extraction import settle_entity_candidates
from backend.app.services.graph_client import GraphClient
from backend.app.services.graph_projection import project_asset_unit_entities, project_item_entities


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
    if db is None:
        return extracted
    candidates = list(extracted.get("candidates") or [])
    if not candidates:
        return extracted
    settle_entity_candidates(
        db,
        candidates,
        source_kind=str(extracted.get("source_kind") or ""),
        source_id=str(extracted.get("source_id") or ""),
        item_id=extracted.get("item_id"),
        chunk_id=extracted.get("source_id") if extracted.get("source_kind") == "document_chunk" else None,
        user_id=_source_user_id(extracted),
    )
    db.flush()
    return extracted


def project_source_graph(persisted: dict, db=None, graph_client=None) -> None:
    if db is None:
        return
    source_kind = str(persisted.get("source_kind") or "")
    user_id = _source_user_id(persisted)
    with _graph_client_scope(graph_client) as client:
        if source_kind == "document_chunk":
            item_id = persisted.get("item_id")
            if item_id:
                project_item_entities(
                    db, client, item_id=str(item_id), user_id=user_id,
                    graph_generation=persisted.get("graph_generation"),
                )
        elif source_kind == "personal_asset_unit":
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
