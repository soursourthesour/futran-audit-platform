"""11-03 C12: the vendor and model catalogue, a client's own "Other" models, and the monthly check that proposes additions
(with AI connected) or reminds the Futran Admin (without). Nothing changes the catalogue until a person accepts."""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.ai.client import FakeAIClient
from app.ai.models import AIInteraction
from app.notifications.models import Notification
from app.register import catalogue
from app.register.models import ClientModel, ModelCatalogueRun, ModelEntry, ModelProposal, ModelVendor
from tests.factories import login_as, make_org, make_user
from tests.register.conftest import new_system


@pytest.fixture
def futran(db, client):
    org = make_org(db, type="futran")
    admin = make_user(db, org, roles=["admin"], name="Fran Admin", email="fran@futran.test")
    auditor = make_user(db, org, roles=["auditor"], name="Ada Auditor", email="ada@futran.test")
    db.commit()
    return type("F", (), {"org": org, "admin": admin, "auditor": auditor, "as_": staticmethod(lambda u: login_as(client, db, u))})


def _cat(client):
    r = client.get("/api/v1/register/model-catalogue")
    assert r.status_code == 200, r.text
    return {v["code"]: v for v in r.json()["vendors"]}


def test_catalogue_is_seeded_once_with_current_models(client, db, reg):
    reg.as_(reg.hr_lead)
    cat = _cat(client)
    assert {"openai", "anthropic", "google", "azure_openai", "amazon_bedrock", "meta_open", "mistral", "cohere", "xai", "deepseek"} <= set(cat)
    assert "Claude Opus 5.5" in cat["anthropic"]["models"] and "GPT-5.5" in cat["openai"]["models"]
    n = db.scalar(select(ModelEntry.id).limit(1))
    _cat(client)
    assert db.query(ModelVendor).count() == len(cat) - 2 and n is not None  # plus "In-house model" and "Unknown"
    assert cat["in_house"]["models"] == [] and cat["unknown"]["name"].startswith("Unknown")


def test_other_model_is_saved_for_that_client_only(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id, ai_provider="openai", model_name="Acme fine-tuned GPT")
    assert s["model_name"] == "Acme fine-tuned GPT"
    assert _cat(client)["openai"]["client_models"] == ["Acme fine-tuned GPT"]
    new_system(client, name="Two", department_id=reg.hr.id, ai_provider="openai", model_name="GPT-5.5")  # in the catalogue: not saved again
    assert db.query(ClientModel).count() == 1
    other = make_org(db, name="Other Co")
    boss = make_user(db, other, roles=["caico"], name="Other Boss", email="boss@other.test")
    db.commit()
    login_as(client, db, boss)
    assert _cat(client)["openai"]["client_models"] == []


def test_new_vendor_codes_are_accepted_and_unknown_refused(client, db, reg):
    reg.as_(reg.caico)
    s = new_system(client, department_id=reg.hr.id, ai_provider="mistral", model_name="Mistral Large 4")
    assert s["ai_provider_label"] == "Mistral AI"
    r = client.post("/api/v1/register", json={"name": "X", "type": "vendor_app", "sourcing": "vendor", "department_id": reg.hr.id, "ai_provider": "nope"})
    assert r.status_code == 422


def test_admin_keeps_the_catalogue_and_clients_cannot(client, db, reg, futran):
    futran.as_(futran.admin)
    r = client.get("/api/v1/admin/model-catalogue")
    assert r.status_code == 200
    v = client.post("/api/v1/admin/model-catalogue/vendors", json={"name": "Acme AI"})
    assert v.status_code == 200 and v.json()["code"] == "acme_ai"
    m = client.post("/api/v1/admin/model-catalogue/models", json={"vendor_id": v.json()["id"], "name": "Acme One"})
    assert m.status_code == 200
    assert client.post("/api/v1/admin/model-catalogue/models", json={"vendor_id": v.json()["id"], "name": "acme one"}).status_code == 409
    openai = next(x for x in r.json()["vendors"] if x["code"] == "openai")
    gpt4o = next(x for x in openai["models"] if x["name"] == "GPT-4o")
    assert client.patch(f"/api/v1/admin/model-catalogue/models/{gpt4o['id']}", json={"active": False}).status_code == 200
    reg.as_(reg.caico)
    cat = _cat(client)
    assert "Acme One" in cat["acme_ai"]["models"] and "GPT-4o" not in cat["openai"]["models"]
    assert client.get("/api/v1/admin/model-catalogue").status_code in (403, 404)
    futran.as_(futran.auditor)
    assert client.post("/api/v1/admin/model-catalogue/vendors", json={"name": "Nope"}).status_code == 403


