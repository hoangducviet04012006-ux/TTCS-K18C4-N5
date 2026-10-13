# Báo cáo chuẩn hóa môi trường demo AgriTrace Sprint 1–3

Ngày 10/10/2026. Phạm vi đã phê duyệt: chuẩn hóa môi trường chạy thử, không phát triển Sprint 4–8 hoặc Recall 3B.2B. Một bộ code chính duy nhất tại `D:\TTCS_K23C_N5\TTCS-K18C4-N5`; không tạo ứng dụng, bản sao code hoặc launcher mới.

## Môi trường chính thức

- Launcher hiện có: `start_demo.bat` → `scripts/start_demo.ps1` → `backend/scripts/run_sprint123_demo.py`.
- Code API: `backend/app`; code UI: `frontend/index.html`, `frontend/js`, `frontend/css` của repository chính.
- Profile: **Sprint 1–3 DEMO**; API và frontend cùng origin.
- Database chính thức: `D:\TTCS_K23C_N5\TTCS-K18C4-N5\.sprint123-trial\demo_sprint123.db`.
- URL đang chạy: **http://127.0.0.1:8769/**, Swagger `/docs`. Cổng mặc định của launcher vẫn là 8765.
- Cổng 8765 đang có server cũ PID **21004**, sử dụng `qa_sprint123.db`; không dừng hoặc dùng lại server đó. Không dùng tab 8765 cho demo chuẩn mới.
- Phiên chính thức đã khởi chạy bằng `start_demo.bat -NoBrowser -Port 8769`: PID launcher Python **20732**, PID Python đang nghe HTTP **19732**. Đây là quan hệ cha/con của virtualenv Windows, không phải hai ứng dụng riêng.

## File thực tế đã sửa trong nhiệm vụ này

| File, tương đối với repository chính | Thay đổi |
|---|---|
| start_demo.bat | Tên cửa sổ Sprint 1–3; tiếp tục dùng PowerShell launcher hiện có và chuyển tham số |
| scripts/start_demo.ps1 | Kiểm tra cổng/PID, không dừng server khác; kiểm tra database hiện hữu; xác minh profile, đường dẫn database và code; in URL/database/PID, bỏ mật khẩu khỏi output |
| backend/scripts/run_sprint123_demo.py | Tách chuẩn bị một lần và khởi động chỉ đọc kiểm tra; 8 mật khẩu riêng; credential local có ACL; schema mới gồm session, marker và trigger; fixture actor bị vô hiệu hóa; cung cấp metadata profile |
| frontend/index.html | Bổ sung ô user-search mà mã JavaScript đã sử dụng |
| frontend/js/app.js | Hiển thị profile/database từ backend, dừng đăng nhập nếu không xác minh được profile; bỏ khoảng trắng dư |
| backend/tests/test_sprint123_demo_safety.py | Thêm kiểm tra không tự chuẩn bị khi khởi động, kiểm tra đọc không thay đổi file, 8 tài khoản với mật khẩu riêng và chỉ 8 tài khoản hoạt động |
| docs/qa/sprint123_browser_check.cjs | URL bắt buộc chỉ định, xác minh database chuẩn, đọc mật khẩu local, đủ 8 tài khoản, UI/API RBAC và truy cập tổ chức không liên quan |
| docs/DEMO.md | Thay hướng dẫn demo cũ bằng quy trình Sprint 1–3, tài khoản, mật khẩu local, cổng và các bước nghiệp vụ |
| README.md | Đưa quy trình demo chuẩn lên đầu, phân biệt với hướng dẫn triển khai cũ |

Các file untracked nói trên đã tồn tại trước nhiệm vụ này và được sửa tại chỗ. Không coi toàn bộ Git diff hiện tại là thay đổi của nhiệm vụ này, vì repository đã có nhiều thay đổi từ các giai đoạn trước.

File tạo mới: database demo, `.sprint123-trial/credentials.local`, báo cáo này và các bằng chứng QA có tiền tố `docs/qa/demo_standardization_` (before.json, after.json, backend_tests.txt, browser_tests.txt, final_browser_smoke.txt, chain.json, demo_state.json). Kết quả `docs/qa/sprint123_browser_results.json` và ảnh `sprint123-chrome-detail.png`, `sprint123-msedge-detail.png` được cập nhật bởi kiểm thử. Database và credential đều bị Git bỏ qua.

