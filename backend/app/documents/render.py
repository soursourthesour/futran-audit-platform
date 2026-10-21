"""Markdown → HTML for generated documents. Raw HTML in templates or merge values is escaped, never rendered.

Two markers, each alone on a line, shape the printed documents: `<!-- pagebreak -->` starts a new page and
`<!-- toc -->` places the table of contents. Neither ever appears as text.
"""
import re
from html import unescape

from markdown_it import MarkdownIt

PAGEBREAK = "<!-- pagebreak -->"
TOC = "<!-- toc -->"
SENTINEL = "PAGEBREAK-7f3c"
TOC_SENTINEL = "TABLE-OF-CONTENTS-7f3c"
MARKERS = {PAGEBREAK: SENTINEL, TOC: TOC_SENTINEL}


def _md() -> MarkdownIt:
    # no raw HTML, and no images: a merge value must never make the reader's browser or the PDF writer fetch anything
    return MarkdownIt("commonmark", {"html": False}).enable("table").disable("image")


def preprocess(md: str) -> str:
    """Turn the page-break and contents markers into paragraphs the DOCX and PDF writers recognise."""
    return "\n".join(f"\n{MARKERS[line.strip()]}\n" if line.strip() in MARKERS else line for line in md.splitlines())


def tokens(md: str):
    return _md().parse(preprocess(md))


def render_markdown(md: str) -> str:
    return (_md().render(preprocess(md)).replace(f"<p>{SENTINEL}</p>", '<div class="pagebreak"></div>')
            .replace(f"<p>{TOC_SENTINEL}</p>", '<div class="toc"></div>'))


# ---- tables: rating colours and score bars, shared by the PDF writer (HTML) and the DOCX writer (cells)
SCALE_HEADER = re.compile(r"\((\d+)\s*[–-]\s*(\d+)\)\s*$")


def plain(html: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", "", html)).split())


def bar_scale(header: str) -> tuple[float, float] | None:
    """A column headed 'Maturity (1–5)' or 'Residual risk (0–100)' holds scores drawn as bars."""
    m = SCALE_HEADER.search(plain(header))
    return (float(m.group(1)), float(m.group(2))) if m else None


def bar_pct(value: str, scale: tuple[float, float]) -> int | None:
    try:
        v = float(plain(value))
    except ValueError:
        return None
    lo, hi = scale
    # a 1–5 bar starts at zero so a score of 1 still shows; percentages of the top of the scale
    return max(0, min(100, round(100 * v / hi))) if hi > lo else None


def column_widths(rows: list[list[str]], width_cm: float = 17.6) -> list[int]:
    """Percent widths. Each column first gets room for its longest word at 9 pt (so nothing breaks mid-word), then the
    rest of the line is shared out by how much text the column holds, so short codes stay narrow and prose gets room."""
    cols = max(len(r) for r in rows)
    need, weight = [], []
    for c in range(cols):
        cells = [plain(r[c]) for r in rows if c < len(r)]
        head_word = max((len(w) for w in cells[0].split()), default=1)  # headers are bold
        body_word = max((len(w) for t in cells[1:] for w in t.split()), default=1)
        avg = sum(len(t) for t in cells[1:]) / max(1, len(cells) - 1) if len(cells) > 1 else len(cells[0])
        need.append(max(0.2 * head_word, 0.18 * body_word) + 0.5)
        weight.append(max(min(avg, 60), 4) ** 1.3)  # prose columns take most of the spare room
    spare = width_cm - sum(need)
    if spare < 0:
        cm = [n * width_cm / sum(need) for n in need]
    else:
        cm = [n + spare * w / sum(weight) for n, w in zip(need, weight)]
    out = [max(1, round(100 * x / width_cm)) for x in cm]
    out[out.index(max(out))] += 100 - sum(out)
    return out


_TABLE = re.compile(r"<table>(.*?)</table>", re.S)
_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
_CELL = re.compile(r"<(t[dh])([^>]*)>(.*?)</\1>", re.S)


def decorate_tables(html: str, rating_class) -> str:
    """Repeat header rows across pages, size columns, shade rating cells ('High (4)') and draw score bars."""

    def table(m: re.Match) -> str:
        rows = [[(t, a, c) for t, a, c in _CELL.findall(r)] for r in _ROW.findall(m.group(1))]
        if not rows:
            return m.group(0)
        header = [c for _, _, c in rows[0]]
        scales = [bar_scale(h) for h in header]
        widths = column_widths([[c for _, _, c in r] for r in rows])
        out = []
        for ri, row in enumerate(rows):
            cells = []
            for ci, (tag, attrs, content) in enumerate(row):
                style = f' style="width: {widths[ci]}%"' if ri == 0 and ci < len(widths) else ""
                cls = rating_class(plain(content)) if tag == "td" else None
                if cls:
                    cells.append(f'<td class="rating {cls}"{style}>{content}</td>')
                    continue
                sc = scales[ci] if ci < len(scales) and tag == "td" else None
                pct = bar_pct(content, sc) if sc else None
                if pct is not None:
                    fill = f'<td class="bar-fill" style="width: {pct}%">&#160;</td>' if pct > 0 else ""
                    rest = f'<td class="bar-rest" style="width: {100 - pct}%">&#160;</td>' if pct < 100 else ""
                    content = (f'<table class="bar"><tr><td class="bar-num">{content}</td><td class="bar-cell">'
                               f'<table class="bar-track"><tr>{fill}{rest}</tr></table></td></tr></table>')
                cells.append(f"<{tag}{attrs}{style}>{content}</{tag}>")
            out.append("<tr>" + "".join(cells) + "</tr>")
        head, body = out[0], "".join(out[1:])
        return f'<table repeat="1"><thead>{head}</thead><tbody>{body}</tbody></table>'

    return _TABLE.sub(table, html)
