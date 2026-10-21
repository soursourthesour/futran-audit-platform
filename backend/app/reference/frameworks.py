import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.reference.jurisdictions import SEEDS
from app.reference.models import Framework, FrameworkControl


def load_frameworks(db: Session) -> str:
    data = yaml.safe_load((SEEDS / "frameworks.yaml").read_text())
    added = 0
    for fw in data["frameworks"]:
        f = db.scalar(select(Framework).where(Framework.code == fw["code"]))
        if f is None:
            f = Framework(code=fw["code"], name=fw["name"])
            db.add(f)
            db.flush()
        have = set(db.scalars(select(FrameworkControl.code).where(FrameworkControl.framework_id == f.id)))
        for c in fw["controls"]:
            if c["code"] not in have:
                db.add(FrameworkControl(framework_id=f.id, code=c["code"], title=c["title"]))
                added += 1
    db.flush()
    return f"{added} controls added"


# Short names used in citations; the catalog keeps the full names.
SHORT_NAMES = {"OECD": "OECD AI Principles", "NIST_AI_RMF": "NIST AI RMF", "EU_AI_ACT": "EU AI Act", "ISO_42001": "ISO/IEC 42001", "GDPR": "GDPR",
               "NYC_LL144": "NYC Local Law 144", "IL_AIVIA": "Illinois AI Video Interview Act", "IL_HRA": "Illinois Human Rights Act"}
CITATION_NAMES = {"NIST_AI_RMF": "NIST AI RMF 1.0", "ISO_42001": "ISO/IEC 42001:2023"}


def control_label(db: Session, ref: str) -> str:
    """'NIST_AI_RMF MEASURE 2.11' -> 'NIST AI RMF MEASURE 2.11'."""
    fw, _, code = ref.partition(" ")
    name = "OECD" if fw == "OECD" else SHORT_NAMES.get(fw, fw)
    return f"{name} {code}".strip()


def control_citation(db: Session, ref: str) -> str:
    """A reader's citation: 'NIST AI RMF 1.0, MEASURE 2.11: Fairness and bias ...'. A reference outside the catalog is
    shown as written, with the framework's readable name."""
    fw, _, code = ref.partition(" ")
    title = db.scalar(select(FrameworkControl.title).join(Framework, Framework.id == FrameworkControl.framework_id).where(Framework.code == fw, FrameworkControl.code == code))
    name = CITATION_NAMES.get(fw, SHORT_NAMES.get(fw, fw))
    if title is None:
        return control_label(db, ref)
    if fw == "ISO_42001" and code.startswith("A."):
        return f"{name}, Annex A control {code}: {title}"
    if fw == "ISO_42001":
        return f"{name}, clause {code}: {title}"
    if fw in ("GDPR", "EU_AI_ACT", "OECD"):
        return f"{name} {code}: {title}"
    return f"{name}, {code}: {title}"
