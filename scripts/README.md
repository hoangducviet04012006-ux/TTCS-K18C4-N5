# Cấu trúc Thư mục Scripts - AgriTrace (Sprint 4)

Hệ thống AgriTrace hiện tại đã được chuẩn hóa theo mô hình một launcher duy nhất ở thư mục gốc:

- Người dùng cuối và quản trị viên chỉ cần nhấp đúp file **`start.bat`** ở thư mục gốc để khởi chạy toàn bộ hệ thống.
- Khi cần dừng hệ thống từ scripts, chạy **`scripts/stop_app.bat`** hoặc **`scripts/stop_app.ps1`**.

## Danh mục các tệp tin trong thư mục `scripts/`:

1. **`start_app.ps1`**:
   - Bộ điều khiển khởi chạy chính cho ứng dụng AgriTrace.
   - Kết nối duy nhất tới cơ sở dữ liệu hợp nhất `data/agritrace.db`.
   - Tự động dò tìm cổng trống (dải 8765–8865) mà không dừng hay chiếm dụng tiến trình của ứng dụng khác.
   - Xác thực ứng dụng (fingerprint), đường dẫn code root và đường dẫn database trước khi mở trình duyệt.
   - Hỗ trợ tham số `-TestMode` để kiểm tra khởi động, tự động xác thực và tắt an toàn phục vụ CI/CD.

2. **`stop_app.ps1` / `stop_app.bat`**:
   - Dò quét và dừng chính xác tiến trình AgriTrace của dự án hiện tại dựa trên chữ ký `/system-info`.
   - Tuyệt đối không can thiệp vào các tiến trình khác trên hệ thống.

3. **`maintenance/`**:
   - Chứa các công cụ bảo trì và khôi phục: `restore_practice.bat`, `stop_practice.bat`, `seed_demo.bat`.

4. **`maintenance/legacy_launchers/`**:
   - Lưu trữ các launcher thử nghiệm cũ (`start_demo.bat`, `start_integrated_demo.bat`, `start_practice.bat`, `start_practice_TH2.bat`, v.v.) nhằm giữ nguyên tính toàn vẹn tài nguyên nhưng không làm rối thư mục gốc.
