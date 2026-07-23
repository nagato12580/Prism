from math import log2
from collections.abc import Iterable


def retrieval_metrics(ranked_chunks: Iterable[str], gold_chunks: set[str] | frozenset[str], *, ks=(1, 3, 5, 10)) -> dict[str, float]:
    """Compute binary Recall@K, reciprocal rank and NDCG over unique chunk ids.

    Empty gold sets produce zero metrics. ``ks`` must be non-empty, positive,
    and unique. Duplicate retrieved ids retain only their first rank.
    """
    ks = tuple(ks)
    if not ks or any(not isinstance(k, int) or isinstance(k, bool) or k <= 0 for k in ks) or len(set(ks)) != len(ks):
        raise ValueError("ks must contain unique positive integers")
    ranked = list(dict.fromkeys(chunk for chunk in ranked_chunks if isinstance(chunk, str) and chunk))
    gold = {chunk for chunk in gold_chunks if isinstance(chunk, str) and chunk}
    result = {f"recall@{k}": (len(gold.intersection(ranked[:k])) / len(gold) if gold else 0.0) for k in ks}
    relevant_ranks = [rank for rank, chunk in enumerate(ranked, 1) if chunk in gold]
    result["mrr"] = 1.0 / relevant_ranks[0] if relevant_ranks else 0.0
    dcg = sum(1.0 / log2(rank + 1) for rank in relevant_ranks)
    ideal = sum(1.0 / log2(rank + 1) for rank in range(1, min(len(gold), len(ranked)) + 1))
    result["ndcg"] = dcg / ideal if ideal else 0.0
    return result
