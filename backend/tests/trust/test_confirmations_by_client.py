"""Feedback of 10 November, F5: Trust Center confirmations grouped and sorted by client, with a count per client."""
from tests.factories import login_as
from tests.trust.test_trust_center import API, _item, _page


def _approve(client, db, who, slug, titles):
    login_as(client, db, who)
    _page(client, slug=slug)
    for t in titles:
        it = _item(client, kind="governance", title=t, body="We have a committee.")
        assert client.post(f"{API}/trust/items/{it['id']}/approve").status_code == 200


def test_queue_is_sorted_by_client_with_a_count_per_client(client, db, world, unsigned_client):
    # Other Co approves first, so oldest-first order alone would put it ahead of ABC Corp
    _approve(client, db, world["other_caico"], "other-co", ["Other governance"])
    _approve(client, db, world["caico"], "abc-corp", ["ABC governance", "ABC rights"])
    login_as(client, db, world["chief"])
    body = client.get(f"{API}/trust/confirmations").json()
    names = [i["client_name"] for i in body["items"]]
    assert names == sorted(names, key=str.lower) and names[0] == "ABC Corp"
    assert [i["title"] for i in body["items"] if i["client_name"] == "ABC Corp"] == ["ABC governance", "ABC rights"]  # oldest first within a client
    counts = {c["name"]: c["count"] for c in body["clients"]}
    assert counts == {"ABC Corp": 2, world["other"].name: 1}
    assert all(c["id"] for c in body["clients"])
