"""Law versions: the first version from a matrix row, copying a version forward, and applying approved changes."""
import re

GUIDANCE_TYPES = {"voluntary", "guidance", "policy", "framework"}


def status_from_text(status_text: str | None, reg_type: str | None) -> str:
    """Best first guess at a LawVersion status from the matrix's free text and type (used by the v1 data move)."""
    t = (status_text or "").lower()
    if re.search(r"repeal|lapsed|struck down|vetoed", t):
        return "repealed"
    if re.search(r"delay|postpon|under amendment", t):
        return "delayed"
    if re.search(r"enacted|not yet in force|effective \d|from \d", t) and "in force" not in t:
        return "enacted_not_in_force"
    if "phased" in t:
        return "in_force_phased"
    if reg_type in GUIDANCE_TYPES:
        return "guidance"
    if reg_type == "pending":
        return "pending"
    return "in_force"


VERSION_FIELDS = [
    "status", "signed_on", "effective_on", "compliance_on", "effective_text", "scope_text", "applies_to", "enforcer",
    "private_right_of_action", "penalty_text", "cure_period", "exemptions_text", "removed_text", "litigation_text",
    "main_duty", "verify_flag", "source_ids",
]


def first_version(db, reg, flush: bool = True) -> "LawVersion":
    """Version 1 of a law from its matrix fields (the same move the migration made for existing laws)."""
    from app.core.ids import new_id
    from app.regmaster.models import LawVersion

    applies = {"both": ["developer", "deployer"], "developer": ["developer"]}.get(reg.applies_to or "deployer", ["deployer"])
    v = LawVersion(
        id=new_id(), regulation_id=reg.id, version_no=1, status=status_from_text(reg.status_text, reg.type), effective_text=reg.effective_date_text,
        scope_text=reg.trigger_text, applies_to=applies, enforcer=reg.enforcer, verify_flag=bool(reg.verify_flag),
        change_summary="First record, from the law matrix",
    )
    db.add(v)
    if flush:
        db.flush()
    reg.current_version_id = v.id
    if reg.binding is None:
        reg.binding = reg.type in ("statute", "regulation", "executive")
    return v


def clone_version(db, old, regulation_id: str | None = None, summary: str | None = None, created_by: str | None = None):
    """Copy a version and everything hanging off it to the next version number (§25.3 step 7: maps are versioned)."""
    from sqlalchemy import func, select

    from app.regmaster.models import CommitteeRule, LawRoleMap, LawVersion, Requirement, ScopeTest

    rid = regulation_id or old.regulation_id
    top = db.scalar(select(func.max(LawVersion.version_no)).where(LawVersion.regulation_id == rid)) or 0
    new = LawVersion(regulation_id=rid, version_no=max(top, old.version_no) + 1, change_summary=summary, created_by=created_by, **{f: getattr(old, f) for f in VERSION_FIELDS})
    db.add(new)
    db.flush()
    req_map: dict[str, str] = {}
    for r in db.scalars(select(Requirement).where(Requirement.law_version_id == old.id).order_by(Requirement.order)):
        copy = Requirement(law_version_id=new.id, **{c.key: getattr(r, c.key) for c in Requirement.__table__.columns if c.key not in ("id", "law_version_id")})
        db.add(copy)
        db.flush()
        req_map[r.id] = copy.id
    for m in db.scalars(select(LawRoleMap).where(LawRoleMap.law_version_id == old.id)):
        data = {c.key: getattr(m, c.key) for c in LawRoleMap.__table__.columns if c.key not in ("id", "law_version_id")}
        data["requirement_ids"] = [req_map.get(i, i) for i in (m.requirement_ids or [])]
        db.add(LawRoleMap(law_version_id=new.id, **data))
    for model in (ScopeTest, CommitteeRule):
        for row in db.scalars(select(model).where(model.law_version_id == old.id)):
            db.add(model(law_version_id=new.id, **{c.key: getattr(row, c.key) for c in model.__table__.columns if c.key not in ("id", "law_version_id")}))
    db.flush()
    return new


def deadline_keys(db, reg, deadline, suffix: str | None = None) -> tuple[str, list[str]]:
    """(key, every key that counts as the same) for something sent once per law and deadline: a client's 90- and
    30-day alerts and a Sales opportunity. The key is the law's first row (stable through Reference data edits, which
    replace the row) and the date, so a new version with the same date is not news. Keys written before this used
    the version id ("date:<version id>[:<mark>]"); those still count for any version of the law with this date."""
    from sqlalchemy import or_, select

    from app.laws.publish import chain_ids
    from app.regmaster.models import LawVersion

    ids = chain_ids(db, reg.id) or [reg.id]
    tail = f":{suffix}" if suffix else ""
    key = f"date:{ids[0]}:{deadline.isoformat()}{tail}"
    same = db.scalars(select(LawVersion.id).where(LawVersion.regulation_id.in_(ids), or_(LawVersion.compliance_on == deadline,
                                                                                          (LawVersion.compliance_on.is_(None)) & (LawVersion.effective_on == deadline))))
    return key, [key, *(f"date:{vid}{tail}" for vid in same)]
