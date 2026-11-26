"""What the website library API serves: the law library and the AI litigation tracker as the app shows them, built from
the same records and helpers as the staff screens (app.regmaster.router M1/M2, app.litigation L1/L2, the law record's
Obligations card), less what ties a law or case to a Futran client or to Futran staff.

Every serializer here is a whitelist: a field the staff endpoints add later is not served until it is added here.
tests/library/test_public_content.py fails when a staff field is neither served nor listed in EXCLUDED with its reason.

Only published records are served: a law's current (approved) version, approved obligations, and cases in the tracker.
Proposals from the refresh pipeline (ProposedChange, pending obligations) are never read; once a person approves one,
it becomes part of the record and the next response carries it.
"""
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.models import Obligation
from app.core.clock import today
from app.core.errors import NotFound
from app.laws.models import Regulation
from app.laws.publish import chain_ids
from app.litigation.models import STAGE_LABELS, STAGES, Case
from app.reference.models import Jurisdiction
from app.refresh.models import RefreshRun
from app.regmaster import changes, letter as letters
from app.regmaster import router as M
from app.regmaster.models import CommitteeRule, LawRoleMap, LawVersion, Requirement, RoleCatalog, ScopeTest, Source

REGIONS = M.REGIONS
REGION_LABELS = dict(REGIONS)
APPLIES_LABELS = {"deployer": "Deployer (uses AI)", "developer": "Developer", "provider": "Provider", "employer": "Employer",
                  "data_fiduciary": "Data fiduciary or controller", "importer": "Importer", "distributor": "Distributor"}
LAW_SORTS = ("geography", "name", "effective_on", "-effective_on")
CASE_SORTS = ("geography", "name", "-last_update_on")
REFRESHED = ("completed", "partial", "capped")  # a run that finished and published what people approved; a failed run is not a refresh

# The app fields the website does not get, and why. Documented in docs/Futran_Audit_Platform_Website_Library_API.md.
EXCLUDED: dict[str, dict[str, str]] = {
    "law_row": {
        "pending_count": "Changes waiting for review in the refresh pipeline: not published.",
        "reviewer_id": "The Futran staff member assigned to review the law.",
        "review_due_on": "Futran's internal review schedule for the law.",
        "refresh_every_days": "Futran's internal refresh schedule for the law.",
        "watch": "Futran's internal watch list.",
    },
    "law_record": {
        "pending": "Proposed changes waiting for review, with who proposed them: not published.",
        "used_by_clients": "How many Futran clients the law applies to (client applicability).",
        "used_by_systems": "How many client AI systems are linked to the law (client registers).",
        "can_edit": "The signed-in viewer's permissions.",
        "can_suggest": "The signed-in viewer's permissions.",
        "can_approve": "The signed-in viewer's permissions.",
        "roles": "The full role catalogue, used by the editor's pick list; the law's own roles are in role_maps.",
    },
    "law_version": {"approved_by": "The name of the Futran staff member who approved the version."},
    "history": {"by": "The name of the Futran staff member who approved each version."},
    "obligation": {
        "approved_by": "The name of the Futran reviewer who approved the obligation.",
        "rejected_reason": "Reviewer notes from the approval workflow.",
        "confidence": "The AI extraction's own confidence score, used by reviewers.",
        "quote_found": "The AI extraction's quote check, used by reviewers.",
        "status": "Always approved: only approved obligations are served.",
    },
    "case_row": {
        "clients_count": "How many Futran clients use AI like the AI in the case (client matches).",
        "systems_count": "How many client AI systems match the case (client matches).",
        "match_summary": "The types of client AI that match the case (client matches).",
        "following": "Whether the signed-in staff member follows the case.",
    },
    "case_record": {
        "matches": "The Futran clients and AI systems that match the case.",
        "match_rule": "The rule that matches the case to client AI registers (types, vendors and uses).",
        "talking_points_futran": "Internal talking points for the Chief Auditor and the sales team.",
        "can_edit": "The signed-in viewer's permissions.",
        "clients_count": "See the case list.", "systems_count": "See the case list.", "following": "See the case list.",
    },
    "case_filters": {"clients": "The tracker's client filter lists Futran clients with matching AI."},
    "law_kpis": {"pending": "Changes waiting for review.", "shown": "A screen count; use pagination.total."},
    "last_refresh": {"open": "Items waiting for review from the last refresh.", "alert_status": "Who the refresh alert was sent to.", "id": "Internal run id."},
}

