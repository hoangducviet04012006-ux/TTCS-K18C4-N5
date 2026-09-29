"""TTCS K18C4 - Backend package.

Đề tài: Truy xuất nguồn gốc và giám sát chuỗi lạnh nông sản.

Package `app` chứa toàn bộ mã nguồn backend FastAPI:
- ``main``      : khởi tạo ứng dụng FastAPI và đăng ký routers.
- ``database``  : cấu hình kết nối SQLite + SQLAlchemy.
- ``models``    : khai báo ORM models (chưa có bảng nào ở Sprint 1).
- ``schemas``   : khai báo Pydantic schemas cho request/response.
- ``routers``   : nhóm các endpoint theo nghiệp vụ.
"""

__version__ = "0.1.0"
