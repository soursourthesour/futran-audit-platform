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
