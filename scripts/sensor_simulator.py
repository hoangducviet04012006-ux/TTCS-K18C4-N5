"""Chương trình giả lập cảm biến nhiệt độ IoT (Task S-42 - AgriTrace).

Tác giả: Hoàng Anh Tú (Phân công Sprint 4)
Chức năng:
    - Tự động tạo dữ liệu nhiệt độ ngẫu nhiên trong khoảng 20°C - 40°C.
    - Định dạng bản tin theo chuẩn JSON (gồm sensor_id, temperature, timestamp, unit).
    - Gửi dữ liệu định kỳ mỗi 5 giây đến máy chủ API hoặc chạy ở chế độ giả lập (Mock).
    - Hiển thị trực quan dữ liệu và trạng thái gửi trên màn hình console.
    - Bắt và xử lý các lỗi truyền thông mạng an toàn, không làm dừng chương trình.
    - Cho phép người dùng dừng chương trình an toàn bằng tổ hợp phím Ctrl + C.
    - Thống kê tóm tắt dữ liệu khi kết thúc chương trình.
"""

import argparse
from datetime import datetime, timezone
import base64
import getpass
import os
import json
import random
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Đảm bảo console Windows hiển thị tốt ký tự tiếng Việt UTF-8
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Thử import thư viện requests; nếu môi trường chưa cài đặt, sử dụng thư viện chuẩn urllib.request
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.error
    import urllib.request
    HAS_REQUESTS = False


# ==============================================================================
# HẰNG SỐ CẤU HÌNH MẶC ĐỊNH
# ==============================================================================
DEFAULT_SENSOR_ID: str = "SENSOR-TEMP-01"
DEFAULT_INTERVAL_SECONDS: float = 5.0
DEFAULT_MIN_TEMPERATURE: float = 20.0
DEFAULT_MAX_TEMPERATURE: float = 40.0
DEFAULT_SERVER_URL: str = "http://127.0.0.1:8765/trips/active-container/{container_code}/readings"
DEFAULT_HTTP_TIMEOUT: float = 3.0


# ==============================================================================
# CÁC HÀM XỬ LÝ DỮ LIỆU CẢM BIẾN
# ==============================================================================
def generate_temperature(
    min_temp: float = DEFAULT_MIN_TEMPERATURE,
    max_temp: float = DEFAULT_MAX_TEMPERATURE
) -> float:
    """Sinh giá trị nhiệt độ ngẫu nhiên trong khoảng [min_temp, max_temp].

    Args:
        min_temp: Giá trị nhiệt độ nhỏ nhất (°C).
        max_temp: Giá trị nhiệt độ lớn nhất (°C).

    Returns:
        float: Giá trị nhiệt độ được làm tròn 1 chữ số thập phân.
    """
    if min_temp > max_temp:
        min_temp, max_temp = max_temp, min_temp
    raw_temp = random.uniform(min_temp, max_temp)
    return round(raw_temp, 1)


