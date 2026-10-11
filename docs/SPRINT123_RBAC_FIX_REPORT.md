# Kết quả sửa RBAC và Dashboard Sprint 1–3 — 10/10/2026

Đã sửa trực tiếp trên bộ code chính `D:\TTCS_K23C_N5\TTCS-K18C4-N5`, theo báo cáo `SPRINT123_RBAC_UI_REVIEW.md` và phê duyệt của người dùng. Không tạo ứng dụng mới, không sửa nghiệp vụ Recall hoặc triển khai Sprint 4–8. Launcher dành cho người dùng ở gốc vẫn chỉ có `start_demo.bat`.

## Lỗi trước/sau

| Lỗi | Trước | Sau đã kiểm thử |
| --- | --- | --- |
| FARM_MANAGE không được enforce | Processor/transporter/distributor/system_admin POST vùng 201, PUT vùng 200 | Cả hai API kiểm tra FARM_MANAGE trước thao tác; các vai trò trên nhận **403**; farmer/org_admin tiếp tục tạo/sửa vùng trong tổ chức |
| System_admin ghi nghiệp vụ | PUT lô 200, POST sự kiện 201 | Thêm quyền BATCH_UPDATE/EVENT_CREATE; system_admin và inspector bị **403**, kể cả ID không tồn tại. Giữ quyền đã có của các vai trò nghiệp vụ còn lại |
| Audit org_admin rò liên tổ chức | Nhận log tổ chức khác, bộ lọc user_id cũng vượt phạm vi | Chỉ trả log có người thực hiện và đối tượng hiện thuộc tổ chức của org_admin; lọc actor ngoài tổ chức/không xác định trả **403**. Lọc phạm vi trước LIMIT. System_admin/inspector vẫn đọc toàn cảnh |
| Org_admin tạo danh mục dùng chung | POST products 201 tác động toàn hệ thống | PRODUCT_CREATE dành cho system_admin (và alias admin cũ); org_admin **403**, nút Thêm sản phẩm bị ẩn. Quyền xem danh mục chung giữ nguyên |
| Cờ summary không xét vai trò | can_split/can_merge/can_handover có thể true trái quyền | Tính kết hợp quyền hành động với giữ lô/trạng thái/khối lượng/bàn giao chờ; transporter không can_split, farmer không can_merge, quản trị/inspector không được thao tác sản xuất |
| Modal Tách/Bàn giao trái quyền | Nút bật dù API trả 403 | Kết hợp quyền Frontend với cờ Backend. Không có quyền: ẩn nút; có quyền nhưng trạng thái lô chưa hợp lệ: disable. Hàm mở modal cũng kiểm tra vai trò và thông báo rõ khi bị từ chối |
| KPI dùng 0 cho lỗi/thiếu quyền | Không tải được hoặc 403 cũng có thể hiển thị 0 | Phân biệt Đang tải, Không có quyền xem, Không tải được dữ liệu, và số liệu tải thành công. Chỉ dùng **0** khi API thành công và thực sự trả dữ liệu rỗng |
| Inspector audit không tự tải | Đăng nhập thấy 0 dù được đọc audit | Tự tải theo canViewAuditLogs thay vì isAdmin; số audit khớp số dòng được tải |
| KPI bàn giao có link không dùng được | Quản trị nhìn thấy link tới trang không được mở | Giữ số liệu đọc được theo tổ chức, ẩn link thao tác khi không có quyền bàn giao. Inspector nhận trạng thái Không có quyền xem, không phải 0 |
| KPI/hoạt động gần đây diễn giải quá rộng | Nhãn hoạt động/tổng có thể bị hiểu là toàn hệ thống | Nêu phạm vi tổ chức/toàn hệ thống, trang và bộ lọc; khối lượng là **còn lại trên trang**, nhóm theo đơn vị; audit tối đa 100 dòng đã tải; hoạt động là mẫu tối đa 5 sự kiện từ 5 lô đầu trên trang |
| Nội dung phiên trước khi đổi tài khoản | Kết quả đang tải/hiển thị có thể thuộc phiên trước | Dọn dữ liệu hiển thị khi xóa phiên; tăng phiên bản request và bỏ phản hồi farms/audit/pending/batches nếu tài khoản đã đổi |

Sidebar đọc chung được giữ. Trang Vùng trồng/Lô dùng mô tả chỉ xem khi tài khoản không có thao tác sản xuất tương ứng; các form/nút vẫn phân quyền riêng. HTTP 403 không xóa phiên; HTTP 401 đưa về đăng nhập và đóng modal. Không đổi URL/prefix API.

## Ma trận Backend cuối cùng của 7 vai trò

✓ là được phép theo vai trò, còn phải thỏa điều kiện tổ chức/giữ lô/trạng thái. Các cột ghi dưới đây chỉ mô tả Sprint 1–3 và phần quản trị đang dùng.

