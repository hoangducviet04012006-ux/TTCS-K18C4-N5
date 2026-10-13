> Báo cáo lịch sử. Khi bàn giao hiện tại, chỉ nhấp đúp `start_demo.bat`; không chạy hướng dẫn seed cũ bên dưới trên database gốc hoặc demo hiện hữu. Xem [DEMO.md](DEMO.md).

# Báo cáo kiểm tra và hoàn thiện Sprint 1–2

Ngày kiểm tra: 10/10/2026. Repository thực tế: `D:\TTCS_K23C_N5\TTCS-K18C4-N5`.

## Phân tích ban đầu và phạm vi

Backend FastAPI dùng SQLAlchemy/SQLite, Pydantic, Argon2 và HTTP Basic; frontend HTML/CSS/JavaScript thuần. Database khởi tạo và migration nằm trong `app/database.py`, model trong `app/models.py`; đã có router farms, batches, products, handovers, events, audit và thuật toán BFS truy xuất. Test có sẵn bao phủ đăng nhập, lockout, cách ly tổ chức, hash, tách/gộp và bàn giao. Tên các file `test_sprint3_full.py` là tên lịch sử, không quyết định phạm vi Sprint của lần kiểm tra này.

Trước sửa, 83 test đạt nhưng chưa chứng minh an toàn cho mọi đường API. Quản trị tài khoản chủ yếu có danh sách; các đường đọc chi tiết lô/sự kiện còn có chỗ thiếu xác thực; cập nhật lô có thể phục hồi lượng đã tách; xóa vùng trồng/lô có thể làm mất nguồn gốc. Seed cũ và đăng nhập nhanh còn gắn với mật khẩu mặc định. SQLite không thực thi `FOR UPDATE` như database server nên các thao tác đồng thời cần kiểm chứng riêng.

Đã thực hiện theo nhóm: tài khoản và quyền → nghiệp vụ/hash và regression → seed → frontend → kiểm tra tích hợp. Người dùng đã xác nhận giữ `admin` quản trị hệ thống, `farmer` thao tác theo tổ chức, thêm trạng thái tài khoản. Migration chỉ bổ sung `is_active`, `is_locked`; không tạo Super Admin, không đổi cơ chế đăng nhập hoặc tên endpoint. Không triển khai tính năng ngoài yêu cầu Sprint 1–2.

Workspace đã có nhiều thay đổi chưa commit trước khi thực hiện. Các thay đổi đó được giữ lại; không coi toàn bộ `git diff` là sản phẩm của lần sửa này. Database thật `backend/ttcs.db` không được dùng để chạy seed hoặc QA trong phiên này; test và trình duyệt dùng các SQLite tạm riêng. Migration sẽ áp dụng khi backend thực tế khởi động.

## Lỗi được xác nhận và cách sửa

