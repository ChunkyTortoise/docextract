"""Tests for structured table extraction."""
from __future__ import annotations


class TestTableToStructured:
    def test_converts_table_to_dict(self):
        from app.services.pdf_extractor import _table_to_structured
        table = [
            ["Date", "Description", "Amount"],
            ["2024-01-01", "Widget A", "100.00"],
            ["2024-01-02", "Widget B", "200.00"],
        ]
        result = _table_to_structured(table, page=1)
        assert result is not None
        assert result["headers"] == ["Date", "Description", "Amount"]
        assert len(result["rows"]) == 2
        assert result["rows"][0] == ["2024-01-01", "Widget A", "100.00"]
        assert result["page"] == 1

    def test_returns_none_for_single_row(self):
        from app.services.pdf_extractor import _table_to_structured
        result = _table_to_structured([["Header Only"]], page=1)
        assert result is None

    def test_returns_none_for_empty_table(self):
        from app.services.pdf_extractor import _table_to_structured
        assert _table_to_structured([], page=1) is None

    def test_handles_none_cells(self):
        from app.services.pdf_extractor import _table_to_structured
        table = [
            ["Date", None, "Amount"],
            ["2024-01-01", None, "100.00"],
        ]
        result = _table_to_structured(table, page=2)
        assert result is not None
        assert result["headers"] == ["Date", "", "Amount"]
        assert result["rows"][0] == ["2024-01-01", "", "100.00"]
        assert result["page"] == 2

    def test_returns_none_for_all_empty(self):
        from app.services.pdf_extractor import _table_to_structured
        table = [
            [None, None],
            [None, None],
        ]
        result = _table_to_structured(table, page=1)
        assert result is None


class TestExtractedContentTables:
    def test_extracted_content_has_tables_field(self):
        from app.services.pdf_extractor import ExtractedContent
        content = ExtractedContent(text="hello")
        assert hasattr(content, "tables")
        assert content.tables == []

    def test_extracted_content_tables_default_empty(self):
        from app.services.pdf_extractor import ExtractedContent
        c1 = ExtractedContent(text="a")
        c2 = ExtractedContent(text="b")
        c1.tables.append({"headers": ["x"], "rows": [], "page": 1})
        # default_factory means c2.tables is independent
        assert c2.tables == []
