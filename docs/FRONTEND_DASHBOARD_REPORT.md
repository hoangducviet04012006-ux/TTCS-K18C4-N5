# Báo cáo Frontend Dashboard AgriTrace

Ngày 10/10/2026. Giữ một bộ code tại D:\TTCS_K23C_N5\TTCS-K18C4-N5. Không sửa API/router backend hoặc code Recall; không seed/reset/migration, không sửa database gốc hoặc demo chuẩn.

## Giao diện đã hoàn thành

Sidebar hiện có, logo AgriTrace và màu xanh lá được giữ. Sáu màn hình riêng: Tổng quan, Vùng trồng, Lô nông sản, Tiếp nhận bàn giao, Truy xuất nguồn gốc và Nhật ký sự kiện. Mỗi lần điều hướng chỉ có một màn hình chính hiện ra, có tiêu đề/mô tả, menu được đánh dấu aria-current và cuộn về đầu. Hỗ trợ URL hash, liên kết trực tiếp, tải lại trang, Back/Forward và vị trí quay lại sau đăng nhập. Các menu Tài khoản/Nhật ký quản trị vẫn hoạt động theo quyền; sản phẩm nằm trong màn hình Lô nông sản để giữ nguyên chức năng.

Các card/form/modal cũ được đưa vào màn hình tương ứng, không thay bằng ứng dụng mới. Modal chi tiết vẫn giữ ba tab, tách/gộp/bàn giao và lịch sử. BFS và timeline trên màn hình riêng dùng lại các hàm/renderers cũ, có vùng kết quả riêng, không ảnh hưởng modal. Modal chi tiết dài có phần nội dung cuộn và nút đóng luôn nằm trong khung nhìn. Badge tài khoản được sửa tương phản trên header trắng. Asset CSS/JS đổi version để tải bản mới.

Tổng quan có thống kê hiện có và 5 sự kiện gần nhất lấy từ tối đa 5 lô đang hiển thị. Số lượng/khối lượng lô vẫn là phạm vi trang dữ liệu hiện tại như nhãn trên giao diện, không tuyên bố tổng toàn hệ thống. Dropdown truy xuất/nhật ký dùng các lô đang tải theo phân trang/bộ lọc. Đây là giới hạn hiện có của dữ liệu frontend, không thêm API thống kê mới.

## RBAC và bảo vệ dữ liệu

Menu tiếp nhận chỉ hiện cho farmer, processor, transporter, distributor; nút thu hoạch chỉ farmer, gộp chỉ processor, vùng trồng chỉnh sửa chỉ farmer/org_admin. Quản trị tài khoản chỉ system_admin/org_admin; nhật ký quản trị theo quyền audit hiện có. Các vai trò vẫn có quyền đọc các màn hình nghiệp vụ theo backend. Hash quản trị trái quyền được chuyển về Tổng quan. API tiếp tục kiểm tra quyền và tổ chức, bao gồm quyền truy xuất tổ tiên/từng giữ lô hiện có.

Kết quả BFS/timeline/cảnh báo được xóa khi đăng xuất. Phản hồi cũ không được đưa vào màn hình sau đổi phiên hoặc chọn lô khác. Không đưa mật khẩu vào ảnh/log hay tự điền mật khẩu. Không thay mật khẩu, vai trò, tổ chức hoặc dữ liệu nghiệp vụ.

## File thay đổi

- frontend/index.html: hai màn hình truy xuất/nhật ký, hoạt động gần đây, heading và liên kết Sidebar; version asset.
- frontend/js/app.js: quản lý màn hình/hash/history/RBAC, tổng hợp hoạt động trong phạm vi, tái sử dụng renderers BFS/timeline/integrity cho hai nơi hiển thị; bảo vệ phản hồi sau đổi phiên/lô.
- frontend/css/style.css: bố cục từng màn hình, menu active, toolbar responsive, badge tương phản, cuộn trong modal chi tiết.
- docs/DEMO.md: hướng dẫn menu màn hình mới.
- Báo cáo này; docs/qa/dashboard_browser_check.cjs; kết quả dashboard_browser_results.json, dashboard_browser_tests.txt; dấu vân tay dashboard_before.json/dashboard_after.json; metadata dashboard_test_instance.json; ảnh kiểm thử bên dưới.

## Kiểm thử Chrome/Edge

**36 mục đạt trên Chrome và Edge thực tế, headless qua Playwright**. Đủ 8 tài khoản demo bao phủ 7 vai trò. Kiểm tra chỉ một màn hình hiển thị, menu active duy nhất, cuộn đầu, Back/Forward, hash trái quyền, form/nút theo RBAC; tạo/sửa vùng trồng, thu hoạch chống gửi trùng, tách, gộp một phần, gửi/nhận và từ chối bàn giao, truy ngược trong modal và màn hình riêng, timeline/hash-chain, 401 quay lại đăng nhập/vị trí cũ, 403 giữ phiên. Không có lỗi JavaScript trong các ca này.

