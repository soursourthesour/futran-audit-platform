"""Every value `seed-reference` loads fits its column. SQLite ignores VARCHAR lengths, so a seed text longer than its
column only fails on PostgreSQL, the hosted install (BUG-K08: the EU AI Act effective text in law_versions)."""
import sqlalchemy as sa


def test_every_seeded_string_fits_its_column(db):
    from app.cli import _futran_org
    from app.core.models import Base
    from app.reference import LOADERS

    _futran_org(db)
    for _, loader in LOADERS:
        loader(db)
    db.flush()
    too_long = []
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            n = getattr(col.type, "length", None)
            if not isinstance(col.type, sa.String) or not n:
                continue
            longest = db.execute(sa.select(sa.func.max(sa.func.length(col)))).scalar()
            if longest and longest > n:
                too_long.append(f"{table.name}.{col.name}: {longest} > {n}")
    assert too_long == []
