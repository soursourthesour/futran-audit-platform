"""The AI vendor and model catalogue (11-03 C12).

Vendors and their models are platform reference data kept by the Futran Admin. A client's "Other" model is saved for
that client and offered again on its later systems. Once a month the daily job checks the list: with an AI provider
connected (`app.ai.client.client_for`) it asks the model for additions, records the call as an AIInteraction and holds
each addition as a proposal for the Futran Admin to accept or reject; without one it reminds the Futran Admin to review
the list. Nothing changes the catalogue without a person accepting.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.client import AIError, client_for
from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.core.ids import new_id
from app.register.models import ClientModel, ModelCatalogueRun, ModelEntry, ModelProposal, ModelVendor

SEED = Path(__file__).resolve().parents[2] / "seeds" / "model_catalogue.yaml"
FIXED = {"in_house": "In-house model", "unknown": "Unknown, vendor did not disclose"}  # provider answers that are not vendors
REVIEW_LINK = "/admin/reference?tab=models"
PROMPT_VERSION = "model-catalogue-v1"


def _norm(s: str) -> str:
    return " ".join(str(s or "").split()).casefold()


# ---- seed and read
def ensure_seeded(db: Session) -> None:
    """Load the seed file into an empty catalogue, once. A vendor the admin switched off is kept, so this never re-adds."""
    if db.scalar(select(ModelVendor.id).limit(1)) is not None:
        return
    data = yaml.safe_load(SEED.read_text(encoding="utf-8"))
    for i, v in enumerate(data["vendors"]):
        vendor = ModelVendor(code=v["code"], name=v["name"], sort=(i + 1) * 10, source_url=v.get("source"), active=True)
        db.add(vendor)
        db.flush()
        for name in dict.fromkeys(v.get("models") or []):
            db.add(ModelEntry(vendor_id=vendor.id, name=str(name), origin="seed", source_url=v.get("source"), active=True))
    db.flush()


def vendors(db: Session, *, active_only: bool = True) -> list[ModelVendor]:
    ensure_seeded(db)
    stmt = select(ModelVendor)
    if active_only:
        stmt = stmt.where(ModelVendor.active.is_(True))
    return list(db.scalars(stmt.order_by(ModelVendor.sort, ModelVendor.name)))


def models_of(db: Session, vendor_id: str, *, active_only: bool = True) -> list[ModelEntry]:
    stmt = select(ModelEntry).where(ModelEntry.vendor_id == vendor_id)
    if active_only:
        stmt = stmt.where(ModelEntry.active.is_(True))
    return list(db.scalars(stmt.order_by(ModelEntry.created_at, ModelEntry.name)))


def provider_codes(db: Session) -> set[str]:
    """Codes a system's underlying AI provider may take: every catalogue vendor (kept even when switched off, so saved
    systems still validate) and the two answers that are not vendors."""
    ensure_seeded(db)
    return set(db.scalars(select(ModelVendor.code))) | set(FIXED)


def provider_label(db: Session, code: str | None) -> str | None:
    if not code:
        return None
    if code in FIXED:
        return FIXED[code]
    v = db.scalar(select(ModelVendor).where(ModelVendor.code == code))
    return v.name if v else code


def client_catalogue(db: Session, org_id: str) -> dict:
    mine: dict[str, list[str]] = {}
    for m in db.scalars(select(ClientModel).where(ClientModel.organization_id == org_id, ClientModel.deleted_at.is_(None)).order_by(ClientModel.name)):
        mine.setdefault(m.vendor_code, []).append(m.name)
    out = [{"code": v.code, "name": v.name, "models": [m.name for m in models_of(db, v.id)], "client_models": mine.get(v.code, [])} for v in vendors(db)]
    out += [{"code": c, "name": label, "models": [], "client_models": mine.get(c, [])} for c, label in FIXED.items()]
    return {"vendors": out}


def remember_client_model(db: Session, actor_id: str | None, org_id: str, vendor_code: str | None, model_name: str | None) -> ClientModel | None:
    """Save a model the client typed under "Other" so it is offered next time. Catalogue models are not saved."""
    if not vendor_code or not model_name or not model_name.strip():
        return None
    name = " ".join(model_name.split())[:160]
    v = db.scalar(select(ModelVendor).where(ModelVendor.code == vendor_code))
    if v is not None and any(_norm(m.name) == _norm(name) for m in models_of(db, v.id, active_only=False)):
        return None
    have = db.scalar(select(ClientModel).where(ClientModel.organization_id == org_id, ClientModel.vendor_code == vendor_code, func.lower(ClientModel.name) == name.lower()))
    if have is not None:
        if have.deleted_at is not None:
            have.deleted_at = None
        return have
    row = ClientModel(organization_id=org_id, vendor_code=vendor_code, name=name, created_by=actor_id, updated_by=actor_id)
    db.add(row)
    db.flush()
    return row


# ---- the Futran Admin's edits
FORMULA_START = ("=", "+", "-", "@")


def _check_name(name: str, what: str) -> None:
    """Names go into spreadsheets (the import template); one that starts like a formula is refused."""
    if name.startswith(FORMULA_START):
        raise Invalid(errors=[{"field": "name", "message": f"The {what}'s name cannot start with =, +, - or @."}])


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _norm(name)).strip("_")[:30] or "vendor"


def add_vendor(db: Session, actor, name: str, source_url: str | None = None) -> ModelVendor:
    name = " ".join(str(name or "").split())[:120]
    if not name:
        raise Invalid(errors=[{"field": "name", "message": "Enter the vendor's name."}])
    _check_name(name, "vendor")
    ensure_seeded(db)
    if db.scalar(select(ModelVendor.id).where(func.lower(ModelVendor.name) == name.lower())):
        raise Conflict(f"{name} is already in the list.")
    code, n = _slug(name), 2
    while code in provider_codes(db):
        code, n = f"{_slug(name)[:27]}_{n}", n + 1
    top = db.scalar(select(func.max(ModelVendor.sort))) or 0
    v = ModelVendor(code=code, name=name, sort=top + 10, source_url=(source_url or None), updated_by=actor.id, active=True)
    db.add(v)
    db.flush()
    audit.record(db, actor_id=actor.id, action="model_catalogue.vendor_add", object_type="ModelVendor", object_id=v.id, organization_id=actor.organization_id,
                 after={"name": name, "code": code}, summary=f"Added {name} to the AI model list")
    return v


def edit_vendor(db: Session, actor, v: ModelVendor, data: dict) -> ModelVendor:
    before = {"name": v.name, "active": v.active}
    if "name" in data:
        name = " ".join(str(data.get("name") or "").split())[:120]
        if not name:
            raise Invalid(errors=[{"field": "name", "message": "Enter the vendor's name."}])
        _check_name(name, "vendor")
        v.name = name
    if "active" in data:
        v.active = bool(data["active"])
    v.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="model_catalogue.vendor_edit", object_type="ModelVendor", object_id=v.id, organization_id=actor.organization_id,
                 before=before, after={"name": v.name, "active": v.active}, summary=f"Edited {v.name} in the AI model list")
    return v


def add_model(db: Session, actor, vendor: ModelVendor, name: str, *, origin: str = "admin", source_url: str | None = None) -> ModelEntry:
    name = " ".join(str(name or "").split())[:160]
    if not name:
        raise Invalid(errors=[{"field": "name", "message": "Enter the model's name."}])
    _check_name(name, "model")
    if any(_norm(m.name) == _norm(name) for m in models_of(db, vendor.id, active_only=False)):
        raise Conflict(f"{name} is already listed for {vendor.name}.")
    m = ModelEntry(vendor_id=vendor.id, name=name, origin=origin, source_url=source_url, created_by=actor.id, updated_by=actor.id, active=True)
    db.add(m)
    db.flush()
    audit.record(db, actor_id=actor.id, action="model_catalogue.model_add", object_type="ModelEntry", object_id=m.id, organization_id=actor.organization_id,
                 after={"vendor": vendor.name, "name": name, "origin": origin}, summary=f"Added {name} ({vendor.name}) to the AI model list")
    return m


def edit_model(db: Session, actor, m: ModelEntry, data: dict) -> ModelEntry:
    before = {"name": m.name, "active": m.active}
    if "name" in data:
        name = " ".join(str(data.get("name") or "").split())[:160]
        if not name:
            raise Invalid(errors=[{"field": "name", "message": "Enter the model's name."}])
        _check_name(name, "model")
        if any(_norm(x.name) == _norm(name) and x.id != m.id for x in models_of(db, m.vendor_id, active_only=False)):
            raise Conflict(f"{name} is already listed for this vendor.")
        m.name = name
    if "active" in data:
        m.active = bool(data["active"])
    m.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="model_catalogue.model_edit", object_type="ModelEntry", object_id=m.id, organization_id=actor.organization_id,
                 before=before, after={"name": m.name, "active": m.active}, summary=f"Edited {m.name} in the AI model list")
    return m


def decide(db: Session, actor, p: ModelProposal, accept: bool) -> ModelProposal:
    if p.status != "pending":
        raise Conflict("This proposal has already been decided.")
    if accept:
        v = db.scalar(select(ModelVendor).where(ModelVendor.code == p.vendor_code)) if p.vendor_code else None
        v = v or db.scalar(select(ModelVendor).where(func.lower(ModelVendor.name) == p.vendor_name.lower()))
        v = v or add_vendor(db, actor, p.vendor_name)
        if not any(_norm(m.name) == _norm(p.model_name) for m in models_of(db, v.id, active_only=False)):
            add_model(db, actor, v, p.model_name, origin="proposal", source_url=p.source_url)
    p.status, p.decided_by, p.decided_at = ("accepted" if accept else "rejected"), actor.id, utcnow()
    audit.record(db, actor_id=actor.id, action=f"model_catalogue.proposal_{p.status}", object_type="ModelProposal", object_id=p.id, organization_id=actor.organization_id,
                 after={"vendor": p.vendor_name, "model": p.model_name}, summary=f"{'Accepted' if accept else 'Rejected'} the proposed model {p.model_name} ({p.vendor_name})")
    if p.ai_interaction_id:
        from app.ai.models import AIInteraction

        i = db.get(AIInteraction, p.ai_interaction_id)
        open_ = db.scalar(select(ModelProposal.id).where(ModelProposal.ai_interaction_id == p.ai_interaction_id, ModelProposal.status == "pending", ModelProposal.id != p.id).limit(1))
        if i is not None:
            i.result_refs = [*(i.result_refs or []), {"type": "model_proposal", "id": p.id, "status": p.status}]
            if open_ is None:
                i.status, i.decided_by, i.decided_at = "decided", actor.id, utcnow()
    db.flush()
    return p


def admin_page(db: Session) -> dict:
    vs = vendors(db, active_only=False)
    last = db.scalar(select(ModelCatalogueRun).order_by(ModelCatalogueRun.created_at.desc()).limit(1))
    props = db.scalars(select(ModelProposal).where(ModelProposal.status == "pending").order_by(ModelProposal.created_at, ModelProposal.vendor_name))
    return {
        "vendors": [{"id": v.id, "code": v.code, "name": v.name, "active": v.active, "source_url": v.source_url,
                     "models": [{"id": m.id, "name": m.name, "active": m.active, "origin": m.origin} for m in models_of(db, v.id, active_only=False)]} for v in vs],
        "proposals": [{"id": p.id, "vendor_name": p.vendor_name, "model_name": p.model_name, "reason": p.reason, "source_url": p.source_url, "created_at": p.created_at.isoformat()} for p in props],
        "last_check": {"at": last.created_at.isoformat(), "mode": last.mode, "proposals": last.proposals, "error": last.error} if last else None,
    }


# ---- the monthly check
SYSTEM = ("You keep a list of AI vendors and the models they currently offer, used by companies to record which model an AI system uses. "
          "Propose only additions: models or vendors that are generally available now and missing from the list. Do not repeat what is listed. "
          "Give the vendor's own documentation page as the source when you know it. If you are not sure a model exists, leave it out.")
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["proposals"],
          "properties": {"proposals": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["vendor", "model", "reason"],
                                                                   "properties": {"vendor": {"type": "string"}, "model": {"type": "string"}, "reason": {"type": "string"},
                                                                                  "source_url": {"type": "string"}}}}}}


def _futran_admins(db: Session):
    from app.tenancy.models import Organization, RoleAssignment, User

    return list(db.scalars(select(User).join(Organization, Organization.id == User.organization_id).join(RoleAssignment, RoleAssignment.user_id == User.id)
                           .where(Organization.type == "futran", RoleAssignment.role == "admin", RoleAssignment.deleted_at.is_(None), User.deleted_at.is_(None)).distinct()))


def _futran_org_id(db: Session) -> str | None:
    from app.tenancy.models import Organization

    return db.scalar(select(Organization.id).where(Organization.type == "futran", Organization.deleted_at.is_(None)).order_by(Organization.created_at).limit(1))


def run_monthly(db: Session, settings, now: datetime, app_state=None, *, manual_by=None) -> int:
    """Once per calendar month (or when the Futran Admin asks). Returns 1 when a check ran, else 0."""
    from app.notifications.service import notify

    key = f"{now:%Y-%m}" if manual_by is None else new_id()[:10]
    if manual_by is None and db.scalar(select(ModelCatalogueRun.id).where(ModelCatalogueRun.run_key == key)):
        return 0
    ensure_seeded(db)
    run = ModelCatalogueRun(run_key=key, mode="reminder", created_by=manual_by.id if manual_by else None)
    db.add(run)
    db.flush()
    admins = _futran_admins(db)
    client = client_for(app_state, settings or _default_settings(), db)  # the saved AI connection, read from this session
    if client is None:
        notify(db, admins, "model_catalogue_review", "Review the AI model list", "No AI provider is connected, so the monthly check could not look for new models. "
               "Check each vendor's documentation and add what is missing.", REVIEW_LINK)
        return 1
    listed = {v.name: [m.name for m in models_of(db, v.id, active_only=False)] for v in vendors(db, active_only=False)}
    prompt = "The list today, as vendor: models.\n" + "\n".join(f"- {v}: {', '.join(ms) or '(none)'}" for v, ms in listed.items()) + f"\n\nToday is {now:%d %B %Y}."
    try:
        reply = client.complete(task="model_catalogue_refresh", system=SYSTEM, prompt=prompt, schema=SCHEMA, context={"catalogue": listed}, max_tokens=4000)
    except AIError as e:
        run.mode, run.error = "failed", str(e)[:300]
        notify(db, admins, "model_catalogue_review", "Review the AI model list", f"The monthly check could not reach the AI provider ({e}). Check the list by hand.", REVIEW_LINK)
        return 1
    from app.ai.models import AIInteraction

    org_id = _futran_org_id(db) or "futran"
    raw = reply.data.get("proposals") if isinstance(reply.data, dict) else None
    i = AIInteraction(organization_id=org_id, feature="model_catalogue", call_id=new_id(), model=reply.model, provider=reply.provider, prompt_version=PROMPT_VERSION,
                      input_refs=[], target_type="catalogue", output=reply.data, citations=[], status="suggested", result_refs=[],
                      input_tokens=reply.input_tokens, output_tokens=reply.output_tokens, created_by=manual_by.id if manual_by else None)
    db.add(i)
    db.flush()
    by_name = {_norm(v.name): v for v in vendors(db, active_only=False)}
    pending = {(_norm(p.vendor_name), _norm(p.model_name)) for p in db.scalars(select(ModelProposal).where(ModelProposal.status == "pending"))}
    made = 0
    for p in (raw if isinstance(raw, list) else [])[:50]:
        if not isinstance(p, dict):
            continue
        vendor, model = " ".join(str(p.get("vendor") or "").split())[:120], " ".join(str(p.get("model") or "").split())[:160]
        if not vendor or not model or vendor.startswith(FORMULA_START) or model.startswith(FORMULA_START):
            continue
        v = by_name.get(_norm(vendor))
        if v is not None and any(_norm(m) == _norm(model) for m in listed.get(v.name, [])):
            continue
        if (_norm(vendor), _norm(model)) in pending:
            continue
        pending.add((_norm(vendor), _norm(model)))
        url = str(p.get("source_url") or "").strip()
        db.add(ModelProposal(run_id=run.id, ai_interaction_id=i.id, vendor_code=v.code if v else None, vendor_name=v.name if v else vendor, model_name=model,
                             reason=str(p.get("reason") or "")[:2000] or None, source_url=url[:600] if url.startswith("https://") else None))
        made += 1
    run.mode, run.proposals = "ai", made
    if not made:
        i.status = "no_proposals"
    db.flush()
    audit.record(db, actor_id=manual_by.id if manual_by else None, action="ai.suggest", object_type="AIInteraction", object_id=i.id, organization_id=org_id,
                 after={"call_id": i.call_id, "feature": "model_catalogue", "model": reply.model, "provider": reply.provider, "prompt_version": PROMPT_VERSION, "suggestions": made},
                 summary=f"Monthly AI model list check: {made} addition{'s' if made != 1 else ''} proposed")
    notify(db, admins, "model_catalogue_review", f"{made} AI model addition{'s' if made != 1 else ''} to review" if made else "Review the AI model list",
           "Accept or reject each one. Nothing is added until you accept it." if made else "The monthly check proposed nothing new. Check the list against each vendor's documentation.",
           REVIEW_LINK)
    return 1


def _default_settings():
    from app.core.config import get_settings

    return get_settings()


def get_vendor(db: Session, vendor_id: str) -> ModelVendor:
    v = db.get(ModelVendor, vendor_id)
    if v is None:
        raise NotFound()
    return v


def get_model(db: Session, model_id: str) -> ModelEntry:
    m = db.get(ModelEntry, model_id)
    if m is None:
        raise NotFound()
    return m


def get_proposal(db: Session, proposal_id: str) -> ModelProposal:
    p = db.get(ModelProposal, proposal_id)
    if p is None:
        raise NotFound()
    return p