LAW_ROW_FIELDS = ("id", "geography", "jurisdiction_code", "short_name", "label", "citation", "type", "binding", "status", "status_label", "effective",
                  "effective_on", "scope", "applies_to", "topics", "requirement_count", "role_count", "committee", "penalty", "last_change", "verify",
                  "version_no", "region")
VERSION_FIELDS = ("id", "version_no", "status", "status_label", "signed_on", "effective_on", "compliance_on", "effective_text", "scope_text", "applies_to",
                  "enforcer", "private_right_of_action", "penalty_text", "cure_period", "exemptions_text", "removed_text", "litigation_text", "main_duty",
                  "verify", "approved_at")
OBLIGATION_FIELDS = ("id", "regulation_id", "law", "text", "actor", "action", "condition", "deadline", "citation", "quote", "effective_date", "control_ids",
                     "question_ids", "requirement_ids", "requirements", "approved_at")

_iso = M._iso


# ------------------------------------------------------------------ freshness

def last_refreshed(db: Session, kind: str) -> str | None:
    """When the scheduled (or manual) refresh of this library last finished. The refresh itself is app.refresh."""
    at = db.scalar(select(func.max(RefreshRun.finished_at)).where(RefreshRun.kind == kind, RefreshRun.status.in_(REFRESHED)))
    return at.isoformat() if at else None


def fingerprint(db: Session) -> tuple:
    """A cheap summary of every table the library responses read. It changes when a law, version, requirement, source,
    obligation, case or refresh run is added or changed, so it keys the server-side cache."""
    q = lambda *cols: tuple(db.execute(select(*cols)).one())  # noqa: E731
    return (
        q(func.count(Regulation.id), func.max(Regulation.created_at), func.max(Regulation.current_version_id)),
        q(func.count(LawVersion.id), func.max(LawVersion.created_at), func.max(LawVersion.approved_at)),
        q(func.count(Requirement.id)), q(func.count(LawRoleMap.id)), q(func.count(ScopeTest.id)), q(func.count(CommitteeRule.id)),
        q(func.count(Source.id), func.max(Source.created_at), func.max(Source.last_read_at)),
        q(func.count(Obligation.id), func.max(Obligation.updated_at)),
        q(func.count(Case.id), func.max(Case.updated_at), func.max(Case.deleted_at)),
        q(func.count(RefreshRun.id), func.max(RefreshRun.finished_at)),
        q(func.count(Jurisdiction.id)),
    )


# ------------------------------------------------------------------ laws

def _live_laws(db: Session) -> list[tuple[Regulation, Jurisdiction, LawVersion]]:
    """Current laws with an approved version, in the library's order (region, then geography, then name)."""
    rows = db.execute(select(Regulation, Jurisdiction).join(Jurisdiction, Jurisdiction.id == Regulation.jurisdiction_id)
                      .where(Regulation.superseded_by_id.is_(None), Regulation.retired_in_version_id.is_(None), Regulation.current_version_id.is_not(None))
                      .order_by(Jurisdiction.name, Regulation.short_name)).all()
    vids = [r.current_version_id for r, _ in rows]
    versions = {v.id: v for v in db.scalars(select(LawVersion).where(LawVersion.id.in_(vids)))} if vids else {}
    return [(r, j, versions[r.current_version_id]) for r, j in rows if r.current_version_id in versions]


def _rows(db: Session):
    laws = _live_laws(db)
    reqs, roles, comm = M._counts(db, [v.id for _, _, v in laws])
    out = []
    for r, j, v in laws:
        staff_row = M._law_row(db, r, j, v, reqs, roles, comm, {})  # no pending counts: review state is not published
        row = {k: staff_row[k] for k in LAW_ROW_FIELDS}
        row["region_label"] = REGION_LABELS.get(row["region"], row["region"])
        out.append((row, v))
    order = {k: i for i, (k, _) in enumerate(REGIONS)}
    out.sort(key=lambda x: order.get(x[0]["region"], len(order)))  # stable: keeps geography, then name, inside each region
    return out


