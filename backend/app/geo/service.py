"""Address suggestions for the new-client wizard.

Providers:
- photon (default): https://photon.komoot.io, OpenStreetMap data, free, no key. Fair use only: the client waits for
  three characters and a pause in typing before asking, and answers are cached here for ten minutes.
- google: Places API (New) Autocomplete, then Place Details for the suggestion the user picks. Needs GOOGLE_PLACES_API_KEY.
- off: no suggestions; the address is typed by hand.

A provider that fails or times out gives no suggestions; the wizard says so and the user types the address.
"""
import logging
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass

import httpx
from sqlalchemy.orm import Session

from app.core.config import VERSION, Settings
from app.reference.jurisdictions import _find_subdivision, by_code

log = logging.getLogger(__name__)

PHOTON_URL = "https://photon.komoot.io/api/"
GOOGLE_AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
GOOGLE_DETAILS_URL = "https://places.googleapis.com/v1/places/{id}"
TIMEOUT = 4.0
LIMIT = 5
MIN_CHARS = 3
CACHE_SECONDS = 600
CACHE_SIZE = 500
# Countries that write the house number after the street name (Friedrichstraße 68).
NUMBER_AFTER_STREET = {"AT", "BA", "BE", "BG", "CH", "CZ", "DE", "DK", "EE", "ES", "FI", "GR", "HR", "HU", "IS", "IT", "LI", "LT", "LU", "LV",
                       "NL", "NO", "PL", "PT", "RO", "RS", "SE", "SI", "SK", "TR", "AR", "BR", "CL", "CO", "MX", "PE", "UY"}
TRANSPORT: httpx.BaseTransport | None = None  # tests install a mock transport here; production uses the network

_cache: "OrderedDict[tuple, tuple[float, list[dict]]]" = OrderedDict()


class Unavailable(Exception):
    pass


@dataclass
class Suggestion:
    id: str
    label: str
    street: str | None = None
    city: str | None = None
    state: str | None = None
    state_code: str | None = None
    postal_code: str | None = None
    country_code: str | None = None
    needs_details: bool = False  # Google: fetch the parts with `place` once the user picks it


def clear_cache() -> None:
    _cache.clear()


def provider(settings: Settings) -> str:
    """photon, google or off. Left blank, Google is used when a key is set and Photon otherwise."""
    choice = (settings.address_autocomplete or "").strip().lower()
    if choice in ("off", "photon", "google"):
        return choice
    return "google" if settings.google_places_api_key else "photon"


def _client(settings: Settings) -> httpx.Client:
    agent = f"FutranAuditPlatform/{VERSION} (client address suggestions; {settings.base_url})"
    return httpx.Client(transport=TRANSPORT, timeout=TIMEOUT, headers={"User-Agent": agent})


def _state(db: Session, country_code: str | None, state: str | None) -> tuple[str | None, str | None]:
    """The state or region's name and ISO 3166-2 code, from the platform's jurisdiction list when it is known there."""
    if not country_code or not state:
        return state, None
    country = by_code(db, country_code.upper())
    j = _find_subdivision(db, country, state) if country is not None else None
    return (j.name, j.code) if j is not None else (state, None)


def _join(*parts: str | None, sep: str = ", ") -> str:
    return sep.join(p for p in parts if p)


# ---- Photon
def _photon(db: Session, settings: Settings, q: str) -> list[Suggestion]:
    with _client(settings) as http:
        r = http.get(PHOTON_URL, params={"q": q, "limit": LIMIT, "lang": "en"})
    if r.status_code != 200:
        raise Unavailable(f"Photon answered {r.status_code}")
    out: list[Suggestion] = []
    for i, f in enumerate(r.json().get("features", [])):
        p = f.get("properties") or {}
        cc = (p.get("countrycode") or "").upper() or None
        if not cc:
            continue
        number, street_name, name = p.get("housenumber"), p.get("street"), p.get("name")
        if street_name:
            street = _join(street_name, number, sep=" ") if cc in NUMBER_AFTER_STREET else _join(number, street_name, sep=" ")
        elif p.get("type") == "street":
            street = name
        else:
            street = None
        city = p.get("city") or (name if p.get("type") in ("city", "town", "village") else None)
        state, state_code = _state(db, cc, p.get("state") or city)  # city-states such as Berlin carry no separate state
        if state_code is None and not p.get("state"):
            state = None
        redundant = not name or name in (street, street_name, city) or (number and name.startswith(str(number)))
        place = None if redundant else name  # a building or business name, not the address again
        label = _join(place, street, city, _join(state, p.get("postcode"), sep=" "), p.get("country"))
        if any(s.label == label for s in out):
            continue
        out.append(Suggestion(id=f"photon-{p.get('osm_type', '')}{p.get('osm_id', i)}", label=label, street=street, city=city, state=state,
                              state_code=state_code, postal_code=p.get("postcode"), country_code=cc))
    return out


