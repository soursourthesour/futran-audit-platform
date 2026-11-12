"""Which home screen a person lands on after sign-in (spec §13.1).

A person with several roles lands on the home of the role with the most authority and sees the union of their modules
in the navigation. Order: Futran — Chief Auditor (Chief Auditor home; 10 Nov F2: every Futran home shows the Dashboard), Admin (console), QA Reviewer (queue), Auditor, Engagement
Manager and Legal Reviewer (My work), Sales Officer and Sales Manager (Sales home). Client — CAICO (Getting started), Executive Sponsor
(Summary), DPO (Data review), Client Admin (Admin home), Department Compliance Lead (My department), Contributor (My tasks).
"""
HOME_PRECEDENCE: list[tuple[str, str]] = [
    ("chief_auditor", "/staff/chief"),
    ("admin", "/staff/admin"),
    ("qa_reviewer", "/qa"),
    ("auditor", "/my-work"),
    ("engagement_manager", "/my-work"),
    ("legal_reviewer", "/my-work"),
    ("sales_team", "/sales"),  # Release 2 R2: SM-01 Sales home
    ("sales_manager", "/sales"),
    ("price_list_owner", "/staff/admin/catalog"),  # Release 2 R1: the CEO and President keep the master price list
    ("pricing_approver", "/sales/approvals"),  # Release 2 R2: the approvals queue (SM-11); no Sales home permission
    ("caico", "/start"),
    ("exec_sponsor", "/summary"),
    ("dpo", "/data-review"),
    ("client_admin", "/admin/home"),
    ("dept_compliance_lead", "/my-department"),
    ("contributor", "/my-tasks"),
]


def home_for(roles: set[str], is_futran: bool) -> str:
    for role, path in HOME_PRECEDENCE:
        if role in roles:
            return path
    return "/audits" if is_futran else "/start"
