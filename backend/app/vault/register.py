"""Wires the vault into G-01 usage: legal holds are billed per matter (M-06e). Storage (`vault_gb`) is already read from
`vault.service.storage_used_gb` by app.commercial.plans."""
from app.commercial import plans


def _legal_holds(db, org_id, on) -> float:
    from app.vault.service import active_holds

    return active_holds(db, org_id, on)


plans.MEASURES.setdefault("legal_holds", _legal_holds)
