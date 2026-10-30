from sqlalchemy import select

from app.inventory.models import AITool, UseCase
from app.register.models import RegisterSystem
from tests.factories import make_org, make_user
from tests.register.conftest import new_system


def test_evidence_upload_and_download_scoped(client, db, reg, settings, tmp_path):
    settings.file_store = f"local:{tmp_path}"
    client.app.state.settings = settings
    reg.as_(reg.hr_lead)
    s = new_system(client, department_id=reg.hr.id)
    r = client.post(f"/api/v1/register/{s['id']}/evidence", files={"file": ("dpa.pdf", b"%PDF-1.4 dpa", "application/pdf")})
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    assert [f["filename"] for f in client.get(f"/api/v1/register/{s['id']}/evidence").json()] == ["dpa.pdf"]
    assert client.get(f"/api/v1/files/{fid}").status_code == 200
    reg.as_(reg.fin_lead)
    assert client.get(f"/api/v1/files/{fid}").status_code == 404
    other = make_org(db, name="Other Co")
    o = make_user(db, other, roles=["caico"], name="Olga", email="olga@other.test")
    db.commit()
    reg.as_(o)
    assert client.get(f"/api/v1/files/{fid}").status_code == 404


def test_csv_export(client, db, reg):
    reg.as_(reg.caico)
    a = new_system(client, name="=HYPERLINK(1)", department_id=reg.hr.id)
    new_system(client, name="Invoice OCR", department_id=reg.fin.id)
    r = client.get("/api/v1/register/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("reference,name,type,sourcing,department,stage")
    assert any(line.startswith("AIS-001,'=HYPERLINK(1)") for line in lines)
    r = client.get(f"/api/v1/register/export.csv?ids={a['id']}")
    assert len(r.text.strip().splitlines()) == 2
    reg.as_(reg.fin_lead)
    assert "HYPERLINK" not in client.get("/api/v1/register/export.csv").text


def test_csv_import_validates_each_row(client, db, reg):
    reg.as_(reg.hr_lead)
    csv_text = ("name,type,sourcing,department,stage,purpose,vendor,ai_provider,model_name,decision_impact,owner_email\n"
                "Résumé screening,Vendor app with AI,vendor,Human Resources,live,Ranks applicants,TalentRank Inc.,unknown,RankNet,consequential,hana@abc.test\n"
                "Chatbot,AI agent,in_house,Human Resources,proposed,Answers questions,,openai,GPT-4.1,none,\n"
                ",robot,x,Finance,proposed,,,,,,\n")
    r = client.post("/api/v1/register/import", files={"file": ("systems.csv", csv_text.encode(), "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 0  # live in the file and bad rows: nothing is imported until the file is clean
    msgs = {(e["row"], e["field"]) for e in body["errors"]}
    assert (2, "stage") in msgs and (4, "name") in msgs and (4, "type") in msgs and (4, "department") in msgs
    good = csv_text.splitlines()[0] + "\n" + csv_text.splitlines()[1].replace(",live,", ",in_development,") + "\n" + csv_text.splitlines()[2] + "\n"
    r = client.post("/api/v1/register/import", files={"file": ("systems.csv", good.encode(), "text/csv")})
    assert r.json() == {"created": 2, "errors": []}
    rows = db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == reg.org.id).order_by(RegisterSystem.reference)).all()
    assert [(x.name, x.type, x.origin, x.owner_user_id) for x in rows] == [("Résumé screening", "vendor_app", "csv", reg.hr_user.id), ("Chatbot", "agent", "csv", None)]
    assert rows[0].vendor_id is not None


def test_csv_template(client, db, reg):
    reg.as_(reg.admin)
    r = client.get("/api/v1/register/import-template.csv")
    assert r.status_code == 200 and r.text.startswith("name,type,sourcing,department,stage")


def _inventory(db, reg):
    from app.engagements.models import Engagement

    e = Engagement(organization_id=reg.org.id, client_id=reg.org.id, name="AI audit 2026", audit_ref="AUD-1", stage=4, status="active")
    db.add(e)
    db.flush()
    chat_free = AITool(organization_id=reg.org.id, vendor="OpenAI", product="ChatGPT", account_type="personal_free", source="attestation", declared_count=5)
    chat_ent = AITool(organization_id=reg.org.id, vendor="OpenAI", product="ChatGPT", account_type="enterprise", approval_status="approved")
    bot = AITool(organization_id=reg.org.id, vendor="HireBot Co.", product="Scheduler", account_type="enterprise", kind="agent")
    rank = AITool(organization_id=reg.org.id, vendor="TalentRank Inc.", product="TalentRank", account_type="enterprise")
    db.add_all([chat_free, chat_ent, bot, rank])
    db.flush()
    db.add(UseCase(organization_id=reg.org.id, engagement_id=e.id, name="Résumé screening", department_id=reg.hr.id, purpose="Shortlists applicants", tool_ids=[rank.id],
                   data_categories=["pii"], decision_impact="consequential", proposed_tier=3, status="dept_approved"))
    db.add(UseCase(organization_id=reg.org.id, engagement_id=e.id, name="Draft emails", department_id=reg.fin.id, tool_ids=[chat_ent.id], data_categories=["none"],
                   decision_impact="none", proposed_tier=1, status="draft"))
    db.add(UseCase(organization_id=reg.org.id, engagement_id=e.id, name="Policy Q&A", department_id=reg.hr.id, tool_ids=[], data_categories=["confidential"],
                   decision_impact="informs", proposed_tier=2, status="dept_approved"))
    db.commit()
    return chat_free, chat_ent, bot, rank


def test_import_from_inventory_dedupes_and_reruns(client, db, reg):
    chat_free, chat_ent, bot, rank = _inventory(db, reg)
    reg.as_(reg.caico)
    r = client.post("/api/v1/register/import-inventory")
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 4  # ChatGPT once, Scheduler, TalentRank, Policy Q&A (approved use case with no tool)
    rows = {s.name: s for s in db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == reg.org.id))}
    assert set(rows) == {"ChatGPT", "Scheduler", "TalentRank", "Policy Q&A"}
    assert all(s.stage == "proposed" and s.origin == "inventory" for s in rows.values())
    assert rows["Scheduler"].type == "agent" and rows["ChatGPT"].sourcing == "vendor"
    tr = rows["TalentRank"]
    assert tr.department_id == reg.hr.id and tr.decision_impact == "consequential" and tr.risk_tier == 3 and tr.purpose == "Shortlists applicants"
    assert rows["ChatGPT"].company_wide is False and rows["ChatGPT"].department_id is None
    # running it again adds nothing; a manual row with the same vendor and name also counts
    assert client.post("/api/v1/register/import-inventory").json()["created"] == 0
    reg.as_(reg.hr_lead)
    assert client.post("/api/v1/register/import-inventory").status_code == 403


def test_import_from_inventory_shadow_only_tool(client, db, reg):
    t = AITool(organization_id=reg.org.id, vendor="Anthropic", product="Claude", account_type="personal_free", source="attestation")
    db.add(t)
    db.commit()
    reg.as_(reg.admin)
    client.post("/api/v1/register/import-inventory")
    s = db.scalar(select(RegisterSystem).where(RegisterSystem.name == "Claude"))
    assert s.sourcing == "shadow" and s.type == "genai_chat_tool"


def test_import_tool_made_by_the_client_is_in_house(client, db, reg):
    db.add(AITool(organization_id=reg.org.id, vendor="ABC Corp", product="Invoice anomaly model", account_type="enterprise"))
    db.commit()
    reg.as_(reg.caico)
    client.post("/api/v1/register/import-inventory")
    s = db.scalar(select(RegisterSystem).where(RegisterSystem.name == "Invoice anomaly model"))
    assert s.sourcing == "in_house" and s.vendor_id is None and s.type == "in_house_model"