| Vai trò | Tạo/sửa vùng | Thu hoạch | Tách | Gộp | Gửi/nhận bàn giao | Sửa lô API | Ghi chú sự kiện API | Tạo sản phẩm chung | Quản lý tài khoản | Audit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| farmer | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ | — | — | — |
| processor | — | — | ✓ | ✓ | ✓ | ✓ | ✓ | — | — | — |
| transporter | — | — | — | — | ✓ | ✓ | ✓ | — | — | — |
| distributor | — | — | ✓ | — | ✓ | ✓ | ✓ | — | — | — |
| inspector | — | — | — | — | — | — | — | — | — | Toàn hệ thống |
| system_admin | — | — | — | — | — | — | — | ✓ | Toàn hệ thống | Toàn hệ thống |
| org_admin | ✓ | — | — | — | — | ✓ | ✓ | — | Tổ chức mình | Phạm vi tổ chức |

Quyền BATCH_UPDATE/EVENT_CREATE của farmer/processor/transporter/distributor/org_admin giữ nguyên hành vi API đã có; chỉ loại system_admin khỏi ghi nghiệp vụ. Không tự suy diễn vai trò từ tên chuỗi event_type, không mở API mới; các loại sự kiện vòng đời dành riêng cho thao tác nghiệp vụ vẫn bị chặn giả mạo bằng API ghi chú. Form Sửa lô trên giao diện vẫn dành cho farmer như trước; quyền API và tập thao tác được cung cấp trong UI được phân biệt rõ.

Mọi vai trò được đọc vùng/lô theo phạm vi router hiện có. Inspector đọc liên tổ chức; các tổ chức khác đọc lô đang giữ, lô từng giữ và tổ tiên hợp lệ theo phả hệ. System_admin không được tự mở rộng danh sách vùng/lô thành toàn cảnh; ngoại lệ đọc lịch sử/integrity đã có giữ nguyên. Quyền xóa quản trị hiện hữu không được mở rộng hay viết lại; lô có lịch sử vẫn bị chặn xóa.

Tám tài khoản kiểm thử thực tế: `s123_farm`, `s123_packing`, `s123_receiver`, `s123_transport`, `s123_distribution`, `s123_inspector`, `s123_admin`, `s123_org_admin`, hậu tố `@demo.local`. Hai tài khoản packing/receiver đều là processor, thuộc tổ chức 1 và 2. Không đổi tài khoản, mật khẩu hoặc tổ chức trong database hiện hữu.

## File sửa/tạo

| File | Nội dung |
| --- | --- |
| `backend/app/services/rbac.py` | BATCH_UPDATE, EVENT_CREATE và PRODUCT_CREATE tập trung |
| `backend/app/routers/farms.py` | FARM_MANAGE cho POST/PUT; sửa mô tả quyền API |
| `backend/app/routers/batches.py` | Chặn sửa lô trái quyền; can_* trong summary xét vai trò |
| `backend/app/routers/events.py` | Kiểm tra EVENT_CREATE trước ghi |
| `backend/app/audit.py` | Truy vấn audit có phạm vi actor và đối tượng, trước giới hạn kết quả |
| `backend/app/routers/audit.py` | Org_admin bắt buộc có tổ chức, chặn bộ lọc actor vượt phạm vi; mô tả quyền |
| `backend/app/routers/products.py` | Chỉ quản trị hệ thống tạo danh mục toàn hệ thống |
| `frontend/js/app.js` | Nút/modal theo vai trò, trạng thái KPI, xử lý phiên và phạm vi dữ liệu |
| `frontend/index.html` | Nhãn KPI/hoạt động rõ phạm vi; cache version app.js tăng lên 14 |
| `backend/tests/test_audit_logs.py` | Test tạo/sửa nghiệp vụ dùng farmer, giữ admin cho đọc/xóa quản trị |
| `backend/tests/test_completion.py` | Regression cập nhật đúng actor nghiệp vụ sau sửa quyền |
| `backend/tests/test_sprint123_rbac_fixes.py` **mới** | 10 test, gồm tham số 8 tài khoản/vai trò, summary, audit, tổ chức và 401 |
| `docs/qa/rbac_fix_browser_check.cjs` **mới** | Guard database TEMP, kiểm tra 8 tài khoản trên Chrome/Edge, API và KPI/phiên |
| Báo cáo này và `docs/qa/rbac_fix_*` | Bằng chứng trước/sau, kết quả test, launcher, instance tạm |

Ảnh và `dashboard_browser_results.json` trong `docs/qa/` được cập nhật bởi bộ regression giao diện hiện hữu. Không sửa `frontend/css/style.css`, code Recall, models/schema, Alembic, Docker/CI hoặc launcher. Git có các thay đổi từ trước nhiệm vụ; danh sách trên được đối chiếu với backup của riêng lượt sửa này, không coi toàn bộ Git diff là thay đổi lần này.

Trước sửa, sao lưu các file cũ trong `tools/backups/rbac-fix-20261010-180944/`: **11 file**, manifest SHA-256 đã xác minh. Backup được Git ignore; không đưa database hoặc credentials.local vào backup/commit. Không chạy Git add/commit.

## Kiểm thử cuối cùng