Không sửa file router/service/model/migration Recall. Không sửa code nghiệp vụ backend trong nhiệm vụ chuẩn hóa này. Không xóa trial, backup, dữ liệu hoặc tài khoản cũ.

## Database và mật khẩu

Database được tạo đúng một lần bằng fixture tổng hợp trong RAM rồi ghi vào file mới, không đọc/copy dữ liệu gốc. Ban đầu: 3 tổ chức, 14 lô, 28 sự kiện. Sau kiểm thử luồng nghiệp vụ: 30 lô, hash-chain hợp lệ toàn bộ; dữ liệu kiểm thử được giữ lại. Có 8 tài khoản đăng nhập hoạt động và 1 actor fixture đã vô hiệu hóa để bảo toàn tác giả sự kiện mẫu.

Khởi động thông thường chỉ xác minh marker/schema/tính toàn vẹn và mở ứng dụng với lifespan off, không gọi init_db/seed/migration. Thiếu database hoặc schema không tương thích thì dừng, không tự sửa. Gọi lại bước chuẩn bị trên database hiện hữu chỉ đọc kiểm tra, không ghi đè, đổi mật khẩu hoặc reset.

Một lần khởi động rồi dừng kiểm tra đã đối chiếu database demo byte-for-byte không thay đổi; kiểm tra chuẩn bị lại sau khi kết thúc browser cũng xác nhận không thay đổi byte. Kiểm tra file trong lúc SQLite đang mở có thể bị Windows từ chối chia sẻ file; không coi lần đọc thất bại là bằng chứng dữ liệu khớp.

Mỗi tài khoản có mật khẩu ngẫu nhiên riêng. File `.sprint123-trial/credentials.local` là nơi đọc mật khẩu cục bộ; ACL đã kiểm tra chỉ có `VIET\Hoang:(F)`, không kế thừa quyền. Đã kiểm tra Git ignore và quét mật khẩu phát sinh trong log/QA output: không có mật khẩu bị ghi ra. Không chỉnh sửa mật khẩu các tài khoản đã có. Sửa credential file không thay đổi mật khẩu trong database.

| Khóa local | Tài khoản email | Vai trò | Phạm vi tổ chức |
|---|---|---|---|
| farm | s123_farm@demo.local | farmer | HTX-DT |
| packing | s123_packing@demo.local | processor | HTX-DT |
| receiver | s123_receiver@demo.local | processor | HTX-TG |
| transport | s123_transport@demo.local | transporter | HTX-TG |
| distribution | s123_distribution@demo.local | distributor | DN-XNK |
| inspector | s123_inspector@demo.local | inspector | Đọc toàn cảnh nghiệp vụ |
| admin | s123_admin@demo.local | system_admin | Quản trị tài khoản hệ thống; nghiệp vụ không tự vượt tổ chức |
| org_admin | s123_org_admin@demo.local | org_admin | HTX-DT |

8 tài khoản bao phủ **7 vai trò khác nhau**, với processor ở hai tổ chức để kiểm thử bàn giao. `demo_admin@demo.local` không nằm trong database demo chuẩn.

## Kiểm thử

| Kiểm tra | Kết quả |
|---|---|
| Toàn bộ backend hiện có, gồm hồi quy Recall và kiểm tra demo | **263 passed, 2 deprecation warnings**, 98.16 giây; dùng cấu hình memory/test và fixture database riêng |
| Nhóm kiểm tra bảo vệ demo sau cập nhật cuối validation | **9 passed**, 1 deprecation warning |
| Chrome và Edge thực tế qua Playwright, headless | **28 mục đạt**, bao gồm đăng nhập 8 tài khoản trên mỗi trình duyệt |
| Hiển thị RBAC | Farmer có thu hoạch; farmer/org_admin có vùng trồng; processor có gộp; admin/org_admin có quản trị tài khoản; quyền lấy từ phiên backend |
| API RBAC | Quyền /users đúng; org_admin chỉ thấy tài khoản tổ chức mình; inspector được đọc toàn cảnh nhưng không tạo vùng trồng |
| Cách ly tổ chức | Tổ chức không có quyền lịch sử/phả hệ bị 403 khi đọc hoặc tách lô mới; 403 giữ phiên |
| Nghiệp vụ UI | Tạo vùng trồng, thu hoạch chống gửi trùng, tìm kiếm, tách, gộp một phần, bàn giao/nhận, truy ngược và xác minh hash-chain đều đạt |
| Session | 401 đóng chi tiết và về đăng nhập; đăng nhập lại trở về vị trí trước đó; tải lại trang khôi phục phiên trên Chrome/Edge |
| Kiểm tra cuối sau khởi động phiên code cuối | Profile/database đúng, Recall và tiêu thụ ẩn, khôi phục phiên, không lỗi JavaScript trên cả hai trình duyệt |
| Hash-chain database demo | **30/30 lô hợp lệ**, không chỉnh sửa sự kiện cũ |
| Launcher | Chạy được .bat; profile/path đúng; cổng 8765 bị từ chối kèm PID; cổng 8769 chạy thành công; StopAfterCheck chỉ dừng tiến trình do launcher vừa tạo |
| Mật khẩu | Riêng từng tài khoản, lưu local có ACL, không có trong Git hoặc log sinh ra |

