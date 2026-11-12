"""G-08 EU AI Act conformity: records per register system, sign-off by the Legal/Compliance Reviewer, obligations,
the Annex IV tracker and the FRIA. Applicable articles and the deadline are computed from role and classification
(`app.euaiact.rules`), never stored."""
from __future__ import annotations

from functools import lru_cache

import pycountry
import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.engagements.models import Engagement, EngagementTeam
from app.euaiact import rules
from app.euaiact.models import OBLIGATION_STATUSES, SECTION_STATUSES, EuAiActRecord
from app.laws.importer import SEEDS
from app.register.models import RegisterSystem
from app.tenancy.models import User

ENGAGEMENT_TYPE = "eu_ai_act_readiness"
SIGNOFF_LABELS = {"draft": "Not sent", "awaiting_signoff": "Pending", "signed_off": "Signed", "returned": "Returned"}
OBLIGATION_LABELS = {"not_started": "Not started", "not_met": "Not met", "partly_met": "Partly met", "met": "Met", "not_applicable": "Not applicable"}
# Changing any of these after sign-off takes the sign-off away (the reviewer signed a role and a classification).
SIGNED_FIELDS = ("role", "also_deployer", "classification", "annex_iii_area", "public_service")


@lru_cache(maxsize=1)
def eu_members() -> frozenset[str]:
    return frozenset(yaml.safe_load((SEEDS / "eu_members.yaml").read_text(encoding="utf-8"))["members"])


def _country(code: str) -> str:
    c = pycountry.countries.get(alpha_2=code)
    return getattr(c, "common_name", None) or (c.name if c else code)


def _eu_codes(places) -> list[str]:
    out = []
    for p in places or []:
        code = ((p or {}).get("country") or "").upper()
        if code == "EU" or code in eu_members():
            out.append(code)
    return list(dict.fromkeys(out))


def eu_exposure(s: RegisterSystem) -> str | None:
    """Where the register says the system meets the EU: where it runs, or whose data it uses."""
    run = _eu_codes([s.run_location] if s.run_location else [])
    if run:
        return "Runs in " + ", ".join("the EU" if c == "EU" else _country(c) for c in run)
    data = _eu_codes(s.data_locations)
    if data:
        return "Uses data of people in " + ", ".join("the EU" if c == "EU" else _country(c) for c in data)
    return None


def record_of(db: Session, s: RegisterSystem) -> EuAiActRecord | None:
    return db.scalar(select(EuAiActRecord).where(EuAiActRecord.register_system_id == s.id, EuAiActRecord.deleted_at.is_(None)))


def _ensure(db: Session, actor: User, s: RegisterSystem) -> EuAiActRecord:
    rec = record_of(db, s)
    if rec is None:
        rec = EuAiActRecord(organization_id=s.organization_id, register_system_id=s.id, obligations={}, annex_iv={}, fria={}, created_by=actor.id, updated_by=actor.id)
        db.add(rec)
        db.flush()
    return rec


def systems_for(db: Session, org_id: str, *, everything: bool) -> list[RegisterSystem]:
    """The client's systems for the workspace: on an EU AI Act engagement, every system not retired; from the client
    page, those with EU geography or a record."""
    rows = list(db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == org_id, RegisterSystem.deleted_at.is_(None), RegisterSystem.stage != "retired")
                           .order_by(RegisterSystem.reference)))
    if everything:
        return rows
    have = set(db.scalars(select(EuAiActRecord.register_system_id).where(EuAiActRecord.organization_id == org_id, EuAiActRecord.deleted_at.is_(None))))
    return [s for s in rows if s.id in have or eu_exposure(s)]


def _fria(rec: EuAiActRecord | None) -> bool:
    return rec is not None and rules.fria_required(rec.role, rec.also_deployer, rec.classification, rec.annex_iii_area, rec.public_service)


def _has_annex_iv(rec: EuAiActRecord | None) -> bool:
    return any(o.get("annex_iv") for o in _obligations(rec))


def _obligations(rec: EuAiActRecord | None) -> list[dict]:
    if rec is None:
        return []
    return rules.applicable(rec.role, rec.classification, also_deployer=rec.also_deployer, fria=_fria(rec))


