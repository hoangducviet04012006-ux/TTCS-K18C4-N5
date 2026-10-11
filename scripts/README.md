# Script nội bộ AgriTrace

Người dùng nhấp đúp `../start_demo.bat`. Không cần chạy các script ở đây trực tiếp.

- `start_demo.ps1`: hỗ trợ launcher Sprint 1–3; chỉ dùng database hiện hữu `.sprint123-trial/demo_sprint123.db`, tự chọn cổng trống và mở trình duyệt.
- `start_recall_demo.ps1`: script thử nghiệm Recall đã có, giữ nguyên nghiệp vụ; chỉ cập nhật cách xác định thư mục gốc sau khi di chuyển. Không thuộc demo Sprint 1–3.
- `seed_demo.bat`: công cụ seed cũ, lưu lại để bàn giao; không chạy cho demo hiện tại. Script này không có bảo vệ profile riêng và có thể dùng database mặc định của Backend. Không chạy với `backend/ttcs.db`.

Không seed, reset, migration hoặc đổi mật khẩu khi khởi động demo. Không ghi mật khẩu vào tài liệu, mã nguồn hoặc log. Python runner vẫn nằm trong `backend/scripts/` để giữ nguyên cơ chế import hiện có.