| Vấn đề | Thay đổi và bằng chứng |
| --- | --- |
| Đọc chi tiết lô/sự kiện qua đường thiếu xác thực hoặc alias | Áp dụng chung `get_current_user` và `can_view_batch`; kiểm thử 401/403 và các alias, danh sách global chỉ chứa dữ liệu được phép |
| Lịch sử tổ chức khác lộ ghi chú và danh tính nội bộ | Lọc payload theo các trường phục vụ truy xuất, ẩn actor/note riêng; giữ nguồn tách/gộp, khối lượng, đơn vị, tổ chức và hash; test và trình duyệt đã xác minh |
| HTTP Basic không cùng cơ chế đếm lần sai với login | Dùng cùng lockout; cập nhật bộ đếm nguyên tử; lần sai thứ 5 khóa tạm, cả credential đúng cũng bị từ chối trong thời gian khóa |
| Cập nhật lô không đủ validation và có thể phục hồi lượng đã tách | Chặn ngày tương lai, lượng không hợp lệ, lô đang chờ bàn giao; sau tách/gộp/bàn giao không sửa nguồn gốc hoặc lượng; ghi `BATCH_UPDATED` trong cùng transaction |
| Xóa lô/vùng trồng có thể phá lịch sử | Trả 409 với lô có lịch sử/quan hệ và vùng trồng chứa lô; vẫn cho xóa vùng trồng rỗng. Test cũ được sửa theo chính sách bảo toàn lịch sử, không bỏ qua test |
| Hash chỉ bảo vệ payload, có thể không bắt metadata | Sự kiện mới băm kèm loại sự kiện, actor, tổ chức, timestamp và metadata; kiểm tra cả alias dữ liệu. Chuỗi cũ vẫn đọc được, không viết lại hash lịch sử |
| Ghi sự kiện đồng thời có nguy cơ phân nhánh | Lấy khóa ghi SQLite trước khi đọc tail; test ghi đồng thời vẫn tạo một chuỗi hợp lệ |
| API ghi chú cho phép giả mạo sự kiện nghiệp vụ | Chặn các loại HARVEST/HANDOVER/SPLIT/MERGE/BATCH_UPDATED qua API annotation; lifecycle chỉ được tạo từ thao tác nghiệp vụ |
| Bàn giao/tách/gộp đồng thời dùng trạng thái cũ | Tuần tự hóa ghi trước kiểm tra trạng thái và lượng, đọc lại dữ liệu; test accept/reject đồng thời chỉ một thao tác thành công |
| Bàn giao lô đã tách hiển thị lượng ban đầu, đơn vị luôn kg | Dùng lượng còn lại và đơn vị sản phẩm; chặn bàn giao lô hết lượng; test tấn sau tách đã đạt |
| Bàn giao đã giải quyết vẫn có cờ quá hạn | Xóa cờ hiện tại khi accept/reject; nhận muộn vẫn ghi thông tin quá hạn trong sự kiện |
| Seed tự động/mật khẩu mặc định và fallback migration đoán tổ chức | Seed mặc định đổi thành opt-in local; không đoán `organization_id=1`/`product_id=1`; seed mới có marker, không reset dữ liệu hoặc đổi credential cũ |
| Thống kê cộng các đơn vị khác nhau và label gây hiểu sai tổng | Nhóm lượng còn lại theo đơn vị; ghi rõ số liệu lô/khối lượng thuộc trang hiện tại |
| Dashboard tràn ngang cả trang | Bố cục grid cho phép co lại, bảng tự cuộn bên trong; đo ở desktop và 390 px không tràn ngang document |

## Quản trị tài khoản và giao diện

Giữ GET `/users` trả danh sách để tương thích; thêm tìm kiếm, role, organization, trạng thái, page/limit. POST `/users` tạo tài khoản với tổ chức tồn tại và role farmer/admin; PATCH `/users/{id}` sửa email/vai trò/tổ chức, khóa/mở khóa, vô hiệu hóa. POST `/users/{id}/reset-password` yêu cầu mật khẩu xác nhận của admin; POST `/auth/change-password` yêu cầu mật khẩu hiện tại của chính người dùng. Mật khẩu mới tối thiểu 12 ký tự, hash Argon2, không trả mật khẩu/hash về frontend. Username/email được kiểm tra trùng không phân biệt hoa thường.

Mọi quyền được kiểm tra tại backend; farmer không thể quản lý tài khoản, tự nâng quyền hoặc sửa tổ chức bằng endpoint admin. Không khóa/vô hiệu hóa/hạ vai trò admin khả dụng cuối cùng, kể cả hai yêu cầu đồng thời. Mở khóa cũng reset bộ đếm sai và khóa tạm. Các thao tác tạo/sửa/reset/đổi mật khẩu đều có audit, không chứa secret. Admin quản lý tài khoản toàn hệ thống nhưng dữ liệu lô không tự mở rộng thành toàn hệ thống.

