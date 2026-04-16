#!/usr/bin/env python3
"""
Post an eval-gate failure summary to Slack via incoming webhook.

Usage:
  python scripts/notify_slack.py \
    --webhook  "$SLACK_WEBHOOK_URL" \
    --author   "cayman" \
    --pr       "https://github.com/..." \
    --scores   eval_artifacts/scores.json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path


def post_webhook(url: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            print(f"Slack webhook returned {resp.status}", file=sys.stderr)
            sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--webhook", required=True)
    parser.add_argument("--author", default="unknown")
    parser.add_argument("--pr", default="")
    parser.add_argument("--scores", type=Path, default=Path("eval_artifacts/scores.json"))
    args = parser.parse_args()

    if not args.webhook or args.webhook.startswith("$"):
        print("No Slack webhook configured — skipping notification", file=sys.stderr)
        sys.exit(0)

    scores: dict = {}
    if args.scores.exists():
        try:
            scores = json.loads(args.scores.read_text())
        except json.JSONDecodeError:
            pass

    metric_lines = "\n".join(
        f"  • {k}: {v:.4f}" if isinstance(v, float) else f"  • {k}: {v}"
        for k, v in scores.items()
        if k not in ("timestamp", "mode") and isinstance(v, (int, float))
    )

    text = (
        f":x: *Eval gate failed* — PR by @{args.author}\n"
        f"<{args.pr}|View PR>\n"
        f"*Scores:*\n{metric_lines or '  (no scores available)'}"
    )

    post_webhook(args.webhook, {"text": text})
    print("Slack notification sent")


if __name__ == "__main__":
    main()
