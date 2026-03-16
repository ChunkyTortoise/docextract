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


class TestProcessAttachmentImage:
    def test_image_attachment_processed(self) -> None:
        """Image attachments are preprocessed and OCR'd."""
        from app.services.email_extractor import _process_attachment

        with (
            patch("app.services.preprocessor.preprocess_bytes") as mock_preprocess,
            patch("app.services.image_extractor.extract_image") as mock_extract,
            patch("app.config.settings") as mock_settings,
        ):
            mock_preprocess.return_value = "preprocessed-image"
            mock_extract.return_value = MagicMock(text="OCR text from image")
            mock_settings.ocr_engine = "tesseract"

            result = _process_attachment(b"img-bytes", "image/jpeg", "scan.jpg", _depth=0)

        assert result == "OCR text from image"
        mock_preprocess.assert_called_once_with(b"img-bytes")

    def test_attachment_exception_returns_none(self) -> None:
        """Failed attachment processing returns None."""
        from app.services.email_extractor import _process_attachment

        with patch("app.services.pdf_extractor.extract_pdf", side_effect=Exception("corrupt")):
            result = _process_attachment(b"bad-pdf", "application/pdf", "bad.pdf", _depth=0)

        assert result is None

    def test_unknown_mime_returns_none(self) -> None:
        """Unknown MIME types are not processed."""
        from app.services.email_extractor import _process_attachment

        result = _process_attachment(b"data", "text/plain", "file.txt", _depth=0)
        assert result is None


class TestGuesseMimeFromFilename:
    def test_known_extensions(self) -> None:
        from app.services.email_extractor import _guess_mime_from_filename

        assert _guess_mime_from_filename("doc.pdf") == "application/pdf"
        assert _guess_mime_from_filename("photo.jpg") == "image/jpeg"
        assert _guess_mime_from_filename("scan.png") == "image/png"
        assert _guess_mime_from_filename("email.eml") == "message/rfc822"

    def test_txt_extension(self) -> None:
        from app.services.email_extractor import _guess_mime_from_filename

        assert _guess_mime_from_filename("readme.txt") == "text/plain"

    def test_unknown_extension(self) -> None:
        from app.services.email_extractor import _guess_mime_from_filename

        assert _guess_mime_from_filename("data.xyz") is None


class TestExtractMsgFile:
    @pytest.fixture(autouse=True)
    def _inject_extract_msg(self):
        """Inject a mock extract_msg module so extract_msg_file can run."""
        import sys
        import app.services.email_extractor as mod

        mock_module = MagicMock()
        sys.modules["extract_msg"] = mock_module
        mod.extract_msg = mock_module
        original_flag = mod.HAS_EXTRACT_MSG
        mod.HAS_EXTRACT_MSG = True
        self._mock_extract_msg = mock_module
        yield
        mod.HAS_EXTRACT_MSG = original_flag
        if hasattr(mod, "extract_msg"):
            delattr(mod, "extract_msg")
        sys.modules.pop("extract_msg", None)

    def test_extract_msg_basic(self) -> None:
        """MSG extraction parses sender, to, subject, body."""
        mock_msg = MagicMock()
        mock_msg.sender = "sender@test.com"
        mock_msg.to = "recipient@test.com"
        mock_msg.cc = ""
        mock_msg.subject = "Test MSG"
        mock_msg.date = "2026-01-01"
        mock_msg.body = "Message body text"
        mock_msg.attachments = []
        mock_msg.close = MagicMock()
        self._mock_extract_msg.Message.return_value = mock_msg

        result = extract_msg_file(b"fake-msg-data")

        assert "Message body text" in result.text
        assert result.metadata["from"] == "sender@test.com"
        assert result.metadata["subject"] == "Test MSG"

    def test_extract_msg_with_attachments(self) -> None:
        """MSG with attachments processes them."""
        mock_att = MagicMock()
        mock_att.data = b"fake-pdf-data"
        mock_att.longFilename = "report.pdf"
        mock_att.shortFilename = "rep.pdf"

        mock_msg = MagicMock()
        mock_msg.sender = "sender@test.com"
        mock_msg.to = "to@test.com"
        mock_msg.cc = None
        mock_msg.subject = "With attachment"
        mock_msg.date = None
        mock_msg.body = "See attached"
        mock_msg.attachments = [mock_att]
        mock_msg.close = MagicMock()
        self._mock_extract_msg.Message.return_value = mock_msg

        with (
            patch("app.services.email_extractor._process_attachment", return_value="Extracted PDF"),
            patch("app.services.email_extractor._guess_mime_from_filename", return_value="application/pdf"),
        ):
            result = extract_msg_file(b"fake-msg-data")

        assert result.metadata["attachment_count"] == 1
        assert "ATTACHMENT: report.pdf" in result.text

    def test_extract_msg_none_fields(self) -> None:
        """MSG with None fields uses empty strings."""
        mock_msg = MagicMock()
        mock_msg.sender = None
        mock_msg.to = None
        mock_msg.cc = None
        mock_msg.subject = None
        mock_msg.date = None
        mock_msg.body = None
        mock_msg.attachments = None
        mock_msg.close = MagicMock()
        self._mock_extract_msg.Message.return_value = mock_msg

        result = extract_msg_file(b"fake-msg-data")

        assert result.metadata["from"] == ""
        assert result.metadata["to"] == ""
        assert result.metadata["attachment_count"] == 0
