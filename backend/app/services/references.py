"""
Customer reference uploads for the agent builder: PDF, DOCX and TXT files (sent
base64-encoded) or pasted text, reduced to plain text. Content is untrusted data:
it's only ever shown to the generator inside <customer_reference> tags.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
import zipfile

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 60000
KINDS = ("pdf", "docx", "txt")


class ReferenceError(ValueError):
    pass


def _clean(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_TEXT_CHARS]


def _docx_text(raw: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
    except (zipfile.BadZipFile, KeyError):
        raise ReferenceError("That Word file couldn't be read. Save it as .docx and try again.")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    xml = re.sub(r"<w:br/>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    for ent, ch in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
        text = text.replace(ent, ch)
    return text


def _pdf_text(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - dependency is in requirements.txt
        raise ReferenceError("PDF reading isn't available right now. Paste the text instead.")
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise ReferenceError("That PDF is password-protected. Remove the password or paste the text instead.")
        return "\n\n".join((page.extract_text() or "") for page in reader.pages[:60])
    except ReferenceError:
        raise
    except Exception:
        raise ReferenceError("That PDF couldn't be read. Paste the text instead.")


def extract(filename: str, content_b64: str) -> tuple[str, str]:
    """(kind, text) from an uploaded file. Raises ReferenceError with a plain message."""
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext not in KINDS:
        raise ReferenceError("Upload a PDF, Word (.docx) or text (.txt) file.")
    try:
        raw = base64.b64decode(content_b64, validate=True)
    except (binascii.Error, ValueError):
        raise ReferenceError("The file didn't upload correctly. Please try again.")
    if len(raw) > MAX_FILE_BYTES:
        raise ReferenceError("That file is over 5 MB. Upload a smaller file or paste the relevant part.")
    if ext == "pdf":
        text = _pdf_text(raw)
    elif ext == "docx":
        text = _docx_text(raw)
    else:
        text = raw.decode("utf-8", "ignore")
    text = _clean(text)
    if len(text) < 20:
        raise ReferenceError("We couldn't find readable text in that file. If it's a scanned document, paste the text instead.")
    return ext, text


def clean_pasted(text: str) -> str:
    text = _clean(text or "")
    if len(text) < 20:
        raise ReferenceError("Paste at least a few sentences.")
    return text
