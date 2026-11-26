"""Shared test factories. Each task adds factories for its own models here."""
from app.tenancy.service import assign_role, create_department, create_organization, create_user


def make_org(db, type="client", name=None, **kw):
    name = name or ("Futran Solutions" if type == "futran" else "ABC Corp")
    return create_organization(db, name=name, type=type, **kw)


def make_user(db, org, roles=(), name="Test User", email=None, password=None, scope=None, **kw):
    """roles: iterable of role names or (role, scope_type, scope_id) tuples."""
    from app.auth.passwords import hash_password

    email = email or f"{name.lower().replace(' ', '.')}@{org.name.lower().replace(' ', '')}.test"
    user = create_user(db, org, name=name, email=email, **kw)
    if password:
        user.password_hash = hash_password(password)
    user.status = kw.get("status", "active")
    for r in roles:
        if isinstance(r, tuple):
            assign_role(db, user, r[0], scope_type=r[1], scope_id=r[2])
        else:
            assign_role(db, user, r)
    db.flush()
    return user


def make_department(db, org, name="Human Resources", **kw):
    return create_department(db, org, name=name, **kw)


def login_as(client, db, user, accept_terms=True):
    """Give `client` a signed-in, MFA-passed session for `user` (client users have accepted the terms); returns the client."""
    from app.auth.sessions import COOKIE_NAME, create_session
    from app.core.clock import utcnow

    if accept_terms and user.terms_accepted_at is None:
        user.terms_accepted_at = utcnow()
    settings = client.app.state.settings
    s, raw = create_session(db, user, settings, mfa_passed=True)
    db.commit()
    client.cookies.set(COOKIE_NAME, raw)
    client.headers["X-CSRF-Token"] = s.csrf_token
    return client


def approve_client_review(db, e):
    """Record sign-offs 2 (each in-scope department), 3 and 4 as approved, as stage 4 leaves them."""
    from app.engagements.models import Engagement
    from app.signoffs.client_review import in_scope_departments
    from app.signoffs.service import create_sign_off

    e = db.get(Engagement, e.id)
    rows = [create_sign_off(db, e, 2, preparer_id=None, required_roles=["dept_compliance_lead"], scope_ref=d.id) for d in in_scope_departments(db, e)]
    rows += [create_sign_off(db, e, n, preparer_id=None, required_roles=["caico"]) for n in (3, 4)]
    for so in rows:
        so.status = "approved"
    db.commit()


# ---- JSON columns compared in Python, so the same test runs on SQLite and PostgreSQL (PostgreSQL has no `=` or `LIKE`
# for the json type)
def mails_to(db, address: str, *, template_key: str | None = None, only: bool = False) -> list:
    """Outbox messages addressed to `address` (with only=True: to that address alone), oldest first."""
    from sqlalchemy import select

    from app.mail.models import OutboxMessage

    q = select(OutboxMessage).order_by(OutboxMessage.created_at, OutboxMessage.id)
    if template_key is not None:
        q = q.where(OutboxMessage.template_key == template_key)
    return [m for m in db.scalars(q) if (m.to == [address] if only else address in (m.to or []))]


def findings_from_questions(db, question_ids: list[str], *, include_deleted: bool = True) -> list:
    """Findings whose source_question_ids are exactly `question_ids`."""
    from sqlalchemy import select

    from app.findings.models import Finding

    q = select(Finding).order_by(Finding.created_at, Finding.id)
    if not include_deleted:
        q = q.where(Finding.deleted_at.is_(None))
    return [f for f in db.scalars(q) if f.source_question_ids == question_ids]
