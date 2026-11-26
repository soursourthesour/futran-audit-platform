"""Cross-tenant access on the real routes: tenant B's most powerful client user calls every route that takes an object
id, with the id of an object that belongs to tenant A (or to Futran). Expect 404 or 403, never 2xx.

Tenant A is ABC Corp (and the other demo clients where ABC has no object of a kind); tenant B is Meridian GmbH. The
attacker holds every org-wide client role at once: CAICO, Client Admin, Executive Sponsor and DPO. Objects come from the
full demo seed; the EU AI Act record, which the demo does not create, is added for ABC.

The same routes are called a second time as a Futran auditor who is on no engagement (spec §6 rule 7), with client
objects only.

A 422 from schema validation means the handler never ran: it is counted as inconclusive, not as a pass of the tenant
check. Bodies are built from the OpenAPI document so that as few requests as possible stop there. Any other answer
(400, 409, a 422 from the app itself) means the request reached business logic on another tenant's object.
"""
from __future__ import annotations

import re
from collections import Counter

import pytest
from sqlalchemy import inspect, select

from tests.security._allowlist import ALLOWLIST
from tests.security._bodies import fill_path, request_kwargs
from tests.security._routes import routes
from tests.security._world import World

PARAM = re.compile(r"\{(\w+)(?::\w+)?\}")
REFUSED = {403, 404}

# Values for parameters that name a kind, a code or a key rather than an object.
LITERALS = {
    "code": "3.1.01", "key": "notice", "kind": "licences", "ctype": "m365", "scope": "global", "section": "1", "role": "dpo",
    "step": "company", "domain": "governance", "week": "2026-11-16", "fmt": "pdf", "provider": "microsoft365", "action": "dismiss",
    "index": "0", "number": "3", "sub_section": "3.1",
}
# Path parameters that are not tenant objects for this check: public tokens and slugs, and the caller's own items.
SKIP_PARAMS = {"token", "slug", "notification_id", "alert_id"}

# (parameter, path fragment or None, model class name). The first rule whose fragment is in the path wins.
RULES: list[tuple[str, str | None, str]] = [
    ("client_id", "/admin/api/clients/", "ApiClient"),
    ("key_id", "/admin/website-keys/", "WebsiteApiKey"),
    ("client_id", None, "Organization"), ("org_id", None, "Organization"), ("entity_id", None, "Organization"),
    ("system_id", "/systems/{system_id}", "AISystem"), ("system_id", "/api/public/", "RegisterSystem"), ("system_id", None, "RegisterSystem"),
    ("sid", None, "RegisterSystem"),
    ("engagement_id", None, "Engagement"),
    ("item_id", "/governance/items/", "GovernanceItem"), ("item_id", "/remediation/", "RemediationItem"), ("item_id", "/roadmap-items/", "RoadmapItem"),
    ("item_id", "/trust/items/", "TrustCenterItem"), ("item_id", "/answer-library/", "AnswerLibraryItem"), ("item_id", "/questionnaires/", "QuestionnaireItem"),
    ("qid", "/questionnaires/", "Questionnaire"), ("qid", "/scoping/", "ScopingQuestionnaire"),
    ("uc_id", None, "UseCase"), ("finding_id", None, "Finding"), ("report_id", None, "Report"), ("so_id", None, "SignOff"), ("file_id", None, "FileObject"),
    ("send_id", "/mail/log/sends/", "MailSend"), ("send_id", "/alerts/sends/", "AlertSend"), ("send_id", "/scoping/sends/", "QuestionnaireSend"),
    ("policy_id", None, "PolicyDocument"),
    ("tool_id", "/tools/{tool_id}", "AITool"), ("tool_id", None, "DiscoveredTool"),
    ("user_id", None, "User"),
    ("assignment_id", "/roles/", "RoleAssignment"), ("assignment_id", None, "TrainingAssignment"),
    ("dept_id", None, "Department"), ("doc_id", None, "PackageDocument"),
    ("link_id", "/draft-findings/", "DraftFindingLink"), ("link_id", "/register/", "RegisterSystemLaw"), ("link_id", "/sales/proposals/", "ProposalLink"),
    ("named_user_id", None, "NamedUser"),
    ("vendor_id", "/model-catalogue/", "ModelVendor"), ("vendor_id", None, "Vendor"),
    ("request_id", "/system-requests/", "SystemAdditionRequest"), ("request_id", "/sales/approvals/", "ApprovalRequest"),
    ("req_id", "/document-requests/", "DocumentRequest"), ("req_id", "/evidence-requests/", "EvidenceRequest"),
    ("response_id", "/adequacy", "ManagementResponse"), ("response_id", None, "Response"),
    ("answer_id", None, "Attestation"), ("comment_id", None, "Comment"), ("hook_id", None, "Webhook"), ("sample_id", None, "AgentDecisionSample"),
    ("control_id", None, "SocControl"),
    ("group_id", None, "MailGroup"),
    ("member_id", "/mail/groups/", "MailGroupMember"), ("member_id", None, "CommitteeMember"),
    ("role_id", None, "GovernanceRoleAssignment"),
    ("entry_id", None, "HistoryEntry"), ("requirement_id", None, "Requirement"),
    ("incident_id", None, "Incident"), ("deadline_id", None, "IncidentDeadline"),
    ("run_id", "/bias-tests/", "BiasTestRun"), ("run_id", "/guardrail-tests/", "GuardrailTestRun"), ("run_id", "/assurance/runs/", "AssuranceRun"),
    ("run_id", "/admin/laws/refresh/", "LawRefreshRun"), ("run_id", "/billing-export/", "BillingExportRun"),
    ("interaction_id", None, "AIInteraction"), ("rule_id", None, "AlertRule"), ("letter_id", None, "IntroLetter"), ("regulation_id", None, "Regulation"),
    ("law_id", None, "Regulation"), ("geo_id", None, "ClientGeography"), ("pid", None, "ImpactAssessment"), ("cid", None, "ImpactCondition"),
    ("tid", None, "ReassessmentTrigger"), ("result_id", None, "MonitorResult"), ("obligation_id", None, "Obligation"), ("sub_id", None, "AddonSubscription"),
    ("uid", None, "RegulatoryUpdate"), ("change_id", None, "ProposedChange"), ("pc_id", None, "ProposedChange"),
    ("import_id", "/catalog/imports/", "CatalogImport"), ("import_id", None, "DiscoveryImport"),
    ("opp_id", None, "Opportunity"), ("contact_id", None, "OpportunityContact"), ("activity_id", None, "OpportunityActivity"),
    ("proposal_id", "/model-catalogue/", "ModelProposal"), ("proposal_id", None, "Proposal"), ("line_id", None, "ProposalLine"),
    ("estimate_id", None, "Estimate"), ("co_id", None, "ChangeOrder"), ("hold_id", None, "LegalHold"), ("partner_id", None, "Partner"),
    ("commission_id", None, "Commission"), ("retainer_id", None, "Retainer"), ("version_id", None, "ServiceTemplateVersion"),
    ("template_id", "/service-templates/", "ServiceTemplate"), ("template_id", None, "MailTemplate"), ("package_id", None, "PackageTemplate"),
    ("suggestion_id", None, "PriceSuggestion"), ("model_id", None, "ModelEntry"), ("preview_id", None, "LawImportPreview"),
    ("wave_id", None, "CopilotWave"), ("site_id", None, "CopilotSite"), ("case_id", None, "Case"),
]
# Body fields whose rule is a validator, not part of the schema: give them a value the validator accepts.
FIELD_VALUES = {"to": ["someone@example.test"], "kind": "note", "decision": "approve", "action": "approve"}
ATTACKERS = ["client superuser", "unassigned auditor"]

