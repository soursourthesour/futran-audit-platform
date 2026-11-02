"""The AI vendor list (ai_vendors.yaml) and the matchers that turn raw signals into AI products (spec §21 F2)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import yaml

PATH = Path(__file__).with_name("ai_vendors.yaml")


@dataclass(frozen=True)
class AIVendor:
    key: str
    vendor: str
    product: str
    category: str
    names: tuple[str, ...] = field(default_factory=tuple)
    domains: tuple[str, ...] = field(default_factory=tuple)
    expense: tuple[str, ...] = field(default_factory=tuple)
    attestation: tuple[str, ...] = field(default_factory=tuple)


@lru_cache
def all_vendors() -> tuple[AIVendor, ...]:
    data = yaml.safe_load(PATH.read_text(encoding="utf-8"))
    return tuple(AIVendor(key=v["key"], vendor=v["vendor"], product=v["product"], category=v.get("category") or "AI tool",
                          names=tuple(v.get("names") or ()), domains=tuple(d.lower() for d in v.get("domains") or ()),
                          expense=tuple(v.get("expense") or ()), attestation=tuple(v.get("attestation") or ())) for v in data["vendors"])


def by_key(key: str | None) -> AIVendor | None:
    return next((v for v in all_vendors() if v.key == key), None)


def _phrase(p: str) -> re.Pattern:
    # a phrase bounded by the start or end of the text or by a character that is not a letter or digit
    return re.compile(r"(?<![a-z0-9])" + re.escape(p.lower()) + r"(?![a-z0-9])")


def _longest(text: str, field_name: str) -> AIVendor | None:
    text = " ".join((text or "").lower().split())
    if not text:
        return None
    best, size = None, 0
    for v in all_vendors():
        for p in getattr(v, field_name):
            if len(p) > size and _phrase(p).search(text):
                best, size = v, len(p)
    return best


def match_name(name: str | None) -> AIVendor | None:
    """An SSO app, OAuth client or licence name."""
    return _longest(name or "", "names")


def match_expense(text: str | None) -> AIVendor | None:
    """A card statement description or merchant name."""
    return _longest(text or "", "expense")


def normalise_domain(value: str | None) -> str:
    v = (value or "").strip().lower()
    if "://" in v:
        v = urlsplit(v).hostname or ""
    v = v.split("/", 1)[0].split(":", 1)[0].strip(".")
    return v


def match_domain(value: str | None) -> AIVendor | None:
    host = normalise_domain(value)
    if not host:
        return None
    best, size = None, 0
    for v in all_vendors():
        for d in v.domains:
            if (host == d or host.endswith("." + d)) and len(d) > size:
                best, size = v, len(d)
    return best


def for_attestation_value(value: str | None) -> AIVendor | None:
    return next((v for v in all_vendors() if value and value in v.attestation), None)
