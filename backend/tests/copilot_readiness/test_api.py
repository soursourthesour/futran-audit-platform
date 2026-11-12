"""G-07 Copilot readiness workspace (spec B7, screen G-07): imports with column checks kept as evidence with SHA-256,
the site risk list, rollout waves with gates, the controls checklist, the readiness report and the Copilot entry in
the client's AI register. Client view for the CAICO."""
import hashlib
import io

from sqlalchemy import select

from app.copilot_readiness.models import CopilotImport
from app.files.models import FileObject
from app.register.models import RegisterSystem
from tests.copilot_readiness.conftest import LICENCES, PURVIEW, SAM, upload


def test_workspace_only_on_copilot_engagements_with_the_default_controls(cp):
    cp.as_(cp.auditor)
    r = cp.client.get(cp.url)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["phase"] == "pilot" and d["summary"] == {"licences": None, "active_users": None, "high_risk_sites": 0, "controls_ready": 0, "controls_total": 9}
    assert [c["key"] for c in d["controls"]][:4] == ["oversharing_report", "audit_logging", "usage_policy", "pilot_group"] and d["can_manage"] is True
    assert cp.client.get(f"/api/v1/e/{cp.plain.id}/copilot").status_code == 404
    assert cp.client.get(f"/api/v1/e/{cp.engagement.id}/workspaces").json()["copilot"] is True


def test_licence_import_counts_licences_and_active_users_and_is_kept_as_evidence(cp):
    cp.as_(cp.auditor)
    r = upload(cp, "licence_usage", LICENCES)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["summary"]["licences"] == 4 and d["summary"]["active_users"] == 2  # active in the 28 days to the report date
    assert d["usage_as_of"] == "2026-11-08" and {x["department"]: x["licences"] for x in d["by_department"]} == {"HR": 2, "Finance": 1, "Sales": 1}
    imp = cp.db.scalar(select(CopilotImport))
    f = cp.db.get(FileObject, imp.file_id)
    assert imp.sha256 == f.sha256 == hashlib.sha256(LICENCES.encode()).hexdigest() and f.engagement_id == cp.engagement.id
    assert d["imports"][0]["sha256"] == imp.sha256 and d["imports"][0]["kind_label"] == "Copilot licence and usage report"
    assert cp.client.get(f"/api/v1/files/{imp.file_id}").content == LICENCES.encode()


def test_column_checks_name_what_is_missing(cp):
    cp.as_(cp.auditor)
    r = upload(cp, "purview_oversharing", "Site,Owner\nHR,someone\n")
    assert r.status_code == 422
    assert "Sensitive items" in r.json()["errors"][0]["message"]
    r = upload(cp, "licence_usage", "Name,Team\nAna,HR\n")
    assert r.status_code == 422 and "User principal name" in r.json()["errors"][0]["message"]
    assert upload(cp, "unknown_kind", "x").status_code == 404
    assert cp.db.scalar(select(CopilotImport)) is None and cp.db.scalar(select(FileObject)) is None  # nothing kept from a refused file
    assert cp.client.post(f"{cp.url}/imports/licence_usage", files={"file": ("notes.txt", b"hello", "text/plain")}).status_code == 422


