"""Address suggestions for the new-client wizard (fixes 2026-10-27, item 1a). The provider is always mocked."""
import json

import httpx
import pytest

from app.geo import service as geo
from tests.factories import login_as, make_org, make_user

PHOTON = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"osm_key": "building", "type": "house", "housenumber": "350", "name": "Empire State Building", "street": "5th Avenue",
                                        "city": "New York", "state": "NY", "country": "United States", "postcode": "10118", "countrycode": "US"}},
    {"type": "Feature", "properties": {"type": "street", "name": "Friedrichstraße", "city": "Berlin", "state": "Berlin", "country": "Germany", "postcode": "10117", "countrycode": "DE"}},
    {"type": "Feature", "properties": {"type": "other", "name": "Nowhere"}},  # no country: dropped
]}


@pytest.fixture
def people(db, matrix):
    f = make_org(db, type="futran")
    c = make_org(db, type="client", name="Client Co")
    p = {"aud": make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test"),
         "admin": make_user(db, f, roles=["admin"], name="Ada Admin", email="ada@futran.test"),
         "client": make_user(db, c, roles=["caico"], name="Cleo Client", email="cleo@client.test")}
    db.commit()
    return p


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Every test gets a transport that fails loudly unless it installs its own."""
    geo.clear_cache()

    def refuse(request):
        raise AssertionError(f"unexpected network call to {request.url}")

    monkeypatch.setattr(geo, "TRANSPORT", httpx.MockTransport(refuse))
    yield
    geo.clear_cache()


def _use(monkeypatch, handler):
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)

    monkeypatch.setattr(geo, "TRANSPORT", httpx.MockTransport(wrapped))
    return calls


def test_photon_suggestions_are_structured(client, db, people, monkeypatch):
    calls = _use(monkeypatch, lambda r: httpx.Response(200, json=PHOTON))
    login_as(client, db, people["aud"])
    r = client.get("/api/v1/geo/suggest", params={"q": "350 Fifth Ave"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True
    first, second = body["suggestions"]
    assert first["street"] == "350 5th Avenue" and first["city"] == "New York" and first["postal_code"] == "10118"
    assert first["country_code"] == "US" and first["state_code"] == "US-NY" and first["state"] == "New York"
    assert first["label"] == "Empire State Building, 350 5th Avenue, New York, New York 10118, United States"
    assert second["street"] == "Friedrichstraße" and second["state_code"] == "DE-BE" and second["country_code"] == "DE"
    req = calls[0]
    assert req.url.host == "photon.komoot.io" and req.url.params["q"] == "350 Fifth Ave" and req.url.params["limit"] == "5"
    assert "FutranAuditPlatform" in req.headers["user-agent"]


def test_short_queries_do_not_call_the_provider(client, db, people):
    login_as(client, db, people["aud"])
    body = client.get("/api/v1/geo/suggest", params={"q": "35"}).json()
    assert body == {"available": True, "provider": "photon", "suggestions": []}


def test_provider_failure_is_reported_quietly(client, db, people, monkeypatch):
    def boom(request):
        raise httpx.ConnectError("down")

    _use(monkeypatch, boom)
    login_as(client, db, people["aud"])
    r = client.get("/api/v1/geo/suggest", params={"q": "350 Fifth Ave"})
    assert r.status_code == 200
    assert r.json()["available"] is False and r.json()["suggestions"] == []
    _use(monkeypatch, lambda r: httpx.Response(503, text="busy"))
    assert client.get("/api/v1/geo/suggest", params={"q": "351 Fifth Ave"}).json()["available"] is False


def test_switched_off(client, db, people, settings):
    settings.address_autocomplete = "off"
    login_as(client, db, people["aud"])
    assert client.get("/api/v1/geo/suggest", params={"q": "350 Fifth Ave"}).json() == {"available": False, "provider": "off", "suggestions": []}


def test_results_are_cached(client, db, people, monkeypatch):
    calls = _use(monkeypatch, lambda r: httpx.Response(200, json=PHOTON))
    login_as(client, db, people["aud"])
    client.get("/api/v1/geo/suggest", params={"q": "350 Fifth Ave"})
    client.get("/api/v1/geo/suggest", params={"q": "350 fifth ave "})
    assert len(calls) == 1


def test_staff_only(client, db, people):
    login_as(client, db, people["client"])
    assert client.get("/api/v1/geo/suggest", params={"q": "350 Fifth Ave"}).status_code in (403, 404)
    login_as(client, db, people["admin"])  # administrators may start a client, so they get suggestions too
    assert client.get("/api/v1/geo/suggest", params={"q": "35"}).status_code == 200
    client.cookies.clear()
    assert client.get("/api/v1/geo/suggest", params={"q": "350 Fifth Ave"}).status_code == 401


GOOGLE_AUTOCOMPLETE = {"suggestions": [{"placePrediction": {"placeId": "ChIJ123", "text": {"text": "350 5th Ave, New York, NY 10118, USA"}}}]}
GOOGLE_DETAILS = {"formattedAddress": "350 5th Ave, New York, NY 10118, USA", "addressComponents": [
    {"longText": "350", "shortText": "350", "types": ["street_number"]},
    {"longText": "5th Avenue", "shortText": "5th Ave", "types": ["route"]},
    {"longText": "New York", "shortText": "New York", "types": ["locality", "political"]},
    {"longText": "New York", "shortText": "NY", "types": ["administrative_area_level_1", "political"]},
    {"longText": "United States", "shortText": "US", "types": ["country", "political"]},
    {"longText": "10118", "shortText": "10118", "types": ["postal_code"]},
]}


def test_google_places_when_a_key_is_set(client, db, people, settings, monkeypatch):
    settings.google_places_api_key = "test-key"
    settings.address_autocomplete = ""

    def handler(request):
        assert request.headers["x-goog-api-key"] == "test-key"
        if request.url.path.endswith(":autocomplete"):
            assert json.loads(request.content)["input"] == "350 Fifth Ave"
            return httpx.Response(200, json=GOOGLE_AUTOCOMPLETE)
        assert request.url.path == "/v1/places/ChIJ123"
        return httpx.Response(200, json=GOOGLE_DETAILS)

    _use(monkeypatch, handler)
    login_as(client, db, people["aud"])
    body = client.get("/api/v1/geo/suggest", params={"q": "350 Fifth Ave", "session": "s1"}).json()
    assert body["provider"] == "google" and body["available"] is True
    (s,) = body["suggestions"]
    assert s["id"] == "ChIJ123" and s["needs_details"] is True and s["label"] == "350 5th Ave, New York, NY 10118, USA"
    place = client.get("/api/v1/geo/place", params={"id": "ChIJ123", "session": "s1"}).json()
    assert place["street"] == "350 5th Avenue" and place["city"] == "New York" and place["state_code"] == "US-NY"
    assert place["postal_code"] == "10118" and place["country_code"] == "US" and place["needs_details"] is False


def test_google_chosen_without_a_key_is_unavailable(client, db, people, settings):
    settings.address_autocomplete = "google"
    settings.google_places_api_key = None
    login_as(client, db, people["aud"])
    assert client.get("/api/v1/geo/suggest", params={"q": "350 Fifth Ave"}).json()["available"] is False


def test_house_number_order_and_city_states(client, db, people, monkeypatch):
    berlin = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {
        "type": "house", "housenumber": "68", "street": "Friedrichstraße", "city": "Berlin", "country": "Germany", "postcode": "10117", "countrycode": "DE"}}]}
    _use(monkeypatch, lambda r: httpx.Response(200, json=berlin))
    login_as(client, db, people["aud"])
    (s,) = client.get("/api/v1/geo/suggest", params={"q": "Friedrichstraße 68"}).json()["suggestions"]
    assert s["street"] == "Friedrichstraße 68"
    assert (s["state"], s["state_code"]) == ("Berlin", "DE-BE")
