"""Tiện ích sinh mã lô nông sản ngẫu nhiên an toàn (T-19).

Quy tắc:
- Sử dụng module ``secrets`` để đảm bảo tính ngẫu nhiên an toàn mật mã học.
- Độ dài mã: 8 ký tự.
- Bảng ký tự loại bỏ hoàn toàn các ký tự dễ gây nhầm lẫn khi in và đọc trên tem:
  CẤM dùng '0', 'O', '1', 'I', 'L'.
"""

import secrets
from typing import Final

# Bảng ký tự cho phép: 31 ký tự (8 chữ số: 2-9, 23 chữ cái in hoa: A-Z bỏ O, I, L)
BATCH_CODE_CHARSET: Final[str] = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
DEFAULT_CODE_LENGTH: Final[int] = 8

# Tập ký tự bị cấm để kiểm thử xác nhận
FORBIDDEN_CHARS: Final[set[str]] = {"0", "O", "1", "I", "L"}


def generate_batch_code(length: int = DEFAULT_CODE_LENGTH) -> str:
    """Tạo mã lô ngẫu nhiên an toàn, không chứa ký tự dễ nhầm lẫn.

    Args:
        length: Độ dài mã cần sinh (mặc định 8 ký tự).

    Returns:
        str: Chuỗi mã lô ngẫu nhiên (ví dụ: 'K7H9P2XA').
    """
    return "".join(secrets.choice(BATCH_CODE_CHARSET) for _ in range(length))
