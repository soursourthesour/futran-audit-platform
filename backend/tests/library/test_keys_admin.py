"""Website API keys (Administration > Website API keys): only the Futran Admin lists, creates and revokes them; the key is
shown once and kept as a SHA-256 hash; every create and revoke is in the audit log."""
import hashlib

from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.library.models import WebsiteApiKey
from tests.library.conftest import API, SITE, new_key


def test_key_is_shown_once_and_stored_hashed(client, db, libw):
    out = new_key(client, libw, rate=90)
    k = out["key"]
    assert k.startswith("fwl_") and len(k) > 40
    row = db.get(WebsiteApiKey, out["website_key"]["id"])
    assert row.key_hash == hashlib.sha256(k.encode()).hexdigest()
    assert k not in str([getattr(row, c.key) for c in row.__table__.columns])
    assert out["website_key"]["key_prefix"] == k[:12] and row.key_prefix == k[:12]
    assert row.allowed_origins == [SITE] and row.rate_limit_per_minute == 90 and row.created_by == libw.admin.id
    libw.as_(libw.admin)
    listing = client.get(f"{API}/admin/website-keys").json()
    assert k not in str(listing)
    item = listing["keys"][0]
    assert item["name"] == "Futran website" and item["status"] == "active" and item["created_by"] == "Ada Admin" and item["last_used_at"] is None


def test_default_rate_limit_is_120_a_minute(client, db, libw):
    out = new_key(client, libw)
    assert out["website_key"]["rate_limit_per_minute"] == 120


def test_revoke_and_audit_log(client, db, libw):
    out = new_key(client, libw)
    kid = out["website_key"]["id"]
    libw.as_(libw.admin)
    r = client.post(f"{API}/admin/website-keys/{kid}/revoke")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "revoked"
    db.expire_all()
    row = db.get(WebsiteApiKey, kid)
    assert row.revoked_by == libw.admin.id and row.revoked_at is not None
    actions = [a.action for a in db.scalars(select(AuditLog).where(AuditLog.object_id == kid).order_by(AuditLog.at))]
    assert actions == ["website_key.create", "website_key.revoke"]
    assert out["key"] not in str([a.after for a in db.scalars(select(AuditLog).where(AuditLog.object_id == kid))])
    assert client.post(f"{API}/admin/website-keys/{kid}/revoke").status_code == 409  # already revoked


def test_origins_and_limits_are_checked(client, libw):
    libw.as_(libw.admin)
    for bad in (["www.futransolutions.com"], ["https://www.futransolutions.com/library"], ["ftp://x.example"], ["https://*.example.com"], ["http://example.com"]):
        r = client.post(f"{API}/admin/website-keys", json={"name": "x", "allowed_origins": bad})
        assert r.status_code == 422, (bad, r.text)
    ok = client.post(f"{API}/admin/website-keys", json={"name": "Local preview", "allowed_origins": ["http://localhost:3000", "https://WWW.Example.com/"]})
    assert ok.status_code == 200, ok.text
    assert ok.json()["website_key"]["allowed_origins"] == ["http://localhost:3000", "https://www.example.com"]
    assert client.post(f"{API}/admin/website-keys", json={"name": "x", "allowed_origins": [], "rate_limit_per_minute": 0}).status_code == 422
    assert client.post(f"{API}/admin/website-keys", json={"name": "x", "allowed_origins": [], "rate_limit_per_minute": 5000}).status_code == 422
    assert client.post(f"{API}/admin/website-keys", json={"name": " ", "allowed_origins": []}).status_code == 422


def test_only_the_futran_admin_manages_website_keys(client, db, libw):
    kid = new_key(client, libw)["website_key"]["id"]
    for user, code in ((libw.chief, 403), (libw.aud, 403), (libw.sales, 403), (libw.caico, 404), (libw.cadmin, 404)):
        libw.as_(user)
        assert client.get(f"{API}/admin/website-keys").status_code in (403, 404), user.name
        assert client.post(f"{API}/admin/website-keys", json={"name": "x", "allowed_origins": []}).status_code in (code, 403, 404), user.name
        assert client.post(f"{API}/admin/website-keys/{kid}/revoke").status_code in (403, 404), user.name
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    assert client.get(f"{API}/admin/website-keys").status_code == 401
    assert db.get(WebsiteApiKey, kid).status == "active"


def test_unknown_key_is_404(client, libw):
    libw.as_(libw.admin)
    assert client.post(f"{API}/admin/website-keys/nope/revoke").status_code == 404
