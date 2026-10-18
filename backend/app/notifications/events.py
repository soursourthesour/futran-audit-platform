"""The notification events of spec §14: who is told, and how."""
from dataclasses import dataclass


@dataclass(frozen=True)
class EventSpec:
    key: str
    label: str
    recipients: str
    channels: tuple[str, ...]  # in_app | email | digest


EVENTS: dict[str, EventSpec] = {e.key: e for e in [
    EventSpec("engagement_submitted", "Draft submitted for approval", "Chief Auditor", ("in_app", "email")),
    EventSpec("package_sent", "Initiation package sent", "CAICO, Client Admin", ("email",)),
    EventSpec("invitation_expiring", "Invitation expiring in 48 h / expired", "Invitee; Futran team", ("email",)),
    EventSpec("sign_off_role_changed", "Sign-off role changed", "Chief Auditor, assigned auditors (and the client's CAICO)", ("in_app", "email")),
    EventSpec("sign_off_awaiting", "Sign-off awaiting you", "Next approver", ("in_app", "email")),
    EventSpec("evidence_request", "Evidence request created / due in 3 days", "Request owner", ("email",)),
    EventSpec("finding_returned", "Finding returned", "Author", ("in_app",)),
    EventSpec("remediation_done", "Remediation item marked done", "Assigned auditor", ("in_app",)),
    EventSpec("overdue_digest", "Commitment / remediation overdue", "Owner, CAICO, assigned auditor", ("digest",)),
]}


def channels_for(kind: str) -> tuple[str, ...]:
    """Kinds not in the §14 table are in-app only."""
    spec = EVENTS.get(kind)
    return spec.channels if spec else ("in_app",)
