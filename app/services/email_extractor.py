"""Email extraction for .eml and .msg files."""
from __future__ import annotations

import email
import email.policy
import logging
from html.parser import HTMLParser
from io import StringIO

from app.services.pdf_extractor import ExtractedContent

try:
    import extract_msg

    HAS_EXTRACT_MSG = True
except ImportError:
    HAS_EXTRACT_MSG = False

logger = logging.getLogger(__name__)

# MIME types for recursive attachment processing
_PDF_MIME = "application/pdf"
_IMAGE_MIMES = {"image/jpeg", "image/png", "image/tiff", "image/bmp", "image/gif", "image/webp"}


class _HTMLStripper(HTMLParser):
    """Simple HTML tag stripper."""

    def __init__(self) -> None:
        super().__init__()
        self._text = StringIO()
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._text.write(data)

    def get_text(self) -> str:
        return self._text.getvalue().strip()


def strip_html(html: str) -> str:
    """Strip HTML tags and return plain text."""
    stripper = _HTMLStripper()
    stripper.feed(html)
    return stripper.get_text()


def extract_eml(data: bytes) -> ExtractedContent:
    """Extract content from an EML file.

    Parses headers, body (prefers text/plain, falls back to text/html with
    tag stripping), and recursively processes PDF/image attachments.

    Args:
        data: Raw EML bytes

    Returns:
        ExtractedContent with email body, attachment text, and metadata
    """
    msg = email.message_from_bytes(data, policy=email.policy.default)

    # Extract headers
    from_addr = str(msg.get("From", ""))
    to_addr = str(msg.get("To", ""))
    cc_addr = str(msg.get("CC", ""))
    subject = str(msg.get("Subject", ""))
    date_str = str(msg.get("Date", ""))

    # Extract body
    body = ""
    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part is not None:
        content = body_part.get_content()
        content_type = body_part.get_content_type()
        if content_type == "text/html":
            body = strip_html(content)
        else:
            body = content if isinstance(content, str) else content.decode("utf-8", errors="replace")

    # Process attachments
    attachment_texts: list[str] = []
    attachment_count = 0
    for part in msg.walk():
        content_disp = part.get_content_disposition()
        if content_disp != "attachment":
            continue

        attachment_count += 1
        filename = part.get_filename() or f"attachment_{attachment_count}"
        mime = part.get_content_type()
        payload = part.get_payload(decode=True)

        if payload is None:
            continue

        extracted = _process_attachment(payload, mime, filename)
        if extracted:
            attachment_texts.append(
                f"\n--- ATTACHMENT: {filename} ---\n{extracted}"
            )

    # Combine
    parts = [body]
    parts.extend(attachment_texts)
    full_text = "\n".join(parts)

    return ExtractedContent(
        text=full_text,
        metadata={
            "from": from_addr,
            "to": to_addr,
            "cc": cc_addr,
            "subject": subject,
            "date": date_str,
            "attachment_count": attachment_count,
        },
        page_count=1,
    )


def extract_msg_file(data: bytes) -> ExtractedContent:
    """Extract content from an Outlook .msg file.

    Args:
        data: Raw MSG bytes

    Returns:
        ExtractedContent with email body, attachment text, and metadata

    Raises:
        RuntimeError: If extract-msg is not installed
    """
    if not HAS_EXTRACT_MSG:
        raise RuntimeError("extract-msg library is required for .msg files")

    import tempfile
    import os

    # extract_msg needs a file path
    with tempfile.NamedTemporaryFile(suffix=".msg", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        msg = extract_msg.Message(tmp_path)

        sender = msg.sender or ""
        to = msg.to or ""
        cc = msg.cc or ""
        subject_val = msg.subject or ""
        date_val = str(msg.date) if msg.date else ""
        body = msg.body or ""

        # Process attachments
        attachment_texts: list[str] = []
        attachment_count = len(msg.attachments) if msg.attachments else 0

        if msg.attachments:
            for att in msg.attachments:
                att_data = att.data
                att_name = att.longFilename or att.shortFilename or "attachment"
                mime = _guess_mime_from_filename(att_name)
                if att_data and mime:
                    extracted = _process_attachment(att_data, mime, att_name)
                    if extracted:
                        attachment_texts.append(
                            f"\n--- ATTACHMENT: {att_name} ---\n{extracted}"
                        )

        msg.close()
    finally:
        os.unlink(tmp_path)

    parts = [body]
    parts.extend(attachment_texts)
    full_text = "\n".join(parts)

    return ExtractedContent(
        text=full_text,
        metadata={
            "from": sender,
            "to": to,
            "cc": cc,
            "subject": subject_val,
            "date": date_val,
            "attachment_count": attachment_count,
        },
        page_count=1,
    )


def _process_attachment(
    payload: bytes, mime: str, filename: str
) -> str | None:
    """Recursively process a PDF or image attachment."""
    try:
        if mime == _PDF_MIME:
            from app.services.pdf_extractor import extract_pdf

            result = extract_pdf(payload)
            return result.text
        elif mime in _IMAGE_MIMES:
            from app.services.preprocessor import preprocess_bytes
            from app.services.image_extractor import extract_image
            from app.config import settings

            image = preprocess_bytes(payload)
            result = extract_image(image, engine=settings.ocr_engine)
            return result.text
    except Exception:
        logger.warning("Failed to process attachment: %s", filename, exc_info=True)
    return None


def _guess_mime_from_filename(filename: str) -> str | None:
    """Guess MIME type from file extension."""
    from app.utils.mime import ALLOWED_MIME_TYPES
    from pathlib import Path

    ext = Path(filename).suffix.lower()
    return ALLOWED_MIME_TYPES.get(ext)
