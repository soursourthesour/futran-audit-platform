"""One list of the client's AI (11-10 U1, U3).

Register systems, inventory tools and agents, use cases and the systems in the current audit, in one list for the client's
"AI systems" page. Nothing is converted: each row is read from its own record. Each source is scoped exactly as the screen
it replaces was scoped (the AI system register, the AI inventory and the audit's AI systems list), so a person sees the same
rows and actions as before, in one place, and nothing more.

An inventory tool already in the register (same vendor and product, or imported from it) and a use case imported into a
register system name that system in `in_register_as`; the page folds them into the system's row by default. That only
happens for register systems the person can see; for someone who cannot see the register, `registered` is None.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.attestation.service import TYPED_VENDORS
from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.engagements.models import Engagement
from app.inventory import service as inv
from app.inventory.models import AITool, UseCase
from app.policy.actions import Action
from app.policy.authorize import authorize, departments_for
from app.register import service as svc
from app.register.models import RegisterSystem
from app.register.seeding import dedupe_key, svc_key
from app.register.serialize import system_out
from app.systems.models import AISystem
from app.tenancy.models import Department
from app.tenancy.people import current_engagement

router = APIRouter(tags=["ai-systems"])

TYPE_LABELS = {"system": "System", "tool": "Tool or agent", "use_case": "Use case"}
SOURCE_LABELS = {"register": "Register", "inventory": "Inventory", "attestation": "Attestation", "discovery": "Discovery", "audit": "Audit"}
TOOL_SOURCE = {"manual": "inventory", "attestation": "attestation", "discovery": "discovery"}
TOOL_STATUS = {"unreviewed": "Unreviewed", "approved": "Approved", "not_approved": "Not approved"}
USE_CASE_STATUS = {"draft": "Draft", "submitted": "Submitted", "dept_approved": "Dept approved", "returned": "Returned"}
AUDIT_STATUS = {"not_started": "Not started", "client_prefill": "In progress", "in_review": "With the auditor", "scored": "With the auditor", "locked": "Locked"}


def _may(db: Session, actor: Actor, action: Action, **kw) -> bool:
    try:
        authorize(db, actor, action, **kw)
    except (Forbidden, NotFound):
        return False
    return True


def prefillable(db: Session, actor: Actor, e: Engagement) -> list[AISystem]:
    """The audit systems this person pre-fills (the old AI systems list, /me/systems): their departments' systems and any
    system they are assigned to; every system for organization-wide roles."""
    from app.systems.service import systems_for

    depts = departments_for(actor, Action.PREFILL_SYSTEM)
    own = {r.scope_id for r in actor.roles if r.scope_type == "system"}
    return [s for s in systems_for(db, e) if depts is None or s.department_id in depts or s.id in own]


def _audit_info(db: Session, e: Engagement, s: AISystem, can_answer: bool) -> dict:
    from app.questionnaire import service as qs

    out = {"system_id": s.id, "reference_id": s.reference_id, "status": s.status, "status_label": AUDIT_STATUS.get(s.status, s.status), "can_answer": can_answer}
    if can_answer:
        c = qs.completion(db, qs.Target(e, s), futran=False)
        out |= {"answered": c["answered"], "applicable": c["applicable"], "pct": c["pct"]}
    return out


def _row(key: str, kind: str, name: str, **kw) -> dict:
    sources = kw.pop("sources")
    return {"key": key, "kind": kind, "type_label": TYPE_LABELS[kind], "name": name, "sources": sources,
            "source_label": " · ".join(SOURCE_LABELS[x] for x in sources), "subtype": None, "detail": None, "departments": [], "company_wide": False,
            "stage": None, "stage_label": None, "tier": None, "registered": None, "in_register_as": None, "in_audit": None, "audit": None,
            "system": None, "tool": None, "use_case": None, "open": None, "can": {}} | kw


@router.get("/ai-systems")
def ai_systems(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.inventory.router import tool_out, use_case_out
    from app.register.router import capabilities, kpis, options

    if actor.is_futran:
        raise NotFound()  # a client screen; Futran reads each client's inventory and systems through the engagement
    org = actor.organization
    e = current_engagement(db, org)
    see_register = _may(db, actor, Action.VIEW_REGISTER, org_id=org.id, list_view=True)
    see_inventory = e is not None and _may(db, actor, Action.VIEW_INVENTORY, engagement_id=e.id, list_view=True)
    see_engagement = e is not None and _may(db, actor, Action.VIEW_ENGAGEMENT, engagement_id=e.id)
    may_prefill = see_engagement and _may(db, actor, Action.PREFILL_SYSTEM, engagement_id=e.id, list_view=True)
    if not (see_register or see_inventory or may_prefill):
        raise Forbidden()

    # the audit's systems as the old AI systems page showed them: only those this person pre-fills. Whether anything else is
    # in the audit is not said (None), since that page was the only place a client saw the audit's systems.
    audit_systems = prefillable(db, actor, e) if may_prefill else []
    answerable = {s.id for s in audit_systems}
    dept_names = {d.id: d.name for d in db.scalars(select(Department).where(Department.organization_id == org.id, Department.deleted_at.is_(None)))}
    dept = (lambda i: {"id": i, "name": dept_names[i]} if i in dept_names else None)  # noqa: E731
    rows: list[dict] = []

    # ---- register systems (the register grid's scope)
    systems = svc.systems_for(db, org.id, departments_for(actor, Action.VIEW_REGISTER)) if see_register else []
    tools_all = {t.id: t for t in inv.tools_for(db, org.id)}
    by_key: dict[str, RegisterSystem] = {}
    by_ref: dict[str, RegisterSystem] = {}
    for s in systems:
        by_key.setdefault(s.dedupe_key or svc_key(s, db), s)
        for ref in s.source_refs or []:
            by_ref.setdefault(ref, s)
    audit_by_register = {a.register_system_id: a for a in audit_systems if a.register_system_id}
    for s in systems:
        out = system_out(db, s, actor)
        if s.origin == "inventory":
            refs = [r.split(":", 1) for r in s.source_refs or []]
            srcs = [TOOL_SOURCE.get(tools_all[i].source, "inventory") if k == "tool" and i in tools_all else "inventory" for k, i in refs]
            sources = list(dict.fromkeys(srcs)) or ["inventory"]
        else:
            sources = ["register"]
        a = audit_by_register.get(s.id)
        depts = [out["department"]] if out["department"] else out["departments"]
        rows.append(_row(f"system:{s.id}", "system", s.name, sources=sources, subtype=out["type_label"], detail=out["vendor"]["name"] if out["vendor"] else None,
                         departments=depts, company_wide=s.company_wide, stage=s.stage, stage_label=out["stage_label"], tier=s.risk_tier, registered=True,
                         in_audit=(a is not None) if may_prefill else None, audit=_audit_info(db, e, a, True) if a is not None else None,
                         system=out, open=f"/register/{s.id}"))

    # ---- the audit's systems not on a register row this person sees (the old AI systems list)
    shown = {s.id for s in systems}
    for a in audit_systems:
        if a.register_system_id and a.register_system_id in shown:
            continue
        rows.append(_row(f"audit:{a.id}", "system", a.name, sources=["audit"], subtype=a.reference_id, departments=[x for x in [dept(a.department_id)] if x],
                         stage=f"audit:{a.status}", stage_label=AUDIT_STATUS.get(a.status, a.status), registered=False if see_register else None, in_audit=True,
                         audit=_audit_info(db, e, a, True), open=f"/systems/{a.id}"))

    inventory = None
    if see_inventory:
        # ---- use cases (the inventory's department scope) and tools (every tool, typed names for individual viewers only)
        scope = departments_for(actor, Action.VIEW_INVENTORY)
        ucs = [u for u in db.scalars(select(UseCase).where(UseCase.engagement_id == e.id, UseCase.deleted_at.is_(None)).order_by(UseCase.name))
               if scope is None or u.department_id in scope]
        individual = _may(db, actor, Action.VIEW_INDIVIDUAL_ATTESTATIONS, engagement_id=e.id)
        tools = [t for t in tools_all.values() if individual or not (t.source == "attestation" and t.vendor in TYPED_VENDORS and t.approval_status == "unreviewed")]
        caico = actor.has_role("caico") and _may(db, actor, Action.REGISTER_AI_TOOL, engagement_id=e.id, list_view=True)
        in_audit_tools = {i for a in audit_systems for i in a.tool_ids or []}
        in_audit_ucs = {i for a in audit_systems for i in a.use_case_ids or []}
        tool_depts: dict[str, list] = {}
        for u in ucs:
            for i in u.tool_ids or []:
                if dept(u.department_id) and dept(u.department_id) not in tool_depts.setdefault(i, []):
                    tool_depts[i].append(dept(u.department_id))
        for t in tools:
            home = (by_ref.get(f"tool:{t.id}") or by_key.get(dedupe_key(t.vendor, t.product))) if see_register else None
            rows.append(_row(f"tool:{t.id}", "tool", f"{t.vendor} {t.product}", sources=[TOOL_SOURCE.get(t.source, "inventory")],
                             subtype="Agent" if t.kind == "agent" else "Tool", detail=t.account_type.replace("_", " "), departments=tool_depts.get(t.id, []),
                             stage=f"tool:{t.approval_status}", stage_label=TOOL_STATUS.get(t.approval_status, t.approval_status),
                             registered=(home is not None) if see_register else None, in_register_as={"id": home.id, "name": home.name} if home else None,
                             in_audit=(t.id in in_audit_tools) if may_prefill else None, tool=tool_out(t, counts=individual),
                             can={"approve_tool": caico}))
        for u in ucs:
            home = by_ref.get(f"use_case:{u.id}") if see_register else None
            rows.append(_row(f"use_case:{u.id}", "use_case", u.name, sources=["attestation" if u.created_from_attestation_id else "inventory"],
                             departments=[x for x in [dept(u.department_id)] if x], stage=f"uc:{u.status}", stage_label=USE_CASE_STATUS.get(u.status, u.status),
                             tier=inv.effective_tier(u) if (u.final_tier or u.proposed_tier) else None,
                             registered=(home is not None) if see_register else None, in_register_as={"id": home.id, "name": home.name} if home else None,
                             in_audit=(u.id in in_audit_ucs) if may_prefill else None, use_case=use_case_out(db, u), open=f"/inventory/{u.id}",
                             can={"review_use_case": u.status == "submitted" and _may(db, actor, Action.APPROVE_USE_CASE, engagement_id=e.id, department_id=u.department_id)}))
        inventory = {
            "tiers": {str(t): sum(1 for u in ucs if inv.effective_tier(u) == t) for t in (1, 2, 3)},
            "can_add_tool": _may(db, actor, Action.REGISTER_AI_TOOL, engagement_id=e.id, list_view=True),
            "can_add_use_case": _may(db, actor, Action.SUBMIT_USE_CASE, engagement_id=e.id, list_view=True),
        }

    register = None
    if see_register:
        reg_rows = [r["system"] for r in rows if r["key"].startswith("system:")]
        register = {"kpis": kpis(db, [r for r in reg_rows if r["stage"] != "retired"]), "can": capabilities(db, actor), **options(db, actor)}
    audit = None
    if may_prefill:
        audit = {"engagement_id": e.id, "audit_ref": e.audit_ref, "locked": e.client_answers_locked_at is not None,
                 "can_answer_governance_questions": departments_for(actor, Action.PREFILL_SYSTEM) is None, "systems": len(answerable)}
    return {"rows": rows, "register": register, "inventory": inventory, "audit": audit}


def audit_link(db: Session, actor: Actor, s: RegisterSystem) -> dict | None:
    """The current audit's system taken from this register system, for its record page: only for someone who pre-fills it
    (as the old AI systems page showed it), otherwise None."""
    e = current_engagement(db, actor.organization)
    if e is None or not _may(db, actor, Action.VIEW_ENGAGEMENT, engagement_id=e.id):
        return None
    if not _may(db, actor, Action.PREFILL_SYSTEM, engagement_id=e.id, list_view=True):
        return None
    a = next((x for x in prefillable(db, actor, e) if x.register_system_id == s.id), None)
    return {"system_id": a.id, "reference_id": a.reference_id, "can_answer": True} if a is not None else None
