"""Starter price list: the sample items and prices exactly as the SM-14 and SM-15 designs show them, and the four packages.

These rows are demo/starter data (`is_starter`), editable like any other. The real list (93 items) is loaded by a Price
List Owner through SM-14's Excel import. Nothing here is invented: every price, range, status and deliverables text is
from the designs; engagement types and the A-05 platform feature follow spec §2.2 and §4.8. Product names are the
Futran Audit Platform's, so the designs' "AI Governix register" reads "AI register" here."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.models import CatalogChange, CatalogItem, CatalogVersion, PackageTemplate
from app.core.clock import utcnow

A02B_DELIVERABLES = """Independent AI governance audit sized for organisations with 11 to 50 AI systems in scope.
• AI system inventory: every AI tool, vendor feature, agent and shadow-AI use we find, recorded in your AI register on the Futran Audit Platform.
• Risk tier for each system and a scored assessment of the high-risk ones: data and privacy, bias testing, human oversight, security, incidents and vendors.
• Map of the laws that apply to you and the governance roles each law expects, with gaps flagged.
• Review of your AI policies and up to 5 governance or data-policy documents.
• Findings report in plain English, rated Critical to Observation, with a maturity scorecard and a prioritised remediation roadmap.
• One executive or board readout and a signed final report.
Client provides: a project lead, access to system owners, documents on request.
Typical duration: 6–10 weeks."""

A05_DELIVERABLES = """• Every AI tool your people use, including ones nobody approved, from one source per unit: Microsoft 365 / Entra ID, Okta, Google Workspace, expense records or web-proxy logs.
• Your IT admin exports standard reports; Futran matches them to known AI vendors and lists each tool by department and number of users.
• Each tool flagged declared or undeclared and added to your AI register to confirm or dismiss.
• Summary of shadow-AI risk and recommended policy actions.
Delivered by Futran consultants from your exports until automatic connectors are available."""


def _item(code, product, name, billing, low, lst, high, price_status, sellable="available", periods=1, **kw):
    return {"code": code, "product": product, "name": name, "billing": billing, "periods_per_year": periods, "low": low, "list_price": lst, "high": high,
            "price_status": price_status, "sellable_status": sellable, **kw}


STARTER_ITEMS: list[dict] = [
    # SM-14 grid rows
    _item("A-02a", "Audit", "Audit, up to 10 systems", "one_time", 12000, 15000, 18000, "proposed", engagement_type="initial_assessment",
          deliverables="AI inventory and risk tiers for up to 10 systems, law map, policy review (5 docs), findings report with maturity scorecard and roadmap, "
                       "1 board readout, signed final report. 4–6 weeks."),
    _item("A-02b", "Audit", "Audit, 11–50 systems", "one_time", 28000, 35000, 45000, "approved", deliverables=A02B_DELIVERABLES,
          description="Independent AI governance audit of up to 50 AI systems.", delivery_mode="mixed",
          included_quantities={"systems": 50, "docs": 5, "readout": 1}, engagement_type="initial_assessment"),
    _item("A-05", "Audit", "Shadow AI discovery sweep", "one_time", 1000, 1500, 2000, "proposed", "manual_delivery", pricing_unit="per source",
          deliverables=A05_DELIVERABLES, platform_feature_ref="F2 connectors (Phase 3)"),
    _item("L-01", "LL144", "LL144 Readiness Assessment", "one_time", 8500, 8500, 12000, "existing", engagement_type="ll144_bias_audit",
          deliverables="3 weeks: which hiring tools are AEDTs, independent bias audit of the first tool, candidate notices (10 business days before use), "
                       "public audit summary, null-compliance check."),
    _item("L-09", "LL144", "Staffing chain — end-client evidence pack and configuration check", "annual", 750, 1000, 1500, "proposed", pricing_unit="per end-client",
          deliverables="Evidence pack the end-client keeps, notices on that client's NYC jobs, and a check whether the tool is set up differently for that client. "
                       "LL144 needs an audit per tool, not per end-client."),
    _item("M-01a", "Monitor", "Monitor, up to 10 systems", "annual", 10000, 12000, 15000, "proposed",
          deliverables="Your AI register, go-live approval gate, regulatory alerts, automatic checks and reminders, monthly dashboard and digest, 5 user seats."),
    _item("M-09", "Monitor", "Trust Center", "annual", 3600, 4800, 6000, "proposed", "roadmap",
          deliverables="Public page showing your AI commitments, policies, bias-audit summary and optional \"Audited by Futran\" badge, checked against your "
                       "signed report. Not yet sellable with a price."),
    _item("AA-02", "Agent Assure", "15-point pre-deploy check and assurance letter", "one_time", 2500, 3500, 5000, "proposed", pricing_unit="per release",
          deliverables="Runs the gold test set; checks permissions, data access, approval points, logging and kill switch; pass, conditional or fail; "
                       "signed assurance letter."),
    # SM-15 estimate lines not in the SM-14 sample
    _item("A-06b", "Audit", "Attestation, 251–1,000", "one_time", 3000, 4000, 5000, "proposed"),
    _item("A-08a", "Audit", "Vendor AI due diligence", "one_time", 2500, 2500, 2500, "existing"),
    _item("M-07a", "Monitor", "Policy drafting", "one_time", 3500, 5000, 7500, "existing"),
    _item("M-03a", "Monitor", "Alert packs, 1–3 states", "quarterly", 4200, 4200, 4200, "existing", periods=4),
    _item("M-06a", "Monitor", "Evidence vault, base", "annual", 1800, 2400, 3000, "proposed"),
]

STARTER_PACKAGES: list[dict] = [
    {"key": "starter", "name": "Starter (LL144)", "sort": 1, "lines": [{"code": "L-01", "qty": 1}],
     "description": "LL144 readiness for a client using automated hiring tools in New York City."},
    {"key": "governed", "name": "Governed", "sort": 2,
     "lines": [{"code": c, "qty": q} for c, q in (("A-02a", 1), ("A-05", 3), ("A-06b", 1), ("A-08a", 3), ("M-07a", 2), ("M-01a", 1), ("M-03a", 1), ("M-06a", 1))],
     "description": "Audit, discovery, attestation, vendor due diligence and policy drafting, with a year of monitoring."},
    {"key": "agent_ready", "name": "Agent-ready", "sort": 3, "lines": [],
     "description": "No lines yet: the designs do not list this package's items. The Futran Admin adds them here."},
    {"key": "custom", "name": "Custom", "sort": 4, "lines": [], "description": "Start empty and add items by code or search."},
]


def seed_starter(db: Session) -> str:
    """Load the starter items as catalog version 1 and the four packages, once, on an empty price list."""
    if db.scalar(select(CatalogItem.id).limit(1)) is not None or db.scalar(select(CatalogVersion.id).limit(1)) is not None:
        return "already loaded"
    now = utcnow()
    v = CatalogVersion(version=1, saved_by=None, saved_at=now, reason="Starter items from the screen designs (demo data until the workbook is imported)",
                       source="seed", change_count=len(STARTER_ITEMS))
    db.add(v)
    db.flush()
    for spec in STARTER_ITEMS:
        db.add(CatalogItem(catalog_version_id=v.id, version_no=1, is_starter=True, created_at=now, updated_at=now,
                           **{"included_quantities": {}, "applies_to": [], "remediation_of": [], "basis": "$", **spec}))
        db.add(CatalogChange(catalog_version_id=v.id, item_code=spec["code"], field="created", old_value=None, new_value=spec["name"], status="applied",
                             applied_at=now, applied_version_id=v.id, reason=v.reason, changed_at=now))
    for p in STARTER_PACKAGES:
        db.add(PackageTemplate(catalog_version_id=v.id, is_starter=True, **p))
    db.flush()
    return f"{len(STARTER_ITEMS)} starter items and {len(STARTER_PACKAGES)} packages"
