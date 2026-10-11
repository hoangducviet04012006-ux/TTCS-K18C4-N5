# Báo cáo tổ chức lại dự án AgriTrace — 10/10/2026

Đã giữ một bộ code chính tại `D:\TTCS_K23C_N5\TTCS-K18C4-N5`. Thư mục gốc chỉ còn **một launcher dành cho người dùng: `start_demo.bat`**. Không viết lại Backend/Frontend hoặc phát triển thêm nghiệp vụ.

## Cây thư mục trước và sau

Các mục dữ liệu dưới đây giữ nguyên vị trí; cây rút gọn không liệt kê từng file con.

```text
TRƯỚC                            SAU
TTCS-K18C4-N5/                   TTCS-K18C4-N5/
├── start_demo.bat                ├── start_demo.bat
├── start_demo.ps1                ├── scripts/
├── start_recall_demo.ps1         │   ├── start_demo.ps1
├── seed_demo.bat                 │   ├── start_recall_demo.ps1
├── backend/                     │   ├── seed_demo.bat
├── frontend/                    │   └── README.md
├── docs/qa/                     ├── tools/backups/organization-20261010-174329/
├── .sprint123-trial/             ├── backend/
├── .recall-trial/                ├── frontend/
├── .demo-logs/                   ├── docs/qa/
├── .git/ và .github/             ├── .sprint123-trial/
└── cấu hình phát triển          ├── .recall-trial/
                                 ├── .demo-logs/
                                 ├── .git/ và .github/
                                 └── cấu hình phát triển
```

Danh sách đầy đủ các mục ở gốc được lưu trong `qa/organization_tree_before.txt` và `qa/organization_tree_after.txt`.

## File di chuyển

Tất cả đường dẫn trong bảng tương đối với thư mục code chính nêu trên.

| Đường dẫn cũ | Đường dẫn mới | Điều chỉnh |
| --- | --- | --- |
| `start_demo.ps1` | `scripts/start_demo.ps1` | Xác định gốc bằng thư mục cha của `scripts`; từ chối database khác `demo_sprint123.db` |
| `start_recall_demo.ps1` | `scripts/start_recall_demo.ps1` | Chỉ đổi cách xác định gốc sau di chuyển; không thay đổi nghiệp vụ Recall |
| `seed_demo.bat` | `scripts/seed_demo.bat` | Đổi thư mục làm việc thành `scripts/../backend`; không thực thi seed |

File sửa thêm: `start_demo.bat`, `README.md`, `docs/DEMO.md`, `docs/COMPLETION_REPORT.md`, `docs/DEMO_PASSWORD_UPDATE_REPORT.md`, `docs/DEMO_STANDARDIZATION_REPORT.md`. Các báo cáo lịch sử ghi rõ việc cập nhật đường dẫn và hướng dẫn seed cũ không áp dụng cho demo hiện tại.

File mới: `scripts/README.md`, `docs/PROJECT_STRUCTURE.md`, báo cáo này và `docs/qa/organization_db_audit.py`. Bằng chứng mới có tiền tố `docs/qa/organization_*`: snapshot database/schema/nội dung bảng trước/sau, snapshot code Recall, cây thư mục, kết quả Backend/browser/launcher và thông tin instance thử nghiệm. Bộ browser hiện có cũng cập nhật `dashboard_browser_results.json` và ảnh `dashboard-*.png`.

Không di chuyển database, trial, log hoặc backup hiện hữu. Chúng đã được tách riêng theo mục đích; di chuyển sẽ tăng rủi ro tham chiếu mà không cải thiện cách chạy cho người dùng. Python runner ở `backend/scripts/` giữ nguyên để không ảnh hưởng import/module. Launcher phát triển trong Backend/Frontend vẫn được giữ cho người phát triển. Không tạo bản sao ứng dụng.

## Sao lưu trước thay đổi

Đã sao lưu 9 file script/tài liệu cần thay đổi vào `tools/backups/organization-20261010-174329/`, giữ đường dẫn tương đối và xác minh SHA-256 từng bản sao bằng `manifest.json`. Không sao chép database hoặc file thông tin đăng nhập local vào bản sao lưu này. Git ignore đã được kiểm tra cho backup, database và `credentials.local`; không chạy Git add/commit.

## Kết quả kiểm thử

