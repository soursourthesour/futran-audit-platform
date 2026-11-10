"""The department workbook (11-03 review C5): instructions, the department list, and one sheet of people per department,
filled from what the client already has so it can be added to and uploaded again."""
import io

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documents.csvsafe import FORMULA_START
from app.policy.roles import CSV_ROLE_NAMES, ROLE_LABELS
from app.tenancy import people as ppl
from app.tenancy.csv_import import DEPARTMENT_HEADER, DEPARTMENT_ROLES, USER_HEADER
from app.tenancy.job_levels import JOB_LEVELS
from app.tenancy.models import Organization, User
from app.tenancy.people_import import COMPANY_WIDE, sheet_title
from app.tenancy.service import roles_of

ROWS = 1000  # rows that carry the drop-down lists
HEAD = Font(bold=True, color="FFFFFF")
FILL = PatternFill("solid", fgColor="1F3A5F")
EXAMPLE = Font(italic=True, color="7A7A7A")
EXAMPLE_PEOPLE = {
    "Human Resources": ["Priya Shah", "priya.shah@example.com", "Human Resources", "Head of HR", "Department head", "Department Compliance Lead"],
    "Talent Acquisition": ["Tom Reyes", "tom.reyes@example.com", "Talent Acquisition", "Recruiter", "Level 2", "Contributor"],
}
EXAMPLE_COMPANY_WIDE = ["Sam Lee", "sam.lee@example.com", None, "Chief Risk Officer", "Executive", ROLE_LABELS["caico"]]
ROLE_NAMES = [ROLE_LABELS[r] for r in dict.fromkeys(CSV_ROLE_NAMES.values())]

USER_HELP = {
    "Full name": "The person's first and last name.",
    "Work email": "Their work email. The invitation goes here, and it is how the platform recognises them later.",
    "Department": "Leave blank on a department's own sheet: the sheet's department is used.",
    "Job title": "Their working title at the company, for example Recruiting Manager.",
    "Job level": "Executive, Department head, Manager, Level 3, Level 2 or Level 1.",
    "AI compliance role": "The role they hold in this AI governance audit. Separate two roles with a semicolon.",
}
DEPT_HELP = {
    "Department": "The department's name as people at the company know it.",
    "Parent department": "Optional. The department this one sits under; it must be on this list.",
    "Head of department": "Optional. The head's work email, or their full name exactly as on the user list.",
    "Headcount": "Optional. How many people work in the department.",
}

INSTRUCTIONS = [
    ("How to use this workbook", None),
    ("1. On the Departments sheet, list every department, one per row. Add parent departments and heads if you have them.", None),
    ("2. Each department has its own sheet of people. To add a department, add it to the Departments sheet, then copy any department sheet, rename the copy to the department's name and replace the rows.", None),
    ("3. On each department sheet, list the people who need a login: one row per person. Leave Department blank to use the sheet's department.", None),
    (f"4. On the {COMPANY_WIDE} sheet, list people who are not in any department, such as the Client Admin, Chief AI Compliance Officer, Executive Sponsor or Data Protection Officer. Leave Department blank there: they are imported with no department. Department Compliance Leads and Contributors belong on a department's sheet.", None),
    ("5. Upload the workbook on People > Departments. Everything is checked first and shown to you; nothing is imported until every row is correct.", None),
    ("6. To add people to one department only, use Upload users to this department on that department's row, with this workbook or a CSV.", None),
    ("", None),
    ("Example rows (shown in grey, with example.com emails) are refused if uploaded. Delete them or replace them with real people.", None),
    ("People already on the user list are recognised by work email. Uploading them again adds any new AI compliance role and fills a blank job title or job level; it never moves them to another department or removes anything. A Department Compliance Lead or Contributor role for a department other than their own is not added; move them on the People screen first.", None),
    ("The head of department is matched by work email first, then by exact full name. A name that matches nobody, or more than one person, is listed as a warning and the head is left as it was.", None),
    ("", None),
    ("Columns on the Departments sheet", "bold"),
    *[(f"{k}: {v}", None) for k, v in DEPT_HELP.items()],
    ("", None),
    (f"Columns on each department sheet and the {COMPANY_WIDE} sheet", "bold"),
    *[(f"{k}: {v}", None) for k, v in USER_HELP.items()],
    ("", None),
    ("Job levels", "bold"),
    (", ".join(JOB_LEVELS.values()), None),
    ("AI compliance roles", "bold"),
    *[(r, None) for r in ROLE_NAMES],
]


def _as_text(ws) -> None:
    """Values that start like a formula (= + - @, tab or return) stay text in the last row written, so the workbook
    never runs anything and uploads back with the same values (OWASP CSV injection; FORMULA_START as in csvsafe)."""
    for c in ws[ws.max_row]:
        if isinstance(c.value, str) and c.value.startswith(FORMULA_START):
            c.data_type = "s"
            c.quotePrefix = True


def _append(ws, values: list) -> None:
    ws.append(values)
    _as_text(ws)


def _header(ws, names: list[str], help_text: dict[str, str], widths: list[int]) -> None:
    ws.append(names)
    for i, cell in enumerate(ws[1], start=1):
        cell.font, cell.fill = HEAD, FILL
        cell.alignment = Alignment(vertical="center")
        cell.comment = Comment(help_text[names[i - 1]], "Futran")
        ws.column_dimensions[cell.column_letter].width = widths[i - 1]
    ws.freeze_panes = "A2"


