"""G-04 client hierarchy (spec B4).

- The tree is `Organization.parent_id` + `Organization.relationship`. Each entity is its own tenant; a link in the tree
  gives nobody access to another entity's data (tenancy rules v0.6.1 §3 unchanged).
- Roll-up: a parent sees counts and statuses of a *subsidiary's* register only while that subsidiary's CAICO consents.
  Consent records who and when, is revocable, and every grant, revocation and roll-up view is in the subsidiary's
  audit log. End-clients and vendor customers are never rolled up.
- LL144 scope per end-client (L-09, L-10): which of the parent's AEDTs are used for roles placed at that client, and
  whether that client gets its own public summary. Pricing counts the end-clients in LL144 scope.

Functions other workstreams use: `ll144_end_client_count`, `group_root`, `children`.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.audit_log.models import AuditLog
from app.core.clock import today, utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.hierarchy.models import RELATIONSHIP_LABELS, RELATIONSHIPS, EndClientScope, RollupConsent
from app.tenancy.models import Organization, User

MAX_DEPTH = 4  # parent > subsidiary > end-client is the deepest real chain; one level spare


def _live(db: Session, org_id: str | None) -> Organization | None:
    o = db.get(Organization, org_id) if org_id else None
    return o if o is not None and o.deleted_at is None and o.type == "client" else None


def children(db: Session, org_id: str) -> list[Organization]:
    return list(db.scalars(select(Organization).where(Organization.parent_id == org_id, Organization.deleted_at.is_(None)).order_by(Organization.name)))


def ancestors(db: Session, org: Organization) -> list[Organization]:
    out, seen, cur = [], {org.id}, org
    while cur.parent_id and cur.parent_id not in seen:
        cur = db.get(Organization, cur.parent_id)
        if cur is None:
            break
        out.append(cur)
        seen.add(cur.id)
    return out


def group_root(db: Session, org: Organization) -> Organization:
    up = ancestors(db, org)
    return up[-1] if up else org


def descendants(db: Session, org: Organization) -> list[tuple[Organization, int]]:
    out: list[tuple[Organization, int]] = []

    def walk(o: Organization, depth: int) -> None:
        for c in children(db, o.id):
            out.append((c, depth))
            if depth < MAX_DEPTH + 1:
                walk(c, depth + 1)

    walk(org, 1)
    return out


def _depth_below(db: Session, org: Organization) -> int:
    return max((d for _, d in descendants(db, org)), default=0)


def _check_relationship(rel: str) -> str:
    if rel not in RELATIONSHIPS:
        raise Invalid(errors=[{"field": "relationship", "message": "Choose subsidiary, end-client or customer of vendor."}])
    return rel


def link(db: Session, actor: User, parent: Organization, child: Organization, relationship: str) -> Organization:
    """Put an existing client under `parent`. Refuses self-links, cycles, a child that already has another parent and
    trees deeper than MAX_DEPTH."""
    _check_relationship(relationship)
    if child.id == parent.id:
        raise Conflict("An entity cannot be its own parent.")
    if any(a.id == child.id for a in ancestors(db, parent)):
        raise Conflict(f"{child.name} is above {parent.name} in this group, so it cannot also sit below it.")
    if child.parent_id and child.parent_id != parent.id:
        raise Conflict(f"{child.name} already belongs to another group. Remove it from that group first.")
    if len(ancestors(db, parent)) + 1 + _depth_below(db, child) > MAX_DEPTH:
        raise Conflict(f"Groups can be at most {MAX_DEPTH} levels deep.")
    before = {"parent_id": child.parent_id, "relationship": child.relationship}
    child.parent_id, child.relationship, child.updated_by = parent.id, relationship, actor.id
    if relationship != "subsidiary":
        _end_consent(db, actor, child, "The entity is no longer a subsidiary.")
    audit.record(db, actor_id=actor.id, action="hierarchy.link", obj=child, before=before, after={"parent_id": parent.id, "relationship": relationship},
                 summary=f"Placed {child.name} under {parent.name} as {RELATIONSHIP_LABELS[relationship].lower()}")
    audit.record(db, actor_id=actor.id, action="hierarchy.link", obj=parent, after={"child_id": child.id, "relationship": relationship},
                 summary=f"{child.name} added to the group as {RELATIONSHIP_LABELS[relationship].lower()}")
    db.flush()
    return child


def add_entity(db: Session, actor: User, parent: Organization, name: str, relationship: str, **fields) -> Organization:
    """A new entity under `parent`: its own client tenant, with no users and no engagement until Futran sets one up."""
    from app.tenancy.service import create_organization

    _check_relationship(relationship)
    name = " ".join(str(name or "").split())
    if not name:
        raise Invalid(errors=[{"field": "name", "message": "Enter the entity's name."}])
    if len(ancestors(db, parent)) + 1 > MAX_DEPTH:
        raise Conflict(f"Groups can be at most {MAX_DEPTH} levels deep.")
    org = create_organization(db, name=name[:200], type="client", actor_id=actor.id, status="draft", parent_id=parent.id, relationship=relationship,
                              **{k: v for k, v in fields.items() if v})
    audit.record(db, actor_id=actor.id, action="hierarchy.add_entity", obj=org, after={"parent_id": parent.id, "relationship": relationship},
                 summary=f"Added {org.name} to the group of {parent.name} as {RELATIONSHIP_LABELS[relationship].lower()}")
    audit.record(db, actor_id=actor.id, action="hierarchy.add_entity", obj=parent, after={"child_id": org.id}, summary=f"Added {org.name} to the group")
    return org


def set_relationship(db: Session, actor: User, child: Organization, relationship: str) -> Organization:
    if not child.parent_id:
        raise Conflict("This entity has no parent.")
    _check_relationship(relationship)
    before = child.relationship
    child.relationship, child.updated_by = relationship, actor.id
    if relationship != "subsidiary":
        _end_consent(db, actor, child, "The entity is no longer a subsidiary.")
    audit.record(db, actor_id=actor.id, action="hierarchy.relationship", obj=child, before={"relationship": before}, after={"relationship": relationship},
                 summary=f"Changed {child.name} to {RELATIONSHIP_LABELS[relationship].lower()}")
    return child


def unlink(db: Session, actor: User, child: Organization) -> Organization:
    if not child.parent_id:
        raise Conflict("This entity has no parent.")
    parent = db.get(Organization, child.parent_id)
    before = {"parent_id": child.parent_id, "relationship": child.relationship}
    _end_consent(db, actor, child, "The entity left the group.")
    child.parent_id, child.relationship, child.updated_by = None, None, actor.id
    audit.record(db, actor_id=actor.id, action="hierarchy.unlink", obj=child, before=before, summary=f"Removed {child.name} from the group of {parent.name if parent else 'its parent'}")
    return child


# ---------------------------------------------------------------- consent and roll-up
def active_consent(db: Session, sub: Organization) -> RollupConsent | None:
    if sub.relationship != "subsidiary" or not sub.parent_id:
        return None
    return db.scalar(select(RollupConsent).where(RollupConsent.organization_id == sub.id, RollupConsent.parent_id == sub.parent_id,
                                                 RollupConsent.revoked_at.is_(None), RollupConsent.deleted_at.is_(None)).order_by(RollupConsent.given_at.desc()).limit(1))


def _end_consent(db: Session, actor: User | None, sub: Organization, why: str) -> None:
    for c in db.scalars(select(RollupConsent).where(RollupConsent.organization_id == sub.id, RollupConsent.revoked_at.is_(None))):
        c.revoked_at, c.revoked_by = utcnow(), actor.id if actor else None
        audit.record(db, actor_id=actor.id if actor else None, action="hierarchy.consent_revoked", obj=c, after={"reason": why}, summary=f"Roll-up consent ended: {why}")


def give_consent(db: Session, actor: User, sub: Organization) -> RollupConsent:
    if sub.relationship != "subsidiary" or not sub.parent_id:
        raise Conflict("Only a subsidiary can share roll-up counts with its parent.")
    cur = active_consent(db, sub)
    if cur is not None:
        return cur
    parent = db.get(Organization, sub.parent_id)
    c = RollupConsent(organization_id=sub.id, parent_id=sub.parent_id, given_by=actor.id, given_at=utcnow(), created_by=actor.id)
    db.add(c)
    db.flush()
    audit.record(db, actor_id=actor.id, action="hierarchy.consent_given", obj=c, after={"parent_id": sub.parent_id},
                 summary=f"{actor.name} let {parent.name} see roll-up counts of {sub.name}'s AI register")
    return c


def revoke_consent(db: Session, actor: User, sub: Organization) -> None:
    if active_consent(db, sub) is None:
        raise Conflict("There is no roll-up consent to withdraw.")
    _end_consent(db, actor, sub, f"withdrawn by {actor.name}")


def consent_out(db: Session, c: RollupConsent | None) -> dict | None:
    if c is None:
        return None
    u = db.get(User, c.given_by)
    return {"given_by": u.name if u else None, "given_at": c.given_at.isoformat()}


def rollup(db: Session, sub: Organization) -> dict:
    """Counts and statuses of the subsidiary's register and current audit. No names, no records."""
    from app.engagements.models import Engagement
    from app.register.models import STAGES, RegisterSystem

    rows = db.execute(select(RegisterSystem.stage, RegisterSystem.risk_tier, RegisterSystem.bias_next_due)
                      .where(RegisterSystem.organization_id == sub.id, RegisterSystem.deleted_at.is_(None))).all()
    active = [r for r in rows if r.stage != "retired"]
    e = db.scalar(select(Engagement).where(Engagement.client_id == sub.id, Engagement.deleted_at.is_(None), Engagement.status.not_in(["draft", "pending_approval"]))
                  .order_by(Engagement.created_at.desc()).limit(1))
    audit_status = None
    if e is not None:
        from app.engagements.client_router import stage_label, status_label

        audit_status = {"status": status_label(e), "stage": stage_label(e)}
    return {
        "systems_total": len(active),
        "by_stage": {s: sum(1 for r in rows if r.stage == s) for s in STAGES},
        "high_risk": sum(1 for r in active if (r.risk_tier or 0) >= 3),
        "bias_audit_due": sum(1 for r in active if r.bias_next_due and r.bias_next_due <= today()),
        "audit": audit_status,
    }


