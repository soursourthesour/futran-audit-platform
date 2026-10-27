"""Every route that takes an object id refuses a client user from another tenant (plan Task 33).

The demo creates ABC Corp (completed) and Meridian GmbH. Meridian's CAICO calls every id-bearing route with ABC's real
ids, using the registry below to pick the right object for each path parameter. None may succeed or reach business
logic (a 409 or 400 would mean the request got past the tenant check)."""
import re

import pytest
from sqlalchemy import select

from tests.factories import login_as

ALLOWED = {401, 403, 404, 405, 422}
LITERALS = {"code": "3.1.01", "domain": "governance", "number": "5", "role": "dpo", "step": "company", "sub_section": "3.1", "key": "notice"}
SKIP_PARAMS = {"token", "preview_id", "run_id", "law_id", "notification_id"}  # public tokens, Futran-only admin objects, the caller's own notifications


def _ids(db, abc_org_id: str) -> dict:
    """Factories: (path prefix, parameter) → an ABC object id."""
    from app.attestation.models import Attestation, AttestationCampaign  # noqa: F401
    from app.docrequests.models import DocumentRequest, EvidenceRequest
    from app.engagements.models import Engagement
    from app.files.models import FileObject
    from app.findings.models import DraftFindingLink, Finding
    from app.governance.models import GovernanceItem
    from app.initiation.models import PackageDocument
    from app.inventory.models import AITool, NamedUser, UseCase
    from app.questionnaire.models import Response
    from app.remediation.models import ManagementResponse, RemediationItem
    from app.reports.models import Report, RoadmapItem
    from app.signoffs.models import SignOff
    from app.systems.models import AISystem, SystemAdditionRequest, Vendor
    from app.tenancy.models import Department, RoleAssignment, User

    def one(model, *where):
        return db.scalar(select(model.id).where(*where).limit(1))

    e = db.scalar(select(Engagement).where(Engagement.client_id == abc_org_id, Engagement.status == "completed"))
    org = (lambda m: m.organization_id == abc_org_id)
    return {
        "client_id": abc_org_id, "engagement_id": e.id, "dept_id": one(Department, org(Department)), "user_id": one(User, org(User)),
        "assignment_id": one(RoleAssignment, org(RoleAssignment)), "doc_id": one(PackageDocument, org(PackageDocument)),
        "file_id": one(FileObject, org(FileObject)), "finding_id": one(Finding, org(Finding)), "link_id": one(DraftFindingLink, org(DraftFindingLink)),
        "named_user_id": one(NamedUser, org(NamedUser)), "report_id": one(Report, org(Report)), "so_id": one(SignOff, org(SignOff)),
        "system_id": one(AISystem, org(AISystem)), "tool_id": one(AITool, org(AITool)), "uc_id": one(UseCase, org(UseCase)), "vendor_id": one(Vendor, org(Vendor)),
        "request_id": one(SystemAdditionRequest, org(SystemAdditionRequest)),
        "answer_id": one(Attestation, org(Attestation)),
        ("/governance/items", "item_id"): one(GovernanceItem, org(GovernanceItem)),
        ("/remediation", "item_id"): one(RemediationItem, org(RemediationItem)),
        ("/roadmap-items", "item_id"): one(RoadmapItem, org(RoadmapItem)),
        ("/document-requests", "req_id"): one(DocumentRequest, org(DocumentRequest)),
        ("/evidence-requests", "req_id"): one(EvidenceRequest, org(EvidenceRequest)),
        ("adequacy", "response_id"): one(ManagementResponse, org(ManagementResponse)),
        ("verify", "response_id"): one(Response, org(Response)),
    }


def _resolve(ids: dict, path: str, param: str):
    if param in LITERALS:
        return LITERALS[param]
    for key, value in ids.items():
        if isinstance(key, tuple) and key[1] == param and key[0] in path:
            return value
    return ids.get(param)


@pytest.fixture
def demo(client, db, matrix, settings, tmp_path):
    from app.demo.seed_demo import run
    from app.reference import LOADERS

    settings.file_store = f"local:{tmp_path}"
    client.app.state.settings = settings
    for name, loader in LOADERS:
        if name != "Law matrix" and not name.startswith("Jurisdictions"):
            loader(db)
    db.commit()
    return run(db, settings, client=client)


def test_cross_tenant_routes_refused(client, db, demo):
    from app.tenancy.models import User

    ids = _ids(db, demo["abc"])
    katrin = db.scalar(select(User).where(User.email == "katrin.vogel@meridian.example"))
    login_as(client, db, katrin)
    paths = client.app.openapi()["paths"]
    tested, leaks, unresolved = 0, [], set()
    for path, ops in paths.items():
        params = re.findall(r"\{(\w+)\}", path)
        if not params or any(p in SKIP_PARAMS for p in params) or path.startswith("/api/v1/me/"):  # /me routes act on the caller's own data
            continue
        values = {p: _resolve(ids, path, p) for p in params}
        if any(v is None for v in values.values()):
            unresolved.update(p for p, v in values.items() if v is None)
            continue
        url = path.replace("/api/v1", "", 1)
        for p, v in values.items():
            url = url.replace("{" + p + "}", str(v))
        for method in ops:
            r = client.request(method.upper(), f"/api/v1{url}", json={} if method != "get" else None)
            tested += 1
            if r.status_code not in ALLOWED:
                leaks.append(f"{method.upper()} {path} → {r.status_code}: {r.text[:120]}")
    assert leaks == []
    print(f"checked {tested} cross-tenant route calls")
    assert tested >= 100, f"only {tested} route calls were checked; unresolved parameters: {sorted(unresolved)}"
