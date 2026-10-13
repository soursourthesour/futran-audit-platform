import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.reference.jurisdictions import SEEDS
from app.reference.models import DocumentCatalogItem, GovernanceCatalogItem, RiskMethodology


def load_catalogs(db: Session) -> str:
    gov = yaml.safe_load((SEEDS / "governance_catalog.yaml").read_text())
    have = set(db.scalars(select(GovernanceCatalogItem.code)))
    n = 0
    for kind, key in (("document", "documents"), ("security_document", "security_documents"), ("role", "roles")):
        for i, item in enumerate(gov[key]):
            if item["code"] in have:
                continue
            db.add(GovernanceCatalogItem(kind=kind, code=item["code"], title=item["title"], description=item.get("description"), control_refs=item.get("control_refs", []), conditional=item.get("conditional"), optional=item.get("optional", False), committee=item.get("committee", False), order=i))
            n += 1
    docs = yaml.safe_load((SEEDS / "document_catalog.yaml").read_text())
    have = set(db.scalars(select(DocumentCatalogItem.code)))
    for i, item in enumerate(docs["items"]):
        if item["code"] in have:
            continue
        db.add(DocumentCatalogItem(category=item["category"], category_title=docs["categories"][item["category"]], code=item["code"], title=item["title"], description=item.get("description"), per_system=item.get("per_system", False), condition=item.get("condition"), template_section=item.get("section"), order=i))
        n += 1
    rm = yaml.safe_load((SEEDS / "risk_methodology_v1.yaml").read_text())
    if not db.scalar(select(RiskMethodology).where(RiskMethodology.version == rm["version"])):
        db.add(RiskMethodology(
            version=rm["version"], effective_date=str(rm["effective_date"]), factor_weights=rm["factors"],
            domain_weights_by_build_type=rm["domain_weights_by_build_type"], bands=rm["bands"], knockout_rules=rm["knockouts"],
            config={k: rm[k] for k in ("domains", "build_type_weights", "light_domains", "proposed_score_bands", "override_rationale_threshold", "max_control_reduction", "eu_ai_act")},
        ))
        n += 1
    db.flush()
    return f"{n} catalog entries added"


def security_scope_note() -> str:
    return yaml.safe_load((SEEDS / "governance_catalog.yaml").read_text())["security_scope_note"]
