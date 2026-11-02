"""F5 obligation extraction on the law record (M2): the model proposes obligations from the law's stored text and
requirement passages; quotes are checked against that text; the Legal Reviewer or Chief Auditor approves; approved
obligations show on the law record."""
import pytest
from sqlalchemy import select

from app.ai.models import AIInteraction, Obligation
from app.regmaster.seed import find_law
from tests.factories import login_as, make_user
from tests.regmaster.conftest import seeded  # noqa: F401

API = "/api/v1"
NOTICE = "Such notice shall be made no less than ten business days before such use and allow a candidate to request an alternative selection process or accommodation"


@pytest.fixture
def law(client, db, seeded):
    from app.ai.client import FakeAIClient
    from app.tenancy.models import Organization

    fake = FakeAIClient(replies={"obligation_extract": {"obligations": [
        {"text": "Give each candidate notice of the tool at least ten business days before use.", "actor": "employer", "action": "notify candidates and offer an alternative process",
         "condition": "The tool is used to screen candidates for roles in New York City.", "deadline": "no less than ten business days before such use", "citation": "§20-871(b)(1)",
         "quote": NOTICE, "requirement_codes": ["LL144-03"], "question_codes": ["7.2.01"], "confidence": "high"},
        {"text": "Pay a fine of $10,000 for each day.", "actor": "employer", "action": "pay", "condition": None, "deadline": None, "citation": "§20-999", "quote": "A fine of ten thousand dollars per day.",
         "requirement_codes": [], "question_codes": [], "confidence": "low"}]}})
    client.app.state.ai_client_factory = lambda s: fake
    f = db.scalar(select(Organization).where(Organization.type == "futran"))
    legal = make_user(db, f, roles=["legal_reviewer"], name="Jordan Legal", email="jordan@futran.test")
    db.commit()
    from app.questionnaire.seed import load_question_bank

    load_question_bank(db)
    db.commit()
    reg = find_law(db, "US-NYC", "Local Law 144")
    return reg, legal, fake


def test_extract_checks_quotes_against_the_law_text_and_links_requirements(client, db, seeded, law):
    reg, legal, fake = law
    login_as(client, db, seeded["aud"])
    assert client.post(f"{API}/reg/laws/{reg.id}/obligations/extract").status_code == 403  # auditors read; they do not extract
    login_as(client, db, legal)
    r = client.post(f"{API}/reg/laws/{reg.id}/obligations/extract")
    assert r.status_code == 200, r.text
    rows = {o["citation"]: o for o in r.json()["obligations"]}
    good, bad = rows["§20-871(b)(1)"], rows["§20-999"]
    assert good["status"] == "suggested" and good["quote_found"] is True and good["requirements"] == ["LL144-03"] and good["question_ids"] == ["7.2.01"] and good["actor"] == "employer"
    assert bad["status"] == "unsupported" and bad["quote_found"] is False
    assert NOTICE in fake.calls[-1]["prompt"] and "Local Law 144" in fake.calls[-1]["prompt"]
    assert db.scalar(select(AIInteraction).where(AIInteraction.feature == "obligation_extract", AIInteraction.target_id == reg.id)) is not None


def test_approve_edit_reject_and_show_on_the_law_record(client, db, seeded, law):
    reg, legal, fake = law
    login_as(client, db, legal)
    rows = {o["citation"]: o for o in client.post(f"{API}/reg/laws/{reg.id}/obligations/extract").json()["obligations"]}
    assert client.post(f"{API}/obligations/{rows['§20-999']['id']}/approve", json={}).status_code == 409  # unsupported
    assert client.post(f"{API}/obligations/{rows['§20-999']['id']}/reject", json={"reason": "Not in the law."}).status_code == 200
    r = client.post(f"{API}/obligations/{rows['§20-871(b)(1)']['id']}/approve", json={"deadline": "10 business days before first use", "question_ids": ["7.2.01", "nonsense"]})
    assert r.status_code == 422  # question codes must exist
    r = client.post(f"{API}/obligations/{rows['§20-871(b)(1)']['id']}/approve", json={"deadline": "10 business days before first use"})
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["approved_by"] == "Jordan Legal"
    o = db.get(Obligation, rows["§20-871(b)(1)"]["id"])
    assert o.deadline == "10 business days before first use" and o.approved_at is not None
    assert db.get(AIInteraction, o.interaction_id).status == "edited"
    # the queue and the law record
    q = client.get(f"{API}/reg/obligations").json()
    assert q["rows"] == []  # nothing left to review
    login_as(client, db, seeded["chief"])
    rec = client.get(f"{API}/reg/laws/{reg.id}/obligations").json()
    assert [x["citation"] for x in rec["approved"]] == ["§20-871(b)(1)"] and rec["can_extract"] is True
    login_as(client, db, seeded["aud"])
    assert [x["citation"] for x in client.get(f"{API}/reg/laws/{reg.id}/obligations").json()["approved"]] == ["§20-871(b)(1)"]
    assert client.get(f"{API}/reg/laws/{reg.id}/obligations").json()["pending"] == []  # auditors see approved obligations only