Frontend giữ công nghệ hiện tại, bổ sung sidebar/header nhất quán, màu xanh và bảng dễ đọc, form tạo/sửa tài khoản và mật khẩu, lọc/tìm/phân trang tài khoản và lô, trạng thái/loading/empty/error. Form vùng trồng và thu hoạch có thể thu gọn. Đăng nhập nhanh chỉ chọn email demo, không tự điền mật khẩu. Chi tiết, timeline, nguồn gốc, bàn giao và tách/gộp dùng các API hiện có và hiển thị đơn vị phù hợp. Số liệu tổng quan hiện mô tả rõ phạm vi trang, không giả làm tổng lô toàn hệ thống.

## File đã tác động

Các đường dẫn dưới đây tính từ repository; một số file đã tồn tại ở trạng thái untracked trước phiên sửa.

| Nhóm | File sửa trong lần thực hiện |
| --- | --- |
| Model/migration/xác thực | `backend/app/models.py`, `database.py`, `security.py`, `schemas.py`, `main.py` |
| API | `backend/app/routers/users.py`, `auth.py`, `audit.py`, `events.py`, `batches.py`, `farms.py`, `handovers.py`, `__init__.py` (dọn dòng cuối) |
| Lịch sử/truy xuất | `backend/app/hash_chain.py`, `audit.py`, `services/traceability.py` |
| Seed cũ/cấu hình | `backend/app/seeds/seed_lineage_graph.py`, `backend/.gitignore` |
| Test cập nhật | `backend/tests/conftest.py`, `test_database_migration.py`, `test_audit_logs.py`, `test_batch_events.py`, `test_batch_events_integrity.py`, `test_handovers.py` |
| Frontend | `frontend/index.html`, `frontend/css/style.css`, `frontend/js/app.js` |
| Tài liệu | `README.md`, `backend/README.md` |

File mới của lần thực hiện: `backend/app/seeds/seed_demo.py`, `backend/tests/test_completion.py`, `scripts/seed_demo.bat`, `docs/DEMO.md`, báo cáo này và ảnh `docs/qa/dashboard-desktop.png`, `dashboard-mobile.png`, `traceability-desktop.png`.

## Chạy ứng dụng, seed và tài khoản demo

Chi tiết lệnh backend/frontend, môi trường và kịch bản: [DEMO.md](DEMO.md).

Từ gốc repository: ` .\scripts\seed_demo.bat `. Mật khẩu tự sinh lấy bằng `Get-Content .\backend\.demo-password.local`, hoặc dùng `DEMO_PASSWORD` đã đặt trước lần seed đầu; chạy lại không đổi password cũ.

| Tài khoản | Quyền |
| --- | --- |
| demo_admin@demo.local | admin |
| demo_farm@demo.local | farmer / canh tác |
| demo_packing@demo.local | farmer / đóng gói |
| demo_distribution@demo.local | farmer / phân phối |

Seed sử dụng các thao tác tạo lô/tách/gộp/bàn giao và hàm hash hiện có. Trên DB mới tạo 11 lô và 6 bàn giao, có pending, quá hạn, accepted, rejected, split, merge, lineage qua ba tổ chức. Script launcher đã chạy hai lần trên DB tạm, giữ nguyên số lượng và toàn bộ chuỗi hợp lệ. Test seed còn chứng minh dữ liệu ngoài marker và mật khẩu đã có không bị thay đổi.

## Kết quả kiểm chứng

| Kiểm tra | Kết quả |
| --- | --- |
| Toàn bộ pytest sau thay đổi cuối | **111 đạt, 0 thất bại, 0 skip/deselect**, 51,56 giây |
| Regression/test mới `test_completion.py` | 28 trường hợp mới; tài khoản, concurrency, quyền/alias, giả mạo, lượng, seed, đơn vị và bàn giao quá hạn |
| Warning test | 1 DeprecationWarning của Starlette về alias `anyio.abc.BlockingPortal`; không tắt cảnh báo |
| JavaScript syntax | `node --check frontend/js/app.js` đạt |
| Seed launcher hai lần | Đạt, 11 lô mỗi lần, cùng marker/root/trace, hash hợp lệ |
| Lint toàn `backend/app` | **Chưa đạt: 30 lỗi** — 24 E501 và 6 C901; chủ yếu seed lineage cũ, migration, create/split/merge và BFS. Không thay cấu hình để bỏ qua |
| Module tài khoản/auth/seed mới | Đã chạy flake8 riêng, đạt |
| Browser | Đã đăng nhập admin/phân phối, lọc và empty state tài khoản, mở form, danh sách lô, chi tiết/timeline/BFS và xác thực 5 sự kiện; không có console error/warn trong lần kiểm tra cuối |
| Responsive | Desktop và 390×844; document không tràn ngang. Bảng dài/sidebar mobile cuộn riêng |

