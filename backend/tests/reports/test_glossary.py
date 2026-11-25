"""BUG-K05: every system profile in the report has an 'EU AI Act risk level' row, so Appendix C defines the term and
the levels the report can show (High-risk was already there)."""
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / "seeds" / "templates" / "report.md.j2"


def _glossary_terms() -> list[str]:
    text = TEMPLATE.read_text(encoding="utf-8")
    block = text.split("## Appendix C. Glossary", 1)[1].split("\n## ", 1)[0]
    rows = [ln for ln in block.splitlines() if ln.startswith("| ") and not ln.startswith("| Term ")]
    return [ln.split("|")[1].strip() for ln in rows]


def test_glossary_defines_the_eu_ai_act_risk_level_and_its_levels():
    terms = _glossary_terms()
    for t in ("EU AI Act risk level", "Limited risk (EU AI Act)", "Minimal risk (EU AI Act)", "High-Risk AI (EU AI Act)"):
        assert t in terms
