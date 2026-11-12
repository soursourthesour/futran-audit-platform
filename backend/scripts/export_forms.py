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
auditor-only questions, section guidance for auditors, scoring, Futran template sources and internal rules; from
Release 2 also prices, the price list, internal scoping questions, mapping rules, proposals and sales findings) is
written to the Futran folder only. A sample proposal is built by the proposal service in the throwaway database from
the starter "Governed" package, for an example prospect and rep.
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
        assert "/" not in name and "/" not in group, name  # only `screen` may name a workspace folder below a screen
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


# ---------------------------------------------------------------- Release 2: sales


def csv_text(header: list[str], rows: list[list] | None = None) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows or [])
    return buf.getvalue()


def heading(alias: str) -> str:
    """A column heading from an importer's alias (aliases are matched without regard to case)."""
    words = [w.upper() if w.strip("()").lower() in ("url", "upn", "utc", "ou", "id") else w for w in alias.split(" ")]
    out = " ".join(words)
    return out[:1].upper() + out[1:]


def price_list(out: Out, db) -> None:
    from sqlalchemy import select

    from app.catalog import fields as F
    from app.catalog import io as cio
    from app.catalog.models import PackageTemplate

    g, s = "Sales", "Price list"
    values = {
        "code": "Codes look like XX-00 with an optional letter, for example A-02a or AA-02. Fixed once the item is added.",
        "product": ", ".join(F.PRODUCTS), "billing": ", ".join(F.BILLING.values()), "basis": " or ".join(F.BASIS),
        "periods_per_year": "1, 4 or 12 (0 for a partner share)", "price_status": ", ".join(F.PRICE_STATUS.values()),
        "sellable_status": ", ".join(F.SELLABLE.values()), "delivery_mode": ", ".join(F.DELIVERY.values()),
        "included_quantities": "A number and a unit, separated by semicolons, for example \"50 systems; 5 docs; 1 readout\"",
        "applies_to": "Price list codes, separated by commas", "remediation_of": "Price list codes, separated by commas", "status": "Active or Retired",
        **{f: "A number in US dollars, not negative (0 to 100 for a % item)" for f in F.PRICE_FIELDS},
    }
    needed = {"code": "Required", "product": "Required for a new item", "name": "Required for a new item", "list_price": "Column required in the sheet"}
    guide = [[label, F.FIELD_LABELS.get(field, field), needed.get(field, ""), values.get(field, "Text"),
              f"Up to {F.TEXT_LIMITS[field]} characters" if field in F.TEXT_LIMITS else ""] for field, label in cio.COLUMNS]
    rules = F.item_errors({"basis": "%", "low": 101, "list_price": 50, "high": 40, "periods_per_year": 2, "price_status": "approved"})
    rules += [f"Warning to confirm: {F.list_move_warning(100, 200)}", "A blank cell in a required column leaves the item's value as it is.",
              "Items on the price list but not in the workbook are retired on save, unless that option is switched off."]
    from openpyxl import load_workbook

    data = xlsx([("Master Price List", [h for _, h in cio.COLUMNS], [], [10, 14, 40, 16, 12, 8, 10, 10, 10, 10, 14, 30, 70, 16, 14, 26, 24, 20, 18, 40, 16, 16, 10]),
                 ("Columns", ["Column", "Field", "Required", "Allowed values", "Limit"], guide, [26, 26, 26, 70, 22]),
                 ("Validation", ["Rule checked on import"], [[r] for r in rules], [100])])
    wb = load_workbook(io.BytesIO(data))
    assert cio.parse_workbook(data) == ([], []), "the template must read cleanly in the importer"
    out.write("Futran", g, s, "Price list import template.xlsx", data,
              "Blank Master Price List sheet with the spec §4.9 columns the importer reads, plus a guide to each column and the validation rules. "
              f"Fill in and import on Price list › Import ({len(wb.sheetnames)} sheets).")
    export = cio.export_xlsx(db)
    out.write("Futran", g, s, "Price list starter items (export).xlsx", export,
              "The starter items as the price list's own Export writes them (sample items from the screen designs until the master workbook is imported). "
              "Edit and re-import to load real prices. Futran only.")
    pk = [[p.name, p.key, p.description, "; ".join(f"{ln['code']} × {ln['qty']}" for ln in p.lines) or "No lines yet", "Yes" if p.is_starter else ""]
          for p in db.scalars(select(PackageTemplate).order_by(PackageTemplate.sort))]
    out.write("Futran", g, s, "Price list packages.xlsx", xlsx([("Packages", ["Package", "Key", "Description", "Lines (code × quantity)", "Starter"], pk, [22, 14, 60, 60, 10])]),
              "The package templates offered in the estimator and the proposal builder, with their lines.")


