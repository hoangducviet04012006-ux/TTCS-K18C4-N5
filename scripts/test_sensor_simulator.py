"""Bộ kiểm thử đơn vị (Unit Tests) cho chương trình giả lập cảm biến nhiệt độ (Task S-42).

Sử dụng thư viện chuẩn `unittest` của Python, không cần cài đặt thêm bất kỳ package nào.
Để chạy kiểm thử:
    python scripts/test_sensor_simulator.py
"""

from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import sys
import threading
import unittest

# Đảm bảo console Windows UTF-8
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Import các hàm từ sensor_simulator
from sensor_simulator import (
    create_sensor_payload,
    generate_temperature,
    send_payload_http,
    serialize_payload_to_json,
    simulate_mock_send,
)


class EphemeralTestServerHandler(BaseHTTPRequestHandler):
    """Handler phục vụ kiểm thử nhận HTTP POST."""

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/sensor/temperature":
            length = int(self.headers.get("Content-Length", 0))
            data = self.rfile.read(length)
            try:
                json.loads(data.decode("utf-8"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
            except Exception:
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format_str: str, *args) -> None:
        return


class TestSensorSimulator(unittest.TestCase):
    """Tập hợp các ca kiểm thử cho hệ thống giả lập cảm biến."""

    def test_tc01_generate_temperature_in_default_range(self) -> None:
        """TC-01: Kiểm tra nhiệt độ ngẫu nhiên luôn nằm trong khoảng [20.0, 40.0]."""
        for _ in range(100):
            temp = generate_temperature(20.0, 40.0)
            self.assertGreaterEqual(temp, 20.0, f"Nhiệt độ {temp} nhỏ hơn ngưỡng tối thiểu 20.0°C")
            self.assertLessEqual(temp, 40.0, f"Nhiệt độ {temp} lớn hơn ngưỡng tối đa 40.0°C")
            # Kiểm tra làm tròn tối đa 1 chữ số thập phân
            self.assertEqual(temp, round(temp, 1))

    def test_tc02_generate_temperature_custom_range(self) -> None:
        """TC-02: Kiểm tra khả năng tùy biến khoảng nhiệt độ (ví dụ 10.0°C - 15.0°C)."""
        for _ in range(50):
            temp = generate_temperature(10.0, 15.0)
            self.assertGreaterEqual(temp, 10.0)
            self.assertLessEqual(temp, 15.0)

    def test_tc03_create_payload_structure(self) -> None:
        """TC-03: Kiểm tra cấu trúc bản tin gồm đầy đủ các trường yêu cầu."""
        sensor_id = "TEMP-DHT22-TEST"
        temp = 28.5
        payload = create_sensor_payload(sensor_id=sensor_id, temperature=temp)

        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["sensor_id"], sensor_id)
        self.assertEqual(payload["temperature"], temp)
        self.assertEqual(payload["unit"], "°C")
        self.assertIn("timestamp", payload)

        # Kiểm tra định dạng thời gian có thể parse được
        parsed_time = datetime.strptime(payload["timestamp"], "%Y-%m-%d %H:%M:%S")
        self.assertIsInstance(parsed_time, datetime)

    def test_tc04_json_serialization(self) -> None:
        """TC-04: Kiểm tra bản tin được định dạng thành JSON hợp lệ."""
        payload = create_sensor_payload(sensor_id="DHT22-01", temperature=32.4)
        json_str = serialize_payload_to_json(payload)

        self.assertIsInstance(json_str, str)
        # Parse ngược lại để đảm bảo JSON đúng chuẩn
        restored = json.loads(json_str)
        self.assertEqual(restored["sensor_id"], "DHT22-01")
        self.assertEqual(restored["temperature"], 32.4)
        self.assertEqual(restored["unit"], "°C")

    def test_tc05_mock_mode_behavior(self) -> None:
        """TC-05: Kiểm tra chế độ giả lập phản hồi thành công (HTTP 200)."""
        payload = create_sensor_payload(sensor_id="DHT22-MOCK", temperature=25.0)
        success, status_code, message = simulate_mock_send(payload)

        self.assertTrue(success)
        self.assertEqual(status_code, 200)
        self.assertIn("Mô phỏng", message)

    def test_tc06_network_error_graceful_handling(self) -> None:
        """TC-06: Kiểm tra xử lý lỗi an toàn khi máy chủ không phản hồi (Connection Refused)."""
        payload = create_sensor_payload(sensor_id="DHT22-FAIL", temperature=30.0)
        # Gửi tới cổng không mở
        success, status_code, message = send_payload_http(
            payload=payload,
            server_url="http://127.0.0.1:59999/api/sensor/temperature",
            timeout=1.0
        )

        # Đảm bảo không crash, trả về trạng thái thất bại và thông báo rõ ràng
        self.assertFalse(success)
        self.assertIsNone(status_code)
        self.assertTrue(len(message) > 0)

    def test_tc07_real_http_transmission_with_local_test_server(self) -> None:
        """TC-07: Kiểm tra truyền tin HTTP POST thực tế tới một HTTP Server thử nghiệm."""
        server = HTTPServer(("127.0.0.1", 0), EphemeralTestServerHandler)
        port = server.server_port
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        try:
            url = f"http://127.0.0.1:{port}/api/sensor/temperature"
            payload = create_sensor_payload(sensor_id="DHT22-REAL", temperature=27.8)
            success, status_code, message = send_payload_http(payload=payload, server_url=url, timeout=2.0)

            self.assertTrue(success)
            self.assertEqual(status_code, 200)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    print("=" * 70)
    print("  CHẠY BỘ KIỂM THỬ ĐƠN VỊ (UNIT TESTS) - S-42 CẢM BIẾN NHIỆT ĐỘ")
    print("=" * 70)
    unittest.main(verbosity=2)