| Kiểm tra | Kết quả |
| --- | --- |
| `start_demo.bat -NoBrowser -StopAfterCheck` | Đạt, exit 0; nhận diện PID 21004 ở 8765 và 23264 ở 8766; chọn 8767; đúng profile, code root và database |
| `start_demo.bat` không tham số, cùng entry point nhấp đúp | Khởi động đúng instance 8767 và gọi trình duyệt mặc định; không seed/reset/migration/đổi mật khẩu |
| Gọi launcher từ thư mục cha, cổng 8781, chế độ kiểm tra rồi dừng | Đạt, exit 0; đường dẫn không phụ thuộc working directory của người dùng |
| Chỉ định database khác | Đạt, báo lỗi rõ ràng và exit 1 trước khởi động; không dùng database khác |
| Parse PowerShell hai script đã chuyển | Không lỗi cú pháp; không thực thi launcher Recall |
| Backend pytest | **263 passed**, 2 cảnh báo deprecation của thư viện, không lỗi |
| Chrome và Edge thật, chạy headless | **36/36 kiểm tra đạt**, không lỗi JavaScript |
| 8 tài khoản demo | Đăng nhập thành công cả 8 trên mỗi trình duyệt; không ghi mật khẩu vào mã/UI/log |
| RBAC/cô lập tổ chức | Kiểm tra menu/thao tác theo vai trò và API truy cập trái tổ chức; HTTP 401/403 xử lý đúng |
| Sprint 1–3 | Vùng trồng tạo/sửa, thu hoạch/chống gửi trùng, tách/gộp, chấp nhận/từ chối bàn giao, BFS, timeline/hash-chain đều đạt |
| Giao diện | Chuyển màn hình, Back/Forward, laptop 1366×768 và desktop 1920×1080, không tràn ngang trang |

Browser và thao tác ghi nghiệp vụ chạy trên **bản sao database trong TEMP**, cùng code chính; không chạy trên database demo chính. Instance ở `C:\Users\Hoang\AppData\Local\Temp\agritrace_dashboard_fruloi1h\dashboard_test.db`; đã dừng riêng server thử nghiệm 8775 sau kiểm thử, giữ nguyên file database thử nghiệm. Lượt browser đầu tiên bắt đầu trước khi server tạm sẵn sàng nên bị connection refused; chạy lại sau kiểm tra `/demo-scope` đã đạt toàn bộ 36 kiểm tra. Đây không phải lỗi launcher chính.

## Đối chiếu dữ liệu

`organization_db_audit.py` chỉ mở SQLite read-only, không import ứng dụng. **Cả 13 database hiện hữu giữ nguyên SHA-256 toàn file, schema và nội dung tất cả bảng trước/sau.** `PRAGMA integrity_check` được ghi trong từng snapshot. Database gốc vẫn có 8 tài khoản, 39 lô, 110 sự kiện và 26 sự kiện mồ côi; byte và nội dung giữ nguyên, không chỉ so số lượng. Database demo chính và các backup/trial khác cũng không thay đổi.

Các file nghiệp vụ Recall (`recall.js`, router/service/models) giữ nguyên SHA-256. Không sửa code Backend/Frontend nghiệp vụ, không migration, seed, reset hay chỉnh mật khẩu trong nhiệm vụ này. `.git`, `.github`, Docker, pytest và Alembic giữ nguyên.

## Cách chạy bàn giao

1. Mở `D:\TTCS_K23C_N5\TTCS-K18C4-N5` và nhấp đúp **`start_demo.bat`**.
2. Chờ launcher in profile `Sprint 1-3 TEST ONLY`, code root và database `.sprint123-trial/demo_sprint123.db`.
3. Trình duyệt tự mở URL thực tế. Lượt kiểm thử này dùng **http://127.0.0.1:8767/**; lần sau cổng có thể khác nếu bận.
4. Chọn tài khoản demo trên màn hình đăng nhập và nhập mật khẩu local đã thiết lập. Các tài khoản: `s123_farm`, `s123_packing`, `s123_receiver`, `s123_transport`, `s123_distribution`, `s123_inspector`, `s123_admin`, `s123_org_admin`, cùng hậu tố `@demo.local`. Xem vai trò và hướng dẫn chi tiết trong [DEMO.md](DEMO.md).
5. Dùng menu Tổng quan, Vùng trồng, Lô nông sản, Tiếp nhận bàn giao, Truy xuất nguồn gốc và Nhật ký sự kiện theo quyền tài khoản.

Server demo của lượt kiểm thử không tham số được giữ chạy tại 8767 (wrapper PID 12204, listener PID 2660). Các server đã có ở 8765/8766/8769 không bị dừng hoặc dùng lại bởi launcher. Đó là các tiến trình chạy từ một bộ code, không phải các ứng dụng mới.

Không phát hiện lỗi chức năng mới sau thay đổi. Còn lưu ý: script seed cũ vẫn được giữ trong `scripts/` để bàn giao, có thể dùng database mặc định nếu chạy trực tiếp; đây là công cụ nội bộ, không thuộc quy trình demo. File/database local và backup vẫn nằm trên máy này, cần chuyển giao riêng nếu bàn giao sang máy mentor. Không tiếp tục Sprint 4–8 hoặc phát triển Recall.