Luồng A (tạo tài khoản → tổ chức/role → đăng nhập), B (thu hoạch → detail/event), C (gửi → nhận/từ chối → ownership/event), D (split → merge → BFS), E (quyền giữa tổ chức), F (hash/tamper/append-only) được kiểm thử tự động qua API thật của FastAPI với database tạm. Chưa thao tác end-to-end bằng trình duyệt cho mọi bước ghi của A–D; đặc biệt không nhập/submission mật khẩu mới qua UI. Vì vậy không coi toàn bộ UI đã được xác minh 100%. Kiểm tra tải lớn, trình duyệt khác và deploy production chưa chạy.

## Đối chiếu từng yêu cầu

“Đạt” ở bảng này chỉ áp dụng hành vi backend/integration đã kiểm chứng trong môi trường local; giới hạn UI và production ở phần trên vẫn áp dụng. Không suy ra hoàn thành chỉ từ việc có endpoint.

| Yêu cầu | Code chính | Kết quả và bằng chứng |
| --- | --- | --- |
| K-01 | `hash_chain.py`, `models.py`, `database.py` | Đạt — hash, ORM/trigger bất biến, test can thiệp SQL trên DB tạm phát hiện sai |
| S-04 | `security.py`, `routers/auth.py` | Đạt — email/case, mật khẩu, sai 5 lần, HTTP Basic cùng lockout |
| S-05 | `security.py`, `routers/farms.py`, `batches.py`, `events.py` | Đạt — danh sách/chi tiết và alias bị giới hạn tổ chức, 401/403 |
| S-07 | `routers/products.py`, `schemas.py`, frontend | Đạt — danh mục, tên không rỗng, enum kg/tấn/thùng; browser thấy ba đơn vị |
| S-08 | `routers/batches.py`, `utils/batch_code.py` | Đạt — tạo lô có mã tự sinh, HARVEST hash |
| S-09 | `schemas.py`, `routers/batches.py` | Đạt — lượng >0, hữu hạn, tối đa 2 số lẻ/phạm vi lưu trữ, ngày, product/farm và quyền |
| S-10 | `hash_chain.py`, `routers/batches.py`, `handovers.py` | Đạt — tạo/sửa/tách/gộp/bàn giao có sự kiện, ghi đồng thời giữ chuỗi |
| S-11 | `models.py`, `database.py`, `routers/events.py`, `farms.py`, `batches.py` | Đạt — không API sửa/xóa event, ORM/trigger chặn, xóa nguồn có lịch sử trả 409 |
| S-12 | `hash_chain.py`, `routers/events.py` | Đạt — chỉ đúng tampered_event_id và HASH_MISMATCH/CHAIN_BROKEN; UI xác minh chuỗi |
| S-13 | `routers/events.py`, timeline frontend | Đạt — timeline có quyền và lịch sử tăng dần; browser thấy merge/handover |
| S-14 | `routers/batches.py`, danh sách frontend | Đạt — tổ chức đang giữ, tìm mã, lọc product, phân trang |
| S-15 | `routers/handovers.py` | Đạt — pending không đổi holder, chặn tự gửi/trùng pending/hết lượng/sai quyền |
| S-16 | `routers/handovers.py` | Đạt — chỉ bên nhận, lý do tối thiểu, accept đổi holder; concurrency chỉ một kết quả |
| S-17 | `routers/batches.py` split | Đạt — tạo con, quan hệ và cập nhật lượng mẹ trong transaction |
| S-18 | split, khóa ghi SQLite | Đạt — test tách đồng thời bảo toàn lượng, lượng vượt bị chặn |
| S-19 | merge, `schemas.py` | Đạt — cùng sản phẩm, quyền, lượng; kiểm thử các trường hợp không hợp lệ |
| S-20 | split/merge, `hash_chain.py` | Đạt — sự kiện ở mẹ/con và chuỗi liên quan hợp lệ |
| S-21 | `services/traceability.py` | Đạt — BFS, root, nhiều cha, phát hiện chu trình; browser thấy 2 cha và gốc |
| S-22 | `seeds/seed_demo.py`, `scripts/seed_demo.bat` | Đạt — đầy đủ trạng thái demo, hai lần không trùng, không ghi đè dữ liệu thật |
| S-23 | `services/permissions.py`, `routers/events.py` | Đạt — lịch sử truy xuất theo lineage/quyền nghiệp vụ, ẩn metadata nội bộ; test/browser |
| S-24 | `services/overdue_job.py`, `routers/handovers.py` | Đạt — quá 48 giờ hai bên thấy cờ, nhận muộn vẫn có lịch sử |
| S-25 | summary/trace-back, schema, modal frontend | Đạt — sản phẩm, lượng còn, đơn vị, holder, mẹ/con trực tiếp; API và chi tiết UI |

