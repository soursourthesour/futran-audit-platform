"""AI literacy training (spec §21 F12, screen 33): assign by department, role or email group; track completion and quiz
score; reminders; certificates; completion by department against a target; the employee player and its token link."""
import re
from datetime import date, timedelta

from sqlalchemy import select

from app.mail.models import MailSend, OutboxMessage
from app.training.models import TrainingAssignment
from tests.factories import login_as

API = "/api/v1"
DUE = (date.today() + timedelta(days=30)).isoformat()


def _assign(client, body):
    r = client.post(f"{API}/training/assign", json={"due_date": DUE, "reminder_days": [3, 7]} | body)
    assert r.status_code == 200, r.text
    return r.json()


def test_overview_lists_five_modules_and_the_target(client, db, world):
    login_as(client, db, world["caico"])
    r = client.get(f"{API}/training")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["modules"]) == 5 and body["program"]["target_pct"] == 80
    assert body["can"]["manage"] is True
    assert client.put(f"{API}/training/program", json={"target_pct": 90, "target_date": DUE}).json()["target_pct"] == 90
    assert client.put(f"{API}/training/program", json={"target_pct": 140}).status_code == 422


def test_permissions(client, db, world):
    login_as(client, db, world["contrib"])
    assert client.get(f"{API}/training").status_code == 403
    assert client.get(f"{API}/my-training").status_code == 200
    login_as(client, db, world["chief"])
    assert client.get(f"{API}/training").status_code == 404


def test_literacy_owner_can_run_training_without_a_platform_role(client, db, world, literacy_owner):
    login_as(client, db, literacy_owner)
    body = client.get(f"{API}/training").json()
    assert body["can"]["manage"] is True and body["is_literacy_owner"] is True


def test_assign_by_department_emails_personal_links(client, db, world):
    login_as(client, db, world["caico"])
    pre = client.post(f"{API}/training/assign/preview", json={"module_codes": ["shadow_ai"], "audience": {"kind": "departments", "ids": [world["fin"].id]}})
    assert pre.status_code == 200 and pre.json()["total"] == 2
    out = _assign(client, {"module_codes": ["shadow_ai"], "audience": {"kind": "departments", "ids": [world["fin"].id]}})
    assert out["assigned"] == 2
    rows = list(db.scalars(select(TrainingAssignment)))
    assert {r.email for r in rows} == {"aisha@abc.test", "peter@abc.test"} and all(r.department_id == world["fin"].id for r in rows)
    s = db.scalar(select(MailSend).where(MailSend.campaign_type == "training"))
    assert s.recipient_count == 2 and s.mode == "personal"
    # assigning again does not duplicate open assignments
    assert _assign(client, {"module_codes": ["shadow_ai"], "audience": {"kind": "departments", "ids": [world["fin"].id]}})["assigned"] == 0


def test_assign_by_role_and_by_group(client, db, world):
    from app.mail.groups import create_group

    login_as(client, db, world["caico"])
    out = _assign(client, {"module_codes": ["prompt_hygiene"], "audience": {"kind": "role", "role": "dpo"}})
    assert out["assigned"] == 1
    g = create_group(db, world["caico"], world["org"].id, name="HR reviewers", source="manual")
    from app.mail.groups import add_member
    from app.mail.models import DirectoryPerson

    add_member(db, world["caico"], g, person_id=db.scalar(select(DirectoryPerson.id).where(DirectoryPerson.email == "hannah@abc.test")))
    db.commit()
    out = _assign(client, {"module_codes": ["bias_basics_hr", "human_oversight"], "audience": {"kind": "groups", "ids": [g.id]}})
    assert out["assigned"] == 2


def _token(db, email):
    msgs = [m for m in db.scalars(select(OutboxMessage).order_by(OutboxMessage.created_at)) if email in (m.to or []) and m.template_key == "training_ai_literacy"]
    return re.search(r"/m/([A-Za-z0-9_\-]+)", msgs[-1].body_text).group(1)


def _answers(module_code):
    from app.training import modules as M

    return {q["id"]: q["answer"] for q in M.library()[module_code]["quiz"]}


