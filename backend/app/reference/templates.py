"""Versioned document templates (Markdown + Jinja). Admin edits create a new version."""
import yaml
from jinja2 import StrictUndefined, TemplateSyntaxError, Undefined
from jinja2.exceptions import SecurityError
from jinja2.sandbox import ImmutableSandboxedEnvironment
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.errors import Invalid, NotFound
from app.reference.jurisdictions import SEEDS
from app.reference.models import DocumentTemplate
from app.tenancy.models import User

TEMPLATE_DIR = SEEDS / "templates"


class _Lenient(Undefined):
    """Missing merge fields render as blank instead of failing the whole document."""

    def __str__(self):
        return ""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self

    def __getitem__(self, key):
        return self

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return False


class _Sandbox(ImmutableSandboxedEnvironment):
    """Admins edit templates in the browser, so templates never reach Python internals or mutate data."""

    def unsafe_undefined(self, obj, attribute):
        raise SecurityError(f"Templates cannot use '{attribute}'.")


MD_SPECIAL = str.maketrans({c: "\\" + c for c in "[]*_`<>"})


def md_inline(value):
    """Escape Markdown that would turn client-supplied text into links, emphasis or code."""
    return value.translate(MD_SPECIAL) if isinstance(value, str) else value


def md_cell(value) -> str:
    """Make a value safe inside a Markdown table cell: no line breaks, pipes escaped."""
    if value is None or isinstance(value, Undefined):
        return ""
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value)
    return " ".join(str(value).split()).replace("|", "\\|")


_env = _Sandbox(undefined=_Lenient, trim_blocks=True, lstrip_blocks=True, autoescape=False, finalize=md_inline)
_env.filters["md_cell"] = md_cell
_strict = _Sandbox(undefined=StrictUndefined)
_strict.filters["md_cell"] = md_cell


def load_templates(db: Session) -> str:
    index = yaml.safe_load((TEMPLATE_DIR / "index.yaml").read_text())["templates"]
    n = 0
    for t in index:
        if db.scalar(select(DocumentTemplate.id).where(DocumentTemplate.key == t["key"]).limit(1)):
            continue
        db.add(DocumentTemplate(
            key=t["key"], name=t["name"], type=t["type"], version=1, body=(TEMPLATE_DIR / f"{t['key']}.md.j2").read_text(),
            package_item=t.get("package_item"), requires_action=t.get("requires_action"), format=t.get("format", "md"), active=True,
        ))
        n += 1
    db.flush()
    return f"{n} templates added"


def active_template(db: Session, key: str) -> DocumentTemplate:
    t = db.scalar(select(DocumentTemplate).where(DocumentTemplate.key == key, DocumentTemplate.active.is_(True)))
    if t is None:
        raise NotFound(f"Template {key} not found.")
    return t


def render_string(body: str, context: dict) -> str:
    return _env.from_string(body).render(**context).strip()


def render_template(db: Session, key: str, context: dict) -> str:
    return render_string(active_template(db, key).body, context)


def edit_template(db: Session, actor: User, key: str, body: str) -> DocumentTemplate:
    try:
        _strict.parse(body)
    except TemplateSyntaxError as exc:
        raise Invalid("The template has a merge-field error.", [{"field": "body", "message": f"Line {exc.lineno}: {exc.message}"}])
    try:
        render_string(body, {})  # test render: missing fields are blank, unsafe or broken expressions fail here, not at generation
    except Exception as exc:
        raise Invalid("The template could not be rendered.", [{"field": "body", "message": str(exc)[:300]}])
    current = active_template(db, key)
    latest = db.scalar(select(func.max(DocumentTemplate.version)).where(DocumentTemplate.key == key)) or 1
    current.active = False
    new = DocumentTemplate(key=key, name=current.name, type=current.type, version=latest + 1, body=body, package_item=current.package_item, requires_action=current.requires_action, format=current.format, active=True, created_by=actor.id)
    db.add(new)
    db.flush()
    audit.record(db, actor_id=actor.id, action="template.edit", object_type="DocumentTemplate", object_id=new.id, organization_id=actor.organization_id, summary=f"Saved {current.name} as version {new.version}")
    return new