SCOPING_TYPES = {"count": "Number", "total": "Number (total of the counts above)", "single": "Choose one", "multi": "Choose any that apply", "yes_no": "Yes or no",
                 "text": "Text"}
OP_WORDS = {"eq": "is", "ne": "is not", "lt": "is less than", "lte": "is at most", "gt": "is more than", "gte": "is at least", "in": "is", "includes": "includes"}


def _q_name(code, qs) -> str:
    if isinstance(code, list):
        return " + ".join(code) + " (added up)"
    q = qs.get(code)
    return f"{code} ({q.label})" if q else str(code)


def _opt(code, value, qs) -> str:
    q = qs.get(code) if isinstance(code, str) else None
    labels = {o["value"]: o["label"] for o in (q.options or [])} if q else {}
    return f"\"{labels.get(str(value), value)}\""


def _range(lo, hi) -> str:
    if lo is not None and hi is not None:
        return f"between {lo:,} and {hi:,}"
    return f"at least {lo:,}" if lo is not None else f"at most {hi:,}"


def condition_text(c: dict, qs: dict) -> str:
    """A mapping rule condition (app/scoping/rules.py grammar) in plain words."""
    if "all" in c or "any" in c:
        key = "all" if "all" in c else "any"
        parts = [condition_text(x, qs) for x in c[key]]
        if not parts:
            return "always"
        if len(parts) == 1:
            return parts[0]
        joined = (" and " if key == "all" else " or ").join(f"({p})" if (" and " in p or " or " in p) else p for p in parts)
        return joined
    q, op, v = c.get("q"), c.get("op"), c.get("value")
    name = _q_name(q, qs)
    if op == "unknown":
        return f"{name} is answered as unknown"
    if op == "any_ticked":
        return f"{name} has any option ticked"
    if op == "between":
        return f"{name} is {_range(*v)}"
    if op == "count_between":
        return f"{name} has {_range(*v)} options ticked"
    if op == "in":
        return f"{name} is " + " or ".join(_opt(q, x, qs) for x in v)
    if op in ("eq", "ne", "includes"):
        return f"{name} {OP_WORDS[op]} {_opt(q, v, qs)}"
    return f"{name} {OP_WORDS.get(op, op)} {v:,}" if isinstance(v, (int, float)) else f"{name} {OP_WORDS.get(op, op)} {v}"


def quantity_text(f: dict, qs: dict) -> str:
    tail = f" (at least {f['min']})" if f.get("min") is not None else ""
    if "const" in f:
        return str(f["const"])
    if "answer" in f:
        add = f.get("add", 0)
        return f"the answer to {_q_name(f['answer'], qs)}" + (f" plus {add}" if add > 0 else f" minus {-add}" if add < 0 else "") + tail
    if "count" in f:
        return f"the number of options ticked in {_q_name(f['count'], qs)}" + tail
    if "sum" in f:
        return f"{' + '.join(f['sum'])} added up" + tail
    if "first" in f:
        return f"the first of {', '.join(f['first'])} that is answered" + tail
    if "excess_included" in f:
        e = f["excess_included"]
        tiers = "; ".join(f"{line} for {_range(lo, hi)}" for line, lo, hi in e["tiers"])
        return f"the answer to {_q_name(e['q'], qs)} minus the {e.get('key', 'systems')} included in the matching price list item ({tiers})"
    return "1"


