"""G-07 Copilot readiness workspace (spec B7): imports kept as evidence, the site risk list, rollout waves with their
gates, the controls checklist, the readiness report and the Copilot entry in the client's AI register."""
from __future__ import annotations

from functools import lru_cache

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.copilot_readiness import imports as imp
from app.copilot_readiness.models import (ACTIONS, CONTROL_STATUSES, PHASES, RISKS, SITE_STATUSES, CopilotControl, CopilotImport, CopilotSite, CopilotWave,
                                          CopilotWorkspace)
from app.core.clock import today, utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.engagements.models import Engagement
from app.files.models import FileObject
from app.laws.importer import SEEDS
from app.tenancy.models import Organization, User

ENGAGEMENT_TYPE = "copilot_readiness"
PHASE_LABELS = {"pilot": "Pilot", "deploy": "Deploy", "operate": "Operate"}
ACTION_LABELS = {"restrict_discovery": "Restrict discovery", "fix_permissions": "Fix permissions", "apply_label": "Apply label", "archive": "Archive", "accept": "Accept"}
SHARING_LABELS = {"everyone": "Everyone", "everyone_except_external": "Everyone except external", "org": "Org-wide", "anyone_link": "Anyone link",
                  "specific": "Specific people", "external": "External guests", "unknown": "Not reported"}
STATUS_LABELS = {"open": "Open", "in_progress": "In progress", "done": "Done"}
CONTROL_LABELS = {"open": "Open", "done": "Done", "not_applicable": "Not applicable"}
RISK_ORDER = {"high": 0, "medium": 1, "low": 2}


@lru_cache(maxsize=1)
def default_controls() -> list[dict]:
    return yaml.safe_load((SEEDS / "copilot_readiness.yaml").read_text(encoding="utf-8"))["controls"]


def template_controls(db: Session) -> list[dict]:
    """The approved G-06 service template's checklist for Copilot readiness, mapped to controls; the starter list
    until the Chief Auditor approves a version."""
    from app.servicetemplates.service import checklist_for

    items = checklist_for(db, ENGAGEMENT_TYPE)
    if not items:
        return default_controls()
    out = []
    for i in items:
        section = str(i.get("section") or "").lower()
        out.append({"key": str(i.get("code") or "")[:40], "label": str(i.get("text") or "")[:300], "phase": section if section in PHASES else "pilot"})
    return [c for c in out if c["key"] and c["label"]] or default_controls()


def find_workspace(db: Session, e: Engagement) -> CopilotWorkspace | None:
    """The engagement's workspace, if the audit team has started it. Never creates one: reads must not write."""
    return db.scalar(select(CopilotWorkspace).where(CopilotWorkspace.engagement_id == e.id, CopilotWorkspace.deleted_at.is_(None)))


def workspace_for(db: Session, e: Engagement, actor_id: str | None = None) -> CopilotWorkspace:
    """The workspace, created on the audit team's first action with the template's controls."""
    ws = find_workspace(db, e)
    if ws is None:
        ws = CopilotWorkspace(organization_id=e.client_id, engagement_id=e.id, phase="pilot", created_by=actor_id, updated_by=actor_id)
        db.add(ws)
        db.flush()
        for i, c in enumerate(template_controls(db), start=1):
            db.add(CopilotControl(organization_id=e.client_id, workspace_id=ws.id, key=c["key"], label=c["label"], phase=c.get("phase", "pilot"), position=i, evidence_ids=[]))
        db.flush()
        audit.record(db, actor_id=actor_id, action="copilot.start", obj=ws, engagement_id=e.id, summary="Started the Copilot readiness workspace")
    return ws


def _control_like(db: Session, ws: CopilotWorkspace, key: str, words: tuple[str, ...]) -> CopilotControl | None:
    """The starter list's control by key, or the template's control whose wording names it."""
    rows = _controls(db, ws)
    return next((c for c in rows if c.key == key), None) or next((c for c in rows if any(w in c.label.casefold() for w in words)), None)


def _sites(db: Session, ws: CopilotWorkspace) -> list[CopilotSite]:
    rows = list(db.scalars(select(CopilotSite).where(CopilotSite.workspace_id == ws.id, CopilotSite.deleted_at.is_(None))))
    return sorted(rows, key=lambda s: (RISK_ORDER[risk(s)], -(s.sensitive_items or 0), s.name.lower()))


