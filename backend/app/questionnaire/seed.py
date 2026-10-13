import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.questionnaire.models import ChecklistItem, Question, TemplateVersion
from app.reference.jurisdictions import SEEDS


def load_question_bank(db: Session) -> TemplateVersion:
    """Seed Template v1.0 + Addendum 5.1a into the question bank. Idempotent."""
    data = yaml.safe_load((SEEDS / "question_bank.yaml").read_text())
    t = data["template"]
    tv = db.scalar(select(TemplateVersion).where(TemplateVersion.name == t["name"], TemplateVersion.version == t["version"]))
    if tv is not None:
        return tv
    tv = TemplateVersion(name=t["name"], version=t["version"], addenda=t["addenda"], effective_date=t.get("effective_date"), status="active")
    db.add(tv)
    db.flush()
    option_sets = data["option_sets"]
    order = 0
    for sec in data["sections"]:
        for q in sec["questions"]:
            order += 1
            opts = q.get("options") or (option_sets[q["option_set"]] if q.get("option_set") else None)
            db.add(Question(
                template_version_id=tv.id,
                code=q["code"],
                section=sec["code"].split(".")[0],
                sub_section=sec["code"],
                section_title=sec["title"],
                section_note=sec.get("note"),
                scope=sec["scope"],
                label=q["label"],
                help_text=q.get("help"),
                type=q["type"],
                options=opts,
                detail_label=q.get("detail_label"),
                required=bool(q.get("required", False)),
                default_respondent=q.get("respondent", "client"),
                applicability_rule=q.get("applies"),
                section_rule=sec.get("applies"),
                finding_rule=q.get("finding"),
                evidence_required=bool(q.get("evidence", False)),
                scoring_map=q.get("scoring"),
                build_types=q.get("build_types", sec.get("build_types")),
                light=bool(sec.get("light", False)),
                order=order,
            ))
    checks = yaml.safe_load((SEEDS / "checklists.yaml").read_text())
    order = 0
    for cl in checks["checklists"]:
        for item in cl["items"]:
            order += 1
            db.add(ChecklistItem(
                template_version_id=tv.id,
                section=cl["section"],
                section_title=cl["title"],
                code=item["code"],
                text=item["text"],
                scope=cl["scope"],
                maturity_domain=item["domain"],
                applicability_rule=item.get("applies"),
                build_types=item.get("build_types", cl.get("build_types")),
                pending_review=bool(item.get("pending_review", False)),
                order=order,
            ))
    db.flush()
    return tv


def active_template_version(db: Session) -> TemplateVersion | None:
    return db.scalar(select(TemplateVersion).where(TemplateVersion.status == "active").order_by(TemplateVersion.created_at.desc()))
