"""G-08 EU AI Act conformity workspace API (spec B8, screen G-08): per-system role and classification with legal
sign-off by the Legal/Compliance Reviewer only, computed articles and deadlines, obligations with evidence, the
Annex IV tracker for providers and the FRIA for deployers where Art. 27 applies."""
import hashlib

from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.euaiact.models import EuAiActRecord
from app.notifications.models import Notification

API = "/api/v1"


def _sys(eu, s, tail=""):
    return f"{API}/eu-ai-act/systems/{s.id}{tail}"


def _classify(eu, s=None, **over):
    body = {"engagement_id": eu.engagement.id, "exposure_basis": "EU customers", "role": "provider", "also_deployer": True, "classification": "high_risk_annex_iii",
            "annex_iii_area": "credit", "reasoning": "Evaluates the creditworthiness of natural persons, so Annex III point 5(b). Built and placed in service under its own name."}
    body.update(over)
    return eu.client.put(_sys(eu, s or eu.credit), json=body)


def test_engagement_workspace_lists_systems_with_exposure_role_classification_and_deadline(eu):
    eu.as_(eu.auditor)
    r = eu.client.get(f"{API}/e/{eu.engagement.id}/eu-ai-act")
    assert r.status_code == 200, r.text
    d = r.json()
    assert "2 Dec 2027" in d["banner"] and "2 Aug 2028" in d["banner"]
    rows = {x["name"]: x for x in d["systems"]}
    assert rows["Credit decision model"]["eu_exposure"] == "Runs in Germany" and rows["Hiring screening"]["eu_exposure"] == "Uses data of people in France"
    assert rows["Member chatbot"]["eu_exposure"] is None and "Other's model" not in rows
    assert d["can_edit"] is True and d["can_sign"] is False
    # a workspace only on engagements of the matching type
    assert eu.client.get(f"{API}/e/{eu.plain.id}/eu-ai-act").status_code == 404

    assert _classify(eu).status_code == 200
    row = next(x for x in eu.client.get(f"{API}/e/{eu.engagement.id}/eu-ai-act").json()["systems"] if x["name"] == "Credit decision model")
    assert row["role_label"] == "Provider (also uses it)" and row["classification_label"].startswith("High-risk · Annex III")
    assert row["deadline"]["label"] == "2 Dec 2027" and row["obligations_total"] >= 14 and row["signoff_label"] == "Not sent"


def test_computed_articles_deadline_annex_iv_and_fria(eu):
    eu.as_(eu.auditor)
    d = _classify(eu).json()
    keys = [o["key"] for o in d["obligations"]]
    assert keys[:3] == ["art4", "art9", "art10"] and "art27" in keys and "art26_1" in keys  # also a deployer of a credit model: FRIA applies
    assert d["deadline"]["date"] == "2027-12-02" and d["fria_required"] is True and len(d["annex_iv"]) == 9
    # Annex I: the other date; no FRIA
    d = _classify(eu, classification="high_risk_annex_i", annex_iii_area=None).json()
    assert d["deadline"]["date"] == "2028-08-02" and d["fria_required"] is False and "art27" not in [o["key"] for o in d["obligations"]]
    # a deployer has no Annex IV tracker
    d = _classify(eu, eu.hiring, role="deployer", also_deployer=False, annex_iii_area="employment").json()
    assert d["annex_iv"] == [] and d["fria_required"] is False and [o["key"] for o in d["obligations"]][:2] == ["art4", "art26_1"]
    # transparency only: in force
    d = _classify(eu, eu.chatbot, role="deployer", also_deployer=False, classification="transparency", annex_iii_area=None).json()
    assert d["deadline"]["label"] == "In force" and [o["key"] for o in d["obligations"]] == ["art4", "art50_3"]
    # validation
    bad = _classify(eu, role="manufacturer")
    assert bad.status_code == 422 and bad.json()["errors"][0]["field"] == "role"
    assert _classify(eu, annex_iii_area=None).status_code == 422  # Annex III needs its area


