"""The forms and templates export (11-10 feedback X1): `python -m scripts.export_forms <out_dir>` writes every form and
template a person fills in or receives, from the application's own seeds and generators, into a Client folder and a
Futran folder. Nothing confidential (answer keys, auditor-only questions, scoring guidance, internal notes) may reach
the Client folder."""
import csv
import io
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def tree(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("forms")
    run = subprocess.run([sys.executable, "-m", "scripts.export_forms", str(out)], cwd=BACKEND, capture_output=True, text=True, timeout=300,
                         env={"PYTHONPATH": str(BACKEND), "PATH": "/usr/bin:/bin", "DATABASE_URL": "sqlite:////nonexistent/never-used.db"})
    assert run.returncode == 0, run.stderr[-4000:]
    root = out / "Forms and templates"
    assert root.is_dir()
    return root


def _files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file())


def _text(p: Path) -> str:
    """Everything a reader can see in the file."""
    if p.suffix == ".docx":
        import docx

        d = docx.Document(str(p))
        parts = [para.text for para in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts += [c.text for c in row.cells]
        return "\n".join(parts)
    if p.suffix == ".xlsx":
        import openpyxl

        wb = openpyxl.load_workbook(str(p))
        return "\n".join(str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value is not None)
    return p.read_text(encoding="utf-8")


def test_top_level_tree(tree):
    assert sorted(p.name for p in tree.iterdir()) == ["Client", "Futran"]
    client = {p.name for p in (tree / "Client").iterdir()}
    assert {"README.md", "Home", "Audit", "AI governance", "People and training", "Data and integrations", "Email"} <= client
    futran = {p.name for p in (tree / "Futran").iterdir()}
    assert {"README.md", "Home and work", "Business", "Administration", "Law library"} <= futran
    assert {"Sales"} <= futran and {"Before the engagement"} <= client
    # every file sits at <side>/<menu group>/<screen>/<file> (a workspace reached from a screen adds one folder),
    # apart from the two READMEs
    for side in ("Client", "Futran"):
        for f in _files(tree / side):
            rel = f.relative_to(tree / side)
            assert rel.name == "README.md" and len(rel.parts) == 1 or len(rel.parts) == 3 or rel.parts[:2] == ("Home and work", "Clients") and len(rel.parts) == 4, rel


KEY_FILES = [
    "Client/People and training/People/User list template.csv",
    "Client/People and training/People/Department list template.csv",
    "Client/People and training/People/Departments and people workbook.xlsx",
    "Client/AI governance/AI systems/AI system register import template.csv",
    "Client/AI governance/AI systems/AI system register import template.xlsx",
    "Client/AI governance/AI systems/AI system questionnaire.xlsx",
    "Client/AI governance/AI systems/AI system questionnaire.docx",
    "Client/People and training/Attestation/AI use attestation form.docx",
    "Client/AI governance/New AI projects/New AI project intake form.docx",
    "Client/Data and integrations/Bias test data/Bias calculator data template.csv",
    "Client/Data and integrations/Customer questionnaires/Customer questionnaire example.xlsx",
    "Client/Audit/Documents/Pre-audit document request list.xlsx",
    "Client/Email/Groups/Group email templates.md",
    "Futran/AI governance/AI systems/AI system questionnaire with auditor questions and scoring.xlsx",
    "Futran/People and training/AI literacy training/AI literacy quiz answer keys.xlsx",
    "Futran/Administration/Templates/Engagement letter and scope (template source).md",
    "Futran/Administration/Templates/AI governance audit report (template source).md",
    "Futran/Home and work/Clients/Engagement letter and scope (example).docx",
    "Futran/Home and work/Clients/Intro letter (example).docx",
    "Futran/Business/Client alerts/Client alert rules.xlsx",
    "Futran/Administration/Email and groups/Platform email templates.md",
    # Release 2
    "Futran/Sales/Price list/Price list import template.xlsx",
    "Futran/Sales/Price list/Price list starter items (export).xlsx",
    "Futran/Sales/Price list/Price list packages.xlsx",
    "Futran/Sales/Scoping/Scoping question bank (with internal questions).xlsx",
    "Futran/Sales/Scoping/Scoping question bank (with internal questions).md",
    "Futran/Sales/Scoping/Scoping mapping rules.md",
    "Futran/Sales/Scoping/Scoping questionnaire emails.md",
    "Futran/Sales/Proposals/Proposal section templates.md",
    "Futran/Sales/Proposals/Sample proposal (Governed package).pdf",
    "Futran/Sales/Proposals/Sample proposal (Governed package).docx",
    "Futran/Administration/Service templates/Service templates.xlsx",
    "Futran/Administration/Service templates/Agent Assure 15-point check (blank).xlsx",
    "Futran/Administration/Billing export/Billing export template.csv",
    "Futran/Home and work/Clients/Copilot readiness/Copilot licence and usage report template.csv",
    "Futran/Home and work/Clients/Copilot readiness/Purview oversharing assessment template.csv",
    "Futran/Home and work/Clients/Copilot readiness/SharePoint permission report template.csv",
    "Futran/Home and work/Clients/Copilot readiness/Copilot readiness import column guide.md",
    "Futran/Home and work/Clients/Copilot readiness/Copilot readiness controls checklist.xlsx",
    "Futran/Home and work/Clients/EU AI Act/EU AI Act obligations checklist.xlsx",
    "Futran/Home and work/Clients/EU AI Act/Annex IV technical documentation tracker.xlsx",
    "Futran/Home and work/Clients/EU AI Act/Fundamental rights impact assessment (FRIA) template.docx",
    "Futran/Home and work/Clients/Agent Assure/AgentWarden licence sync template.csv",
    "Futran/Home and work/Clients/Agent Assure/Agent Assure record form.md",
    "Futran/Home and work/Clients/Discovery import/Discovery import column guide.md",
    "Futran/Home and work/Clients/Client hierarchy/End-client import template.csv",
    "Client/Before the engagement/Scoping questionnaire link/Scoping questionnaire.docx",
    "Client/Before the engagement/Scoping questionnaire link/Scoping questionnaire email.md",
    "Client/Data and integrations/Integrations/Discovery import column guide.md",
    "Client/AI governance/Copilot readiness/Copilot readiness site list fields.md",
    "Client/AI governance/AI systems/Agent Assure record fields.md",
]


@pytest.mark.parametrize("rel", KEY_FILES)
def test_key_files(tree, rel):
    assert (tree / rel).is_file(), rel


def test_ten_policy_templates_and_five_training_modules(tree):
    policies = list((tree / "Client/AI governance/Policies").glob("*.docx"))
    assert len(policies) == 10
    from app.policies.templates import library

    titles = {t.name for t in library().values()}
    assert {p.stem.replace(" (template)", "") for p in policies} == titles
    assert len(list((tree / "Client/People and training/AI literacy training").glob("*.docx"))) == 5
    assert len(list((tree / "Futran/People and training/AI literacy training").glob("*.docx"))) == 5


def test_every_workbook_and_document_opens(tree):
    import docx
    import openpyxl

    n = 0
    for f in _files(tree):
        if f.suffix == ".xlsx":
            assert openpyxl.load_workbook(str(f)).worksheets, f
            n += 1
        elif f.suffix == ".docx":
            assert docx.Document(str(f)).paragraphs, f
            n += 1
        elif f.suffix == ".csv":
            assert next(csv.reader(io.StringIO(f.read_text(encoding="utf-8-sig")))), f
    assert n >= 30


def test_readmes_list_every_file(tree):
    for side in ("Client", "Futran"):
        text = (tree / side / "README.md").read_text(encoding="utf-8")
        assert text.startswith("---\n") and "\ntags:" in text.split("---")[1]
        for f in _files(tree / side):
            if f.name != "README.md":
                assert str(f.relative_to(tree / side)) in text, f


def _client_text(tree) -> str:
    return "\n".join(_text(f) for f in _files(tree / "Client"))


def test_client_folder_holds_no_answer_keys(tree):
    from app.training.modules import library

    client = _client_text(tree)
    assert not re.search(r"answer key|correct answer", client, re.I)
    for m in library().values():
        for q in m["quiz"]:
            assert q["explanation"] not in client, q["id"]
    futran = "\n".join(_text(f) for f in _files(tree / "Futran/People and training/AI literacy training"))
    first = next(iter(library().values()))["quiz"][0]
    assert first["explanation"] in futran


def test_client_folder_holds_no_auditor_questions_or_scoring(tree):
    data = yaml.safe_load((BACKEND / "seeds/question_bank.yaml").read_text())
    client = _client_text(tree)
    auditor = [q for s in data["sections"] for q in s["questions"] if q.get("respondent") == "auditor"]
    assert auditor
    for q in auditor:
        assert f"{q['code']} " not in client and f"\n{q['code']}\n" not in client, q["code"]
    for s in data["sections"]:
        if s.get("note"):
            assert s["note"] not in client, s["code"]  # auditor guidance per section
    assert "Scoring method" not in client and "knockout" not in client.lower()
    import openpyxl

    for f in _files(tree / "Client"):
        if f.suffix == ".xlsx":
            assert not {"Scoring method", "Section guidance", "Audit checklists"} & set(openpyxl.load_workbook(str(f)).sheetnames), f
    full = tree / "Futran/AI governance/AI systems/AI system questionnaire with auditor questions and scoring.xlsx"
    assert auditor[0]["label"] in _text(full)
    assert {"Scoring method", "Section guidance", "Audit checklists"} <= set(openpyxl.load_workbook(str(full)).sheetnames)


def test_client_folder_holds_no_futran_only_templates(tree):
    client = {f.name for f in _files(tree / "Client")}
    assert not any("template source" in n for n in client)
    assert not any(n.startswith(("Lead Auditor declaration", "AI governance audit report", "Platform email templates", "Client alert rules")) for n in client)


def test_generated_from_the_application(tree):
    """Spot checks that the files come from the live generators, not copies."""
    from app.register.seeding import HEADER
    from app.tenancy.csv_import import USER_HEADER

    reg = next(csv.reader(io.StringIO((tree / "Client/AI governance/AI systems/AI system register import template.csv").read_text(encoding="utf-8-sig"))))
    assert reg == HEADER
    users = next(csv.reader(io.StringIO((tree / "Client/People and training/People/User list template.csv").read_text(encoding="utf-8-sig"))))
    assert users == USER_HEADER
    from app.biascalc.dataset import parse

    parsed = parse((tree / "Client/Data and integrations/Bias test data/Bias calculator data template.csv").read_bytes())
    assert parsed.report["error_count"] == 0 and parsed.report["rows_valid"] >= 4


# ---------------------------------------------------------------- Release 2


def _header(p: Path) -> list[str]:
    return next(csv.reader(io.StringIO(p.read_text(encoding="utf-8-sig"))))


def test_price_list_files_read_back_in_the_importer(tree):
    import openpyxl

    from app.catalog import io as cio
    from app.catalog.seed import STARTER_ITEMS

    folder = tree / "Futran/Sales/Price list"
    rows, errors = cio.parse_workbook((folder / "Price list import template.xlsx").read_bytes())
    assert rows == [] and errors == []
    ws = openpyxl.load_workbook(str(folder / "Price list import template.xlsx"))["Master Price List"]
    assert [c.value for c in ws[1]] == [h for _, h in cio.COLUMNS]
    rows, errors = cio.parse_workbook((folder / "Price list starter items (export).xlsx").read_bytes())
    assert errors == [] and {r["code"] for r in rows} == {i["code"] for i in STARTER_ITEMS}


def test_scoping_bank_and_rules_are_complete_in_the_futran_copy(tree):
    from app.scoping.bank import STARTER
    from app.scoping.rules import SEED

    folder = tree / "Futran/Sales/Scoping"
    bank_text = _text(folder / "Scoping question bank (with internal questions).xlsx")
    md = _text(folder / "Scoping question bank (with internal questions).md")
    for q in STARTER:
        assert q["code"] in bank_text and q["code"] in md, q["code"]
    assert any(q.get("internal_only") for q in STARTER)
    rules_md = _text(folder / "Scoping mapping rules.md")
    for r in SEED:
        assert f"{r['code']} " in rules_md and r["line_code"] in rules_md, r["code"]
    body = rules_md.split("\n## ", 1)[1]
    assert '"op"' not in body and '{"' not in body  # conditions and quantities written as words, not JSON


def test_client_scoping_questionnaire_has_every_client_question(tree):
    from app.scoping.bank import STARTER

    text = _text(tree / "Client/Before the engagement/Scoping questionnaire link/Scoping questionnaire.docx")
    for q in STARTER:
        if not q.get("internal_only"):
            assert (q.get("client_label") or q["label"]) in text, q["code"]


def test_proposal_templates_and_sample(tree):
    from app.proposals.templates import STARTER

    folder = tree / "Futran/Sales/Proposals"
    text = _text(folder / "Proposal section templates.md")
    for _key, title, _body in STARTER:
        assert f"## {title}" in text
    assert (folder / "Sample proposal (Governed package).pdf").read_bytes().startswith(b"%PDF")
    assert "Pricing" in _text(folder / "Sample proposal (Governed package).docx")


def test_service_templates_and_agent_assure_list(tree):
    import openpyxl

    from app.assurance.models import CHECK_POSITIONS
    from app.servicetemplates.types import B6_ENGAGEMENT_TYPES, ENGAGEMENT_TYPES

    folder = tree / "Futran/Administration/Service templates"
    for t in B6_ENGAGEMENT_TYPES:
        assert (folder / f"Service template - {ENGAGEMENT_TYPES[t].replace('/', '-')}.md").is_file(), t
    ws = openpyxl.load_workbook(str(folder / "Agent Assure 15-point check (blank).xlsx")).worksheets[0]
    assert ws.max_row == CHECK_POSITIONS + 1


def test_import_templates_match_the_importers(tree):
    from app.assurance.service import WARDEN_COLUMNS
    from app.commercial.plans import COLUMNS as BILLING
    from app.connectors import manual_import as mi
    from app.copilot_readiness import imports as cimp
    from app.hierarchy.service import parse_end_clients

    for t in mi.EXPORT_TYPES.values():
        for side, folder in (("Futran", "Home and work/Clients/Discovery import"), ("Client", "Data and integrations/Integrations")):
            header = _header(tree / side / folder / f"{t.label} template.csv")
            assert all(mi.guess_mapping(t, header).values()), (side, t.key)
    for kind, spec in cimp.KINDS.items():
        header = [cimp._norm(h) for h in _header(tree / f"Futran/Home and work/Clients/Copilot readiness/{spec['label']} template.csv")]
        assert all(v is not None for v in cimp.columns(kind, header).values()), kind
    warden = [h.lower() for h in _header(tree / "Futran/Home and work/Clients/Agent Assure/AgentWarden licence sync template.csv")]
    assert all(any(a.replace("_", " ") in warden for a in names) for names in WARDEN_COLUMNS.values())
    rows, errors = parse_end_clients((tree / "Futran/Home and work/Clients/Client hierarchy/End-client import template.csv").read_bytes())
    assert rows and not errors
    assert _header(tree / "Futran/Administration/Billing export/Billing export template.csv") == BILLING


def test_eu_ai_act_files(tree):
    from app.euaiact import rules

    folder = tree / "Futran/Home and work/Clients/EU AI Act"
    obligations = _text(folder / "EU AI Act obligations checklist.xlsx")
    assert all(o["title"] in obligations for o in rules.data()["obligations"])
    assert all(a["label"] in _text(folder / "Annex IV technical documentation tracker.xlsx") for a in rules.data()["annex_iv"])
    assert all(q["label"] in _text(folder / "Fundamental rights impact assessment (FRIA) template.docx") for q in rules.data()["fria"])


def test_client_folder_holds_no_internal_scoping_questions_prices_or_answer_keys(tree):
    from app.catalog.seed import STARTER_ITEMS
    from app.connectors.manual_import import FINDINGS
    from app.scoping.bank import SECTION_INTROS, SECTION_LABELS, STARTER

    client = _client_text(tree)
    # internal-only scoping questions: code, wording and help never reach the client
    for q in STARTER:
        if q.get("internal_only"):
            assert q["code"] not in client, q["code"]
            assert not re.search(rf"^\W*{re.escape(q['label'])}\W*$", client, re.M), q["label"]
        for text in (q.get("help"), q.get("unknown_assumption")):  # rep help and pricing assumptions are written for Futran
            if text:
                assert text not in client, q["code"]
    assert SECTION_LABELS["RF"] not in client and SECTION_INTROS["RF"] not in client
    # no prices, price list codes or sales findings
    assert not re.search(r"\$\s?\d|list price|unit price", client, re.I)
    for item in STARTER_ITEMS:
        assert not re.search(rf"(?<![\w-]){re.escape(item['code'])}(?![\w-])", client), item["code"]
    for service, _kind in FINDINGS.values():
        assert service not in client
    # no answer keys
    assert not re.search(r"answer key|correct answer", client, re.I)
