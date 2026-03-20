"""Tests for prompt_config loader."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.services.prompt_config import (
    PromptConfig,
    PromptParams,
    load_prompt_config,
)


class TestPromptParamsDefaults:
    def test_default_values(self):
        p = PromptParams()
        assert p.max_chunk_tokens == 4000
        assert p.overlap_chars == 200
        assert p.extract_text_limit == 8000
        assert p.correction_text_limit == 3000
        assert p.classify_text_limit == 2000
        assert p.extraction_confidence_threshold == 0.8
        assert p.classification_confidence_threshold == 0.6


class TestPromptConfigDefaults:
    def test_default_prompts_are_non_empty(self):
        cfg = PromptConfig()
        assert "extraction specialist" in cfg.extract_system_prompt
        assert "{doc_type}" in cfg.extract_prompt
        assert "{text}" in cfg.extract_prompt
        assert "{text}" in cfg.classify_prompt
        assert "{doc_type}" in cfg.correction_prompt
        assert "{confidence" in cfg.correction_prompt
        assert "{extraction_json}" in cfg.correction_prompt

    def test_default_params(self):
        cfg = PromptConfig()
        assert cfg.params.max_chunk_tokens == 4000


class TestLoadPromptConfigMissingFile:
    def test_missing_yaml_returns_defaults(self, tmp_path):
        missing = tmp_path / "nonexistent.yaml"
        cfg = load_prompt_config(path=missing)
        assert isinstance(cfg, PromptConfig)
        assert cfg.params.max_chunk_tokens == 4000
        assert "extraction specialist" in cfg.extract_system_prompt

    def test_missing_yaml_params_are_defaults(self, tmp_path):
        missing = tmp_path / "nonexistent.yaml"
        cfg = load_prompt_config(path=missing)
        assert cfg.params.overlap_chars == 200


class TestLoadPromptConfigFromYaml:
    def test_loads_params(self, tmp_path):
        yaml_file = tmp_path / "prompts.yaml"
        yaml_file.write_text(textwrap.dedent("""\
            params:
              max_chunk_tokens: 2000
              overlap_chars: 100
              extract_text_limit: 4000
              correction_text_limit: 1500
              classify_text_limit: 1000
              extraction_confidence_threshold: 0.7
              classification_confidence_threshold: 0.5
        """))
        cfg = load_prompt_config(path=yaml_file)
        assert cfg.params.max_chunk_tokens == 2000
        assert cfg.params.overlap_chars == 100
        assert cfg.params.extract_text_limit == 4000
        assert cfg.params.correction_text_limit == 1500
        assert cfg.params.classify_text_limit == 1000
        assert cfg.params.extraction_confidence_threshold == 0.7
        assert cfg.params.classification_confidence_threshold == 0.5

    def test_loads_custom_prompt(self, tmp_path):
        yaml_file = tmp_path / "prompts.yaml"
        yaml_file.write_text(textwrap.dedent("""\
            extract_system_prompt: "Custom system prompt."
        """))
        cfg = load_prompt_config(path=yaml_file)
        assert cfg.extract_system_prompt == "Custom system prompt."

    def test_missing_keys_fall_back_to_defaults(self, tmp_path):
        yaml_file = tmp_path / "prompts.yaml"
        yaml_file.write_text("params:\n  max_chunk_tokens: 999\n")
        cfg = load_prompt_config(path=yaml_file)
        assert cfg.params.max_chunk_tokens == 999
        # Other params fall back to defaults
        assert cfg.params.overlap_chars == 200
        # Prompts fall back to defaults
        assert "extraction specialist" in cfg.extract_system_prompt

    def test_invalid_yaml_returns_defaults(self, tmp_path):
        yaml_file = tmp_path / "prompts.yaml"
        yaml_file.write_text(": this is not: valid: yaml: {{{{")
        cfg = load_prompt_config(path=yaml_file)
        assert isinstance(cfg, PromptConfig)
        assert cfg.params.max_chunk_tokens == 4000

    def test_empty_yaml_returns_defaults(self, tmp_path):
        yaml_file = tmp_path / "prompts.yaml"
        yaml_file.write_text("")
        cfg = load_prompt_config(path=yaml_file)
        assert isinstance(cfg, PromptConfig)
        assert cfg.params.max_chunk_tokens == 4000


class TestLoadPromptConfigFromActualYaml:
    """Verify the bundled prompts.yaml parses correctly."""

    def test_bundled_yaml_loads(self):
        bundled = Path(__file__).parent.parent.parent / "autoresearch" / "prompts.yaml"
        if not bundled.exists():
            pytest.skip("autoresearch/prompts.yaml not found")
        cfg = load_prompt_config(path=bundled)
        assert cfg.params.max_chunk_tokens == 4000
        assert "{doc_type}" in cfg.extract_prompt
        assert "{text}" in cfg.classify_prompt

    def test_bundled_correction_prompt_formattable(self):
        bundled = Path(__file__).parent.parent.parent / "autoresearch" / "prompts.yaml"
        if not bundled.exists():
            pytest.skip("autoresearch/prompts.yaml not found")
        cfg = load_prompt_config(path=bundled)
        rendered = cfg.correction_prompt.format(
            doc_type="invoice",
            confidence=0.75,
            text_limit=3000,
            text="sample text",
            extraction_json='{"key": "value"}',
        )
        assert "invoice" in rendered
        assert "0.75" in rendered
        assert "sample text" in rendered
