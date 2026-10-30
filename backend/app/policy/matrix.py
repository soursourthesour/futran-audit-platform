"""Permission matrix — spec §5, plus v0.2 actions and schematic §8a.

Scopes:
  ALL       Futran: any engagement / tenant.
  ASSIGNED  Futran: only engagements where the user is on the engagement team.
  ORG       Client: own organization.
  DEPT      Client: own department (role assignment scoped to that department).
  SYSTEM    Client: one AI system (role assignment scoped to that system), or own department.
"""
from enum import StrEnum

from app.policy.actions import Action as A
from app.policy.roles import Role as R


class Scope(StrEnum):
    ALL = "all"
    ASSIGNED = "assigned"
    ORG = "org"
    DEPT = "dept"
    SYSTEM = "system"
    NONE = "none"


S = Scope

_FUTRAN_TEAM_VIEW = {
    A.VIEW_ENGAGEMENT: S.ASSIGNED,
    A.VIEW_CLIENT_USERS: S.ASSIGNED,
    A.VIEW_INVENTORY: S.ASSIGNED,
    A.VIEW_GOVERNANCE: S.ASSIGNED,
    A.VIEW_EVIDENCE: S.ASSIGNED,
    A.VIEW_SCORES: S.ASSIGNED,
    A.VIEW_FINAL_REPORT: S.ASSIGNED,
    A.VIEW_FINDINGS_RESPONSES: S.ASSIGNED,
    A.VIEW_ATTESTATION_AGGREGATES: S.ASSIGNED,
    A.VIEW_REGISTER: S.ASSIGNED,  # read-only, beside the audit system it feeds
}