def _controls(db: Session, ws: CopilotWorkspace) -> list[CopilotControl]:
    return list(db.scalars(select(CopilotControl).where(CopilotControl.workspace_id == ws.id, CopilotControl.deleted_at.is_(None)).order_by(CopilotControl.position)))


def _waves(db: Session, ws: CopilotWorkspace) -> list[CopilotWave]:
    return list(db.scalars(select(CopilotWave).where(CopilotWave.workspace_id == ws.id, CopilotWave.deleted_at.is_(None)).order_by(CopilotWave.position, CopilotWave.created_at)))


def risk(s: CopilotSite) -> str:
    return s.risk_override or imp.risk_of(s.sharing, s.sensitive_items, s.label_coverage)


def _files(db: Session, ids) -> list[dict]:
    out = []
    for fid in ids or []:
        f = db.get(FileObject, fid)
        if f is not None and f.deleted_at is None:
            out.append({"id": f.id, "filename": f.filename, "sha256": f.sha256})
    return out


def gate(db: Session, w: CopilotWave, sites: dict[str, CopilotSite], controls: dict[str, CopilotControl]) -> tuple[str, str]:
    """("go" | "hold", text). Every gate site done and every gate control done or not applicable, and no manual hold."""
    if w.hold_note:
        return "hold", f"Hold · {w.hold_note}"
    reasons = []
    open_sites = [sid for sid in w.gate_site_ids or [] if sid in sites and sites[sid].status != "done"]
    if open_sites:
        reasons.append(f"{len(open_sites)} site{'s' if len(open_sites) > 1 else ''} open")
    reasons += [controls[k].label for k in w.gate_control_keys or [] if k in controls and controls[k].status not in ("done", "not_applicable")]
    return ("hold", "Hold · " + ", ".join(reasons)) if reasons else ("go", "Go")


def view(db: Session, e: Engagement, ws: CopilotWorkspace, *, client: bool) -> dict:
    sites = _sites(db, ws)
    controls = _controls(db, ws)
    by_site, by_ctl = {s.id: s for s in sites}, {c.key: c for c in controls}
    from app.register.models import RegisterSystem

    reg = db.get(RegisterSystem, ws.register_system_id) if ws.register_system_id else None
    imports = list(db.scalars(select(CopilotImport).where(CopilotImport.workspace_id == ws.id, CopilotImport.deleted_at.is_(None)).order_by(CopilotImport.created_at.desc())))
    names = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_({i.created_by for i in imports if i.created_by})))} if imports else {}
    waves = []
    for w in _waves(db, ws):
        g, text = gate(db, w, by_site, by_ctl)
        waves.append({"id": w.id, "name": w.name, "groups": w.groups, "user_count": w.user_count, "planned_on": w.planned_on.isoformat() if w.planned_on else None,
                      "gate_site_ids": w.gate_site_ids or [], "gate_control_keys": w.gate_control_keys or [], "hold_note": w.hold_note, "gate": g, "gate_text": text})
    report = db.get(FileObject, ws.report_file_id) if ws.report_file_id else None
    org = db.get(Organization, e.client_id)
    return {
        "engagement": {"id": e.id, "name": e.name, "audit_ref": e.audit_ref}, "client": {"id": org.id, "name": org.name}, "client_view": client,
        "phase": ws.phase, "phase_label": PHASE_LABELS[ws.phase], "usage_as_of": ws.usage_as_of.isoformat() if ws.usage_as_of else None, "by_department": ws.by_department or [],
        "summary": {"licences": ws.licences, "active_users": ws.active_users, "high_risk_sites": sum(1 for s in sites if risk(s) == "high"),
                    "controls_ready": sum(1 for c in controls if c.status in ("done", "not_applicable")), "controls_total": len(controls)},
        "sites": [{
            "id": s.id, "name": s.name, "url": s.url, "site_owner": s.site_owner, "label_coverage": s.label_coverage, "sharing": s.sharing,
            "sharing_label": SHARING_LABELS.get(s.sharing, s.sharing), "sensitive_items": s.sensitive_items, "last_activity": s.last_activity.isoformat() if s.last_activity else None,
            "risk": risk(s), "risk_overridden": bool(s.risk_override), "action": s.action, "action_label": ACTION_LABELS.get(s.action or ""), "action_owner": s.action_owner,
            "status": s.status, "status_label": STATUS_LABELS[s.status], "note": s.note, "sources": s.sources or [],
        } for s in sites],
        "waves": waves,
        "controls": [{"key": c.key, "label": c.label, "phase": c.phase, "status": c.status, "status_label": CONTROL_LABELS[c.status], "note": c.note,
                      "evidence": [] if client else _files(db, c.evidence_ids)} for c in controls],
        "imports": [{"id": i.id, "kind": i.kind, "kind_label": imp.KINDS[i.kind]["label"], "filename": (db.get(FileObject, i.file_id).filename if i.file_id else None),
                     "file_id": None if client else i.file_id, "sha256": i.sha256, "rows_read": i.rows_read, "rows_used": i.rows_used, "imported_by": names.get(i.created_by),
                     "imported_at": i.created_at.isoformat()} for i in imports],
        "register_entry": {"id": reg.id, "reference": reg.reference, "name": reg.name} if reg is not None and reg.deleted_at is None else None,
        "register_candidates": [] if client or reg is not None else [{"id": x.id, "reference": x.reference, "name": x.name} for x, _ in register_candidates(db, e.client_id)],
        "register_choices": [] if client or reg is not None else [{"id": x.id, "reference": x.reference, "name": x.name} for x in register_choices(db, e.client_id)],
        "report": {"file_id": report.id, "filename": report.filename, "created_at": ws.report_at.isoformat() if ws.report_at else None} if report is not None else None,
        "options": {"phases": PHASE_LABELS, "actions": ACTION_LABELS, "statuses": STATUS_LABELS, "risks": {"high": "High", "medium": "Medium", "low": "Low"},
                    "control_statuses": CONTROL_LABELS, "import_kinds": {k: {"label": v["label"], "source": v["source"]} for k, v in imp.KINDS.items()}},
    }


