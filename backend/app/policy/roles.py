from enum import StrEnum


class Role(StrEnum):
    # Futran
    CHIEF_AUDITOR = "chief_auditor"
    ADMIN = "admin"
    AUDITOR = "auditor"
    QA_REVIEWER = "qa_reviewer"
    ENGAGEMENT_MANAGER = "engagement_manager"
    LEGAL_REVIEWER = "legal_reviewer"
    SALES_TEAM = "sales_team"  # §27.5
    # Client
    EXEC_SPONSOR = "exec_sponsor"
    CAICO = "caico"
    CLIENT_ADMIN = "client_admin"
    DPO = "dpo"
    DEPT_COMPLIANCE_LEAD = "dept_compliance_lead"
    CONTRIBUTOR = "contributor"


FUTRAN_ROLES = {Role.CHIEF_AUDITOR, Role.ADMIN, Role.AUDITOR, Role.QA_REVIEWER, Role.ENGAGEMENT_MANAGER, Role.LEGAL_REVIEWER, Role.SALES_TEAM}
CLIENT_ROLES = {Role.EXEC_SPONSOR, Role.CAICO, Role.CLIENT_ADMIN, Role.DPO, Role.DEPT_COMPLIANCE_LEAD, Role.CONTRIBUTOR}
SIGN_OFF_ROLES = {Role.CAICO, Role.EXEC_SPONSOR, Role.DPO}

ROLE_LABELS: dict[str, str] = {
    "chief_auditor": "Chief Auditor",
    "admin": "Admin",
    "auditor": "Auditor",
    "qa_reviewer": "QA Reviewer",
    "engagement_manager": "Engagement Manager",
    "legal_reviewer": "Legal/Compliance Reviewer",
    "sales_team": "Sales Team",
    "exec_sponsor": "Executive Sponsor",
    "caico": "Chief AI Compliance Officer",
    "client_admin": "Client Admin",
    "dpo": "Data Protection Officer",
    "dept_compliance_lead": "Department Compliance Lead",
    "contributor": "Contributor",
}

# Role names accepted in the user list CSV (spec §12), matched case-insensitively.
CSV_ROLE_NAMES: dict[str, str] = {
    "chief ai compliance officer": "caico",
    "client admin": "client_admin",
    "executive sponsor": "exec_sponsor",
    "data protection officer": "dpo",
    "department compliance lead": "dept_compliance_lead",
    "contributor": "contributor",
}


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role.replace("_", " ").title())
