"""Parser decoded-resource budgets (lane B B8).

Acceptance: oversized dimensions, malformed PDFs, and attachment-heavy inputs
fail within explicit memory/time budgets — checked before allocation wherever
the header or geometry makes it possible.
"""
from __future__ import annotations

import struct

import pytest

from app.services.email_extractor import extract_eml
from app.services.preprocessor import ParserBudgetError, image_size_from_header, preprocess_bytes


def _png_header(width: int, height: int) -> bytes:
    ihdr = b"IHDR" + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + ihdr


class TestImagePixelBudget:
    def test_header_dimensions_read_without_decoding(self):
        assert image_size_from_header(_png_header(800, 600)) == (800, 600)

    def test_oversized_declared_dimensions_fail_before_decode(self):
        # 50000x50000 = 2.5G pixels: rejected from the header alone, before
        # cv2.imdecode ever allocates.
        with pytest.raises(ParserBudgetError, match="decoded-pixel budget"):
            preprocess_bytes(_png_header(50_000, 50_000), max_pixels=1_000_000)

    def test_top_level_image_route_enforces_pixel_budget(self, monkeypatch):
        from app.config import settings
        from app.services.ingestion import ingest

        monkeypatch.setattr(settings, "ocr_engine", "tesseract")
        monkeypatch.setattr(settings, "vision_extraction_enabled", False)
        with pytest.raises(ParserBudgetError, match="decoded-pixel budget"):
            ingest(_png_header(50_000, 50_000), "image/png", "big.png")


class TestPdfRenderBudget:
    def test_oversized_scanned_page_fails_before_render(self, monkeypatch):
        import app.services.pdf_extractor as pdf_extractor

        class _FakeRect:
            width = 20_000.0
            height = 20_000.0

        class _FakePage:
            rect = _FakeRect()

            def get_text(self, kind):
                return []

            def get_pixmap(self, dpi=None):
                raise AssertionError("budget check must run before rendering")

        class _FakeDoc:
            is_encrypted = False
            page_count = 1

            def __getitem__(self, i):
                return _FakePage()

            def close(self):
                pass

        monkeypatch.setattr(pdf_extractor.fitz, "open", lambda **kwargs: _FakeDoc())

        with pytest.raises(ParserBudgetError, match="render budget exceeded"):
            pdf_extractor.extract_pdf(b"%PDF-1.4 fake")

    def test_malformed_pdf_still_fails_explicitly(self, monkeypatch):
        import app.services.pdf_extractor as pdf_extractor

        def _broken(**kwargs):
            raise RuntimeError("broken")

        monkeypatch.setattr(pdf_extractor.fitz, "open", _broken)

        with pytest.raises(ValueError, match="Corrupt or unreadable PDF"):
            pdf_extractor.extract_pdf(b"%PDF-1.4 broken")


class TestEmailAttachmentBudget:
    def _eml(self, attachment_sizes: list[int]) -> bytes:
        import email.message

        msg = email.message.EmailMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "rcpt@example.com"
        msg["Subject"] = "invoices"
        msg.set_content("see attachments")
        for i, size in enumerate(attachment_sizes):
            msg.add_attachment(
                b"x" * size,
                maintype="application",
                subtype="pdf",
                filename=f"att_{i}.pdf",
            )
        return msg.as_bytes()

    def test_attachment_heavy_input_fails_on_shared_budget(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "parser_attachment_budget_bytes", 100)
        with pytest.raises(ParserBudgetError, match="budget exceeded"):
            extract_eml(self._eml([60, 60]))

    def test_single_oversized_attachment_fails(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "parser_max_attachment_bytes", 10)
        with pytest.raises(ParserBudgetError, match="per-attachment decoded budget"):
            extract_eml(self._eml([60]))

    def test_small_attachments_pass_the_budget(self):
        content = extract_eml(self._eml([10, 10]))
        assert "see attachments" in content.text