MATRIX: dict[R, dict[A, S]] = {
    R.CHIEF_AUDITOR: {
        A.VIEW_FUTRAN_USERS: S.ALL,
        A.APPROVE_ENGAGEMENT: S.ALL,
        A.CREATE_CLIENT_ENGAGEMENT: S.ALL,
        A.VIEW_ENGAGEMENT: S.ALL,
        A.ASSIGN_AUDITORS: S.ALL,
        A.VIEW_CLIENT_USERS: S.ALL,
        A.APPROVE_TEMPLATES: S.ALL,
        A.VIEW_INVENTORY: S.ALL,
        A.OVERRIDE_FINAL_TIER: S.ALL,
        A.VIEW_INDIVIDUAL_ATTESTATIONS: S.ALL,
        A.VIEW_ATTESTATION_AGGREGATES: S.ALL,
        A.VIEW_GOVERNANCE: S.ALL,
        A.VIEW_EVIDENCE: S.ALL,
        A.RECORD_FINDINGS: S.ALL,  # spec §6 rule 2: Chief-Auditor-authored findings route to the QA Reviewer
        A.APPROVE_FINDINGS: S.ALL,
        A.SIGN_FINAL_REPORT: S.ALL,
        A.VIEW_FINAL_REPORT: S.ALL,
        A.VIEW_FINDINGS_RESPONSES: S.ALL,
        A.CLOSE_REMEDIATION: S.ALL,
        A.VIEW_AUDIT_LOG: S.ALL,
        A.VERIFY_SYSTEM_ANSWERS: S.ALL,
        A.SCORE_SYSTEM: S.ALL,
        A.VIEW_SCORES: S.ALL,
        A.MANAGE_DOCUMENT_REQUESTS: S.ALL,
        A.SIGN_DECLARATION: S.ALL,
        A.MANAGE_SYSTEMS: S.ALL,
        A.ADVANCE_STAGE: S.ALL,
        A.VIEW_REGISTER: S.ALL,
        # regulatory master (§25.7)
        A.VIEW_REG_MASTER: S.ALL,
        A.PROPOSE_REG_CHANGE: S.ALL,
        A.APPROVE_REG_CHANGE: S.ALL,
        A.MANAGE_REG_TRACKING: S.ALL,
        A.VIEW_APPLICABILITY: S.ALL,
        A.EDIT_APPLICABILITY: S.ALL,
        A.APPROVE_INTRO_LETTER: S.ALL,
    },
    R.ADMIN: {
        A.MANAGE_FUTRAN_USERS: S.ALL,
        A.VIEW_FUTRAN_USERS: S.ALL,
        A.CREATE_CLIENT_ENGAGEMENT: S.ALL,
        A.VIEW_ENGAGEMENT: S.ALL,
        A.MANAGE_CLIENT_USERS: S.ALL,
        A.VIEW_CLIENT_USERS: S.ALL,
        A.CONFIGURE_TEMPLATES: S.ALL,
        A.VIEW_AUDIT_LOG: S.ALL,
        A.MANAGE_REFERENCE_DATA: S.ALL,
        A.RUN_LAW_REFRESH: S.ALL,
        # regulatory master (§25.7): edits become proposals the Chief Auditor approves
        A.VIEW_REG_MASTER: S.ALL,
        A.PROPOSE_REG_CHANGE: S.ALL,
        A.MANAGE_REG_TRACKING: S.ALL,
        A.VIEW_APPLICABILITY: S.ALL,
        A.EDIT_APPLICABILITY: S.ALL,
    },
    R.AUDITOR: {
        **_FUTRAN_TEAM_VIEW,
        A.VIEW_FUTRAN_USERS: S.ALL,
        A.CREATE_CLIENT_ENGAGEMENT: S.ALL,  # drafts only; approval is the Chief Auditor's
        A.REGISTER_AI_TOOL: S.ASSIGNED,
        A.SUBMIT_USE_CASE: S.ASSIGNED,
        A.SET_FINAL_TIER: S.ASSIGNED,
        A.VIEW_INDIVIDUAL_ATTESTATIONS: S.ASSIGNED,
        A.UPLOAD_EVIDENCE: S.ASSIGNED,
        A.RECORD_FINDINGS: S.ASSIGNED,
        A.VERIFY_REMEDIATION: S.ASSIGNED,
        A.VIEW_AUDIT_LOG: S.ASSIGNED,
        A.VERIFY_SYSTEM_ANSWERS: S.ASSIGNED,
        A.SCORE_SYSTEM: S.ASSIGNED,
        A.MANAGE_DOCUMENT_REQUESTS: S.ASSIGNED,
        A.MANAGE_SYSTEMS: S.ASSIGNED,
        A.ADVANCE_STAGE: S.ASSIGNED,
        # regulatory master (§25.7): read, and suggest a change with its source
        A.VIEW_REG_MASTER: S.ALL,
        A.SUGGEST_REG_CHANGE: S.ALL,
        A.VIEW_APPLICABILITY: S.ASSIGNED,
    },
    R.QA_REVIEWER: {
        **_FUTRAN_TEAM_VIEW,
        A.APPROVE_FINDINGS: S.ASSIGNED,
        A.SIGN_DECLARATION: S.ASSIGNED,
        A.VIEW_REG_MASTER: S.ALL,
        A.SUGGEST_REG_CHANGE: S.ALL,
        A.SECOND_REVIEW_REG_CHANGE: S.ALL,
    },
    R.ENGAGEMENT_MANAGER: {
        **_FUTRAN_TEAM_VIEW,
        A.APPROVE_SYSTEM_ADDITION: S.ASSIGNED,
        A.ADVANCE_STAGE: S.ASSIGNED,
        A.MANAGE_DOCUMENT_REQUESTS: S.ASSIGNED,
        A.SIGN_DECLARATION: S.ASSIGNED,
        A.VIEW_AUDIT_LOG: S.ASSIGNED,
    },
    R.LEGAL_REVIEWER: {**_FUTRAN_TEAM_VIEW},
    R.CAICO: {
        A.VIEW_ENGAGEMENT: S.ORG,
        A.MANAGE_CLIENT_USERS: S.ORG,
        A.VIEW_CLIENT_USERS: S.ORG,
        A.VIEW_INVENTORY: S.ORG,
        A.REGISTER_AI_TOOL: S.ORG,
        A.SUBMIT_USE_CASE: S.ORG,
        A.APPROVE_USE_CASE: S.ORG,
        A.PROPOSE_TIER: S.ORG,
        A.RECORD_NAMED_USERS: S.ORG,
        A.LAUNCH_ATTESTATION: S.ORG,
        A.VIEW_INDIVIDUAL_ATTESTATIONS: S.ORG,
        A.VIEW_ATTESTATION_AGGREGATES: S.ORG,
        A.ANSWER_GOVERNANCE: S.ORG,
        A.SEND_ATTESTATION: S.ORG,
        A.MANAGE_ATTESTATION_ANSWERS: S.ORG,
        A.COMPLETE_OWN_ATTESTATION: S.ORG,
        A.APPROVE_GOVERNANCE: S.ORG,
        A.VIEW_GOVERNANCE: S.ORG,
        A.UPLOAD_EVIDENCE: S.ORG,
        A.VIEW_EVIDENCE: S.ORG,
        A.VIEW_FINAL_REPORT: S.ORG,
        A.RESPOND_FINDINGS: S.ORG,
        A.APPROVE_RESPONSES: S.ORG,
        A.VIEW_FINDINGS_RESPONSES: S.ORG,
        A.VIEW_AUDIT_LOG: S.ORG,
        A.PREFILL_SYSTEM: S.ORG,
        A.VIEW_SCORES: S.ORG,
        A.UPLOAD_REQUESTED_DOCUMENT: S.ORG,
        A.SIGN_DECLARATION: S.ORG,
        A.SIGN_CLIENT_SIGNOFF: S.ORG,
        # register (§24.7): the AI Compliance Officer
        A.VIEW_REGISTER: S.ORG,
        A.EDIT_REGISTER: S.ORG,
        A.IMPORT_INVENTORY_TO_REGISTER: S.ORG,
        A.ADD_SYSTEM_LAW: S.ORG,
        A.REMOVE_SYSTEM_LAW: S.ORG,
        A.FILL_SYSTEM_ROLES: S.ORG,
        A.SET_COMPANY_ROLES: S.ORG,
        A.MARK_REQUIRED_ROLE_NA: S.ORG,
        A.SUBMIT_GO_LIVE: S.ORG,
        A.APPROVE_GO_LIVE: S.ORG,
        A.MANAGE_COMMITTEE_MEMBERS: S.ORG,
        A.RECORD_COMMITTEE: S.ORG,
        A.RECORD_SYSTEM_HISTORY: S.ORG,
    },
    R.CLIENT_ADMIN: {
        A.VIEW_ENGAGEMENT: S.ORG,
        A.MANAGE_CLIENT_USERS: S.ORG,
        A.VIEW_CLIENT_USERS: S.ORG,
        A.SEND_ATTESTATION: S.ORG,
        A.COMPLETE_OWN_ATTESTATION: S.ORG,
        # register (§24.7): all systems, import, the user and committee lists; no roles, laws or go-live
        A.VIEW_REGISTER: S.ORG,
        A.EDIT_REGISTER: S.ORG,
        A.IMPORT_INVENTORY_TO_REGISTER: S.ORG,
        A.MANAGE_COMMITTEE_MEMBERS: S.ORG,
    },
    R.EXEC_SPONSOR: {
        A.VIEW_ENGAGEMENT: S.ORG,
        A.VIEW_INVENTORY: S.ORG,
        A.VIEW_GOVERNANCE: S.ORG,
        A.VIEW_FINAL_REPORT: S.ORG,
        A.APPROVE_RESPONSES: S.ORG,
        A.VIEW_FINDINGS_RESPONSES: S.ORG,
        A.VIEW_SCORES: S.ORG,
        A.SIGN_DECLARATION: S.ORG,
        A.SIGN_CLIENT_SIGNOFF: S.ORG,
        A.COMPLETE_OWN_ATTESTATION: S.ORG,
    },
    R.DPO: {
        A.VIEW_ENGAGEMENT: S.ORG,
        A.VIEW_INVENTORY: S.ORG,
        A.VIEW_INDIVIDUAL_ATTESTATIONS: S.ORG,
        A.VIEW_ATTESTATION_AGGREGATES: S.ORG,
        A.VIEW_GOVERNANCE: S.ORG,
        A.MANAGE_ATTESTATION_ANSWERS: S.ORG,
        A.COMPLETE_OWN_ATTESTATION: S.ORG,
        A.VIEW_EVIDENCE: S.ORG,
        A.VIEW_FINAL_REPORT: S.ORG,
        A.VIEW_FINDINGS_RESPONSES: S.ORG,
        A.VIEW_SCORES: S.ORG,
        A.UPLOAD_REQUESTED_DOCUMENT: S.ORG,
        A.SIGN_CLIENT_SIGNOFF: S.ORG,
    },
    R.DEPT_COMPLIANCE_LEAD: {
        A.VIEW_ENGAGEMENT: S.ORG,
        A.VIEW_CLIENT_USERS: S.DEPT,
        A.VIEW_INVENTORY: S.DEPT,
        A.REGISTER_AI_TOOL: S.DEPT,
        A.SUBMIT_USE_CASE: S.DEPT,
        A.APPROVE_USE_CASE: S.DEPT,
        A.PROPOSE_TIER: S.DEPT,
        A.RECORD_NAMED_USERS: S.DEPT,
        A.VIEW_ATTESTATION_AGGREGATES: S.DEPT,
        A.UPLOAD_EVIDENCE: S.DEPT,
        A.VIEW_EVIDENCE: S.DEPT,
        A.VIEW_FINAL_REPORT: S.DEPT,
        A.RESPOND_FINDINGS: S.DEPT,
        A.VIEW_FINDINGS_RESPONSES: S.DEPT,
        A.PREFILL_SYSTEM: S.DEPT,
        A.UPLOAD_REQUESTED_DOCUMENT: S.DEPT,
        A.SIGN_CLIENT_SIGNOFF: S.DEPT,
        A.COMPLETE_OWN_ATTESTATION: S.ORG,  # one's own line item, whatever the department
        # register (§24.7, "Dept Head"): own department; laws add only; submits for go-live
        A.VIEW_REGISTER: S.DEPT,
        A.EDIT_REGISTER: S.DEPT,
        A.ADD_SYSTEM_LAW: S.DEPT,
        A.FILL_SYSTEM_ROLES: S.DEPT,
        A.SUBMIT_GO_LIVE: S.DEPT,
        A.RECORD_SYSTEM_HISTORY: S.DEPT,
    },
    R.CONTRIBUTOR: {
        A.VIEW_ENGAGEMENT: S.ORG,
        A.VIEW_INVENTORY: S.DEPT,
        A.REGISTER_AI_TOOL: S.DEPT,
        A.SUBMIT_USE_CASE: S.DEPT,
        A.RECORD_NAMED_USERS: S.DEPT,
        A.UPLOAD_EVIDENCE: S.DEPT,
        A.VIEW_EVIDENCE: S.DEPT,
        A.VIEW_FINDINGS_RESPONSES: S.DEPT,
        A.PREFILL_SYSTEM: S.SYSTEM,
        A.UPLOAD_REQUESTED_DOCUMENT: S.SYSTEM,
        A.COMPLETE_OWN_ATTESTATION: S.ORG,
    },
}


