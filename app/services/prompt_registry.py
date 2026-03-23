"""Versioned prompt registry.

Prompts are stored as plain-text files under ``prompts/<category>/vX.Y.Z.txt``.
Active versions are configurable via environment variables:
  PROMPT_EXTRACTION_VERSION, PROMPT_CLASSIFICATION_VERSION, PROMPT_SEARCH_VERSION
"""
from __future__ import annotations

import difflib
import os
import re
from pathlib import Path
from typing import Literal

PromptCategory = Literal["extraction", "classification", "search"]

_SEMVER_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

_ENV_VAR_MAP: dict[str, str] = {
    "extraction": "PROMPT_EXTRACTION_VERSION",
    "classification": "PROMPT_CLASSIFICATION_VERSION",
    "search": "PROMPT_SEARCH_VERSION",
}


def _parse_semver(tag: str) -> tuple[int, int, int]:
    """Parse 'vX.Y.Z' into (X, Y, Z) ints. Raises ValueError on bad input."""
    m = _SEMVER_RE.match(tag)
    if not m:
        raise ValueError(f"Invalid semver tag: {tag!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


class PromptRegistry:
    """Manages versioned prompts stored in the prompts/ directory.

    Prompts are stored as plain text files with semantic versioning.
    Active versions are configurable via environment variables.
    Supports loading by exact version or 'latest'.
    """

    def __init__(self, prompts_dir: Path | None = None) -> None:
        self._dir = prompts_dir or Path(__file__).parent.parent.parent / "prompts"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_prompt(self, category: PromptCategory, version: str = "latest") -> str:
        """Load a prompt by category and version.

        'latest' returns the file with the highest semver tag.

        Raises FileNotFoundError if the requested version does not exist or
        the category directory is empty.
        """
        resolved = self._resolve_version(category, version)
        path = self._dir / category / f"{resolved}.txt"
        if not path.exists():
            raise FileNotFoundError(
                f"Prompt file not found: {path} "
                f"(category={category!r}, version={version!r})"
            )
        return path.read_text(encoding="utf-8")

    def list_versions(self, category: PromptCategory) -> list[str]:
        """List all available versions for a category, sorted descending."""
        cat_dir = self._dir / category
        if not cat_dir.is_dir():
            return []
        versions: list[tuple[tuple[int, int, int], str]] = []
        for f in cat_dir.iterdir():
            if f.suffix == ".txt" and _SEMVER_RE.match(f.stem):
                try:
                    key = _parse_semver(f.stem)
                    versions.append((key, f.stem))
                except ValueError:
                    continue
        versions.sort(key=lambda x: x[0], reverse=True)
        return [v for _, v in versions]

    def get_active_version(self, category: PromptCategory) -> str:
        """Get active version from env var PROMPT_{CATEGORY}_VERSION or 'latest'."""
        env_var = _ENV_VAR_MAP.get(category, f"PROMPT_{category.upper()}_VERSION")
        return os.environ.get(env_var, "latest")

    def get_changelog(self) -> str:
        """Read CHANGELOG.md from the prompts directory."""
        changelog = self._dir / "CHANGELOG.md"
        if not changelog.exists():
            return ""
        return changelog.read_text(encoding="utf-8")

    def compare_versions(
        self, category: PromptCategory, v1: str, v2: str
    ) -> dict:
        """Return diff metadata between two prompt versions.

        Returns:
            {
                "added_lines": int,
                "removed_lines": int,
                "changed_sections": list[str],
            }
        """
        text_a = self.get_prompt(category, v1)
        text_b = self.get_prompt(category, v2)

        lines_a = text_a.splitlines(keepends=True)
        lines_b = text_b.splitlines(keepends=True)

        added = 0
        removed = 0
        changed_sections: list[str] = []

        opcodes = difflib.SequenceMatcher(None, lines_a, lines_b).get_opcodes()
        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "insert":
                added += j2 - j1
            elif tag == "delete":
                removed += i2 - i1
            elif tag == "replace":
                removed += i2 - i1
                added += j2 - j1
                # Collect leading non-whitespace tokens from changed lines as labels
                for line in lines_a[i1:i2]:
                    stripped = line.strip()
                    if stripped and stripped not in changed_sections:
                        changed_sections.append(stripped[:60])

        return {
            "added_lines": added,
            "removed_lines": removed,
            "changed_sections": changed_sections,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_version(self, category: PromptCategory, version: str) -> str:
        """Resolve 'latest' to the highest semver; otherwise return as-is."""
        if version != "latest":
            return version
        available = self.list_versions(category)
        if not available:
            raise FileNotFoundError(
                f"No prompt versions found for category {category!r} "
                f"in {self._dir / category}"
            )
        return available[0]  # already sorted descending