def _list(formula: str, prompt: str, strict: bool = True) -> DataValidation:
    dv = DataValidation(type="list", formula1=formula, allow_blank=True, showDropDown=False, showErrorMessage=True,
                        errorStyle="stop" if strict else "warning", promptTitle=None, prompt=prompt, showInputMessage=True)
    dv.error = "Choose a value from the list."
    return dv


def _people_sheet(wb: Workbook, title: str, dept: str | None, rows: list[list], example: bool) -> None:
    ws = wb.create_sheet(title)
    _header(ws, USER_HEADER, USER_HELP, [26, 32, 22, 28, 16, 34])
    for r in rows:
        _append(ws, r)
        if example:
            for c in ws[ws.max_row]:
                c.font = EXAMPLE
    rng = lambda col: f"{col}2:{col}{ROWS}"  # noqa: E731
    dv = _list(f"Departments!$A$2:$A${ROWS}", f"Blank means {dept}." if dept else "Leave blank: people on this sheet have no department.")
    dv.add(rng("C"))
    lv = _list('"' + ",".join(JOB_LEVELS.values()) + '"', "Executive, Department head, Manager, Level 3, Level 2 or Level 1.")
    lv.add(rng("E"))
    rl = _list('"' + ",".join(ROLE_NAMES) + '"', "Two roles: separate them with a semicolon.", strict=False)
    rl.add(rng("F"))
    for v in (dv, lv, rl):
        ws.add_data_validation(v)


def department_workbook(db: Session, org: Organization) -> bytes:
    wb = Workbook()
    ins = wb.active
    ins.title = "Instructions"
    ins.column_dimensions["A"].width = 130
    _append(ins, [f"{org.name}: departments and people"])
    ins["A1"].font = Font(bold=True, size=14)
    ins.append([])
    for text, style in INSTRUCTIONS:
        ins.append([text])
        cell = ins.cell(row=ins.max_row, column=1)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        if style == "bold":
            cell.font = Font(bold=True)

    ds = wb.create_sheet("Departments")
    _header(ds, DEPARTMENT_HEADER, DEPT_HELP, [34, 34, 36, 12])
    depts = ppl.departments(db, org)
    names = {d.id: d.name for d in depts}
    example = False
    if depts:
        for d in depts:
            _append(ds, [d.name, names.get(d.parent_id) if d.parent_id else None, d.head_email or d.head_name, d.headcount])
        sheets = [(d.name, d) for d in depts]
    else:
        e = ppl.current_engagement(db, org)
        scope = [n for n in ((e.wizard_state or {}).get("departments") or [] if e else []) if str(n).strip()]
        if scope:
            for n in scope:
                _append(ds, [n, None, None, None])
            sheets = [(n, None) for n in scope]
        else:
            example = True
            ds.append(["Human Resources", None, "priya.shah@example.com", 14])
            ds.append(["Talent Acquisition", "Human Resources", "Priya Shah", 6])
            for c in (*ds[2], *ds[3]):
                c.font = EXAMPLE
            sheets = [("Human Resources", None), ("Talent Acquisition", None)]
    pv = _list(f"$A$2:$A${ROWS}", "A department on this list.")
    pv.add(f"B2:B{ROWS}")
    hc = DataValidation(type="whole", operator="greaterThanOrEqual", formula1="0", allow_blank=True, showErrorMessage=True)
    hc.error = "Headcount must be a whole number."
    hc.add(f"D2:D{ROWS}")
    ds.add_data_validation(pv)
    ds.add_data_validation(hc)

    used = {"instructions", "departments", "history", COMPANY_WIDE.casefold()}  # Excel keeps "History" for itself
    users = list(db.scalars(select(User).where(User.organization_id == org.id, User.deleted_at.is_(None), User.status != "disabled").order_by(User.name)))
    if example:
        company = [EXAMPLE_COMPANY_WIDE]
    else:
        company = [[u.name, u.email, None, u.job_title, JOB_LEVELS.get(u.job_level) if u.job_level else None,
                    "; ".join(dict.fromkeys(ROLE_LABELS[r.role] for r in roles_of(db, u.id) if r.role in ROLE_LABELS and r.scope_type == "org")) or None]
                   for u in users if ppl.user_department(db, u, names) is None]
    _people_sheet(wb, COMPANY_WIDE, None, company, example)
    for name, d in sheets:
        title, i = sheet_title(name), 2
        while title.casefold() in used:
            suffix = f" ({i})"
            title, i = sheet_title(name)[: 31 - len(suffix)] + suffix, i + 1
        used.add(title.casefold())
        rows = []
        if d is not None:
            for u in users:
                if ppl.user_department(db, u, names) != d.name:
                    continue
                roles = [ROLE_LABELS[r.role] for r in roles_of(db, u.id)
                         if r.role in ROLE_LABELS and (r.scope_type == "org" or (r.role in DEPARTMENT_ROLES and r.scope_id == d.id))]
                rows.append([u.name, u.email, d.name, u.job_title, JOB_LEVELS.get(u.job_level) if u.job_level else None, "; ".join(dict.fromkeys(roles)) or None])
        elif example:
            rows = [EXAMPLE_PEOPLE[name]]
        _people_sheet(wb, title, name, rows, example)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