# ---------------------------------------------------------------- imports
def import_file(db: Session, settings, actor: User, e: Engagement, ws: CopilotWorkspace, kind: str, data: bytes, filename: str) -> CopilotImport:
    from app.files.service import upload

    parsed = imp.parse(kind, data, filename, today())  # refuses a file without the columns before anything is stored
    f = upload(db, settings, actor, data=data, filename=filename, content_type=None, organization_id=e.client_id, engagement_id=e.id,
               linked_type="copilot_import", linked_id=ws.id)
    row = CopilotImport(organization_id=e.client_id, workspace_id=ws.id, kind=kind, file_id=f.id, sha256=f.sha256, rows_read=parsed.rows_read,
                        rows_used=parsed.rows_used, created_by=actor.id, summary={})
    db.add(row)
    if kind == "licence_usage":
        ws.licences, ws.active_users, ws.usage_as_of, ws.by_department = parsed.licences, parsed.active_users, parsed.usage_as_of, parsed.by_department
        row.summary = {"licences": parsed.licences, "active_users": parsed.active_users, "as_of": parsed.usage_as_of.isoformat() if parsed.usage_as_of else None}
    else:
        have = {s.site_key: s for s in db.scalars(select(CopilotSite).where(CopilotSite.workspace_id == ws.id, CopilotSite.deleted_at.is_(None)))}
        added = 0
        for p in parsed.sites:
            s = have.get(p["key"])
            if s is None and p.get("url") is None:
                s = next((x for x in have.values() if x.name.lower() == p["name"].lower()), None)
            if s is None:
                s = CopilotSite(organization_id=e.client_id, workspace_id=ws.id, site_key=p["key"], name=p["name"], status="open", sources=[], created_by=actor.id)
                db.add(s)
                have[p["key"]] = s
                added += 1
            for k in ("url", "last_activity", "sensitive_items", "label_coverage", "sharing"):
                if p.get(k) is not None and not (k == "sharing" and p[k] == "unknown" and s.sharing not in (None, "unknown")):
                    setattr(s, k, p[k])
            if p.get("owner"):
                s.site_owner = p["owner"]
            s.sources = list(dict.fromkeys([*(s.sources or []), kind]))
            s.updated_by = actor.id
        row.summary = {"sites": len(parsed.sites), "new_sites": added}
        ctl = _control_like(db, ws, "oversharing_report", ("oversharing",))
        if ctl is not None:
            ctl.evidence_ids = [*(ctl.evidence_ids or []), f.id]
    db.flush()
    audit.record(db, actor_id=actor.id, action="copilot.import", obj=row, engagement_id=e.id, after={"kind": kind, "sha256": f.sha256, "rows": parsed.rows_used},
                 summary=f"Imported {imp.KINDS[kind]['label'].lower()} {f.filename} ({parsed.rows_used} rows, SHA-256 {f.sha256[:12]}…)")
    return row


