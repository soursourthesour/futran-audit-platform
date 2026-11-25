"""The register list and the AI systems grid read each system's data, actions, law links and latest bias test for all
systems at once (load test bottleneck 8: about 15 queries per system). The rows are the same as one at a time."""
from datetime import date

from sqlalchemy import event, select

from app.register import service as svc
from app.register.models import BiasTest, RegisterSystem, RegisterSystemAction, RegisterSystemData
from app.register.serialize import system_out
from tests.register.conftest import new_system


def _detail(db, reg):
    for i, s in enumerate(db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == reg.org.id))):
        db.add(RegisterSystemData(organization_id=reg.org.id, register_system_id=s.id, data_categories=["hr"], data_subjects=["staff"], consent_basis="consent"))
        db.add(RegisterSystemAction(organization_id=reg.org.id, register_system_id=s.id, action_code="other", description=f"Action {i}"))
        db.add(BiasTest(organization_id=reg.org.id, register_system_id=s.id, tested_on=date(2026, 1, 1 + i), tester_type="internal", result="passed"))
        db.add(BiasTest(organization_id=reg.org.id, register_system_id=s.id, tested_on=date(2026, 6, 1 + i), tester_type="internal", result="flagged"))
    db.commit()


def test_register_rows_are_the_same_with_the_grid_prefetch_and_need_fewer_queries(client, db, engine, reg):
    reg.as_(reg.caico)
    for i in range(6):
        new_system(client, name=f"System {i}", decision_impact="consequential", company_wide=True)
    _detail(db, reg)
    db.expire_all()
    seen = []

    def on(*_):
        seen.append(1)

    event.listen(engine, "before_cursor_execute", on)
    rows = client.get("/api/v1/register").json()["systems"]
    with_prefetch = len(seen)
    event.remove(engine, "before_cursor_execute", on)
    one_by_one = {s.id: system_out(db, s, None) for s in db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == reg.org.id))}
    assert len(rows) == 6
    for r in rows:
        mine = one_by_one[r["id"]]
        for key in ("data", "actions", "laws", "bias", "consent", "gate", "roles"):
            assert r[key] == mine[key], key
        assert r["bias"]["result"] == "flagged" and r["actions"][0]["description"].startswith("Action")
    seen.clear()
    event.listen(engine, "before_cursor_execute", on)
    for s in db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == reg.org.id)):
        system_out(db, s, None)
    without = len(seen)
    event.remove(engine, "before_cursor_execute", on)
    db.expire_all()
    seen.clear()
    systems = list(db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == reg.org.id)))
    event.listen(engine, "before_cursor_execute", on)
    with svc.prefetched(db, systems):
        for s in systems:
            system_out(db, s, None)
    prefetched = len(seen)
    event.remove(engine, "before_cursor_execute", on)
    assert prefetched <= without - 3 * 6, (prefetched, without)
    assert svc.PREFETCH_KEY not in db.info
    assert with_prefetch


def test_the_ai_systems_grid_still_lists_register_systems(client, db, reg):
    reg.as_(reg.caico)
    new_system(client, name="Chat helper", company_wide=True)
    _detail(db, reg)
    rows = client.get("/api/v1/ai-systems").json()
    items = rows["rows"] if isinstance(rows, dict) and "rows" in rows else rows
    assert any(x.get("name") == "Chat helper" and x["system"]["bias"]["result"] == "flagged" for x in items)
