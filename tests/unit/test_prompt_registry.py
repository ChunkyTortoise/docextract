"""Unit tests for PromptRegistry — uses tmp_path for full isolation."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.prompt_registry import PromptRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_registry(tmp_path: Path) -> tuple[PromptRegistry, Path]:
    """Return a registry pointed at tmp_path/prompts and the prompts root."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    return PromptRegistry(prompts_dir=prompts_dir), prompts_dir


def _write_prompt(prompts_dir: Path, category: str, version: str, content: str) -> Path:
    cat_dir = prompts_dir / category
    cat_dir.mkdir(parents=True, exist_ok=True)
    p = cat_dir / f"{version}.txt"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# get_prompt tests
# ---------------------------------------------------------------------------


class TestGetPrompt:
    def test_loads_correct_file_content(self, tmp_path: Path) -> None:
        reg, pdir = _make_registry(tmp_path)
        _write_prompt(pdir, "extraction", "v1.0.0", "hello extraction")
        assert reg.get_prompt("extraction", "v1.0.0") == "hello extraction"

    def test_latest_returns_highest_semver(self, tmp_path: Path) -> None:
        reg, pdir = _make_registry(tmp_path)
        _write_prompt(pdir, "extraction", "v1.0.0", "old")
        _write_prompt(pdir, "extraction", "v1.1.0", "new")
        _write_prompt(pdir, "extraction", "v2.0.0", "newest")
        assert reg.get_prompt("extraction", "latest") == "newest"

    def test_exact_version_loads_correct_content(self, tmp_path: Path) -> None:
        reg, pdir = _make_registry(tmp_path)
        _write_prompt(pdir, "classification", "v1.0.0", "classify v1")
        _write_prompt(pdir, "classification", "v1.1.0", "classify v1.1")
        assert reg.get_prompt("classification", "v1.0.0") == "classify v1"

    def test_missing_version_raises_file_not_found(self, tmp_path: Path) -> None:
        reg, pdir = _make_registry(tmp_path)
        _write_prompt(pdir, "extraction", "v1.0.0", "content")
        with pytest.raises(FileNotFoundError):
            reg.get_prompt("extraction", "v9.9.9")

    def test_empty_category_raises_file_not_found(self, tmp_path: Path) -> None:
        reg, pdir = _make_registry(tmp_path)
        (pdir / "extraction").mkdir()  # category dir exists but is empty
        with pytest.raises(FileNotFoundError):
            reg.get_prompt("extraction", "latest")


# ---------------------------------------------------------------------------
# list_versions tests
# ---------------------------------------------------------------------------


class TestListVersions:
    def test_returns_sorted_descending(self, tmp_path: Path) -> None:
        reg, pdir = _make_registry(tmp_path)
        _write_prompt(pdir, "extraction", "v1.0.0", "a")
        _write_prompt(pdir, "extraction", "v2.0.0", "b")
        _write_prompt(pdir, "extraction", "v1.1.0", "c")
        assert reg.list_versions("extraction") == ["v2.0.0", "v1.1.0", "v1.0.0"]

    def test_returns_empty_list_for_missing_category(self, tmp_path: Path) -> None:
        reg, pdir = _make_registry(tmp_path)
        assert reg.list_versions("search") == []

    def test_ignores_non_semver_files(self, tmp_path: Path) -> None:
        reg, pdir = _make_registry(tmp_path)
        cat_dir = pdir / "extraction"
        cat_dir.mkdir()
        (cat_dir / "v1.0.0.txt").write_text("ok")
        (cat_dir / "notes.txt").write_text("not a version")
        (cat_dir / "latest.txt").write_text("also not")
        assert reg.list_versions("extraction") == ["v1.0.0"]


# ---------------------------------------------------------------------------
# get_active_version tests
# ---------------------------------------------------------------------------


class TestGetActiveVersion:
    def test_returns_latest_when_env_not_set(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        reg, _ = _make_registry(tmp_path)
        monkeypatch.delenv("PROMPT_EXTRACTION_VERSION", raising=False)
        assert reg.get_active_version("extraction") == "latest"

    def test_reads_from_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        reg, _ = _make_registry(tmp_path)
        monkeypatch.setenv("PROMPT_EXTRACTION_VERSION", "v1.2.3")
        assert reg.get_active_version("extraction") == "v1.2.3"

    def test_classification_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        reg, _ = _make_registry(tmp_path)
        monkeypatch.setenv("PROMPT_CLASSIFICATION_VERSION", "v2.0.0")
        assert reg.get_active_version("classification") == "v2.0.0"

    def test_search_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        reg, _ = _make_registry(tmp_path)
        monkeypatch.setenv("PROMPT_SEARCH_VERSION", "v3.1.0")
        assert reg.get_active_version("search") == "v3.1.0"


# ---------------------------------------------------------------------------
# compare_versions tests
# ---------------------------------------------------------------------------


class TestCompareVersions:
    def test_returns_diff_metadata_structure(self, tmp_path: Path) -> None:
        reg, pdir = _make_registry(tmp_path)
        _write_prompt(pdir, "extraction", "v1.0.0", "line one\nline two\n")
        _write_prompt(pdir, "extraction", "v1.1.0", "line one\nline two\nnew line\n")
        result = reg.compare_versions("extraction", "v1.0.0", "v1.1.0")
        assert "added_lines" in result
        assert "removed_lines" in result
        assert "changed_sections" in result

    def test_added_lines_counted(self, tmp_path: Path) -> None:
        reg, pdir = _make_registry(tmp_path)
        _write_prompt(pdir, "extraction", "v1.0.0", "line one\n")
        _write_prompt(pdir, "extraction", "v1.1.0", "line one\nextra line\n")
        result = reg.compare_versions("extraction", "v1.0.0", "v1.1.0")
        assert result["added_lines"] == 1
        assert result["removed_lines"] == 0

    def test_identical_prompts_have_no_diff(self, tmp_path: Path) -> None:
        reg, pdir = _make_registry(tmp_path)
        _write_prompt(pdir, "extraction", "v1.0.0", "same content\n")
        _write_prompt(pdir, "extraction", "v1.1.0", "same content\n")
        result = reg.compare_versions("extraction", "v1.0.0", "v1.1.0")
        assert result["added_lines"] == 0
        assert result["removed_lines"] == 0
        assert result["changed_sections"] == []

    def test_changed_sections_captures_removed_lines(self, tmp_path: Path) -> None:
        reg, pdir = _make_registry(tmp_path)
        _write_prompt(pdir, "extraction", "v1.0.0", "old line\n")
        _write_prompt(pdir, "extraction", "v1.1.0", "new line\n")
        result = reg.compare_versions("extraction", "v1.0.0", "v1.1.0")
        # "old line" was removed, should appear in changed_sections
        assert any("old line" in s for s in result["changed_sections"])

    def test_missing_version_raises_file_not_found(self, tmp_path: Path) -> None:
        reg, pdir = _make_registry(tmp_path)
        _write_prompt(pdir, "extraction", "v1.0.0", "content")
        with pytest.raises(FileNotFoundError):
            reg.compare_versions("extraction", "v1.0.0", "v9.0.0")
