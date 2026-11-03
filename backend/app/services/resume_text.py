"""Turn an uploaded resume file into plain text. PDF, DOCX and TXT are supported.

Only the text is kept; the file itself is never stored. The kind of file is decided from its first bytes, not its name,
so a renamed file cannot sneak through. Every failure raises ResumeFileError with a message that is safe to show.
"""
from __future__ import annotations

import io
import re
import zipfile

MAX_BYTES = 5 * 1024 * 1024        # one resume
MAX_PAGES = 12                      # a resume longer than this is not a resume
MAX_CHARS = 60_000                  # what we keep
MIN_CHARS = 80                      # less than this is a scan or an empty file
MAX_UNZIPPED = 40 * 1024 * 1024     # a .docx is a zip: refuse zip bombs


class ResumeFileError(Exception):
    """`code` is stable for the API and tests; `message` is safe to show the user."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def detect_kind(data: bytes) -> str:
    """'pdf', 'docx' or 'txt'. Raises ResumeFileError for anything else."""
    if b"%PDF" in data[:1024]:
        return "pdf"
    if data[:2] == b"PK":
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile as exc:
            raise ResumeFileError("unreadable", "This file looks damaged and could not be opened.") from exc
        if any(n.startswith("word/") for n in names):
            return "docx"
        raise ResumeFileError("unsupported", "Upload a PDF, a Word (.docx) file or a plain text file.")
    if data[:4] == b"\xd0\xcf\x11\xe0":
        raise ResumeFileError("old_doc", "Old .doc files are not supported. Save the file as .docx or PDF and upload it again.")
    if b"\x00" in data[:4096]:
        raise ResumeFileError("unsupported", "Upload a PDF, a Word (.docx) file or a plain text file.")
    return "txt"


def _clean(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _with_links(text: str, links: list[str]) -> str:
    """Links hide behind words like "LinkedIn", so their targets are added at the end where the reader can see them."""
    seen: list[str] = []
    for url in links:
        url = str(url).strip()
        if url and url not in seen and not url.lower().startswith("mailto:"):
            seen.append(url)
    if not seen:
        return text
    return text + "\n\nLinks in the file:\n" + "\n".join(seen[:20])


def _pdf(data: bytes) -> str:
    import pdfplumber

    parts: list[str] = []
    links: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages[:MAX_PAGES]:
                parts.append(page.extract_text() or "")
                links += [h["uri"] for h in (page.hyperlinks or []) if h.get("uri")]
    except Exception as exc:  # noqa: BLE001  (pdfminer raises a different type for every kind of damage)
        raise ResumeFileError("unreadable", "This PDF could not be opened. It may be damaged or password protected.") from exc
    return _with_links("\n".join(parts), links)


def _docx(data: bytes) -> str:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
                raise ResumeFileError("too_big", "This Word file expands to an unreasonable size.")
        doc = docx.Document(io.BytesIO(data))
        lines: list[str] = []
        for section in doc.sections:  # contact details often sit in the header
            lines += [p.text for p in section.header.paragraphs]
        for child in doc.element.body.iterchildren():  # document order, so two-column table layouts read naturally
            if child.tag.endswith("}p"):
                lines.append(Paragraph(child, doc).text)
            elif child.tag.endswith("}tbl"):
                for row in Table(child, doc).rows:
                    cells, seen = [], set()
                    for cell in row.cells:
                        if id(cell._tc) not in seen:  # a merged cell shows up once per column it spans
                            seen.add(id(cell._tc))
                            cells.append(cell.text.strip())
                    lines.append(" | ".join(c for c in cells if c))
        links = [rel.target_ref for rel in doc.part.rels.values() if rel.reltype.endswith("/hyperlink")]
    except ResumeFileError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ResumeFileError("unreadable", "This Word file could not be opened. It may be damaged.") from exc
    return _with_links("\n".join(lines), links)


def _txt(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("latin-1")
    printable = sum(1 for c in text[:4000] if c.isprintable() or c in "\n\r\t")
    if text[:4000] and printable / len(text[:4000]) < 0.9:
        raise ResumeFileError("unsupported", "Upload a PDF, a Word (.docx) file or a plain text file.")
    return text


def extract_text(data: bytes) -> str:
    """The cleaned text of a resume file. Raises ResumeFileError."""
    if not data:
        raise ResumeFileError("empty", "This file is empty.")
    if len(data) > MAX_BYTES:
        raise ResumeFileError("too_big", f"This file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    kind = detect_kind(data)
    text = _clean({"pdf": _pdf, "docx": _docx, "txt": _txt}[kind](data))
    if len(text) < MIN_CHARS:
        raise ResumeFileError(
            "no_text",
            "Almost no readable text was found. If this is a scanned image, upload a text-based PDF or a Word file instead.",
        )
    return text[:MAX_CHARS]