def _role_label(rec: EuAiActRecord | None) -> str | None:
    if rec is None or not rec.role:
        return None
    label = rules.roles().get(rec.role, rec.role)
    return f"{label} (also uses it)" if rec.also_deployer and rec.role != "deployer" else label


def _class_label(rec: EuAiActRecord | None) -> str | None:
    if rec is None or not rec.classification:
        return None
    label = rules.classifications().get(rec.classification, rec.classification)
    area = rules.areas().get(rec.annex_iii_area or "", {}).get("label") if rec.classification == "high_risk_annex_iii" else None
    return f"{label} ({area})" if area else label


def _iso(d) -> str | None:
    return d.isoformat() if d else None


def _deadline(rec: EuAiActRecord | None) -> dict:
    d = rules.deadline_for(rec.classification if rec else None)
    return d | {"date": _iso(d["date"])}


def _counts(rec: EuAiActRecord | None) -> tuple[int, int]:
    obs = _obligations(rec)
    st = (rec.obligations or {}) if rec else {}
    met = sum(1 for o in obs if (st.get(o["key"]) or {}).get("status") in ("met", "not_applicable"))
    return met, len(obs)


def _name(db: Session, uid: str | None) -> str | None:
    u = db.get(User, uid) if uid else None
    return u.name if u else None


def summary(db: Session, s: RegisterSystem, rec: EuAiActRecord | None) -> dict:
    met, total = _counts(rec)
    return {
        "id": s.id, "reference": s.reference, "name": s.name, "eu_exposure": eu_exposure(s), "exposure_basis": rec.exposure_basis if rec else None,
        "role": rec.role if rec else None, "role_label": _role_label(rec), "classification": rec.classification if rec else None, "classification_label": _class_label(rec),
        "deadline": _deadline(rec), "obligations_met": met, "obligations_total": total, "fria_required": _fria(rec),
        "fria_status": ((rec.fria or {}).get("status") or "not_started") if _fria(rec) else None,
        "signoff_status": rec.signoff_status if rec else "draft", "signoff_label": SIGNOFF_LABELS[rec.signoff_status if rec else "draft"],
    }


def _evidence(db: Session, ids: list) -> list[dict]:
    from app.files.models import FileObject

    out = []
    for fid in ids or []:
        f = db.get(FileObject, fid)
        if f is not None and f.deleted_at is None:
            out.append({"id": f.id, "filename": f.filename, "sha256": f.sha256, "uploaded_at": f.created_at.isoformat()})
    return out


def detail(db: Session, s: RegisterSystem, rec: EuAiActRecord | None) -> dict:
    from app.euaiact import lawseed

    lib = lawseed.library_rows(db)
    st = (rec.obligations or {}) if rec else {}
    annex = (rec.annex_iv or {}) if rec else {}
    annex_rows = [{"key": a["key"], "label": a["label"], "status": (annex.get(a["key"]) or {}).get("status") or "not_started", "note": (annex.get(a["key"]) or {}).get("note")}
                  for a in rules.data()["annex_iv"]] if _has_annex_iv(rec) else []
    done = sum(1 for a in annex_rows if a["status"] == "done")
    obligations = []
    for o in _obligations(rec):
        cur = st.get(o["key"]) or {}
        req = lib.get(o["ref"])
        status = cur.get("status") or "not_started"
        obligations.append({
            "key": o["key"], "article": o["article"], "title": o["title"], "status": status, "status_label": OBLIGATION_LABELS[status], "note": cur.get("note"),
            "evidence": _evidence(db, cur.get("evidence_ids")), "checked_by": _name(db, cur.get("by")), "checked_at": cur.get("at"),
            "progress": f"{done} of {len(annex_rows)} sections" if o.get("annex_iv") else None,
            "library": {"code": req.code, "text": req.text, "citation": req.citation, "law_version_id": req.law_version_id} if req is not None else None,
        })
    fria = (rec.fria or {}) if rec else {}
    return summary(db, s, rec) | {
        "client_view": False, "engagement_id": rec.engagement_id if rec else None, "also_deployer": bool(rec and rec.also_deployer),
        "annex_iii_area": rec.annex_iii_area if rec else None, "public_service": bool(rec and rec.public_service), "reasoning": rec.reasoning if rec else None,
        "legal_review_flag": rec.legal_review_flag if rec else True, "classified_by": _name(db, rec.classified_by if rec else None),
        "classified_at": rec.classified_at.isoformat() if rec and rec.classified_at else None,
        "sent_by": _name(db, rec.sent_by if rec else None), "sent_at": rec.sent_at.isoformat() if rec and rec.sent_at else None,
        "signed_off_by": _name(db, rec.signed_off_by if rec else None), "signed_off_at": rec.signed_off_at.isoformat() if rec and rec.signed_off_at else None,
        "signoff_note": rec.signoff_note if rec else None,
        "obligations": obligations, "annex_iv": annex_rows, "annex_iv_done": done,
        "fria": {"status": fria.get("status") or "not_started", "answers": fria.get("answers") or {},
                 "questions": rules.data()["fria"]} if _fria(rec) else None,
    }