def scoping(out: Out, db, catalog_names: dict) -> None:
    from app.scoping import bank, rulebook, rules
    from app.scoping import sending as S

    g, s = "Sales", "Scoping"
    qs = bank.questions(db)
    by = {q.code: q for q in qs}
    rule_rows = rulebook.all_rules(db)
    used_by: dict[str, list[str]] = {}
    for r in rule_rows:
        for c in rules.question_codes(rulebook.as_definition(r)):
            used_by.setdefault(c, []).append(r.code)
    opts = lambda q: "; ".join(o["label"] for o in q.options or [])  # noqa: E731
    sections = list(dict.fromkeys(q.section for q in qs))
    head = ["Section", "Section name", "Code", "Rep wording", "Client wording", "Answer type", "Options", "Total of", "Help for the rep", "Sent to the client",
            "Assumption when unknown", "Mapping rules that read it"]
    rows = [[q.section, bank.SECTION_LABELS.get(q.section, q.section), q.code, q.label, q.client_label or "", SCOPING_TYPES.get(q.type, q.type), opts(q),
             ", ".join(q.sum_of or []), q.help or "", "No: internal only" if q.internal_only or not q.client_visible else "Yes", q.unknown_assumption or "",
             ", ".join(used_by.get(q.code, []))] for q in qs]
    index = [[sc, bank.SECTION_LABELS.get(sc, sc), bank.SECTION_INTROS.get(sc, ""), sum(1 for q in qs if q.section == sc)] for sc in sections]
    ver = bank.current_version(db)
    out.write("Futran", g, s, "Scoping question bank (with internal questions).xlsx",
              xlsx([("Sections", ["Section", "Name", "Introduction", "Questions"], index, [9, 30, 80, 11]), ("Questions", head, rows, [8, 24, 10, 40, 50, 18, 50, 30, 50, 18, 50, 24])]),
              f"Every scoping question in bank v{ver} ({bank.STARTER_LABEL.lower()}), by section: rep and client wording, options, rep help, internal-only questions and the "
              "mapping rules that read each answer. Futran only.")
    md = ["# Scoping question bank", "", f"Bank v{ver}. {bank.STARTER_NOTE}", "",
          "Each answer is marked Confirmed, Estimate or Unknown. Internal questions are never sent to the client. Futran only.", ""]
    for sc in sections:
        md += [f"## {sc}. {bank.SECTION_LABELS.get(sc, sc)}", ""] + ([f"*{bank.SECTION_INTROS[sc]}*", ""] if sc in bank.SECTION_INTROS else [])
        for q in (q for q in qs if q.section == sc):
            md += [f"### {q.code} {q.label}", "", f"- Answer type: {SCOPING_TYPES.get(q.type, q.type)}" + (f": {opts(q)}" if q.options else "")]
            if q.client_label:
                md.append(f"- Client wording: {q.client_label}")
            md.append("- Sent to the client: " + ("no, internal only" if q.internal_only or not q.client_visible else "yes"))
            for label, v in (("Total of", ", ".join(q.sum_of or [])), ("Help for the rep", q.help), ("Assumption when unknown", q.unknown_assumption),
                             ("Read by mapping rules", ", ".join(used_by.get(q.code, [])))):
                if v:
                    md.append(f"- {label}: {v}")
            md.append("")
    out.write("Futran", g, s, "Scoping question bank (with internal questions).md", "\n".join(md),
              "The same question bank as a note to read section by section. Futran only.")

    flags = rulebook.flags(db, rule_rows)
    md = ["# Scoping mapping rules", "", "How scoping answers become suggested price list lines (spec §4.5). Rules run in order; the first rule that suggests a "
          "line code wins. A rule edit, including switching it off, waits for the Pricing Approver. An unanswered or unknown answer fails every condition "
          "except \"answered as unknown\". Futran only.", ""]
    for r in rule_rows:
        d = rulebook.as_definition(r)
        md += [f"## {r.code} → {r.line_code} {catalog_names.get(r.line_code, '')}".rstrip(), "",
               f"- When: {condition_text(d['inputs'] or {'all': []}, by)}", f"- Quantity: {quantity_text(d['qty_formula'] or {'const': 1}, by)}",
               f"- Reason shown to the rep: {r.reason_template}", f"- Status: {r.status}{'' if r.active else ', switched off'}"]
        if r.note:
            md.append(f"- Note: {r.note}")
        if r.code in flags:
            md.append(f"- Needs repair: {flags[r.code]}")
        md.append("")
    out.write("Futran", g, s, "Scoping mapping rules.md", "\n".join(md),
              f"All {len(rule_rows)} mapping rules in plain words: the answers each one reads, the line and quantity it suggests, and whether its line is on the price list yet.")

    emails = ["# Scoping questionnaire emails", "", "Sent from the rep's own mailbox. The rep can edit the subject and message before sending. "
              "Merge fields are in square brackets.", "", f"Subject: {S.SUBJECT}", "", "## First email", "", "```text", S.MESSAGE, "```", "",
              "## To a colleague the client forwards it to", "", "```text", S.FORWARD_MESSAGE, "```", "", "## Reminder", "", "```text", S.REMINDER_MESSAGE, "```", "",
              f"Reminders go on days {' and '.join(str(d) for d in S.DEFAULT_REMINDERS)} by default. Each link lasts {S.LINK_DAYS} days and can be forwarded "
              f"to up to {S.MAX_FORWARDS} colleagues.", "", "## Shown at the foot of the questionnaire", "", S.FOOTER, "", S.PRIVACY, ""]
    data = "\n".join(emails)
    out.write("Futran", g, s, "Scoping questionnaire emails.md", data, "The default email, forwarding email and reminder that carry the client's questionnaire link.")
    out.write("Client", "Before the engagement", "Scoping questionnaire link", "Scoping questionnaire email.md", data,
              "The email that brings the personal questionnaire link, the email a forwarded colleague receives, and the reminder.")

    client_qs = [q for q in qs if not q.internal_only and q.client_visible and q.active]  # as the client link shows them (scoping.sending.view)
    md = ["# A few questions to scope your AI compliance review", "",
          "Futran Solutions sends these questions on a personal link before preparing a proposal. \"Not sure\" is a fine answer to any question, and "
          "your answers are saved as you go. The sales rep chooses which of these questions to send.", ""]
    for sc in dict.fromkeys(q.section for q in client_qs):
        md += [f"## {bank.SECTION_LABELS.get(sc, sc)}", ""]
        for q in (q for q in client_qs if q.section == sc):
            md += [f"### {q.client_label or q.label}", "", f"*{SCOPING_TYPES.get(q.type, q.type).replace(' (total of the counts above)', '')}*", ""]
            if q.options:
                md += [f"- [ ] {o['label']}" for o in q.options]
            elif q.type in ("count", "total"):
                md.append("Number: ____________")
            else:
                md.append("_______________________________________________")
            md += ["- [ ] Not sure", ""]
    md += ["---", "", S.FOOTER, "", S.PRIVACY]
    out.write("Client", "Before the engagement", "Scoping questionnaire link", "Scoping questionnaire.docx", docx("\n".join(md), "Scoping questionnaire"),
              f"The {len(client_qs)} questions a prospect can be asked on the personal scoping link, by section. Internal questions, rep notes and prices are not included.")


