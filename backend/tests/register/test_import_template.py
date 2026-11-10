"""11-03 C7: the register's import template has the fields the system needs, in the form's order, with required columns
marked and allowed values listed (an instructions sheet in the workbook). Old templates still import."""
import csv
import io

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import select

from app.register.models import RegisterSystem, RegisterSystemAction, RegisterSystemLaw
from app.register.service import data_row
from app.regmaster.seed import find_law, seed_regmaster

FORM_ORDER = ["Name *", "Type *", "Built or bought *", "Department *", "Used by departments", "Stage", "Purpose", "Who uses it", "Users", "Number of users",
              "System owner email", "Vendor", "Underlying AI provider", "Model or algorithm", "Model version", "Algorithm type", "Hosting", "Vendor trains on our data",
              "Vendor documents received", "Agent actions and tools", "Other action or tool", "How much it acts on its own", "Runtime controls", "Pre-release testing",
              "Data used", "Whose data", "Was consent obtained?", "Consent date or version", "Retention period", "Data leaves the country?",
              "Where it runs: country", "Where it runs: state or region", "Where it runs: city", "Where the people whose data it uses are", "Laws that apply",
              "Effect on decisions about people", "Next bias test due"]


def _upload(client, name, data, kind="text/csv"):
    r = client.post("/api/v1/register/import", files={"file": (name, data, kind)})
    assert r.status_code == 200, r.text
    return r.json()


def _row(**kw) -> dict:
    return {h: "" for h in FORM_ORDER} | kw


def _csv(rows: list[dict]) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(FORM_ORDER)
    for r in rows:
        w.writerow([r.get(h, "") for h in FORM_ORDER])
    return out.getvalue().encode()


def test_csv_template_has_the_form_fields_in_order(client, db, reg):
    reg.as_(reg.admin)
    r = client.get("/api/v1/register/import-template.csv")
    assert r.status_code == 200
    rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿"))))
    assert rows[0] == FORM_ORDER
    assert rows[1][0] == "Résumé screening" and rows[1][1] == "Vendor app with AI"


def test_xlsx_template_has_instructions_allowed_values_and_dropdowns(client, db, reg):
    reg.as_(reg.admin)
    r = client.get("/api/v1/register/import-template.xlsx")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames[:2] == ["AI systems", "Instructions"]
    ws = wb["AI systems"]
    assert [c.value for c in ws[1]] == FORM_ORDER
    ins = {row[0]: row for row in wb["Instructions"].iter_rows(min_row=2, values_only=True) if row[0]}
    assert ins["Type *"][1] == "Required" and "AI agent" in ins["Type *"][3]
    assert ins["Purpose"][1] == "Optional"
    assert "Bought from vendor" in ins["Built or bought *"][3]
    assert "The company's own data" in ins["Whose data"][3] and "semicolons" in ins["Whose data"][2]
    assert "OpenAI" in ins["Underlying AI provider"][3]
    assert "Live" not in ins["Stage"][3].split("; ")
    sqrefs = " ".join(str(dv.sqref) for dv in ws.data_validations.dataValidation)
    assert "B2" in sqrefs  # Type has a dropdown


