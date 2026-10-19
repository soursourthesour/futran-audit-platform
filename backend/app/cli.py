"""Command line: `python -m app.cli <command>`.

Commands:
  create-admin --email E --name N     create the first Futran admin and print a one-time invitation link
  admin-link --email E [--name N]     print a set-password link for an administrator (--enable, --grant-admin)
  seed-reference                      load reference data (idempotent)
  reset-demo                          recreate the database with reference data and demo tenants (test mode only)
  seed-e2e                            minimal users for automated browser tests (test mode only)
"""
import argparse
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import make_engine, make_sessionmaker

DEMO_PASSWORD = "Demo-Password-2026"


def _session():
    settings = get_settings()
    engine = make_engine(settings.database_url)
    import importlib

    importlib.import_module("app.models_registry")
    return settings, make_sessionmaker(engine)()


def _futran_org(db):
    from app.tenancy.models import Organization
    from app.tenancy.service import create_organization

    org = db.scalar(select(Organization).where(Organization.type == "futran", Organization.is_internal.is_(False)))
    return org or create_organization(db, name="Futran Solutions", type="futran", legal_name="Futran Solutions Inc.", status="active", hq_city="Edison", hq_state="NJ", hq_country="US")


def cmd_create_admin(args) -> int:
    from app.invitations.service import invite_user
    from app.tenancy.service import assign_role, create_user

    settings, db = _session()
    org = _futran_org(db)
    user = create_user(db, org, name=args.name, email=args.email)
    assign_role(db, user, "admin")
    inv = invite_user(db, settings, None, user)
    db.commit()
    print(f"Admin {args.email} created. Open this link within 7 days to set a password:\n{settings.base_url}/invite/{inv.raw_token}")
    return 0


def cmd_admin_link(args) -> int:
    """Print a fresh set-password link for a Futran administrator, creating the account if it does not exist yet.

    A disabled account is only re-enabled with --enable; a Futran user who is not an administrator only becomes one
    with --grant-admin. Every change is written to the audit log.
    """
    from app.audit_log import service as audit
    from app.invitations.service import invite_user
    from app.tenancy.service import assign_role, create_user, find_user_by_email, roles_of

    settings, db = _session()
    org = _futran_org(db)
    user = find_user_by_email(db, args.email)
    created = False
    if user is None:
        if not args.name:
            print("No account uses that email yet. Run again with --name to create it.", file=sys.stderr)
            return 2
        user, created = create_user(db, org, name=args.name, email=args.email), True
    if user.organization_id != org.id:
        print("That email belongs to a client user, not a Futran administrator.", file=sys.stderr)
        return 2
    if user.status == "disabled" and not args.enable:
        print("That account is disabled. Run again with --enable if it should be turned back on.", file=sys.stderr)
        return 2
    is_admin = "admin" in {r.role for r in roles_of(db, user.id)}
    if not is_admin and not created and not args.grant_admin:
        print("That user is not an administrator. Run again with --grant-admin to make them one.", file=sys.stderr)
        return 2
    log = {"actor_id": None, "actor_name": "Command line", "object_type": "User", "object_id": user.id, "organization_id": org.id}
    if created:
        audit.record(db, action="cli.admin_link.create", after={"email": user.email}, summary=f"Created administrator account {user.email} from the command line", **log)
    if not is_admin:
        assign_role(db, user, "admin")
        audit.record(db, action="cli.admin_link.grant_admin", after={"role": "admin"}, summary=f"Gave {user.name} the administrator role from the command line", **log)
    before = user.status
    user.status = "invited"
    user.password_hash = None
    inv = invite_user(db, settings, None, user)
    audit.record(db, action="cli.admin_link.reset", before={"status": before}, after={"status": "invited"}, summary=f"Issued a set-password link for {user.email} from the command line; the old password no longer works", **log)
    db.commit()
    print(f"Open this link within 7 days to set the password for {user.email}:\n{settings.base_url}/invite/{inv.raw_token}")
    return 0


def cmd_seed_reference(args) -> int:
    from app.reference import LOADERS

    settings, db = _session()
    _futran_org(db)
    for name, loader in LOADERS:
        result = loader(db)
        print(f"{name}: {result}")
    db.commit()
    return 0


def _require_test_mode(settings) -> None:
    if not settings.test_mode:
        print("Refused: demo and test data can only be loaded while the platform is in test mode.", file=sys.stderr)
        raise SystemExit(2)


def cmd_seed_e2e(args) -> int:
    from app.auth.passwords import hash_password
    from app.tenancy.models import User
    from app.tenancy.service import assign_role, create_user

    settings, db = _session()
    _require_test_mode(settings)
    if getattr(args, "late", False):
        import json

        from app.demo.seed_demo import e2e_late

        out = e2e_late(db, settings)
        db.commit()
        print(json.dumps(out))
        return 0
    org = _futran_org(db)
    people = [
        ("Ada Admin", "admin@futran.demo", "admin"),
        ("Chris Chief", "chief@futran.demo", "chief_auditor"),
        ("Alex Auditor", "auditor1@futran.demo", "auditor"),
        ("Erin Manager", "manager@futran.demo", "engagement_manager"),
    ]
    for name, email, role in people:
        u = db.scalar(select(User).where(User.email == email)) or create_user(db, org, name=name, email=email)
        u.password_hash = hash_password(DEMO_PASSWORD)
        u.status = "active"
        assign_role(db, u, role)
    db.commit()
    print("e2e users ready")
    return 0


def cmd_reset_demo(args) -> int:
    import os

    import importlib.util

    settings, _ = _session()
    _require_test_mode(settings)
    if importlib.util.find_spec("app.demo") is None:  # check before deleting anything
        print("The demo clients are not in this build yet. Your data was left as it is.")
        return 0
    url = settings.database_url
    if url.startswith("sqlite:///"):
        path = url.replace("sqlite:///", "", 1)
        try:
            for suffix in ("", "-wal", "-shm"):
                if os.path.exists(path + suffix):
                    os.remove(path + suffix)
        except PermissionError:
            print("The database is in use, so it could not be replaced. Close every other Futran Audit Platform window "
                  "(the black windows from run.bat or demo.bat), then try again.", file=sys.stderr)
            return 2
    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations"))
    command.upgrade(cfg, "head")
    cmd_seed_reference(args)
    settings, db = _session()
    from app.demo.seed_demo import run

    run(db, settings)
    db.commit()
    print("Demo data loaded. Sign in as chief@futran.demo with the password Demo-Password-2026.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("create-admin")
    a.add_argument("--email", required=True)
    a.add_argument("--name", required=True)
    a.set_defaults(func=cmd_create_admin)
    al = sub.add_parser("admin-link")
    al.add_argument("--email", required=True)
    al.add_argument("--name")
    al.add_argument("--enable", action="store_true", help="re-enable a disabled account")
    al.add_argument("--grant-admin", action="store_true", help="give an existing Futran user the administrator role")
    al.set_defaults(func=cmd_admin_link)
    sub.add_parser("seed-reference").set_defaults(func=cmd_seed_reference)
    se = sub.add_parser("seed-e2e")
    se.add_argument("--late", action="store_true", help="ABC Corp at stage 6 and Meridian at stage 3, for the review-to-close journey")
    se.set_defaults(func=cmd_seed_e2e)
    sub.add_parser("reset-demo").set_defaults(func=cmd_reset_demo)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
