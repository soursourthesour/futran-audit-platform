"""The report explains how it rates risk and maturity, shows the level beside every rating and lists each finding's
references, from the first draft on."""
import re

from sqlalchemy import select

from app.reference.models import RiskMethodology
from app.reports.models import Report
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import inv  # noqa: F401
from tests.reports.test_reports import SUMMARY, _generate, ready  # noqa: F401


def _draft(client, db, people, cid) -> str:
    login_as(client, db, people["aud"])
    client.put(f"/api/v1/clients/{cid}/report/summary", json=SUMMARY)
    rep = _generate(client, cid, "v0.1")
    assert rep.status_code == 200, rep.text
    return db.get(Report, rep.json()["id"]).body_md


def _section(md: str, heading: str) -> str:
    start = md.index(heading)
    nxt = re.search(r"^## ", md[start + len(heading):], re.M)
    return md[start: start + len(heading) + (nxt.start() if nxt else len(md))]


def test_draft_explains_scoring_from_the_methodology(client, db, ready, people):
    from app.questionnaire.seed import load_question_bank

    cid, e, maria, f = ready
    load_question_bank(db)  # factor answers are described with the questionnaire's own option labels
    row = db.scalar(select(RiskMethodology))
    weights = {k: dict(v) for k, v in row.domain_weights_by_build_type.items()}
    weights["in_house"]["vendor_risk"] = 0.25  # an edited methodology: the report must follow it, not a copy of the yaml
    row.domain_weights_by_build_type = weights
    db.commit()
    md = _draft(client, db, people, cid)
    assert md.index("## 1. Executive summary") < md.index("## 2. How this report rates risk and maturity") < md.index("## 3. Findings")
    part = _section(md, "## 2. How this report rates risk and maturity")
    assert "25%" in part and "Vendor and third-party AI risk" in part
    for text in ("Critical (5)", "High (4)", "Medium (3)", "Low (2)", "Observation (1)", "75–100", "50–74.9", "25–49.9", "0–24.9", "30 days", "90 days"):
        assert text in part, text
    assert "inherent × (1 − 0.75 × (maturity − 1) ÷ 4)" in part
    assert "Fully automated" in part and "Analytics or reporting only" in part
    assert "70" in part and "EU AI Act" in part
    for name in ("Initial or ad hoc", "Defined and documented", "Managed and measured", "Optimized"):
        assert name in part
    assert "weighted" in _section(md, "## 1. Executive summary").lower()


def test_ratings_carry_their_level_and_findings_their_references(client, db, ready, people):
    cid, e, maria, f = ready
    md = _draft(client, db, people, cid)
    assert re.search(r"\| F-001 \| Personal AI accounts used with applicant data \| High \(4\) \|", md)
    detail = md[md.index("### F-001"):]
    assert "References" in detail and "Regulatory and standard references" in detail
    assert "Remediation due" in detail and "90 days" in detail
    rest = md.replace(_section(md, "## 2. How this report rates risk and maturity"), "").replace("<!-- pagebreak -->", "").replace("<!-- toc -->", "")
    rest = rest[: rest.index("## Appendix A")]  # the maturity scale names level 1 "None"
    for bad in (r"\bNone\b", r"\bnull\b", "<!--", r"\*\*:\*\*", r"\|[ \t]*\|"):
        assert not re.search(bad, rest), bad


def test_report_screen_gets_the_scale(client, db, ready, people):
    """The report screen labels severities from the same scale as the documents."""
    cid, e, maria, f = ready
    login_as(client, db, people["aud"])
    d = client.get(f"/api/v1/clients/{cid}/report").json()
    assert d["risk_levels"][1] == {"key": "high", "level": 4, "label": "High"}
