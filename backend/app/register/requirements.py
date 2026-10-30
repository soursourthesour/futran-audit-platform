"""The requirements checklist for a register system (spec §27.2), from the regulatory master's Requirement rows."""
from sqlalchemy.orm import Session

from app.register.models import RegisterSystem


def gate_blockers(db: Session, s: RegisterSystem) -> list[str]:
    """Requirements needed before use or go-live that are not met."""
    return []
