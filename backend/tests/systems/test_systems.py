from sqlalchemy import select

from app.engagements.models import EngagementTeam
from app.inventory.models import UseCase
from app.systems.models import AISystem, SystemAdditionRequest
from app.systems.service import create_from_use_case, unmapped_tier3
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import inv  # noqa: F401


def _use_case(db, cid, e, hr, name, tier, final=False):
    uc = UseCase(organization_id=cid, engagement_id=e.id, name=name, department_id=hr.id, tool_ids=[], data_categories=["pii"], decision_impact="consequential" if tier == 3 else "informs", proposed_tier=tier, final_tier=tier if final else None, status="dept_approved")
    db.add(uc)
    db.flush()
    return uc


def _systems(db, e):
    return list(db.scalars(select(AISystem).where(AISystem.engagement_id == e.id, AISystem.deleted_at.is_(None)).order_by(AISystem.reference_id)))


def test_wizard_planned_systems_converted(client, db, inv):
    cid, e, *_ = inv
    rows = _systems(db, e)
    assert [(s.reference_id, s.name, s.source, s.assessment_depth, s.status) for s in rows] == [
        ("SYS-001", "HireScore", "wizard", "full", "not_started"),
        ("SYS-002", "Resume parser", "wizard", "full", "not_started"),
    ]
    assert all(s.methodology_version == "1.0" for s in rows)


def test_reference_ids_sequential_per_engagement(client, db, inv, people):
    cid, e, maria, hr, *_ = inv
    a = create_from_use_case(db, people["aud"], e, [_use_case(db, cid, e, hr, "Shortlisting", 3).id], built_by="vendor")
    b = create_from_use_case(db, people["aud"], e, [_use_case(db, cid, e, hr, "Interview notes", 2).id], built_by="in_house")
    assert (a.reference_id, b.reference_id) == ("SYS-003", "SYS-004")
    a.deleted_at = a.created_at  # a removed system keeps its number
    db.flush()
    c = create_from_use_case(db, people["aud"], e, [_use_case(db, cid, e, hr, "Payroll", 2).id], built_by="vendor")
    assert c.reference_id == "SYS-005"


def test_depth_full_for_tier3_light_for_tier2(client, db, inv, people):
    cid, e, maria, hr, *_ = inv
    t3 = _use_case(db, cid, e, hr, "Shortlisting", 3)
    t2 = _use_case(db, cid, e, hr, "Drafting", 2)
    t2_final3 = _use_case(db, cid, e, hr, "Ranking", 2)
    t2_final3.final_tier = 3
    assert create_from_use_case(db, people["aud"], e, [t3.id], built_by="vendor").assessment_depth == "full"
    assert create_from_use_case(db, people["aud"], e, [t2.id], built_by="vendor").assessment_depth == "light"
    assert create_from_use_case(db, people["aud"], e, [t2_final3.id], built_by="vendor").assessment_depth == "full"
    t3_lowered = _use_case(db, cid, e, hr, "Lowered", 3)
    t3_lowered.final_tier = 2  # the final tier wins over the proposed one
    s = create_from_use_case(db, people["aud"], e, [t3_lowered.id], built_by="vendor")
    assert s.assessment_depth == "light" and s.name == "Lowered" and s.department_id == hr.id


def test_unmapped_tier3_listed(client, db, inv, people):
    cid, e, maria, hr, *_ = inv
    t3a = _use_case(db, cid, e, hr, "Shortlisting", 3)
    t3b = _use_case(db, cid, e, hr, "Scoring", 3, final=True)
    _use_case(db, cid, e, hr, "Drafting", 2)
    assert {u.id for u in unmapped_tier3(db, e)} == {t3a.id, t3b.id}
    create_from_use_case(db, people["aud"], e, [t3a.id], built_by="vendor")
    assert [u.id for u in unmapped_tier3(db, e)] == [t3b.id]
    db.commit()
    login_as(client, db, people["aud"])
    r = client.get(f"/api/v1/clients/{cid}/systems").json()
    assert [u["name"] for u in r["unmapped_tier3"]] == ["Scoring"]
    assert {s["reference_id"] for s in r["systems"]} == {"SYS-001", "SYS-002", "SYS-003"}


