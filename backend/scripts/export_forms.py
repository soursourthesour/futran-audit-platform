"""Write every form and template a person fills in or receives into a folder tree (11-10 feedback X1).

    cd backend
    python -m scripts.export_forms <out_dir>        (or: python scripts/export_forms.py <out_dir>)

writes

    <out_dir>/Forms and templates/Client/<menu group>/<screen>/<files>
    <out_dir>/Forms and templates/Futran/<menu group>/<screen>/<files>
    <out_dir>/Forms and templates/Client/README.md, Futran/README.md

Everything comes from the application's own seeds and generators, run against a throwaway in-memory SQLite database
loaded with the platform's reference data (the same loaders as `python -m app.cli seed-reference`). No real database
is opened. Folder names follow the menus in frontend/src/nav.ts. Content that clients must not see (quiz answer keys,
auditor-only questions, section guidance for auditors, scoring, Futran template sources and internal rules) is written
to the Futran folder only.
"""
from __future__ import annotations

import csv
import io
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

if __package__ in (None, ""):  # run as a file: make `app` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT_NAME = "Forms and templates"
COMPANY = "[Company name]"
DOCX_META: dict = {}

# ---------------------------------------------------------------- output


@dataclass
class Entry:
    side: str
    group: str
    screen: str
    name: str
    purpose: str


class Out:
    def __init__(self, root: Path):
        self.root = root
        self.entries: list[Entry] = []

    def write(self, side: str, group: str, screen: str, name: str, data: bytes | str, purpose: str) -> Path:
        path = self.root / side / group / screen / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            path.write_text(data, encoding="utf-8", newline="\n")
        else:
            path.write_bytes(data)
        self.entries.append(Entry(side, group, screen, name, purpose))
        return path

    def both(self, group: str, screen: str, name: str, data: bytes | str, purpose: str) -> None:
        self.write("Client", group, screen, name, data, purpose)
        self.write("Futran", group, screen, name, data, purpose)


def docx(md: str, title: str) -> bytes:
    from app.documents.docx import to_docx

    return to_docx(md, title, DOCX_META)