def log_rollup_view(db: Session, actor: User, sub: Organization) -> None:
    """Every share is logged in the subsidiary's audit log; repeated views by the same person within an hour are one entry."""
    since = utcnow() - timedelta(hours=1)
    seen = db.scalar(select(AuditLog.id).where(AuditLog.organization_id == sub.id, AuditLog.action == "hierarchy.rollup_view", AuditLog.actor_id == actor.id,
                                               AuditLog.at >= since).limit(1))
    if seen is None:
        audit.record(db, actor_id=actor.id, action="hierarchy.rollup_view", obj=sub, summary=f"{actor.name} of the parent viewed roll-up counts of {sub.name}")


# ---------------------------------------------------------------- LL144 scope per end-client
def scope_for(db: Session, end_client_id: str) -> EndClientScope | None:
    return db.scalar(select(EndClientScope).where(EndClientScope.end_client_id == end_client_id, EndClientScope.deleted_at.is_(None)))


def set_scope(db: Session, actor: User, child: Organization, data: dict) -> EndClientScope:
    from app.register.models import RegisterSystem

    if not child.parent_id or child.relationship not in ("end_client", "customer_of_vendor"):
        raise Conflict("LL144 scope is set for end-clients and vendor customers.")
    ids = list(dict.fromkeys(data.get("aedt_system_ids") or []))
    if ids:
        own = set(db.scalars(select(RegisterSystem.id).where(RegisterSystem.id.in_(ids), RegisterSystem.organization_id == child.parent_id, RegisterSystem.deleted_at.is_(None))))
        if own != set(ids):
            raise Invalid(errors=[{"field": "aedt_system_ids", "message": "Choose AI systems from the parent's own register."}])
    s = scope_for(db, child.id)
    before = None
    if s is None:
        s = EndClientScope(organization_id=child.parent_id, end_client_id=child.id, created_by=actor.id)
        db.add(s)
    else:
        before = {"ll144_in_scope": s.ll144_in_scope, "aedt_system_ids": s.aedt_system_ids, "roles_note": s.roles_note}
    s.ll144_in_scope = bool(data.get("ll144_in_scope"))
    s.aedt_system_ids = ids if s.ll144_in_scope else []
    s.roles_note = (" ".join(str(data.get("roles_note") or "").split()) or None)
    s.roles_note = s.roles_note[:300] if s.roles_note else None
    s.own_public_summary = bool(data.get("own_public_summary")) and s.ll144_in_scope
    s.vendor_allows_summary = bool(data.get("vendor_allows_summary")) and child.relationship == "customer_of_vendor"
    s.updated_by = actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="hierarchy.ll144_scope", obj=s, before=before,
                 after={"ll144_in_scope": s.ll144_in_scope, "aedt_system_ids": s.aedt_system_ids, "roles_note": s.roles_note},
                 summary=f"LL144 scope for {child.name}: {'in scope' if s.ll144_in_scope else 'not in scope'}")
    return s