def test_add_after_initiation_requires_em_approval(client, db, inv, people):
    cid, e, maria, hr, *_ = inv
    t3 = _use_case(db, cid, e, hr, "Shortlisting", 3)
    db.commit()
    login_as(client, db, people["aud"])
    r = client.post(f"/api/v1/clients/{cid}/systems", json={"use_case_ids": [t3.id], "built_by": "vendor", "reason": "Tier 3 use case found in discovery"})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert len(_systems(db, e)) == 2  # nothing added yet
    req = db.scalar(select(SystemAdditionRequest))
    # the requester cannot approve; an auditor has no approval right; the Engagement Manager can
    assert client.post(f"/api/v1/system-requests/{req.id}/decide", json={"approve": True}).status_code == 403
    login_as(client, db, people["em"])
    r = client.post(f"/api/v1/system-requests/{req.id}/decide", json={"approve": True})
    assert r.status_code == 200, r.text
    db.expire_all()
    rows = _systems(db, e)
    assert len(rows) == 3 and rows[-1].use_case_ids == [t3.id] and rows[-1].assessment_depth == "full"
    assert unmapped_tier3(db, e) == []
    assert client.post(f"/api/v1/system-requests/{req.id}/decide", json={"approve": True}).status_code == 409
    # the client cannot add systems
    login_as(client, db, maria)
    assert client.post(f"/api/v1/clients/{cid}/systems", json={"name": "X", "built_by": "vendor"}).status_code == 403


def test_em_who_requested_cannot_approve(client, db, inv, people):
    cid, e, maria, hr, *_ = inv
    em = people["em"]
    em_req = SystemAdditionRequest(organization_id=cid, engagement_id=e.id, requested_by=em.id, payload={"name": "Chatbot", "built_by": "vendor", "use_case_ids": []}, reason="x", status="pending")
    db.add(em_req)
    db.commit()
    login_as(client, db, em)
    assert client.post(f"/api/v1/system-requests/{em_req.id}/decide", json={"approve": True}).status_code == 403
    assert client.post(f"/api/v1/system-requests/{em_req.id}/decide", json={"approve": False, "comment": ""}).status_code == 403


def test_vendor_register_and_system_edit(client, db, inv, people):
    cid, e, maria, hr, *_ = inv
    login_as(client, db, people["aud"])
    v = client.post(f"/api/v1/clients/{cid}/vendors", json={"legal_name": "HireScore Inc.", "capability": "Résumé ranking", "personal_data_processed": True, "baa_dpa_signed": False, "risk_level": "H"})
    assert v.status_code == 200, v.text
    assert client.post(f"/api/v1/clients/{cid}/vendors", json={"legal_name": "hirescore inc."}).status_code == 409
    assert client.post(f"/api/v1/clients/{cid}/vendors", json={"legal_name": "Y", "risk_level": "X"}).status_code == 422
    s = _systems(db, e)[0]
    r = client.patch(f"/api/v1/systems/{s.id}", json={"built_by": "vendor", "vendor_id": v.json()["id"], "version": "4.2", "department_id": hr.id})
    assert r.status_code == 200 and r.json()["vendor"] == "HireScore Inc."
    assert client.patch(f"/api/v1/systems/{s.id}", json={"built_by": "magic"}).status_code == 422
    # a Tier 3 use case mapped to an existing system needs no approval and makes it full depth
    t3 = _use_case(db, cid, e, hr, "Shortlisting", 3)
    db.commit()
    r = client.patch(f"/api/v1/systems/{s.id}", json={"use_case_ids": [t3.id]})
    assert r.status_code == 200 and r.json()["assessment_depth"] == "full"
    db.expire_all()
    assert unmapped_tier3(db, e) == []
    # light cannot be chosen while a Tier 3 use case is mapped
    assert client.patch(f"/api/v1/systems/{s.id}", json={"assessment_depth": "light"}).status_code == 409
    login_as(client, db, people["aud2"])  # not on the team
    assert client.patch(f"/api/v1/systems/{s.id}", json={"version": "5"}).status_code == 404