Quyền truy xuất cho phép xem lô từng giữ hoặc tổ tiên của lô đã giữ, theo code hiện có. Vì vậy không coi mọi lần đọc lô hiện đang ở tổ chức khác là vi phạm RBAC. Đã dùng lô mới không liên quan để kiểm tra từ chối truy cập.

## Đối chiếu database gốc

Đọc bằng SQLite URI `mode=ro`, `PRAGMA query_only=ON`. Bằng chứng: `demo_standardization_before.json` và `demo_standardization_after.json` giống nhau hoàn toàn khi nạp JSON.

- SHA-256 toàn file bằng nhau: bảo toàn từng byte của `backend/ttcs.db`.
- SHA-256 schema (bảng, index, trigger và SQL định nghĩa) bằng nhau.
- SHA-256 nội dung tất cả các dòng, bao gồm toàn bộ cột của **11 bảng**, bằng nhau: bao phủ mật khẩu/account/session/audit, lô, quan hệ và sự kiện mà không tiết lộ nội dung nhạy cảm.
- SQLite integrity_check: `ok` trước và sau.
- Giữ nguyên **8 tài khoản, 39 lô, 110 sự kiện, 26 sự kiện mồ côi**.
- Không migration, seed, reset hoặc đăng nhập trên database gốc trong nhiệm vụ này.

## Hướng dẫn sử dụng và giới hạn còn lại

1. Mở http://127.0.0.1:8769/ của phiên đang chạy; kiểm tra banner có `demo_sprint123.db`. Không dùng tab 8765 của server cũ.
2. Mở `notepad .\.sprint123-trial\credentials.local` tại repository; đọc mật khẩu khóa tương ứng, không chụp/chia sẻ hoặc đưa vào Git/log.
3. Đăng nhập `s123_farm@demo.local`; làm vùng trồng và thu hoạch/tách. Đăng xuất, dùng packing để gộp/bàn giao sang HTX-TG; dùng receiver để nhận, truy ngược và xác minh hash-chain. Chi tiết form và các vai trò khác xem `docs/DEMO.md`.
4. Khi cần chạy lại: dừng đúng tiến trình demo của mình rồi dùng `start_demo.bat -Port 8769`, hoặc chọn cổng trống khác. Không dừng tiến trình chiếm 8765 nếu chưa tự quyết định xử lý nó.

Không còn lỗi user-search/khởi tạo JavaScript trong các ca đã kiểm tra. Hai cảnh báo deprecation của dependency backend còn tồn tại. Dữ liệu demo tích lũy qua mỗi lần thử, không reset; file mật khẩu phải được tự bảo quản. Browser kiểm thử bằng Chrome/Edge headless thực tế, chưa kiểm tra tương tác thủ công mọi kích thước màn hình. Đây là báo cáo chuẩn hóa môi trường, không thay thế nghiệm thu toàn bộ Acceptance Criteria Excel; các vấn đề CI/lint/Docker/staging đã ghi nhận ở đánh giá trước không nằm trong thay đổi này.

Recall giữ nguyên trong code và bộ hồi quy. Profile Sprint 1–3 chỉ ẩn điều khiển sau Sprint 3, không xóa router/API. Dừng công việc sau báo cáo này, không triển khai Sprint 4–8 hoặc Recall tiếp theo.


Ghi chú tổ chức thư mục (10/10/2026): đường dẫn script trong báo cáo đã được cập nhật sang `scripts/`; tại thời điểm lập báo cáo ban đầu chúng nằm ở thư mục gốc. Chỉ dùng `start_demo.bat` cho demo Sprint 1–3 hiện tại.