# The kinds the brief names, each of which must be covered by at least one resolved route call.
MUST_COVER = {"UseCase", "RegisterSystem", "FileObject", "Finding", "Report", "SignOff", "MailSend", "EuAiActRecord", "EngagementTeam"}
METHOD_ORDER = {"GET": 0, "PUT": 1, "PATCH": 2, "POST": 3, "DELETE": 4}


def _rule(param: str, path: str) -> str | None:
    for p, frag, model in RULES:
        if p == param and (frag is None or frag in path):
            return model
    return None


def _id_routes():
    out = []
    for r in routes():
        params = PARAM.findall(r.path)
        if not params or r.key in ALLOWLIST or r.path.startswith("/api/v1/me/") or r.path.startswith("/api/public/"):
            continue
        if any(p in SKIP_PARAMS for p in params) or all(p in LITERALS for p in params):
            continue
        out.append(r)
    out.sort(key=lambda r: (METHOD_ORDER.get(r.method, 9), r.path))
    return out


@pytest.fixture(scope="module")
def xt(tmp_path_factory):
    from app.core.models import Base
    from app.tenancy.models import Organization
    from tests.factories import make_user

    w = World(str(tmp_path_factory.mktemp("files")))
    db = w.db
    orgs = {o.name: o for o in db.scalars(select(Organization))}
    abc, mer = orgs["ABC Corp"], orgs["Meridian GmbH"]
    futran = next(o for o in orgs.values() if o.type == "futran")
    attackers = {
        "client superuser": make_user(db, mer, roles=["caico", "client_admin", "exec_sponsor", "dpo"], name="Meridian Superuser", email="superuser@meridian.example"),
        # spec §6 rule 7: an auditor sees only assigned engagements
        "unassigned auditor": make_user(db, futran, roles=["auditor"], name="Unassigned Auditor", email="unassigned.auditor@futran.test"),
    }
    _add_eu_record(db, abc)
    db.commit()
    models = {}
    for m in Base.registry.mappers:
        models.setdefault(m.class_.__name__, m.class_)
    w.ctx = {"abc": abc, "mer": mer, "futran": futran, "attackers": attackers, "current": None, "models": models, "picked": {}, "tally": Counter(), "covered": set()}
    yield w
    t = w.ctx["tally"]
    print(f"\ncross-tenant route calls: {sum(t.values())} {dict(t)}; kinds covered: {sorted(w.ctx['covered'])}")
    w.close()


