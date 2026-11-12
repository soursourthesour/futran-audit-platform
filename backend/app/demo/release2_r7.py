"""Release 2 R7 demo step: a staffing group (G-04), an evidence vault with a legal hold (G-10) and channel partners (G-11).

- Acme Staffing LLC (parent, two LL144 AEDTs), its subsidiary Acme Healthcare Staffing Inc. (whose CAICO has not yet
  consented to roll-up) and three end-clients: two with NYC roles in LL144 scope, one with NJ roles only.
- Metro Retail Inc. with an LL144 audit completed in December 2019: its evidence enters the 90-day deletion countdown,
  and legal hold LH-001 (client counsel request) covers the AEDT 1 evidence.
- Four partners as in the G-11 design: two law firms (no fees), an ATS vendor at 15% and a cloud partner at 20%, with
  referrals both ways and two commissions (one due, one paid).

`seed(m, ids)` runs in the full demo; `seed_e2e(db, settings, password_hash)` gives the browser tests the same data.
All names are examples; every row can be edited or removed in the app.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import today, utcnow
from app.tenancy.models import Organization, RoleAssignment, User
from app.tenancy.service import assign_role, create_organization, create_user

PARENT = "Acme Staffing LLC"
VAULT_CLIENT = "Metro Retail Inc."


def _org(db: Session, name: str, **kw) -> Organization:
    return db.scalar(select(Organization).where(Organization.name == name, Organization.deleted_at.is_(None))) or create_organization(db, name=name, type="client", **kw)


def _user(db: Session, org: Organization, name: str, email: str, role: str, password_hash: str | None) -> User:
    u = db.scalar(select(User).where(User.email == email))
    if u is None:
        u = create_user(db, org, name=name, email=email)
        u.status = "active"
        u.terms_accepted_at = utcnow()
        if password_hash:
            u.password_hash = password_hash
        assign_role(db, u, role)
    return u


def _staff(db: Session, email: str, name: str, role: str, password_hash: str | None) -> User:
    from app.commercial.common import futran_org

    u = db.scalar(select(User).where(User.email == email))
    if u is None:
        u = create_user(db, futran_org(db), name=name, email=email)
        u.status = "active"
        if password_hash:
            u.password_hash = password_hash
    if role not in set(db.scalars(select(RoleAssignment.role).where(RoleAssignment.user_id == u.id, RoleAssignment.deleted_at.is_(None)))):
        assign_role(db, u, role)
    return u


def _hierarchy(db: Session, admin: User, password_hash: str | None) -> dict:
    from app.hierarchy import service as h
    from app.register.models import RegisterSystem

    parent = _org(db, PARENT, status="active", industry="staffing", hq_city="New York", hq_state="NY", hq_country="US")
    if h.children(db, parent.id):
        return {"acme": parent.id}
    _user(db, parent, "Pat Romero", "pat.romero@acmestaffing.example", "caico", password_hash)
    aedts = []
    for ref, name in (("AIS-001", "Candidate ranking (AEDT 1)"), ("AIS-002", "Video interview scoring (AEDT 2)")):
        s = RegisterSystem(organization_id=parent.id, reference=ref, name=name, type="vendor_app", sourcing="vendor", stage="live", decision_impact="consequential",
                           purpose="Ranks or scores candidates for roles the firm places at its end-clients")
        db.add(s)
        aedts.append(s)
    db.flush()
    sub = _org(db, "Acme Healthcare Staffing Inc.", status="active", industry="staffing", hq_city="Newark", hq_state="NJ", hq_country="US")
    _user(db, sub, "Sid Okafor", "sid.okafor@acmehealthcare.example", "caico", password_hash)
    for i, (name, stage, tier) in enumerate([("Nurse shift matching", "live", 3), ("Credential checker", "live", 2), ("Rota forecaster", "proposed", 1)]):
        db.add(RegisterSystem(organization_id=sub.id, reference=f"AIS-{i + 1:03d}", name=name, type="vendor_app", sourcing="vendor", stage=stage, risk_tier=tier))
    h.link(db, admin, parent, sub, "subsidiary")
    for name, in_scope, note in (("Riverside Hospital", True, "NYC roles placed at this client"), ("Brookline Bank", True, "NYC roles placed at this client"),
                                 ("Hudson Logistics", False, "NJ roles only")):
        end = h.add_entity(db, admin, parent, name, "end_client")
        h.set_scope(db, admin, end, {"ll144_in_scope": in_scope, "aedt_system_ids": [s.id for s in aedts] if in_scope else [], "roles_note": note,
                                     "own_public_summary": in_scope})
    db.flush()
    return {"acme": parent.id, "acme_sub": sub.id}


def _vault(db: Session, settings, chief: User, password_hash: str | None) -> dict:
    from app.engagements.models import Engagement
    from app.files.models import FileObject
    from app.files.storage import get_storage
    from app.systems.models import AISystem
    from app.vault import service as vault
    from app.vault.models import LegalHold

    org = _org(db, VAULT_CLIENT, status="active", industry="retail", hq_city="Chicago", hq_state="IL", hq_country="US")
    if db.scalar(select(LegalHold.id).where(LegalHold.organization_id == org.id)):
        return {"metro": org.id}
    _user(db, org, "Maria Lopez", "maria.lopez@metroretail.example", "caico", password_hash)
    done = datetime.combine(today() - timedelta(days=7 * 365 + 2) + timedelta(days=40), datetime.min.time()) + timedelta(hours=12)  # due in about 40 days
    e1 = Engagement(organization_id=org.id, client_id=org.id, name="LL144 audit 2019", type="ll144_bias_audit", status="completed", stage=9, audit_ref="FSL-AI-AUD-2019-014",
                    completed_at=done)
    e2 = Engagement(organization_id=org.id, client_id=org.id, name="Initial assessment 2019", type="initial_assessment", status="completed", stage=9,
                    audit_ref="FSL-AI-AUD-2019-015", completed_at=done + timedelta(days=21))
    db.add_all([e1, e2])
    db.flush()
    # The annual review is already started (a draft carrying the 2019 assessment forward), so the opportunity scan does
    # not raise a renewal audit for Metro Retail; the 2019 evidence and its retention countdown are unchanged.
    db.add(Engagement(organization_id=org.id, client_id=org.id, name="Annual review", type="annual_review", status="draft", stage=1, prior_engagement_id=e2.id))
    db.flush()
    aedt = AISystem(organization_id=org.id, engagement_id=e1.id, name="AEDT 1 · Résumé screening", reference_id="SYS-001")
    db.add(aedt)
    db.flush()
    store = get_storage(settings)
    for e, name, linked, sys_id, mb in ((e1, "Applicant data extract (bias test).csv", "evidence", aedt.id, 84), (e1, "AEDT 1 vendor bias audit 2019.pdf", "evidence", aedt.id, 3),
                                        (e2, "Vendor terms v3.pdf", "evidence", None, 2), (e2, "Interview notes, HR.docx", "evidence", None, 1),
                                        (e2, "AI acceptable use policy.pdf", "governance_document", None, 1)):
        key = store.put(org.id, b"Demo evidence file for the Futran Audit Platform.\n", name)
        db.add(FileObject(organization_id=org.id, engagement_id=e.id, storage_key=key, filename=name, content_type="application/octet-stream", size=mb * 1024 * 1024,
                          sha256="0" * 64, linked_type=linked, linked_id=sys_id or e.id, created_at=e.completed_at - timedelta(days=60)))
    db.flush()
    vault.place_hold(db, chief, org, name="Client counsel request", matter_ref="Doe v. Metro Retail (S.D.N.Y.)",
                     reason="Client counsel asked Futran to keep all AEDT 1 evidence from the 2019 LL144 audit while the matter is open.",
                     scope={"engagement_ids": [e1.id], "system_ids": [aedt.id], "from": "2019-01-01"})
    db.flush()
    return {"metro": org.id}


def _partners(db: Session, sm: User, ids: dict) -> None:
    from app.partners import service as svc
    from app.partners.models import Partner
    from app.sales.models import Opportunity

    if db.scalar(select(Partner.id).limit(1)):
        return
    rows = [("Employment law firm (example)", "law_firm", None, "Referral agreement"), ("Privacy and EU law firm (example)", "law_firm", None, "Referral agreement"),
            ("ATS vendor (example)", "ats_vendor", 15, "Channel agreement"), ("Cloud partner (example)", "cloud_partner", 20, None)]
    ps = {}
    for name, ptype, rate, agreement in rows:
        ps[ptype if ptype != "law_firm" or "Employment" in name else "law2"] = svc.create_partner(db, sm, {"name": name, "type": ptype, "rate_pct": rate, "agreement_label": agreement})
    metro, brook = ids.get("metro"), db.scalar(select(Organization.id).where(Organization.name == "Brookline Bank"))
    opps = []
    for org_id, service, value in ((metro, "Initial assessment and Monitor plan", 52800), (brook, "LL144 bias audit", 18000)):
        if org_id:
            o = Opportunity(organization_id=org_id, trigger="manual", service=service, owner_id=sm.id, stage="won", value=value, closed_at=utcnow())
            db.add(o)
            opps.append(o)
    db.flush()
    for o in opps:
        svc.record_referral(db, sm, ps["ats_vendor"], direction="in", opportunity_id=o.id, note="Joint customer introduced by the vendor's partner team")
    svc.record_referral(db, sm, ps["law_firm"], direction="in", organization_id=metro, note="Asked for an AI audit ahead of litigation")
    svc.record_referral(db, sm, ps["law_firm"], direction="out", organization_id=metro, note="Legal opinion on LL144 applicability")
    svc.record_referral(db, sm, ps["law2"], direction="out", organization_id=metro, note="EU AI Act role assessment")
    for i, (o, ref) in enumerate(zip(opps, ("ORD-0172", "ORD-0151"))):
        c = svc.commission_for_win(db, o, type("O", (), {"id": None, "ref": ref, "organization_id": o.organization_id, "start_on": today() - timedelta(days=10 + 60 * i)})(),
                                   o.value)
        if i == 1 and c is not None:
            svc.mark_paid(db, sm, c)
    db.flush()


def seed_e2e(db: Session, settings, password_hash: str | None) -> dict:
    admin = _staff(db, "admin@futran.demo", "Ada Admin", "admin", password_hash)
    chief = _staff(db, "chief@futran.demo", "Chris Chief", "chief_auditor", password_hash)
    sm = _staff(db, "salesmanager@futran.demo", "Riya Mehta", "sales_manager", password_hash)
    out = _hierarchy(db, admin, password_hash)
    out |= _vault(db, settings, chief, password_hash)
    _partners(db, sm, out)
    db.flush()
    return out


def seed(m, ids: dict) -> dict:
    from app.auth.passwords import hash_password
    from app.demo.seed_demo import DEMO_PASSWORD

    out = seed_e2e(m.db, m.settings, hash_password(DEMO_PASSWORD))
    m.db.commit()
    return out