def proposals(out: Out, db) -> None:
    from app.cli import _futran_org
    from app.proposals import document as D
    from app.proposals import service as P
    from app.proposals import templates as T
    from app.sales.models import Opportunity
    from app.sales.prospects import create_prospect
    from app.tenancy.service import create_user

    g, s = "Sales", "Proposals"
    md = ["# Proposal section templates", "", f"Each new proposal copies this wording into its own sections; later edits never change a proposal already drafted. "
          f"Merge fields: {', '.join(f'[{m}]' for m in T.MERGE_FIELDS)}. Edited on Price list › Proposal templates.", ""]
    for t in T.all_templates(db):
        md += [f"## {t.title}", "", f"*{'Always in the proposal' if t.key in ('cover', 'pricing', 'acceptance', 'independence') else 'Can be switched off'}.*", "",
               "```text", t.body, "```", ""]
        if T.AUTO.get(t.key):
            md += [f"Added by the platform: {T.AUTO[t.key]}", ""]
    out.write("Futran", g, s, "Proposal section templates.md", "\n".join(md),
              "The wording of each proposal section, the merge fields, and what the platform adds to each section automatically.")

    # A sample proposal built by the proposal service itself from the starter "Governed" package, in the throwaway database.
    rep = create_user(db, _futran_org(db), name="[Rep name]", email="rep@example.invalid")
    prospect = create_prospect(db, name="Example Prospect Inc.")
    opp = Opportunity(organization_id=prospect.id, trigger="manual", service="AI governance audit", name="Example Prospect Inc.", stage="scoping", owner_id=rep.id)
    db.add(opp)
    db.flush()
    p = P.create_blank(db, opp, rep, package="governed")
    purpose = ("Example of the proposal document the platform generates (here from the starter Governed package at starter prices, for an example "
               "prospect). Futran only: the client receives its own copy through the acceptance link.")
    out.write("Futran", g, s, "Sample proposal (Governed package).pdf", D.to_pdf(db, p), purpose)
    out.write("Futran", g, s, "Sample proposal (Governed package).docx", D.to_docx(db, p), purpose)


# ---------------------------------------------------------------- Release 2: service templates, billing, agent assurance


