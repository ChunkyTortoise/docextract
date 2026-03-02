"""Tests for email extractor with sample EML data."""
from unittest.mock import patch, MagicMock

import pytest

from app.services.email_extractor import extract_eml, extract_msg_file, strip_html
from app.services.pdf_extractor import ExtractedContent


def _make_eml(
    body: str = "Hello from email",
    subject: str = "Test Subject",
    from_addr: str = "sender@example.com",
    to_addr: str = "recipient@example.com",
    html: bool = False,
    attachment: bytes | None = None,
    attachment_name: str = "doc.pdf",
    attachment_mime: str = "application/pdf",
) -> bytes:
    """Create a minimal EML message."""
    import email.mime.multipart
    import email.mime.text
    import email.mime.base

    if attachment is not None or html:
        msg = email.mime.multipart.MIMEMultipart()
    else:
        msg = email.mime.text.MIMEText(body)

    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = "Mon, 01 Mar 2026 10:00:00 -0800"

    if isinstance(msg, email.mime.multipart.MIMEMultipart):
        if html:
            html_part = email.mime.text.MIMEText(
                f"<html><body><p>{body}</p></body></html>", "html"
            )
            msg.attach(html_part)
        else:
            text_part = email.mime.text.MIMEText(body)
            msg.attach(text_part)

        if attachment is not None:
            att = email.mime.base.MIMEBase(*attachment_mime.split("/"))
            att.set_payload(attachment)
            att.add_header(
                "Content-Disposition", "attachment", filename=attachment_name
            )
            msg.attach(att)

    return msg.as_bytes()


def test_extract_eml_plain_text() -> None:
    """Extract plain text EML body."""
    eml_bytes = _make_eml(body="Invoice attached")
    result = extract_eml(eml_bytes)

    assert isinstance(result, ExtractedContent)
    assert "Invoice attached" in result.text
    assert result.metadata["subject"] == "Test Subject"
    assert result.metadata["from"] == "sender@example.com"
    assert result.metadata["to"] == "recipient@example.com"
    assert result.metadata["attachment_count"] == 0


def test_extract_eml_html_body() -> None:
    """HTML body is stripped to plain text."""
    eml_bytes = _make_eml(body="Bold text here", html=True)
    result = extract_eml(eml_bytes)

    assert "Bold text here" in result.text
    # Should not contain HTML tags
    assert "<html>" not in result.text
    assert "<p>" not in result.text


def test_extract_eml_attachment_count() -> None:
    """Attachment count is tracked in metadata."""
    eml_bytes = _make_eml(
        attachment=b"fake-pdf-content",
        attachment_name="invoice.pdf",
        attachment_mime="application/pdf",
    )
    result = extract_eml(eml_bytes)

    assert result.metadata["attachment_count"] == 1


@patch("app.services.email_extractor._process_attachment")
def test_extract_eml_with_pdf_attachment(mock_process: MagicMock) -> None:
    """PDF attachments are processed recursively."""
    mock_process.return_value = "Extracted PDF text"

    eml_bytes = _make_eml(
        attachment=b"fake-pdf-bytes",
        attachment_name="report.pdf",
        attachment_mime="application/pdf",
    )
    result = extract_eml(eml_bytes)

    assert "ATTACHMENT: report.pdf" in result.text
    assert "Extracted PDF text" in result.text


def test_strip_html_basic() -> None:
    """HTML tags are properly stripped."""
    html = "<html><body><h1>Title</h1><p>Content here</p></body></html>"
    text = strip_html(html)

    assert "Title" in text
    assert "Content here" in text
    assert "<h1>" not in text
    assert "<p>" not in text


def test_strip_html_script_tags() -> None:
    """Script and style tags are excluded."""
    html = "<p>Visible</p><script>alert('xss')</script><style>.red{}</style><p>Also visible</p>"
    text = strip_html(html)

    assert "Visible" in text
    assert "Also visible" in text
    assert "alert" not in text
    assert ".red" not in text


def test_extract_eml_empty_body() -> None:
    """Empty email body doesn't crash."""
    eml_bytes = _make_eml(body="")
    result = extract_eml(eml_bytes)

    assert isinstance(result, ExtractedContent)
    assert result.metadata["subject"] == "Test Subject"


@patch("app.services.email_extractor.HAS_EXTRACT_MSG", False)
def test_extract_msg_not_installed() -> None:
    """Raises RuntimeError when extract-msg is not installed."""
    with pytest.raises(RuntimeError, match="extract-msg"):
        extract_msg_file(b"fake-msg-data")


class TestAttachmentDepthLimit:
    def test_process_attachment_within_depth(self) -> None:
        """Attachments within depth limit are processed normally."""
        from app.services.email_extractor import _process_attachment

        with patch("app.services.pdf_extractor.extract_pdf") as mock_pdf:
            mock_pdf.return_value = MagicMock(text="Extracted PDF")
            result = _process_attachment(b"pdf-bytes", "application/pdf", "doc.pdf", _depth=0)

        assert result == "Extracted PDF"

    def test_process_attachment_at_max_depth_returns_empty(self) -> None:
        """Attachments at depth >= 3 return empty string (no recursion)."""
        from app.services.email_extractor import _process_attachment

        result = _process_attachment(b"pdf-bytes", "application/pdf", "doc.pdf", _depth=3)
        assert result == ""

    def test_process_attachment_beyond_max_depth_returns_empty(self) -> None:
        """Attachments beyond depth 3 return empty string."""
        from app.services.email_extractor import _process_attachment

        result = _process_attachment(b"pdf-bytes", "application/pdf", "doc.pdf", _depth=5)
        assert result == ""

    def test_depth_limit_does_not_block_shallow(self) -> None:
        """Depth 2 (below limit) still processes normally."""
        from app.services.email_extractor import _process_attachment

        with patch("app.services.pdf_extractor.extract_pdf") as mock_pdf:
            mock_pdf.return_value = MagicMock(text="Deep PDF")
            result = _process_attachment(b"pdf-bytes", "application/pdf", "deep.pdf", _depth=2)

        assert result == "Deep PDF"
