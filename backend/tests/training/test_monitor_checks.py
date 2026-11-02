"""Monitoring checks registered by WS-I (wave 3 plan): "Training below target" and "Policy past review date"."""
from datetime import date, timedelta

from app.monitoring.registry import CHECKS, load_checks
from app.policies.models import PolicyDocument
from app.training.models import TrainingAssignment, TrainingCampaign, TrainingProgram
from app.training.service import ensure_modules


def _check(code):
    load_checks()
    return CHECKS[code]


def test_both_checks_are_registered():
    load_checks()
    assert {"training_below_target", "policy_past_review_date"} <= set(CHECKS)
    assert CHECKS["training_below_target"].applies_to == "department" and CHECKS["policy_past_review_date"].applies_to == "policy"


def test_training_not_started_then_attention_then_failed(db, world):
    fn = _check("training_below_target").fn
    org = world["org"]
    [o] = fn(db, org)
    assert o.status == "not_started"
    mod = ensure_modules(db)["shadow_ai"]
    c = TrainingCampaign(organization_id=org.id, module_id=mod.id, module_code=mod.code, audience={})
    db.add(c)
    db.flush()
    for i, (dept, done) in enumerate([(world["fin"], True), (world["fin"], False), (world["hr"], True), (world["hr"], True)]):
        db.add(TrainingAssignment(organization_id=org.id, campaign_id=c.id, module_id=mod.id, module_code=mod.code, email=f"p{i}@abc.test", department_id=dept.id,
                                  status="completed" if done else "assigned", answers={}))
    db.add(TrainingProgram(organization_id=org.id, target_pct=80, target_date=date.today() + timedelta(days=10)))
    db.flush()
    out = {o.object_label: o for o in fn(db, org)}
    assert out["Finance"].status == "attention" and "50%" in out["Finance"].detail and out["Finance"].action == "send_reminder"
    assert out["HR"].status == "healthy"
    db.query(TrainingProgram).one().target_date = date.today() - timedelta(days=1)
    db.flush()
    assert {o.object_label: o.status for o in fn(db, org)}["Finance"] == "failed"
    assert fn(db, world["other"])[0].status == "not_started"  # another client's data is never counted


def test_policy_past_review_date(db, world):
    fn = _check("policy_past_review_date").fn
    org = world["org"]
    assert fn(db, org) == []
    from app.policies.service import ensure_templates

    t = ensure_templates(db)["acceptable_use"]
    for title, due in (("Old policy", date.today() - timedelta(days=3)), ("Due soon", date.today() + timedelta(days=20)), ("Fine", date.today() + timedelta(days=200))):
        db.add(PolicyDocument(organization_id=org.id, template_id=t.id, template_code=t.code, template_version=t.version, title=title, status="published", review_due=due,
                              answers={}, blocks=[]))
    db.add(PolicyDocument(organization_id=org.id, template_id=t.id, template_code=t.code, template_version=t.version, title="Draft", status="draft",
                          review_due=date.today() - timedelta(days=30), answers={}, blocks=[]))
    db.flush()
    out = {o.object_label: o for o in fn(db, org)}
    assert set(out) == {"Old policy", "Due soon", "Fine"}
    assert out["Old policy"].status == "failed" and out["Old policy"].action == "open" and out["Old policy"].action_link.startswith("/policies/")
    assert out["Due soon"].status == "attention" and out["Fine"].status == "healthy"
