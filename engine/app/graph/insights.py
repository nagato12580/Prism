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
