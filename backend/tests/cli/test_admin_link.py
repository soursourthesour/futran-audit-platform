from sqlalchemy import select

from app import cli
from app.audit_log.models import AuditLog
from app.tenancy.service import roles_of
from tests.factories import make_org, make_user


def _run(monkeypatch, db, settings, *argv):
    monkeypatch.setattr(cli, "_session", lambda: (settings, db))
    return cli.main(["admin-link", *argv])


def _futran(db):
    return cli._futran_org(db)


def test_disabled_admin_needs_enable(monkeypatch, db, settings, capsys):
    u = make_user(db, _futran(db), roles=["admin"], name="Ada Admin", email="ada@futran.test")
    u.status = "disabled"
    db.commit()
    assert _run(monkeypatch, db, settings, "--email", "ada@futran.test") == 2
    assert "disabled" in capsys.readouterr().err
    db.refresh(u)
    assert u.status == "disabled"
    assert _run(monkeypatch, db, settings, "--email", "ada@futran.test", "--enable") == 0
    assert db.get(type(u), u.id).status == "invited"


def test_admin_role_only_with_grant_admin(monkeypatch, db, settings, capsys):
    u = make_user(db, _futran(db), roles=["auditor"], name="Aud Itor", email="aud@futran.test")
    db.commit()
    assert _run(monkeypatch, db, settings, "--email", "aud@futran.test") == 2
    assert "--grant-admin" in capsys.readouterr().err
    assert "admin" not in {r.role for r in roles_of(db, u.id)}
    assert _run(monkeypatch, db, settings, "--email", "aud@futran.test", "--grant-admin") == 0
    assert "admin" in {r.role for r in roles_of(db, u.id)}


def test_reset_is_audited(monkeypatch, db, settings):
    make_user(db, _futran(db), roles=["admin"], name="Ada Admin", email="ada@futran.test")
    db.commit()
    assert _run(monkeypatch, db, settings, "--email", "ada@futran.test") == 0
    log = db.scalars(select(AuditLog).where(AuditLog.action.like("cli.admin_link%"))).all()
    assert log and all(a.actor_name == "Command line" for a in log)


def test_client_user_refused(monkeypatch, db, settings):
    make_user(db, make_org(db, name="ABC Corp"), name="Cli Ent", email="c@abc.test")
    db.commit()
    assert _run(monkeypatch, db, settings, "--email", "c@abc.test", "--grant-admin") == 2
