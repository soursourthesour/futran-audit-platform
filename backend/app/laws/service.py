"""Law queries and manual edits (Admin > Reference data)."""
import re

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Invalid, NotFound
from app.laws.importer import FEATURE_LABELS, FEATURES, TYPES
from app.laws.models import MatrixVersion, Regulation
from app.reference.models import Jurisdiction
from app.tenancy.models import User

LEVEL_ORDER = {"city": 0, "state": 1, "country": 2, "supranational": 3}


def law_summary(r: Regulation) -> str:
    """A one-line description for pickers: obligations if recorded, else the source text after the name."""
    if r.obligations_text:
        return r.obligations_text
    text = (r.full_text or "").strip()
    paren = ""
    if text.startswith(r.short_name):
        rest = text[len(r.short_name):].lstrip()
        m = re.match(r"^\(([^()]*)\)\s*", rest)
        if m:
            paren, rest = m.group(1).strip(), rest[m.end():]
        rest = rest.lstrip(" :;—-.").strip()
        if rest:
            rest = rest[0].upper() + rest[1:]
            return f"{rest} ({paren})" if paren else rest
    return text or r.short_name


def law_out(r: Regulation, j: Jurisdiction | None = None) -> dict:
    return {
        "id": r.id,
        "jurisdiction_code": j.code if j else None,
        "jurisdiction_name": j.name if j else None,
        "short_name": r.short_name,
        "feature": r.feature,
        "feature_label": FEATURE_LABELS.get(r.feature, r.feature),
        "type": r.type,
        "type_text": r.type_text,
        "category_text": r.category_text,
        "enforcer": r.enforcer,
        "trigger_text": r.trigger_text,
        "obligations_text": r.obligations_text,
        "developments_text": r.developments_text,
        "most_affected": r.most_affected,
        "full_text": r.full_text,
        "summary": law_summary(r),
        "applies_to": r.applies_to,
        "verify_flag": r.verify_flag,
        "public_summary": r.public_summary,
        "origin": r.origin,
        "matrix_version_id": r.matrix_version_id,
    }


def search_laws(
    db: Session,
    codes: list[str] | None,
    feature: str | None = None,
    q: str | None = None,
    exclude_developer: bool = False,
) -> list[dict]:
    """Current laws grouped by jurisdiction, ordered as `codes` (or city → supranational when all)."""
    stmt = (
        select(Regulation, Jurisdiction)
        .join(Jurisdiction, Jurisdiction.id == Regulation.jurisdiction_id)
        .where(Regulation.superseded_by_id.is_(None), Regulation.retired_in_version_id.is_(None))
    )
    if codes:
        stmt = stmt.where(Jurisdiction.code.in_(codes))
    if feature:
        stmt = stmt.where(Regulation.feature == feature)
    if exclude_developer:
        stmt = stmt.where(Regulation.applies_to != "developer")
    if q:
        for word in re.findall(r"\w+", q.lower())[:6]:
            like = f"%{word}%"
            stmt = stmt.where(or_(Regulation.short_name.ilike(like), Regulation.full_text.ilike(like), Regulation.obligations_text.ilike(like), Jurisdiction.name.ilike(like)))
    groups: dict[str, dict] = {}
    for reg, j in db.execute(stmt.order_by(Regulation.short_name)):
        g = groups.setdefault(j.code, {"jurisdiction": {"code": j.code, "name": j.name, "level": j.level}, "laws": []})
        g["laws"].append(law_out(reg, j))
    if codes:
        order = {c: i for i, c in enumerate(codes)}
        return sorted(groups.values(), key=lambda g: order.get(g["jurisdiction"]["code"], 999))
    return sorted(groups.values(), key=lambda g: (g["jurisdiction"]["code"] != "US", LEVEL_ORDER.get(g["jurisdiction"]["level"], 9), g["jurisdiction"]["name"]))


def new_manual_version(db: Session, actor: User, label: str) -> MatrixVersion:
    for old in db.scalars(select(MatrixVersion).where(MatrixVersion.status == "published")):
        old.status = "superseded"
    v = MatrixVersion(label=label, origin="manual", status="published", published_by=actor.id, published_at=utcnow())
    db.add(v)
    db.flush()
    return v


EDITABLE = ["short_name", "feature", "type", "enforcer", "trigger_text", "obligations_text", "developments_text", "most_affected", "full_text", "applies_to", "verify_flag", "public_summary", "effective_date_text", "status_text", "citation"]


def _validate(fields: dict) -> None:
    errors = []
    if "feature" in fields and fields["feature"] not in FEATURES:
        errors.append({"field": "feature", "message": "Choose one of the nine AI features."})
    if "type" in fields and fields["type"] not in TYPES:
        errors.append({"field": "type", "message": "Choose a valid type."})
    if "applies_to" in fields and fields["applies_to"] not in ("deployer", "developer", "both"):
        errors.append({"field": "applies_to", "message": "Choose deployer, developer or both."})
    if "short_name" in fields and not (fields["short_name"] or "").strip():
        errors.append({"field": "short_name", "message": "Give the law a short name."})
    if errors:
        raise Invalid(errors=errors)


def edit_law(db: Session, actor: User, reg_id: str, fields: dict) -> Regulation:
    old = db.get(Regulation, reg_id)
    if old is None or old.superseded_by_id or old.retired_in_version_id:
        raise NotFound("This law has been replaced by a newer version. Reload and try again.")
    fields = {k: v for k, v in fields.items() if k in EDITABLE}
    _validate(fields)
    v = new_manual_version(db, actor, f"Manual edit — {old.short_name[:80]}")
    data = {c.key: getattr(old, c.key) for c in Regulation.__table__.columns if c.key not in ("id", "created_at", "superseded_by_id", "retired_in_version_id")}
    data.update(fields)
    data.update(matrix_version_id=v.id, last_seen_version_id=v.id, origin="manual", updated_by=actor.id)
    new = Regulation(**data)
    db.add(new)
    db.flush()
    old.superseded_by_id = new.id
    from app.laws.publish import carry_forward

    carry_forward(db, old.id, new.id)  # register links, client applicability and sources move to the new row
    audit.record(db, actor_id=actor.id, action="law.edit", object_type="Regulation", object_id=new.id, organization_id=actor.organization_id, before={k: getattr(old, k) for k in fields}, after=fields, summary=f"Edited law {new.short_name}")
    return new


def add_law(db: Session, actor: User, jurisdiction_code: str, fields: dict, version: MatrixVersion | None = None, origin: str = "manual") -> Regulation:
    j = db.scalar(select(Jurisdiction).where(Jurisdiction.code == jurisdiction_code))
    if j is None:
        raise Invalid(errors=[{"field": "jurisdiction_code", "message": "Unknown jurisdiction."}])
    fields = {k: v for k, v in fields.items() if k in EDITABLE}
    fields.setdefault("feature", "government_other")
    fields.setdefault("type", "statute")
    _validate(fields | {"short_name": fields.get("short_name", "")})
    v = version or new_manual_version(db, actor, f"Manual addition — {fields['short_name'][:80]}")
    reg = Regulation(jurisdiction_id=j.id, matrix_version_id=v.id, last_seen_version_id=v.id, origin=origin, updated_by=actor.id, full_text=fields.get("full_text") or fields["short_name"], **{k: v_ for k, v_ in fields.items() if k != "full_text"})
    db.add(reg)
    j.has_laws = True
    db.flush()
    audit.record(db, actor_id=actor.id, action="law.add", object_type="Regulation", object_id=reg.id, organization_id=actor.organization_id, after=fields, summary=f"Added law {reg.short_name}")
    return reg