def test_site_risk_list_from_purview_and_sharepoint_reports(cp):
    cp.as_(cp.auditor)
    assert upload(cp, "purview_oversharing", PURVIEW).status_code == 200
    d = upload(cp, "sharepoint_permissions", SAM).json()
    sites = {s["name"]: s for s in d["sites"]}
    assert [s["name"] for s in d["sites"]][:2] == ["HR · Candidate files", "Finance · Payroll archive"]  # high risk first
    assert sites["HR · Candidate files"]["risk"] == "high" and sites["HR · Candidate files"]["sensitive_items"] == 2140 and sites["HR · Candidate files"]["label_coverage"] == 12
    assert sites["Finance · Payroll archive"]["risk"] == "high" and sites["Finance · Payroll archive"]["sharing"] == "anyone_link"  # merged by URL, latest sharing
    assert sites["Sales · Client contracts"]["risk"] == "medium" and sites["Marketing · Public assets"]["risk"] == "low"
    assert sites["Board papers"]["sources"] == ["sharepoint_permissions"] and len(d["sites"]) == 5
    assert d["summary"]["high_risk_sites"] == 2
    # the oversharing control holds both reports as evidence
    ctl = next(c for c in d["controls"] if c["key"] == "oversharing_report")
    assert len(ctl["evidence"]) == 2

    # actions, owner and status; a re-import keeps them
    hr = sites["HR · Candidate files"]["id"]
    r = cp.client.put(f"{cp.url}/sites/{hr}", json={"action": "restrict_discovery", "action_owner": "HR IT", "status": "in_progress"})
    assert r.status_code == 200 and next(x for x in r.json()["sites"] if x["id"] == hr)["action_label"] == "Restrict discovery"
    assert cp.client.put(f"{cp.url}/sites/{hr}", json={"action": "delete_everything"}).status_code == 422
    upload(cp, "purview_oversharing", PURVIEW)
    site = next(s for s in cp.client.get(cp.url).json()["sites"] if s["id"] == hr)
    assert site["action"] == "restrict_discovery" and site["status"] == "in_progress"
    # export is formula-safe
    csv = cp.client.get(f"{cp.url}/sites.csv")
    assert csv.status_code == 200 and csv.text.splitlines()[0].startswith("Site,URL,Owner")


def test_formula_cells_are_neutralised_in_the_export(cp):
    cp.as_(cp.auditor)
    evil = "Site name,Sensitive items,Sharing scope\n=HYPERLINK(\"http://x\"),5,Everyone\n"
    assert upload(cp, "purview_oversharing", evil).status_code == 200
    body = cp.client.get(f"{cp.url}/sites.csv").text
    assert "'=HYPERLINK" in body


def test_rollout_waves_gate_on_sites_and_controls(cp):
    cp.as_(cp.auditor)
    d = upload(cp, "purview_oversharing", PURVIEW).json()
    sites = {s["name"]: s["id"] for s in d["sites"]}
    r = cp.client.post(f"{cp.url}/waves", json={"name": "Pilot", "groups": "IT, Compliance", "user_count": 20, "planned_on": "2026-12-01", "gate_control_keys": ["pilot_group"]})
    assert r.status_code == 200, r.text
    w = cp.client.post(f"{cp.url}/waves", json={"name": "Wave 2", "groups": "HR, Finance", "user_count": 60, "planned_on": "2027-01-15",
                                                "gate_site_ids": [sites["HR · Candidate files"], sites["Finance · Payroll archive"]], "gate_control_keys": ["dlp"]}).json()
    waves = {x["name"]: x for x in w["waves"]}
    assert waves["Pilot"]["gate"] == "hold" and waves["Pilot"]["gate_text"] == "Hold · Pilot group defined"
    assert waves["Wave 2"]["gate_text"] == "Hold · 2 sites open, DLP for Copilot on labelled content"
    cp.client.put(f"{cp.url}/controls/pilot_group", json={"status": "done"})
    for name in ("HR · Candidate files", "Finance · Payroll archive"):
        cp.client.put(f"{cp.url}/sites/{sites[name]}", json={"status": "done"})
    cp.client.put(f"{cp.url}/controls/dlp", json={"status": "not_applicable", "note": "Covered by tenant-wide DLP"})
    waves = {x["name"]: x for x in cp.client.get(cp.url).json()["waves"]}
    assert waves["Pilot"]["gate_text"] == "Go" and waves["Wave 2"]["gate"] == "go"
    # a manual hold wins; gates must name this workspace's sites and controls
    wid = waves["Wave 2"]["id"]
    assert cp.client.put(f"{cp.url}/waves/{wid}", json={"hold_note": "Works council review"}).json()["waves"][1]["gate_text"] == "Hold · Works council review"
    assert cp.client.put(f"{cp.url}/waves/{wid}", json={"gate_control_keys": ["nope"]}).status_code == 422
    assert cp.client.delete(f"{cp.url}/waves/{wid}").status_code == 200
    assert [x["name"] for x in cp.client.get(cp.url).json()["waves"]] == ["Pilot"]