def client_view(db: Session, s: RegisterSystem, rec: EuAiActRecord | None) -> dict:
    """What the client's CAICO sees on the register record: the role and classification once signed off, never the
    workspace's working notes."""
    signed = rec is not None and rec.signoff_status == "signed_off"
    if rec is None or not rec.classification:
        status = "Not assessed yet"
    elif signed:
        status = "Signed off by the legal reviewer"
    else:
        status = "With the legal reviewer: the classification shows here once it is signed off"
    return {
        "client_view": True, "id": s.id, "name": s.name, "eu_exposure": eu_exposure(s), "status_text": status,
        "role_label": _role_label(rec) if signed else None, "classification": rec.classification if signed else None,
        "classification_label": _class_label(rec) if signed else None, "deadline": _deadline(rec) if signed else None,
        "signed_off_at": rec.signed_off_at.isoformat() if signed and rec.signed_off_at else None,
    }


# ---------------------------------------------------------------- changes
def _choice(v, allowed, field, msg, errs):
    if v in (None, ""):
        return None
    if v not in allowed:
        errs.append({"field": field, "message": msg})
    return v


def update(db: Session, actor: User, s: RegisterSystem, data: dict) -> EuAiActRecord:
    errs: list[dict] = []
    rec = _ensure(db, actor, s)
    clean: dict = {}
    if "role" in data:
        clean["role"] = _choice(data["role"], rules.roles(), "role", "Choose provider, deployer, importer, distributor or product manufacturer.", errs)
    if "classification" in data:
        clean["classification"] = _choice(data["classification"], rules.classifications(), "classification", "Choose a classification.", errs)
    if "annex_iii_area" in data:
        clean["annex_iii_area"] = _choice(data["annex_iii_area"], rules.areas(), "annex_iii_area", "Choose the Annex III area.", errs)
    for k in ("also_deployer", "public_service", "legal_review_flag"):
        if k in data and data[k] is not None:
            clean[k] = bool(data[k])
    for k, n in (("exposure_basis", 300), ("reasoning", 8000)):
        if k in data:
            clean[k] = (str(data[k] or "").strip()[:n]) or None
    if "engagement_id" in data and data["engagement_id"]:
        e = db.get(Engagement, data["engagement_id"])
        if e is None or e.client_id != s.organization_id or e.deleted_at is not None:
            errs.append({"field": "engagement_id", "message": "That engagement is not this client's."})
        else:
            clean["engagement_id"] = e.id
    cls = clean.get("classification", rec.classification)
    area = clean.get("annex_iii_area", rec.annex_iii_area)
    if cls == "high_risk_annex_iii" and not area and not errs:
        errs.append({"field": "annex_iii_area", "message": "Choose the Annex III area the system falls in."})
    if cls != "high_risk_annex_iii":
        clean["annex_iii_area"] = None
    if errs:
        raise Invalid(errors=errs)
    before = {k: getattr(rec, k) for k in clean}
    changed = {k: v for k, v in clean.items() if getattr(rec, k) != v}
    for k, v in changed.items():
        setattr(rec, k, v)
    if any(k in changed for k in SIGNED_FIELDS + ("reasoning",)):
        rec.classified_by, rec.classified_at = actor.id, utcnow()
    if rec.signoff_status in ("signed_off", "awaiting_signoff") and any(k in changed for k in SIGNED_FIELDS):
        was = rec.signoff_status
        rec.signoff_status = "draft"
        rec.signoff_note = "Changed after sign-off; send it to the legal reviewer again." if was == "signed_off" else "Changed while with the legal reviewer; send it again."
    rec.updated_by = actor.id
    if changed:
        audit.record(db, actor_id=actor.id, action="euaiact.update", obj=rec, before={k: before[k] for k in changed}, after=changed, engagement_id=rec.engagement_id,
                     summary=f"Updated the EU AI Act record of {s.reference} {s.name}")
    db.flush()
    return rec


