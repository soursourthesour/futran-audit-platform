"""Text the model may read, and the quote check (wave 3 plan, AI rule 2).

PDF text is read page by page with pypdf, so a citation names the printed page. DOCX has no pages until it is laid out,
so its paragraphs are grouped into "pages" of about 3,000 characters, never splitting a paragraph; plain text the same
way by line. A quote counts as found when it appears in the cited document after normalising whitespace, case, and
typographic quotes and dashes.
"""
import re
from io import BytesIO
from pathlib import Path

PAGE_CHARS = 3000
TEXT_TYPES = {".txt", ".md", ".csv"}
_TRANSLATE = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "–": "-", "—": "-", "‑": "-", " ": " ", "­": ""})


def normalise(s: str) -> str:
    return " ".join((s or "").translate(_TRANSLATE).lower().split())


def _chunk(blocks: list[str], sep: str) -> list[dict]:
    pages, cur = [], ""
    for b in (x.strip() for x in blocks):
        if not b:
            continue
        if cur and len(cur) + len(sep) + len(b) > PAGE_CHARS:
            pages.append(cur)
            cur = b
        else:
            cur = f"{cur}{sep}{b}" if cur else b
    if cur:
        pages.append(cur)
    return [{"page": i + 1, "text": t} for i, t in enumerate(pages)]


def _docx_blocks(data: bytes) -> list[str]:
    import docx

    d = docx.Document(BytesIO(data))
    out = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            out.append(" | ".join(dict.fromkeys(c.text.strip() for c in row.cells if c.text.strip())))
    return out


def _xlsx_blocks(data: bytes) -> list[str]:
    from openpyxl import load_workbook

    wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [str(v).strip() for v in row if v not in (None, "")]
            if cells:
                out.append(" | ".join(cells))
    return out


def extract_pages(filename: str, data: bytes) -> tuple[str, list[dict], str | None]:
    """(method, pages, error). Pages are [{"page": n, "text": ...}]; empty when nothing could be read."""
    ext = Path(filename or "").suffix.lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(data))
            pages = [{"page": i + 1, "text": (p.extract_text() or "").strip()} for i, p in enumerate(reader.pages)]
        except Exception:  # noqa: BLE001 - a damaged or encrypted PDF
            return "pdf", [], "The text of this PDF could not be read."
        pages = [p for p in pages if p["text"]]
        return "pdf", pages, None if pages else "This PDF has no text layer (it may be a scan)."
    if ext == ".docx":
        try:
            return "docx", _chunk(_docx_blocks(data), "\n"), None
        except Exception:  # noqa: BLE001
            return "docx", [], "The text of this Word document could not be read."
    if ext == ".xlsx":
        try:
            return "xlsx", _chunk(_xlsx_blocks(data), "\n"), None
        except Exception:  # noqa: BLE001
            return "xlsx", [], "The text of this spreadsheet could not be read."
    if ext in TEXT_TYPES:
        text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
        return "text", _chunk(text.split("\n"), "\n"), None
    return "none", [], "Text can't be read from this file type."


def find_quote(pages: list[dict], quote: str, page_hint: int | None = None) -> int | None:
    """The page the quote is on (the cited page first), or None when the document does not contain it."""
    q = normalise(quote)
    if len(q) < 3:
        return None
    ordered = sorted(pages, key=lambda p: p["page"] != page_hint)
    for p in ordered:
        if q in normalise(p["text"]):
            return p["page"]
    return None


def quote_in(text: str, quote: str) -> bool:
    q = normalise(quote)
    return len(q) >= 3 and q in normalise(text)


def sentences(text: str) -> list[str]:
    """Sentence-like pieces of a page, for the fake model and for short excerpts. A line break inside a paragraph (a PDF
    wraps long lines) is a space; one after a short line with no closing punctuation (a heading) ends the piece."""
    lines = [ln.strip() for ln in (text or "").splitlines()]
    blocks, cur = [], []
    for ln in lines:
        if not ln:
            if cur:
                blocks.append(" ".join(cur))
                cur = []
            continue
        cur.append(ln)
        if ln.endswith((".", "!", "?", ":")) and len(ln) < 60 or (len(ln) < 60 and not ln.endswith((",", ";", "-", "and", "or", "the", "of"))):
            blocks.append(" ".join(cur))
            cur = []
    if cur:
        blocks.append(" ".join(cur))
    out = []
    for b in blocks:
        out += [" ".join(p.split()) for p in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\"“])", b)]
    return [p for p in out if len(p.split()) >= 3]