def xlsx(sheets: list[tuple[str, list[str], list[list], list[int]]]) -> bytes:
    """Workbook with one sheet per (title, header, rows, column widths): bold header row, wrapped text, frozen header."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)
    for title, header, rows, widths in sheets:
        ws = wb.create_sheet(title[:31])
        ws.append(header)
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F3A5F")
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        for r in rows:
            ws.append(["" if v is None else v for v in r])
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                if isinstance(cell.value, str):
                    cell.data_type = "s"  # text stays text, never a formula
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def cell(v) -> str:
    return " ".join(str(v if v is not None else "").split()).replace("|", "/")


# ---------------------------------------------------------------- database


def open_database():
    """A throwaway in-memory database holding the platform's reference data and two example client organizations."""
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.models_registry  # noqa: F401  (every domain model)
    from app.cli import _futran_org
    from app.core.models import Base
    from app.reference import LOADERS

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk_on(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    _futran_org(db)
    for _name, loader in LOADERS:
        loader(db)
    db.flush()
    return db


EXAMPLE_GEOGRAPHIES = ("US-NYC", "US-IL", "EU")


def client_orgs(db):
    """`blank`: a client with nothing entered yet, so generators give their empty templates. `example`: a client with
    employees in New York City, Illinois and the EU, so the intro letter has real laws, roles and rules to show."""
    from sqlalchemy import select

    from app.reference.models import Jurisdiction
    from app.regmaster import engine
    from app.tenancy.service import create_organization

    blank = create_organization(db, name="Your company", type="client", status="active")
    example = create_organization(db, name="Example Client Inc.", type="client", status="active", hq_city="New York", hq_state="NY", hq_country="US")
    for code in EXAMPLE_GEOGRAPHIES:
        engine.add_geography(db, example.id, db.scalar(select(Jurisdiction.id).where(Jurisdiction.code == code)), "employees", None)
    db.flush()
    return blank, example


# ---------------------------------------------------------------- People and training


def people(out: Out, db, org) -> None:
    from app.tenancy import people as ppl
    from app.tenancy.people_template import department_workbook

    g, s = "People and training", "People"
    out.write("Client", g, s, "User list template.csv", ppl.user_template(db, org),
              "CSV for adding people who need a login: name, work email, department, job title, job level and AI compliance role. Upload on People.")
    out.write("Client", g, s, "Department list template.csv", ppl.department_template(db, org),
              "CSV of departments with their head and headcount. Upload on People > Departments.")
    out.write("Client", g, s, "Departments and people workbook.xlsx", department_workbook(db, org),
              "Workbook with instructions, the department list and one sheet of people per department. Fill it in and upload it on People > Departments.")


ATTESTATION_STEPS = ("About you", "Which AI tools and agents do you use for work?", "What do you use it for?", "AI use policy")


def attestation(out: Out) -> None:
    from app.attestation import service as A

    tools = [t for t in A.TOOLS if t["kind"] == "tool"]
    agents = [t for t in A.TOOLS if t["kind"] == "agent"]

    def tool_line(t):
        extra = []
        if t.get("has_name"):
            extra.append("name required" if t.get("needs_name") else "name optional")
        if t.get("account"):
            extra.append(f"account: {dict((a['value'], a['label']) for a in A.ACCOUNT_TYPES).get(t['account'], t['account'])}")
        return f"- [ ] {t['label']}" + (f" ({'; '.join(extra)})" if extra else "")

    md = [
        "# AI use attestation form", "",
        "Every employee in the departments in scope answers these questions, from a link or in the platform. It takes about two minutes.", "",
        f"## Step 1 of 4. {ATTESTATION_STEPS[0]}", "",
        "- Your name", "- Work email (optional when answering from a shared link)", "- Department (chosen from the departments in scope)", "",
        f"## Step 2 of 4. {ATTESTATION_STEPS[1]}", "", "**AI tools**", "", *[tool_line(t) for t in tools], "",
        "**AI agents (tools that take actions for you)**", "", *[tool_line(t) for t in agents], "",
        "- [ ] I don't use AI for work", "",
        "For each tool or agent ticked: which account do you use it with?", "", *[f"- {a['label']}" for a in A.ACCOUNT_TYPES], "",
        f"## Step 3 of 4. {ATTESTATION_STEPS[2]}", "", "Tick all that apply:", "", *[f"- [ ] {p['label']}" for p in A.PURPOSES], "",
        "If \"Something else\": what else?", "", "What information goes into it?", "", *[f"- [ ] {d['label']}" for d in A.DATA_CATEGORIES], "",
        f"## Step 4 of 4. {ATTESTATION_STEPS[3]}", "", A.POLICY_TEXT, "", "- [ ] I have read the AI use policy", "",
        "*Individual answers are seen only by the Chief AI Compliance Officer, the Data Protection Officer and the Futran auditors. "
        f"Managers see department totals only, and only where at least {A.MIN_AGGREGATE} people have answered.*",
    ]
    out.both("People and training", "Attestation", "AI use attestation form.docx", docx("\n".join(md), "AI use attestation form"),
             "The questions every employee answers about the AI tools and agents they use, with every option offered.")


def _module_md(m: dict, with_answers: bool) -> str:
    md = [f"# {m['title']}", "", f"*{m['minutes']} minutes · {m['audience']} · Futran module v{m['version']} · pass mark {m['pass_mark']}%*", "", m["summary"], ""]
    for p in m["pages"]:
        md += [f"## {p['title']}", ""]
        for para in p.get("paragraphs") or []:
            md += [para, ""]
        md += [f"- {pt}" for pt in p.get("points") or []] + ([""] if p.get("points") else [])
    md += ["## Quiz", ""]
    for n, q in enumerate(m["quiz"], start=1):
        md += [f"### Question {n}. {q['question']}", ""]
        md += [f"- {o['id'].upper()}. {o['text']}" for o in q["options"]] + [""]
        if with_answers:
            right = next(o for o in q["options"] if o["id"] == q["answer"])
            md += [f"**Correct answer:** {right['id'].upper()}. {right['text']}", "", f"*Why:* {q['explanation']}", ""]
    return "\n".join(md)


def training(out: Out) -> None:
    from app.training.modules import for_client, learner_view, library

    g, s = "People and training", "AI literacy training"
    keys = []
    for n, (code, m) in enumerate(library().items(), start=1):
        learner = learner_view(m, COMPANY)  # what the learner's browser receives: no answers, no explanations
        full = for_client(m, COMPANY)
        stem = f"Module {n} - {learner['title'].replace(COMPANY, 'your company')}"
        out.write("Client", g, s, f"{stem}.docx", docx(_module_md(learner, False), learner["title"]),
                  f"Learner copy of the module: pages and the {len(learner['quiz'])}-question quiz, without answers.")
        out.write("Futran", g, s, f"{stem} (with answers).docx", docx(_module_md(full, True), full["title"]),
                  "Facilitator copy: the module with the correct answer and explanation for each quiz question. Futran only.")
        for q in full["quiz"]:
            right = next(o for o in q["options"] if o["id"] == q["answer"])
            keys.append([f"Module {n}", full["title"], q["id"], q["question"], f"{right['id'].upper()}. {right['text']}", q["explanation"], m["pass_mark"]])
    out.write("Futran", g, s, "AI literacy quiz answer keys.xlsx",
              xlsx([("Answer keys", ["Module", "Title", "Question id", "Question", "Correct answer", "Explanation", "Pass mark (%)"], keys, [10, 40, 11, 60, 45, 70, 12])]),
              "Every quiz question in the five modules with its correct answer, explanation and the pass mark. Futran only.")


# ---------------------------------------------------------------- AI governance


TYPE_LABELS = {"text": "Short text", "long_text": "Long text", "single": "Choose one", "multi": "Choose any that apply", "yes_no": "Yes or no",
               "date": "Date", "number": "Number", "percent": "Percentage", "person": "Person (name and title)"}


def _questions(db):
    from sqlalchemy import select

    from app.questionnaire.models import ChecklistItem, Question
    from app.questionnaire.seed import active_template_version

    tv = active_template_version(db)
    qs = list(db.scalars(select(Question).where(Question.template_version_id == tv.id).order_by(Question.order)))
    checks = list(db.scalars(select(ChecklistItem).where(ChecklistItem.template_version_id == tv.id).order_by(ChecklistItem.order)))
    return tv, qs, checks


def _options(q) -> str:
    return "; ".join(o["label"] for o in q.options or [])


def rule_text(rule, by_code: dict) -> str:
    """An applicability rule (app/questionnaire/rules.py grammar) in plain words."""
    if not rule:
        return ""
    if "any" in rule:
        return " or ".join(rule_text(r, by_code) for r in rule["any"])
    if "all" in rule:
        return " and ".join(rule_text(r, by_code) for r in rule["all"])
    if "q" in rule:
        q = by_code.get(rule["q"])
        labels = {o["value"]: o["label"] for o in (q.options or [])} if q else {}
        name = f"{rule['q']} ({q.label})" if q else rule["q"]
        if "contains" in rule:
            return f"{name} includes {labels.get(rule['contains'], rule['contains'])}"
        if "in" in rule:
            return f"{name} is {' or '.join(labels.get(v, str(v)) for v in rule['in'])}"
        if "eq" in rule:
            return f"{name} is {labels.get(rule['eq'], str(rule['eq']))}"
    if "engagement" in rule:
        fact = rule["engagement"]
        if fact.endswith("_in_scope"):
            name = fact[: -len("_in_scope")].replace("_", " ")
            name = name.upper() if len(name) <= 5 else name.capitalize()
            return f"{name} is in scope for the engagement" if rule.get("eq", True) else f"{name} is not in scope"
        if "in" in rule:
            return f"the client's {fact.replace('_', ' ')} is {', '.join(str(v).replace('_', ' ') for v in rule['in'])}"
    if "system" in rule:
        vals = rule.get("in") or [rule.get("eq")]
        return f"the system's {rule['system'].replace('_', ' ')} is {' or '.join(str(v).replace('_', ' ') for v in vals)}"
    return "in some engagements"


def questionnaire(out: Out, db) -> None:
    import yaml

    from app.reference.jurisdictions import SEEDS

    tv, qs, checks = _questions(db)
    by_code = {q.code: q for q in qs}
    g, s = "AI governance", "AI systems"
    client_qs = [q for q in qs if q.default_respondent == "client"]
    scope = {"system": "Each AI system", "engagement": "Once for the organization"}

    def row(q, futran: bool) -> list:
        base = [q.sub_section, q.section_title, scope.get(q.scope, q.scope), q.code, q.label, q.help_text, TYPE_LABELS.get(q.type, q.type), _options(q),
                q.detail_label, "Required" if q.required else "Optional", rule_text(q.applicability_rule, by_code) or rule_text(q.section_rule, by_code)]
        if futran:
            base += ["Auditor" if q.default_respondent == "auditor" else "Client, verified by the auditor", "Yes" if q.light else "",
                     q.scoring_map or "", "Yes" if q.evidence_required else "",
                     (f"{q.finding_rule.get('severity', '')}: {q.finding_rule.get('title', '')}" if q.finding_rule else "")]
        return base

    head = ["Section", "Section title", "Answered for", "Code", "Question", "Guidance", "Answer type", "Options", "Detail asked", "Required", "Asked only when"]
    widths = [8, 30, 18, 9, 50, 60, 16, 50, 18, 10, 40]
    sections = list(dict.fromkeys((q.sub_section, q.section_title, q.scope) for q in client_qs))
    index = [[sc, title, scope.get(sp, sp), sum(1 for q in client_qs if q.sub_section == sc)] for sc, title, sp in sections]
    out.write("Client", g, s, "AI system questionnaire.xlsx",
              xlsx([("Sections", ["Section", "Title", "Answered for", "Questions"], index, [10, 50, 22, 11]),
                    ("Questions", head, [row(q, False) for q in client_qs], widths)]),
              f"The {tv.name} questions the client pre-fills for each AI system (and once for the organization), by section, with guidance and options.")
    md = [f"# {tv.name}: questions for the client", "", f"Template version {tv.version}" + (f", addenda {', '.join(tv.addenda)}" if tv.addenda else "") +
          ". The client answers these for each AI system in scope; the Futran auditor verifies each answer.", ""]
    for sc, title, sp in sections:
        md += [f"## {sc} {title}", "", f"*{scope.get(sp, sp)}.*", ""]
        for q in (q for q in client_qs if q.sub_section == sc):
            md += [f"### {q.code} {q.label}" + (" *" if q.required else ""), ""]
            if q.help_text:
                md += [q.help_text, ""]
            line = f"*{TYPE_LABELS.get(q.type, q.type)}*" + (f": {_options(q)}" if q.options else "")
            md += [line, ""]
            when = rule_text(q.applicability_rule, by_code)
            if when:
                md += [f"Asked only when {when}.", ""]
    out.write("Client", g, s, "AI system questionnaire.docx", docx("\n".join(md), "AI system questionnaire"),
              "The same client questions as a document to read or work through offline, section by section. Questions marked * are required.")

    # Futran: every question, auditor guidance, scoring and checklists
    method = yaml.safe_load((SEEDS / "risk_methodology_v1.yaml").read_text())
    factors = []
    for key, f in method["factors"].items():
        q = by_code.get(f.get("question") or "")
        labels = {o["value"]: o["label"] for o in (q.options or [])} if q else {}
        if f.get("scores"):
            detail = "; ".join(f"{labels.get(v, v)} = {n}" for v, n in f["scores"].items())
        elif f.get("bands"):
            detail = "; ".join(f"up to {b['max']:,} = {b['score']}" if b.get("max") is not None else f"more = {b['score']}" for b in f["bands"])
        else:
            detail = "; ".join(f"{rule_text(lv['rule'], by_code) or 'otherwise'} = {lv['score']}" for lv in f.get("levels", []))
        factors.append([key.replace("_", " ").capitalize(), f["weight"], f.get("question") or ", ".join(f.get("questions", [])), detail])
    bands = [[b["rating"].capitalize(), b["min"]] for b in method["bands"]]
    knockouts = [[k["code"], k["label"], k["force"]] for k in method.get("knockouts", [])]
    domains = [[k, v, *[method["domain_weights_by_build_type"][bt].get(k, "") for bt in ("in_house", "vendor")]] for k, v in method["domains"].items()]
    guidance = [[sc, title, note] for sc, title, note in dict.fromkeys((q.sub_section, q.section_title, q.section_note) for q in qs) if note]
    fhead = head + ["Answered by", "Light assessment", "Scoring factor", "Evidence required", "Draft finding when triggered"]
    out.write("Futran", g, s, "AI system questionnaire with auditor questions and scoring.xlsx",
              xlsx([("Questions", fhead, [row(q, True) for q in qs], widths + [22, 10, 16, 10, 50]),
                    ("Section guidance", ["Section", "Title", "Guidance for the auditor"], guidance, [8, 40, 110]),
                    ("Audit checklists", ["Section", "Checklist", "Code", "Item", "Maturity domain", "Applies when", "Awaiting Futran review"],
                     [[c.section, c.section_title, c.code, c.text, method["domains"].get(c.maturity_domain, c.maturity_domain), rule_text(c.applicability_rule, by_code),
                       "Yes" if c.pending_review else ""] for c in checks], [8, 30, 9, 80, 30, 40, 12]),
                    ("Scoring method", ["Factor", "Weight", "Question", "Answer scores"], factors, [26, 8, 22, 90]),
                    ("Risk bands and knockouts", ["Rating or knockout code", "Minimum score or rule", "Forces rating"],
                     [[r, m, ""] for r, m in bands] + [[c, lbl, f] for c, lbl, f in knockouts], [30, 90, 14]),
                    ("Maturity domains", ["Domain", "Name", "Weight (built in-house)", "Weight (bought from vendor)"], domains, [14, 40, 20, 22])]),
              f"Every question in the {tv.name} (client and auditor), the auditor guidance for each section, the audit checklists, and the "
              f"risk scoring method v{method['version']}. Futran only.")
    md = [f"# {tv.name}: full question bank", "", "Client questions, auditor questions and the guidance for each section. Futran only.", ""]
    for sc, title, note in dict.fromkeys((q.sub_section, q.section_title, q.section_note) for q in qs):
        md += [f"## {sc} {title}", ""]
        if note:
            md += [f"> {note}", ""]
        for q in (q for q in qs if q.sub_section == sc):
            who = "Auditor" if q.default_respondent == "auditor" else "Client"
            md += [f"### {q.code} {q.label}" + (" *" if q.required else ""), "", f"*{who} · {TYPE_LABELS.get(q.type, q.type)}*" + (f": {_options(q)}" if q.options else ""), ""]
            if q.help_text:
                md += [q.help_text, ""]
            if q.scoring_map:
                md += [f"Scoring factor: {q.scoring_map}.", ""]
            if q.finding_rule:
                md += [f"Draft finding ({q.finding_rule.get('severity')}): {q.finding_rule.get('title')}.", ""]
    out.write("Futran", g, s, "AI system questionnaire with auditor questions and scoring.docx", docx("\n".join(md), "AI system questionnaire (full)"),
              "The full question bank as a document, with the auditor guidance for each section. Futran only.")


def register_template(out: Out, db) -> None:
    from app.register import seeding

    g, s = "AI governance", "AI systems"
    out.write("Client", g, s, "AI system register import template.csv", seeding.template_csv(),
              "CSV for adding AI systems to the register in bulk, with one example row. Columns marked * are required.")
    out.write("Client", g, s, "AI system register import template.xlsx", seeding.template_xlsx(db),
              "The same template as a workbook, with drop-down lists and an Instructions sheet explaining every column.")


def policies(out: Out) -> None:
    from app.policies import templates as T

    g, s = "AI governance", "Policies"
    rows = []
    for t in T.library().values():
        answers = T.defaults(t, COMPANY)
        for q in t.questions:  # required answers with no default show as a bracketed placeholder
            if q["key"] != "company_name" and q.get("required") and not answers.get(q["key"]):
                answers[q["key"]] = [f"[{q['label']}]"] if q["type"] in ("list", "multi") and not q.get("options") else f"[{q['label']}]"
        md = T.blocks_to_markdown(T.render(t, answers))
        md += "\n## Questions that tailor this policy\n\n| Question | Answer type | Default | Guidance |\n|---|---|---|---|\n"
        for q in t.questions:
            d = q.get("default")
            if q.get("options") and d is not None:
                labels = {o["value"]: o["label"] for o in q["options"]}
                d = ", ".join(labels.get(x, x) for x in d) if isinstance(d, list) else labels.get(d, d)
            elif isinstance(d, bool):
                d = "Yes" if d else "No"
            md += f"| {cell(q['label'])}{' *' if q.get('required') else ''} | {cell(q['type'])} | {cell(d)} | {cell(q.get('help'))} |\n"
            rows.append([t.name, t.version, q["label"], "Required" if q.get("required") else "Optional", q["type"],
                         "; ".join(o["label"] for o in q.get("options") or []), str(d if d is not None else ""), q.get("help")])
        out.write("Client", g, s, f"{t.name} (template).docx", docx(md, t.name),
                  f"Futran template v{t.version}: {t.summary} Default wording, with the questions that tailor it listed at the end.")
    out.write("Client", g, s, "Policy template questions.xlsx",
              xlsx([("Questions", ["Policy", "Template version", "Question", "Required", "Answer type", "Options", "Default", "Guidance"], rows,
                     [34, 10, 34, 10, 10, 50, 30, 80])]),
              "Every question the policy builder asks, for all ten templates, to gather answers before starting.")


PROJECT_FIELDS = [
    ("project_name", "Project name", True, None), ("department_id", "Department", True, None), ("tool_or_vendor", "Tool or vendor", True, None),
    ("planned_go_live", "Planned go-live", False, None), ("system_type", "Type of AI", True, "type"), ("sourcing", "Bought or built", True, "sourcing"),
    ("autonomy", "How much it acts on its own (AI agents only)", False, "autonomy"), ("purpose", "Purpose", True, None),
    ("jurisdiction_ids", "Where the users are", False, None), ("data_categories", "Data it will use", True, "data_categories"),
    ("data_subjects", "Whose data, or whom it affects", False, "data_subjects"), ("decision_impact", "Decisions about people", True, "decision_impact"),
    ("public_facing", "Will it talk directly to the public?", False, None),
]


def new_projects(out: Out) -> None:
    from app.impact.assess import FEATURE_LABELS, depth_for
    from app.impact.service import INTAKE_KEYS, STEP_LABELS
    from app.register.service import CODE_LABELS

    keys = {k for k, *_ in PROJECT_FIELDS}
    assert set(INTAKE_KEYS) - {"user_count"} <= keys, "a new intake field needs a label here"
    md = ["# New AI project intake form", "", "Submit before buying or deploying any AI tool. The platform proposes the risk tier, the assessment depth and the laws that apply as you answer.", ""]
    for key, label, required, codes in PROJECT_FIELDS:
        md += [f"## {label}" + (" *" if required else ""), ""]
        if codes:
            md += [f"- {v}" for v in CODE_LABELS[codes].values()] + (["- None of these"] if key == "data_categories" else []) + [""]
        elif key == "public_facing":
            md += ["- Yes, users chat with it", "- No", ""]
        elif key == "jurisdiction_ids":
            md += ["Countries, states or cities, chosen from the platform's list.", ""]
        else:
            md += ["_______________________________________________", ""]
    md += ["## How the assessment depth is set", ""]
    md += [f"- Tier {tier}: {depth_for(tier, {})[2]}" for tier in (1, 2, 3)] + [""]
    md += ["## AI features the laws are matched on", ""] + [f"- {v}" for v in FEATURE_LABELS.values()] + [""]
    md += ["## Reviewers", ""] + [f"1. {v}" for v in STEP_LABELS.values()] + ["1. Chief AI Compliance Officer: decision (approved, approved with conditions or rejected)", ""]
    out.write("Client", "AI governance", "New AI projects", "New AI project intake form.docx", docx("\n".join(md), "New AI project intake form"),
              "The impact assessment intake for a new AI project, with every option, how the assessment depth is set and who reviews it.")


def governance_catalog(out: Out, db) -> None:
    from sqlalchemy import select

    from app.reference.models import GovernanceCatalogItem

    kinds = {"document": "Governance document", "security_document": "Data and security document", "role": "Committee or named owner"}
    rows = [[kinds.get(i.kind, i.kind), i.code, i.title, i.description, "Optional" if i.optional else "Expected",
             "Only with EU operations" if i.conditional == "eu_operations" else (i.conditional or ""), ", ".join(i.control_refs or [])]
            for i in db.scalars(select(GovernanceCatalogItem).order_by(GovernanceCatalogItem.order))]
    out.write("Client", "AI governance", "Governance", "AI governance structure checklist.xlsx",
              xlsx([("Governance structure", ["Kind", "Code", "Item", "What it is", "Expected or optional", "Condition", "Controls it supports"], rows,
                     [26, 8, 44, 80, 14, 22, 50])]),
              "The governance documents, data and security documents, committees and named owners Futran asks for, with the controls each supports.")


# ---------------------------------------------------------------- documents and letters


def package_context(db, org, categories: list[dict] | None = None) -> dict:
    """Merge values for the initiation templates, with every client-specific value as a bracketed placeholder."""
    from app.core.clock import today
    from app.initiation.context import TYPE_LABELS, fmt, governance_groups

    team = [{"name": "[Chief Auditor]", "role_label": "Chief Auditor", "email": ""}, {"name": "[Engagement Manager]", "role_label": "Engagement Manager", "email": ""},
            {"name": "[Auditor]", "role_label": "Auditor", "email": ""}]
    return {
        "today": fmt(today()),
        "client": {"name": "[Client name]", "legal_name": "[Client legal name]", "hq_address": "[Head office address]", "industry": "[Industry]"},
        "engagement": {"name": "[Engagement name]", "audit_ref": "[Audit reference]", "type_label": TYPE_LABELS["initial_assessment"],
                       "period_start": "[Start of audit period]", "period_end": "[End of audit period]", "letter_due": "[Date to sign by]",
                       "report_due": "[Report date]", "draft_report_target": "[Draft report date]", "final_report_target": "[Final report date]",
                       "methodology_version": "Futran AI Audit Procedure v1.0", "departments": ["[Department]"], "department_rows": [{"name": "[Department]"}],
                       "systems": [], "business_processes": None, "geographic_scope": None, "exclusions": None, "retention_years": None},
        "contacts": {"caico": {"name": "[Chief AI Compliance Officer]", "title": "Chief AI Compliance Officer", "email": "[CAICO email]"},
                     "client_admin": {"name": "[Client Admin]"}, "exec_sponsor": {"name": "[Executive Sponsor]"}, "dpo": {"name": "[Data Protection Officer]"}},
        "laws": [{"short_name": "[Law or framework]", "jurisdiction_name": "[Jurisdiction]", "feature_label": "[Area]"}],
        "team": team, "chief_auditor": {"name": "[Chief Auditor]"}, "sender": {"name": "[Sender name]", "role_label": "Chief Auditor"},
        "has_ny": True, "has_eu": True, "groups": governance_groups(db, org), "due_date": None, "categories": categories or [],
    }


EXAMPLE_NOTE = ("*Example: client details are shown in square brackets, and paragraphs that apply only to New York or EU operations are "
                "included. The platform fills these in from the engagement when it generates the document.*")


def letters(out: Out, db, org, example) -> None:
    from sqlalchemy import select

    from app.reference.models import DocumentCatalogItem, DocumentTemplate
    from app.reference.templates import render_template
    from app.regmaster.letter import build_body, to_markdown
    from app.regmaster.models import IntroLetter

    cats: dict[int, dict] = {}
    for item in db.scalars(select(DocumentCatalogItem).order_by(DocumentCatalogItem.order)):
        cats.setdefault(item.category, {"title": f"{item.category}. {item.category_title}", "requests": []})["requests"].append(
            {"title": item.title, "system": "[AI system]" if item.per_system else None})
    ctx = package_context(db, org, [cats[k] for k in sorted(cats)])
    names = {t.key: t.name for t in db.scalars(select(DocumentTemplate).where(DocumentTemplate.active.is_(True)))}

    def render(key: str) -> bytes:
        return docx(f"{EXAMPLE_NOTE}\n\n{render_template(db, key, ctx)}", names[key])

    home, clients = ("Home", "Getting started"), ("Home and work", "Clients")
    for key, purpose in (("engagement_letter", "The engagement letter and scope the client signs (initiation package item 1)."),
                         ("roles_note", "The note asking the client to name its AI compliance roles (initiation package item 2)."),
                         ("data_notice", "The notice to employees about the data the audit uses (initiation package item 5)."),
                         ("getting_started", "The getting started guide for the client's team (initiation package item 6)."),
                         ("governance_request", "The request for the client's AI governance documents, committees and owners (initiation package item 7).")):
        data = render(key)
        out.write("Client", *home, f"{names[key]} (example).docx", data, purpose)
        if key == "engagement_letter":
            out.write("Futran", *clients, f"{names[key]} (example).docx", data, purpose)
    data = render("document_request_email")
    out.write("Client", "Audit", "Documents", "Pre-audit document request email (example).docx", data,
              "The email that asks the client for the pre-audit documents, grouped by category, with the due date.")
    out.write("Futran", *clients, "Pre-audit document request email (example).docx", data,
              "The pre-audit document request email as sent to the client's Chief AI Compliance Officer.")
    for key, side_screens, purpose in (
        ("management_representation", [("Client", "Audit", "Review"), ("Futran", *clients)], "The management representation the client signs at sign-off."),
        ("client_declaration", [("Client", "Audit", "Review"), ("Futran", *clients)], "The declaration the client signs on receiving the final report."),
        ("lead_auditor_declaration", [("Futran", *clients)], "The declaration the Lead Auditor signs on the final report. Futran only."),
    ):
        data = render(key)
        for side, g, s in side_screens:
            out.write(side, g, s, f"{names[key]} (example).docx", data, purpose)

    letter = IntroLetter(organization_id=example.id, version_no=1, body=build_body(db, example), changes=[], edited_text={})
    md = to_markdown(letter)
    data = docx(f"*Example generated for a client with employees in New York City, Illinois and the EU.*\n\n{md}", "AI governance requirements for your operations")
    purpose = "The intro letter: laws that apply, the committee to form, roles to fill and rules per AI type, generated from the applicability engine."
    out.write("Futran", *clients, "Intro letter (example).docx", data, purpose)
    out.write("Client", *home, "Intro letter (example).docx", data, purpose)

    # every document template source, as Futran edits it under Administration > Templates
    for t in db.scalars(select(DocumentTemplate).where(DocumentTemplate.active.is_(True)).order_by(DocumentTemplate.package_item.is_(None), DocumentTemplate.package_item, DocumentTemplate.name)):
        what = f"initiation package item {t.package_item} ({t.requires_action})" if t.package_item else t.type.replace("_", " ")
        out.write("Futran", "Administration", "Templates", f"{t.name} (template source).md", t.body,
                  f"Template source (Markdown with merge fields), version {t.version}: {what}. Futran only.")


def document_requests(out: Out, db) -> None:
    from sqlalchemy import select

    from app.reference.models import DocumentCatalogItem

    cond = {"gdpr": "If GDPR applies", "hipaa": "If HIPAA applies"}
    rows = [[f"{i.category}. {i.category_title}", i.code, i.title, i.description, "Once for each AI system" if i.per_system else "Once",
             cond.get(i.condition or "", i.condition or ""), i.template_section, "", "", ""]
            for i in db.scalars(select(DocumentCatalogItem).order_by(DocumentCatalogItem.order))]
    out.both("Audit", "Documents", "Pre-audit document request list.xlsx",
             xlsx([("Document requests", ["Category", "Code", "Document", "Detail", "How many", "Condition", "Audit section", "Owner", "Date provided", "Not available: reason"],
                    rows, [30, 8, 50, 50, 22, 16, 10, 20, 14, 30])]),
             "Every document requested before fieldwork, by category, with columns to track the owner and date provided.")


# ---------------------------------------------------------------- Data and integrations


def bias_template(out: Out) -> None:
    from app.biascalc import dataset

    header = ["id", "selected", "score", "sex", "race_ethnicity", "age_band", "qualified"]
    rows = [["A-1001", "yes", "82", "Female", "Hispanic or Latino", "25-34", "yes"], ["A-1002", "no", "41", "Male", "White", "35-44", "no"],
            ["A-1003", "yes", "77", "Male", "Black or African American", "18-24", "yes"], ["A-1004", "no", "55", "Female", "Asian", "45-54", "yes"],
            ["A-1005", "yes", "90", "", "Two or more races", "25-34", "yes"], ["A-1006", "no", "38", "Female", "", "55-64", "no"]]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    parsed = dataset.parse(buf.getvalue().encode())
    assert parsed.report["error_count"] == 0, parsed.report["errors"]  # the template must read cleanly in the calculator
    g, s = "Data and integrations", "Bias test data"
    out.write("Client", g, s, "Bias calculator data template.csv", buf.getvalue(),
              "CSV layout for applicant or employee data for the bias calculator: one row per person assessed, with six example rows to replace.")
    guide = ["# Bias calculator data: column guide", "", "One row per person the tool assessed. Column names are matched without regard to case, spaces or punctuation.", "",
             "| Column | Also accepted as |", "|---|---|"]
    guide += [f"| {k} | {', '.join(v)} |" for k, v in dataset.ALIASES.items()]
    guide += ["", "## What each column holds", "", "```", dataset.__doc__.split("Columns", 1)[1].split("Values that cannot", 1)[0].strip(), "```", "",
              "Values that cannot be read are listed as errors with their row number, so the data is corrected at source."]
    out.write("Client", g, s, "Bias calculator column guide.md", "\n".join(guide) + "\n",
              "What each column of the bias calculator file means and the other column names it accepts.")


def customer_questionnaire(out: Out) -> None:
    from app.ai import questionnaires as Q
    from app.demo.wave3_g import _questionnaire_xlsx

    data = _questionnaire_xlsx()
    found = Q.detect_xlsx(data)
    g, s = "Data and integrations", "Customer questionnaires"
    out.write("Client", g, s, "Customer questionnaire example.xlsx", data,
              "An example customer AI and data due diligence questionnaire in a layout the platform reads: a Question column and a response column.")
    md = ["# How the platform reads a customer questionnaire", "", "Upload the customer's own file (Excel, Word or PDF). The platform finds the questions, drafts answers "
          "from your answer library, published policies and latest signed Futran report, and writes your approved answers back into the file.", "",
          "- **Excel:** the column headed \"Question\" (otherwise the column with most cells ending in \"?\"); answers go in the column headed answer, response, "
          "comment or reply, otherwise the next column. A column headed section, category, domain or area is kept as the section.",
          "- **Word:** paragraphs and table cells ending in \"?\" or starting with describe, explain, list, provide, confirm, state or outline; the answer goes "
          "in an \"Answer:\" paragraph after the question, or the next table cell.",
          "- **PDF:** lines ending in \"?\"; the answers come back as a Word document.", "",
          f"## Questions found in the example ({len(found)})", "", "| Sheet | Row | Section | Question |", "|---|---|---|---|"]
    md += [f"| {cell(f['locator']['sheet'])} | {f['locator']['row']} | {cell(f['section'])} | {cell(f['question'])} |" for f in found]
    out.write("Client", g, s, "How customer questionnaires are read.md", "\n".join(md) + "\n",
              "The file formats accepted and how questions and answer columns are found, with the questions found in the example.")


# ---------------------------------------------------------------- email, alerts, regulatory updates


def group_emails(out: Out) -> None:
    from app.mail.library import DEFAULTS, MERGE_FIELDS

    md = ["# Group email templates", "", "Futran's default templates for group sends. A client can copy one and edit its own copy; each edit is a new version.", "",
          f"Merge fields: {', '.join(f'[{m}]' for m in MERGE_FIELDS)}. A regulatory change alert also has [Changes].", ""]
    for d in DEFAULTS:
        md += [f"## {d['name']}", "", f"- Purpose: {d['purpose']}", f"- Sent as: {'one personal email each' if d['default_mode'] == 'personal' else 'one email, recipients in BCC'}",
               f"- Subject: {d['subject']}", f"- Button: {d['button_label']}", "", "```text", d["body"], "```", ""]
    data = "\n".join(md)
    out.write("Client", "Email", "Groups", "Group email templates.md", data, "The default email templates offered when sending to a group, with their merge fields.")
    out.write("Futran", "Administration", "Email and groups", "Group email templates.md", data, "The default group email templates Futran ships to every client.")


def platform_emails(out: Out) -> None:
    from app.mail import service

    folder = Path(service.__file__).parent / "templates"
    keys = sorted({p.name.split(".")[0] for p in folder.glob("*.j2")} - {"_layout"})
    md = ["# Platform email templates", "", "The emails the platform sends on its own (invitations, codes, reminders, alerts). Sources are Jinja templates in "
          "backend/app/mail/templates; the HTML version uses the shared layout. Futran only.", ""]
    for k in keys:
        md += [f"## {k.replace('_', ' ').capitalize()}", ""]
        for part, label in (("subject", "Subject"), ("txt", "Plain text")):
            p = folder / f"{k}.{part}.j2"
            if p.is_file():
                md += [f"**{label}**", "", "```jinja", p.read_text(encoding="utf-8").strip(), "```", ""]
    out.write("Futran", "Administration", "Email and groups", "Platform email templates.md", "\n".join(md),
              "The subject and text of every email the platform sends automatically, as template source. Futran only.")
    alert = ["# Client alert email (template source)", ""]
    for part in ("subject", "txt", "html"):
        alert += [f"## {part}", "", "```jinja", (folder / f"client_alert.{part}.j2").read_text(encoding="utf-8").strip(), "```", ""]
    out.write("Futran", "Business", "Client alerts", "Client alert email (template source).md", "\n".join(alert),
              "The email a client alert is sent in: subject, text and HTML source. Futran only.")


def client_alerts(out: Out) -> None:
    from app.clientalerts.service import APPROVAL_LABELS, AUDIENCE_LABELS, DEFAULT_RULES, WHEN_LABELS

    rows = [[WHEN_LABELS.get(t, t), AUDIENCE_LABELS.get(a, a), ", ".join(gr), label, APPROVAL_LABELS.get(ap, ap), ", ".join(f"{d} days" for d in days),
             "Off until switched on" if t == "tracing_addon" else "On"] for t, a, gr, label, ap, days in DEFAULT_RULES]
    out.write("Futran", "Business", "Client alerts", "Client alert rules.xlsx",
              xlsx([("Alert rules", ["When", "Who receives it", "Client groups", "Email", "Approval", "Days before", "Default"], rows, [36, 40, 36, 44, 34, 16, 18])]),
              "The default client alert rules: what triggers each alert, who gets it and who approves it. Futran only.")


REG_UPDATE_FIELDS = [("change_type", "Type of change", True), ("title", "Headline", True), ("summary", "What changed and who it affects", True),
                     ("jurisdiction_id", "Jurisdiction (or the law it changes)", True), ("regulation_id", "Law in the law library", False),
                     ("law_name", "Law name (when not in the library)", False), ("effective_on", "Effective date", False),
                     ("affected_features", "AI features affected", False), ("todo_text", "What clients should do", False), ("source_name", "Source", False),
                     ("source_url", "Source web address", False), ("source_quote", "Quotation from the source", False), ("verify_note", "Note for the reviewer", False),
                     ("watch", "Keep watching this", False)]


def regulatory_updates(out: Out) -> None:
    from app.impact.assess import FEATURE_LABELS
    from app.regupdates.models import FEATURES
    from app.regupdates.service import CHANGE_LABELS

    md = ["# Regulatory update entry form", "", "The fields Futran fills in to record a regulatory update. A second person reviews it before it is published to the clients it matches.", ""]
    md += [f"- **{label}**{' (required)' if req else ''}" for _k, label, req in REG_UPDATE_FIELDS] + ["", "## Types of change", ""]
    md += [f"- {v}" for v in CHANGE_LABELS.values()] + ["", "## AI features", ""] + [f"- {FEATURE_LABELS.get(f, f)}" for f in FEATURES] + [""]
    out.write("Futran", "Law library", "Regulatory updates", "Regulatory update entry form.md", "\n".join(md),
              "The fields, change types and AI features used when entering a regulatory update.")


# ---------------------------------------------------------------- README


CLIENT_INTRO = ("Forms and templates the client side of the Futran Audit Platform asks people to fill in, or sends them. Folders follow the client menu: "
                "menu group, then screen. Documents marked (example) show what the platform generates, with client details in square brackets.")
FUTRAN_INTRO = ("Forms and templates for Futran staff, including the confidential copies clients never receive: quiz answer keys, auditor-only questions "
                "and guidance, the scoring method, template sources and internal rules. Folders follow the Futran menu; material that belongs to a client "
                "screen (Audit › Documents, AI governance › AI systems, People and training › Attestation and AI literacy training) "
                "uses the client menu's group and screen names.")


def readme(out: Out, side: str) -> str:
    entries = [e for e in out.entries if e.side == side]
    lines = ["---", f"title: Forms and templates ({side})", f"generated: {date.today().isoformat()}", "tags: [futran-audit-platform, forms-and-templates, "
             f"{side.lower()}]", f"files: {len(entries)}", "---", "", f"# Forms and templates: {side}", "", CLIENT_INTRO if side == "Client" else FUTRAN_INTRO, "",
             "Generated by `python -m scripts.export_forms` from the application's own seeds and generators. Run it again after a release to refresh.", ""]
    for group in dict.fromkeys(e.group for e in entries):
        lines += [f"## {group}", ""]
        for screen in dict.fromkeys(e.screen for e in entries if e.group == group):
            lines += [f"### {screen}", "", "| File | Section | What it is for |", "|---|---|---|"]
            for e in (e for e in entries if e.group == group and e.screen == screen):
                path = f"{e.group}/{e.screen}/{e.name}"
                lines.append(f"| [[{path}\\|{e.name}]] | {e.group} › {e.screen} | {cell(e.purpose)} |")
            lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- main


def export(out_dir: Path) -> Out:
    root = Path(out_dir) / ROOT_NAME
    if root.exists():
        import shutil

        shutil.rmtree(root)  # a fresh tree each run, so removed forms do not linger
    out = Out(root)
    db = open_database()
    try:
        blank, example = client_orgs(db)
        letters(out, db, blank, example)
        register_template(out, db)
        questionnaire(out, db)
        governance_catalog(out, db)
        policies(out)
        new_projects(out)
        document_requests(out, db)
        people(out, db, blank)
        attestation(out)
        training(out)
        bias_template(out)
        customer_questionnaire(out)
        group_emails(out)
        platform_emails(out)
        client_alerts(out)
        regulatory_updates(out)
    finally:
        db.rollback()
        db.close()
    for side in ("Client", "Futran"):
        (root / side / "README.md").write_text(readme(out, side), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("Usage: python -m scripts.export_forms <out_dir>", file=sys.stderr)
        return 2
    out = export(Path(argv[0]))
    for side in ("Client", "Futran"):
        print(f"{side}: {sum(e.side == side for e in out.entries)} files")
    print(f"Written to {Path(argv[0]) / ROOT_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
