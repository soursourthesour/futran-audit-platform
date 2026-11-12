"""G-05 manual discovery import (Release 2 B5): export types, upload, column mapping with saved presets, preview, vendor
matching, DiscoveredTool rows with signal "manual_import" and the same confirm/dismiss flow, each import an evidence item
with SHA-256, and `discovery_finding` opportunities once a finding is final (its tool confirmed)."""
import hashlib
import io
import json

from sqlalchemy import select

from app.connectors.models import DiscoveredTool, DiscoveryImport
from app.files.models import FileObject
from app.sales.models import Opportunity

COPILOT = b"""User Principal Name,Display Name,Department,Last activity date (UTC),Products assigned
ana@abccorp.example,Ana Ruiz,HR,2026-10-30,Microsoft 365 Copilot
ben@abccorp.example,Ben Ok,HR,,Microsoft 365 Copilot
cy@abccorp.example,Cy Lee,Finance,2026-11-01,Microsoft 365 Copilot
"""
ENTRA = b"""Application name,Users,Consent type
Otter.ai,9,User consent
AI Notes Pro,1,User consent
Workday,800,Admin consent
HireVue,12,Admin consent
"""
EXPENSE = b"""Employee,Email,Department,Description,Amount
Ana Ruiz,ana@abccorp.example,Recruiting,OPENAI *CHATGPT SUBSCR,20.00
Ben Ok,ben@abccorp.example,Recruiting,OPENAI *CHATGPT SUBSCR,20.00
Cy Lee,cy@abccorp.example,Finance,STAPLES 0042,12.00
"""
PROXY = b"""user,department,destination_host,requests
u1@abccorp.example,Operations,chatgpt.com,40
u2@abccorp.example,Operations,claude.ai,7
u3@abccorp.example,Operations,www.bbc.co.uk,99
"""
AGENTS = b"""Agent name,Type,Owner
Carrier booking agent,Agent,ops@abccorp.example
Invoice triage,Agent,fin@abccorp.example
"""


def _base(w):
    return f"/api/v1/engagements/{w.engagement.id}/discovery"


def _post(w, path, export_type, data, name="export.csv", mapping=None, **extra):
    form = {"export_type": export_type}
    if mapping is not None:
        form["mapping"] = json.dumps(mapping)
    form.update(extra)
    return w.client.post(f"{_base(w)}/{path}", data=form, files={"file": (name, data, "text/csv")})


def test_the_auditor_on_the_engagement_sees_the_export_types(w):
    w.as_(w.auditor)
    r = w.client.get(f"{_base(w)}/import")
    assert r.status_code == 200, r.text
    d = r.json()
    assert [t["value"] for t in d["export_types"]] == ["copilot_usage", "entra_apps", "google_apps", "gemini_usage", "gemini_agents", "expense", "proxy"]
    assert d["engagement"]["client_name"] == "ABC Corp"
    w.as_(w.other_auditor)
    assert w.client.get(f"{_base(w)}/import").status_code == 404
    w.as_(w.admin)
    assert w.client.get("/api/v1/integrations/import").status_code == 200
    w.as_(w.caico)
    assert w.client.get("/api/v1/integrations/import").status_code == 403


def test_analyse_guesses_the_mapping_and_previews_without_storing_anything(w):
    w.as_(w.auditor)
    r = _post(w, "import/analyse", "copilot_usage", COPILOT)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["mapping"]["user"] == "User Principal Name" and d["mapping"]["department"] == "Department"
    assert d["mapping"]["last_activity"] == "Last activity date (UTC)"
    assert d["rows_read"] == 3 and d["rows_matched"] == 3
    tools = {(t["product"], t["department"]): t for t in d["tools"]}
    assert tools[("Copilot", "HR")]["user_count"] == 2 and "1 active" in tools[("Copilot", "HR")]["detail"]
    assert d["preview"][0]["cells"]["user"] == "ana@abccorp.example"
    assert w.db.scalar(select(DiscoveredTool.id)) is None and w.db.scalar(select(DiscoveryImport.id)) is None


def test_a_required_column_left_unmapped_is_refused(w):
    w.as_(w.auditor)
    r = _post(w, "import/analyse", "entra_apps", ENTRA, mapping={"app": "", "users": "Users"})
    assert r.status_code == 422
    assert "Application" in r.json()["errors"][0]["message"] or "app" in r.json()["errors"][0]["field"]


