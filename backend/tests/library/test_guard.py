"""Review fixes, 26 Nov: (1) free text typed by staff or approved from a refresh can name a client: every served string is
checked against client and prospect names and a match is replaced with "[client]"; (2) CORS preflight is rate limited
per address and the allowed-origin set is cached; (3) origins drop default ports and use IDNA ASCII hosts."""
import logging

from sqlalchemy import select

from app.library import keys as K
from app.library.models import WebsiteApiKey
from app.litigation.models import Case
from app.regmaster.models import LawVersion, Source
from tests.factories import make_org
from tests.library.conftest import API, LIB, SITE, all_pages, hdr, new_key, walk

PLACEHOLDER = "[client]"


def _every_string(client, key, libw) -> str:
    bodies = [client.get(f"{LIB}/meta", headers=hdr(key)).json(), all_pages(client, "/laws", key, show="all"), all_pages(client, "/cases", key)]
    for c in bodies[2]:
        bodies.append(client.get(f"{LIB}/cases/{c['id']}", headers=hdr(key)).json())
    bodies.append(client.get(f"{LIB}/laws/{libw.law.id}", headers=hdr(key)).json())
    keys, strings = set(), []
    walk(bodies, keys, strings)
    return "\n".join(strings)


def test_client_names_typed_into_free_text_are_replaced(client, db, libw, key, caplog):
    prospect = make_org(db, name="Brindlewick Holdings", trading_name="Brindle Co")
    prospect.type = "prospect"
    archived = make_org(db, name="Corvane Retail Group")
    archived.status = "archived"
    v = db.get(LawVersion, libw.law.current_version_id)
    v.change_summary = "Updated after Quillfeather Mutual Insurance's review of the notice wording"
    case = db.get(Case, libw.case.id)
    case.stage_note = "Raised by quillfeather mutual insurance in October"
    case.why_matters = "Brindle Co asked about this.\nAlso relevant to Corvane Retail Group."
    case.timeline = [*case.timeline, {"on": "2026-11-20", "stage": "discovery", "label": "Brindlewick Holdings filed an amicus note"}]
    case.sources = [*case.sources, {"title": "Press", "url": "https://news.example.com/quillfeather-mutual-insurance-ai-screening"}]
    db.add(Source(regulation_id=libw.law.id, name="Client memo", url="https://files.example.com/Quillfeather_Mutual_Insurance/memo.pdf", kind="secondary"))
    db.commit()
    with caplog.at_level(logging.WARNING, logger="app.library"):
        text = _every_string(client, key, libw)
    for name in ("Quillfeather", "Brindlewick", "Brindle Co", "Corvane"):
        assert name.casefold() not in text.casefold(), name
    assert "Updated after [client]'s review" in text
    assert "Raised by [client] in October" in text
    assert "news.example.com/[client]-ai-screening" in text
    law = client.get(f"{LIB}/laws/{libw.law.id}", headers=hdr(key)).json()
    assert any(s["url"] == "https://files.example.com/[client]/memo.pdf" for s in law["sources"])
    lst = next(x for x in all_pages(client, "/laws", key) if x["id"] == libw.law.id)
    assert lst["last_change"] == "No change"  # version 1: the summary is shown in history only
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and r.name.startswith("app.library")]
    assert warnings, "staff need a warning to fix the record"
    assert not any("Quillfeather" in r.getMessage() or "Brindle" in r.getMessage() for r in warnings), "the warning must not repeat the name"
    assert any(libw.case.id in r.getMessage() for r in warnings)


def test_matching_is_by_whole_word_and_ignores_futran_and_internal_orgs(client, db, libw, key):
    make_org(db, name="Ace")  # a client called Ace must not touch "Acetone" or "placement"
    internal = make_org(db, name="Discovery Labs")
    internal.is_internal = True
    case = db.get(Case, libw.case.id)
    case.stage_note = "Acetone placement study; discovery under way at Futran Solutions"
    db.commit()
    out = client.get(f"{LIB}/cases/{libw.case.id}", headers=hdr(key)).json()
    assert out["stage_note"] == "Acetone placement study; discovery under way at Futran Solutions"


def test_a_new_client_name_invalidates_cached_responses(client, db, libw, key):
    case = db.get(Case, libw.case.id)
    case.stage_note = "Noted by Pellucid Freight"
    db.commit()
    assert client.get(f"{LIB}/cases/{libw.case.id}", headers=hdr(key)).json()["stage_note"] == "Noted by Pellucid Freight"
    make_org(db, name="Pellucid Freight")
    db.commit()
    assert client.get(f"{LIB}/cases/{libw.case.id}", headers=hdr(key)).json()["stage_note"] == "Noted by [client]"