def test_monthly_check_without_ai_reminds_the_admin_once_a_month(db, reg, futran, monkeypatch):
    monkeypatch.setattr(catalogue, "client_for", lambda app_state, settings, db=None: None)
    catalogue.ensure_seeded(db)
    before = db.query(ModelEntry).count()
    assert catalogue.run_monthly(db, None, datetime(2026, 12, 1, 10)) == 1
    assert catalogue.run_monthly(db, None, datetime(2026, 12, 2, 10)) == 0  # once per calendar month
    n = db.scalars(select(Notification).where(Notification.user_id == futran.admin.id)).all()
    assert len(n) == 1 and "review" in n[0].title.lower() and n[0].link == "/admin/reference?tab=models"
    assert not db.scalars(select(Notification).where(Notification.user_id == futran.auditor.id)).all()
    assert db.scalar(select(ModelCatalogueRun.mode)) == "reminder"
    assert db.query(ModelEntry).count() == before and db.query(AIInteraction).count() == 0


def test_monthly_check_with_ai_proposes_and_a_person_decides(client, db, reg, futran, monkeypatch):
    fake = FakeAIClient(replies={"model_catalogue_refresh": {"proposals": [
        {"vendor": "OpenAI", "model": "GPT-6.2 Sol", "reason": "Released this month.", "source_url": "https://developers.openai.com/api/docs/changelog"},
        {"vendor": "OpenAI", "model": "GPT-5.5", "reason": "Already listed."},
        {"vendor": "Newco", "model": "Newco 1", "reason": "A new vendor."},
    ]}})
    monkeypatch.setattr(catalogue, "client_for", lambda app_state, settings, db=None: fake)
    monkeypatch.setattr(catalogue, "ai_status", lambda app_state, settings, db=None: {"source": "connection", "provider": "openai"})
    catalogue.ensure_seeded(db)
    before = db.query(ModelEntry).count()
    assert catalogue.run_monthly(db, None, datetime(2026, 12, 1, 10)) == 1
    db.commit()
    props = {p.model_name: p for p in db.scalars(select(ModelProposal))}
    assert set(props) == {"GPT-6.2 Sol", "Newco 1"}  # what is already listed is not proposed
    ai = db.scalars(select(AIInteraction)).all()
    assert len(ai) == 1 and ai[0].feature == "model_catalogue" and ai[0].output["proposals"][0]["model"] == "GPT-6.2 Sol"
    assert db.query(ModelEntry).count() == before  # nothing changes until a person accepts
    assert "model_catalogue_refresh" in fake.calls[0]["task"]
    futran.as_(futran.admin)
    page = client.get("/api/v1/admin/model-catalogue").json()
    assert {p["model_name"] for p in page["proposals"]} == {"GPT-6.2 Sol", "Newco 1"}
    assert client.post(f"/api/v1/admin/model-catalogue/proposals/{props['GPT-6.2 Sol'].id}/decide", json={"accept": True}).status_code == 200
    assert client.post(f"/api/v1/admin/model-catalogue/proposals/{props['Newco 1'].id}/decide", json={"accept": False}).status_code == 200
    db.expire_all()
    names = set(db.scalars(select(ModelEntry.name)))
    assert "GPT-6.2 Sol" in names and "Newco 1" not in names
    assert db.get(AIInteraction, ai[0].id).status == "decided"
    assert client.post(f"/api/v1/admin/model-catalogue/proposals/{props['Newco 1'].id}/decide", json={"accept": True}).status_code == 409


def test_daily_run_includes_the_monthly_check():
    from app.notifications.jobs import JOBS

    assert "model_catalogue_monthly" in JOBS