def _add_eu_record(db, abc):
    from app.euaiact.models import EuAiActRecord
    from app.register.models import RegisterSystem

    s = db.scalar(select(RegisterSystem).where(RegisterSystem.organization_id == abc.id, RegisterSystem.deleted_at.is_(None)).limit(1))
    if db.scalar(select(EuAiActRecord).where(EuAiActRecord.register_system_id == s.id)) is None:
        db.add(EuAiActRecord(organization_id=abc.id, register_system_id=s.id, role="deployer", classification="high_risk_annex_iii", annex_iii_area="employment",
                             reasoning="Ranks job applicants.", obligations={}, annex_iv={}, fria={}))


def _pick(xt, model_name: str):
    """An id of `model_name` that tenant B must not reach: ABC's first, then any other non-Meridian owner's."""
    ctx = xt.ctx
    if model_name in ctx["picked"]:
        return ctx["picked"][model_name]
    abc, mer = ctx["abc"].id, ctx["mer"].id
    if model_name == "Organization":
        ctx["picked"][model_name] = (abc, "tenant")
        return ctx["picked"][model_name]
    model = ctx["models"].get(model_name)
    value = None
    if model is not None:
        cols = {c.key for c in inspect(model).columns}
        live = [model.deleted_at.is_(None)] if "deleted_at" in cols else []
        pk = inspect(model).primary_key[0]
        if "organization_id" in cols:
            for where, kind in ((model.organization_id == abc, "tenant"), (model.organization_id.not_in([mer, ctx["futran"].id]), "tenant"),
                                (model.organization_id != mer, "futran")):
                v = xt.db.scalar(select(pk).where(where, *live).limit(1))
                if v is not None:
                    value = (v, kind)
                    break
        else:
            v = xt.db.scalar(select(pk).where(*live).limit(1))
            value = (v, "futran") if v is not None else None
    ctx["picked"][model_name] = value
    return value


XFAIL: dict = {}  # Y06 (client mail status for an unassigned auditor) was fixed on 25 Nov


def _cases():
    out = []
    for r in _id_routes():
        for a in ATTACKERS:
            reason = XFAIL.get((r.key, a))
            out.append(pytest.param(r, a, id=f"{r.key} [{a}]", marks=[pytest.mark.xfail(strict=True, reason=reason)] if reason else []))
    return out


@pytest.mark.parametrize("route,attacker", _cases())
def test_tenant_b_cannot_reach_tenant_a_objects(xt, route, attacker):
    """Client superuser: every object. Unassigned auditor: client objects only (Futran-wide records are theirs to see)."""
    if xt.ctx["current"] != attacker:
        xt.login(xt.ctx["attackers"][attacker])
        xt.ctx["current"] = attacker
    values, kinds = {}, set()
    for p in PARAM.findall(route.path):
        if p in LITERALS:
            values[p] = LITERALS[p]
            continue
        model = _rule(p, route.path)
        got = _pick(xt, model) if model else None
        if got is None:
            xt.ctx["tally"]["unresolved"] += 1
            pytest.skip(f"no object for {{{p}}} ({model or 'no rule'}) in the demo world")
        values[p] = got[0]
        kinds.add(got[1])
        xt.ctx["covered"].add(model)
    if "/eu-ai-act/systems/" in route.path:
        xt.ctx["covered"].add("EuAiActRecord")
    if route.path.endswith("/team"):
        xt.ctx["covered"].add("EngagementTeam")
    if attacker == "unassigned auditor" and "tenant" not in kinds:
        pytest.skip("Futran-owned object: not a cross-tenant case for Futran staff")
    url = fill_path(route.path, values)
    kw = request_kwargs(route.path, route.method)
    if isinstance(kw.get("json"), dict):
        kw["json"] = {k: FIELD_VALUES.get(k, v) for k, v in kw["json"].items()}
    r = xt.client.request(route.method, url, **kw)
    assert r.status_code != 401, "the attacker's session was lost"
    if r.status_code == 422 and r.headers.get("x-schema-validation"):
        xt.ctx["tally"]["inconclusive (schema 422)"] += 1
        pytest.skip(f"schema validation stopped the request before the handler: {r.text[:160]}")
    owner = "tenant" if "tenant" in kinds else "futran"
    xt.ctx["tally"][f"{attacker}: checked ({owner} object)"] += 1
    assert r.status_code in REFUSED, f"{route.method} {url} as {attacker} on {owner} data → {r.status_code}: {r.text[:240]}"


def test_coverage(xt):
    """Runs after the parametrised test in this module: the named kinds were all exercised."""
    missing = MUST_COVER - xt.ctx["covered"]
    assert not missing, f"no cross-tenant call reached these kinds: {sorted(missing)}"
    assert xt.ctx["tally"]["client superuser: checked (tenant object)"] >= 250
    assert xt.ctx["tally"]["unassigned auditor: checked (tenant object)"] >= 250
