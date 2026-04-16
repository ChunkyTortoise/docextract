"""Push prompt files to Langfuse prompt registry.

Reads each prompt file from prompts/<family>/<version>.txt and creates
a versioned Langfuse prompt entry with the specified label.

Usage:
    python scripts/sync_langfuse.py --dry-run
    python scripts/sync_langfuse.py --family extraction --version 1.1.0 --label production
    python scripts/sync_langfuse.py --all --label production

Environment:
    LANGFUSE_PUBLIC_KEY  — required unless --dry-run
    LANGFUSE_SECRET_KEY  — required unless --dry-run
    LANGFUSE_HOST        — optional, defaults to https://cloud.langfuse.com
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Prompt registry: maps family name to prompt file glob pattern
PROMPT_REGISTRY = {
    "extraction": "prompts/extraction/v{version}.txt",
    "classification": "prompts/classification/v{version}.txt",
    "search": "prompts/search/v{version}.txt",
}

# Default versions to sync when --all is used
DEFAULT_VERSIONS = {
    "extraction": "1.1.0",
    "classification": "1.0.0",
    "search": "1.0.0",
}

REPO_ROOT = Path(__file__).parent.parent


def _resolve_prompt_path(family: str, version: str) -> Path:
    pattern = PROMPT_REGISTRY.get(family)
    if pattern is None:
        raise ValueError(f"Unknown prompt family '{family}'. Known: {list(PROMPT_REGISTRY)}")
    return REPO_ROOT / pattern.format(version=version)


def _push_prompt(
    family: str,
    version: str,
    label: str,
    dry_run: bool,
) -> None:
    prompt_path = _resolve_prompt_path(family, version)

    if not prompt_path.exists():
        print(f"ERROR: Prompt file not found: {prompt_path}", file=sys.stderr)
        sys.exit(1)

    content = prompt_path.read_text(encoding="utf-8")

    # Strip the langfuse frontmatter comment if present (first line starting with "# langfuse:")
    lines = content.splitlines(keepends=True)
    if lines and lines[0].strip().startswith("# langfuse:"):
        content = "".join(lines[1:]).lstrip("\n")

    prompt_name = f"docextract-{family}"
    char_count = len(content)

    if dry_run:
        print(
            f"Would push {prompt_name}@{version} "
            f"({char_count} chars, labels=[{label}])"
        )
        print(f"  Source: {prompt_path.relative_to(REPO_ROOT)}")
        print(f"  Preview: {content[:120].strip()!r}...")
        return

    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        print(
            "ERROR: LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set. "
            "Use --dry-run to preview without credentials.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        from langfuse import Langfuse
    except ImportError:
        print(
            "ERROR: langfuse package not installed. Run: pip install langfuse>=4.2.0",
            file=sys.stderr,
        )
        sys.exit(1)

    client = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=host,
    )

    try:
        client.create_prompt(
            name=prompt_name,
            prompt=content,
            labels=[label],
            config={
                "version": version,
                "model": "claude-sonnet-4-6",
                "source_file": str(prompt_path.relative_to(REPO_ROOT)),
            },
        )
        print(f"Pushed {prompt_name}@{version} → label={label} ({char_count} chars)")
    except Exception as exc:
        exc_type = type(exc).__name__
        if "duplicate" in str(exc).lower() or "already exists" in str(exc).lower():
            print(f"Skipped {prompt_name}@{version} — already exists in Langfuse")
        else:
            print(f"ERROR pushing {prompt_name}@{version}: {exc_type}: {exc}", file=sys.stderr)
            sys.exit(1)
    finally:
        client.flush()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync prompt files to Langfuse prompt registry."
    )
    parser.add_argument(
        "--family",
        choices=list(PROMPT_REGISTRY),
        help="Prompt family to sync (extraction, classification, search).",
    )
    parser.add_argument(
        "--version",
        help="Semantic version string (e.g. 1.1.0). Required with --family.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="sync_all",
        help="Sync all families at their default versions.",
    )
    parser.add_argument(
        "--label",
        default="production",
        help="Langfuse label to apply (default: production).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be pushed without calling Langfuse.",
    )
    args = parser.parse_args()

    if args.sync_all:
        for family, version in DEFAULT_VERSIONS.items():
            _push_prompt(family, version, args.label, args.dry_run)
        return

    if not args.family or not args.version:
        parser.error("--family and --version are required unless --all is specified.")

    _push_prompt(args.family, args.version, args.label, args.dry_run)


if __name__ == "__main__":
    main()
