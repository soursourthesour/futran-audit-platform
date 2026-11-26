"""The website sees the same laws and cases, with the same fields and filters, as the app's Law library and Litigation
tracker, less the fields listed in app.library.content.EXCLUDED."""
import pytest

from app.library import content as C
from tests.library.conftest import LIB, all_pages, hdr, staff


def _staff_laws(client, w, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    body = staff(client, w, f"/reg/laws?{qs}")
    return [x for g in body["groups"] for x in g["laws"]], body


def _classified(staff_keys, public_keys, excluded, renamed=()):
    """Every field the app returns is either served or listed as excluded, with a reason."""
    unclassified = set(staff_keys) - set(public_keys) - set(excluded) - set(renamed)
    assert not unclassified, f"staff fields neither served nor excluded: {sorted(unclassified)}"
    assert not set(public_keys) & set(excluded), "an excluded field is served"


# ------------------------------------------------------------------ laws

def test_law_list_matches_the_law_library(client, libw, key):
    rows, body = _staff_laws(client, libw)
    pub = all_pages(client, "/laws", key)
    assert [x["id"] for x in pub] == [x["id"] for x in rows]  # same laws, same order (geography, then name)
    by_id = {x["id"]: x for x in rows}
    for p in pub:
        s = by_id[p["id"]]
        _classified(s, p, C.EXCLUDED["law_row"])
        for k in p:
            if k in s:
                assert p[k] == s[k] or k == "last_change", (p["id"], k)
        assert p["region_label"] == dict(C.REGIONS)[p["region"]]
    assert len(pub) == body["kpis"]["library"]


@pytest.mark.parametrize("params", [
    {"region": "eu"}, {"region": "us_states"}, {"status": "in_force"}, {"status": "enacted_not_in_force"}, {"applies_to": "developer"},
    {"topic": "hiring"}, {"q": "colorado"}, {"q": "impact assessment"}, {"show": "all"}, {"show": "all", "region": "india"},
    {"region": "us_states", "topic": "hiring", "q": "employ"},
])
def test_law_filters_match_the_law_library(client, libw, key, params):
    rows, _ = _staff_laws(client, libw, **params)
    pub = all_pages(client, "/laws", key, **params)
    assert sorted(x["id"] for x in pub) == sorted(x["id"] for x in rows), params


def test_law_list_pagination_and_sort(client, libw, key):
    first = client.get(f"{LIB}/laws", params={"limit": 5}, headers=hdr(key)).json()
    assert len(first["data"]) == 5
    p = first["pagination"]
    assert p["page"] == 1 and p["limit"] == 5 and p["total"] >= 10 and p["next_page"] == 2 and p["pages"] == -(-p["total"] // 5)
    second = client.get(f"{LIB}/laws", params={"limit": 5, "page": 2}, headers=hdr(key)).json()
    assert not {x["id"] for x in first["data"]} & {x["id"] for x in second["data"]}
    names = [x["label"].casefold() for x in all_pages(client, "/laws", key, sort="name")]
    assert names == sorted(names)
    dated = [x["effective_on"] for x in all_pages(client, "/laws", key, sort="-effective_on") if x["effective_on"]]
    assert dated == sorted(dated, reverse=True)
    past = client.get(f"{LIB}/laws", params={"page": 999}, headers=hdr(key)).json()
    assert past["data"] == [] and past["pagination"]["next_page"] is None


def test_law_record_matches_the_law_record_screen(client, libw, key):
    law_id = libw.law.id
    s = staff(client, libw, f"/reg/laws/{law_id}")
    p = client.get(f"{LIB}/laws/{law_id}", headers=hdr(key)).json()
    _classified(s, p, C.EXCLUDED["law_record"])
    _classified(s["version"], p["version"], C.EXCLUDED["law_version"])
    for k in ("id", "short_name", "label", "citation", "type", "binding", "topics", "region", "geography", "jurisdiction_code", "parent_geography",
              "scope_tests", "requirements", "role_maps", "committees", "sources"):
        assert p[k] == s[k], k
    assert {k: v for k, v in s["version"].items() if k not in C.EXCLUDED["law_version"]} == p["version"]
    assert [h["version_no"] for h in p["history"]] == [h["version_no"] for h in s["history"]]
    assert all(set(h) == {"id", "version_no", "change", "date"} for h in p["history"])
    # approved obligations only, as the Obligations card shows them
    obl = staff(client, libw, f"/reg/laws/{law_id}/obligations")
    assert [o["id"] for o in p["obligations"]] == [o["id"] for o in obl["approved"]]
    _classified(obl["approved"][0], p["obligations"][0], C.EXCLUDED["obligation"])
    _classified(s["history"][0], p["history"][0], C.EXCLUDED["history"])
    assert "role_maps" in p and "roles" not in p
    # related court cases, as the Related cases card (the litigation tracker's /laws/{id}/cases) shows them
    cases = staff(client, libw, f"/laws/{law_id}/cases")
    assert sorted(c["id"] for c in p["cases"]) == sorted(c["id"] for c in cases)
    assert libw.case.id in {c["id"] for c in p["cases"]}


def test_law_record_of_a_law_outside_the_library_is_still_served(client, libw, key):
    """show=all lists matrix laws without requirements; each opens like any other."""
    lib = {x["id"] for x in all_pages(client, "/laws", key)}
    extra = next(x for x in all_pages(client, "/laws", key, show="all") if x["id"] not in lib)
    r = client.get(f"{LIB}/laws/{extra['id']}", headers=hdr(key))
    assert r.status_code == 200 and r.json()["requirements"] == []


def test_superseded_law_ids_are_not_served(client, db, libw, key):
    from app.laws.models import Regulation

    old = db.query(Regulation).filter(Regulation.superseded_by_id.is_not(None)).first()
    if old is None:
        pytest.skip("the matrix has no superseded rows")
    assert client.get(f"{LIB}/laws/{old.id}", headers=hdr(key)).status_code == 404


# ------------------------------------------------------------------ cases

def test_case_list_matches_the_litigation_tracker(client, libw, key):
    s = staff(client, libw, "/litigation")
    pub = all_pages(client, "/cases", key)
    assert sorted(x["id"] for x in pub) == sorted(x["id"] for x in s["items"])
    by_id = {x["id"]: x for x in s["items"]}
    for p in pub:
        _classified(by_id[p["id"]], p, C.EXCLUDED["case_row"])
        for k in p:
            if k in by_id[p["id"]]:
                assert p[k] == by_id[p["id"]][k], (p["id"], k)
    # the tracker's initial order: geography, then name
    assert [(x["geography"] or "", x["name"]) for x in pub] == sorted((x["geography"] or "", x["name"]) for x in pub)


@pytest.mark.parametrize("params", [{"stage": "discovery"}, {"stage": "discovery,decided"}, {"area": "Hiring discrimination"}, {"geography": "United States · federal"},
                                    {"q": "screening"}, {"q": "HARLOW"}, {"stage": "filed", "q": "ai"}])
def test_case_filters_match_the_litigation_tracker(client, libw, key, params):
    s = staff(client, libw, "/litigation?" + "&".join(f"{k}={v}" for k, v in params.items()))
    pub = all_pages(client, "/cases", key, **params)
    assert sorted(x["id"] for x in pub) == sorted(x["id"] for x in s["items"]), params


def test_case_sort_by_last_update(client, libw, key):
    dates = [x["last_update_on"] for x in all_pages(client, "/cases", key, sort="-last_update_on") if x["last_update_on"]]
    assert dates == sorted(dates, reverse=True)


def test_case_record_matches_the_case_record_screen(client, libw, key):
    s = staff(client, libw, f"/litigation/{libw.case.id}")
    p = client.get(f"{LIB}/cases/{libw.case.id}", headers=hdr(key)).json()
    _classified(s, p, C.EXCLUDED["case_record"])
    for k in p:
        if k in s:
            assert p[k] == s[k], k
    assert p["talking_points_client"] == "Check that your screening vendor has run a bias audit."
    assert p["timeline"][-1]["stage"] == "discovery" and p["sources"][0]["title"] == "Court docket"
    assert [x["id"] for x in p["laws"]] == [libw.law.id]
    assert p["laws"][0]["short_name"] == "SB 26-189" and p["laws"][0]["geography"] == "Colorado"


# ------------------------------------------------------------------ meta

def test_meta_lists_filters_counts_and_refresh_times(client, libw, key):
    m = client.get(f"{LIB}/meta", headers=hdr(key)).json()
    lib = staff(client, libw, "/reg/laws")
    lit = staff(client, libw, "/litigation")
    assert m["laws"]["filters"]["regions"] == lib["regions"] and m["laws"]["filters"]["topics"] == lib["topics"]
    assert {o["value"] for o in m["laws"]["filters"]["statuses"]} >= {"in_force", "enacted_not_in_force", "repealed"}
    assert {o["value"] for o in m["laws"]["filters"]["applies_to"]} >= {"deployer", "developer"}
    assert m["laws"]["filters"]["sort"] == ["geography", "name", "effective_on", "-effective_on"]
    k = lib["kpis"]
    assert m["laws"]["counts"] == {"laws": k["library"], "all_laws": k["all"], "geographies": k["geographies"], "requirements": k["requirements"], "upcoming_90_days": k["upcoming"]}
    f = lit["filters"]
    assert m["cases"]["filters"]["stages"] == f["stages"] and m["cases"]["filters"]["areas"] == f["areas"] and m["cases"]["filters"]["geographies"] == f["geographies"]
    assert "clients" not in m["cases"]["filters"]
    assert m["cases"]["counts"]["cases"] == len(lit["items"])
    assert m["cases"]["counts"]["by_stage"]["discovery"] >= 1
    assert m["laws"]["last_refreshed_at"] == libw.law_run.finished_at.isoformat()
    assert m["cases"]["last_refreshed_at"] == libw.lit_run.finished_at.isoformat()


def test_last_refreshed_header_follows_the_library(client, libw, key):
    assert client.get(f"{LIB}/laws", headers=hdr(key)).headers["x-library-last-refreshed"] == libw.law_run.finished_at.isoformat()
    assert client.get(f"{LIB}/cases", headers=hdr(key)).headers["x-library-last-refreshed"] == libw.lit_run.finished_at.isoformat()
    assert client.get(f"{LIB}/meta", headers=hdr(key)).headers["x-library-last-refreshed"] == libw.lit_run.finished_at.isoformat()  # the later of the two


def test_a_failed_refresh_does_not_count_as_refreshed(client, db, libw, key):
    from app.core.clock import utcnow
    from app.refresh.models import RefreshRun

    db.add(RefreshRun(kind="law", status="failed", started_at=utcnow(), finished_at=utcnow()))
    db.commit()
    m = client.get(f"{LIB}/meta", headers=hdr(key)).json()
    assert m["laws"]["last_refreshed_at"] == libw.law_run.finished_at.isoformat()


def test_an_approved_proposal_goes_public(client, db, libw, key):
    """A pending AI proposal is not served; once a person approves it, the next response has it."""
    from sqlalchemy import select

    from app.regmaster.models import ProposedChange

    before = client.get(f"{LIB}/laws/{libw.law.id}", headers=hdr(key)).json()
    assert before["version"]["cure_period"] != "PENDING-VALUE: 90 days"
    pc = db.scalar(select(ProposedChange).where(ProposedChange.summary.like("PENDING-SUMMARY%")))
    libw.as_(libw.chief)
    r = client.post(f"/api/v1/reg/changes/{pc.id}/decide", json={"action": "approve"})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    after = client.get(f"{LIB}/laws/{libw.law.id}", headers=hdr(key)).json()
    assert after["version"]["cure_period"] == "PENDING-VALUE: 90 days"
    assert after["version"]["version_no"] == before["version"]["version_no"] + 1
