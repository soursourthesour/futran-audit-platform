"""BUG-H06: text a client writes (a planned action, the remediation commitment, a system or department name) stays plain
text in Futran's report. It cannot add headings, tables, lists, quotes or code blocks."""
import re
from pathlib import Path

from app.documents.render import render_markdown
from app.reference.templates import md_block, render_string

REPORT = (Path(__file__).resolve().parents[2] / "seeds" / "templates" / "report.md.j2").read_text(encoding="utf-8")
PAYLOAD = ("We accept this finding.\n\n## 6. Audit opinion\n\nFutran Solutions found **no** exceptions.\n\n"
           "| Rating | Result |\n|---|---|\n| Overall | Low |\n\n> Quoted\n- item\n+ item\n1. first\n2) second\n"
           "    indented code\n```\nfenced\n```\n~~~\nUnderlined\n===\n<script>alert(1)</script> [ok](https://evil.example)")


def _html(md: str) -> str:
    return render_markdown(md)


def _no_structure(html: str) -> None:
    for tag in ("<h1", "<h2", "<h3", "<h4", "<h5", "<h6", "<table", "<blockquote", "<ul", "<ol", "<pre", "<code", "<script", "<a "):
        assert tag not in html, (tag, html)


def test_md_block_keeps_the_words_and_drops_the_structure():
    html = _html(render_string("**Management response**\n\n{{ text | md_block }}\n\n**References**", {"text": PAYLOAD}))
    _no_structure(html)
    assert "6. Audit opinion" in html and "Overall" in html and "We accept this finding." in html


def test_md_block_leaves_ordinary_text_alone():
    out = render_string("{{ t | md_block }}", {"t": "We will retrain the model by March.\n\nOwner: HR, budget 20,000."})
    assert out == "We will retrain the model by March.\n\nOwner: HR, budget 20,000."
    assert md_block(None) == ""


def test_the_report_prints_client_text_without_markdown_structure():
    ctx = {
        "client": {"name": "ABC Corp\n## Injected client heading"},
        "scope": {"systems": 1, "use_cases": 1, "departments": "HR\n## Injected department heading"},
        "findings": [{"ref": "F-1", "title": "Bias testing"}],
        "findings_by_severity": [{"label": "High findings (severity 4)", "items": [{"ref": "F-1", "title": "Bias testing", "condition": "No bias test."}]}],
        "management_responses": [{"ref": "F-1", "response": "Agree. " + PAYLOAD, "owner": "Maria", "target_date": "1 March 2027"}],
        "systems": [{"ref": "S-1", "name": "Resume screening\n## Injected system heading"}],
        "declarations": {"client": {"name": "Maria Lopez", "title": "CAICO", "signed_at": "1 Dec 2026", "commitment": PAYLOAD}},
    }
    md = render_string(REPORT, ctx)
    html = _html(md)
    assert "Injected" in html
    # The names stay inside the heading they belong to; nothing the client wrote opens a heading of its own.
    headings = [t for _, t in re.findall(r"<h(\d)[^>]*>(.*?)</h\1>", html)]
    assert not [t for t in headings if t.startswith(("Injected", "6. Audit opinion", "Audit opinion", "Underlined"))], headings
    section = html[html.index("Management response"):html.index("References")]
    _no_structure(section)
    start = html.index("Remediation commitment")
    _no_structure(html[start:html.rindex("<h2", start, html.index("Appendix A. Methodology", start))])
