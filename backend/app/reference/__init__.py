"""Reference-data loaders, run in order by `python -m app.cli seed-reference`. Each returns a short summary."""
from collections.abc import Callable

from sqlalchemy.orm import Session


def _iso(db: Session) -> str:
    from app.reference.jurisdictions import seed_iso

    return seed_iso(db)


def _law_matrix(db: Session) -> str:
    """Import the bundled law matrix once, on a fresh install. Later updates go through Admin > Reference data."""
    from sqlalchemy import select

    from app.laws.importer import SEEDS, parse_workbook
    from app.laws.models import MatrixVersion
    from app.laws.publish import publish
    from app.tenancy.models import Organization

    if db.scalar(select(MatrixVersion.id).limit(1)):
        return "already loaded"
    futran = db.scalar(select(Organization).where(Organization.type == "futran", Organization.is_internal.is_(False)))
    v = publish(db, parse_workbook(SEEDS / "law_matrix.xlsx"), None, {}, organization_id=futran.id if futran else None)
    return f"published {v.summary['created']} laws (status {v.status_date})"


def _frameworks(db: Session) -> str:
    from app.reference.frameworks import load_frameworks

    return load_frameworks(db)


def _catalogs(db: Session) -> str:
    from app.reference.catalogs import load_catalogs

    return load_catalogs(db)


def _templates(db: Session) -> str:
    from app.reference.templates import load_templates

    return load_templates(db)


def _question_bank(db: Session) -> str:
    from app.questionnaire.seed import load_question_bank

    tv = load_question_bank(db)
    return f"{tv.name} {tv.version} (addenda {', '.join(tv.addenda)})"


def _regmaster(db: Session) -> str:
    from app.regmaster.seed import seed_regmaster

    return seed_regmaster(db)


LOADERS: list[tuple[str, Callable[[Session], str]]] = [
    ("Jurisdictions (ISO 3166, EU, built-in cities)", _iso),
    ("Law matrix", _law_matrix),
    ("Frameworks", _frameworks),
    ("Governance and document catalogs, risk methodology", _catalogs),
    ("Document templates", _templates),
    ("Question bank", _question_bank),
    ("Regulatory master (roles, sources, cited requirements)", _regmaster),
]


def _court_sources(db: Session) -> str:
    from app.litigation.seed import seed_court_sources

    return f"{seed_court_sources(db)} court sources added to the allowlist"


LOADERS.append(("Litigation tracker court sources", _court_sources))  # v0.6 WS-D
