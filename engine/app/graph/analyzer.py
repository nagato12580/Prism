"""graphify analysis layer: export the Entity graph, run community/god/surprising,
write community_id / is_god / cohesion / surprising edges back to Neo4j.

The Neo4j/MySQL graph store is the single source of truth; the NetworkX graph
built here is temporary (built from MySQL, discarded after analysis).
"""
import logging
from collections import defaultdict
from itertools import combinations

from backend.app.models import EntityMention, EntityRelation, KnowledgeEntity
from .ckp_governance import govern_ckp_status_by_graph
from .insights import compute_suggested_questions, generate_community_labels

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


def _remap_communities(new_comms: dict[int, list[str]], old: dict[str, int]) -> dict[str, int]:
    """Map new community ids back to stable old ids by max Jaccard overlap.

    new_comms: {new_cid: [node_ids]} from graphify.cluster
    old: {node_id: old_cid} read from Neo4j before recompute
    Returns {node_id: final_cid} where final_cid reuses old ids when possible.
    """
    old_by_cid: dict[int, set[str]] = defaultdict(set)
    for node_id, cid in old.items():
        old_by_cid[cid].add(node_id)

    used_old: set[int] = set()
    new_to_final: dict[int, int] = {}
    next_id = (max(old_by_cid.keys()) + 1) if old_by_cid else 0

    for new_cid, members in new_comms.items():
        member_set = set(members)
        best_old, best_score = None, 0.0
        for old_cid, old_set in old_by_cid.items():
            if old_cid in used_old or not old_set:
                continue
            union = member_set | old_set
            score = len(member_set & old_set) / len(union) if union else 0.0
            if score > best_score:
                best_score, best_old = score, old_cid
        if best_old is not None and best_score > 0:
            new_to_final[new_cid] = best_old
            used_old.add(best_old)
        else:
            new_to_final[new_cid] = next_id
            next_id += 1

    return {node_id: new_to_final[cid] for cid, members in new_comms.items() for node_id in members}


def run_analysis(db, graph, user_id: str = "default-user", top_god: int = 20, top_surprising: int = 20) -> dict:
    """Run graphify analysis over the full entity graph and write results to Neo4j.

    Never raises (caller wraps in try/except, but we guard anyway).
    """
    try:
        from graphify.build import build_from_json
        from graphify.cluster import cluster, score_all
        from graphify.analyze import surprising_connections
        from graphify.diagnostics import diagnose_extraction
    except Exception as exc:
        logger.warning("[analyzer] graphify_import_failed error=%s", exc)
        return {"node_count": 0, "skipped": True}

    exported = export_graph_for_graphify(db, user_id=user_id)
    node_count = len(exported["nodes"])
    if node_count == 0:
        return {"node_count": 0, "skipped": True}

    try:
        G = build_from_json(exported, directed=False)
        communities = cluster(G)                       # {cid: [members]}
        cohesion_by_cid = score_all(G, communities)    # {cid: float}
        old = graph.read_entity_communities() if hasattr(graph, "read_entity_communities") else {}
        final = _remap_communities(communities, old)   # {node_id: final_cid}

        # god nodes = top by degree (graphify.god_nodes filters out concept nodes,
        # so compute hubs directly)
        ranked = sorted(G.degree, key=lambda x: x[1], reverse=True)
        god_ids = {nid for nid, _ in ranked[:top_god]}

        # surprising connections
        surprising = []
        try:
            surprising = surprising_connections(G, communities, top_n=top_surprising)
        except Exception as exc:
            logger.warning("[analyzer] surprising_failed error=%s", exc)

        # write back per node
        for node_id, cid in final.items():
            graph.set_entity_analysis(
                node_id,
                community_id=int(cid),
                is_god=node_id in god_ids,
                cohesion=float(cohesion_by_cid.get(_new_cid_for_node(communities, node_id), 0.0)),
            )

        # write surprising edges
        for s in surprising:
            try:
                graph.relate(
                    "Entity", s.get("source"), "RELATED_TO", "Entity", s.get("target"),
                    {"surprising": True, "note": s.get("note", "")},
                )
            except Exception as exc:
                logger.warning("[analyzer] surprising_edge_write_failed %s", exc)

        # diagnostics: log only, never block
        try:
            diag = diagnose_extraction(exported, directed=False)
            dangling = diag.get("dangling_endpoint_edges", 0)
            if dangling:
                logger.warning("[analyzer] diagnostics dangling_endpoint_edges=%s", dangling)
        except Exception:
            pass

        # ---- P5: persist community labels + suggested questions ----
        try:
            from backend.app.models import GraphCommunity, GraphInsightSummary

            label_by_id = {n["id"]: n.get("label", n["id"]) for n in exported["nodes"]}
            members_by_cid: dict[int, list[str]] = defaultdict(list)
            for node_id, cid in final.items():
                members_by_cid[int(cid)].append(label_by_id.get(node_id, node_id))

            labels = generate_community_labels(dict(members_by_cid), user_id=user_id)

            # upsert per-community label + cohesion
            existing = {gc.community_id: gc for gc in db.query(GraphCommunity).filter_by(user_id=user_id).all()}
            for cid, members in members_by_cid.items():
                gc = existing.get(cid)
                if gc is None:
                    gc = GraphCommunity(user_id=user_id, community_id=cid)
                    db.add(gc)
                gc.label = labels.get(cid, "")
                gc.cohesion = float(cohesion_by_cid.get(_new_cid_for_node(communities, members[0]) if members else -1, 0.0))
            db.flush()

            questions = compute_suggested_questions(
                _graph=G, communities=communities,
                community_labels={cid: labels.get(cid, "") for cid in members_by_cid},
                top_n=7,
            )
            summ = db.query(GraphInsightSummary).filter_by(user_id=user_id).one_or_none()
            if summ is None:
                summ = GraphInsightSummary(user_id=user_id)
                db.add(summ)
            summ.suggested_questions = questions
            db.commit()
        except Exception as exc:
            logger.warning("[analyzer] insights_persist_failed err=%s", exc)
            try:
                db.rollback()
            except Exception:
                pass

        # ---- P4: graph-driven CKP governance (promote draft -> stable) ----
        try:
            govern_ckp_status_by_graph(db, graph, user_id=user_id)
        except Exception as exc:
            logger.warning("[analyzer] ckp_governance_failed err=%s", exc)

        return {"node_count": node_count, "communities": len(communities),
                "god_nodes": len(god_ids), "surprising": len(surprising)}
    except Exception as exc:
        logger.warning("[analyzer] run_analysis_failed error=%s", exc)
        return {"node_count": node_count, "skipped": True, "error": str(exc)}


def _new_cid_for_node(communities: dict[int, list[str]], node_id: str) -> int:
    for cid, members in communities.items():
        if node_id in members:
            return cid
    return -1
