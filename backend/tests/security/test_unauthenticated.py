"""No session, no access: every route that is not public answers 401 or 403, never 200 and never 500.

Requests are built from the route table and the OpenAPI document: path parameters are random UUIDs and bodies are the
smallest that pass schema validation. The public API routes must refuse a request with no bearer token the same way."""
import pytest

from tests.security._allowlist import PUBLIC
from tests.security._bodies import fill_path, request_kwargs
from tests.security._routes import routes
from tests.security._world import World

REFUSED = {401, 403}
# Public API routes: no session cookie, but they must still refuse a request without a bearer token.
PUBLIC_API_TOKEN_ROUTES = {k for k in PUBLIC if k.split(" ", 1)[1].startswith("/api/public/v1/") and "/docs" not in k and "openapi" not in k and "oauth/token" not in k}


def _targets():
    return [pytest.param(r.method, r.path, id=r.key) for r in routes() if r.key not in PUBLIC or r.key in PUBLIC_API_TOKEN_ROUTES]


@pytest.fixture(scope="module")
def anon(tmp_path_factory):
    w = World(str(tmp_path_factory.mktemp("files")), demo=False)
    yield w.logout()
    w.close()


@pytest.mark.parametrize("method,path", _targets())
def test_no_session_is_refused(anon, method, path):
    r = anon.request(method, fill_path(path), **request_kwargs(path, method))
    assert r.status_code in REFUSED, f"{method} {path} without a session answered {r.status_code}: {r.text[:200]}"


def test_coverage():
    n = len(_targets())
    print(f"\nunauthenticated checks: {n}")
    assert n >= 750
