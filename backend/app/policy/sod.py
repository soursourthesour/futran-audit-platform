"""Separation-of-duties rules (spec §6), enforced in services, not just the UI."""
from app.auth.deps import Actor
from app.core.errors import Forbidden


def assert_not_self_approval(approver_id: str, *preparer_ids: str | None) -> None:
    """Rule 2: the approver of any item must differ from its author or preparer."""
    if approver_id in {p for p in preparer_ids if p}:
        raise Forbidden("You prepared this item, so you cannot approve it. Another approver must sign it off.")


def self_approval_or_stand_in(db, approver_id: str, org, role: str, *preparer_ids: str | None) -> bool:
    """Rule 2 with the sign-off stand-in rule: a preparer may approve only when nobody else holds `role` today, so a
    practice with one Chief Auditor is never stuck. Returns True for a stand-in approval, which the caller records."""
    from app.tenancy.people import active_holders

    preparers = {p for p in preparer_ids if p}
    if approver_id not in preparers:
        return False
    if [u for u in active_holders(db, org, role) if u.id not in preparers]:
        assert_not_self_approval(approver_id, *preparer_ids)
    return True


def assert_not_admin_judgment(actor: Actor) -> None:
    """Rule 1: Admin can never create, edit or approve findings or risk tiers."""
    judgment_roles = {"chief_auditor", "auditor", "qa_reviewer"}
    if actor.is_futran and "admin" in actor.role_names and not (actor.role_names & judgment_roles):
        raise Forbidden("Administrators manage the platform and cannot make audit judgments.")

