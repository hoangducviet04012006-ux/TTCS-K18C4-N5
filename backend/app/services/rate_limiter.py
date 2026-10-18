"""Cơ chế Rate Limiting chống dò quét mã lô hàng loạt cho Cổng truy xuất công khai (Story S-50).

Quy tắc bảo mật:
- Địa chỉ peer IP trực tiếp từ TCP socket (request.client.host) là nguồn kiểm chứng thực tế.
- Header X-Forwarded-For hoặc X-Real-IP CHỈ được tin cậy khi kết nối đến từ reverse proxy đáng tin cậy
  (127.0.0.1, ::1, localhost, hoặc testclient).
- Nếu client kết nối trực tiếp từ mạng ngoài không qua trusted proxy, hệ thống bỏ qua header X-Forwarded-For
  để ngăn chặn triệt để hành vi giả mạo header nhằm bypass rate limit.
- Cửa sổ trượt 60 giây: Một địa chỉ IP truy vấn quá 30 mã lô khác nhau trong 1 phút sẽ bị chặn tạm thời (HTTP 429).
- Mã lô không tồn tại cũng được tính vào giới hạn để chống tấn công Brute-force mã QR.
"""

import threading
import time
from typing import Union
from fastapi import HTTPException, Request, status

RATE_LIMIT_WINDOW_SECONDS: float = 60.0
MAX_DISTINCT_BATCH_CODES_PER_MINUTE: int = 30
TRUSTED_PROXIES: set[str] = {"127.0.0.1", "::1", "localhost", "testclient"}

_lock = threading.Lock()
# Cấu trúc: {ip: list of (timestamp, batch_code)}
_IP_REQUEST_LOGS: dict[str, list[tuple[float, str]]] = {}


def clear_rate_limit_cache() -> None:
    """Xóa dữ liệu bộ đếm rate limit (phục vụ test)."""
    with _lock:
        _IP_REQUEST_LOGS.clear()


def get_trusted_client_ip(request: Request) -> str:
    """Xác định địa chỉ IP của client một cách an toàn, chống giả mạo header X-Forwarded-For."""
    peer_ip = request.client.host if request.client else "127.0.0.1"

    # Nếu kết nối KHÔNG đến từ reverse proxy tin cậy, tuyệt đối không tin header client tự gửi
    if peer_ip not in TRUSTED_PROXIES:
        return peer_ip

    # Khi kết nối từ proxy tin cậy (như Nginx nội bộ / test runner), lấy IP thực từ header
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first_ip = forwarded.split(",")[0].strip()
        if first_ip:
            return first_ip

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    return peer_ip


def check_scan_rate_limit(client: Union[str, Request], batch_code: str) -> None:
    """Kiểm tra giới hạn tần suất dò quét mã lô theo địa chỉ IP.

    Args:
        client: Request object hoặc chuỗi địa chỉ IP client.
        batch_code: Mã lô nông sản đang được tra cứu.

    Raises:
        HTTPException 429: Nếu IP này đã tra cứu quá 30 mã lô khác nhau trong 60 giây gần nhất.
    """
    if isinstance(client, Request):
        client_ip = get_trusted_client_ip(client)
    else:
        client_ip = str(client).strip()

    now = time.time()
    code_normalized = str(batch_code).strip().upper()

    with _lock:
        logs = _IP_REQUEST_LOGS.setdefault(client_ip, [])

        # 1. Loại bỏ các bản ghi quá 60 giây
        cutoff = now - RATE_LIMIT_WINDOW_SECONDS
        logs[:] = [(ts, code) for ts, code in logs if ts >= cutoff]

        # 2. Tập hợp các mã lô khác nhau đã truy vấn trong cửa sổ
        distinct_codes = {code for _, code in logs}

        # 3. Nếu mã hiện tại chưa có trong tập và số mã đã đạt ngưỡng 30 -> Chặn 429
        if code_normalized not in distinct_codes and len(distinct_codes) >= MAX_DISTINCT_BATCH_CODES_PER_MINUTE:
            # Ghi nhận lượt vi phạm để tiếp tục chặn
            logs.append((now, code_normalized))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Địa chỉ IP của bạn đã tra cứu vượt quá 30 mã lô khác nhau trong 1 phút. Vui lòng thử lại sau 60 giây.",
                headers={"Retry-After": "60"},
            )

        # 4. Ghi nhận lượt tra cứu hợp lệ
        logs.append((now, code_normalized))
