"""Cơ chế Rate Limiting chống dò quét mã lô hàng loạt cho Cổng truy xuất công khai (Story S-50).

Quy tắc nghiệp vụ:
- Theo dõi theo địa chỉ IP gọi đến.
- Cửa sổ trượt 60 giây.
- Một địa chỉ IP truy vấn quá 30 mã lô khác nhau trong vòng một phút sẽ bị chặn tạm thời (HTTP 429).
- Mã lô không tồn tại cũng được tính vào giới hạn để chống dò quét Brute-force mã QR.
"""

import threading
import time
from fastapi import HTTPException, status

RATE_LIMIT_WINDOW_SECONDS: float = 60.0
MAX_DISTINCT_BATCH_CODES_PER_MINUTE: int = 30

_lock = threading.Lock()
# Cấu trúc: {ip: list of (timestamp, batch_code)}
_IP_REQUEST_LOGS: dict[str, list[tuple[float, str]]] = {}


def clear_rate_limit_cache() -> None:
    """Xóa dữ liệu bộ đếm rate limit (phục vụ test)."""
    with _lock:
        _IP_REQUEST_LOGS.clear()


def check_scan_rate_limit(client_ip: str, batch_code: str) -> None:
    """Kiểm tra giới hạn tần suất dò quét mã lô theo địa chỉ IP.

    Args:
        client_ip: Địa chỉ IP của client gọi tới.
        batch_code: Mã lô nông sản đang được tra cứu.

    Raises:
        HTTPException 429: Nếu IP này đã tra cứu quá 30 mã lô khác nhau trong 60 giây gần nhất.
    """
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
