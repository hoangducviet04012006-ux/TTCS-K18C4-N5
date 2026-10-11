# Cập nhật đăng nhập demo Sprint 1–3

Ngày 10/10/2026. Thực hiện theo yêu cầu đổi mật khẩu chung cho đúng 8 tài khoản s123_* hiện có. Không ghi giá trị mật khẩu trong báo cáo, giao diện hoặc mã ứng dụng.

## Kết quả

- Chỉ cập nhật cột password của 8 tài khoản trong `D:\TTCS_K23C_N5\TTCS-K18C4-N5\.sprint123-trial\demo_sprint123.db`, một transaction BEGIN IMMEDIATE với danh sách tài khoản kiểm tra khớp chính xác trước khi ghi.
- Dùng `app.security.hash_password` (Argon2id); 8 hash có salt riêng, đã xác minh cả 8 với cấu hình local đồng bộ. Database không lưu plaintext.
- Không seed, reset, migration hoặc tạo lại database. Actor fixture bị vô hiệu hóa giữ nguyên. Tất cả cột user ngoài password được đối chiếu và giữ nguyên.
- Tất cả bảng dữ liệu nghiệp vụ, batch_relations, batch_events, audit và schema demo giữ nguyên; 30 lô và 64 sự kiện hiện có không thay đổi. Các phiên mới trong user_sessions là kết quả đăng nhập kiểm thử, không phải dữ liệu seed.
- Database gốc và 11 database trial/backup khác giữ nguyên byte-for-byte, schema và nội dung tất cả bảng. Database gốc vẫn có 8 tài khoản, 110 sự kiện lịch sử và 26 sự kiện mồ côi. Bằng chứng before/after và kết luận trong `docs/qa/demo_password_*.json`.

## Launcher và giao diện

Nhấp đúp `start_demo.bat` chạy profile Sprint 1–3 và mở trình duyệt. Launcher bắt đầu ở cổng 8765; cổng bận thì báo PID và tự tìm cổng tiếp theo (tối đa 100 cổng), không tắt hoặc dùng lại server cũ. URL thực tế, code root và database được in ra. Kiểm tra PID listener thuộc tiến trình vừa tạo trước khi mở trình duyệt để tránh dùng nhầm server nếu cổng đổi chủ khi khởi động. Nếu hết dải cổng hoặc khởi động lỗi thì dừng có thông báo, không chuyển database.

Phiên đang chạy: **http://127.0.0.1:8766/**; PID launcher Python 21092, PID listener 23264. Cổng 8765 (PID 21004) và phiên cũ 8769 được giữ nguyên. Cùng một code chính, không có launcher hoặc ứng dụng mới.

Màn hình đăng nhập có selector đủ 8 tài khoản theo vai trò và tổ chức. Chọn tài khoản chỉ điền email, xóa ô mật khẩu và đưa con trỏ vào ô mật khẩu. Người dùng nhập mật khẩu chung đã yêu cầu; không tự điền hoặc hiển thị mật khẩu. Profile ngoài Sprint 1–3 giữ các nút chọn nhanh cũ.

Tài khoản: s123_farm (farmer/HTX-DT), s123_packing (processor/HTX-DT), s123_receiver (processor/HTX-TG), s123_transport (transporter/HTX-TG), s123_distribution (distributor/DN-XNK), s123_inspector (inspector/toàn cảnh), s123_admin (system_admin/HTX-DT), s123_org_admin (org_admin/HTX-DT). Email tương ứng có hậu tố @demo.local. Vai trò và tổ chức không thay đổi.

## Kiểm thử

- **24 test backend đạt**, 1 cảnh báo deprecation: demo safety, RBAC/session và đăng nhập email. Fixtures dùng database tạm/memory; không kiểm thử ghi trên database gốc.
- **16 phiên đăng nhập đạt**: cả 8 tài khoản trên Chrome và Edge thực tế qua Playwright headless. POST login và GET auth/me thành công; username, role và organization_id đúng; selector có 8 lựa chọn, không tự điền mật khẩu; quyền hiển thị thu hoạch, gộp và quản trị tài khoản đúng; không có lỗi JavaScript.
- Chạy `start_demo.bat` không tham số thành công, tự chọn 8766 và gọi mở trình duyệt.
- Khi 8765 và 8766 cùng bận, `start_demo.bat -NoBrowser -StopAfterCheck` tự chọn 8767, chạy thành công rồi dừng tiến trình vừa tạo; không tác động các server khác.
- Đối chiếu nội dung/schema và SHA-256 toàn file trên 13 database: chỉ database demo được thay đổi có chủ đích. Mọi bảng demo ngoài users/user_sessions giữ nguyên; mọi trường user ngoài password và actor fixture giữ nguyên.
- Kiểm tra Git ignore/ACL credential local được giữ; không có mật khẩu trong log mới của launcher hoặc kiểm thử nhiệm vụ này. Cấu hình `.sprint123-trial/credentials.local` được đồng bộ, không đưa vào Git.

## File thay đổi

- `scripts/start_demo.ps1`: tìm cổng trống tự động, hiển thị PID cổng bận, xác minh sở hữu listener.
- `frontend/index.html`: selector 8 tài khoản theo vai trò.
- `frontend/js/app.js`: chọn nhanh chỉ email trong profile Sprint 1–3.
- `docs/DEMO.md`: hướng dẫn cổng tự động và đăng nhập hiện tại.
- `.sprint123-trial/demo_sprint123.db`: đúng 8 password hash; session phát sinh do kiểm thử đăng nhập.
- `.sprint123-trial/credentials.local`: đồng bộ cấu hình mật khẩu local, giữ ACL/Git ignore.
- Báo cáo này và bằng chứng QA: `demo_password_before.json`, `demo_password_after.json`, `demo_password_verification.json`, `demo_password_browser_results.json`, `demo_password_browser_tests.txt`, `demo_password_backend_tests.txt`.

`start_demo.bat` không cần sửa thêm: đã chuyển tham số, xử lý lỗi và gọi PowerShell launcher đúng. Không sửa code Recall, hash-chain hoặc nghiệp vụ backend; không phát triển Sprint 4–8.

## Cách dùng

Nhấp đúp start_demo.bat, hoặc mở URL 8766 của phiên đang chạy. Kiểm tra banner có demo_sprint123.db, chọn tài khoản theo vai trò, nhập mật khẩu chung đã thống nhất và đăng nhập. Khi nhiều cổng đang dùng, xem URL thực tế launcher vừa mở. Không dùng database hoặc tài khoản gốc để thử demo.

Còn một cảnh báo deprecation từ dependency backend trong nhóm test. Các phiên đăng nhập có sẵn không bị cưỡng bức thu hồi trong thao tác cập nhật chỉ cột password này. Trình duyệt đã kiểm thử ở chế độ headless; lệnh launcher mở trình duyệt mặc định đã chạy thành công.


Ghi chú tổ chức thư mục (10/10/2026): đường dẫn script trong báo cáo đã được cập nhật sang `scripts/`; tại thời điểm lập báo cáo ban đầu chúng nằm ở thư mục gốc. Chỉ dùng `start_demo.bat` cho demo Sprint 1–3 hiện tại.