Laptop 1366×768 và desktop 1920×1080: kiểm tra sáu màn hình trên cả hai trình duyệt, không tràn ngang toàn trang. Bảng dài vẫn cuộn trong vùng bảng. 24 ảnh bố cục, thêm 2 ảnh modal chi tiết và 2 ảnh danh sách đang chờ trước khi nhận.

Kiểm thử ghi chạy trên bản sao SQLite trong thư mục Windows TEMP agritrace_dashboard_* và server thử tạm port 8775, dùng chính backend/frontend từ repository này. Không có bản sao ứng dụng hoặc launcher mới, không seed/migration bản sao. Server thử đã dừng; database tạm và bằng chứng giữ lại. Các server có sẵn 8765/8766/8769 được giữ nguyên.

Bản demo chính tại http://127.0.0.1:8766/ sử dụng cùng frontend cập nhật. Chỉ cần tải lại trang (Ctrl+F5 nếu cần), không chạy lại server hoặc tạo dữ liệu để thấy giao diện mới. Ảnh kiểm thử hiển thị đường dẫn TEMP/cổng 8775 đúng môi trường kiểm thử, không phải thay database chính.

Không chạy lại toàn bộ backend tests trong thay đổi frontend này; không có mã backend/API nào được sửa. Kiểm tra cú pháp JavaScript và git diff --check đạt. Báo cáo backend từ nhiệm vụ trước không được tính là lần chạy mới.

## Đối chiếu database

Cả **13 database hiện có trong repository**, gồm backend/ttcs.db, demo_sprint123.db và trial/backup khác: dấu vân tay SHA-256 toàn file và nội dung từng dòng/tất cả cột của mọi bảng **khớp hoàn toàn trước/sau**. Không chỉ dựa vào đếm bản ghi. Database gốc vẫn giữ 8 tài khoản, 110 sự kiện và 26 sự kiện mồ côi; demo giữ nguyên mọi dữ liệu và hash-chain. Các dấu vân tay không chứa plaintext hoặc hash mật khẩu.

## Ảnh từng màn hình

| Màn hình | Chrome laptop | Chrome desktop | Edge laptop | Edge desktop |
|---|---|---|---|---|
| Tổng quan | [Ảnh](qa/dashboard-chrome-laptop-overview.png) | [Ảnh](qa/dashboard-chrome-desktop-overview.png) | [Ảnh](qa/dashboard-msedge-laptop-overview.png) | [Ảnh](qa/dashboard-msedge-desktop-overview.png) |
| Vùng trồng | [Ảnh](qa/dashboard-chrome-laptop-farm-card.png) | [Ảnh](qa/dashboard-chrome-desktop-farm-card.png) | [Ảnh](qa/dashboard-msedge-laptop-farm-card.png) | [Ảnh](qa/dashboard-msedge-desktop-farm-card.png) |
| Lô nông sản | [Ảnh](qa/dashboard-chrome-laptop-batch-card.png) | [Ảnh](qa/dashboard-chrome-desktop-batch-card.png) | [Ảnh](qa/dashboard-msedge-laptop-batch-card.png) | [Ảnh](qa/dashboard-msedge-desktop-batch-card.png) |
| Tiếp nhận bàn giao | [Ảnh](qa/dashboard-chrome-laptop-pending-handovers-card.png) | [Ảnh](qa/dashboard-chrome-desktop-pending-handovers-card.png) | [Ảnh](qa/dashboard-msedge-laptop-pending-handovers-card.png) | [Ảnh](qa/dashboard-msedge-desktop-pending-handovers-card.png) |
| Truy xuất nguồn gốc | [Ảnh](qa/dashboard-chrome-laptop-traceability.png) | [Ảnh](qa/dashboard-chrome-desktop-traceability.png) | [Ảnh](qa/dashboard-msedge-laptop-traceability.png) | [Ảnh](qa/dashboard-msedge-desktop-traceability.png) |
| Nhật ký sự kiện | [Ảnh](qa/dashboard-chrome-laptop-events.png) | [Ảnh](qa/dashboard-chrome-desktop-events.png) | [Ảnh](qa/dashboard-msedge-laptop-events.png) | [Ảnh](qa/dashboard-msedge-desktop-events.png) |

[Danh sách chờ có dữ liệu](qa/dashboard-chrome-pending-before-accept.png) · [Modal chi tiết](qa/dashboard-chrome-detail.png).

Không ghi nhận lỗi còn chặn demo trong các ca đã kiểm tra. Chưa kiểm thử tương tác thủ công hoặc mọi độ rộng thiết bị; phạm vi kiểm thử kích thước là laptop/desktop nói trên. Dừng sau cải tiến frontend này.