def ll144_end_client_count(db: Session, parent_id: str) -> int:
    """End-clients of `parent_id` in LL144 scope — what L-09 pricing counts. Vendor customers (L-10) are not counted."""
    return db.scalar(select(func.count(EndClientScope.id)).join(Organization, Organization.id == EndClientScope.end_client_id)
                     .where(EndClientScope.organization_id == parent_id, EndClientScope.ll144_in_scope.is_(True), EndClientScope.deleted_at.is_(None),
                            Organization.parent_id == parent_id, Organization.relationship == "end_client", Organization.deleted_at.is_(None))) or 0


def _scope_out(db: Session, s: EndClientScope | None, names: dict[str, str]) -> dict | None:
    if s is None:
        return None
    return {"in_scope": s.ll144_in_scope, "aedts": [{"id": i, "name": names.get(i, "Removed system")} for i in s.aedt_system_ids or []], "roles_note": s.roles_note,
            "own_public_summary": s.own_public_summary, "vendor_allows_summary": s.vendor_allows_summary}


# ---------------------------------------------------------------- views
def futran_tree(db: Session, org: Organization) -> dict:
    """The whole group of `org` for Futran staff (G-04)."""
    from app.register.models import RegisterSystem

    root = group_root(db, org)
    entities = [(root, 0), *descendants(db, root)]
    ids = [o.id for o, _ in entities]
    names = dict(db.execute(select(RegisterSystem.id, RegisterSystem.name).where(RegisterSystem.organization_id.in_(ids))).all())
    nodes, aedts, end_clients, in_scope = [], set(), 0, 0
    for o, depth in entities:
        consent = active_consent(db, o)
        s = scope_for(db, o.id) if o.relationship in ("end_client", "customer_of_vendor") else None
        if o.relationship == "end_client" and o.parent_id == root.id:  # the L-09 pricing count
            end_clients += 1
            if s is not None and s.ll144_in_scope:
                in_scope += 1
                aedts |= set(s.aedt_system_ids or [])
        nodes.append({
            "id": o.id, "name": o.name, "client_ref": o.client_ref, "status": o.status, "parent_id": o.parent_id, "depth": depth,
            "relationship": o.relationship, "relationship_label": RELATIONSHIP_LABELS.get(o.relationship or "", "Parent" if depth == 0 else None),
            "consent": consent_out(db, consent) if o.relationship == "subsidiary" else None, "consented": consent is not None,
            "rollup": rollup(db, o) if consent is not None else None, "ll144": _scope_out(db, s, names),
            "children": sum(1 for c, _ in entities if c.parent_id == o.id),
        })
    parent_systems = [{"id": i, "name": n} for i, n in db.execute(select(RegisterSystem.id, RegisterSystem.name).where(
        RegisterSystem.organization_id == root.id, RegisterSystem.deleted_at.is_(None), RegisterSystem.stage != "retired").order_by(RegisterSystem.reference)).all()]
    return {"root": {"id": root.id, "name": root.name}, "nodes": nodes, "ll144": {"end_clients": end_clients, "in_scope": in_scope, "aedts": len(aedts)},
            "parent_systems": parent_systems}


