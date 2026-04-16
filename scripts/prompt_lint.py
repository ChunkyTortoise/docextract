#!/usr/bin/env python3
"""Prompt file linter for pre-commit hook.

Checks staged prompt files for:
  1. Unclosed {{placeholder}} tokens
  2. File size > 8000 characters
  3. CHANGELOG.md updated when any prompt file is staged

Usage (called by pre-commit):
  python scripts/prompt_lint.py prompts/extraction/v1.1.0.txt [...]

Exit code:
  0 — all checks pass
  1 — one or more checks failed (pre-commit blocks commit)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

MAX_CHARS = 8000
PLACEHOLDER_RE = re.compile(r"\{\{[^}]*$", re.MULTILINE)  # {{ without closing }}
REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "prompts" / "CHANGELOG.md"


def _staged_files() -> list[str]:
    """Return list of staged file paths (relative to repo root)."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def lint_file(path: Path) -> list[str]:
    """Return list of error strings for the given prompt file."""
    errors = []
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        return [f"{path}: cannot read file: {e}"]

    if len(content) > MAX_CHARS:
        errors.append(
            f"{path}: file is {len(content)} chars, exceeds limit of {MAX_CHARS}"
        )

    if PLACEHOLDER_RE.search(content):
        errors.append(f"{path}: contains unclosed {{{{placeholder}}}} token")

    return errors


def check_changelog_staged(prompt_files: list[str]) -> list[str]:
    """Return errors if prompt files are staged without updating CHANGELOG.md."""
    if not prompt_files:
        return []
    staged = _staged_files()
    changelog_rel = str(CHANGELOG.relative_to(REPO_ROOT))
    if changelog_rel not in staged:
        return [
            f"Prompt files changed ({', '.join(prompt_files)}) but "
            f"prompts/CHANGELOG.md is not staged. "
            f"Add a CHANGELOG entry describing what changed and why."
        ]
    return []


def main() -> None:
    prompt_files = sys.argv[1:]
    if not prompt_files:
        sys.exit(0)

    errors: list[str] = []

    for filepath in prompt_files:
        path = Path(filepath)
        if path.exists():
            errors.extend(lint_file(path))

    errors.extend(check_changelog_staged(prompt_files))

    if errors:
        print("prompt-lint: FAILED", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        sys.exit(1)

    print(f"prompt-lint: OK ({len(prompt_files)} file(s) checked)")


if __name__ == "__main__":
    main()
