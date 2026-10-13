from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.main import create_app
from app.policy.authorize import get_scoped
from app.tenancy.models import Department
from tests.factories import login_as, make_department, make_org, make_user


def test_cross_tenant_id_returns_404(settings, engine, db):
    app = create_app(settings, engine=engine)
    r = APIRouter()

    @r.get("/api/v1/_test/departments/{dept_id}")
    def get_dept(dept_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
        d = get_scoped(db, actor, Department, dept_id)
        return {"name": d.name}

    app.router.routes.insert(0, r.routes[0])
    a = make_org(db, type="client", name="ABC Corp")
    b = make_org(db, type="client", name="BCD Inc")
    dept = make_department(db, a, name="Human Resources")
    ua = make_user(db, a, roles=["caico"], name="A User", email="a@abc.test")
    ub = make_user(db, b, roles=["caico"], name="B User", email="b@bcd.test")
    db.commit()
    with TestClient(app) as c:
        login_as(c, db, ub)
        assert c.get(f"/api/v1/_test/departments/{dept.id}").status_code == 404
        login_as(c, db, ua)
        assert c.get(f"/api/v1/_test/departments/{dept.id}").json() == {"name": "Human Resources"}
