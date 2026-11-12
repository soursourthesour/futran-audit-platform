"""Independence rules I-1 to I-4 for proposals (spec §4.7). They apply when the opportunity's independence flag is set:
the client is a current or recent Futran audit client.

The flag comes from R2's `sales.independence.flag_for(db, org_id)` when it is installed; otherwise it is computed here
from the engagements: a current engagement (awaiting approval, initiated or in fieldwork), or one completed in the last
12 months.

- I-1 Lines whose catalog `remediation_of` tags match an open finding's area are held until the Chief Auditor approves
  with a note. A finding's area is its template section (a tag "6" or "6.2" matches section 6.2 and 6.2.1) or one of
  its control references, compared without case.
- I-2 Policy drafting (M-07*), AgentWarden (AW-*) or Agent Assure (AA-*): the Chief Auditor confirms a separate delivery
  team; the hand-off (SM-13) records it.
- I-3 Fractional AI Governance Officer (X-01): the person who holds the client role is kept off that client's audit
  team; `app.engagements.team.check_separate_team` enforces it whenever someone is added to an engagement team.
- I-4 The fixed independence statement goes into the document (a note, not an approval).

Each result has the shape of `catalog.guardrails.needed_approvals`: {rule, kind, approver_role, approver, codes, message}."""
import importlib
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow

CURRENT = ("pending_approval", "initiated", "in_progress")
RECENT_DAYS = 365
STATEMENT = ("Futran Solutions is, or has recently been, the independent auditor of [Company]'s AI governance. To protect that "
             "independence, Futran does not sell the remediation of a finding it raised in an open audit, and any policy drafting, "
             "AgentWarden, Agent Assure or Fractional AI Governance Officer work in this proposal is delivered by people who are not on "
             "the audit team.")


def _r2_flag():
    try:
        mod = importlib.import_module("app.sales.independence")
    except ImportError:
        return None
    return getattr(mod, "flag_for", None)


def compute_flag(db: Session, org_id: str) -> tuple[bool, str]:
    from app.engagements.models import Engagement

    rows = list(db.scalars(select(Engagement).where(Engagement.client_id == org_id, Engagement.deleted_at.is_(None))))
    current = [e for e in rows if e.status in CURRENT]
    if current:
        return True, f"Current audit client: {current[0].name} ({current[0].audit_ref or 'no reference yet'}) is {current[0].status.replace('_', ' ')}."
    cutoff = utcnow() - timedelta(days=RECENT_DAYS)
    recent = [e for e in rows if e.status in ("completed", "archived") and e.completed_at and e.completed_at >= cutoff]
    if recent:
        return True, f"Recent audit client: {recent[0].name} was completed on {recent[0].completed_at:%d %b %Y}."
    return False, "Not a current or recent audit client."


def flag_for(db: Session, org_id: str) -> tuple[bool, str]:
    fn = _r2_flag()
    if fn is not None:
        flag, reason = fn(db, org_id)
        return bool(flag), reason or ""
    return compute_flag(db, org_id)


def open_finding_areas(db: Session, org_id: str) -> set[str]:
    from app.engagements.models import Engagement
    from app.findings.models import Finding

    ids = [e.id for e in db.scalars(select(Engagement).where(Engagement.client_id == org_id, Engagement.deleted_at.is_(None), Engagement.status.in_(CURRENT)))]
    if not ids:
        return set()
    areas: set[str] = set()
    for f in db.scalars(select(Finding).where(Finding.engagement_id.in_(ids), Finding.deleted_at.is_(None))):
        if f.template_section:
            areas.add(f.template_section.strip().lower())
        areas |= {str(c).strip().lower() for c in (f.control_refs or []) if c}
    return areas


def _tag_matches(tag: str, areas: set[str]) -> bool:
    t = (tag or "").strip().lower()
    return bool(t) and any(a == t or a.startswith(t + ".") for a in areas)


def _family(code: str) -> str:
    return (code or "").split("-")[0].upper()


def needs_separate_team(code: str) -> bool:
    c = (code or "").upper()
    return c.startswith("M-07") or _family(c) in ("AW", "AA")


def _rule(rule: str, codes: list[str], message: str, kind: str = "approval") -> dict:
    return {"rule": rule, "kind": kind, "approver_role": "chief_auditor" if kind == "approval" else None,
            "approver": "Chief Auditor" if kind == "approval" else None, "codes": codes, "message": message}


def rules(db: Session, org_id: str, lines: list[dict], flag: bool) -> list[dict]:
    """`lines`: offered lines as {code, remediation_of}."""
    if not flag:
        return []
    out = []
    areas = open_finding_areas(db, org_id)
    i1 = [ln["code"] for ln in lines if any(_tag_matches(t, areas) for t in ln.get("remediation_of") or [])]
    if i1:
        out.append(_rule("I-1", i1, f"{', '.join(i1)} would remediate findings Futran raised in an open audit: held until the Chief Auditor approves with a note."))
    i2 = [ln["code"] for ln in lines if needs_separate_team(ln["code"])]
    if i2:
        out.append(_rule("I-2", i2, f"{', '.join(i2)} for systems Futran audits: the Chief Auditor confirms a separate delivery team."))
    i3 = [ln["code"] for ln in lines if (ln["code"] or "").upper().startswith("X-01")]
    if i3:
        out.append(_rule("I-3", i3, "Fractional AI Governance Officer: the person who holds the role is kept off this client's audit team. Chief Auditor."))
    out.append(_rule("I-4", [], "Audit client: the fixed independence statement is added to the document.", kind="note"))
    return out
