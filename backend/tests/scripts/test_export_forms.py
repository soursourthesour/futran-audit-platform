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
    # every file sits at <side>/<menu group>/<screen>/<file>, apart from the two READMEs
    for side in ("Client", "Futran"):
        for f in _files(tree / side):
            rel = f.relative_to(tree / side)
            assert rel.name == "README.md" and len(rel.parts) == 1 or len(rel.parts) == 3, rel


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