def service_templates(out: Out, db) -> None:
    from sqlalchemy import select

    from app.servicetemplates import service as ST
    from app.servicetemplates.models import ServiceTemplate
    from app.servicetemplates.types import ENGAGEMENT_TYPES

    g, s = "Administration", "Service templates"
    tpls, secs, checks, ques, dates = [], [], [], [], []
    for key, (name, content, codes, owner) in ST.BUILTIN.items():
        tpls.append([ENGAGEMENT_TYPES[key], name, owner, "Built in", content, ", ".join(codes), ""])
    for tpl in db.scalars(select(ServiceTemplate).order_by(ServiceTemplate.name)):
        label = ENGAGEMENT_TYPES.get(tpl.engagement_type, tpl.engagement_type)
        v = (ST.versions(db, tpl) or [None])[0]
        status = f"{v.version} {ST.STATUS_LABELS.get(v.status, v.status)}" if v else "No version yet"
        tpls.append([label, tpl.name, tpl.content_owner, status, tpl.note or "", ", ".join(v.catalog_codes or []) if v else "", v.report_template or "" if v else ""])
        md = [f"# {tpl.name}", "", f"- Engagement type: {label}", f"- Content owner: {tpl.content_owner}", f"- Version: {status}"]
        if tpl.note:
            md.append(f"- Note: {tpl.note}")
        if v is None:
            md += ["", "No content yet: the content owner supplies it, and the Futran Admin writes it here for the Chief Auditor to approve.", ""]
        else:
            md += [f"- Price list codes: {', '.join(v.catalog_codes or []) or 'none'}", f"- Report template: {v.report_template or 'not set'}",
                   f"- Change note: {v.change_note or ''}", "", "## Sections", ""]
            for sec in v.sections or []:
                secs.append([tpl.name, sec.get("code"), sec.get("title"), sec.get("note") or ""])
                md += [f"### {sec.get('code')} {sec.get('title')}", ""] + ([sec["note"], ""] if sec.get("note") else [])
                items = [c for c in v.checklists or [] if c.get("section") == sec.get("code")]
                md += [f"- [ ] {c.get('text')}" + (" (evidence)" if c.get("evidence") else "") for c in items] + ([""] if items else [])
            for c in v.checklists or []:
                checks.append([tpl.name, c.get("section"), c.get("code"), c.get("text"), "Yes" if c.get("evidence") else ""])
            qrows = ST.questions(db, v)
            if qrows:
                md += ["## Questions (from the question bank)", ""] + [f"- {q['code']} {q['label']}" for q in qrows] + [""]
                ques += [[tpl.name, q["code"], q["section_title"], q["label"]] for q in qrows]
            md += ["## Deliverables", ""] + ([f"- {d}" for d in v.deliverables] if v.deliverables else ["None listed yet."]) + [""]
            md += ["## Default stages", ""] + ([f"1. {d}" for d in v.default_stages] if v.default_stages else ["None listed yet."]) + [""]
            if v.key_dates:
                md += ["## Key dates", ""] + [f"- {d['label']}: {d['date']} ({d.get('source', '')})" for d in v.key_dates] + [""]
                dates += [[tpl.name, d["label"], d["date"], d.get("source", "")] for d in v.key_dates]
        out.write("Futran", g, s, f"Service template - {label.replace('/', '-')}.md", "\n".join(md),
                  f"The {label} service template: sections, checklists, questions, deliverables and stages as the platform holds them.")
    out.write("Futran", g, s, "Service templates.xlsx",
              xlsx([("Templates", ["Engagement type", "Template", "Content owner", "Version", "Note", "Price list codes", "Report template"], tpls, [34, 36, 18, 24, 60, 30, 20]),
                    ("Sections", ["Template", "Code", "Section", "Note"], secs, [36, 16, 60, 60]),
                    ("Checklists", ["Template", "Section", "Code", "Item", "Evidence"], checks, [36, 16, 26, 80, 10]),
                    ("Questions", ["Template", "Code", "Question bank section", "Question"], ques, [36, 10, 30, 80]),
                    ("Key dates", ["Template", "Date for", "Date", "Source"], dates, [36, 30, 12, 50])]),
              "Every engagement type's service template in one workbook: sections, checklists, questions and key dates.")


def agent_assure(out: Out, db) -> None:
    from app.assurance import service as A
    from app.assurance.models import CHECK_RESULTS, DEPLOYMENTS, SEVERITIES
    from app.impact.triggers import TYPE_LABELS

    results = ", ".join(r.replace("_", " ") for r in CHECK_RESULTS)
    rows = [[c["position"], c["text"] or "", "", "", ""] for c in A.checklist(db)]
    out.write("Futran", "Administration", "Service templates", "Agent Assure 15-point check (blank).xlsx",
              xlsx([("15-point check", ["Point", "Check item", f"Result ({results})", "Condition or note", "Due"], rows, [8, 70, 26, 50, 14])]),
              f"The Agent Assure pre-deploy check as the platform holds it: {A.CHECKLIST_NOTE}")
    triggers = " or ".join(TYPE_LABELS.get(t, t).lower() for t in A.RECERT_TRIGGERS)
    md = ["# Agent Assure record", "", "One record per release of an agent, on the AI system's Assurance tab. The latest record sets the agent's Agent Assure status.", "",
          "## Release", "", "- Release (for example v1.2)", "- Model and version tested", "", "## Gold evaluation set", "", "- Version", "- Number of cases", "- Owner", "",
          "## 15-point pre-deploy check", "", A.CHECKLIST_NOTE, "", f"Each point: result ({results}), condition or note, due date.", ""]
    md += [f"{c['position']}. {c['text'] or '(blank until supplied)'}" for c in A.checklist(db)] + ["", "## Red-team results", "",
           f"Each scenario: what happened, severity ({', '.join(SEVERITIES)}).", "", "## Outcome", ""] + [f"- {v}" for v in A.OUTCOME_LABELS.values()] + [
           "", "## Assurance letter", "", "- Signed by", "- Date signed", "- Letter (PDF)", "", "## Status shown on the AI system", ""] + [f"- {v}" for v in A.STATUS_LABELS.values()] + [
           "", f"A new record is needed after a {triggers}.", ""]
    record = "\n".join(md)
    out.write("Futran", "Home and work", "Clients/Agent Assure", "Agent Assure record form.md", record,
              "The fields a Futran auditor records for each release of an agent: evaluation set, 15-point check, red team, outcome and signed letter.")
    out.write("Client", "AI governance", "AI systems", "Agent Assure record fields.md", record,
              "What the Assurance tab of an agent's record shows: each Agent Assure record Futran keeps, its 15-point results, red-team results, outcome and letter.")
    header = [heading(names[0]) for names in A.WARDEN_COLUMNS.values()]
    out.write("Futran", "Home and work", "Clients/Agent Assure", "AgentWarden licence sync template.csv", csv_text(header),
              "Columns of the AgentWarden licence CSV synced for a client (until the AgentWarden API exists). The Agent column holds the register reference "
              f"(AIS-001) or the agent's name; Deployment is {' or '.join(DEPLOYMENTS)}.")