def scopes_for(roles: set[str], action: A) -> set[S]:
    out = set()
    for r in roles:
        try:
            s = MATRIX.get(R(r), {}).get(action, S.NONE)
        except ValueError:
            continue
        if s != S.NONE:
            out.add(s)
    return out


# ---- v0.6 WS-D: litigation (§27.4), Sales Team and opportunities (§27.5), client alerts (§27.6), refresh alerts (§27.9).
# The Sales Team sees cases, opportunities and the trigger behind each; it holds no engagement, evidence, finding,
# score or report permission, and edits no law, case, register or engagement record.
_WS_D: dict[R, dict[A, S]] = {
    R.SALES_TEAM: {
        A.VIEW_LITIGATION: S.ALL,
        A.VIEW_OPPORTUNITIES: S.ALL,
        A.WORK_OPPORTUNITIES: S.ALL,
        A.APPROVE_ADDON_ALERTS: S.ALL,
    },
    R.CHIEF_AUDITOR: {
        A.VIEW_LITIGATION: S.ALL,
        A.MANAGE_LITIGATION: S.ALL,
        A.VIEW_OPPORTUNITIES: S.ALL,
        A.WORK_OPPORTUNITIES: S.ALL,
        A.APPROVE_OPPORTUNITY: S.ALL,
        A.MANAGE_CLIENT_ALERTS: S.ALL,
        A.APPROVE_CLIENT_ALERTS: S.ALL,
        A.APPROVE_ADDON_ALERTS: S.ALL,
        A.MANAGE_ALERT_SETTINGS: S.ALL,
    },
    R.AUDITOR: {A.VIEW_LITIGATION: S.ALL},
    R.ADMIN: {A.MANAGE_CLIENT_ALERTS: S.ALL, A.MANAGE_ALERT_SETTINGS: S.ALL},
}
for _role, _acts in _WS_D.items():
    MATRIX.setdefault(_role, {}).update(_acts)