def test_full_row_imports_every_field(client, db, reg, matrix):
    seed_regmaster(matrix)
    matrix.commit()
    reg.as_(reg.caico)
    row = _row(**{"Name *": "Interview scheduler", "Type *": "AI agent", "Built or bought *": "Bought from vendor", "Department *": "Human Resources",
                  "Used by departments": "Human Resources; Finance", "Stage": "In development / procurement", "Purpose": "Books interviews.", "Who uses it": "Role level",
                  "Users": "Recruiters", "Number of users": "4", "System owner email": "hana@abc.test", "Vendor": "HireBot Co.", "Underlying AI provider": "OpenAI",
                  "Model or algorithm": "GPT-5.5", "Algorithm type": "Large language model (LLM) agent", "Hosting": "Vendor cloud (US)",
                  "Vendor trains on our data": "No, contractually excluded", "Vendor documents received": "Data processing agreement; Model card or system documentation",
                  "Agent actions and tools": "Send email; Write to calendars", "Other action or tool": "Book rooms", "How much it acts on its own": "Acts on its own",
                  "Data used": "Personal information", "Whose data": "Job candidates; The company's own data", "Was consent obtained?": "Notice given",
                  "Retention period": "4 years", "Data leaves the country?": "No", "Where it runs: country": "US", "Where it runs: state or region": "NY",
                  "Where it runs: city": "New York", "Where the people whose data it uses are": "US-IL; New York, US-NY; DE", "Laws that apply": "NYC Local Law 144",
                  "Effect on decisions about people": "Supports a decision a person makes", "Next bias test due": "2027-01-31"})
    body = _upload(client, "systems.csv", _csv([row]))
    assert body == {"created": 1, "errors": []}
    s = db.scalar(select(RegisterSystem).where(RegisterSystem.name == "Interview scheduler"))
    assert s.type == "agent" and s.stage == "in_development" and s.department_id == reg.hr.id and s.department_ids == [reg.hr.id, reg.fin.id]
    assert s.users_scope == "role" and s.user_count == 4 and s.owner_user_id == reg.hr_user.id and s.ai_provider == "openai" and s.model_name == "GPT-5.5"
    assert s.autonomy == "autonomous" and s.vendor_documents == ["dpa", "model_card"] and str(s.bias_next_due) == "2027-01-31"
    assert s.run_location == {"country": "US", "region": "US-NY", "city": "New York"}
    assert s.data_locations == [{"country": "US", "region": "US-IL"}, {"country": "US", "region": "US-NY", "city": "New York"}, {"country": "DE"}]
    d = data_row(db, s)
    assert d.data_subjects == ["candidates", "company"] and d.consent_basis == "notice_only" and d.cross_border == "no"
    acts = {a.action_code for a in db.scalars(select(RegisterSystemAction).where(RegisterSystemAction.register_system_id == s.id, RegisterSystemAction.deleted_at.is_(None)))}
    assert acts == {"send_email", "write_calendar", "other"}
    law = find_law(db, "US-NYC", "Local Law 144")
    assert db.scalar(select(RegisterSystemLaw.regulation_id).where(RegisterSystemLaw.register_system_id == s.id)) == law.id


def test_xlsx_upload_reads_the_systems_sheet(client, db, reg):
    reg.as_(reg.hr_lead)
    tpl = load_workbook(io.BytesIO(client.get("/api/v1/register/import-template.xlsx").content))
    ws = tpl["AI systems"]
    ws.append([{"Name *": "Shift planner", "Type *": "In-house model", "Built or bought *": "Built in-house", "Department *": "Human Resources"}.get(h, None) for h in FORM_ORDER])
    buf = io.BytesIO()
    tpl.save(buf)
    body = _upload(client, "systems.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert body == {"created": 1, "errors": []}
    assert db.scalar(select(RegisterSystem.stage).where(RegisterSystem.name == "Shift planner")) == "proposed"


def test_old_template_still_imports(client, db, reg):
    reg.as_(reg.hr_lead)
    old = ("name,type,sourcing,department,stage,purpose,vendor,ai_provider,model_name,decision_impact,owner_email\n"
           "Chatbot,AI agent,in_house,Human Resources,proposed,Answers questions,,openai,GPT-4.1,none,\n")
    assert _upload(client, "old.csv", old.encode()) == {"created": 1, "errors": []}


def test_bad_values_are_listed_and_nothing_is_imported(client, db, reg, matrix):
    reg.as_(reg.hr_lead)
    rows = [_row(**{"Name *": "A", "Type *": "AI agent", "Built or bought *": "Bought from vendor", "Department *": "Human Resources", "Whose data": "Martians",
                    "Laws that apply": "No such law", "Where the people whose data it uses are": "ZZ-99", "Used by departments": "Marketing"})]
    body = _upload(client, "systems.csv", _csv(rows))
    assert body["created"] == 0
    fields = {e["field"] for e in body["errors"]}
    assert {"Whose data", "Laws that apply", "Where the people whose data it uses are", "Used by departments"} <= fields
    assert db.scalar(select(RegisterSystem.id)) is None


def test_missing_required_column_is_a_header_error(client, db, reg):
    reg.as_(reg.hr_lead)
    body = _upload(client, "systems.csv", b"Name *,Purpose\nX,Y\n")
    assert body["created"] == 0 and body["errors"][0]["row"] == 1 and "Type" in body["errors"][0]["message"]


def test_unknown_column_is_ignored_with_a_warning(client, db, reg):
    reg.as_(reg.hr_lead)
    body = _upload(client, "systems.csv", ("Name *,Type *,Built or bought *,Department *,Colour\nX,AI agent,Bought from vendor,Human Resources,Red\n").encode())
    assert body["created"] == 1 and body["errors"] == [] and "Colour" in body["warnings"][0]["message"]