def billing(out: Out) -> None:
    from app.commercial.plans import COLUMNS
    from app.documents.csvsafe import to_csv

    out.write("Futran", "Administration", "Billing export", "Billing export template.csv", to_csv(COLUMNS, []),
              "The header row of the monthly billing export CSV, one row per order line, milestone, overage, retainer hours or partner commission.")


def end_clients(out: Out) -> None:
    from app.hierarchy.models import RELATIONSHIP_LABELS
    from app.hierarchy.service import parse_end_clients

    data = csv_text(["name", "relationship", "ll144_in_scope", "roles_note"],
                    [["[End-client name]", "end_client", "yes", "NYC roles only"], ["[Subsidiary name]", "subsidiary", "", ""]])
    rows, errors = parse_end_clients(data.encode())
    assert rows and not errors, errors
    out.write("Futran", "Home and work", "Clients/Client hierarchy", "End-client import template.csv", data,
              f"CSV for adding a client's subsidiaries and end-clients in bulk, with two example rows. Relationship: {', '.join(RELATIONSHIP_LABELS)}.")


# ---------------------------------------------------------------- Release 2: engagement workspaces


def copilot(out: Out) -> None:
    import yaml

    from app.copilot_readiness import imports as C
    from app.copilot_readiness import service as CS
    from app.reference.jurisdictions import SEEDS

    g, s = "Home and work", "Clients/Copilot readiness"
    md = ["# Copilot readiness imports: columns", "", "Upload each admin export unchanged, as CSV or Excel. Column names are matched without regard to case; "
          "the first name listed is the one in the template.", ""]
    for kind, spec in C.KINDS.items():
        header = [heading(a) for _f, (_d, aliases) in spec["required"].items() for a in aliases[:1]]
        for aliases in spec["optional"].values():
            h = heading(aliases[0])
            if h.lower() not in (x.lower() for x in header):
                header.append(h)
        found = C.columns(kind, [C._norm(h) for h in header])
        assert all(v is not None for v in found.values()), kind
        out.write("Futran", g, s, f"{spec['label']} template.csv", csv_text(header),
                  f"Columns the platform reads from the {spec['label']} ({spec['source']}).")
        md += [f"## {spec['label']}", "", f"From {spec['source']}.", "", "| Field | Required | Column names accepted |", "|---|---|---|"]
        md += [f"| {d} | Yes | {', '.join(a)} |" for _f, (d, a) in spec["required"].items()]
        md += [f"| {f.replace('_', ' ').capitalize()} | | {', '.join(a)} |" for f, a in spec["optional"].items()] + [""]
    out.write("Futran", g, s, "Copilot readiness import column guide.md", "\n".join(md), "Every column each Copilot readiness import reads, with the other names it accepts.")
    controls = yaml.safe_load((SEEDS / "copilot_readiness.yaml").read_text())["controls"]
    out.write("Futran", g, s, "Copilot readiness controls checklist.xlsx",
              xlsx([("Controls", ["Phase", "Control", "Status", "Note"], [[CS.PHASE_LABELS[c["phase"]], c["label"], "", ""] for c in controls], [12, 60, 18, 50]),
                    ("Status values", ["Status"], [[v] for v in CS.CONTROL_LABELS.values()], [20])]),
              "The default controls checklist a Copilot readiness workspace starts with (the approved service template's list is used instead when there is one).")
    site = ["# Copilot readiness: site list", "", "Futran builds the site list from the Purview and SharePoint reports and rates each site's risk. "
            "The Chief AI Compliance Officer sees the list on AI governance › Copilot readiness and can change three fields on each site.", "",
            "## Shown for each site", "", "- Site name and address", "- Site owner", "- Sharing: " + ", ".join(CS.SHARING_LABELS.values()),
            "- Sensitive items", "- Sensitivity label coverage (%)", "- Last activity", "- Risk: High, Medium or Low",
            "- Action: " + ", ".join(CS.ACTION_LABELS.values()), "", "## What the Chief AI Compliance Officer updates", ""]
    names = {"action_owner": "Action owner (name)", "status": "Status: " + ", ".join(CS.STATUS_LABELS.values()), "note": "Note"}
    site += [f"- {names[f]}" for f in sorted(CS.CLIENT_SITE_FIELDS, key=list(names).index)] + [""]
    out.write("Client", "AI governance", "Copilot readiness", "Copilot readiness site list fields.md", "\n".join(site),
              "The fields on the Copilot readiness site list and the three the Chief AI Compliance Officer updates (there is no upload template for them).")