# ---- v0.5 WS-C: email, groups and sync (§26.9; §27.1 per-user sync and the Futran Admin's starting groups for a client)
_WS_C: dict[R, dict[A, S]] = {
    R.ADMIN: {
        A.MANAGE_FUTRAN_MAILBOX: S.ALL, A.MANAGE_FUTRAN_GROUPS: S.ALL, A.VIEW_FUTRAN_GROUPS: S.ALL, A.EDIT_MAIL_TEMPLATES: S.ALL,
        A.VIEW_MAIL_LOG: S.ALL, A.SET_USER_MAIL_SYNC: S.ALL, A.MANAGE_CLIENT_GROUPS: S.ALL, A.VIEW_CLIENT_GROUPS: S.ALL, A.VIEW_CLIENT_MAILBOX: S.ALL,
    },
    R.CHIEF_AUDITOR: {A.VIEW_FUTRAN_GROUPS: S.ALL, A.VIEW_CLIENT_GROUPS: S.ALL, A.VIEW_CLIENT_MAILBOX: S.ALL, A.SEND_TO_CLIENT_GROUPS: S.ALL, A.VIEW_MAIL_LOG: S.ALL},
    R.AUDITOR: {A.VIEW_FUTRAN_GROUPS: S.ALL, A.VIEW_CLIENT_GROUPS: S.ASSIGNED, A.VIEW_CLIENT_MAILBOX: S.ASSIGNED, A.SEND_TO_CLIENT_GROUPS: S.ASSIGNED, A.VIEW_MAIL_LOG: S.ASSIGNED},
    R.CLIENT_ADMIN: {
        A.MANAGE_CLIENT_MAILBOX: S.ORG, A.VIEW_CLIENT_MAILBOX: S.ORG, A.MANAGE_CLIENT_GROUPS: S.ORG, A.VIEW_CLIENT_GROUPS: S.ORG, A.SEND_TO_CLIENT_GROUPS: S.ORG,
        A.EDIT_MAIL_TEMPLATES: S.ORG, A.VIEW_MAIL_LOG: S.ORG, A.SET_USER_MAIL_SYNC: S.ORG,
    },
    R.CAICO: {
        A.VIEW_CLIENT_MAILBOX: S.ORG, A.MANAGE_CLIENT_GROUPS: S.ORG, A.VIEW_CLIENT_GROUPS: S.ORG, A.SEND_TO_CLIENT_GROUPS: S.ORG, A.EDIT_MAIL_TEMPLATES: S.ORG,
        A.VIEW_MAIL_LOG: S.ORG,
    },
    R.DEPT_COMPLIANCE_LEAD: {A.MANAGE_CLIENT_GROUPS: S.DEPT, A.VIEW_CLIENT_GROUPS: S.DEPT, A.SEND_TO_CLIENT_GROUPS: S.DEPT, A.VIEW_MAIL_LOG: S.DEPT},
}
for _role, _grants in _WS_C.items():
    MATRIX.setdefault(_role, {}).update(_grants)
