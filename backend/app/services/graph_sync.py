import logging

from backend.app.config import settings
from backend.app.services.graph_client import GraphClient
from backend.app.services.graph_projection import (
    GraphProjectionResult,
    project_ckp_graph,
    project_entity_graph,
    project_pku_entity_mentions,
)

logger = logging.getLogger("uvicorn.error")


def project_governance_graph_if_enabled(
    db,
    *,
    user_id: str = "default-user",
    pku_ids: set[str] | None = None,
    ckp_ids: set[str] | None = None,
    entity_ids: set[str] | None = None,
) -> dict[str, GraphProjectionResult] | None:
    """Project CKP/PKU, Entity, and PKU→Entity bridge edges when graph sync is enabled.

    When ``pku_ids``, ``ckp_ids``, or ``entity_ids`` are provided, only the specified
    items are projected (incremental mode).  When all are ``None`` (default), a full
    scan of all active items is performed.

    This is intentionally best-effort: graph projection is a secondary index update
    and must not roll back successful governance settlement.
    """
    if not settings.ENTITY_GRAPH_ENABLED:
        return None

    graph = GraphClient()
    try:
        ckp_result = project_ckp_graph(db, graph, user_id=user_id, ckp_ids=ckp_ids, pku_ids=pku_ids)
        entity_result = project_entity_graph(db, graph, user_id=user_id, entity_ids=entity_ids)
        bridge_result = project_pku_entity_mentions(db, graph, user_id=user_id, pku_ids=pku_ids, entity_ids=entity_ids)
        logger.info(
            "[graph_projection] projected user_id=%s ckp=%s pku=%s entity=%s alias=%s "
            "ckp_rel=%s entity_rel=%s pku_entity_mentions=%s incremental=%s",
            user_id,
            ckp_result.ckp_count,
            ckp_result.pku_count,
            entity_result.entity_count,
            entity_result.alias_count,
            ckp_result.relation_count,
            entity_result.relation_count,
            bridge_result.pku_entity_mention_count,
            pku_ids is not None or ckp_ids is not None or entity_ids is not None,
        )
        return {"ckp": ckp_result, "entity": entity_result, "bridge": bridge_result}
    except Exception:
        logger.exception("[graph_projection] best-effort projection failed user_id=%s", user_id)
        return None
    finally:
        graph.close()
