"""Email onboarding hooks into other screens: the Client Admin's "Connect your email" Getting started item (§26.1)."""
from sqlalchemy.orm import Session

from app.mail.connections import org_connection
from app.tenancy.models import Organization


def getting_started_items(db: Session, actor) -> list[dict]:
    """Extra Getting started items for this user. They sit beside the seven initiation package items and do not count
    towards them (the package gate is unchanged)."""
    if actor.is_futran or not actor.has_role("client_admin"):
        return []
    conn = org_connection(db, db.get(Organization, actor.organization.id))
    done = conn is not None and conn.status == "connected" and conn.test_sent_at is not None
    status = "Not started" if conn is None or conn.status in ("not_connected", "disconnected") else (
        "Waiting for IT to approve access" if conn.status == "consent_requested" else ("Connected" if conn.status == "connected" else "Needs attention"))
    return [{"key": "email", "title": "Connect your email", "done": done, "status": status, "link": "/admin/email",
             "description": "Requests to employees and department heads go out from your own email system and replies come back into the platform. "
                            "Connect Microsoft 365 or Google Workspace, choose the sender, sync your directory and send a test."}]