def test_controls_with_evidence_and_the_register_entry(cp):
    cp.as_(cp.auditor)
    upload(cp, "licence_usage", LICENCES)
    r = cp.client.post(f"{cp.url}/controls/usage_policy/evidence", files={"file": ("policy.pdf", b"policy v1", "application/pdf")})
    assert r.status_code == 200
    ctl = next(c for c in r.json()["controls"] if c["key"] == "usage_policy")
    assert ctl["evidence"][0]["sha256"] == hashlib.sha256(b"policy v1").hexdigest()
    assert cp.client.put(f"{cp.url}/controls/usage_policy", json={"status": "done"}).json()["summary"]["controls_ready"] == 1
    assert cp.client.put(f"{cp.url}/controls/usage_policy", json={"status": "maybe"}).status_code == 422
    # create the Copilot entry in the client's register
    r = cp.client.post(f"{cp.url}/register", json={})
    assert r.status_code == 200, r.text
    d = r.json()
    s = cp.db.get(RegisterSystem, d["register_entry"]["id"])
    assert s.organization_id == cp.org.id and s.name == "Microsoft 365 Copilot" and s.type == "genai_chat_tool" and s.sourcing == "vendor" and s.user_count == 4
    assert next(c for c in d["controls"] if c["key"] == "register_entry")["status"] == "done"
    assert cp.client.post(f"{cp.url}/register", json={}).json()["register_entry"]["id"] == s.id  # never a second entry
    # or link an existing entry instead (only the client's own)
    other = RegisterSystem(organization_id=cp.other.id, reference="AIS-001", name="Their Copilot", type="genai_chat_tool", sourcing="vendor")
    mine = RegisterSystem(organization_id=cp.org.id, reference="AIS-009", name="Copilot (already listed)", type="genai_chat_tool", sourcing="vendor")
    cp.db.add_all([other, mine])
    cp.db.commit()
    assert cp.client.post(f"{cp.url}/register", json={"register_system_id": other.id}).status_code == 404
    assert cp.client.post(f"{cp.url}/register", json={"register_system_id": mine.id}).json()["register_entry"]["name"] == "Copilot (already listed)"


def test_readiness_report_pdf(cp):
    cp.as_(cp.auditor)
    upload(cp, "licence_usage", LICENCES)
    upload(cp, "purview_oversharing", PURVIEW)
    r = cp.client.post(f"{cp.url}/report")
    assert r.status_code == 200, r.text
    fid = r.json()["report"]["file_id"]
    pdf = cp.client.get(f"/api/v1/files/{fid}")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    from pypdf import PdfReader

    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Copilot readiness" in text and "HR · Candidate files" in text and "Governix" not in text
    # the client's CAICO can download the readiness report
    cp.as_(cp.caico)
    assert cp.client.get(f"/api/v1/files/{fid}").status_code == 200


def test_client_view_and_permissions(cp):
    cp.as_(cp.auditor)
    d = upload(cp, "purview_oversharing", PURVIEW).json()
    hr = d["sites"][0]["id"]
    imp_file = cp.db.scalar(select(CopilotImport)).file_id
    cp.as_(cp.caico)
    lst = cp.client.get("/api/v1/copilot").json()
    assert [x["engagement_id"] for x in lst] == [cp.engagement.id]
    d = cp.client.get(cp.url).json()
    assert d["client_view"] is True and d["can_manage"] is False and d["can_update_sites"] is True and len(d["sites"]) == 4
    # the client works remediation (owner, status, note) but not the risk or the action
    r = cp.client.put(f"{cp.url}/sites/{hr}", json={"status": "done", "action_owner": "HR IT"})
    assert r.status_code == 200
    assert cp.client.put(f"{cp.url}/sites/{hr}", json={"risk_override": "low"}).status_code == 403
    assert upload(cp, "licence_usage", LICENCES).status_code == 403
    assert cp.client.post(f"{cp.url}/waves", json={"name": "x"}).status_code == 403
    assert cp.client.get(f"/api/v1/files/{imp_file}").status_code == 404  # raw admin exports stay with Futran
    cp.as_(cp.client_admin)
    assert cp.client.get(cp.url).status_code == 403
    cp.as_(cp.other_caico)
    assert cp.client.get(cp.url).status_code == 404 and cp.client.get("/api/v1/copilot").json() == []
    cp.as_(cp.outsider)
    assert cp.client.get(cp.url).status_code == 404
