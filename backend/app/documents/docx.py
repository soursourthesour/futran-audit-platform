"""Markdown → DOCX with python-docx: headings 1–3, paragraphs, bold/italic, lists, tables, quotes and page breaks."""
from io import BytesIO

from docx import Document
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from app.documents.render import SENTINEL, tokens

NAVY = RGBColor(0x1B, 0x3A, 0x6B)
FONT = "Arial"  # IBM Plex Sans is the brand face, but Arial is on every reader's machine


def _field(paragraph, instr: str) -> None:
    run = paragraph.add_run()
    for tag, attrs in (("w:fldChar", {"w:fldCharType": "begin"}), ("w:instrText", None), ("w:fldChar", {"w:fldCharType": "end"})):
        el = OxmlElement(tag)
        if attrs:
            for k, v in attrs.items():
                el.set(qn(k), v)
        else:
            el.set(qn("xml:space"), "preserve")
            el.text = instr
        run._r.append(el)


def _inline(paragraph, inline_token) -> None:
    bold = italic = False
    for t in inline_token.children or []:
        if t.type == "strong_open":
            bold = True
        elif t.type == "strong_close":
            bold = False
        elif t.type == "em_open":
            italic = True
        elif t.type == "em_close":
            italic = False
        elif t.type in ("text", "code_inline"):
            r = paragraph.add_run(t.content)
            r.bold, r.italic = bold or None, italic or None
            if t.type == "code_inline":
                r.font.name = "Consolas"
        elif t.type == "softbreak":
            paragraph.add_run(" ")
        elif t.type == "hardbreak":
            paragraph.add_run().add_break()


def _styles(doc) -> None:
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = FONT, Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    for i, size in ((1, 18), (2, 14), (3, 12)):
        s = doc.styles[f"Heading {i}"]
        s.font.name, s.font.size, s.font.color.rgb, s.font.bold = FONT, Pt(size), NAVY, True


def to_docx(md: str, title: str, meta: dict) -> bytes:
    doc = Document()
    _styles(doc)
    doc.core_properties.title = title
    doc.core_properties.author = "Futran Solutions"
    sec = doc.sections[0]
    sec.header.paragraphs[0].text = "Futran Solutions · Confidential"
    sec.header.paragraphs[0].runs[0].font.size = Pt(8)
    fp = sec.footer.paragraphs[0]
    fp.add_run(f"{meta.get('audit_ref', '')} · {title} · Page ").font.size = Pt(8)
    _field(fp, "PAGE")

    toks = tokens(md)
    lists: list[str] = []
    table: list[list[tuple[str, object]]] | None = None
    row: list | None = None
    in_quote = False
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.type == "heading_open":
            level = min(int(t.tag[1]), 3)
            p = doc.add_paragraph(style=f"Heading {level}")
            _inline(p, toks[i + 1])
            i += 3
            continue
        if t.type in ("bullet_list_open", "ordered_list_open"):
            lists.append("Bullet" if t.type == "bullet_list_open" else "Number")
        elif t.type in ("bullet_list_close", "ordered_list_close"):
            lists.pop()
        elif t.type == "blockquote_open":
            in_quote = True
        elif t.type == "blockquote_close":
            in_quote = False
        elif t.type == "table_open":
            table = []
        elif t.type == "tr_open":
            row = []
        elif t.type in ("th_open", "td_open"):
            row.append((t.type, toks[i + 1]))
            i += 3
            continue
        elif t.type == "tr_close":
            table.append(row)
        elif t.type == "table_close":
            cols = max(len(r) for r in table)
            tbl = doc.add_table(rows=len(table), cols=cols)
            tbl.style = "Table Grid"
            for ri, r in enumerate(table):
                for ci, (kind, inline) in enumerate(r):
                    cell_p = tbl.cell(ri, ci).paragraphs[0]
                    _inline(cell_p, inline)
                    if kind == "th_open":
                        for run in cell_p.runs:
                            run.bold = True
            table = None
        elif t.type == "paragraph_open":
            inline = toks[i + 1]
            if inline.content.strip() == SENTINEL:
                doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            else:
                style = None
                if lists:
                    style = f"List {lists[-1]}" + (f" {min(len(lists), 3)}" if len(lists) > 1 else "")
                elif in_quote:
                    style = "Quote"
                p = doc.add_paragraph(style=style)
                _inline(p, inline)
            i += 3
            continue
        elif t.type == "hr":
            doc.add_paragraph()
        elif t.type in ("fence", "code_block"):
            p = doc.add_paragraph()
            r = p.add_run(t.content.rstrip("\n"))
            r.font.name = "Consolas"
        i += 1
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
