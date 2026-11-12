"""EU AI Act rules for the G-08 workspace, read from `seeds/eu_ai_act.yaml` so dates and articles can be changed
without code: deadlines by classification, the obligations that apply to a role and classification, the FRIA
condition of Art. 27(1), and article references used to match rows in the law library."""
from __future__ import annotations

import re
from datetime import date
from functools import lru_cache

import yaml

from app.core.clock import today as _today
from app.laws.importer import SEEDS

DATA_FILE = SEEDS / "eu_ai_act.yaml"
HIGH_RISK = ("high_risk_annex_iii", "high_risk_annex_i")


@lru_cache(maxsize=1)
def _load() -> dict:
    return yaml.safe_load(DATA_FILE.read_text(encoding="utf-8"))


def data() -> dict:
    return _load()


def roles() -> dict[str, str]:
    return data()["roles"]


def classifications() -> dict[str, str]:
    return data()["classifications"]


def areas() -> dict[str, dict]:
    return data()["annex_iii_areas"]


def _date(v) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def fmt(d: date | None) -> str:
    return f"{d.day} {d.strftime('%b %Y')}" if d else "—"


def deadline_for(classification: str | None, today: date | None = None) -> dict:
    """{"date", "label", "in_force", "source"} for a classification. "In force" once the date has passed."""
    spec = (data()["deadlines"] or {}).get(classification or "")
    if not spec:
        return {"date": None, "label": "—", "in_force": False, "source": None}
    d = _date(spec.get("date"))
    now = today or _today()
    in_force = d is not None and d <= now
    return {"date": d, "label": "In force" if in_force else fmt(d), "in_force": in_force, "source": spec.get("source")}


def fria_required(role: str | None, also_deployer: bool, classification: str | None, area: str | None, public_service: bool) -> bool:
    """Art. 27(1): deployers of Annex III high-risk systems that are public bodies or provide public services, and any
    deployer of a credit-scoring or life and health insurance system; never for critical infrastructure (point 2)."""
    deploys = role == "deployer" or bool(also_deployer)
    if not deploys or classification != "high_risk_annex_iii":
        return False
    a = areas().get(area or "", {})
    if a.get("no_fria"):
        return False
    return bool(public_service) or bool(a.get("fria"))


def _matches(when: dict, role: str, classification: str) -> bool:
    rs, cs = when.get("roles"), when.get("classifications")
    return (rs == "all" or role in (rs or [])) and (cs == "all" or classification in (cs or []))


def applicable(role: str | None, classification: str | None, *, also_deployer: bool = False, fria: bool = False) -> list[dict]:
    """The obligations that apply, in the data file's order. A provider marked "also uses it" takes the deployer duties
    as well; the FRIA (Art. 27) only when `fria` is true."""
    if not role or not classification:
        return []
    acting = [role] + (["deployer"] if also_deployer and role != "deployer" else [])
    out = []
    for o in data()["obligations"]:
        if o.get("fria") and not fria:
            continue
        if any(_matches(o.get("when") or {}, r, classification) for r in acting):
            out.append(o)
    return out


_AMENDED = re.compile(r"\(as amended[^)]*\)", re.I)
_REF = re.compile(r"(?<![\d/(])(\d{1,3})(?!\d)((?:\([0-9a-z]+\))*)")


def article_refs(citation: str | None) -> list[str]:
    """Article references in a citation: "EU AI Act Art. 14, 26(2)" → ["14", "26(2)"]. A range "50(3)–(4)" keeps its
    first paragraph; numbers after "Annex" or inside "(as amended …)" are not articles."""
    if not citation:
        return []
    text = _AMENDED.sub("", citation)
    m = re.search(r"\bArt(?:icle)?s?\.?\s*", text)
    if not m:
        return []
    text = re.split(r"\bAnnex\b", text[m.end():])[0]
    return [n + p for n, p in _REF.findall(text)]


def covers(existing: str, ref: str) -> bool:
    """Whether a library row citing `existing` covers the obligation `ref`: the same reference, a paragraph of the
    article asked for, or the whole article the paragraph belongs to."""
    return existing == ref or existing.startswith(ref + "(") or ref.startswith(existing + "(")