def eu_ai_act(out: Out) -> None:
    from app.euaiact import rules as R
    from app.euaiact import service as E
    from app.euaiact.models import SECTION_STATUSES

    g, s = "Home and work", "Clients/EU AI Act"
    data = R.data()
    roles, classes = R.roles(), R.classifications()

    def who(values, names):
        return "All" if values == "all" else ", ".join(names.get(v, v) for v in values or [])

    rows = [[o["article"], o["title"], who(o["when"].get("roles"), roles), who(o["when"].get("classifications"), classes),
             "Yes" if o.get("annex_iv") else "", "Only when a FRIA is required" if o.get("fria") else "", "", "", ""] for o in data["obligations"]]
    deadlines = [[classes.get(k, k), str(v["date"]), v.get("source", "")] for k, v in data["deadlines"].items()]
    areas = [[a["label"], "Yes, for any deployer" if a.get("fria") else ("Never (Art. 27(1))" if a.get("no_fria") else "Public bodies and public services")]
             for a in data["annex_iii_areas"].values()]
    out.write("Futran", g, s, "EU AI Act obligations checklist.xlsx",
              xlsx([("Obligations", ["Article", "Obligation", "Applies to roles", "Classifications", "Annex IV tracker", "FRIA", "Status", "Evidence", "Note"], rows,
                     [16, 60, 40, 50, 10, 24, 16, 30, 40]),
                    ("Status values", ["Status"], [[v] for v in E.OBLIGATION_LABELS.values()], [20]),
                    ("Deadlines", ["Classification", "Date", "Source"], deadlines, [36, 12, 80]),
                    ("Annex III areas", ["Area", "FRIA for a deployer"], areas, [60, 36])]),
              f"Every obligation the EU AI Act workspace can list, with the roles and classifications it applies to and the deadlines. {data['banner']}")
    status = ", ".join(x.replace("_", " ").capitalize() for x in SECTION_STATUSES)
    out.write("Futran", g, s, "Annex IV technical documentation tracker.xlsx",
              xlsx([("Annex IV", ["Point", f"Status ({status})", "Note", "Evidence"], [[a["label"], "", "", ""] for a in data["annex_iv"]], [70, 30, 50, 30])]),
              "The nine points of Annex IV tracked for a provider of a high-risk system (Art. 11).")
    fria_any = [a["label"] for a in data["annex_iii_areas"].values() if a.get("fria")]
    fria_never = [a["label"] for a in data["annex_iii_areas"].values() if a.get("no_fria")]
    md = ["# Fundamental rights impact assessment (FRIA)", "", "EU AI Act Art. 27. Completed before first use by a deployer of an Annex III high-risk system that "
          f"is a public body or provides public services, and by any deployer of a system in: {'; '.join(fria_any)}. Never for: {'; '.join(fria_never)}.", ""]
    for q in data["fria"]:
        md += [f"## {q['label']}", "", "_______________________________________________", ""]
    md += ["## Status", "", status]
    out.write("Futran", g, s, "Fundamental rights impact assessment (FRIA) template.docx", docx("\n".join(md), "Fundamental rights impact assessment"),
              "The FRIA questions (Art. 27(1)(a) to (f) and the notification) as the EU AI Act workspace asks them, with when a FRIA is required.")