def test_only_the_legal_reviewer_signs_off_and_who_and_when_are_kept(eu):
    eu.as_(eu.auditor)
    _classify(eu)
    r = eu.client.post(_sys(eu, eu.credit, "/send"), json={})
    assert r.status_code == 200 and r.json()["signoff_status"] == "awaiting_signoff"
    assert eu.db.scalar(select(Notification).where(Notification.user_id == eu.legal.id, Notification.kind == "eu_classification_signoff")) is not None
    for u in (eu.auditor, eu.chief, eu.em, eu.caico):
        eu.as_(u)
        assert eu.client.post(_sys(eu, eu.credit, "/signoff"), json={"approve": True}).status_code in (403, 404), u.name
    eu.as_(eu.legal_outside)  # a reviewer on no engagement for this client
    assert eu.client.post(_sys(eu, eu.credit, "/signoff"), json={"approve": True}).status_code == 404
    eu.as_(eu.legal)
    assert eu.client.put(_sys(eu, eu.credit), json={"role": "deployer"}).status_code == 403  # the reviewer signs, never edits
    r = eu.client.post(_sys(eu, eu.credit, "/signoff"), json={"approve": True, "note": "Agree: Annex III 5(b)."})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["signoff_status"] == "signed_off" and d["signed_off_by"] == "Jordan Ellis" and d["signed_off_at"]
    rec = eu.db.scalar(select(EuAiActRecord).where(EuAiActRecord.register_system_id == eu.credit.id))
    assert rec.signed_off_by == eu.legal.id and rec.signed_snapshot["classification"] == "high_risk_annex_iii"
    assert eu.db.scalar(select(AuditLog).where(AuditLog.action == "euaiact.signoff", AuditLog.object_id == rec.id)) is not None
    assert eu.client.post(_sys(eu, eu.credit, "/signoff"), json={"approve": True}).status_code == 409  # nothing waiting

    # changing the classification afterwards takes the sign-off away
    eu.as_(eu.auditor)
    d = _classify(eu, classification="high_risk_annex_i", annex_iii_area=None).json()
    assert d["signoff_status"] == "draft" and "changed after sign-off" in (d["signoff_note"] or "").lower()
    # the obligations checklist does not
    _classify(eu)
    eu.client.post(_sys(eu, eu.credit, "/send"), json={})
    eu.as_(eu.legal)
    eu.client.post(_sys(eu, eu.credit, "/signoff"), json={"approve": True})
    eu.as_(eu.auditor)
    assert eu.client.put(_sys(eu, eu.credit, "/obligations/art9"), json={"status": "met", "note": "Risk procedure v2"}).json()["signoff_status"] == "signed_off"


def test_returned_classification_and_no_self_signoff(eu):
    from app.tenancy.service import assign_role

    eu.as_(eu.auditor)
    _classify(eu)
    eu.client.post(_sys(eu, eu.credit, "/send"), json={})
    eu.as_(eu.legal)
    r = eu.client.post(_sys(eu, eu.credit, "/signoff"), json={"approve": False, "note": "Check whether the model is a safety component."})
    assert r.status_code == 200 and r.json()["signoff_status"] == "returned"
    assert eu.db.scalar(select(Notification).where(Notification.user_id == eu.auditor.id, Notification.kind == "eu_classification_returned")) is not None
    assert eu.client.post(_sys(eu, eu.credit, "/signoff"), json={"approve": False}).status_code == 409
    # a person who is both auditor and reviewer cannot sign their own classification
    assign_role(eu.db, eu.legal, "auditor")
    eu.db.commit()
    eu.as_(eu.legal)
    assert _classify(eu, reasoning="Revised after review.").status_code == 200
    eu.client.post(_sys(eu, eu.credit, "/send"), json={})
    r = eu.client.post(_sys(eu, eu.credit, "/signoff"), json={"approve": True})
    assert r.status_code == 403 and "own" in r.json()["detail"].lower()


