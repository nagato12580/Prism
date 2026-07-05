"""graphify analysis layer: export the Entity graph, run community/god/surprising,
write community_id / is_god / cohesion / surprising edges back to Neo4j.

The Neo4j/MySQL graph store is the single source of truth; the NetworkX graph
built here is temporary (built from MySQL, discarded after analysis).
"""
import logging
from collections import defaultdict
from itertools import combinations

from backend.app.models import EntityMention, EntityRelation, KnowledgeEntity

logger = logging.getLogger("uvicorn.error")


def export_graph_for_graphify(db, user_id: str = "default-user") -> dict:
    """Export entities + entity-entity edges as a graphify {nodes, edges} dict.

    Edges come from two sources:
      1. explicit EntityRelation rows (predicate -> relation)
      2. co-occurrence: two entities mentioned by the same Source (chunk) -> edge
    Co-occurrence projects the Source-Entity bipartite graph onto an
    Entity-Entity homogeneous graph, which is what community detection needs.
    """
    entities = (
        db.query(KnowledgeEntity)
        .filter(KnowledgeEntity.user_id == user_id, KnowledgeEntity.status != "deprecated")
        .all()
    )
    nodes = [
        {
            "id": e.id,
            "label": e.canonical_name or e.id,
            "file_type": "concept",
            "source_file": f"entity:{e.id}",
            "source_location": None,
        }
        for e in entities
    ]
    active_ids = {e.id for e in entities}

    edges = []
    seen = set()

    def _add_edge(src, tgt, relation, confidence, score):
        if src not in active_ids or tgt not in active_ids or src == tgt:
            return
        key = (src, tgt) if src < tgt else (tgt, src)
        if key in seen:
            return
        seen.add(key)
        edges.append(
            {
                "source": src,
                "target": tgt,
                "relation": relation,
                "confidence": confidence,
                "confidence_score": score,
                "source_file": f"entity:{src}",
                "source_location": None,
                "weight": 1.0,
            }
        )

    # 1) explicit relations
    for rel in db.query(EntityRelation).filter(EntityRelation.source_kind == "document_chunk").all():
        if rel.object_entity_id:
            _add_edge(rel.subject_entity_id, rel.object_entity_id, rel.predicate or "related_to", "INFERRED", float(rel.confidence or 0.75))

    # 2) co-occurrence: entities sharing a chunk source
    by_source = defaultdict(set)
    for m in db.query(EntityMention).filter(EntityMention.source_kind == "document_chunk").all():
        if m.entity_id in active_ids:
            by_source[m.source_id].add(m.entity_id)
    for members in by_source.values():
        members = list(members)
        if len(members) < 2:
            continue
        for a, b in combinations(members, 2):
            _add_edge(a, b, "co_occurs_with", "INFERRED", 0.75)

    return {"nodes": nodes, "edges": edges}