def discovery(out: Out) -> None:
    from app.connectors import manual_import as mi

    intro = ["Upload a standard admin export as CSV or Excel. The platform guesses which column holds each field from the headings below (matched "
             "without regard to case), shows the mapping and a preview, and you can change the mapping or save it as a preset.", ""]
    client = ["# Discovery import: columns", ""] + intro
    futran = ["# Discovery import: columns", ""] + intro
    for t in mi.EXPORT_TYPES.values():
        header = [heading(f.aliases[0]) for f in t.fields]
        assert all(mi.guess_mapping(t, header).values()), t.key  # every field found from the template's own headings
        data = csv_text(header)
        purpose = f"Column headings for the {t.label} export from {t.source}." + (" Only the AI vendor rows are kept." if t.summary_only else "")
        out.write("Futran", "Home and work", "Clients/Discovery import", f"{t.label} template.csv", data, purpose)
        out.write("Client", "Data and integrations", "Integrations", f"{t.label} template.csv", data, purpose)
        table = [f"## {t.label}", "", f"From {t.source}. Read for: {t.parsed_into}." + (" Only the rows for AI vendors are kept; the file itself is not." if t.summary_only else ""),
                 "", "| Field | Required | Column names accepted |", "|---|---|---|"] + [f"| {f.label} | {'Yes' if f.required else ''} | {', '.join(f.aliases)} |" for f in t.fields] + [""]
        client += table
        futran += table + [f"Recorded in the AI inventory as account type: {t.account_type.replace('_', ' ')}." + ("" if t.keep_people else " People's names are not kept."), ""]
    futran += ["## Findings for Sales (never shown to the client)", "", "| Finding | Opportunity opened when a tool is confirmed |", "|---|---|"]
    futran += [f"| {k.replace('_', ' ').capitalize()} | {svc} |" for k, (svc, _kind) in mi.FINDINGS.items()] + [""]
    out.write("Futran", "Home and work", "Clients/Discovery import", "Discovery import column guide.md", "\n".join(futran),
              "Each of the seven export types: the fields read, the column names accepted, and the sales findings each import can raise. Futran only.")
    out.write("Client", "Data and integrations", "Integrations", "Discovery import column guide.md", "\n".join(client),
              "Each of the seven admin exports the Client Admin can import from Integrations, with the fields read and the column names accepted.")


# ---------------------------------------------------------------- README


CLIENT_INTRO = ("Forms and templates the client side of the Futran Audit Platform asks people to fill in, or sends them. Folders follow the client menu: "
                "menu group, then screen. Documents marked (example) show what the platform generates, with client details in square brackets. "
                "Before the engagement › Scoping questionnaire link holds what a prospect receives on the personal link Futran's sales team sends: "
                "the client questions only, with no internal questions, rep notes or prices.")
FUTRAN_INTRO = ("Forms and templates for Futran staff, including the confidential copies clients never receive: quiz answer keys, auditor-only questions "
                "and guidance, the scoring method, template sources and internal rules. Folders follow the Futran menu; material that belongs to a client "
                "screen (Audit › Documents, AI governance › AI systems, People and training › Attestation and AI literacy training) "
                "uses the client menu's group and screen names. The engagement workspaces reached from Home and work › Clients (Copilot readiness, "
                "EU AI Act, Agent Assure, Discovery import, Client hierarchy) each have a folder under Clients. Sales › Scoping holds the scoping "
                "question bank and mapping rules (edited on the Price list's Question bank and Mapping rules tabs, used from Opportunities). "
                "Prices, internal scoping questions and sales findings are in this folder only.")


def readme(out: Out, side: str) -> str:
    entries = [e for e in out.entries if e.side == side]
    lines = ["---", f"title: Forms and templates ({side})", f"generated: {date.today().isoformat()}", "tags: [futran-audit-platform, forms-and-templates, "
             f"{side.lower()}]", f"files: {len(entries)}", "---", "", f"# Forms and templates: {side}", "", CLIENT_INTRO if side == "Client" else FUTRAN_INTRO, "",
             "Generated by `python -m scripts.export_forms` from the application's own seeds and generators. Run it again after a release to refresh.", ""]
    for group in dict.fromkeys(e.group for e in entries):
        lines += [f"## {group}", ""]
        for screen in dict.fromkeys(e.screen for e in entries if e.group == group):
            lines += [f"### {screen.replace('/', ' › ')}", "", "| File | Section | What it is for |", "|---|---|---|"]
            for e in (e for e in entries if e.group == group and e.screen == screen):
                path = f"{e.group}/{e.screen}/{e.name}"
                lines.append(f"| [[{path}\\|{e.name}]] | {e.group} › {e.screen.replace('/', ' › ')} | {cell(e.purpose)} |")
            lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- main


def export(out_dir: Path) -> Out:
    root = Path(out_dir) / ROOT_NAME
    if root.exists():
        import shutil

        shutil.rmtree(root)  # a fresh tree each run, so removed forms do not linger
    out = Out(root)
    from sqlalchemy import select

    from app.catalog.models import CatalogItem

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
        price_list(out, db)
        scoping(out, db, {i.code: i.name for i in db.scalars(select(CatalogItem))})
        proposals(out, db)
        service_templates(out, db)
        agent_assure(out, db)
        billing(out)
        end_clients(out)
        copilot(out)
        eu_ai_act(out)
        discovery(out)
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
