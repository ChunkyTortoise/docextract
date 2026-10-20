"""Reconstructed documents must faithfully include every stored value and provenance."""
import json
from html.parser import HTMLParser

import pytest

from frontend.comparison_samples import DATA_DIR, LABEL, render_comparison


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def values(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from values(item)
    elif isinstance(value, list):
        for item in value:
            yield from values(item)
    else:
        yield str(value)


@pytest.mark.parametrize("sample", ["invoice", "contract", "receipt"])
def test_comparison_matches_all_fields_and_reproducible_asset(sample):
    html = render_comparison(sample)
    assert (DATA_DIR / "comparison" / f"{sample}.html").read_text() == html
    parser = TextParser()
    parser.feed(html)
    visible = " ".join(parser.parts)
    fixture = json.loads((DATA_DIR / f"{sample}_sample.json").read_text())
    assert LABEL in visible
    assert "not the original processed PDF" in visible
    for value in values(fixture["extracted_data"]):
        assert value in visible
    assert "<script" not in html


def test_invalid_sample_rejected():
    with pytest.raises(ValueError, match="Unknown comparison"):
        render_comparison("../../private")
