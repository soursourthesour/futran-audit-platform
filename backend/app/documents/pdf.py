"""Markdown → PDF with xhtml2pdf.

Text is set in IBM Plex Sans, embedded from app/documents/fonts, with DejaVu Sans for any character Plex lacks. The
standard PDF fonts (Helvetica and the like) are never used: they have no glyphs for ₹, →, ≥ and many other characters,
which then print as boxes or stray symbols.

With meta["cover"], the document is a report: the text before the first page break becomes a cover page with the
Futran Solutions logo and no running header, and `<!-- toc -->` becomes a table of contents with page numbers.
"""
from html import escape
from io import BytesIO
from pathlib import Path

from xhtml2pdf import pisa

from app.documents.render import decorate_tables, render_markdown
from app.scoring.scale import RISK_LEVELS, from_labelled

HERE = Path(__file__).parent
FONTS = HERE / "fonts"
ASSETS = HERE / "assets"
LOGO = ASSETS / "futran-logo.png"
LOGO_RATIO = 3180 / 519  # width ÷ height of the logo image
PAGE = "size: letter; margin: 2.3cm 2cm 2.2cm 2cm;"
FRAMES = ("@frame header_frame { -pdf-frame-content: header_content; left: 2cm; width: 17.6cm; top: 0.9cm; height: 1cm; }"
          "@frame footer_frame { -pdf-frame-content: footer_content; left: 2cm; width: 17.6cm; top: 26.3cm; height: 0.9cm; }")

FACES = (  # family, file, weight, style. The regular face comes last: xhtml2pdf gives the bare family name to the face
    # registered last, and the table of contents is set in the bare family.
    ("plex", "IBMPlexSans-Bold.ttf", "bold", "normal"),
    ("plex", "IBMPlexSans-Italic.ttf", "normal", "italic"),
    ("plex", "IBMPlexSans-BoldItalic.ttf", "bold", "italic"),
    ("plex", "IBMPlexSans-Regular.ttf", "normal", "normal"),
    ("plexsemi", "IBMPlexSans-SemiBold.ttf", "bold", "normal"),
    ("plexsemi", "IBMPlexSans-SemiBold.ttf", "normal", "normal"),
    ("dejavu", "DejaVuSans-Bold.ttf", "bold", "normal"),
    ("dejavu", "DejaVuSans-Oblique.ttf", "normal", "italic"),
    ("dejavu", "DejaVuSans-BoldOblique.ttf", "bold", "italic"),
    ("dejavu", "DejaVuSans.ttf", "normal", "normal"),
)


def _font_css() -> str:
    missing = [f for _, f, _, _ in FACES if not (FONTS / f).is_file()]
    if missing:
        raise RuntimeError(f"Bundled fonts are missing from {FONTS}: {', '.join(missing)}")
    faces = "\n".join(f'@font-face {{ font-family: {fam}; src: url("{FONTS / f}"); font-weight: {w}; font-style: {s}; }}' for fam, f, w, s in FACES)
    return faces + "\nbody, td, th, p, li, div, span { font-family: plex, dejavu; }\nh1, h2, h3, h4, .cover-client, .toc-title { font-family: plexsemi, dejavu; font-weight: normal; }\n"


def _rating_css() -> str:
    return "\n".join(f"td.rating-{r.key} {{ background-color: #{r.fill}; color: #{r.ink}; font-weight: bold; }}" for r in RISK_LEVELS)


def _rating_class(text: str) -> str | None:
    r = from_labelled(text)
    return f"rating-{r.key}" if r else None


def _only_bundled_files(uri: str, rel: str) -> str:
    """xhtml2pdf may only load our own fonts and logo; any other URI (file, http) resolves to nothing."""
    p = Path(uri)
    if (p.parent == FONTS and p.suffix == ".ttf") or (p.parent == ASSETS and p.suffix == ".png"):
        return str(p)
    return ""


def _logo(height_cm: float, cls: str) -> str:
    return f'<img class="{cls}" src="{LOGO}" height="{height_cm}cm" width="{height_cm * LOGO_RATIO:.2f}cm" />'


def report_html(md: str, title: str, meta: dict) -> str:
    """The HTML the PDF is drawn from (exposed for tests)."""
    css = (HERE / "styles.css").read_text() + _font_css() + _rating_css()
    ref = escape(str(meta.get("audit_ref", "")))
    body = decorate_tables(render_markdown(md), _rating_class)
    header = (f'<div id="header_content"><table class="running"><tr><td class="running-left">{_logo(0.42, "header-logo")}</td>'
              f'<td class="running-right">Confidential</td></tr></table></div>')
    footer = (f'<div id="footer_content"><table class="running"><tr><td class="running-left">{ref}{"&#160;&#160;&#160;" if ref else ""}{escape(title)}</td>'
              f'<td class="running-right">Page <pdf:pagenumber> of <pdf:pagecount></td></tr></table></div>')
    if meta.get("cover"):
        cover, _, rest = body.partition('<div class="pagebreak"></div>')
        body = (f'<div class="cover"><p class="cover-logo">{_logo(1.4, "cover-logo-img")}</p><div class="cover-body">{cover}</div></div>'
                f'<pdf:nexttemplate name="main" /><div class="pagebreak"></div>{rest}')
        body = body.replace('<div class="toc"></div>', '<p class="toc-title">Contents</p><pdf:toc />')
        pages = f"@page {{ {PAGE} }}\n@page main {{ {PAGE} {FRAMES} }}\n"
    else:
        pages = f"@page {{ {PAGE} {FRAMES} }}\n"
    return f"""<html><head><meta charset="utf-8"><title>{escape(title)}</title><style>{css}{pages}</style></head><body>
{header}
{footer}
{body}
</body></html>"""


def to_pdf(md: str, title: str, meta: dict) -> bytes:
    out = BytesIO()
    result = pisa.CreatePDF(report_html(md, title, meta), dest=out, encoding="utf-8", link_callback=_only_bundled_files)
    if result.err:
        raise RuntimeError(f"PDF generation failed for {title}")
    return out.getvalue()
