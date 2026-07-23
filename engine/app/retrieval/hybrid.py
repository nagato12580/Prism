"""Pure rank-fusion helpers for retrieval orchestrators."""

from .contracts import ChannelResult

RRF_K = 60
VECTOR_WEIGHT = 0.6
BM25_WEIGHT = 0.4
GRAPH_WEIGHT = 0.5


def weighted_rrf(
    results: list[ChannelResult], weights: dict[str, float], k: int = RRF_K
) -> list[dict]:
    """Fuse precomputed channel results without performing any retrieval."""
    healthy = [result for result in results if result.health != "failed"]
    active = {
        result.channel: weights[result.channel]
        for result in healthy
        if result.channel in weights
    }
    total = sum(active.values()) or 1.0
    normalized = {name: value / total for name, value in active.items()}

    merged: dict[str, dict] = {}
    for result in healthy:
        weight = normalized.get(result.channel, 0.0)
        for candidate in result.candidates:
            row = merged.setdefault(
                candidate.chunk_uid,
                {
                    "chunk_uid": candidate.chunk_uid,
                    "item_id": candidate.item_id,
                    "file_uid": candidate.file_uid,
                    "rrf_score": 0.0,
                    "channels": {},
                    "metadata": {},
                },
            )
            row["rrf_score"] += weight / (k + candidate.raw_rank)
            row["channels"][result.channel] = {
                "raw_rank": candidate.raw_rank,
                "raw_score": candidate.raw_score,
            }
            for key, value in candidate.metadata.items():
                if row["metadata"].get(key) in (None, "") and value not in (None, ""):
                    row["metadata"][key] = value
    return sorted(merged.values(), key=lambda row: row["rrf_score"], reverse=True)
