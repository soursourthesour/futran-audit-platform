"""Cross-client benchmarking (spec §21 F15, screen 34).

- A snapshot is taken from each engagement when its final report is signed (sign-off 7): the engagement scorecard's
  domain scores, overall maturity and rating, the client's industry and size band, its consent (Organization.
  benchmark_consent, recorded from the engagement letter) and the themes of its approved findings.
- A peer figure is the median of the latest snapshot of each other consenting client in the group, and is shown only when
  the group has at least five such clients. Groups are tried from the most specific: industry and size band, industry,
  size band, all consenting clients.
- No output names a peer, gives a peer's own score or an identifier. The client's own figures are shown only in that
  client's comparison (Chief Auditor). The practice view counts themes across consenting clients, also only from five.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engagements.models import Engagement
from app.engagements.wizard import INDUSTRIES
from app.findings.models import Finding
from app.insights.models import BenchmarkSnapshot
from app.scoring import engine
from app.tenancy.models import Organization

MIN_PEERS = 5
THEMES = Path(__file__).with_name("themes.yaml")


def median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


@lru_cache(maxsize=1)
def themes() -> list[dict]:
    return yaml.safe_load(THEMES.read_text())["themes"]


def theme_of(f: Finding) -> str | None:
    title = (f.title or "").casefold()
    for t in themes():
        if any(q.startswith(p) for q in f.source_question_ids or [] for p in t.get("questions", [])):
            return t["code"]
        sec = f.template_section or ""
        if any(sec == p or sec.startswith(p + ".") for p in t.get("sections", [])):
            return t["code"]
        if any(w in title for w in t.get("words", [])):
            return t["code"]
    return None


def band_label(band: str | None) -> str:
    return f"{(band or '').replace('-', '–')} employees" if band else "Size not recorded"


def record_snapshot(db: Session, e: Engagement) -> BenchmarkSnapshot:
    from app.core.clock import utcnow
    from app.scoring.service import engagement_rollup

    org = db.get(Organization, e.client_id)
    sc = engagement_rollup(db, e)
    found = db.scalars(select(Finding).where(Finding.engagement_id == e.id, Finding.deleted_at.is_(None), Finding.status == "approved"))
    th = sorted({t for t in (theme_of(f) for f in found) if t})
    snap = db.scalar(select(BenchmarkSnapshot).where(BenchmarkSnapshot.engagement_id == e.id))
    if snap is None:
        snap = BenchmarkSnapshot(organization_id=e.client_id, engagement_id=e.id)
        db.add(snap)
    snap.industry, snap.size_band, snap.consent = org.industry, org.employee_band, bool(org.benchmark_consent)
    snap.domain_scores, snap.overall_maturity, snap.overall_rating = dict(sc.domain_scores or {}), sc.overall_maturity, sc.overall_rating
    snap.finding_themes, snap.period_end, snap.signed_at = th, e.period_end, utcnow()
    db.flush()
    return snap


def snapshot_on_signoff(db: Session, settings, actor, so) -> None:
    """Sign-off 7 (final report) approved: recompute the engagement's snapshot."""
    record_snapshot(db, db.get(Engagement, so.engagement_id))


def _latest_by_client(db: Session) -> dict[str, BenchmarkSnapshot]:
    """Each client's latest snapshot, with consent read from the organization now (withdrawn consent stops counting)."""
    out: dict[str, BenchmarkSnapshot] = {}
    for s in db.scalars(select(BenchmarkSnapshot).where(BenchmarkSnapshot.deleted_at.is_(None)).order_by(BenchmarkSnapshot.created_at)):
        out[s.organization_id] = s
    consent = dict(db.execute(select(Organization.id, Organization.benchmark_consent).where(Organization.id.in_(list(out)))).all()) if out else {}
    return {k: v for k, v in out.items() if consent.get(k) is True}


def _domains(db: Session) -> dict[str, str]:
    from app.scoring.service import methodology

    try:
        return dict(methodology(db).domains)
    except Exception:  # no methodology loaded yet
        from app.scoring.service import SECTION_DOMAIN

        return {d: d for d in dict.fromkeys(SECTION_DOMAIN.values())}


