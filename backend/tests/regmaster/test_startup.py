"""After `alembic upgrade head` alone (run.bat), the app seeds the regulatory master on its first start."""
from sqlalchemy import func, select

from app.main import create_app
from app.regmaster.models import Requirement, RoleCatalog


def test_first_start_seeds_the_catalogue_and_law_content(matrix, engine, settings):
    db = matrix
    db.commit()
    create_app(settings.model_copy(update={"seed_on_start": True}), engine=engine)
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(RoleCatalog)) == 21
    assert db.scalar(select(func.count()).select_from(Requirement)) >= 50


def test_start_without_seeding_when_switched_off(matrix, engine, settings):
    matrix.commit()
    create_app(settings.model_copy(update={"seed_on_start": False}), engine=engine)
    assert matrix.scalar(select(func.count()).select_from(RoleCatalog)) == 0


def test_start_never_fails_on_an_unmigrated_database(settings):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    bare = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    create_app(settings.model_copy(update={"seed_on_start": True}), engine=bare)