## Vấn đề còn tồn tại trước Sprint 3

1. Lint CI chưa xanh. Cần refactor các hàm lớn và dọn dòng dài còn lại; danh sách chỉ có E501/C901, không còn lỗi import/indent được báo trong lần lint cuối. Không coi pytest xanh là CI xanh.
2. HTTP Basic và sessionStorage vẫn là cơ chế hiện tại: frontend giữ credential trong phiên tab. Chưa thay kiến trúc; khi đưa ra ngoài local cần HTTPS và thiết kế session phù hợp. Không có email reset password/token hết hạn; reset hiện do admin xác nhận mật khẩu và chuyển credential qua kênh riêng.
3. Hash-chain và trigger phát hiện/chặn thay đổi trong phạm vi ứng dụng. Chủ sở hữu file SQLite có toàn quyền có thể xóa trigger và tính lại toàn bộ chuỗi; chưa có chữ ký hoặc checkpoint ngoài database. Event legacy không có metadata bảo vệ mới vẫn giữ cách xác minh tương thích cũ.
4. Khóa ghi SQLite hiện tuần tự hóa các thao tác nghiệp vụ, phù hợp demo/local nhưng chưa benchmark tải lớn. Chưa xác minh PostgreSQL/MySQL hay nhiều worker; cache BFS hiện in-memory với TTL 60 giây.
5. Migration giữ dữ liệu cũ chưa xác định org/product thay vì đoán. Nếu tồn tại bản ghi thiếu liên kết, cần quản trị kiểm tra và bổ sung theo nguồn dữ liệu thực tế; phiên này không sửa database thật để đoán thông tin.
6. Chưa chạy E2E trình duyệt cho tất cả submit quản trị và thu hoạch/tách/gộp/bàn giao, chưa kiểm tra Firefox/Safari hoặc accessibility toàn diện. Ảnh QA dùng dữ liệu tạm; không phải dữ liệu production.
7. Seed nhận diện dataset và không khôi phục trạng thái đã được người dùng thao tác. Chạy lại không reset demo. Script seed lineage cũ vẫn được giữ để tương thích test nhưng không là hướng dẫn seed chính.

Ảnh kiểm tra: [desktop](qa/dashboard-desktop.png), [mobile](qa/dashboard-mobile.png), [truy xuất](qa/traceability-desktop.png).


Ghi chú tổ chức thư mục (10/10/2026): đường dẫn script trong báo cáo đã được cập nhật sang `scripts/`; tại thời điểm lập báo cáo ban đầu chúng nằm ở thư mục gốc. Chỉ dùng `start_demo.bat` cho demo Sprint 1–3 hiện tại.