# ---------------------------------------------------------------- sites, waves, controls, phase
CLIENT_SITE_FIELDS = {"action_owner", "status", "note"}


def update_site(db: Session, actor: User, ws: CopilotWorkspace, site_id: str, data: dict) -> CopilotSite:
    s = db.get(CopilotSite, site_id)
    if s is None or s.workspace_id != ws.id or s.deleted_at is not None:
        raise NotFound()
    errs = []
    if "action" in data and data["action"] not in (None, *ACTIONS):
        errs.append({"field": "action", "message": "Choose restrict discovery, fix permissions, apply label, archive or accept."})
    if "status" in data and data["status"] not in SITE_STATUSES:
        errs.append({"field": "status", "message": "Choose open, in progress or done."})
    if "risk_override" in data and data["risk_override"] not in (None, *RISKS):
        errs.append({"field": "risk_override", "message": "Choose high, medium or low."})
    if errs:
        raise Invalid(errors=errs)
    before = {k: getattr(s, k) for k in data}
    for k in ("action", "status", "risk_override"):
        if k in data:
            setattr(s, k, data[k])
    for k, n in (("action_owner", 200), ("note", 2000)):
        if k in data:
            setattr(s, k, (str(data[k] or "").strip()[:n]) or None)
    s.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="copilot.site", obj=s, engagement_id=ws.engagement_id, before=before, after={k: getattr(s, k) for k in data},
                 summary=f"Updated Copilot site {s.name}")
    db.flush()
    return s


def _wave_fields(db: Session, ws: CopilotWorkspace, data: dict) -> dict:
    errs, out = [], {}
    if "name" in data:
        out["name"] = (str(data["name"] or "").strip())[:120]
        if not out["name"]:
            errs.append({"field": "name", "message": "Name the wave."})
    for k, n in (("groups", 400), ("hold_note", 400)):
        if k in data:
            out[k] = (str(data[k] or "").strip()[:n]) or None
    if "user_count" in data:
        v = data["user_count"]
        if v in (None, ""):
            out["user_count"] = None
        elif not isinstance(v, int) or v < 0:
            errs.append({"field": "user_count", "message": "Enter a whole number."})
        else:
            out["user_count"] = v
    if "planned_on" in data:
        d = imp.parse_date(data["planned_on"]) if data["planned_on"] else None
        if data["planned_on"] and d is None:
            errs.append({"field": "planned_on", "message": "Enter a date."})
        out["planned_on"] = d
    if "gate_site_ids" in data:
        ids = list(dict.fromkeys(data["gate_site_ids"] or []))
        mine = {s.id for s in _sites(db, ws)}
        if any(i not in mine for i in ids):
            errs.append({"field": "gate_site_ids", "message": "Choose sites from this workspace's site risk list."})
        out["gate_site_ids"] = ids
    if "gate_control_keys" in data:
        keys = list(dict.fromkeys(data["gate_control_keys"] or []))
        mine = {c.key for c in _controls(db, ws)}
        if any(k not in mine for k in keys):
            errs.append({"field": "gate_control_keys", "message": "Choose controls from this workspace's checklist."})
        out["gate_control_keys"] = keys
    if errs:
        raise Invalid(errors=errs)
    return out


def add_wave(db: Session, actor: User, ws: CopilotWorkspace, data: dict) -> CopilotWave:
    fields = _wave_fields(db, ws, {"name": data.get("name")} | data)
    w = CopilotWave(organization_id=ws.organization_id, workspace_id=ws.id, position=len(_waves(db, ws)) + 1, created_by=actor.id, **fields)
    db.add(w)
    db.flush()
    audit.record(db, actor_id=actor.id, action="copilot.wave_add", obj=w, engagement_id=ws.engagement_id, summary=f"Added Copilot rollout wave {w.name}")
    return w