def law_list(db: Session, *, region=None, status=None, applies_to=None, topic=None, q=None, show="library", sort="geography", page=1, limit=50) -> dict:
    rows = _rows(db)
    shown = rows if show == "all" else [x for x in rows if x[0]["requirement_count"]]
    if region:
        shown = [x for x in shown if x[0]["region"] == region]
    if status:
        shown = [x for x in shown if x[0]["status"] == status or (status == "in_force" and x[0]["status"] == "in_force_phased")]
    if applies_to:
        shown = [x for x in shown if applies_to in x[0]["applies_to"]]
    if topic:
        shown = [x for x in shown if topic in x[0]["topics"]]
    if q:
        words = q.lower().split()
        hits = set(db.scalars(select(Requirement.law_version_id).where(func.lower(Requirement.text).contains(q.lower()))))
        shown = [x for x in shown if all(w in f"{x[0]['short_name']} {x[0]['citation'] or ''} {x[0]['geography']} {x[0]['label']}".lower() for w in words)
                 or x[1].id in hits]
    data = [x[0] for x in shown]
    if sort == "name":
        data.sort(key=lambda x: (x["label"].casefold(), x["geography"]))
    elif sort in ("effective_on", "-effective_on"):
        dated = sorted((x for x in data if x["effective_on"]), key=lambda x: x["effective_on"], reverse=sort.startswith("-"))
        data = dated + [x for x in data if not x["effective_on"]]
    return paginate(data, page, limit)


