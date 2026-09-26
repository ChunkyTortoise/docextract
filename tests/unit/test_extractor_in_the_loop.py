"""Extractor-in-the-loop: recorded raw responses through the real extract() path.

The offline replay gate scores frozen parsed fixtures without ever calling the
extractor, so a parser or prompt-assembly regression could pass it silently
(lane A finding 1). This module replays the recorded raw Anthropic responses in
`autoresearch/golden_responses/` through the real extract() parsing and
correction path with the client stubbed — deterministic, zero network, zero API
cost.

Acceptance (lane A P1): a deliberate break in `_parse_json_response` makes
these tests fail.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO / "autoresearch" / "golden_responses"
DATASET = REPO / "autoresearch" / "eval_dataset_72.json"


@pytest.fixture(autouse=True)
def _bypass_instructor(monkeypatch):
    """Let stubbed clients pass through instructor.from_anthropic unchanged."""
    import instructor as _instructor

    monkeypatch.setattr(_instructor, "from_anthropic", lambda client, **kw: client)


def _make_text_block(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _make_response(content_blocks: list) -> MagicMock:
    response = MagicMock()
    response.content = content_blocks
    return response


def _replay_cases() -> list[dict]:
    dataset = {c["id"]: c for c in json.loads(DATASET.read_text())}
    cases: list[dict] = []
    for fx in sorted(FIXTURE_DIR.glob("*.json")):
        fixture = json.loads(fx.read_text())
        case = dataset.get(fixture.get("case_id", ""))
        if case is None or not fixture.get("raw_response"):
            continue
        cases.append({"case": case, "fixture": fixture})
    return cases


REPLAY_CASES = _replay_cases()


def test_replay_covers_committed_fixtures():
    """The loop must cover the committed fixture set — never silently degrade."""
    assert len(REPLAY_CASES) >= 28


@pytest.mark.parametrize("ctx", REPLAY_CASES, ids=lambda ctx: ctx["case"]["id"])
class TestExtractorInTheLoop:
    @patch("app.services.claude_extractor.AsyncAnthropic")
    async def test_recorded_raw_response_reproduces_parsed_extraction(
        self, mock_cls, ctx
    ):
        """The real parse+correction path must reproduce the recorded parse.

        A regression in _parse_json_response (or in the prompt assembly that
        feeds it) changes the parsed output and fails this test: the offline
        gate must not outlive the extractor it certifies.
        """
        from app.services.claude_extractor import extract

        client = MagicMock()
        mock_cls.return_value = client
        recorded_calls: list[dict] = []
        raw_response = ctx["fixture"]["raw_response"]
        expected = {
            k: v
            for k, v in (ctx["fixture"]["parsed_extraction"] or {}).items()
            if k != "_confidence"
        }

        async def _create(**kwargs):
            recorded_calls.append(kwargs)
            return _make_response([_make_text_block(raw_response)])

        client.messages.create = AsyncMock(side_effect=_create)

        result = await extract(ctx["case"]["input_text"], ctx["case"]["doc_type"])

        assert result.data == expected

        # Prompt-assembly guard: the document must reach the model inside the
        # untrusted-content fence on the first (extraction) call.
        assert recorded_calls
        first_call = recorded_calls[0]
        user_text = "".join(
            block.get("text", "")
            for block in first_call["messages"][0]["content"]
            if isinstance(block, dict)
        )
        assert "<untrusted_document>" in user_text
        assert ctx["case"]["input_text"][:50] in user_text
