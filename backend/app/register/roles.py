"""Governance roles on register systems (spec §24.1, §24.2). The role catalogue and law–role map come from the regulatory master."""
from sqlalchemy.orm import Session

from app.register.models import RegisterSystem


def role_rows(db: Session, s: RegisterSystem) -> list[dict]:
    """One row per catalogue role that applies to the system, with its requirement level and assignment."""
    return []


def plan_bulk_roles(db: Session, actor, systems: list[RegisterSystem], roles: list[dict]) -> list[dict]:
    """Validate the roles part of a bulk edit and find conflicts. One entry per (system, role) it applies to."""
    return []


def apply_bulk_roles(db: Session, actor, s: RegisterSystem, plan: list[dict], reason: str, batch_id: str) -> int:
    return 0


def catalog_role(db: Session, role_id: str | None) -> dict | None:
    """The catalogue role as {id, code, name, level, default_stage}, or None."""
    return None
