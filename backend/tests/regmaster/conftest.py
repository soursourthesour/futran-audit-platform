import pytest

from tests.initiation.conftest import APPROVAL, live, people, submitted  # noqa: F401  (shared wizard fixtures)


@pytest.fixture
def seeded(db, people):
    from app.regmaster.seed import seed_regmaster

    seed_regmaster(db)
    db.commit()
    return people