# ---- Google Places API (New)
def _google_headers(settings: Settings, fields: str | None = None) -> dict:
    h = {"X-Goog-Api-Key": settings.google_places_api_key or ""}
    if fields:
        h["X-Goog-FieldMask"] = fields
    return h


def _google(settings: Settings, q: str, session: str | None) -> list[Suggestion]:
    if not settings.google_places_api_key:
        raise Unavailable("GOOGLE_PLACES_API_KEY is not set")
    body = {"input": q, "languageCode": "en"} | ({"sessionToken": session} if session else {})
    with _client(settings) as http:
        r = http.post(GOOGLE_AUTOCOMPLETE_URL, json=body, headers=_google_headers(settings))
    if r.status_code != 200:
        raise Unavailable(f"Google Places answered {r.status_code}")
    out = []
    for s in r.json().get("suggestions", [])[:LIMIT]:
        pred = s.get("placePrediction")
        if pred and pred.get("placeId"):
            out.append(Suggestion(id=pred["placeId"], label=(pred.get("text") or {}).get("text", ""), needs_details=True))
    return out


def google_place(db: Session, settings: Settings, place_id: str, session: str | None) -> dict:
    if provider(settings) != "google" or not settings.google_places_api_key:
        raise Unavailable("Google Places is not in use")
    params = {"languageCode": "en"} | ({"sessionToken": session} if session else {})
    with _client(settings) as http:
        r = http.get(GOOGLE_DETAILS_URL.format(id=place_id), params=params, headers=_google_headers(settings, "addressComponents,formattedAddress"))
    if r.status_code != 200:
        raise Unavailable(f"Google Places answered {r.status_code}")
    data = r.json()
    parts: dict[str, dict] = {}
    for c in data.get("addressComponents", []):
        for t in c.get("types", []):
            parts.setdefault(t, c)

    def long(t: str) -> str | None:
        return (parts.get(t) or {}).get("longText")

    cc = ((parts.get("country") or {}).get("shortText") or "").upper() or None
    state_raw = (parts.get("administrative_area_level_1") or {}).get("shortText") or long("administrative_area_level_1")
    state, state_code = _state(db, cc, state_raw)
    if state_code is None:
        state = long("administrative_area_level_1")
    city = long("locality") or long("postal_town") or long("sublocality") or long("administrative_area_level_2")
    street = _join(long("street_number"), long("route"), sep=" ") or None
    return asdict(Suggestion(id=place_id, label=data.get("formattedAddress") or "", street=street, city=city, state=state, state_code=state_code,
                             postal_code=long("postal_code"), country_code=cc))


# ---- entry point
def suggest(db: Session, settings: Settings, q: str, session: str | None = None) -> dict:
    which = provider(settings)
    q = " ".join((q or "").split())[:200]
    if which == "off":
        return {"available": False, "provider": which, "suggestions": []}
    if len(q) < MIN_CHARS:
        return {"available": True, "provider": which, "suggestions": []}
    key = (which, q.casefold())
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        _cache.move_to_end(key)
        return {"available": True, "provider": which, "suggestions": hit[1]}
    try:
        found = _google(settings, q, session) if which == "google" else _photon(db, settings, q)
    except (httpx.HTTPError, ValueError, Unavailable) as exc:
        log.warning("Address suggestions unavailable (%s): %s", which, exc)
        return {"available": False, "provider": which, "suggestions": []}
    rows = [asdict(s) for s in found]
    _cache[key] = (time.monotonic() + CACHE_SECONDS, rows)
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return {"available": True, "provider": which, "suggestions": rows}
