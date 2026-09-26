#!/usr/bin/env python3
"""Offline retrieval eval: recall@k and MRR over a synthetic labeled corpus, no API key.

Scope: this exercises the BM25 lexical search primitive
(`app/services/bm25.py`) against a small in-script synthetic corpus with
explicit query-to-relevant-document labels. It does NOT measure the pgvector
embedding path, hybrid RRF ranking, agentic RAG loop quality, or live-model
retrieval, and it is not the extraction replay population. Metrics reported
here are offline/synthetic only.

Fails (exit 1) if:
  - fewer than --min-queries labeled queries are present (corpus must not shrink)
  - recall@k falls below --floor

Run:  .venv/bin/python scripts/eval_offline_retrieval.py --floor 0.75
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.services.bm25 import build_index, search_bm25  # noqa: E402

# Synthetic corpus: 8 single-topic documents with generic content. Labels are
# explicit: each query has exactly one relevant document id. All content is
# synthetic fixture data written for this eval, not measured production output.
CORPUS: dict[str, str] = {
    "doc-001": (
        "Invoice 2024-0412 from Meridian Office Supplies. Total amount due "
        "$1,240.00, payment terms net 30, due date April 12. Line items include "
        "copy paper, toner cartridges, and desk organizers. Vendor tax ID "
        "listed on the header."
    ),
    "doc-002": (
        "Point-of-sale receipt for grocery purchase. Card ending 4021 paid "
        "$86.53 with tax included. Register 4, cashier on duty, transaction "
        "approved with contactless tap. Return window is 14 days."
    ),
    "doc-003": (
        "Bank statement for checking account statement period ending June 30. "
        "Opening balance $4,210.18, closing balance $3,877.42 after direct "
        "deposit and automatic withdrawals. Service fee of $12.00 applied "
        "mid-month."
    ),
    "doc-004": (
        "Medical record summary from a routine annual physical examination. "
        "Patient blood pressure 118 over 76, resting heart rate 62. Physician "
        "noted normal lab panel and recommended follow-up in twelve months. "
        "Diagnosis code Z00.00 recorded."
    ),
    "doc-005": (
        "Purchase order PO-88231 issued to Cascade Furniture for conference "
        "room seating. Quantity twelve ergonomic chairs, unit price $310.00, "
        "authorized by the operations director. Delivery expected within "
        "three weeks of approval."
    ),
    "doc-006": (
        "Identity document extract from a driver license scan. License number "
        "redacted, class C, expiration date August 14. Address on file matches "
        "the voter registration roll. Organ donor indicator marked yes."
    ),
    "doc-007": (
        "Residential lease agreement for a two-bedroom apartment. Monthly "
        "rent $2,150.00, security deposit equal to one month, lease term "
        "twelve months starting September 1. Pets allowed with an additional "
        "deposit. Landlord contact on the signature page."
    ),
    "doc-008": (
        "Tax form W-2 wage and tax statement for the calendar year. Box 1 "
        "wages $78,400.00, federal income tax withheld $9,120.00, Social "
        "Security wages capped at the annual limit. Employer identification "
        "number in box b."
    ),
}

QUERIES: dict[str, str] = {
    "q-001": "what is the total amount due on the invoice",
    "q-002": "how much did the card payment charge",
    "q-003": "closing balance on the checking statement",
    "q-004": "blood pressure reading from the physical exam",
    "q-005": "which purchase order covers conference chairs",
    "q-006": "driver license expiration date",
    "q-007": "monthly rent and security deposit in the lease",
    "q-008": "federal income tax withheld on the W-2",
}

LABELS: dict[str, str] = {qid: doc_id for qid, doc_id in zip(QUERIES, CORPUS)}


def recall_at_k(ranks: dict[str, int | None], k: int) -> float:
    """Fraction of queries whose relevant document appears in the top k."""
    if not ranks:
        return 0.0
    hits = sum(1 for r in ranks.values() if r is not None and r <= k)
    return hits / len(ranks)


def mrr(ranks: dict[str, int | None]) -> float:
    """Mean reciprocal rank over the labeled queries (0 for misses)."""
    if not ranks:
        return 0.0
    return sum(1.0 / r for r in ranks.values() if r is not None) / len(ranks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--floor", type=float, default=0.75, help="Minimum recall@k to pass")
    parser.add_argument("-k", "--top-k", type=int, default=3, help="Rank cutoff for recall")
    parser.add_argument("--min-queries", type=int, default=8, help="Minimum labeled queries")
    args = parser.parse_args()

    if len(QUERIES) < args.min_queries:
        print(f"FAIL: only {len(QUERIES)} labeled queries present, need {args.min_queries}")
        return 1

    doc_ids = list(CORPUS)
    index = build_index([CORPUS[d] for d in doc_ids])

    ranks: dict[str, int | None] = {}
    for qid, query in QUERIES.items():
        hits = search_bm25(query, index, doc_ids, limit=len(doc_ids))
        relevant = LABELS[qid]
        rank = next((i + 1 for i, (rid, _) in enumerate(hits) if rid == relevant), None)
        ranks[qid] = rank

    recall = recall_at_k(ranks, args.top_k)
    reciprocal = mrr(ranks)

    print("Offline retrieval eval (synthetic corpus, BM25 lexical primitive)")
    print(f"  queries: {len(QUERIES)} labeled / corpus: {len(CORPUS)} docs")
    print(f"  recall@{args.top_k}: {recall:.4f} (floor {args.floor})")
    print(f"  MRR: {reciprocal:.4f}")
    for qid, rank in sorted(ranks.items()):
        mark = f"rank {rank}" if rank else "MISS"
        print(f"  {qid}: {mark} -> {LABELS[qid]}")
    print("  Scope: offline/synthetic only; not pgvector, hybrid, agentic, or live retrieval")

    if recall < args.floor:
        print(f"FAIL: recall@{args.top_k} {recall:.4f} below floor {args.floor}")
        return 1
    print(f"PASS: recall@{args.top_k} {recall:.4f} at or above floor {args.floor}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
