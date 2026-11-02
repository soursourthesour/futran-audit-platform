"""Text extraction keeps page numbers, and the quote check (AI rule 2) is whitespace- and case-insensitive."""
from io import BytesIO


def _pdf(pages: list[list[str]]) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for lines in pages:
        y = 720
        for line in lines:
            c.drawString(72, y, line)
            y -= 16
        c.showPage()
    c.save()
    return buf.getvalue()


def _docx(paragraphs: list[str]) -> bytes:
    import docx

    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    buf = BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_pdf_pages_keep_their_numbers():
    from app.ai.text import extract_pages

    method, pages, error = extract_pages("standard.pdf", _pdf([["Model Governance Standard"], ["2.1 All models are trained through the Azure ML pipeline", "with staged approval gates."]]))
    assert method == "pdf" and error is None and [p["page"] for p in pages] == [1, 2]
    assert "Azure ML pipeline" in pages[1]["text"]


def test_docx_is_split_into_pages_of_about_3000_characters_on_paragraph_boundaries():
    from app.ai.text import extract_pages

    paras = [f"Paragraph {i}. " + "Text of the model card section. " * 40 for i in range(8)]  # about 1,300 characters each
    method, pages, error = extract_pages("card.docx", _docx(paras))
    assert method == "docx" and error is None and len(pages) >= 3
    assert all(len(p["text"]) <= 3000 + 1400 for p in pages)
    assert pages[0]["text"].startswith("Paragraph 0.") and any(p["text"].startswith("Paragraph 2.") or "Paragraph 2." in p["text"] for p in pages)
    joined = "\n".join(p["text"] for p in pages)
    assert all(f"Paragraph {i}." in joined for i in range(8))


def test_plain_text_and_unreadable_files():
    from app.ai.text import extract_pages

    method, pages, error = extract_pages("notes.txt", "Monitoring runs weekly.\n".encode())
    assert method == "text" and pages == [{"page": 1, "text": "Monitoring runs weekly."}]
    method, pages, error = extract_pages("photo.png", b"\x89PNG....")
    assert method == "none" and pages == [] and error == "Text can't be read from this file type."
    method, pages, error = extract_pages("broken.pdf", b"%PDF-1.4 not really")
    assert method == "pdf" and pages == [] and error == "The text of this PDF could not be read."


def test_quote_check_normalises_whitespace_case_and_typographic_marks():
    from app.ai.text import find_quote

    pages = [{"page": 1, "text": "Intro"}, {"page": 4, "text": "All models are trained and deployed through the\nAzure ML pipeline with staged approval gates (dev – UAT – prod)."}]
    assert find_quote(pages, "all models are trained and deployed through the azure ML pipeline", 4) == 4
    assert find_quote(pages, "staged approval gates (dev - UAT - prod)", 1) == 4  # cited the wrong page: the page it is on
    assert find_quote(pages, "Section 5 Limitations: TBD.", 4) is None
    assert find_quote(pages, "  ", 4) is None
    assert find_quote([{"page": 2, "text": "the “model owner” signs each release"}], 'the "model owner" signs each release', 2) == 2
