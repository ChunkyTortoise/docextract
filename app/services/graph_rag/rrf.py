"""Reciprocal Rank Fusion helpers for hybrid retrieval."""

from __future__ import annotations


def reciprocal_rank_fusion(
    rank_maps: list[dict[str, int]],
    k: int = 60,
    default_rank: int | None = None,
) -> dict[str, float]:
    """Fuse multiple rank maps via RRF. Higher score is better."""
    if not rank_maps:
        return {}

    all_ids: set[str] = set()
    for ranks in rank_maps:
        all_ids.update(ranks)

    fallback = default_rank if default_rank is not None else len(all_ids)

    scores: dict[str, float] = {}
    for item_id in all_ids:
        total = 0.0
        for ranks in rank_maps:
            rank = ranks.get(item_id, fallback)
            total += 1.0 / (k + rank)
        scores[item_id] = total

    return scores
