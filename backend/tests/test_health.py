"""Kiểm thử tự động cho endpoint kiểm tra sức khỏe hệ thống (Health Check) - SCRUM-17 / S-03."""

from fastapi.testclient import TestClient


def test_health_check_returns_ok_and_connected_db(client: TestClient) -> None:
    """GET /health trả về 200 OK cùng trạng thái hệ thống và kết nối database."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"

    # Đảm bảo không làm lộ bất kỳ thông tin nhạy cảm nào (secret, connection string, password, path...)
    sensitive_keys = {"password", "secret", "database_url", "db_path", "config", "env"}
    assert not any(key in data for key in sensitive_keys)
