"""Law suggestion for the new-client wizard (spec §10.3, schematic D4)."""
from dataclasses import asdict, dataclass

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engagements.models import ClientLocation, Engagement
from app.laws.importer import FEATURE_LABELS
from app.laws.models import Regulation
from app.reference.jurisdictions import SEEDS
from app.reference.models import Jurisdiction
from app.tenancy.models import Organization

# Words in the client's industry or engagement reason → the AI feature they point to.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "employment_hiring": ("hiring", "hire", "recruit", "staffing", "candidate", "applicant", "talent", "hr "),
    "health_insurance": ("insur", "health", "clinic", "patient", "hospital", "claims", "pharma"),
    "consequential_decisions_admt": ("credit", "lend", "loan", "bank", "bfsi", "underwrit", "mortgage"),
    "chatbots_minors": ("chatbot", "chat bot", "virtual assistant", "companion"),
}
LEVEL_ORDER = {"city": 0, "state": 1, "country": 2, "supranational": 3}


@dataclass
class Suggestion:
    regulation_id: str | None
    label: str
    jurisdiction_code: str
    jurisdiction_name: str
    feature: str
    reason: str
    source: str  # auto | futran_default
    prechecked: bool

    def to_json(self) -> dict:
        return asdict(self) | {"feature_label": FEATURE_LABELS.get(self.feature, self.feature)}


def matched_features(org: Organization, engagement: Engagement | None = None) -> set[str]:
    text = " ".join(filter(None, [org.industry, org.engagement_reason, engagement.business_processes if engagement else None])).lower() + " "
    return {feature for feature, words in KEYWORDS.items() if any(w in text for w in words)}


def _defaults() -> list[dict]:
    return yaml.safe_load((SEEDS / "futran_defaults.yaml").read_text())["defaults"]


def suggest_requirements(db: Session, org: Organization, engagement: Engagement | None = None) -> list[Suggestion]:
    """Every deployer law reaching an in-scope site; laws matching the client's AI use and Futran defaults pre-checked."""
    locs = list(db.scalars(select(ClientLocation).where(ClientLocation.organization_id == org.id, ClientLocation.in_scope.is_(True), ClientLocation.deleted_at.is_(None))))
    sites_by_j: dict[str, list[str]] = {}
    for loc in locs:
        for jid in loc.jurisdiction_ids or []:
            sites_by_j.setdefault(jid, []).append(loc.site_name)
    juris = {j.id: j for j in db.scalars(select(Jurisdiction).where(Jurisdiction.id.in_(list(sites_by_j))))}
    codes = {j.code for j in juris.values()}
    features = matched_features(org, engagement)

    regs = list(db.scalars(select(Regulation).where(
        Regulation.jurisdiction_id.in_(list(juris)),
        Regulation.superseded_by_id.is_(None),
        Regulation.retired_in_version_id.is_(None),
        Regulation.applies_to != "developer",
    )))
    defaults: dict[str, dict] = {}
    out: list[Suggestion] = []
    for d in _defaults():
        if d.get("when") and d["when"] not in codes:
            continue
        j = db.scalar(select(Jurisdiction).where(Jurisdiction.code == d["jurisdiction"]))
        match = j and db.scalar(select(Regulation).where(
            Regulation.jurisdiction_id == j.id, Regulation.short_name.startswith(d["starts_with"], autoescape=True),
            Regulation.superseded_by_id.is_(None), Regulation.retired_in_version_id.is_(None),
        ).limit(1))
        if match:
            defaults[match.id] = d
            if match.jurisdiction_id not in juris:  # a default from outside the client's sites (NIST for a Berlin-only client)
                regs.append(match)
                juris[j.id] = j
                sites_by_j[j.id] = []
        else:
            out.append(Suggestion(None, d.get("label", d["starts_with"]), d["jurisdiction"], j.name if j else d["jurisdiction"], d.get("feature", "government_other"), d["reason"], d["source"], True))

    for r in regs:
        j = juris[r.jurisdiction_id]
        sites = ", ".join(dict.fromkeys(sites_by_j[j.id]))
        if r.id in defaults:
            d = defaults[r.id]
            out.append(Suggestion(r.id, r.short_name, j.code, j.name, r.feature, d["reason"], d["source"], True))
        elif r.feature in features:
            out.append(Suggestion(r.id, r.short_name, j.code, j.name, r.feature, f"{sites}: {FEATURE_LABELS[r.feature].lower()} matches the client's AI use", "auto", True))
        else:
            out.append(Suggestion(r.id, r.short_name, j.code, j.name, r.feature, f"{sites}: include if the client uses AI for {FEATURE_LABELS[r.feature].lower()}", "auto", False))

    level = {j.code: LEVEL_ORDER.get(j.level, 9) for j in juris.values()}
    out.sort(key=lambda s: (not s.prechecked, s.source == "futran_default", level.get(s.jurisdiction_code, 9), s.jurisdiction_name, s.feature, s.label))
    return out
