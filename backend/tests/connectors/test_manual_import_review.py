"""G-05 review fixes: the monitoring check survives manual imports, clients never see sales data, malformed files are
refused plainly, expense/proxy imports keep no unmatched spending text, import evidence downloads, archived engagements
take no imports."""
import json

from sqlalchemy import select

from app.connectors.models import DiscoveryImport
from tests.connectors.test_manual_import import COPILOT, ENTRA, EXPENSE, PROXY, _base, _post

SALES = ("service", "service_kind", "opportunity_id")


def test_the_undeclared_tool_check_still_runs_and_reports_connector_findings_after_a_manual_import(w):
    from app.connectors.models import Connector, DiscoveredTool
    from app.connectors.monitor_checks import undeclared_ai_tool
    from app.core.clock import utcnow

    conn = Connector(organization_id=w.org.id, type="entra_id", status="connected", scopes=[], verified_domains=[])
    w.db.add(conn)
    w.db.flush()
    w.db.add(DiscoveredTool(organization_id=w.org.id, connector_id=conn.id, vendor_key="otter", vendor="Otter", product="Otter.ai", signal="sso_app",
                            department_key="unknown", user_count=3, first_seen=utcnow(), last_seen=utcnow(), status="new"))
    w.db.commit()
    w.as_(w.auditor)
    assert _post(w, "imports", "copilot_usage", COPILOT).status_code == 200
    out = undeclared_ai_tool(w.db, w.org)
    otter = next(o for o in out if o.object_label.startswith("Otter.ai"))
    assert otter.status == "failed" and "Microsoft Entra ID" in otter.detail
    copilot = next(o for o in out if o.object_label.startswith("Copilot"))
    assert "Copilot licence and usage report" in copilot.detail


def test_a_client_admin_sees_only_their_own_imports_and_no_sales_fields(w):
    w.as_(w.auditor)
    assert _post(w, "imports", "copilot_usage", COPILOT).status_code == 200  # Futran's import, with an X-04 finding
    w.as_(w.admin)
    r = w.client.post("/api/v1/integrations/imports", data={"export_type": "copilot_usage"}, files={"file": ("mine.csv", COPILOT, "text/csv")})
    assert r.status_code == 200, r.text
    body = json.dumps(r.json())
    assert all(f'"{k}"' not in body for k in SALES) and "X-04" not in body
    page = w.client.get("/api/v1/integrations/import").json()
    assert [i["filename"] for i in page["imports"]] == ["mine.csv"]
    text = json.dumps(page)
    assert all(f'"{k}"' not in text for k in SALES) and "X-04" not in text and "Copilot governance" not in text


def test_random_bytes_and_an_oversized_cell_are_refused_with_a_plain_message(w):
    import os

    w.as_(w.auditor)
    r = _post(w, "import/analyse", "entra_apps", b"App name,Users\n" + os.urandom(2000) + b"\x00\x00\n", name="junk.csv")
    assert r.status_code == 422, r.text
    big = b"Application name,Users\n\"" + b"A" * (130 * 1024) + b"\",1\n"
    r = _post(w, "import/analyse", "entra_apps", big, name="big.csv")
    assert r.status_code == 422, r.text
    assert "could not be read" in r.json()["errors"][0]["message"]


def test_expense_and_proxy_imports_keep_no_unmatched_spending_text(w):
    data = EXPENSE + b"Ana Ruiz,ana@abccorp.example,Recruiting,EXPEDIA TRAVEL AGENT FEE - ANA HONEYMOON,900.00\nBen Ok,ben@abccorp.example,Recruiting,CVS PHARMACY ASSISTANT REFILL,12.00\n"
    w.as_(w.auditor)
    a = _post(w, "import/analyse", "expense", data).json()
    assert a["unmatched"] == [] and a["unmatched_count"] == 3
    assert "HONEYMOON" not in json.dumps(a) and "PHARMACY" not in json.dumps(a)
    imp = _post(w, "imports", "expense", data).json()
    row = w.db.get(DiscoveryImport, imp["id"])
    assert row.unmatched == [] and row.unmatched_count == 3
    assert "HONEYMOON" not in json.dumps(w.client.get(f"{_base(w)}/import").json())
    p = _post(w, "imports", "proxy", PROXY).json()
    assert w.db.get(DiscoveryImport, p["id"]).unmatched == []


def test_import_evidence_downloads_for_the_importing_client_admin_and_the_assigned_auditor(w):
    w.as_(w.admin)
    imp = w.client.post("/api/v1/integrations/imports", data={"export_type": "entra_apps"}, files={"file": ("apps.csv", ENTRA, "text/csv")}).json()
    fid = imp["evidence_file_id"]
    assert w.client.get(f"/api/v1/files/{fid}").status_code == 200
    w.as_(w.auditor)
    assert w.client.get(f"/api/v1/files/{fid}").status_code == 200
    w.as_(w.other_auditor)
    assert w.client.get(f"/api/v1/files/{fid}").status_code == 404
    w.as_(w.other_admin)
    assert w.client.get(f"/api/v1/files/{fid}").status_code == 404
    w.as_(w.contrib)
    assert w.client.get(f"/api/v1/files/{fid}").status_code in (403, 404)


def test_an_archived_engagement_takes_no_imports(w):
    w.engagement.status = "archived"
    w.db.commit()
    w.as_(w.auditor)
    r = _post(w, "imports", "entra_apps", ENTRA)
    assert r.status_code == 409
    assert w.db.scalar(select(DiscoveryImport.id)) is None