def comparison(db: Session, org: Organization) -> dict:
    domains = _domains(db)
    own = db.scalar(select(BenchmarkSnapshot).where(BenchmarkSnapshot.organization_id == org.id, BenchmarkSnapshot.deleted_at.is_(None)).order_by(BenchmarkSnapshot.created_at.desc()).limit(1))
    base = {"client": {"id": org.id, "name": org.name, "industry": INDUSTRIES.get(org.industry or "", org.industry), "size_band": band_label(org.employee_band), "consent": org.benchmark_consent},
            "min_peers": MIN_PEERS, "group": None, "groups_considered": [], "note": None,
            "domains": [{"key": k, "label": v, "client": (own.domain_scores or {}).get(k) if own else None, "peer_median": None, "below_peers": False} for k, v in domains.items()],
            "overall": {"client": own.overall_maturity if own else None, "peer_median": None}}
    if org.benchmark_consent is not True:
        base["note"] = "This client has not consented to benchmarking in its engagement letter, so it is not compared with peers."
        return base
    if own is None:
        base["note"] = "This client has no signed report yet. Figures appear after the final report is signed."
        return base
    peers = [s for k, s in _latest_by_client(db).items() if k != org.id]
    ind = INDUSTRIES.get(org.industry or "", org.industry or "Industry not recorded")
    groups = [(f"{ind}, {band_label(org.employee_band)}", lambda s: s.industry == org.industry and s.size_band == org.employee_band),
              (ind, lambda s: s.industry == org.industry), (band_label(org.employee_band), lambda s: s.size_band == org.employee_band), ("All consenting clients", lambda s: True)]
    chosen = None
    for label, match in groups:
        members = [s for s in peers if match(s)]
        shown = chosen is None and len(members) >= MIN_PEERS
        base["groups_considered"].append({"label": label, "n": len(members), "shown": shown})
        if shown:
            chosen = (label, members)
    if chosen is None:
        base["note"] = f"No peer group has {MIN_PEERS} consenting clients yet, so no peer figure is shown."
        return base
    label, members = chosen
    base["group"] = {"label": label, "n": len(members)}
    for d in base["domains"]:
        vals = [s.domain_scores[d["key"]] for s in members if (s.domain_scores or {}).get(d["key"]) is not None]
        if len(vals) >= MIN_PEERS:
            d["peer_median"] = engine.r1(median(vals))
            d["below_peers"] = d["client"] is not None and d["client"] < d["peer_median"]
    vals = [s.overall_maturity for s in members if s.overall_maturity is not None]
    base["overall"]["peer_median"] = engine.r2(median(vals)) if len(vals) >= MIN_PEERS else None
    return base


def practice(db: Session) -> dict:
    """Most common finding themes across consenting clients and the service each leads to. No names, no scores."""
    snaps = list(_latest_by_client(db).values())
    out = {"clients": len(snaps), "min_clients": MIN_PEERS, "themes": [], "note": None}
    if len(snaps) < MIN_PEERS:
        out["note"] = f"Shown when at least {MIN_PEERS} clients have consented to benchmarking."
        return out
    counts = {t["code"]: sum(1 for s in snaps if t["code"] in (s.finding_themes or [])) for t in themes()}
    out["themes"] = [{"code": t["code"], "label": t["label"], "service": t["service"], "clients": counts[t["code"]]} for t in sorted(themes(), key=lambda t: -counts[t["code"]]) if counts[t["code"]]]
    return out


def clients_with_snapshots(db: Session) -> list[dict]:
    """For the Chief Auditor's client picker."""
    ids = list(dict.fromkeys(db.scalars(select(BenchmarkSnapshot.organization_id).where(BenchmarkSnapshot.deleted_at.is_(None)))))
    orgs = db.scalars(select(Organization).where(Organization.id.in_(ids), Organization.type == "client", Organization.deleted_at.is_(None)).order_by(Organization.name)) if ids else []
    return [{"id": o.id, "name": o.name, "consent": o.benchmark_consent} for o in orgs]
