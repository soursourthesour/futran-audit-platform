"""Trust Center (spec §21 F9, screen 32): the client's editor, CAICO approval and Futran Chief Auditor confirmation
against the signed report, and the public page — published items only, no sign-in, noindex unless opted in, optional NDA
gate for detailed documents, view counts by day."""
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.trust.models import TrustCenterView
from tests.factories import login_as

API = "/api/v1"


def _page(client, slug="abc-corp", **kw):
    r = client.put(f"{API}/trust/page", json={"slug": slug, "title": "How ABC Corp governs its use of AI",
                                              "intro": "We use AI to help our recruiting and customer support teams.", "contact_email": "ai@abccorp.example", "live": True} | kw)
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, **body):
    r = client.post(f"{API}/trust/items", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _publish(client, db, world, item_id):
    login_as(client, db, world["caico"])
    assert client.post(f"{API}/trust/items/{item_id}/approve").status_code == 200
    login_as(client, db, world["chief"])
    r = client.post(f"{API}/trust/items/{item_id}/confirm", json={"note": "Matches section 4 of the signed report."})
    assert r.status_code == 200, r.text
    return r.json()


def test_editor_permissions(client, db, world):
    login_as(client, db, world["admin"])
    assert client.get(f"{API}/trust").status_code == 200
    assert client.put(f"{API}/trust/page", json={"slug": "abc-corp"}).status_code == 403
    login_as(client, db, world["contrib"])
    assert client.get(f"{API}/trust").status_code == 403
    login_as(client, db, world["caico"])
    assert _page(client)["slug"] == "abc-corp"
    login_as(client, db, world["other_caico"])
    r = client.put(f"{API}/trust/page", json={"slug": "abc-corp", "title": "x", "live": True})
    assert r.status_code == 409  # slugs are unique across clients
    assert client.put(f"{API}/trust/page", json={"slug": "Bad Slug!", "title": "x"}).status_code == 422


def test_item_is_public_only_after_caico_approval_and_futran_confirmation(client, db, world, signed):
    login_as(client, db, world["caico"])
    _page(client)
    it = _item(client, kind="governance", title="Governance", body="An AI governance committee chaired by our COO meets quarterly.")
    assert it["status"] == "draft"
    assert client.get(f"{API}/public/trust/abc-corp").json()["items"] == []
    assert client.post(f"{API}/trust/items/{it['id']}/approve").json()["status"] == "awaiting_confirmation"
    assert client.get(f"{API}/public/trust/abc-corp").json()["items"] == []
    login_as(client, db, world["aud"])
    assert client.post(f"{API}/trust/items/{it['id']}/confirm", json={}).status_code in (403, 404)
    login_as(client, db, world["chief"])
    queue = client.get(f"{API}/trust/confirmations").json()["items"]
    assert [q["id"] for q in queue] == [it["id"]] and queue[0]["client_name"] == "ABC Corp"
    assert queue[0]["report"]["ref"] == "FSL-AI-AUD-2026-001 v1.1"
    done = client.post(f"{API}/trust/items/{it['id']}/confirm", json={"note": "Matches the governance section."}).json()
    assert done["status"] == "published" and done["confirmed_report_id"] == signed["report"].id
    client.cookies.clear()
    pub = client.get(f"{API}/public/trust/abc-corp")
    assert pub.status_code == 200
    assert [i["title"] for i in pub.json()["items"]] == ["Governance"]
    assert db.scalar(select(AuditLog).where(AuditLog.action == "trust.confirm")) is not None


def test_no_signed_report_means_nothing_can_be_confirmed(client, db, world, unsigned_client):
    login_as(client, db, world["other_caico"])
    _page(client, slug="other-co")
    it = _item(client, kind="governance", title="Governance", body="We have a committee.")
    client.post(f"{API}/trust/items/{it['id']}/approve")
    login_as(client, db, world["chief"])
    r = client.post(f"{API}/trust/items/{it['id']}/confirm", json={})
    assert r.status_code == 409 and "signed report" in r.json()["detail"]


def test_badge_and_bias_summary_come_from_the_signed_report(client, db, world, signed):
    login_as(client, db, world["caico"])
    _page(client)
    sources = client.get(f"{API}/trust").json()["sources"]
    assert [e["id"] for e in sources["engagements"]] == [world["engagement"].id]
    assert [s["id"] for s in sources["bias_summaries"]] == [signed["summary"].id]
    badge = _item(client, kind="badge", source_id=world["engagement"].id, show_rating=False)
    bias = _item(client, kind="bias_summary", source_id=signed["summary"].id)
    for i in (badge, bias):
        _publish(client, db, world, i["id"])
    client.cookies.clear()
    items = {i["kind"]: i for i in client.get(f"{API}/public/trust/abc-corp").json()["items"]}
    b = items["badge"]["content"]
    assert b["report_ref"] == "FSL-AI-AUD-2026-001 v1.1" and b["period_start"] == "2026-01-01" and b["signed_on"] == "2026-09-30"
    assert "rating" not in b  # only when the client opts in
    s = items["bias_summary"]["content"]
    assert s["tool_name"] == "ScreenRank résumé screening" and s["audit_date"] == "2026-09-01" and s["auditor"] == "Futran Solutions"
    assert s["impact_ratios"][0]["impact_ratio"] == 0.94


def test_rating_band_only_when_opted_in(client, db, world, signed):
    login_as(client, db, world["caico"])
    _page(client)
    badge = _item(client, kind="badge", source_id=world["engagement"].id, show_rating=True)
    _publish(client, db, world, badge["id"])
    client.cookies.clear()
    [b] = client.get(f"{API}/public/trust/abc-corp").json()["items"]
    assert b["content"]["rating"] == "Medium (3)"


def test_edit_after_publication_keeps_the_confirmed_version_public_until_reconfirmed(client, db, world, signed):
    login_as(client, db, world["caico"])
    _page(client)
    it = _item(client, kind="governance", title="Governance", body="Committee meets quarterly.")
    _publish(client, db, world, it["id"])
    login_as(client, db, world["caico"])
    r = client.put(f"{API}/trust/items/{it['id']}", json={"title": "Governance", "body": "Committee meets monthly and audits every system."})
    assert r.status_code == 200 and r.json()["status"] == "draft" and r.json()["live"] is True
    client.cookies.clear()
    [pub] = client.get(f"{API}/public/trust/abc-corp").json()["items"]
    assert pub["body"] == "Committee meets quarterly."
    login_as(client, db, world["caico"])
    assert client.post(f"{API}/trust/items/{it['id']}/withdraw").status_code == 200
    client.cookies.clear()
    assert client.get(f"{API}/public/trust/abc-corp").json()["items"] == []


def test_futran_return_sends_the_item_back(client, db, world, signed):
    login_as(client, db, world["caico"])
    _page(client)
    it = _item(client, kind="commitment", title="AI in hiring", body="A person reviews every recommendation and we never use AI without a bias audit.")
    client.post(f"{API}/trust/items/{it['id']}/approve")
    login_as(client, db, world["chief"])
    r = client.post(f"{API}/trust/items/{it['id']}/return", json={"note": "The report found one system without a bias audit; reword the claim."})
    assert r.status_code == 200 and r.json()["status"] == "returned"
    assert client.post(f"{API}/trust/items/{it['id']}/return", json={}).status_code == 409


def test_public_page_isolation_and_unknown_slugs(client, db, world, signed, unsigned_client):
    login_as(client, db, world["caico"])
    _page(client)
    it = _item(client, kind="governance", title="ABC governance", body="ABC text.")
    _publish(client, db, world, it["id"])
    login_as(client, db, world["other_caico"])
    _page(client, slug="other-co")
    client.cookies.clear()
    assert client.get(f"{API}/public/trust/other-co").json()["items"] == []
    assert client.get(f"{API}/public/trust/no-such-page").status_code == 404
    # another client's slug never reaches ABC's documents or items
    assert client.get(f"{API}/public/trust/other-co/items/{it['id']}/document").status_code == 404
    body = client.get(f"{API}/public/trust/abc-corp").json()
    assert set(body) <= {"slug", "organization", "title", "intro", "contact_email", "access", "nda_text", "noindex", "items", "updated_at"}
    # a page that is not live is not public
    login_as(client, db, world["caico"])
    _page(client, live=False)
    client.cookies.clear()
    assert client.get(f"{API}/public/trust/abc-corp").status_code == 404


def test_noindex_header_and_view_counts(client, db, world, signed):
    login_as(client, db, world["caico"])
    _page(client)
    client.cookies.clear()
    r = client.get(f"{API}/public/trust/abc-corp")
    assert r.headers["x-robots-tag"] == "noindex" and r.json()["noindex"] is True
    html = client.get("/trust/abc-corp")
    assert html.headers.get("x-robots-tag") == "noindex"
    client.get(f"{API}/public/trust/abc-corp")
    assert db.scalar(select(TrustCenterView.views)) == 2
    login_as(client, db, world["caico"])
    assert sum(d["views"] for d in client.get(f"{API}/trust").json()["views"]) == 2
    _page(client, indexable=True)
    client.cookies.clear()
    assert "x-robots-tag" not in client.get(f"{API}/public/trust/abc-corp").headers
    assert "x-robots-tag" not in client.get("/trust/abc-corp").headers


def test_policy_item_document_behind_the_nda_gate(client, db, world, signed):
    from tests.policies.test_policy_builder import _publish as publish_policy

    pol = publish_policy(client, db, world, ack=False)
    login_as(client, db, world["caico"])
    _page(client, access="nda", nda_text="You agree to keep these documents confidential.")
    it = _item(client, kind="policy", source_id=pol["id"])
    assert it["title"] == "AI acceptable use policy"
    _publish(client, db, world, it["id"])
    client.cookies.clear()
    page = client.get(f"{API}/public/trust/abc-corp").json()
    [p] = page["items"]
    assert p["content"]["document"] is True and p["gated"] is True and page["access"] == "nda"
    assert client.get(f"{API}/public/trust/abc-corp/items/{it['id']}/document").status_code == 403
    r = client.post(f"{API}/public/trust/abc-corp/nda", json={"name": "Jo Buyer", "email": "jo@customer.example", "company": "Customer Inc", "accept": True})
    assert r.status_code == 200
    token = r.json()["access_token"]
    doc = client.get(f"{API}/public/trust/abc-corp/items/{it['id']}/document?access={token}")
    assert doc.status_code == 200 and doc.content.startswith(b"%PDF")
    assert client.post(f"{API}/public/trust/abc-corp/nda", json={"name": "Jo", "email": "jo@customer.example", "accept": False}).status_code == 422


def test_a_retired_policy_leaves_the_public_page_until_the_item_moves_to_the_new_version(client, db, world, signed):
    from tests.policies.test_policy_builder import _publish as publish_policy

    v1 = publish_policy(client, db, world, ack=False)
    login_as(client, db, world["caico"])
    _page(client)
    it = _item(client, kind="policy", source_id=v1["id"])
    _publish(client, db, world, it["id"])
    client.cookies.clear()
    [p] = client.get(f"{API}/public/trust/abc-corp").json()["items"]
    assert p["content"]["version_no"] == 1
    assert client.get(f"{API}/public/trust/abc-corp/items/{it['id']}/document").status_code == 200
    # version 2 is published and version 1 retired
    login_as(client, db, world["caico"])
    v2 = client.post(f"{API}/policies/{v1['id']}/new-version").json()
    client.post(f"{API}/policies/{v2['id']}/submit")
    assert client.post(f"{API}/policies/{v2['id']}/approve", json={}).json()["status"] == "published"
    client.cookies.clear()
    assert client.get(f"{API}/public/trust/abc-corp").json()["items"] == []
    assert client.get(f"{API}/public/trust/abc-corp/items/{it['id']}/document").status_code == 404
    # the editor says the item needs updating, and moving it to version 2 needs approval and confirmation again
    login_as(client, db, world["caico"])
    [ed] = client.get(f"{API}/trust").json()["items"]
    assert ed["live"] is False and "version 2" in ed["problem"] and ed["update_to"] == {"policy_id": v2["id"], "version_no": 2}
    r = client.put(f"{API}/trust/items/{it['id']}", json={"source_id": v2["id"]})
    assert r.status_code == 200 and r.json()["status"] == "draft" and r.json()["source_id"] == v2["id"] and r.json()["problem"] is None
    client.cookies.clear()
    assert client.get(f"{API}/public/trust/abc-corp").json()["items"] == []
    _publish(client, db, world, it["id"])
    client.cookies.clear()
    [p] = client.get(f"{API}/public/trust/abc-corp").json()["items"]
    assert p["content"]["version_no"] == 2
    assert client.get(f"{API}/public/trust/abc-corp/items/{it['id']}/document").status_code == 200


def test_a_policy_item_moves_only_to_a_later_version_of_the_same_policy(client, db, world, signed):
    from tests.policies.test_policy_builder import _publish as publish_policy

    v1 = publish_policy(client, db, world, ack=False)
    login_as(client, db, world["caico"])
    other = client.post(f"{API}/policies", json={"template_code": "incident_response"})
    assert other.status_code == 200, other.text
    _page(client)
    it = _item(client, kind="policy", source_id=v1["id"])
    r = client.put(f"{API}/trust/items/{it['id']}", json={"source_id": other.json()["id"]})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "source_id"
