def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200

    payload = response.get_json()
    assert payload["status"] in {"healthy", "ok"}
    assert "timestamp" in payload and payload["timestamp"]
