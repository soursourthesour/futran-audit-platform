"""Reference-data loaders, run in order by `python -m app.cli seed-reference`. Each returns a short summary."""
from collections.abc import Callable

from sqlalchemy.orm import Session


def _iso(db: Session) -> str:
    from app.reference.jurisdictions import seed_iso

    return seed_iso(db)


LOADERS: list[tuple[str, Callable[[Session], str]]] = [
    ("Jurisdictions (ISO 3166, EU, built-in cities)", _iso),
]
