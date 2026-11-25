"""Every route reaches `authorize`, or is on the documented allowlist (CLAUDE.md: "Every endpoint calls authorize").

Static proof: the route's endpoint, or one of its FastAPI dependencies, or any function either of them mentions
(transitively, across the `app` package) mentions `app.policy.authorize.authorize`. See tests/security/_callgraph.py.
"""
import pytest

from tests.security._allowlist import ALLOWLIST, FINDINGS, PUBLIC, SIGNED_IN
from tests.security._callgraph import AUTHORIZE, graph, qualname
from tests.security._routes import routes


def _reaches(r) -> bool:
    g = graph()
    for fn in r.calls:
        if not hasattr(fn, "__qualname__"):
            continue
        q = qualname(fn)
        if q == AUTHORIZE or g.reaches(q):
            return True
    return False


def _params():
    out = []
    for r in routes():
        marks = [pytest.mark.xfail(strict=True, reason=FINDINGS[r.key])] if r.key in FINDINGS else []
        out.append(pytest.param(r, id=r.key, marks=marks))
    return out


@pytest.mark.parametrize("route", _params())
def test_route_reaches_authorize_or_is_allowlisted(route):
    if route.key in ALLOWLIST:
        return
    assert _reaches(route), f"{route.key} ({qualname(route.endpoint)}) never reaches authorize and is not on the allowlist"


def test_allowlist_entries_are_real_routes_with_reasons():
    keys = {r.key for r in routes()}
    assert not set(PUBLIC) & set(SIGNED_IN)
    assert not set(ALLOWLIST) & set(FINDINGS)
    for k, reason in {**ALLOWLIST, **FINDINGS}.items():
        assert k in keys, f"stale allowlist entry: {k}"
        assert reason.strip() and "\n" not in reason, f"{k}: give a one-line reason"


def test_signed_in_allowlist_routes_require_a_session():
    """Allowlisted 'own records' routes still need a signed-in user: their dependencies include current_actor."""
    by_key = {r.key: r for r in routes()}
    for k in SIGNED_IN:
        names = {qualname(c) for c in by_key[k].calls if hasattr(c, "__qualname__")}
        assert "app.auth.deps.current_actor" in names, f"{k} does not depend on current_actor"


def test_call_graph_sees_known_checks():
    """Guards the analyser itself: a handler that calls authorize directly, one that calls it through a helper, and one
    that does not call it at all."""
    g = graph()
    assert g.reaches("app.laws.router.patch_law")  # direct
    assert g.reaches("app.findings.router.patch")  # through _finding()
    assert not g.reaches("app.notifications.router.mine")
    assert g.reaches("app.mail.router.list_outbox")  # direct since the Y01 fix


def test_summary():
    rs = routes()
    unreached = [r.key for r in rs if not _reaches(r)]
    print(f"\nroutes checked: {len(rs)}; reach authorize: {len(rs) - len(unreached)}; allowlisted: {len(ALLOWLIST)}; findings: {len(FINDINGS)}")
    assert set(unreached) <= set(ALLOWLIST) | set(FINDINGS)