def paginate(data: list, page: int, limit: int) -> dict:
    total = len(data)
    pages = -(-total // limit) if total else 0
    start = (page - 1) * limit
    return {"data": data[start:start + limit],
            "pagination": {"page": page, "limit": limit, "total": total, "pages": pages, "next_page": page + 1 if page < pages else None}}


def _live_law(db: Session, law_id: str) -> tuple[Regulation, LawVersion]:
    reg = db.get(Regulation, law_id)
    if reg is None or reg.superseded_by_id or reg.retired_in_version_id or not reg.current_version_id:
        raise NotFound()
    v = db.get(LawVersion, reg.current_version_id)
    if v is None:
        raise NotFound()
    return reg, v


def _role_maps(db: Session, reg: Regulation, v: LawVersion, reqs: list[Requirement]) -> list[dict]:
    """As the law record's "Roles and committees this law requires" card (app.regmaster.router.law_record)."""
    maps = list(db.scalars(select(LawRoleMap).where(LawRoleMap.law_version_id == v.id)))
    roles = {r.id: r for r in db.scalars(select(RoleCatalog))}
    req_codes = {r.id: r.code for r in reqs}
    out = []
    for m in sorted(maps, key=lambda m: (m.level != "required", roles[m.role_id].number)):
        role = roles[m.role_id]
        out.append({"role": role.code, "name": role.name, "level": m.level, "needed_by_stage": m.needed_by_stage, "basis": m.basis_text, "applies_to": m.applies_to or [],
                    "requirements": [req_codes[i] for i in (m.requirement_ids or []) if i in req_codes], "verify": m.verify_flag})
    prev = db.scalar(select(LawVersion).where(LawVersion.regulation_id == reg.id, LawVersion.version_no < v.version_no).order_by(LawVersion.version_no.desc()).limit(1))
    if prev is not None:
        now_ids = {m.role_id for m in maps}
        for m in db.scalars(select(LawRoleMap).where(LawRoleMap.law_version_id == prev.id)):
            if m.role_id not in now_ids:
                role = roles[m.role_id]
                out.append({"role": role.code, "name": role.name, "level": "no_longer_required", "needed_by_stage": None, "basis": None, "applies_to": [], "requirements": [], "verify": False})
    return out


def _obligations(db: Session, reg: Regulation) -> list[dict]:
    from app.ai.obligations import obligation_out

    rows = db.scalars(select(Obligation).where(Obligation.regulation_id == reg.id, Obligation.deleted_at.is_(None), Obligation.status == "approved").order_by(Obligation.created_at))
    return [{k: o[k] for k in OBLIGATION_FIELDS} for o in (obligation_out(db, x) for x in rows)]


def law_record(db: Session, law_id: str) -> dict:
    """The law record (M2) as the app shows it, less the fields in EXCLUDED."""
    reg, v = _live_law(db, law_id)
    j = db.get(Jurisdiction, reg.jurisdiction_id)
    parent = db.get(Jurisdiction, j.parent_id) if j and j.parent_id else None
    reqs = list(db.scalars(select(Requirement).where(Requirement.law_version_id == v.id).order_by(Requirement.order)))
    version = {"id": v.id, "version_no": v.version_no, "status": v.status, "status_label": letters.STATUS_LABELS.get(v.status, v.status), "signed_on": _iso(v.signed_on),
               "effective_on": _iso(v.effective_on), "compliance_on": _iso(v.compliance_on), "effective_text": v.effective_text, "scope_text": v.scope_text,
               "applies_to": v.applies_to or [], "enforcer": v.enforcer, "private_right_of_action": v.private_right_of_action, "penalty_text": v.penalty_text,
               "cure_period": v.cure_period, "exemptions_text": v.exemptions_text, "removed_text": v.removed_text, "litigation_text": v.litigation_text,
               "main_duty": v.main_duty, "verify": v.verify_flag, "approved_at": _iso(v.approved_at)}
    history = [{"id": h.id, "version_no": h.version_no, "change": h.change_summary or "", "date": _iso(h.approved_at or h.created_at)}
               for h in db.scalars(select(LawVersion).where(LawVersion.regulation_id == reg.id, LawVersion.version_no <= v.version_no).order_by(LawVersion.version_no.desc()))]
    region = M._region(db, reg, j)
    return {
        "id": reg.id, "short_name": reg.short_name, "label": M.engine.law_label(reg), "citation": reg.citation, "type": reg.type, "binding": reg.binding,
        "topics": reg.topics or [], "region": region, "region_label": REGION_LABELS.get(region, region), "geography": j.name if j else "",
        "jurisdiction_code": j.code if j else None, "parent_geography": parent.name if parent else None,
        "version": version,
        "scope_tests": [{"order": t.order, "question_text": t.question_text, "answer_type": t.answer_type, "in_scope_rule": t.in_scope_rule, "decisive": t.decisive,
                         "prefill_from": t.prefill_from, "note": t.note}
                        for t in db.scalars(select(ScopeTest).where(ScopeTest.law_version_id == v.id).order_by(ScopeTest.order))],
        "requirements": [changes.requirement_out(db, r) for r in reqs],
        "role_maps": _role_maps(db, reg, v, reqs),
        "committees": [{"committee_type": c.committee_type, "title": c.title, "level": c.level, "basis": c.basis_text, "condition": c.condition_text, "items": c.items or []}
                       for c in db.scalars(select(CommitteeRule).where(CommitteeRule.law_version_id == v.id))],
        "obligations": _obligations(db, reg),
        "sources": [{"id": s.id, "name": s.name, "url": s.url, "kind": s.kind, "last_read_at": _iso(s.last_read_at)}
                    for s in db.scalars(select(Source).where(Source.regulation_id == reg.id).order_by(Source.kind, Source.name))],
        "history": history,
        "cases": [case_row(c) for c in _cases_for_law(db, reg)],
    }


def _cases_for_law(db: Session, reg: Regulation) -> list[Case]:
    """Cases that interpret the law; earlier rows of the same law count (as app.litigation.router.cases_for_law)."""
    ids = set(chain_ids(db, reg.id)) or {reg.id}
    return [c for c in db.scalars(select(Case).where(Case.deleted_at.is_(None)).order_by(Case.name)) if ids & set(c.regulation_ids or [])]


# ------------------------------------------------------------------ cases

def case_row(c: Case) -> dict:
    """A row of the litigation tracker (L1), less the client match columns and the viewer's follow."""
    return {"id": c.id, "name": c.name, "geography": c.geography, "jurisdiction_id": c.jurisdiction_id, "area": c.area, "court": c.court, "docket_ref": c.docket_ref,
            "description": c.description, "stage": c.stage, "stage_label": STAGE_LABELS.get(c.stage, c.stage), "stage_note": c.stage_note,
            "last_update_on": _iso(c.last_update_on), "version": c.version, "regulation_ids": c.regulation_ids or [], "origin": c.origin, "updated_at": _iso(c.updated_at)}


def _live_case(db: Session, case_id: str) -> Case:
    c = db.get(Case, case_id)
    if c is None or c.deleted_at is not None:
        raise NotFound()
    return c


def _visible_cases(db: Session, *, stage=None, area=None, geography=None, q=None) -> list[Case]:
    """The tracker's filters (app.litigation.router._visible), without the client filter."""
    stmt = select(Case).where(Case.deleted_at.is_(None))
    if stage:
        stmt = stmt.where(Case.stage.in_(stage.split(",")))
    if area:
        stmt = stmt.where(Case.area == area)
    if geography:
        stmt = stmt.where(Case.geography == geography)
    rows = list(db.scalars(stmt.order_by(Case.last_update_on.desc().nulls_last(), Case.name)))
    if q:
        needle = q.casefold()
        rows = [c for c in rows if needle in f"{c.name} {c.area} {c.court or ''} {c.description or ''}".casefold()]
    return rows


def case_list(db: Session, *, stage=None, area=None, geography=None, q=None, sort="geography", page=1, limit=50) -> dict:
    rows = _visible_cases(db, stage=stage, area=area, geography=geography, q=q)
    if sort == "geography":
        rows.sort(key=lambda c: (c.geography or "", c.name))
    elif sort == "name":
        rows.sort(key=lambda c: c.name.casefold())
    return paginate([case_row(c) for c in rows], page, limit)


def _linked_law(db: Session, law_id: str) -> dict | None:
    """A law the case interprets, as its current row (a replaced row points on to the one that replaced it)."""
    ids = chain_ids(db, law_id)
    reg = next((r for r in (db.get(Regulation, i) for i in reversed(ids)) if r.superseded_by_id is None and r.retired_in_version_id is None), None)
    if reg is None:
        return None
    j = db.get(Jurisdiction, reg.jurisdiction_id)
    return {"id": reg.id, "short_name": reg.short_name, "label": M.engine.law_label(reg), "geography": j.name if j else "", "jurisdiction_code": j.code if j else None}


def case_record(db: Session, case_id: str) -> dict:
    """The case record (L2) as the app shows it, less the fields in EXCLUDED."""
    c = _live_case(db, case_id)
    laws, seen = [], set()
    for lid in c.regulation_ids or []:
        x = _linked_law(db, lid)
        if x is not None and x["id"] not in seen:
            seen.add(x["id"])
            laws.append(x)
    return case_row(c) | {"why_matters": c.why_matters, "talking_points_client": c.talking_points_client, "sources": c.sources or [], "timeline": c.timeline or [],
                          "laws": laws}


# ------------------------------------------------------------------ meta

def meta(db: Session) -> dict:
    rows = _rows(db)
    library = [x for x, _ in rows if x["requirement_count"]]
    soon = today() + timedelta(days=90)
    upcoming = sum(1 for _, v in rows if any(d and today() <= d <= soon for d in (v.effective_on, v.compliance_on)))
    cases = list(db.scalars(select(Case).where(Case.deleted_at.is_(None))))
    return {
        "laws": {
            "filters": {"regions": [{"value": k, "label": v} for k, v in REGIONS], "topics": [{"value": k, "label": v} for k, v in M.TOPICS.items()],
                        "statuses": [{"value": k, "label": v} for k, v in letters.STATUS_LABELS.items()],
                        "applies_to": [{"value": k, "label": v} for k, v in APPLIES_LABELS.items()],
                        "show": [{"value": "library", "label": "Laws with requirements"}, {"value": "all", "label": "All laws in the matrix"}],
                        "sort": list(LAW_SORTS)},
            "counts": {"laws": len(library), "all_laws": len(rows), "geographies": len({x["jurisdiction_code"] for x in library}),
                       "requirements": sum(x["requirement_count"] for x in library), "upcoming_90_days": upcoming},
            "last_refreshed_at": last_refreshed(db, "law"),
        },
        "cases": {
            "filters": {"stages": [{"value": s, "label": STAGE_LABELS[s]} for s in STAGES], "areas": sorted({c.area for c in cases}),
                        "geographies": sorted({c.geography for c in cases if c.geography}), "sort": list(CASE_SORTS)},
            "counts": {"cases": len(cases), "by_stage": {s: sum(1 for c in cases if c.stage == s) for s in STAGES}},
            "last_refreshed_at": last_refreshed(db, "litigation"),
        },
    }