def test_import_creates_manual_import_tools_and_one_evidence_item_with_its_sha256(w):
    w.as_(w.auditor)
    r = _post(w, "imports", "copilot_usage", COPILOT, name="copilot-oct.csv")
    assert r.status_code == 200, r.text
    imp = w.db.get(DiscoveryImport, r.json()["id"])
    assert imp.source_sha256 == hashlib.sha256(COPILOT).hexdigest() and imp.engagement_id == w.engagement.id
    ev = w.db.get(FileObject, imp.evidence_file_id)
    assert ev.linked_type == "evidence" and ev.engagement_id == w.engagement.id and ev.sha256 == imp.source_sha256
    rows = list(w.db.scalars(select(DiscoveredTool).where(DiscoveredTool.organization_id == w.org.id)))
    assert {(t.product, t.signal, t.import_type, t.user_count) for t in rows} == {("Copilot", "manual_import", "copilot_usage", 2), ("Copilot", "manual_import", "copilot_usage", 1)}
    assert all(t.status == "new" and t.import_id == imp.id for t in rows)
    page = w.client.get(f"{_base(w)}/import").json()
    assert page["imports"][0]["filename"] == "copilot-oct.csv" and page["imports"][0]["sha256"] == imp.source_sha256
    assert any(t["signal_label"].startswith("Manual import") for t in page["tools"])


def test_a_saved_preset_is_offered_again_for_that_export_type(w):
    w.as_(w.auditor)
    mapping = {"app": "Application name", "users": "Users", "consent": "Consent type"}
    r = _post(w, "imports", "entra_apps", ENTRA, mapping=mapping, save_preset="Entra standard export")
    assert r.status_code == 200, r.text
    page = w.client.get(f"{_base(w)}/import").json()
    preset = next(p for p in page["presets"] if p["name"] == "Entra standard export")
    assert preset["export_type"] == "entra_apps" and preset["mapping"]["users"] == "Users"
    w.as_(w.chief)  # Futran's presets are shared by Futran staff
    assert any(p["name"] == "Entra standard export" for p in w.client.get(f"{_base(w)}/import").json()["presets"])
    w.as_(w.admin)  # and never shown to a client
    assert w.client.get("/api/v1/integrations/import").json()["presets"] == []


def test_vendor_dictionary_matches_names_and_lists_ai_looking_rows_it_does_not_know(w):
    w.as_(w.auditor)
    d = _post(w, "import/analyse", "entra_apps", ENTRA).json()
    assert d["rows_read"] == 4 and d["rows_matched"] == 2
    assert {t["product"] for t in d["tools"]} == {"Otter.ai", "HireVue"}
    assert [u["name"] for u in d["unmatched"]] == ["AI Notes Pro"]  # Workday is not an AI product and is not listed


def test_an_unmatched_row_can_be_matched_by_hand(w):
    w.as_(w.auditor)
    imp = _post(w, "imports", "entra_apps", ENTRA).json()
    r = w.client.post(f"{_base(w)}/imports/{imp['id']}/unmatched/0/match", json={"vendor": "Notes Pro Inc", "product": "AI Notes Pro"})
    assert r.status_code == 200, r.text
    t = w.db.scalar(select(DiscoveredTool).where(DiscoveredTool.product == "AI Notes Pro"))
    assert t.signal == "manual_import" and t.vendor == "Notes Pro Inc" and t.user_count == 1


def test_expense_and_proxy_keep_only_a_summary_as_evidence_and_the_hash_of_the_original(w, settings):
    from app.files.service import read

    w.as_(w.auditor)
    for et, data in (("expense", EXPENSE), ("proxy", PROXY)):
        r = _post(w, "imports", et, data)
        assert r.status_code == 200, r.text
        imp = w.db.get(DiscoveryImport, r.json()["id"])
        assert imp.source_sha256 == hashlib.sha256(data).hexdigest()
        ev = w.db.get(FileObject, imp.evidence_file_id)
        assert ev.sha256 != imp.source_sha256 and ev.filename.endswith("summary.csv")
        body = read(settings, ev).decode()
        assert "@abccorp.example" not in body and "STAPLES" not in body and "bbc" not in body
    proxy_tools = list(w.db.scalars(select(DiscoveredTool).where(DiscoveredTool.import_type == "proxy")))
    assert {t.product for t in proxy_tools} == {"ChatGPT", "Claude"}
    from app.connectors.models import DiscoveredToolUser

    assert w.db.scalar(select(DiscoveredToolUser.id).where(DiscoveredToolUser.discovered_tool_id.in_([t.id for t in proxy_tools]))) is None


