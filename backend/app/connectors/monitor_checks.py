"""Monitoring check owned by WS-J's discovery data: "New undeclared AI tool" (spec §21 F3)."""
from sqlalchemy import select

from app.connectors import service as svc
from app.connectors.adapters import LABELS
from app.connectors.models import Connector, DiscoveredTool
from app.monitoring.registry import CheckOutcome, register_check


def undeclared_ai_tool(db, org) -> list[CheckOutcome]:
    conns = {c.id: c for c in db.scalars(select(Connector).where(Connector.organization_id == org.id, Connector.deleted_at.is_(None)))}
    rows = list(db.scalars(select(DiscoveredTool).where(DiscoveredTool.organization_id == org.id, DiscoveredTool.deleted_at.is_(None))))
    if not rows and not any(c.status == "connected" for c in conns.values()):
        return [CheckOutcome(None, org.name, "not_started", "Connect Okta, Microsoft or Google, or upload expense data, so new AI tools can be found.", "/integrations")]
    declared, _ = svc.declared_keys(db, org.id)
    out = []
    for t in rows:
        dept = svc._dept_label(db, t)
        label = f"{t.product} · {dept} · {t.user_count} {'person' if t.user_count == 1 else 'people'}"
        source = LABELS[conns[t.connector_id].type] if t.connector_id in conns else "a connector"
        if t.status == "new" and t.vendor_key not in declared:
            out.append(CheckOutcome(t.id, label, "failed", f"Not declared in the latest attestation; found through {source}.", f"/integrations?tool={t.id}", action="review"))
        else:
            why = {"confirmed": "added to the AI inventory", "mapped": "mapped to an inventory tool", "dismissed": "dismissed with a reason"}.get(t.status, "declared in the attestation")
            out.append(CheckOutcome(t.id, label, "healthy", f"Found through {source}; {why}.", f"/integrations?tool={t.id}"))
    return out


register_check("undeclared_ai_tool", "New undeclared AI tool", "high", "monthly and after each connector sync", "tool", undeclared_ai_tool)