def _wave(db: Session, ws: CopilotWorkspace, wave_id: str) -> CopilotWave:
    w = db.get(CopilotWave, wave_id)
    if w is None or w.workspace_id != ws.id or w.deleted_at is not None:
        raise NotFound()
    return w


def update_wave(db: Session, actor: User, ws: CopilotWorkspace, wave_id: str, data: dict) -> CopilotWave:
    w = _wave(db, ws, wave_id)
    for k, v in _wave_fields(db, ws, data).items():
        setattr(w, k, v)
    w.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="copilot.wave_update", obj=w, engagement_id=ws.engagement_id, after={k: str(v) for k, v in data.items()},
                 summary=f"Updated Copilot rollout wave {w.name}")
    db.flush()
    return w


def delete_wave(db: Session, actor: User, ws: CopilotWorkspace, wave_id: str) -> None:
    w = _wave(db, ws, wave_id)
    w.deleted_at = utcnow()
    audit.record(db, actor_id=actor.id, action="copilot.wave_delete", obj=w, engagement_id=ws.engagement_id, summary=f"Removed Copilot rollout wave {w.name}")
    db.flush()


def _control(db: Session, ws: CopilotWorkspace, key: str) -> CopilotControl:
    c = db.scalar(select(CopilotControl).where(CopilotControl.workspace_id == ws.id, CopilotControl.key == key, CopilotControl.deleted_at.is_(None)))
    if c is None:
        raise NotFound()
    return c


def update_control(db: Session, actor: User, ws: CopilotWorkspace, key: str, status: str | None, note: str | None) -> CopilotControl:
    c = _control(db, ws, key)
    if status is not None and status not in CONTROL_STATUSES:
        raise Invalid(errors=[{"field": "status", "message": "Choose open, done or not applicable."}])
    if status is not None:
        c.status = status
    if note is not None:
        c.note = note.strip()[:2000] or None
    c.checked_by, c.checked_at = actor.id, utcnow()
    audit.record(db, actor_id=actor.id, action="copilot.control", obj=c, engagement_id=ws.engagement_id, after={"key": key, "status": c.status},
                 summary=f"Copilot control “{c.label}”: {CONTROL_LABELS[c.status]}")
    db.flush()
    return c


def control_evidence(db: Session, settings, actor: User, ws: CopilotWorkspace, key: str, data: bytes, filename: str) -> CopilotControl:
    from app.files.service import upload

    c = _control(db, ws, key)
    f = upload(db, settings, actor, data=data, filename=filename, content_type=None, organization_id=ws.organization_id, engagement_id=ws.engagement_id,
               linked_type="copilot_import", linked_id=ws.id)
    c.evidence_ids = [*(c.evidence_ids or []), f.id]
    db.flush()
    return c


def set_phase(db: Session, actor: User, ws: CopilotWorkspace, phase: str) -> None:
    if phase not in PHASES:
        raise Invalid(errors=[{"field": "phase", "message": "Choose pilot, deploy or operate."}])
    before, ws.phase = ws.phase, phase
    audit.record(db, actor_id=actor.id, action="copilot.phase", obj=ws, engagement_id=ws.engagement_id, before={"phase": before}, after={"phase": phase},
                 summary=f"Copilot readiness phase set to {PHASE_LABELS[phase]}")
    db.flush()


# ---------------------------------------------------------------- register entry
COPILOT_VENDOR, COPILOT_NAME = "Microsoft", "Microsoft 365 Copilot"
LIKELY_NAMES = {"copilot", "microsoft copilot", "microsoft 365 copilot", "m365 copilot", "ms copilot", "office 365 copilot", "copilot for microsoft 365",
                "microsoft copilot for microsoft 365", "copilot for m365"}


def _register_rows(db: Session, org_id: str) -> list:
    from app.register.models import RegisterSystem

    return list(db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == org_id, RegisterSystem.deleted_at.is_(None), RegisterSystem.stage != "retired")
                           .order_by(RegisterSystem.reference)))


def register_candidates(db: Session, org_id: str) -> list[tuple]:
    """[(system, exact)] already in the client's register that are likely Microsoft 365 Copilot: the register's own
    dedupe key (vendor|product) for Microsoft 365 Copilot is an exact match; the usual names are likely ones."""
    from app.register.seeding import dedupe_key, svc_key

    target = dedupe_key(COPILOT_VENDOR, COPILOT_NAME)
    out = []
    for s in _register_rows(db, org_id):
        exact = (s.dedupe_key or svc_key(s, db)) == target
        if exact or " ".join(s.name.split()).casefold() in LIKELY_NAMES:
            out.append((s, exact))
    return out


