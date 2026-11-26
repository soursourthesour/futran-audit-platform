"""The boundary that is not optional: nothing that ties a law or a case to a Futran client or to Futran staff leaves through
the website library API. The world seeds a client matched to a case (with its register system and vendor), client
applicability with a reason, an opportunity with an owner and value, a staff follow, a named law reviewer, pending
proposals (a law change and a new case), an unapproved obligation and internal talking points. Every public response
is walked, keys and string values, and none of it may appear."""
from sqlalchemy import select

from app.tenancy.models import User
from tests.library.conftest import LIB, all_pages, hdr, walk

FORBIDDEN_KEYS = {
    "organization_id", "organization_name", "organization_ids", "client_id", "clients", "clients_count", "systems_count", "matches", "match_summary",
    "match_rule", "match_reason", "ai_system_ids", "systems", "following", "follows", "owner_id", "owner", "opportunities", "opportunity",
    "reviewer_id", "review_due_on", "refresh_every_days", "watch", "approved_by", "proposed_by", "created_by", "updated_by", "decided_by", "started_by",
    "pending", "pending_count", "used_by_clients", "used_by_systems", "can_edit", "can_suggest", "can_approve", "can_extract", "claude_available",
    "talking_points_futran", "rejected_reason", "interaction_id", "quote_found", "confidence", "reason_text", "scope_answers", "open",
}


def _every_public_response(client, libw, key) -> list:
    out = [client.get(f"{LIB}/meta", headers=hdr(key)).json()]
    laws = all_pages(client, "/laws", key, show="all")
    out.append(laws)
    for params in ({"q": "quillfeather"}, {"topic": "hiring"}, {"region": "us_states"}):
        out.append(all_pages(client, "/laws", key, **params))
    cases = all_pages(client, "/cases", key)
    out.append(cases)
    out.append(all_pages(client, "/cases", key, q="harlow"))
    linked = {libw.law.id}
    for c in cases:
        detail = client.get(f"{LIB}/cases/{c['id']}", headers=hdr(key)).json()
        out.append(detail)
        linked |= {x["id"] for x in detail["laws"]}
    for lid in sorted(linked) + [x["id"] for x in laws[:15]]:
        r = client.get(f"{LIB}/laws/{lid}", headers=hdr(key))
        assert r.status_code == 200
        out.append(r.json())
    return out


def test_no_client_staff_or_sales_data_in_any_public_response(client, db, libw, key):
    bodies = _every_public_response(client, libw, key)
    keys: set = set()
    strings: list = []
    walk(bodies, keys, strings)
    text = "\n".join(strings)
    assert not keys & FORBIDDEN_KEYS, sorted(keys & FORBIDDEN_KEYS)
    users = list(db.scalars(select(User)))
    secrets = {
        "client name": libw.org.name, "client id": libw.org.id, "client department": "Talent Acquisition",
        "register system": libw.system.name, "register system id": libw.system.id, "register reference": "AIS-901", "vendor": "Zyxtrel",
        "opportunity id": libw.opp.id, "opportunity reason": "OPP-WHY", "opportunity value": "48500", "opportunity service": "Briefing and review of AI like that",
        "applicability reason": "CLIENT-REASON", "internal talking points": "INTERNAL-TP", "pending law change": "PENDING-SUMMARY",
        "pending value": "PENDING-VALUE", "pending case": "Unreviewed v. Proposal", "pending case summary": "PENDING-CASE",
        "unapproved obligation": "UNAPPROVED-OBLIGATION", "match reason": "Matched on",
    }
    for u in users:
        secrets[f"user id {u.name}"] = u.id
        secrets[f"user email {u.name}"] = u.email
        secrets[f"user name {u.name}"] = u.name
    leaked = {label: value for label, value in secrets.items() if value and value.casefold() in text.casefold()}
    assert not leaked, leaked
    # the raw bodies too (numbers and ids outside strings)
    raw = client.get(f"{LIB}/cases/{libw.case.id}", headers=hdr(key)).text + client.get(f"{LIB}/laws/{libw.law.id}", headers=hdr(key)).text
    assert libw.org.id not in raw and "48500" not in raw and libw.opp.id not in raw


def test_the_seeded_world_really_holds_the_confidential_data(client, db, libw):
    """Guards the test above: the staff endpoints do show these, so their absence from the public API is meaningful."""
    from tests.library.conftest import staff

    case = staff(client, libw, f"/litigation/{libw.case.id}")
    assert case["matches"][0]["organization_name"] == libw.org.name and case["talking_points_futran"].startswith("INTERNAL-TP")
    law = staff(client, libw, f"/reg/laws/{libw.law.id}")
    assert law["used_by_clients"] == 1 and law["pending"][0]["summary"].startswith("PENDING-SUMMARY")
    rows = [x for g in staff(client, libw, "/reg/laws")["groups"] for x in g["laws"]]
    assert next(x for x in rows if x["id"] == libw.law.id)["reviewer_id"] == libw.aud.id
    filters = staff(client, libw, "/litigation")["filters"]
    assert [c["name"] for c in filters["clients"]] == [libw.org.name]


def test_client_filter_is_not_accepted(client, libw, key):
    """The tracker's client_id filter would reveal which cases match a client: the public API refuses it rather than ignoring it."""
    r = client.get(f"{LIB}/cases", params={"client_id": libw.org.id}, headers=hdr(key))
    assert r.status_code == 422
    assert libw.org.id not in r.text