def create_sensor_payload(
    sensor_id: str,
    temperature: float,
    unit: str = "°C",
    timestamp: Optional[str] = None
) -> Dict[str, Any]:
    """Tạo bản tin dữ liệu cảm biến định dạng theo chuẩn dictionary (để serialize JSON).

    Mỗi bản tin gồm:
        - sensor_id: Mã định danh của cảm biến.
        - temperature: Giá trị nhiệt độ đo được.
        - timestamp: Thời điểm gửi dữ liệu (chuẩn ISO YYYY-MM-DD HH:MM:SS).
        - unit: Đơn vị đo nhiệt độ (mặc định là °C).

    Args:
        sensor_id: Mã cảm biến.
        temperature: Giá trị nhiệt độ đo được.
        unit: Đơn vị đo.
        timestamp: Chuỗi thời gian (nếu None sẽ lấy thời điểm hiện tại).

    Returns:
        dict: Bản tin dữ liệu cảm biến.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    recorded = datetime.fromisoformat(timestamp)
    recorded = recorded.astimezone(timezone.utc) if recorded.tzinfo else recorded.replace(tzinfo=timezone.utc)

    return {
        "sensor_id": sensor_id,
        "temperature": temperature,
        "unit": unit,
        "timestamp": timestamp,
        "recorded_at": recorded.isoformat()
    }


def serialize_payload_to_json(payload: Dict[str, Any]) -> str:
    """Chuyển đổi dữ liệu bản tin sang chuỗi JSON tiêu chuẩn.

    Args:
        payload: Dữ liệu bản tin dạng dict.

    Returns:
        str: Chuỗi định dạng JSON UTF-8.
    """
    return json.dumps(payload, ensure_ascii=False)


# ==============================================================================
# CÁC HÀM TRUYỀN DỮ LIỆU & GIẢ LẬP MÁY CHỦ
# ==============================================================================
def send_payload_http(
    payload: Dict[str, Any],
    server_url: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
    authorization: Optional[str] = None,
) -> Tuple[bool, Optional[int], str]:
    """Gửi bản tin JSON đến máy chủ qua giao thức HTTP POST.

    Hàm tự động ưu tiên thư viện `requests`, nếu chưa cài đặt sẽ tự động
    dùng `urllib.request` của thư viện chuẩn Python.

    Args:
        payload: Bản tin dữ liệu cần gửi.
        server_url: Địa chỉ endpoint API máy chủ nhận dữ liệu.
        timeout: Thời gian tối đa chờ phản hồi (giây).

    Returns:
        Tuple[bool, Optional[int], str]:
            - bool: Trạng thái gửi (True nếu thành công, False nếu lỗi).
            - Optional[int]: Mã trạng thái HTTP (200, 404, 500...) hoặc None nếu mất kết nối.
            - str: Thông điệp phản hồi hoặc mô tả lỗi chi tiết.
    """
    json_data = serialize_payload_to_json(payload)

    # Trường hợp 1: Sử dụng thư viện `requests`
    if HAS_REQUESTS:
        try:
            headers = {"Content-Type": "application/json; charset=utf-8"}
            if authorization:
                headers["Authorization"] = authorization
            response = requests.post(server_url, data=json_data.encode("utf-8"), headers=headers, timeout=timeout)
            if 200 <= response.status_code < 300:
                return True, response.status_code, "Gửi thành công đến API máy chủ"
            return False, response.status_code, f"Máy chủ trả về mã lỗi HTTP {response.status_code}"
        except requests.exceptions.ConnectionError:
            return False, None, f"Không thể kết nối tới máy chủ tại {server_url} (Connection Refused)"
        except requests.exceptions.Timeout:
            return False, None, f"Quá thời gian chờ phản hồi ({timeout}s)"
        except requests.exceptions.RequestException as exc:
            return False, None, f"Lỗi yêu cầu HTTP: {exc}"

    # Trường hợp 2: Sử dụng thư viện chuẩn `urllib.request` (không cần cài thêm package)
    try:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if authorization:
            headers["Authorization"] = authorization
        req = urllib.request.Request(
            server_url,
            data=json_data.encode("utf-8"),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = resp.getcode()
            if 200 <= status_code < 300:
                return True, status_code, "Gửi thành công đến API máy chủ (urllib)"
            return False, status_code, f"Máy chủ trả về mã HTTP {status_code}"
    except urllib.error.HTTPError as http_err:
        return False, http_err.code, f"Máy chủ trả về lỗi HTTP {http_err.code}"
    except urllib.error.URLError as url_err:
        return False, None, f"Không thể kết nối tới {server_url}: {url_err.reason}"
    except Exception as exc:
        return False, None, f"Lỗi gửi dữ liệu không xác định: {exc}"


def simulate_mock_send(payload: Dict[str, Any]) -> Tuple[bool, Optional[int], str]:
    """Chế độ giả lập gửi dữ liệu khi chưa có máy chủ thật.

    Mô phỏng phản hồi thành công tức thì của máy chủ nhận dữ liệu,
    giúp kiểm thử toàn bộ luồng hoạt động của chương trình mà không cần setup backend.

    Args:
        payload: Bản tin dữ liệu.

    Returns:
        Tuple[bool, int, str]: Kết quả mô phỏng (True, 200, thông báo).
    """
    # Tạo độ trễ mạng giả lập nhỏ từ 0.02 - 0.05 giây
    time.sleep(random.uniform(0.02, 0.05))
    return True, 200, "Mô phỏng tiếp nhận thành công (Chế độ giả lập máy chủ)"


# ==============================================================================
# CÁC HÀM HIỂN THỊ MÀN HÌNH & THỐNG KÊ
# ==============================================================================
def display_transmission_log(
    sequence: int,
    payload: Dict[str, Any],
    success: bool,
    status_code: Optional[int],
    message: str,
    is_mock: bool = False
) -> None:
    """In thông tin bản tin và trạng thái gửi trực quan lên màn hình console.

    Args:
        sequence: Số thứ tự bản tin (bắt đầu từ 1).
        payload: Nội dung bản tin JSON.
        success: Trạng thái thành công hay thất bại.
        status_code: Mã HTTP phản hồi (nếu có).
        message: Chi tiết thông điệp.
        is_mock: Có đang chạy ở chế độ giả lập hay không.
    """
    tag = "[MOCK OK]" if is_mock and success else ("[SUCCESS]" if success else "[ERROR]  ")
    http_tag = f"HTTP {status_code}" if status_code is not None else "NO RESPONSE"
    json_str = serialize_payload_to_json(payload)

    print(f"{tag} #{sequence:03d} | {payload['timestamp']} | "
          f"{payload['sensor_id']} | Nhiệt độ: {payload['temperature']:>4.1f}{payload['unit']} | "
          f"[{http_tag}] {message}")
    print(f"       -> JSON Payload: {json_str}")
    print("-" * 90)


def print_summary_statistics(
    total_messages: int,
    successful_messages: int,
    failed_messages: int,
    temperatures: List[float]
) -> None:
    """In báo cáo thống kê tóm tắt quá trình chạy khi người dùng dừng chương trình.

    Args:
        total_messages: Tổng số bản tin đã tạo.
        successful_messages: Số bản tin gửi thành công.
        failed_messages: Số bản tin gửi thất bại.
        temperatures: Danh sách tất cả các giá trị nhiệt độ đã tạo.
    """
    print("\n" + "=" * 90)
    print("                 BÁO CÁO TỔNG KẾT CHƯƠNG TRÌNH GIẢ LẬP CẢM BIẾN (S-42)")
    print("=" * 90)
    print(f"  * Tổng số bản tin đã tạo:     {total_messages}")
    print(f"  * Số bản tin gửi thành công:  {successful_messages}")
    print(f"  * Số bản tin gửi thất bại:    {failed_messages}")

    if total_messages > 0:
        success_rate = (successful_messages / total_messages) * 100
        print(f"  * Tỷ lệ gửi thành công:       {success_rate:.1f}%")

    if temperatures:
        avg_temp = sum(temperatures) / len(temperatures)
        min_temp = min(temperatures)
        max_temp = max(temperatures)
        print(f"  * Nhiệt độ trung bình:        {avg_temp:.2f}°C")
        print(f"  * Nhiệt độ thấp nhất đo được: {min_temp:.1f}°C")
        print(f"  * Nhiệt độ cao nhất đo được:  {max_temp:.1f}°C")

    print("=" * 90)
    print("Chương trình đã dừng an toàn. Cảm ơn bạn đã sử dụng!\n")


# ==============================================================================
# HÀM THỰC THI CHÍNH CỦA BỘ GIẢ LẬP
# ==============================================================================
def run_sensor_simulator(
    sensor_id: str = DEFAULT_SENSOR_ID,
    interval: float = DEFAULT_INTERVAL_SECONDS,
    min_temp: float = DEFAULT_MIN_TEMPERATURE,
    max_temp: float = DEFAULT_MAX_TEMPERATURE,
    server_url: str = DEFAULT_SERVER_URL,
    mock_mode: bool = False,
    max_count: Optional[int] = None,
    authorization: Optional[str] = None,
) -> None:
    """Chạy vòng lặp giả lập cảm biến: tạo dữ liệu, gửi định kỳ, xử lý lỗi và ngắt phím.

    Args:
        sensor_id: Mã định danh của cảm biến (ví dụ: SENSOR-TEMP-01).
        interval: Chu kỳ gửi dữ liệu tính bằng giây (mặc định: 5.0).
        min_temp: Ngưỡng nhiệt độ nhỏ nhất (mặc định: 20.0°C).
        max_temp: Ngưỡng nhiệt độ lớn nhất (mặc định: 40.0°C).
        server_url: Địa chỉ API endpoint nhận dữ liệu.
        mock_mode: Nếu True, chạy ở chế độ giả lập phản hồi (không gửi mạng thật).
        max_count: Số bản tin tối đa cần gửi (dùng cho test tự động, None nếu chạy vô hạn).
    """
    mode_text = "GIẢ LẬP MÁY CHỦ (Offline Mock Mode)" if mock_mode else f"KẾT NỐI API THỰC TẾ ({server_url})"
    http_engine = "requests" if HAS_REQUESTS else "urllib.request (standard library)"

    print("=" * 90)
    print("      KHỞI ĐỘNG HỆ THỐNG GIẢ LẬP CẢM BIẾN NHIỆT ĐỘ IOT - AGRITRACE (TASK S-42)")
    print("=" * 90)
    print(f"  - Mã cảm biến:           {sensor_id}")
    print(f"  - Khoảng nhiệt độ:       {min_temp}°C -> {max_temp}°C")
    print(f"  - Chu kỳ gửi:            {interval} giây/lần")
    print(f"  - Chế độ hoạt động:      {mode_text}")
    print(f"  - Thư viện HTTP:         {http_engine}")
    print("  - Phím tắt dừng:         Nhấn [Ctrl + C] trên bàn phím bất kỳ lúc nào để dừng an toàn")
    print("=" * 90 + "\n")

    sequence: int = 0
    successful_count: int = 0
    failed_count: int = 0
    temperature_history: List[float] = []

    try:
        while True:
            sequence += 1

            # 1. Tạo giá trị nhiệt độ ngẫu nhiên từ 20°C đến 40°C
            current_temp = generate_temperature(min_temp=min_temp, max_temp=max_temp)
            temperature_history.append(current_temp)

            # 2. Đóng gói bản tin JSON
            payload = create_sensor_payload(sensor_id=sensor_id, temperature=current_temp)

            # 3. Gửi bản tin (chế độ giả lập hoặc gửi HTTP thật)
            if mock_mode:
                success, status_code, message = simulate_mock_send(payload)
            else:
                success, status_code, message = send_payload_http(
                    payload=payload,
                    server_url=server_url,
                    timeout=DEFAULT_HTTP_TIMEOUT,
                    authorization=authorization,
                )

            # 4. Cập nhật số liệu thống kê
            if success:
                successful_count += 1
            else:
                failed_count += 1

            # 5. Hiển thị thông tin lên màn hình console
            display_transmission_log(
                sequence=sequence,
                payload=payload,
                success=success,
                status_code=status_code,
                message=message,
                is_mock=mock_mode
            )

            # 6. Kiểm tra điều kiện dừng nếu có đặt số lượng bản tin tối đa
            if max_count is not None and sequence >= max_count:
                print(f"\n[THÔNG BÁO] Đã hoàn thành gửi đủ {max_count} bản tin theo cấu hình.")
                break

            # 7. Tạm dừng đúng chu kỳ cấu hình (5 giây) trước khi gửi bản tin kế tiếp
            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\n[NGẮT BÀN PHÍM] Nhận tín hiệu dừng từ người dùng (Ctrl + C)... Đang kết thúc an toàn.")

    finally:
        # Luôn luôn in thống kê tổng kết khi thoát
        print_summary_statistics(
            total_messages=sequence,
            successful_messages=successful_count,
            failed_messages=failed_count,
            temperatures=temperature_history
        )


# ==============================================================================
# HÀM XỬ LÝ THAM SỐ DÒNG LỆNH (ARGPARSE)
# ==============================================================================
def parse_arguments() -> argparse.Namespace:
    """Phân tích các tham số truyền vào từ dòng lệnh (Command Line Interface)."""
    parser = argparse.ArgumentParser(
        description="Chương trình Python giả lập cảm biến nhiệt độ gửi dữ liệu định kỳ (AgriTrace S-42)."
    )
    parser.add_argument(
        "--id",
        type=str,
        default=DEFAULT_SENSOR_ID,
        help=f"Mã cảm biến (mặc định: {DEFAULT_SENSOR_ID})"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"Chu kỳ gửi dữ liệu tính theo giây (mặc định: {DEFAULT_INTERVAL_SECONDS}s)"
    )
    parser.add_argument(
        "--min-temp",
        type=float,
        default=DEFAULT_MIN_TEMPERATURE,
        help=f"Nhiệt độ tối thiểu (mặc định: {DEFAULT_MIN_TEMPERATURE}°C)"
    )
    parser.add_argument(
        "--max-temp",
        type=float,
        default=DEFAULT_MAX_TEMPERATURE,
        help=f"Nhiệt độ tối đa (mặc định: {DEFAULT_MAX_TEMPERATURE}°C)"
    )
    parser.add_argument(
        "--url",
        type=str,
        default=DEFAULT_SERVER_URL,
        help=f"Địa chỉ API máy chủ nhận dữ liệu (mặc định: {DEFAULT_SERVER_URL})"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Bật chế độ giả lập máy chủ nội bộ (không cần server thật, thích hợp kiểm thử độc lập)"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Số lượng bản tin cần gửi trước khi tự dừng (mặc định: chạy vô hạn đến khi bấm Ctrl+C)"
    )
    parser.add_argument("--container", help="Mã thùng lạnh của chuyến đang chạy")
    parser.add_argument("--username", default=os.getenv("AGRITRACE_SENSOR_USERNAME"))
    parser.add_argument("--replay", help="JSON list nhiệt độ/recorded_at để kiểm thử dữ liệu lịch sử")
    return parser.parse_args()


# ==============================================================================
# ĐIỂM VÀO CHƯƠNG TRÌNH (ENTRY POINT)
# ==============================================================================
def main() -> None:
    """Điểm vào chính của script."""
    args = parse_arguments()
    authorization = None
    if not args.mock:
        if "{container_code}" in args.url and not args.container:
            raise SystemExit("Cần --container hoặc --url đầy đủ của API readings")
        if not args.username:
            raise SystemExit("Cần --username hoặc AGRITRACE_SENSOR_USERNAME")
        password = os.getenv("AGRITRACE_SENSOR_PASSWORD") or getpass.getpass("Mật khẩu cảm biến: ")
        authorization = "Basic " + base64.b64encode(f"{args.username}:{password}".encode()).decode()
        from urllib.parse import quote
        args.url = args.url.replace("{container_code}", quote(args.container or "", safe=""))
    if args.replay:
        with open(args.replay, encoding="utf-8-sig") as stream:
            samples = json.load(stream)
        for sample in samples:
            success, code, message = (simulate_mock_send(sample) if args.mock else
                                      send_payload_http(sample, args.url, authorization=authorization))
            print(f"HTTP {code}: {message}")
            if not success:
                raise SystemExit(1)
        return

    run_sensor_simulator(
        sensor_id=args.id,
        interval=args.interval,
        min_temp=args.min_temp,
        max_temp=args.max_temp,
        server_url=args.url,
        mock_mode=args.mock,
        max_count=args.count,
        authorization=authorization,
    )


if __name__ == "__main__":
    main()