def test_token_link_player_quiz_certificate_and_completion_by_department(client, db, world):
    login_as(client, db, world["caico"])
    _assign(client, {"module_codes": ["shadow_ai"], "audience": {"kind": "departments", "ids": [world["fin"].id, world["hr"].id]}})
    token = _token(db, "aisha@abc.test")
    client.cookies.clear()
    landing = client.get(f"{API}/public/m/{token}").json()
    assert landing["kind"] == "training" and landing["module"]["title"] == "Shadow AI and data leakage"
    base = f"{API}/public/training/{token}"
    v = client.get(base).json()
    assert v["status"] == "assigned" and "answer" not in str(v["module"]["quiz"])
    answers = _answers("shadow_ai")
    first = next(iter(answers))
    r = client.post(f"{base}/check", json={"question_id": first, "option_id": "zz"})
    assert r.status_code == 422
    wrong = next(o["id"] for q in v["module"]["quiz"] if q["id"] == first for o in q["options"] if o["id"] != answers[first])
    r = client.post(f"{base}/check", json={"question_id": first, "option_id": wrong}).json()
    assert r["correct"] is False and r["explanation"]
    for qid, opt in list(answers.items())[1:]:
        assert client.post(f"{base}/check", json={"question_id": qid, "option_id": opt}).json()["correct"] is True
    fin = client.post(f"{base}/finish").json()
    n = len(answers)
    if round(100 * (n - 1) / n) < 80:
        assert fin["passed"] is False and fin["attempts"] == 1
        for qid, opt in answers.items():
            client.post(f"{base}/check", json={"question_id": qid, "option_id": opt})
        fin = client.post(f"{base}/finish").json()
    assert fin["passed"] is True and fin["score"] >= 80 and fin["status"] == "completed"
    pdf = client.get(f"{base}/certificate")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    login_as(client, db, world["caico"])
    ov = client.get(f"{API}/training").json()
    fin_row = next(d for d in ov["departments"] if d["name"] == "Finance")
    assert fin_row["assigned"] == 2 and fin_row["completed"] == 1 and fin_row["pct"] == 50 and fin_row["below_target"] is True
    mod = next(m for m in ov["modules"] if m["code"] == "shadow_ai")
    assert mod["completed"] == 1 and mod["assigned"] == 4  # Hannah and Tom (HR), Aisha and Peter (Finance)


def test_signed_in_learner_and_named_user_feed(client, db, world):
    from app.inventory.models import NamedUser, UseCase

    uc = UseCase(organization_id=world["org"].id, engagement_id=world["engagement"].id, name="Résumé screening", department_id=world["hr"].id)
    db.add(uc)
    db.flush()
    nu = NamedUser(organization_id=world["org"].id, use_case_id=uc.id, person_name="Tom Reyes", email="tom@abc.test")
    db.add(nu)
    db.commit()
    login_as(client, db, world["caico"])
    _assign(client, {"module_codes": ["human_oversight"], "audience": {"kind": "role", "role": "contributor"}})
    login_as(client, db, world["contrib"])
    mine = client.get(f"{API}/my-training").json()["assignments"]
    assert [a["module"]["code"] for a in mine] == ["human_oversight"]
    aid = mine[0]["id"]
    for qid, opt in _answers("human_oversight").items():
        client.post(f"{API}/learn/{aid}/check", json={"question_id": qid, "option_id": opt})
    assert client.post(f"{API}/learn/{aid}/finish").json()["passed"] is True
    db.expire_all()
    assert db.get(NamedUser, nu.id).training_complete is True
    login_as(client, db, world["dpo"])
    assert client.get(f"{API}/learn/{aid}").status_code == 404  # someone else's assignment


def test_reminders_go_to_people_who_have_not_finished(client, db, world):
    login_as(client, db, world["caico"])
    _assign(client, {"module_codes": ["shadow_ai"], "audience": {"kind": "departments", "ids": [world["fin"].id]}})
    r = client.post(f"{API}/training/reminders", json={})
    assert r.status_code == 200 and r.json()["reminded"] == 2
    rem = db.scalar(select(MailSend).where(MailSend.kind == "reminder"))
    assert rem is not None and rem.campaign_type == "training"


def test_scorm_export_and_evidence_for_the_literacy_owner_role(client, db, world, literacy_owner):
    login_as(client, db, world["caico"])
    r = client.get(f"{API}/training/modules/acceptable_use/scorm")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    r = client.post(f"{API}/training/evidence")
    assert r.status_code == 200, r.text
    from app.register.models import GovernanceRoleAssignment

    db.expire_all()
    a = db.scalar(select(GovernanceRoleAssignment).where(GovernanceRoleAssignment.user_id == literacy_owner.id))
    assert r.json()["file_id"] in a.evidence_ids
