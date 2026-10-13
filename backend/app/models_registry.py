"""Import every domain's models so `Base.metadata` is complete (Alembic, tests)."""
import importlib

DOMAINS_WITH_MODELS: list[str] = []

for _mod in DOMAINS_WITH_MODELS:
    importlib.import_module(f"app.{_mod}.models")
