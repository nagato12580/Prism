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