def _reviewers(db: Session, rec: EuAiActRecord) -> list[User]:
    """Legal/Compliance Reviewers on the client's engagements: on the record's engagement when it has one."""
    q = select(EngagementTeam.user_id).join(Engagement, Engagement.id == EngagementTeam.engagement_id).where(
        EngagementTeam.role == "legal_reviewer", EngagementTeam.deleted_at.is_(None), Engagement.client_id == rec.organization_id, Engagement.deleted_at.is_(None))
    if rec.engagement_id:
        q = q.where(Engagement.id == rec.engagement_id)
    return [u for u in (db.get(User, i) for i in set(db.scalars(q))) if u is not None]


def send_for_signoff(db: Session, actor: User, s: RegisterSystem) -> EuAiActRecord:
    rec = record_of(db, s)
    if rec is None or not rec.role or not rec.classification or not (rec.reasoning or "").strip():
        raise Invalid("Record the role, the classification and the reasoning before sending it for legal sign-off.",
                      [{"field": "classification", "message": "Role, classification and reasoning are needed."}])
    if rec.signoff_status == "signed_off":
        raise Conflict("This classification is already signed off.")
    rec.signoff_status, rec.sent_by, rec.sent_at, rec.signoff_note = "awaiting_signoff", actor.id, utcnow(), None
    audit.record(db, actor_id=actor.id, action="euaiact.send_for_signoff", obj=rec, engagement_id=rec.engagement_id,
                 summary=f"Sent the EU AI Act classification of {s.reference} {s.name} for legal sign-off")
    from app.notifications.service import notify

    link = f"/e/{rec.engagement_id}/eu-ai-act?system={s.id}" if rec.engagement_id else f"/clients/{s.organization_id}/eu-ai-act?system={s.id}"
    notify(db, _reviewers(db, rec), "eu_classification_signoff", f"EU AI Act classification to sign off: {s.name}",
           f"{_role_label(rec)} · {_class_label(rec)}. Sent by {actor.name}.", link)
    db.flush()
    return rec


def decide(db: Session, actor: User, s: RegisterSystem, approve: bool, note: str | None) -> EuAiActRecord:
    rec = record_of(db, s)
    if rec is None or rec.signoff_status != "awaiting_signoff":
        raise Conflict("Nothing is waiting for your sign-off on this system.")
    if actor.id in (rec.classified_by, rec.sent_by):
        raise Forbidden("You classified this system or sent it for sign-off. Another Legal/Compliance Reviewer signs it off; nobody signs off their own classification.")
    now = utcnow()
    rec.signoff_note = (note or "").strip()[:2000] or None
    if approve:
        rec.signoff_status, rec.signed_off_by, rec.signed_off_at = "signed_off", actor.id, now
        rec.signed_snapshot = {k: getattr(rec, k) for k in SIGNED_FIELDS} | {"signed_by": actor.id, "signed_at": now.isoformat()}
    else:
        rec.signoff_status = "returned"
    audit.record(db, actor_id=actor.id, action="euaiact.signoff" if approve else "euaiact.signoff_returned", obj=rec, engagement_id=rec.engagement_id,
                 after={"status": rec.signoff_status, "note": rec.signoff_note},
                 summary=f"{'Signed off' if approve else 'Returned'} the EU AI Act classification of {s.reference} {s.name}")
    from app.notifications.service import notify

    people = [u for u in (db.get(User, i) for i in {rec.sent_by, rec.classified_by} if i) if u is not None]
    link = f"/e/{rec.engagement_id}/eu-ai-act?system={s.id}" if rec.engagement_id else f"/clients/{s.organization_id}/eu-ai-act?system={s.id}"
    notify(db, people, "eu_classification_signed" if approve else "eu_classification_returned",
           f"EU AI Act classification {'signed off' if approve else 'returned'}: {s.name}", rec.signoff_note, link)
    db.flush()
    return rec


