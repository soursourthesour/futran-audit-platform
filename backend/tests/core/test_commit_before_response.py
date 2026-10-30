"""A request's writes are committed before its response is sent.

FastAPI runs the clean-up of a `yield` dependency after the response has gone out unless the dependency is declared with
scope="function". If get_db commits in that clean-up, a browser can act on the response (for example the next request
after signing in) before the write is visible, and gets a 401.
"""
import pathlib
import re

from sqlalchemy import event

from tests.factories import make_org, make_user

APP = pathlib.Path(__file__).resolve().parents[2] / "app"


def test_sign_in_is_committed_before_the_response_starts(app, client, db, matrix):
    f = make_org(db, type="futran")
    make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test", password="Correct-Horse-2026")
    db.commit()

    order: list[str] = []
    engine = app.state.sessionmaker.kw["bind"]
    listener = lambda conn: order.append("commit")  # noqa: E731
    event.listen(engine, "commit", listener)

    inner = app.middleware_stack

    async def watch(scope, receive, send):
        async def send_and_note(message):
            if message["type"] == "http.response.start":
                order.append("response")
            await send(message)

        await inner(scope, receive, send_and_note)

    app.middleware_stack = watch
    try:
        r = client.post("/api/v1/auth/login", json={"email": "alex@futran.test", "password": "Correct-Horse-2026"})
    finally:
        app.middleware_stack = inner
        event.remove(engine, "commit", listener)
    assert r.status_code == 200, r.text
    assert "commit" in order and "response" in order
    assert order.index("commit") < order.index("response"), order


def test_every_database_dependency_ends_before_the_response():
    """Mixing scopes would give one request two database sessions, so every use must say scope="function"."""
    offenders = []
    for path in APP.rglob("*.py"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in re.finditer(r"Depends\(get_db([^)]*)\)", line):
                if 'scope="function"' not in m.group(1):
                    offenders.append(f"{path.relative_to(APP)}:{n}")
    assert not offenders, "Use Depends(get_db, scope=\"function\"): " + ", ".join(offenders[:20])
