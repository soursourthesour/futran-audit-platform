"""Reference-data loaders, run in order by `python -m app.cli seed-reference`. Each returns a short summary."""
from collections.abc import Callable

from sqlalchemy.orm import Session

LOADERS: list[tuple[str, Callable[[Session], str]]] = []
