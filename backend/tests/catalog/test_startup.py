"""The starter price list loads on an empty database: from seed-reference and on start-up (run.bat only migrates)."""
from app.catalog.models import CatalogItem


def test_reference_loader_seeds_the_price_list_once(db, futran):
    from app.reference import LOADERS

    loader = dict(LOADERS)["Master price list starter items"]
    assert "13 starter items" in loader(db)
    assert loader(db) == "already loaded"


def test_app_start_seeds_an_empty_price_list(settings, engine):
    from sqlalchemy.orm import sessionmaker

    from app.main import create_app

    create_app(settings.model_copy(update={"seed_on_start": True}), engine=engine)
    s = sessionmaker(bind=engine)()
    assert s.query(CatalogItem).count() == 13
    s.close()
