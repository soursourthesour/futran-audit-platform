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


def control_label(db: Session, ref: str) -> str:
    """'NIST_AI_RMF MEASURE 2.11' -> 'NIST AI RMF MEASURE 2.11'."""
    fw, _, code = ref.partition(" ")
    names = {"OECD": "OECD", "NIST_AI_RMF": "NIST AI RMF", "EU_AI_ACT": "EU AI Act", "ISO_42001": "ISO/IEC 42001"}
    return f"{names.get(fw, fw)} {code}".strip()