def register_choices(db: Session, org_id: str) -> list:
    """Systems the audit team can link: any whose name mentions Copilot, then the rest of the register."""
    rows = _register_rows(db, org_id)
    return [s for s in rows if "copilot" in s.name.casefold()] or rows


COPILOT_PURPOSE = "Microsoft 365 Copilot: drafts, summarises and searches across email, chats, meetings and files the user can already open."


def register_entry(db: Session, actor: User, e: Engagement, ws: CopilotWorkspace, system_id: str | None) -> None:
    """Link an existing register system, or create the Copilot entry with the client's suggested laws (its required
    roles follow from them). Never a second entry."""
    from app.register import service as reg
    from app.register.models import RegisterSystem

    org = db.get(Organization, e.client_id)
    if system_id:
        s = db.get(RegisterSystem, system_id)
        if s is None or s.organization_id != org.id or s.deleted_at is not None or s.stage == "retired":
            raise NotFound()
        summary = f"Linked {s.reference} {s.name} as the Copilot entry in the AI register"
    elif ws.register_system_id and (s := db.get(RegisterSystem, ws.register_system_id)) is not None and s.deleted_at is None:
        return
    elif (found := register_candidates(db, org.id)):
        exact = [x for x in found if x[1]]
        if len(exact) != 1:
            names = ", ".join(f"{x[0].reference} {x[0].name}" for x in found)
            raise Conflict(f"The AI register already lists what looks like Copilot ({names}). Link to the existing system instead of adding another.")
        s = exact[0][0]
        summary = f"Linked {s.reference} {s.name} as the Copilot entry in the AI register (it was already there)"
    else:
        s = reg.create_system(db, actor, org, {"name": "Microsoft 365 Copilot", "type": "genai_chat_tool", "sourcing": "vendor", "stage": "proposed", "company_wide": True,
                                               "vendor_name": "Microsoft", "purpose": COPILOT_PURPOSE, "user_count": ws.licences},
                              reason=f"Copilot readiness engagement {e.audit_ref}")
        laws = [x["regulation_id"] for x in reg.suggested_laws(db, s)]
        if laws:
            reg.accept_suggestions(db, actor, s, laws, reason="Laws in scope for the client")
        summary = f"Added {s.reference} Microsoft 365 Copilot to the AI register"
    ws.register_system_id = s.id
    ctl = _control_like(db, ws, "register_entry", ("ai register",))
    if ctl is not None and ctl.status != "done":
        ctl.status, ctl.checked_by, ctl.checked_at = "done", actor.id, utcnow()
        ctl.note = f"{s.reference} {s.name}"
    audit.record(db, actor_id=actor.id, action="copilot.register_entry", obj=ws, engagement_id=e.id, after={"register_system_id": s.id}, summary=summary)
    db.flush()


# ---------------------------------------------------------------- readiness report
def _day(iso: str | None) -> str:
    if not iso:
        return "—"
    d = imp.parse_date(iso[:10])
    return f"{d.day} {d.strftime('%b %Y')}" if d else iso


def _hash(h: str) -> str:
    """The full hash in groups of 16, so the PDF table can wrap it."""
    return " ".join(h[i:i + 16] for i in range(0, len(h), 16))


def _md_cell(v) -> str:
    return str("—" if v in (None, "") else v).replace("|", "/").replace("\n", " ")