def test_findings_raise_discovery_finding_opportunities_once_the_tool_is_confirmed(w):
    w.as_(w.auditor)
    imp = _post(w, "imports", "copilot_usage", COPILOT).json()
    assert [f["key"] for f in imp["findings"]] == ["copilot_licences"] and imp["findings"][0]["opportunity_id"] is None
    assert w.db.scalar(select(Opportunity.id).where(Opportunity.trigger == "discovery_finding")) is None
    tid = imp["tools"][0]["id"]
    r = w.client.post(f"{_base(w)}/tools/{tid}/confirm")
    assert r.status_code == 200, r.text
    opp = w.db.scalar(select(Opportunity).where(Opportunity.trigger == "discovery_finding"))
    assert opp is not None and opp.organization_id == w.org.id and "X-04" in opp.service and opp.trigger_ref == "copilot_licences"
    from app.sales.models import TRIGGER_LABELS

    assert TRIGGER_LABELS["discovery_finding"] == "Discovery finding"
    again = _post(w, "imports", "copilot_usage", COPILOT).json()
    assert again["findings"][0]["opportunity_id"] == opp.id
    assert len(list(w.db.scalars(select(Opportunity).where(Opportunity.trigger == "discovery_finding")))) == 1


def test_agents_found_feed_agent_assurance_and_raise_an_aa_aw_finding(w):
    w.as_(w.auditor)
    imp = _post(w, "imports", "gemini_agents", AGENTS).json()
    assert {t["product"] for t in imp["tools"]} == {"Carrier booking agent", "Invoice triage"}
    assert [f["key"] for f in imp["findings"]] == ["agents_found"]
    w.client.post(f"{_base(w)}/tools/{imp['tools'][0]['id']}/confirm")
    opp = w.db.scalar(select(Opportunity).where(Opportunity.trigger_ref == "agents_found"))
    assert opp is not None and "AA" in opp.service and "AW" in opp.service


def test_undeclared_paid_ai_tools_are_a_finding(w):
    w.as_(w.auditor)
    imp = _post(w, "imports", "expense", EXPENSE).json()
    f = next(f for f in imp["findings"] if f["key"] == "undeclared_paid")
    assert "1 undeclared paid AI tool" in f["label"]


def test_an_eu_scoped_high_risk_tool_is_an_x03_finding(w):
    from app.engagements.models import ClientLocation

    w.db.add(ClientLocation(organization_id=w.org.id, site_name="Dublin", country_code="IE", in_scope=True, jurisdiction_ids=[]))
    w.db.commit()
    w.as_(w.auditor)
    imp = _post(w, "imports", "entra_apps", ENTRA).json()
    f = next(f for f in imp["findings"] if f["key"] == "eu_high_risk")
    assert "HireVue" in f["label"] and "X-03" in f["service"]


def test_a_workbook_upload_goes_through_the_workbook_guard(w):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Application name", "Users"])
    ws.append(["Otter.ai", 4])
    buf = io.BytesIO()
    wb.save(buf)
    w.as_(w.auditor)
    r = w.client.post(f"{_base(w)}/import/analyse", data={"export_type": "entra_apps"},
                      files={"file": ("apps.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    assert r.json()["tools"][0]["product"] == "Otter.ai" and r.json()["tools"][0]["user_count"] == 4
    bad = w.client.post(f"{_base(w)}/import/analyse", data={"export_type": "entra_apps"}, files={"file": ("apps.xlsx", b"not a workbook", "application/octet-stream")})
    assert bad.status_code == 422


def test_the_client_admin_imports_from_integrations_and_decides_there(w):
    w.as_(w.admin)
    r = w.client.post("/api/v1/integrations/imports", data={"export_type": "entra_apps"}, files={"file": ("apps.csv", ENTRA, "text/csv")})
    assert r.status_code == 200, r.text
    imp = w.db.get(DiscoveryImport, r.json()["id"])
    assert imp.engagement_id is None and w.db.get(FileObject, imp.evidence_file_id).linked_type == "discovery_import"
    page = w.client.get("/api/v1/integrations").json()
    otter = next(t for t in page["tools"] if t["product"] == "Otter.ai")
    assert otter["signal"] == "manual_import" and otter["signal_label"].startswith("Manual import")
    assert w.client.post(f"/api/v1/discovered-tools/{otter['id']}/confirm").status_code == 200
    w.as_(w.caico)
    assert w.client.post("/api/v1/integrations/imports", data={"export_type": "entra_apps"}, files={"file": ("apps.csv", ENTRA, "text/csv")}).status_code == 403


def test_another_tenant_cannot_reach_the_engagement_import(w):
    w.as_(w.other_admin)
    assert w.client.get(f"{_base(w)}/import").status_code in (403, 404)
    assert _post(w, "imports", "entra_apps", ENTRA).status_code in (403, 404)
