"""Máy chủ HTTP mini nhận dữ liệu cảm biến IoT (Mock Server - Task S-42 AgriTrace).

Tác giả: Hoàng Anh Tú (Phân công Sprint 4)
Chức năng:
    - Lắng nghe HTTP POST tại endpoint: /api/sensor/temperature
    - Tiếp nhận và phân tích (parse) bản tin JSON từ cảm biến nhiệt độ.
    - Hiển thị trực quan dữ liệu tiếp nhận lên màn hình.
    - Trả về phản hồi HTTP 200 JSON cho cảm biến.
    - Sử dụng hoàn toàn thư viện chuẩn `http.server`, không phụ thuộc bất kỳ package ngoài nào.
"""

from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import sys

# Đảm bảo console Windows in ký tự tiếng Việt UTF-8 không bị lỗi charmap
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

HOST: str = "127.0.0.1"
PORT: int = 5000
EXPECTED_ENDPOINT: str = "/api/sensor/temperature"


class SensorDataReceiverHandler(BaseHTTPRequestHandler):
    """Bộ xử lý HTTP tiếp nhận bản tin JSON từ các thiết bị cảm biến nhiệt độ."""

    def do_POST(self) -> None:  # noqa: N802
        """Xử lý yêu cầu HTTP POST từ cảm biến."""
        if self.path != EXPECTED_ENDPOINT:
            self.send_response(404)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            err_body = json.dumps({"error": f"Endpoint không tồn tại. Vui lòng gửi tới {EXPECTED_ENDPOINT}"})
            self.wfile.write(err_body.encode("utf-8"))
            return

        # Đọc dữ liệu từ body của HTTP POST
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        try:
            payload = json.loads(post_data.decode("utf-8"))
            received_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # In thông tin nhận được lên màn hình máy chủ
            sensor_id = payload.get("sensor_id", "N/A")
            temperature = payload.get("temperature", "N/A")
            unit = payload.get("unit", "°C")
            sent_time = payload.get("timestamp", "N/A")

            print(f"[RECEIVER] [{received_time}] Tiếp nhận thành công từ {sensor_id}: "
                  f"Nhiệt độ = {temperature}{unit} (Thời gian gửi: {sent_time})")

            # Trả về phản hồi HTTP 200 cho cảm biến
            response_data = {
                "status": "success",
                "message": "Dữ liệu cảm biến đã được tiếp nhận thành công",
                "received_at": received_time
            }
            body = json.dumps(response_data, ensure_ascii=False).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        except json.JSONDecodeError:
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            err_body = json.dumps({"error": "Dữ liệu gửi lên không phải JSON hợp lệ"}).encode("utf-8")
            self.wfile.write(err_body)

    def log_message(self, format_str: str, *args) -> None:
        """Tắt log mặc định của BaseHTTPRequestHandler để màn hình sạch sẽ."""
        return


def run_mock_server(host: str = HOST, port: int = PORT) -> None:
    """Khởi động máy chủ HTTP lắng nghe dữ liệu từ cảm biến."""
    server_address = (host, port)
    httpd = HTTPServer(server_address, SensorDataReceiverHandler)

    print("=" * 80)
    print("      MÁY CHỦ MẪU TIẾP NHẬN DỮ LIỆU CẢM BIẾN IOT (MOCK RECEIVER - S-42)")
    print("=" * 80)
    print(f"  - Địa chỉ máy chủ:   http://{host}:{port}")
    print(f"  - Endpoint tiếp nhận: {EXPECTED_ENDPOINT}")
    print("  - Đang chờ dữ liệu từ sensor_simulator.py...")
    print("  - Nhấn [Ctrl + C] để dừng máy chủ bất cứ lúc nào.")
    print("=" * 80 + "\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[THÔNG BÁO] Đang tắt máy chủ tiếp nhận dữ liệu...")
    finally:
        httpd.server_close()
        print("[THÔNG BÁO] Máy chủ đã dừng hoàn toàn.\n")


if __name__ == "__main__":
    run_mock_server()
