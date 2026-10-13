def test_health_reports_status_and_test_mode(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "test_mode": True,
        "data_region": "us-east",
        "version": "0.1.0",
    }


def test_unknown_api_path_is_json_404(client):
    r = client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert "detail" in r.json()
