"""Screens 35 (heat map and lineage) and 34 (benchmarking and practice insights)."""
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response as HttpResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import NotFound
from app.engagements.models import Engagement
from app.findings.models import Finding
from app.insights import benchmark, heatmap, lineage, render
from app.insights import register  # noqa: F401  report appendices and the sign-off 7 snapshot
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.systems.service import get_system
from app.tenancy.models import Organization
from app.tenancy.people import current_engagement

router = APIRouter(tags=["insights"])


class ConsentIn(BaseModel):
    consent: bool
    note: str | None = None


def _engagement(db: Session, actor: Actor, client_id: str, engagement_id: str | None) -> Engagement:
    org = db.get(Organization, client_id)
    if org is None or org.type != "client" or org.deleted_at is not None:
        raise NotFound()
    e = db.get(Engagement, engagement_id) if engagement_id else current_engagement(db, org)
    if e is None or e.client_id != org.id:
        raise NotFound()
    authorize(db, actor, Action.VIEW_HEATMAP, engagement_id=e.id)
    return e


def _heatmap(db: Session, actor: Actor, client_id: str, engagement_id, department, build_type, framework) -> dict:
    e = _engagement(db, actor, client_id, engagement_id)
    out = heatmap.build(db, e, department=department or None, build_type=build_type or None, framework=framework or None)
    org = db.get(Organization, client_id)
    out["client"] = {"id": org.id, "name": org.name}
    out["findings"] = [{"id": f.id, "ref": f.ref, "title": f.title, "severity": f.severity, "status": f.status}
                       for f in db.query(Finding).filter(Finding.engagement_id == e.id, Finding.deleted_at.is_(None)).order_by(Finding.ref)]
    return out


@router.get("/clients/{client_id}/heatmap")
def get_heatmap(client_id: str, engagement_id: str | None = None, department: str | None = None, build_type: str | None = None, framework: str | None = None,
                actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return _heatmap(db, actor, client_id, engagement_id, department, build_type, framework)


@router.get("/clients/{client_id}/heatmap.svg")
def get_heatmap_svg(client_id: str, engagement_id: str | None = None, department: str | None = None, build_type: str | None = None,
                    actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    data = _heatmap(db, actor, client_id, engagement_id, department, build_type, None)
    return HttpResponse(render.to_svg(data), media_type="image/svg+xml", headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})


@router.get("/clients/{client_id}/heatmap.png")
def get_heatmap_png(client_id: str, engagement_id: str | None = None, department: str | None = None, build_type: str | None = None,
                    actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    data = _heatmap(db, actor, client_id, engagement_id, department, build_type, None)
    name = f"{data['engagement']['audit_ref'] or 'engagement'} risk heat map.png".replace("/", "-")
    return HttpResponse(render.to_png(data), media_type="image/png", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/findings/{finding_id}/lineage")
def get_lineage(finding_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    f = db.get(Finding, finding_id)
    if f is None or f.deleted_at is not None:
        raise NotFound()
    authorize(db, actor, Action.VIEW_HEATMAP, engagement_id=f.engagement_id)
    return lineage.finding_lineage(db, f)


@router.get("/systems/{system_id}/lineage/control/{code}")
def get_control_proof(system_id: str, code: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = get_system(db, system_id)
    authorize(db, actor, Action.VIEW_HEATMAP, engagement_id=s.engagement_id)
    return lineage.control_proof(db, s, code)


# ---- benchmarking (screen 34)
@router.get("/insights/clients")
def insight_clients(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    if not actor.is_futran:
        raise NotFound()
    authorize(db, actor, Action.VIEW_BENCHMARKS)
    return {"clients": benchmark.clients_with_snapshots(db), "min_peers": benchmark.MIN_PEERS}


@router.get("/insights/clients/{client_id}")
def insight_client(client_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    if not actor.is_futran:
        raise NotFound()
    org = db.get(Organization, client_id)
    if org is None or org.type != "client":
        raise NotFound()
    authorize(db, actor, Action.VIEW_BENCHMARKS, org_id=org.id)
    return benchmark.comparison(db, org, test_mode=request.app.state.settings.test_mode)


@router.get("/insights/clients/{client_id}/page.pdf")
def insight_page(client_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """The comparison as a page the Chief Auditor can share with that client."""
    from app.documents.pdf import to_pdf

    data = insight_client(client_id, request, actor, db)
    md = benchmark_markdown(data)
    name = f"{data['client']['name']} benchmark.pdf".replace("/", "-").replace('"', "")
    audit.record(db, actor_id=actor.id, action="benchmark.page", organization_id=client_id, object_type="Organization", object_id=client_id, summary=f"Exported the benchmark page for {data['client']['name']}")
    return HttpResponse(to_pdf(md, "Benchmark against peers", {"audit_ref": data["client"]["name"]}), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


def benchmark_markdown(data: dict) -> str:
    g = data["group"]
    lines = [f"# {data['client']['name']}: AI governance maturity against peers", ""]
    if g is None:
        lines += [data.get("note") or "No peer figure is available yet.", ""]
    else:
        lines += [f"Peer group: {g['label']} ({g['n']} clients). Each peer figure is the median of clients who agreed to benchmarking; no client is named "
                  "and a figure is shown only for groups of at least five. Scores are control maturity on a 1 to 5 scale.", "",
                  "| Domain | Your score | Peer median |", "|---|---|---|"]
        for d in data["domains"]:
            lines.append(f"| {d['label']} | {d['client'] if d['client'] is not None else 'Not scored'} | {d['peer_median'] if d['peer_median'] is not None else 'Not enough peers'} |")
        lines.append(f"| Overall maturity | {data['overall']['client']} | {data['overall']['peer_median'] if data['overall']['peer_median'] is not None else 'Not enough peers'} |")
    return "\n".join(lines) + "\n"


@router.put("/insights/clients/{client_id}/consent")
def put_consent(client_id: str, body: ConsentIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = db.get(Organization, client_id)
    if org is None or org.type != "client":
        raise NotFound()
    authorize(db, actor, Action.SET_BENCHMARK_CONSENT, org_id=org.id)
    before = org.benchmark_consent
    org.benchmark_consent = body.consent
    note = " ".join(str(body.note or "").split())[:500] or None
    audit.record(db, actor_id=actor.id, action="benchmark.consent", obj=org, before={"consent": before}, after={"consent": body.consent, "note": note},
                 summary=f"Recorded that {org.name} {'consents' if body.consent else 'does not consent'} to benchmarking")
    return {"consent": org.benchmark_consent}


@router.get("/insights/practice")
def practice(request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    if not actor.is_futran:
        raise NotFound()
    authorize(db, actor, Action.VIEW_PRACTICE_INSIGHTS)
    return benchmark.practice(db, test_mode=request.app.state.settings.test_mode)