def client_group(db: Session, actor: User, org: Organization) -> dict:
    """What a client CAICO sees: their parent (and their own consent) and their direct children, with the roll-up of
    each subsidiary that consents. Nothing of any other entity beyond its name, relationship and consent."""
    parent = db.get(Organization, org.parent_id) if org.parent_id else None
    kids = []
    for c in children(db, org.id):
        consent = active_consent(db, c)
        ru = None
        if consent is not None:
            ru = rollup(db, c)
            log_rollup_view(db, actor, c)
        s = scope_for(db, c.id) if c.relationship in ("end_client", "customer_of_vendor") else None
        kids.append({"id": c.id, "name": c.name, "relationship": c.relationship, "relationship_label": RELATIONSHIP_LABELS.get(c.relationship or ""),
                     "consent": consent is not None if c.relationship == "subsidiary" else None, "rollup": ru,
                     "ll144": {"in_scope": s.ll144_in_scope, "roles_note": s.roles_note, "own_public_summary": s.own_public_summary} if s else None})
    mine = active_consent(db, org)
    return {
        "organization": {"id": org.id, "name": org.name, "relationship": org.relationship, "relationship_label": RELATIONSHIP_LABELS.get(org.relationship or "")},
        "parent": {"id": parent.id, "name": parent.name} if parent else None,
        "can_consent": org.relationship == "subsidiary" and parent is not None,
        "consent": consent_out(db, mine),
        "children": kids,
    }