def _applicable_key(rec: EuAiActRecord | None, key: str) -> dict:
    o = next((o for o in _obligations(rec) if o["key"] == key), None)
    if o is None:
        raise NotFound("That obligation does not apply to this system's role and classification.")
    return o


def set_obligation(db: Session, actor: User, s: RegisterSystem, key: str, status: str | None, note: str | None) -> EuAiActRecord:
    rec = record_of(db, s)
    o = _applicable_key(rec, key)
    if status is not None and status not in OBLIGATION_STATUSES:
        raise Invalid(errors=[{"field": "status", "message": "Choose met, partly met, not met, not started or not applicable."}])
    obs = dict(rec.obligations or {})
    cur = dict(obs.get(key) or {})
    if status is not None:
        cur["status"] = status
    if note is not None:
        cur["note"] = note.strip()[:2000] or None
    cur["by"], cur["at"] = actor.id, utcnow().isoformat()
    obs[key] = cur
    rec.obligations = obs
    audit.record(db, actor_id=actor.id, action="euaiact.obligation", obj=rec, engagement_id=rec.engagement_id, after={"key": key, "status": cur.get("status")},
                 summary=f"{o['article']} on {s.reference} {s.name}: {OBLIGATION_LABELS[cur.get('status') or 'not_started']}")
    db.flush()
    return rec


def add_evidence(db: Session, settings, actor: User, s: RegisterSystem, key: str, data: bytes, filename: str) -> EuAiActRecord:
    from app.files.service import upload

    rec = record_of(db, s)
    _applicable_key(rec, key)
    f = upload(db, settings, actor, data=data, filename=filename, content_type=None, organization_id=s.organization_id, engagement_id=rec.engagement_id,
               linked_type="euaiact_evidence", linked_id=rec.id)
    obs = dict(rec.obligations or {})
    cur = dict(obs.get(key) or {})
    cur["evidence_ids"] = [*(cur.get("evidence_ids") or []), f.id]
    obs[key] = cur
    rec.obligations = obs
    db.flush()
    return rec


def set_annex_iv(db: Session, actor: User, s: RegisterSystem, section: str, status: str | None, note: str | None) -> EuAiActRecord:
    rec = record_of(db, s)
    if not _has_annex_iv(rec):
        raise Conflict("The Annex IV tracker is for providers of high-risk systems.")
    if section not in {a["key"] for a in rules.data()["annex_iv"]}:
        raise NotFound()
    if status is not None and status not in SECTION_STATUSES:
        raise Invalid(errors=[{"field": "status", "message": "Choose not started, in progress or done."}])
    ax = dict(rec.annex_iv or {})
    cur = dict(ax.get(section) or {})
    if status is not None:
        cur["status"] = status
    if note is not None:
        cur["note"] = note.strip()[:2000] or None
    cur["by"], cur["at"] = actor.id, utcnow().isoformat()
    ax[section] = cur
    rec.annex_iv = ax
    audit.record(db, actor_id=actor.id, action="euaiact.annex_iv", obj=rec, engagement_id=rec.engagement_id, after={"section": section, "status": cur.get("status")},
                 summary=f"Annex IV section {section} on {s.reference} {s.name}: {cur.get('status')}")
    db.flush()
    return rec


def set_fria(db: Session, actor: User, s: RegisterSystem, answers: dict | None, status: str | None) -> EuAiActRecord:
    rec = record_of(db, s)
    if not _fria(rec):
        raise Conflict("A fundamental rights impact assessment is not required for this system's role and classification (Art. 27(1)).")
    if status is not None and status not in SECTION_STATUSES:
        raise Invalid(errors=[{"field": "status", "message": "Choose not started, in progress or done."}])
    keys = {q["key"] for q in rules.data()["fria"]}
    fr = dict(rec.fria or {})
    ans = dict(fr.get("answers") or {})
    for k, v in (answers or {}).items():
        if k in keys:
            ans[k] = str(v or "").strip()[:4000] or None
    fr["answers"] = ans
    if status is not None:
        fr["status"] = status
    fr["by"], fr["at"] = actor.id, utcnow().isoformat()
    rec.fria = fr
    audit.record(db, actor_id=actor.id, action="euaiact.fria", obj=rec, engagement_id=rec.engagement_id, after={"status": fr.get("status")},
                 summary=f"Updated the fundamental rights impact assessment of {s.reference} {s.name}")
    db.flush()
    return rec
