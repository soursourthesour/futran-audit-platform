import pytest

from tests.policies.conftest import world  # noqa: F401


@pytest.fixture
def literacy_owner(db, world):
    """Tom (a Contributor) holds the company-wide AI literacy and training owner role (§24.1 row 7)."""
    from app.regmaster.models import RoleCatalog
    from app.register.models import GovernanceRoleAssignment

    role = db.query(RoleCatalog).filter_by(code="ai_literacy_owner").one_or_none()
    if role is None:
        role = RoleCatalog(code="ai_literacy_owner", number=7, name="AI literacy and training owner", level="company", default_stage="go_live", active=True)
        db.add(role)
        db.flush()
    db.add(GovernanceRoleAssignment(organization_id=world["org"].id, role_id=role.id, status="assigned", user_id=world["contrib"].id))
    db.commit()
    return world["contrib"]