def load_client(db: Session, org_id: str) -> Organization:
    o = _live(db, org_id)
    if o is None:
        raise NotFound()
    return o


# ---------------------------------------------------------------- import end-clients (CSV)
IMPORT_MAX_ROWS = 500
IMPORT_MAX_BYTES = 1024 * 1024
_YES = {"yes", "y", "true", "1", "x"}


def _cell(v) -> str:
    s = " ".join(str(v or "").split())
    return s.lstrip("=+-@\t\r ")  # never keep a spreadsheet formula prefix in a name


def parse_end_clients(data: bytes) -> tuple[list[dict], list[dict]]:
    """Columns: name (required), relationship (end_client by default), ll144_in_scope (yes/no), roles_note."""
    import csv
    import io

    if len(data) > IMPORT_MAX_BYTES:
        raise Invalid("The file is larger than 1 MB.", [{"field": "file", "message": "File too large."}])
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise Invalid("Save the file as CSV (UTF-8) and upload it again.", [{"field": "file", "message": "Not a UTF-8 CSV file."}]) from exc
    reader = csv.DictReader(io.StringIO(text))
    fields = {(f or "").strip().lower(): f for f in reader.fieldnames or []}
    if "name" not in fields:
        raise Invalid("The first row must name the columns, with at least a 'name' column.", [{"field": "file", "message": "No name column."}])
    rows, errors = [], []
    for n, raw in enumerate(reader, start=2):
        if n - 1 > IMPORT_MAX_ROWS:
            errors.append({"row": n, "field": "file", "message": f"Only the first {IMPORT_MAX_ROWS} rows can be imported at once."})
            break
        get = lambda k: _cell(raw.get(fields[k])) if k in fields else ""  # noqa: E731
        name = get("name")[:200]
        if not name:
            continue
        rel = (get("relationship").lower().replace("-", "_").replace(" ", "_") or "end_client")
        rel = {"end_client_(staffing)": "end_client", "customer": "customer_of_vendor"}.get(rel, rel)
        if rel not in RELATIONSHIPS:
            errors.append({"row": n, "field": "relationship", "message": f"{name}: use subsidiary, end_client or customer_of_vendor."})
            continue
        rows.append({"row": n, "name": name, "relationship": rel, "ll144_in_scope": get("ll144_in_scope").lower() in _YES, "roles_note": get("roles_note")[:300] or None})
    return rows, errors


def import_end_clients(db: Session, actor: User, parent: Organization, data: bytes, *, apply: bool) -> dict:
    rows, errors = parse_end_clients(data)
    have = {c.name.lower() for c in children(db, parent.id)}
    out = []
    for r in rows:
        dup = r["name"].lower() in have
        out.append(r | {"status": "already in the group" if dup else "new"})
        if apply and not dup:
            org = add_entity(db, actor, parent, r["name"], r["relationship"])
            have.add(r["name"].lower())
            if r["relationship"] != "subsidiary" and (r["ll144_in_scope"] or r["roles_note"]):
                set_scope(db, actor, org, {"ll144_in_scope": r["ll144_in_scope"], "roles_note": r["roles_note"]})
    created = sum(1 for r in out if r["status"] == "new") if apply else 0
    if apply:
        audit.record(db, actor_id=actor.id, action="hierarchy.import", obj=parent, after={"created": created, "rows": len(rows)},
                     summary=f"Imported {created} entities into the group of {parent.name}")
    return {"rows": out, "errors": errors, "applied": apply, "created": created}
