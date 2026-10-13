"""Markdown → PDF with xhtml2pdf. Uses IBM Plex Sans when its TTF files are bundled in app/documents/fonts, else Helvetica."""
from html import escape
from io import BytesIO
from pathlib import Path

from xhtml2pdf import pisa

from app.documents.render import render_markdown

HERE = Path(__file__).parent
FONTS = HERE / "fonts"


def _font_css() -> str:
    regular, bold = FONTS / "IBMPlexSans-Regular.ttf", FONTS / "IBMPlexSans-Bold.ttf"
    if not (regular.exists() and bold.exists()):
        return ""
    return (
        f'@font-face {{ font-family: Plex; src: url("{regular}"); }}\n'
        f'@font-face {{ font-family: Plex; src: url("{bold}"); font-weight: bold; }}\n'
        "body { font-family: Plex; }\n"
    )


def _only_bundled_fonts(uri: str, rel: str) -> str:
    """xhtml2pdf may only load our own font files; any other URI (file, http) resolves to nothing."""
    p = Path(uri)
    return str(p) if p.parent == FONTS and p.suffix == ".ttf" else ""


def to_pdf(md: str, title: str, meta: dict) -> bytes:
    css = (HERE / "styles.css").read_text() + _font_css()
    ref = escape(str(meta.get("audit_ref", "")))
    html = f"""<html><head><meta charset="utf-8"><title>{escape(title)}</title><style>{css}</style></head><body>
<div id="header_content">Futran Solutions · Confidential</div>
<div id="footer_content">{ref} · {escape(title)} · Page <pdf:pagenumber></div>
{render_markdown(md)}
</body></html>"""
    out = BytesIO()
    result = pisa.CreatePDF(html, dest=out, encoding="utf-8", link_callback=_only_bundled_fonts)
    if result.err:
        raise RuntimeError(f"PDF generation failed for {title}")
    return out.getvalue()
