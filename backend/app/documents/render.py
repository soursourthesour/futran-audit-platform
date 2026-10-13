"""Markdown → HTML for generated documents. Raw HTML in templates or merge values is escaped, never rendered."""
from markdown_it import MarkdownIt

PAGEBREAK = "<!-- pagebreak -->"
SENTINEL = "PAGEBREAK-7f3c"


def _md() -> MarkdownIt:
    return MarkdownIt("commonmark", {"html": False}).enable("table")


def preprocess(md: str) -> str:
    """Turn the page-break marker into a paragraph the DOCX and PDF writers recognise."""
    return "\n".join(f"\n{SENTINEL}\n" if line.strip() == PAGEBREAK else line for line in md.splitlines())


def tokens(md: str):
    return _md().parse(preprocess(md))


def render_markdown(md: str) -> str:
    return _md().render(preprocess(md)).replace(f"<p>{SENTINEL}</p>", '<div class="pagebreak"></div>')
