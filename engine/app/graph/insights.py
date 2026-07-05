"""P5 graph insights: signal gating + community labeling + question mining +
per-query insight block injection (mirrors active_recall).

Insights are precomputed in run_analysis (community labels via cheap LLM,
suggested_questions structurally) and stored in graph_community /
graph_insight_summary. graph_insights_context() reads them per-query and
returns a short background block (or "" ) injected into the system prompt.
"""
import logging

from ..config import settings
from ..llm.client import chat

logger = logging.getLogger("uvicorn.error")

_INSIGHT_SIGNALS = ("关系", "联系", "区别", "还有", "相关", "关联", "为什么", "怎么办", "怎么", "哪些", "之间", "属于")


def has_insight_signal(query: str) -> bool:
    text = (query or "").strip()
    if not text or len(text) < 2:
        return False
    return any(sig in text for sig in _INSIGHT_SIGNALS)


def generate_community_labels(communities_by_cid: dict[int, list[str]], user_id: str = "default-user") -> dict[int, str]:
    """One cheap LLM call per community -> <=6 char Chinese label.

    communities_by_cid: {cid: [entity surface names]}.
    Returns {cid: label}. Empty on any failure (non-fatal).
    """
    if not communities_by_cid:
        return {}
    model = settings.COMMUNITY_LABEL_MODEL or None
    labels: dict[int, str] = {}
    for cid, names in communities_by_cid.items():
        names = [n for n in names if n][:12]
        if not names:
            continue
        prompt = (
            "用一个不超过6个汉字的中文短语概括下面这组知识点的共同主题，只输出短语本身：\n"
            + "、".join(names)
        )
        try:
            raw = chat([{"role": "user", "content": prompt}], model=model)
            label = (raw or "").strip().strip("\"'""").replace("\n", "")[:6]
            if label:
                labels[cid] = label
        except Exception as exc:
            logger.warning("[insights] community_label_failed cid=%s err=%s", cid, exc)
    return labels


# graphify's bridge-node questions are filtered out for concept nodes (same as
# god_nodes); keep god / ambiguous_edge / surprising-derived questions only.
_KEEP_QUESTION_TYPES = {"god", "ambiguous_edge", "verification", "isolated"}


def compute_suggested_questions(
    _graph=None,
    communities: dict | None = None,
    community_labels: dict | None = None,
    top_n: int = 7,
    _questions_override: list[dict] | None = None,
    _questions_fn=None,
) -> list[dict]:
    """Structural question mining via graphify.suggest_questions (no LLM).

    Drops bridge_node (concept-filtered) and other unhelpful types.
    Returns [{type, question, why}]. Empty on any failure (non-fatal).
    """
    try:
        if _questions_override is not None:
            raw = _questions_override
        else:
            from graphify.analyze import suggest_questions
            fn = _questions_fn or suggest_questions
            raw = fn(_graph, communities or {}, community_labels or {}, top_n=top_n)
    except Exception as exc:
        logger.warning("[insights] suggest_questions_failed err=%s", exc)
        return []
    kept = [q for q in raw if isinstance(q, dict) and q.get("type") in _KEEP_QUESTION_TYPES]
    return kept[:top_n]


def graph_insights_context(
    query: str,
    user_id: str = "default-user",
    *,
    db=None,
    graph_client=None,
    enabled: bool | None = None,
) -> str:
    """Return a short graph-insight background block for the query, or "".

    Mirrors active_recall: signal-gated, never raises, never delays first token.
    Caller may pass db/graph_client for testing; production path builds them.
    """
    if enabled is None:
        enabled = settings.GRAPH_INSIGHTS_ENABLED
    if not enabled or not has_insight_signal(query):
        return ""

    own_db = db is None
    own_graph = graph_client is None
    if own_db:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        db = sessionmaker(bind=create_engine(settings.DATABASE_URL, pool_pre_ping=True))()
    if own_graph:
        try:
            from backend.app.services.graph_client import GraphClient
            graph_client = GraphClient()
        except Exception as exc:
            logger.warning("[insights] graph_client_unavailable err=%s", exc)
            graph_client = None

    try:
        from backend.app.models import GraphCommunity, GraphInsightSummary, KnowledgeEntity
        from engine.app.retrieval.graph_expand import match_seed_entities

        seeds = match_seed_entities(db, query, limit=settings.GRAPH_INSIGHTS_SEED_ENTITIES)
        if not seeds or graph_client is None:
            return ""

        # communities touched by seeds
        cids: set[int] = set()
        for sid in seeds:
            cid = graph_client.entity_community(sid)
            if cid is not None:
                cids.add(int(cid))
        if not cids:
            return ""

        gc_rows = db.query(GraphCommunity).filter(GraphCommunity.community_id.in_(cids)).all()
        label_by_cid = {gc.community_id: gc.label for gc in gc_rows}

        # surprising endpoints of seeds -> other entities (render names)
        surprising_pairs: list[tuple[str, str]] = []
        for sid in seeds:
            for other in graph_client.surprising_endpoints(sid):
                surprising_pairs.append((sid, other))
        surprising_pairs = surprising_pairs[: settings.GRAPH_INSIGHTS_MAX_SURPRISING]

        # god entities in touched communities (read via Neo4j neighbors of seeds)
        god_ids: list[str] = []
        for sid in seeds:
            god_ids.extend(graph_client.god_neighbors(sid, limit=settings.GRAPH_INSIGHTS_MAX_GOD))
        god_ids = list(dict.fromkeys(god_ids))[: settings.GRAPH_INSIGHTS_MAX_GOD]

        # global suggested questions (top-N)
        summ = db.query(GraphInsightSummary).filter_by(user_id=user_id).one_or_none()
        questions = (summ.suggested_questions if summ else [])[: settings.GRAPH_INSIGHTS_MAX_QUESTIONS]

        # resolve names
        name_ids = set(seeds) | {o for _, o in surprising_pairs} | set(god_ids)
        name_map = {e.id: e.canonical_name for e in db.query(KnowledgeEntity).filter(KnowledgeEntity.id.in_(name_ids)).all()}

        lines = ["【图谱洞察】"]
        for a, b in surprising_pairs:
            lines.append(f"- 隐藏联系：{name_map.get(a, a)} 与 {name_map.get(b, b)} 存在跨主题关联")
        if god_ids:
            lines.append("- 枢纽节点：" + "、".join(name_map.get(g, g) for g in god_ids))
        if cids and any(label_by_cid.get(c) for c in cids):
            lines.append("- 当前主题：" + "、".join(label_by_cid[c] for c in cids if label_by_cid.get(c)))
        if questions:
            lines.append("- 可追问：" + "；".join(q.get("question", "") for q in questions))
        if len(lines) == 1:
            return ""
        lines.append("回答时可参考这些联系，并在合适时主动提示用户。")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("[insights] graph_insights_context_failed err=%s", exc)
        return ""
    finally:
        if own_db:
            try:
                db.close()
            except Exception:
                pass
        if own_graph and graph_client is not None:
            try:
                graph_client.close()
            except Exception:
                pass
