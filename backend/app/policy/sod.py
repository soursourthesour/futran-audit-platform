"""Separation-of-duties rules (spec §6), enforced in services, not just the UI."""
from app.auth.deps import Actor
from app.core.errors import Forbidden


def assert_not_self_approval(approver_id: str, *preparer_ids: str | None) -> None:
    """Rule 2: the approver of any item must differ from its author or preparer."""
    if approver_id in {p for p in preparer_ids if p}:
        raise Forbidden("You prepared this item, so you cannot approve it. Another approver must sign it off.")


def assert_not_admin_judgment(actor: Actor) -> None:
    """Rule 1: Admin can never create, edit or approve findings or risk tiers."""
    judgment_roles = {"chief_auditor", "auditor", "qa_reviewer"}
    if actor.is_futran and "admin" in actor.role_names and not (actor.role_names & judgment_roles):
        raise Forbidden("Administrators manage the platform and cannot make audit judgments.")


def assert_client_cannot_edit_finding(actor: Actor) -> None:
    """Rule 5: clients can respond to findings but never edit finding text."""
    if not actor.is_futran:
        raise Forbidden("Clients can respond to findings but cannot change finding text.")