| Bộ kiểm tra | Kết quả |
| --- | --- |
| Toàn bộ Backend, bao gồm regression Sprint 1–3 và test cũ | **273 passed**, 2 DeprecationWarning của thư viện; 263 test cũ + 10 test mới |
| Luồng giao diện Chrome/Edge hiện hữu | **36/36 đạt**: tạo/sửa vùng, thu hoạch, tách/gộp, gửi/nhận/từ chối bàn giao, BFS, timeline/hash-chain, điều hướng, Back/Forward, laptop/desktop, 401/403 |
| Ma trận RBAC Chrome/Edge mới | **16/16 phiên đạt**, đủ 8 tài khoản ở mỗi trình duyệt; **244 kiểm tra API trực tiếp** với kỳ vọng trạng thái chính xác |
| Tải KPI lỗi và không có quyền | Giả lập HTTP 500/403 trong trình duyệt cho farms/batches/pending/audit; hiện đúng thông báo, không có số 0 giả, 403 giữ phiên |
| Hết phiên | Cookie hết hạn, gọi API nhận 401; về đăng nhập, modal đóng, không lỗi JavaScript |
| Trái tổ chức | Đọc lô không liên quan, sửa vùng, PATCH user và lọc audit actor khác tổ chức bị 403 |
| Inspector | Đọc liên tổ chức được, mọi thao tác ghi đã kiểm tra bị 403; audit tự tải và pending hiển thị Không có quyền xem |
| Hash-chain | Kiểm tra hợp lệ sau chuỗi thao tác trong database tạm; regression bất biến/hash/concurrency của Backend đạt |
| Launcher | `start_demo.bat` gọi đúng code chính, chọn cổng trống, mở trình duyệt, xác minh profile/database. Không seed/reset/migration/đổi mật khẩu hoặc dừng server khác |

Không chỉ kiểm tra nút ẩn: browser test gọi thẳng API có CSRF của từng phiên. Các API bị từ chối được gọi bằng payload hợp lệ. Quyền đọc và quyền ghi được assert riêng. Các lần chạy ban đầu phát hiện test cũ dùng admin thực hiện sản xuất và lỗi dọn cây DOM khi xóa phiên; đã sửa đúng actor test và giữ các container phả hệ, rồi chạy lại các bộ kiểm tra trên bản cuối. Log lỗi thử nghiệm đã được che giá trị mật khẩu nếu traceback chứa literal từ test cũ.

Mọi request đăng nhập/ghi/đánh dấu quá hạn chạy trên database TEMP sao từ demo bằng SQLite backup read-only, cùng code chính. Các fixture thêm chỉ nằm trong DB tạm, không sửa vai trò/mật khẩu của 8 tài khoản. Hai instance cuối được ghi trong `qa/rbac_fix_test_instance.json` và `qa/rbac_fix_matrix_instance.json`; đã dừng riêng server tạm sau kiểm thử, giữ file database. Không tạo bản sao ứng dụng.

Bằng chứng: [Backend](qa/rbac_fix_backend_tests.txt), [RBAC browser](qa/rbac_fix_browser_results.json), [luồng UI](qa/rbac_fix_flow_results.json), [launcher cuối](qa/rbac_fix_launcher_final.txt), [database trước](qa/rbac_fix_before.json), [database sau](qa/rbac_fix_after.json).

## Demo và bảo toàn dữ liệu

Nhấp đúp `start_demo.bat` ở gốc. Launcher tự mở URL thực tế và chỉ dùng `.sprint123-trial/demo_sprint123.db` hiện hữu. **Phiên Backend mới của lượt này: http://127.0.0.1:8770/**. Các tab/server cũ ở cổng khác có thể vẫn chạy Backend cũ; dùng URL của launcher mới để kiểm tra bản sửa. Không dừng các server có trước. Chỉ phiên demo do lượt sửa này vừa tạo được thay thế khi nạp quyền danh mục mới; phiên cuối được giữ chạy cho người dùng.

So trước/sau của **13 database hiện hữu**: SHA-256 toàn file, schema, digest nội dung từng bảng và PRAGMA integrity_check khớp hoàn toàn. Database gốc `backend/ttcs.db` vẫn nguyên 8 tài khoản, 39 lô, 110 sự kiện và 26 sự kiện mồ côi. Database demo chính cũng giữ nguyên toàn bộ dữ liệu, kể cả users/user_sessions; các request kiểm thử không đăng nhập vào nó. Các database trial/backup khác giữ nguyên. Bốn file nghiệp vụ Recall được đối chiếu SHA-256 không đổi.

Không có lỗi chức năng còn thất bại trong các bộ kiểm tra trên. Giới hạn cần biết: schema audit không lưu snapshot tổ chức lúc ghi, nên org_admin chỉ được đọc log chứng minh được phạm vi bằng actor và đối tượng hiện tại; đối tượng đã xóa/chuyển tổ chức hoặc loại đối tượng không xác định có thể bị ẩn để tránh lộ dữ liệu. System_admin/inspector vẫn đọc đầy đủ. Không thêm cột/migration để xử lý lịch sử trong nhiệm vụ này. Số KPI audit là số dòng đã tải, không phải tổng lịch sử. Kết thúc ở Sprint 1–3; không tiếp tục Recall hoặc Sprint 4–8.
