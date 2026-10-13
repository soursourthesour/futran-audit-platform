"""Versioned document templates (Markdown + Jinja). Admin edits create a new version."""
import yaml
from jinja2 import Environment, StrictUndefined, TemplateSyntaxError, Undefined
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
        return self

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return False


_env = Environment(undefined=_Lenient, trim_blocks=True, lstrip_blocks=True, autoescape=False)
_strict = Environment(undefined=StrictUndefined)


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
    current = active_template(db, key)
    latest = db.scalar(select(func.max(DocumentTemplate.version)).where(DocumentTemplate.key == key)) or 1
    current.active = False
    new = DocumentTemplate(key=key, name=current.name, type=current.type, version=latest + 1, body=body, package_item=current.package_item, requires_action=current.requires_action, format=current.format, active=True, created_by=actor.id)
    db.add(new)
    db.flush()
    audit.record(db, actor_id=actor.id, action="template.edit", object_type="DocumentTemplate", object_id=new.id, organization_id=actor.organization_id, summary=f"Saved {current.name} as version {new.version}")
    return new