def report_markdown(db: Session, e: Engagement, ws: CopilotWorkspace) -> str:
    v = view(db, e, ws, client=False)
    s = v["summary"]
    on = today()
    lines = ["# Microsoft 365 Copilot readiness", "", f"**{v['client']['name']}** · {e.audit_ref} · {on.day} {on.strftime('%B %Y')}", "",
             f"Phase: **{v['phase_label']}**. Copilot licences: **{s['licences'] if s['licences'] is not None else 'not imported'}**; "
             f"active users in the 28 days to {_day(v['usage_as_of'])}: **{s['active_users'] if s['active_users'] is not None else '—'}**. "
             f"High-risk sites: **{s['high_risk_sites']}**. Controls ready: **{s['controls_ready']} of {s['controls_total']}**.", ""]
    ready = [w for w in v["waves"] if w["gate"] == "go"]
    lines += ["## Summary", "",
              (f"{len(ready)} of {len(v['waves'])} rollout waves can go ahead now." if v["waves"] else "No rollout waves are planned yet.") + " "
              + (f"{s['high_risk_sites']} sites hold broadly shared sensitive content and should be fixed or restricted before wider rollout." if s["high_risk_sites"] else
                 "No site in the imported reports is high risk."), ""]
    lines += ["## Site risk list", ""]
    if v["sites"]:
        lines += ["| Site | Sharing | Sensitive items | Label coverage | Risk | Action | Owner | Status |", "|---|---|---|---|---|---|---|---|"]
        for x in v["sites"]:
            cov = f"{x['label_coverage']:g}%" if x["label_coverage"] is not None else None
            sens = f"{x['sensitive_items']:,}" if x["sensitive_items"] is not None else None
            lines.append(f"| {_md_cell(x['name'])} | {_md_cell(x['sharing_label'])} | {_md_cell(sens)} | {_md_cell(cov)} | "
                         f"{x['risk'].capitalize()} | {_md_cell(x['action_label'])} | {_md_cell(x['action_owner'])} | {x['status_label']} |")
    else:
        lines.append("No Purview or SharePoint report has been imported.")
    lines += ["", "## Rollout waves", ""]
    if v["waves"]:
        lines += ["| Wave | Groups | Users | Date | Gate |", "|---|---|---|---|---|"]
        for w in v["waves"]:
            lines.append(f"| {_md_cell(w['name'])} | {_md_cell(w['groups'])} | {_md_cell(w['user_count'])} | {_day(w['planned_on'])} | {_md_cell(w['gate_text'])} |")
    else:
        lines.append("No waves planned yet.")
    lines += ["", "## Controls checklist", "", "| Control | Phase | Status | Evidence |", "|---|---|---|---|"]
    for c in v["controls"]:
        lines.append(f"| {_md_cell(c['label'])} | {PHASE_LABELS.get(c['phase'], c['phase'])} | {c['status_label']} | {len(c['evidence'])} file{'s' if len(c['evidence']) != 1 else ''} |")
    if v["by_department"]:
        lines += ["", "## Licences and active users by department", "", "| Department | Licences | Active, 28 days |", "|---|---|---|"]
        lines += [f"| {_md_cell(d['department'])} | {d['licences']} | {d['active']} |" for d in v["by_department"]]
    reg = v["register_entry"]
    lines += ["", "## AI register", "", f"Copilot is in the AI register as {reg['reference']} {reg['name']}." if reg else "Copilot is not yet in the client's AI register."]
    lines += ["", "## Evidence", "", "Each imported report is kept as evidence with its SHA-256 hash.", ""]
    if v["imports"]:
        lines += ["| Report | File | Imported | SHA-256 |", "|---|---|---|---|"]
        lines += [f"| {i['kind_label']} | {_md_cell(i['filename'])} | {_day(i['imported_at'])} | {_hash(i['sha256'])} |" for i in v["imports"]]
    else:
        lines.append("No reports imported yet.")
    return "\n".join(lines) + "\n"


def make_report(db: Session, settings, actor: User, e: Engagement, ws: CopilotWorkspace) -> FileObject:
    from app.documents.pdf import to_pdf
    from app.files.service import upload

    org = db.get(Organization, e.client_id)
    data = to_pdf(report_markdown(db, e, ws), "Microsoft 365 Copilot readiness", {"audit_ref": e.audit_ref or org.name})
    stamp = today().isoformat()
    f = upload(db, settings, actor, data=data, filename=f"Copilot readiness report {org.name} {stamp}.pdf", content_type="application/pdf", organization_id=org.id,
               engagement_id=e.id, linked_type="copilot_report", linked_id=ws.id)
    ws.report_file_id, ws.report_at = f.id, utcnow()
    audit.record(db, actor_id=actor.id, action="copilot.report", obj=ws, engagement_id=e.id, after={"file_id": f.id, "sha256": f.sha256},
                 summary=f"Produced the Copilot readiness report ({f.filename})")
    db.flush()
    return f

