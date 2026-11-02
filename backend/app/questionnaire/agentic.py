"""The "Agentic AI" question set (spec §21 F14, §18.4), added to every active template version that lacks it.

The question bank loader returns early when a template version already exists, so a new section would never reach a
database loaded before it. `ensure_agentic_questions` adds the missing questions (matched by code) and changes nothing
else. It runs from the question bank loader and at start-up.
"""
import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.questionnaire.models import Question, TemplateVersion
from app.reference.jurisdictions import SEEDS

ORDER_BASE = 9000  # after the template's own sections


def ensure_agentic_questions(db: Session) -> int:
    data = yaml.safe_load((SEEDS / "question_bank_agentic.yaml").read_text())
    bank = yaml.safe_load((SEEDS / "question_bank.yaml").read_text())
    option_sets = bank["option_sets"]
    sec = data["section"]
    added = 0
    for tv in db.scalars(select(TemplateVersion).where(TemplateVersion.status == "active")):
        have = set(db.scalars(select(Question.code).where(Question.template_version_id == tv.id, Question.sub_section == sec["code"])))
        top = max(db.scalar(select(func.max(Question.order)).where(Question.template_version_id == tv.id)) or 0, ORDER_BASE)
        for i, q in enumerate(data["questions"]):
            if q["code"] in have:
                continue
            db.add(Question(template_version_id=tv.id, code=q["code"], section=sec["code"], sub_section=sec["code"], section_title=sec["title"], section_note=sec.get("note"),
                            scope=sec["scope"], label=q["label"], help_text=q.get("help"), type=q["type"],
                            options=q.get("options") or (option_sets[q["option_set"]] if q.get("option_set") else None), detail_label=q.get("detail_label"), required=False,
                            default_respondent=q.get("respondent", "client"), applicability_rule=q.get("applies"), section_rule=sec.get("applies"), finding_rule=q.get("finding"),
                            evidence_required=bool(q.get("evidence", False)), scoring_map=None, build_types=None, light=False, order=top + i + 1))
            added += 1
    db.flush()
    return added