def test_ids_and_enum_values_are_left_alone(client, db, libw, key):
    make_org(db, name="Discovery")  # a client name equal to a stage label
    db.commit()
    out = client.get(f"{LIB}/cases/{libw.case.id}", headers=hdr(key)).json()
    assert out["stage"] == "discovery" and out["id"] == libw.case.id
    assert out["stage_label"] == PLACEHOLDER  # labels are display text: matched like any other


# ------------------------------------------------------------------ preflight

def _preflight(client, origin=SITE):
    return client.options(f"{LIB}/laws", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})


def test_preflight_is_rate_limited_per_address(client, libw, key):
    codes = [_preflight(client, "https://evil.example").status_code for _ in range(31)]
    assert codes[:30] == [403] * 30 and codes[30] == 429
    r = _preflight(client)
    assert r.status_code == 429 and r.headers["retry-after"] == "60"


def test_allowed_origins_are_cached_and_dropped_on_create_and_revoke(client, db, libw, key, monkeypatch):
    calls = []
    real = K.active_origins
    monkeypatch.setattr(K, "active_origins", lambda db: calls.append(1) or real(db))
    for _ in range(3):
        assert _preflight(client).status_code == 204
    assert len(calls) == 1
    # a key written straight to the database (not through the admin endpoints) waits for the cache to expire
    db.add(WebsiteApiKey(name="side door", key_prefix="fwl_x", key_hash="0" * 64, allowed_origins=["https://late.example"], status="active"))
    db.commit()
    assert _preflight(client, "https://late.example").status_code == 403
    # creating a key through the admin endpoint drops the cache
    out = new_key(client, libw, name="Partner site", origins=("https://partner.example",))
    assert _preflight(client, "https://partner.example").status_code == 204
    libw.as_(libw.admin)
    assert client.post(f"{API}/admin/website-keys/{out['website_key']['id']}/revoke").status_code == 200
    client.cookies.clear()
    assert _preflight(client, "https://partner.example").status_code == 403


def test_origin_cache_expires(client, db, libw, key, monkeypatch):
    from app.library import public_app as P

    assert _preflight(client, "https://late.example").status_code == 403
    db.add(WebsiteApiKey(name="side door", key_prefix="fwl_x", key_hash="1" * 64, allowed_origins=["https://late.example"], status="active"))
    db.commit()
    monkeypatch.setattr(P, "ORIGINS_SECONDS", 0)
    assert _preflight(client, "https://late.example").status_code == 204


# ------------------------------------------------------------------ origins

def test_default_ports_are_dropped():
    assert K.normalize_origin("https://www.example.com:443") == "https://www.example.com"
    assert K.normalize_origin("http://localhost:80") == "http://localhost"
    assert K.normalize_origin("https://www.example.com:8443") == "https://www.example.com:8443"
    assert K.normalize_origin("http://localhost:443") == "http://localhost:443"


def test_unicode_hosts_become_idna_ascii():
    assert K.normalize_origin("https://Bücher.Example") == "https://xn--bcher-kva.example"
    assert K.normalize_origin("https://xn--bcher-kva.example") == "https://xn--bcher-kva.example"
    assert K.normalize_origin("https://BÜCHER.example:443") == K.normalize_origin("https://xn--bcher-kva.example")  # a request Origin matches the saved one
    assert K.normalize_origin("https://exa mple.com") is None


def test_saved_and_requested_origins_are_normalized_the_same_way(client, db, libw):
    out = new_key(client, libw, origins=("https://bücher.example:443",))
    assert out["website_key"]["allowed_origins"] == ["https://xn--bcher-kva.example"]
    k = out["key"]
    for origin in ("https://xn--bcher-kva.example", "https://xn--bcher-kva.example:443", "https://XN--BCHER-KVA.example"):  # browsers send hosts in ASCII
        r = client.get(f"{LIB}/meta", headers=hdr(k, Origin=origin))
        assert r.status_code == 200, origin
        assert r.headers["access-control-allow-origin"] == origin
    assert _preflight(client, "https://xn--bcher-kva.example:443").status_code == 204
    row = db.scalar(select(WebsiteApiKey).where(WebsiteApiKey.id == out["website_key"]["id"]))
    assert row.allowed_origins == ["https://xn--bcher-kva.example"]

