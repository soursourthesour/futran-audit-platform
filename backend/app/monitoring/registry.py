"""The monitoring check registry (spec §21 F3; wave 3 plan, "Monitoring checks are a registry").

Each workstream registers the checks for its own data, at import time, in a module named `app/<package>/monitor_checks.py`
(`load_checks` imports every such module it finds):

    from app.monitoring.registry import CheckOutcome, register_check

    def _overdue(db, org) -> list[CheckOutcome]:
        return [CheckOutcome(c.id, c.description, "failed", "Due 1 Oct 2026", "/governance", action="open") for c in ...]

    register_check("commitment_overdue", "Commitment overdue", "high", "monthly", "commitment", _overdue)

`fn(db, org)` returns one outcome per object it looked at: `healthy`, `attention`, `failed`, or `not_started` (the
check has nothing to work on yet, for example no connector is connected). Return an empty list when there is nothing to
report; the run then records one healthy row for the check. `fn` must only read: monitoring never changes a signed
report or any audit record. `action` names the button the dashboard shows: start_reassessment, review, open,
send_reminder or request_report (None for no button); `action_link` is the in-app path the button or row opens.
"""
from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.monitoring.models import APPLIES_TO, SEVERITIES, STATUSES, MonitorCheck

ACTIONS = ("start_reassessment", "review", "open", "send_reminder", "request_report")


@dataclass
class CheckOutcome:
    object_id: str | None
    object_label: str
    status: str
    detail: str
    action_link: str | None = None
    action: str | None = None
    register_system_id: str | None = None  # the register system a failed check may raise a reassessment on

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f"Unknown check status {self.status!r}; use one of {', '.join(STATUSES)}.")
        if self.action is not None and self.action not in ACTIONS:
            raise ValueError(f"Unknown action {self.action!r}; use one of {', '.join(ACTIONS)}.")


@dataclass
class RegisteredCheck:
    code: str
    description: str
    severity: str
    frequency: str
    applies_to: str
    fn: Callable[[Session, object], list[CheckOutcome]]
    on_action: Callable | None = None  # (db, settings, user, org, result) -> message; for request_report and send_reminder


CHECKS: dict[str, RegisteredCheck] = {}


def register_check(code: str, description: str, severity: str, frequency: str, applies_to: str, fn: Callable, *, on_action: Callable | None = None) -> RegisteredCheck:
    """Register a check. `on_action(db, settings, user, org, result)` carries out the result's request_report or
    send_reminder button and returns a short message for the person; start_reassessment calls
    app.impact.triggers.raise_trigger on the result's register_system_id, and review and open are links."""
    if severity not in SEVERITIES:
        raise ValueError(f"Unknown severity {severity!r}; use one of {', '.join(SEVERITIES)}.")
    if applies_to not in APPLIES_TO:
        raise ValueError(f"Unknown scope {applies_to!r}; use one of {', '.join(APPLIES_TO)}.")
    c = RegisteredCheck(code, description, severity, frequency, applies_to, fn, on_action)
    CHECKS[code] = c
    return c


def load_checks() -> dict[str, RegisteredCheck]:
    """Import every `app.<package>.monitor_checks` module, so each workstream's checks are registered."""
    import app

    for info in pkgutil.iter_modules(app.__path__):
        if not info.ispkg:
            continue
        name = f"app.{info.name}.monitor_checks"
        if importlib.util.find_spec(name) is not None:
            importlib.import_module(name)
    return CHECKS


def sync_checks(db: Session) -> dict[str, MonitorCheck]:
    """Mirror the registry into `monitor_checks` (one row per code). Checks no longer registered are marked inactive."""
    rows = {c.code: c for c in db.scalars(select(MonitorCheck))}
    for code, rc in CHECKS.items():
        row = rows.get(code)
        if row is None:
            row = MonitorCheck(code=code)
            db.add(row)
            rows[code] = row
        row.description, row.severity, row.frequency, row.applies_to, row.active = rc.description, rc.severity, rc.frequency, rc.applies_to, True
        row.rule = {"module": getattr(rc.fn, "__module__", None)}
    for code, row in rows.items():
        if code not in CHECKS:
            row.active = False
    db.flush()
    return rows
