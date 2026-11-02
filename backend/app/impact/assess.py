"""Live assessment of a new AI project (screen 28): proposed tier, required depth, AI features and laws matched.

Tier: the §11 rules exactly as the register applies them (`register.service.calc_tier`), so the project and the register
system it becomes always agree. Laws: §10.3 — the applicability engine's scope tests where a law has them (M5), else the
law matrix's geography (the user locations, plus every level above them, e.g. Federal) and AI feature (§10.2).
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.regmaster.engine import EMPLOYMENT

SYSTEM_SECTIONS = ["3.1", "3.2", "3.3", "5.1", "5.1a", "5.2", "5.3", "OS", "6.1", "6.2", "6.3", "V", "7.1", "7.2", "8.1", "8.2", "8.3", "9.2"]
LIGHT_SECTIONS = ["3.1", "3.2", "3.3", "5.1", "5.1a", "5.2", "5.3", "7.2", "9.2"]  # question bank `light: true` (§3, §5, §7.2, §9)
BASELINE_SECTIONS = ["3.1", "3.2", "3.3"]
GENAI_TYPES = ("genai_chat_tool", "foundation_model_api", "agent")
PERSONAL = {"personal", "health", "biometric", "sensitive", "children"}
FEATURE_LABELS = {
    "consequential_decisions_admt": "Consequential decisions (ADMT)", "employment_hiring": "Employment and hiring AI", "privacy_profiling": "Privacy and profiling",
    "health_insurance": "Health and insurance", "chatbots_minors": "Chatbots and minors", "synthetic_content": "Synthetic content", "frontier_safety": "Frontier model safety",
    "biometrics_pricing": "Biometrics and pricing", "government_other": "Government and other",
}
HEALTH = re.compile(r"health|patient|clinical|medical|insur|claim", re.I)
SYNTHETIC = re.compile(r"image|video|voice|audio|deepfake|synthetic|likeness", re.I)
PRICING = re.compile(r"(personali[sz]ed|individuali[sz]ed|algorithmic|dynamic|surveillance)\s+pric", re.I)
BINDING_TYPES = ("statute", "regulation")


def _text(intake: dict) -> str:
    return f"{intake.get('project_name') or ''} {intake.get('purpose') or ''} {intake.get('department_name') or ''}"


def is_employment(intake: dict) -> bool:
    subjects = set(intake.get("data_subjects") or [])
    return intake.get("decision_impact") in ("informs", "consequential") and (bool(EMPLOYMENT.search(_text(intake))) or "candidates" in subjects)


def project_features(intake: dict) -> list[str]:
    """The §10.2 AI features this project touches. Also used to match regulatory updates to register systems."""
    cats = set(intake.get("data_categories") or [])
    text = _text(intake)
    impact = intake.get("decision_impact")
    out = []
    if impact == "consequential":
        out.append("consequential_decisions_admt")
    if is_employment(intake):
        out.append("employment_hiring")
    if cats & PERSONAL:
        out.append("privacy_profiling")
    if "health" in cats or (impact in ("informs", "consequential") and HEALTH.search(text)):
        out.append("health_insurance")
    if "children" in cats:
        out.append("chatbots_minors")
    if intake.get("system_type") in GENAI_TYPES and SYNTHETIC.search(text):
        out.append("synthetic_content")
    if "biometric" in cats or PRICING.search(text):
        out.append("biometrics_pricing")
    return out


def tier_for(intake: dict) -> tuple[int, str]:
    from app.register.models import RegisterSystem, RegisterSystemData
    from app.register.service import calc_tier

    s = RegisterSystem(type=intake.get("system_type") or "vendor_app", sourcing=intake.get("sourcing") or "vendor", decision_impact=intake.get("decision_impact"),
                       autonomy=intake.get("autonomy"))
    d = RegisterSystemData(data_categories=list(intake.get("data_categories") or []), data_subjects=list(intake.get("data_subjects") or []))
    return calc_tier(s, d)


def depth_for(tier: int, intake: dict) -> tuple[str, list[str], str]:
    genai = intake.get("system_type") in GENAI_TYPES or bool(intake.get("public_facing"))
    if tier == 3:
        return "full", list(SYSTEM_SECTIONS), "Full assessment of every system section (§3, §5–§9), including bias testing (§6.2) before go-live."
    if tier == 2:
        sections = LIGHT_SECTIONS + (["8.1"] if genai else [])
        text = "Light assessment (§3, §5, §7.2, §9)"
        return "light", sections, text + (" and the generative AI security questions (§8.1.05)." if genai else ".")
    return "baseline", list(BASELINE_SECTIONS), "Baseline: record the system in the register (§3) and confirm no personal data or decisions about people."


def match_laws(db: Session, jurisdiction_ids: list[str], intake: dict) -> list[dict]:
    from app.laws.models import Regulation
    from app.laws.publish import current_regulations
    from app.reference.models import Jurisdiction
    from app.regmaster.engine import _decide, expand
    from app.regmaster.models import LawVersion, ScopeTest

    geo = expand(db, set(jurisdiction_ids or []))
    features = set(project_features(intake))
    who = [type("P", (), {"name": intake.get("project_name") or "this project"})()]
    facts = {"use_cases": 1, "consequential": who if intake.get("decision_impact") == "consequential" else [],
             "employment": who if intake.get("decision_impact") == "consequential" and is_employment(intake) else []}
    matched, near = [], []
    for reg in sorted(current_regulations(db), key=lambda r: (r.short_name or "")):
        if (reg.short_name or "").startswith("No "):
            continue
        v = db.get(LawVersion, reg.current_version_id) if reg.current_version_id else None
        tests = list(db.scalars(select(ScopeTest).where(ScopeTest.law_version_id == v.id).order_by(ScopeTest.order))) if v else []
        name = reg.short_name
        if v is not None and v.status == "repealed":
            continue
        if tests:
            ok, reason, _ = _decide(db, reg, v, tests, geo, facts, {})
            if ok:
                matched.append({"regulation_id": reg.id, "name": name, "matched": True, "reason": reason.replace("Applies to every client", "Futran default framework")})
            elif reg.feature in features:
                near.append({"regulation_id": reg.id, "name": name, "matched": False, "reason": f"Not matched: {reason[:1].lower()}{reason[1:]}"})
            continue
        if reg.type not in BINDING_TYPES or reg.feature not in features:
            continue
        if reg.jurisdiction_id in geo:  # near misses are listed only for the curated laws with scope tests (above)
            j = db.get(Jurisdiction, reg.jurisdiction_id)
            matched.append({"regulation_id": reg.id, "name": name, "matched": True, "reason": f"Users in {j.name if j else 'scope'}; {FEATURE_LABELS.get(reg.feature, reg.feature).lower()}"})
    seen = set()
    out = []
    for x in matched + near[:5]:
        if x["regulation_id"] in seen:
            continue
        seen.add(x["regulation_id"])
        out.append(x)
    return out


def assess(db: Session, intake: dict) -> dict:
    tier, reason = tier_for(intake)
    depth, sections, text = depth_for(tier, intake)
    return {"tier": tier, "tier_reason": reason, "depth": depth, "depth_sections": sections, "depth_text": text, "features": project_features(intake),
            "feature_labels": [FEATURE_LABELS[f] for f in project_features(intake)], "laws": match_laws(db, intake.get("jurisdiction_ids") or [], intake)}