def test_obligations_with_evidence_annex_iv_and_fria(eu):
    eu.as_(eu.auditor)
    _classify(eu)
    r = eu.client.put(_sys(eu, eu.credit, "/obligations/art10"), json={"status": "partly_met", "note": "Bias test 2025"})
    assert r.status_code == 200
    data = b"risk procedure v2"
    r = eu.client.post(_sys(eu, eu.credit, "/obligations/art9/evidence"), files={"file": ("risk-procedure.pdf", data, "application/pdf")})
    assert r.status_code == 200, r.text
    ob = next(o for o in r.json()["obligations"] if o["key"] == "art9")
    assert ob["evidence"][0]["filename"] == "risk-procedure.pdf" and ob["evidence"][0]["sha256"] == hashlib.sha256(data).hexdigest()
    f = eu.client.get(f"{API}/files/{ob['evidence'][0]['id']}")
    assert f.status_code == 200 and f.content == data
    # an obligation that does not apply is refused
    assert eu.client.put(_sys(eu, eu.credit, "/obligations/art23"), json={"status": "met"}).status_code == 404
    assert eu.client.put(_sys(eu, eu.credit, "/obligations/art9"), json={"status": "done"}).status_code == 422
    # Annex IV: 9 sections, counted
    for key in ("general", "elements", "monitoring", "metrics", "risk"):
        assert eu.client.put(_sys(eu, eu.credit, f"/annex-iv/{key}"), json={"status": "done"}).status_code == 200
    d = eu.client.get(_sys(eu, eu.credit)).json()
    assert d["annex_iv_done"] == 5 and next(o for o in d["obligations"] if o["key"] == "art11")["progress"] == "5 of 9 sections"
    # FRIA
    r = eu.client.put(_sys(eu, eu.credit, "/fria"), json={"answers": {"process": "Consumer lending decisions", "persons": "Loan applicants"}, "status": "in_progress"})
    assert r.status_code == 200 and r.json()["fria"]["answers"]["process"] == "Consumer lending decisions" and r.json()["fria"]["status"] == "in_progress"
    _classify(eu, eu.hiring, role="deployer", also_deployer=False, annex_iii_area="employment")
    assert eu.client.put(_sys(eu, eu.hiring, "/fria"), json={"answers": {}, "status": "done"}).status_code == 409
    assert eu.client.put(_sys(eu, eu.hiring, "/annex-iv/general"), json={"status": "done"}).status_code == 409


def test_tenancy_visibility_and_client_view(eu):
    eu.as_(eu.auditor)
    _classify(eu)
    # an auditor on no engagement for the client, and another client's people, see nothing
    eu.as_(eu.outsider)
    assert eu.client.get(_sys(eu, eu.credit)).status_code == 404
    assert eu.client.get(f"{API}/e/{eu.engagement.id}/eu-ai-act").status_code == 404
    eu.as_(eu.other_caico)
    assert eu.client.get(_sys(eu, eu.credit)).status_code == 404
    eu.as_(eu.auditor)
    assert eu.client.get(_sys(eu, eu.foreign)).status_code == 404
    # the client's CAICO: no classification until it is signed off; never edits
    eu.as_(eu.caico)
    d = eu.client.get(_sys(eu, eu.credit)).json()
    assert d["client_view"] is True and d["classification"] is None and d["status_text"].startswith("With the legal reviewer")
    assert "reasoning" not in d and "obligations" not in d
    assert eu.client.put(_sys(eu, eu.credit), json={"role": "deployer"}).status_code == 403
    assert eu.client.get(f"{API}/e/{eu.engagement.id}/eu-ai-act").status_code == 404  # the workspace is Futran's
    eu.as_(eu.client_admin)
    assert eu.client.get(_sys(eu, eu.credit)).status_code == 403
    eu.as_(eu.auditor)
    eu.client.post(_sys(eu, eu.credit, "/send"), json={})
    eu.as_(eu.legal)
    eu.client.post(_sys(eu, eu.credit, "/signoff"), json={"approve": True})
    eu.as_(eu.caico)
    d = eu.client.get(_sys(eu, eu.credit)).json()
    assert d["classification_label"].startswith("High-risk · Annex III") and d["deadline"]["label"] == "2 Dec 2027" and d["signed_off_at"]


def test_client_level_view_for_systems_with_eu_geography(eu):
    eu.as_(eu.auditor)
    r = eu.client.get(f"{API}/clients/{eu.org.id}/eu-ai-act")
    assert r.status_code == 200
    assert [x["name"] for x in r.json()["systems"]] == ["Credit decision model", "Hiring screening"]  # EU geography or a record
    assert eu.client.get(f"{API}/e/{eu.engagement.id}/workspaces").json() == {"copilot": False, "eu_ai_act": True, "eu_systems": 2}
    assert eu.client.get(f"{API}/e/{eu.plain.id}/workspaces").status_code == 404  # not on that engagement's team
    eu.as_(eu.chief)
    assert eu.client.get(f"{API}/e/{eu.plain.id}/workspaces").json() == {"copilot": False, "eu_ai_act": False, "eu_systems": 2}
