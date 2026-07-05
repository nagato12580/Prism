"""P4 graph-driven CKP governance: map CKPs to entities, aggregate community
cohesion + god signals, and promote draft -> stable. Only promotes, never demotes.

Runs at the end of run_analysis (after Step B wrote community/god and P5 wrote
graph_community). Failure-isolated: never blocks analysis or ingestion.
"""
import logging
from datetime import datetime, timezone

from backend.app.models import EntityAlias, KnowledgeEntity
from backend.app.services.entity_resolution import normalize_entity_key

logger = logging.getLogger("uvicorn.error")


def _ckp_surfaces(ckp) -> list[str]:
    names: list[str] = []
    for field in ("concepts", "entities", "aliases"):
        val = getattr(ckp, field, None) or []
        if isinstance(val, list):
            names.extend(str(x) for x in val if x)
    # de-dup preserving order
    seen = set(); out = []
    for n in names:
        if n not in seen:
            seen.add(n); out.append(n)
    return out


def map_ckp_to_entities(db, ckp) -> list[str]:
    """Return backing KnowledgeEntity ids for a CKP via normalized_key + aliases."""
    keys = {normalize_entity_key(n) for n in _ckp_surfaces(ckp)}
    if not keys:
        return []
    user_id = getattr(ckp, "user_id", "default-user") or "default-user"
    # alias match first (covers surface variants)
    alias_rows = (
        db.query(EntityAlias.entity_id.label("eid"))
        .join(KnowledgeEntity, EntityAlias.entity_id == KnowledgeEntity.id)
        .filter(EntityAlias.normalized_key.in_(keys), KnowledgeEntity.user_id == user_id)
        .distinct()
        .all()
    )
    ids = [r.eid for r in alias_rows]
    if not ids:
        name_rows = (
            db.query(KnowledgeEntity.id)
            .filter(KnowledgeEntity.user_id == user_id, KnowledgeEntity.normalized_key.in_(keys))
            .all()
        )
        ids = [r.id for r in name_rows]
    # de-dup preserving order
    seen = set(); out = []
    for i in ids:
        if i not in seen:
            seen.add(i); out.append(i)
    return out


def aggregate_ckp_signals(db, graph, entity_ids: list[str], user_id: str = "default-user") -> dict:
    """Aggregate cohesion + god signals over backing entities.

    cohesion_score = max(graph_community.cohesion) over distinct backing communities.
    god_backed     = any backing entity is_god (Neo4j).
    """
    if not entity_ids:
        return {"cohesion_score": 0.0, "god_backed": False}

    # community per entity (Neo4j)
    cids: set[int] = set()
    for eid in entity_ids:
        try:
            cid = graph.entity_community(eid)
        except Exception as exc:
            logger.warning("[ckp_gov] entity_community_failed eid=%s err=%s", eid, exc)
            cid = None
        if cid is not None:
            cids.add(int(cid))

    # cohesion per community (graph_community table; P5)
    cohesion_score = 0.0
    if cids:
        try:
            from backend.app.models import GraphCommunity
            rows = db.query(GraphCommunity.cohesion).filter(
                GraphCommunity.user_id == user_id, GraphCommunity.community_id.in_(cids)
            ).all()
            scores = [float(r[0] or 0.0) for r in rows]
            cohesion_score = max(scores) if scores else 0.0
        except Exception as exc:
            logger.warning("[ckp_gov] cohesion_read_failed err=%s", exc)

    # god_backed (Neo4j batch)
    god_backed = False
    try:
        god_backed = any(graph.are_gods(entity_ids).values())
    except Exception as exc:
        logger.warning("[ckp_gov] are_gods_failed err=%s", exc)

    return {"cohesion_score": cohesion_score, "god_backed": god_backed}


from ..config import settings


def govern_ckp_status_by_graph(db, graph, user_id: str = "default-user") -> dict:
    """Promote draft CKPs to stable based on graph signals (cohesion / god).

    Only promotes; never demotes. Skips deprecated. Writes signals + reason to
    CKP.extra_meta. Failure-isolated: returns a result dict, never raises.
    """
    promoted = 0
    signaled = 0
    if not settings.GRAPH_GOV_ENABLED:
        return {"promoted": 0, "signaled": 0, "skipped": True}
    try:
        from backend.app.models import CanonicalKnowledgePoint

        ckps = (
            db.query(CanonicalKnowledgePoint)
            .filter(
                CanonicalKnowledgePoint.user_id == user_id,
                CanonicalKnowledgePoint.status != "deprecated",
            )
            .all()
        )
        for ckp in ckps:
            entity_ids = map_ckp_to_entities(db, ckp)
            sig = aggregate_ckp_signals(db, graph, entity_ids, user_id=user_id)
            reason = ""
            if ckp.status == "draft":
                if sig["cohesion_score"] >= settings.GRAPH_GOV_COHESION_THRESHOLD:
                    ckp.status = "stable"; promoted += 1
                    reason = f"graph:cohesion({sig['cohesion_score']:.2f})"
                elif sig["god_backed"]:
                    ckp.status = "stable"; promoted += 1
                    reason = "graph:god"
            # write signals regardless (transparency), preserve existing meta keys
            meta = dict(ckp.extra_meta or {})
            meta.update({
                "graph_cohesion": sig["cohesion_score"],
                "god_backed": sig["god_backed"],
                "reason": reason,
                "graph_governed_at": datetime.now(timezone.utc).isoformat(),
            })
            ckp.extra_meta = meta
            if entity_ids:
                signaled += 1
        db.commit()
        return {"promoted": promoted, "signaled": signaled}
    except Exception as exc:
        logger.warning("[ckp_gov] govern_failed err=%s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return {"promoted": 0, "signaled": 0, "error": str(exc)}
