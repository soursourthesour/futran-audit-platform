"""Review 11-25 #2: a request body larger than the upload limit is refused before it is read, signed in or not, so
nobody can fill the disk or tie up the server by sending huge bodies to an upload route."""
import pytest

LIMIT_MB = 1


@pytest.fixture
def small(client, settings):
    client.app.state.settings = settings.model_copy(update={"max_upload_mb": LIMIT_MB})
    return client


def test_a_declared_oversized_body_is_refused_unread(small):
    body = b"x" * ((LIMIT_MB + 3) * 1024 * 1024)
    r = small.post("/api/v1/systems/nope/evidence", content=body, headers={"content-type": "application/octet-stream"})
    assert r.status_code == 413
    assert "limit" in r.json()["detail"]


def test_a_chunked_oversized_body_is_cut_off(small):
    sent = {"n": 0}

    def chunks():  # a multipart upload with no Content-Length: the form is read before the sign-in check
        yield b'--BOUNDARY\r\nContent-Disposition: form-data; name="file"; filename="big.pdf"\r\nContent-Type: application/pdf\r\n\r\n'
        for _ in range(LIMIT_MB * 16 + 64):  # 64 KB chunks, well past the limit
            sent["n"] += 1
            yield b"y" * 65536
        yield b"\r\n--BOUNDARY--\r\n"

    r = small.post("/api/v1/systems/nope/evidence", content=chunks(), headers={"content-type": "multipart/form-data; boundary=BOUNDARY"})
    assert r.status_code == 413


def test_normal_requests_pass(small):
    assert small.get("/api/v1/health").status_code == 200
    r = small.post("/api/v1/auth/login", json={"email": "x@y.com", "password": "nope"})
    assert r.status_code == 401
