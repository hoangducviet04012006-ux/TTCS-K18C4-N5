# AgriTrace — bàn giao và hoàn thiện thiết kế Recall 3B.1B

Ngày kiểm tra: 10/10/2026. Trạng thái: hoàn thiện gói thiết kế và kiểm thử thử nghiệm; CHỜ NGƯỜI DÙNG PHÊ DUYỆT. Không triển khai 3B.2.

## 1. Phạm vi kiểm tra và nguồn chuẩn

Repo thực tế: `D:/TTCS_K23C_N5/TTCS-K18C4-N5`; không sử dụng file zip gửi nhầm. Đã rà soát trạng thái Git, cấu trúc backend/frontend, models, router, RBAC, session, hash-chain, BFS, fixtures, scripts migration, launcher và cấu hình Docker. Đây là kiểm tra mã nguồn và kiểm thử cô lập; không khởi động lại demo, không chạy lifespan/init_db, không chạy Docker/PostgreSQL hay migration dữ liệu thật. Git có nhiều thay đổi chưa commit từ trước; giữ nguyên chúng, không reset và không commit.

Nguồn Recall chính: báo cáo Antigravity `stage3b1_recall_system_design.md` tại thư mục brain `4525d36c-4a79-4f58-9870-f31c8908cbcc`, được lưu nguyên nội dung trong `STAGE3B1_RECALL_DESIGN_REFERENCE.md`. Đã đọc thêm báo cáo rà soát nghiệp vụ Giai đoạn 3 và báo cáo 3A.2.

Đối chiếu trực tiếp workbook mentor `D:/TTCS_K23C_N5/Truy xuất nguồn gốc và giám sát chuỗi lạnh nông sản (1).xlsx`, sheet Backlog, dòng 38–44 (A:O). Báo cáo rà soát nghiệp vụ cũ mô tả S-33–S-39 khác workbook hiện tại; dùng workbook và thiết kế 3B.1 mới làm chuẩn, không triển khai theo bảng mô tả cũ.

## 2. Phần Antigravity đã hoàn thành — được giữ lại

- Backend FastAPI/SQLAlchemy, frontend HTML/CSS/JS, launcher demo, schema hiện có và hệ thống hash-chain.
- RBAC/session và kiểm tra phân quyền; `can_recall_batch` đã tồn tại: inspector được mở Recall; org_admin chỉ khi đang giữ lô; system_admin không tự có quyền này.
- Truy ngược và truy xuôi BFS; trạng thái CONSUMED và khóa nghiệp vụ tương ứng. Bộ kiểm thử trước khi sửa: **167 passed, 2 warnings, 73.66s**.
- Báo cáo thiết kế Recall 3B.1 đã đầy đủ khung nghiệp vụ, API dự kiến, transaction và schema.
- 3B.1B đã có script migration thử và file oracle S-39; chưa có seed S-39 và bộ test Recall. Chưa có Recall ORM model/router/service/frontend chạy thật. Không viết lại các tính năng đã hoàn thành.

## 3. Phần 3B.1B đã bổ sung/hiệu chỉnh

### Migration thử nghiệm

Giữ ba bảng thiết kế từ script cũ: recalls, recall_acknowledgments, idempotency_records. Thay lớp thực thi để toàn bộ DDL chỉ được chạy trong SQLite memory có schema nền; lấy dữ liệu nguồn qua SQLite backup từ kết nối `mode=ro`, `query_only=ON`. Backup đọc cả dữ liệu WAL đã commit, tránh sao chép riêng file database đang mở. Không sửa hay dọn dữ liệu mồ côi.

`--dry-run` là mặc định. `--apply` và `--target-db` bị từ chối trước khi mở nguồn; không cung cấp đường thực thi migration file ở 3B.1B. Có thể chỉ định `--source-db` để thử trên nguồn khác theo chế độ chỉ đọc. Hàm DDL cũng từ chối mọi connection có database file đính kèm, nên symlink/hardlink không tạo đường ghi vào bản gốc.

FK phải bật trước BEGIN; schema nền phải đủ. DDL nằm trong transaction, caller commit sau kiểm tra hoặc rollback khi lỗi. Kiểm tra integrity và dấu vân tay tất cả bảng cũ. Các vi phạm FK có sẵn được báo cáo, không sửa. Ràng buộc mới: reason tối thiểu 20 ký tự sau TRIM, enum trạng thái, thời điểm hoàn tất/xác nhận nhất quán, FK RESTRICT, acknowledgment duy nhất mỗi Recall/tổ chức. Idempotency dùng khóa ghép `(user_id, endpoint, key)` thay khóa toàn cục để tránh xung đột giữa người dùng hoặc thao tác.

Giữ partial unique OPEN và bổ sung unique theo root suốt vòng đời, nhất quán với chính sách “không mở lại” của báo cáo 3B.1. Workbook chỉ yêu cầu chặn trùng OPEN; việc chặn cả sau COMPLETED là **đề xuất thiết kế nghiêm hơn cần phê duyệt**, chưa tác động dữ liệu thật.

### Dữ liệu S-39 và oracle

Bổ sung `backend/scripts/seed_recall_s39.py`: fixture trạng thái đồ thị tổng hợp, yêu cầu Session SQLite memory rõ ràng, từ chối Session trỏ file. Không gọi SessionLocal, không đăng ký startup. CLI tự tạo memory và tự đóng; không tạo tài khoản đăng nhập hay seed trên database thật. Fixture này kiểm tra thuật toán/schema; không thay thế kiểm thử đi qua toàn bộ hành trình API tách/gộp/bàn giao.

Giữ oracle đã được viết trước code seed; bổ sung nguồn sạch `S39-CLEAN-X`, danh sách tầng và lá. Bỏ tên hai kiểm định viên không có bằng chứng. `verified_by=[]`: **chưa đạt yêu cầu hai người đếm độc lập của S-39**, cần người dùng/mentor xác nhận; kiểm thử tự động không giả làm xác nhận con người.

Đồ thị có 7 lô, 6 cạnh, 4 tầng tính cả root, 3 tổ chức. Root A 1000 kg tách B1 400 kg + B2 600 kg. B2 đã tiêu thụ. B1 gộp với nguồn sạch X 200 kg thành C1 600 kg; C1 tách D1 250 kg và D2 350 kg. Recall A có 5 hậu duệ, 3 lá, 3 lô bị ảnh hưởng qua gộp khác nguồn. X là đồng nguồn của C1, **không** phải hậu duệ của A. Tổng tồn thu hồi 600 kg; đã tiêu thụ 600 kg; tổng nguồn vật lý 1200 kg. Số tồn 600 kg bao gồm cả 200 kg nguồn sạch đã trộn, vì phải thu hồi toàn lô trộn, không chỉ phần nguyên liệu A.

### Sửa công thức thống kê trong thiết kế

Không cộng `initial_quantity - remaining_quantity` của mọi lô trong phả hệ: ví dụ S-39 ra **2600 kg**, đếm lại lượng đã tách/gộp. Tồn = tổng remaining_quantity của các lô bị ảnh hưởng, khử trùng theo batch_id và cùng đơn vị. Đã tiêu thụ = tổng `CONSUMED.payload.previous_remaining_quantity` của từng sự kiện hợp lệ trên các lô bị ảnh hưởng. Trường này có sẵn trong endpoint consume hiện tại; nếu lô đã tách một phần rồi bán phần còn lại, không dùng initial_quantity để suy ra đã bán. Dữ liệu lịch sử thiếu chứng cứ tiêu thụ phải ghi “không xác định”, không đoán bằng chênh lệch tồn. Không sửa sự kiện cũ. Dùng Decimal và tách tổng theo đơn vị nếu dữ liệu đa đơn vị.

## 4. Hợp đồng thiết kế để phê duyệt, chưa triển khai

| Story | Hợp đồng 3B.1B | Kiểm chứng hiện tại / phần chờ 3B.2 |
|---|---|---|
| S-33 | Inspector hoặc org_admin đang giữ root; lý do strip >=20; mã riêng; 403 sai quyền; 409 trùng kèm recall_code | Test policy có sẵn + constraint schema thử. HTTP tạo Recall và sự kiện chưa triển khai |
| S-34 | Tính lại hậu duệ mỗi lần xem; không lưu danh sách cứng; khử trùng ID; lô gộp và hậu duệ vẫn bị ảnh hưởng | S-39 đối chiếu BFS. Làm mới động trong Recall thật chờ 3B.2 |
| S-35 | Từng lô có tổ chức/địa điểm/tồn/đã tiêu thụ; nhóm theo tổ chức; công thức sửa như trên | Đối chiếu tồn, tiêu thụ và từng lô S-39. View Recall và privacy chờ 3B.2 |
| S-36 | Banner khi đăng nhập; org_admin đang liên quan xác nhận phần tổ chức mình; chứng cứ ACK append-only | FK/unique/status thử; event, banner và API ACK chưa triển khai |
| S-37 | Tiến độ x/y; mọi tổ chức xác nhận thì tự COMPLETED + event; không xóa lệnh | Schema status thử; completion nghiệp vụ chờ 3B.2 |
| S-38 | Chặn handover/split/merge từ dịch vụ chung, kể cả COMPLETED; lỗi kèm recall_code | Thiết kế hook chung; chưa lắp vào router. Chặn consume thêm là đề xuất cần phê duyệt |
| S-39 | Oracle viết trước seed; 4 tầng/3 tổ chức/merge khác nguồn/CONSUMED; hai người độc lập đếm | Seed memory + oracle + test đạt; xác nhận hai người còn chờ |

API dự kiến dùng prefix hiện có của ứng dụng (router hiện tại không có `/api/v1`): `POST /recalls`, `GET /recalls`, `GET /recalls/{id}`, `POST /recalls/{id}/acknowledge`. Đây chỉ là hợp đồng, chưa đăng ký route. POST tạo trả 201; GET 200; ACK 200. Thiếu lô/lệnh trả 404, input sai 422, quyền sai 403, xung đột/idempotency payload khác trả 409. Kiểm tra session/CSRF cho request ghi theo hệ thống hiện có. Không thay HTTP Basic/session ở giai đoạn này.

Không thêm RECALLED đè lên `Batch.status`; Recall là lớp cảnh báo độc lập giữ nguyên ACTIVE/SPLIT/MERGED/CONSUMED. Inspector vốn chỉ đọc có ngoại lệ hành động Recall theo S-33, không mở rộng quyền sửa nghiệp vụ khác. Tổ chức chỉ nhận chi tiết lô đang thuộc mình và tiến độ cần thiết; inspector có toàn cảnh. Không cho phép system_admin mặc nhiên mở Recall hay xem địa điểm riêng qua API mới. Chi tiết lịch sử vẫn theo cutoff hiện có, không cấp quyền xuyên tổ chức từ một mã Recall.

Một transaction tạo gồm: authorize + trạng thái/idempotency, đọc đồ thị đầy đủ, insert Recall, ACK projections cho tổ chức liên quan, ghi RECALL_INIT/RECALL_AFFECTED và audit bằng helper hiện có, lưu kết quả idempotency, một commit. Mọi lỗi rollback tất cả. ACK có một transaction riêng: kiểm tra đúng tổ chức, chỉ PENDING -> ACKNOWLEDGED một lần, ghi event append-only gắn recall_id/org_id/actor/time/notes, cập nhật projection, kiểm tra toàn bộ ACK rồi ghi RECALL_COMPLETED nếu đủ, lưu idempotency, commit. Projection có thể cập nhật nhưng event chứng cứ không sửa/xóa; không có API sửa ghi chú ACK, hủy hay xóa Recall.

Retry cùng `(actor, endpoint, key)` và cùng hash payload trả lại kết quả đã lưu; hash khác trả 409. Phân quyền được kiểm tra lại trước trả kết quả; thành công và idempotency phải commit cùng nhau. Dùng unique DB và transaction để giải quyết tạo/ACK đồng thời, không chỉ kiểm tra Python trước insert. Chỉ lưu kết quả thành công; lỗi rollback không để lại bản ghi “đang xử lý”. Đề xuất không tự xóa idempotency trong 3B.2 để giữ chứng cứ; thời hạn lưu cần quyết định trước production.

Danh sách ACK lấy từ tập tổ chức đang gắn với root + các hậu duệ, kể cả CONSUMED, khử trùng; S-39 cho FARM/PROC/DIST. Mỗi lần đọc/ACK tính lại danh sách ảnh hưởng không dùng cache. Nếu dữ liệu ngoài ứng dụng làm xuất hiện tổ chức mới khi OPEN, transaction hòa giải thêm PENDING và event, không hoàn tất theo mẫu cũ. COMPLETED không tự mở lại: nếu dữ liệu ngoại lệ xuất hiện sau hoàn tất thì báo cảnh báo cần thanh tra xử lý, tiếp tục khóa lô. Không có đường sửa đồ thị bình thường khi Recall đã khóa. Yêu cầu S-34 “con mới xuất hiện” kiểm chứng khả năng đọc lại đồ thị trong tình huống dữ liệu mới/ngoại lệ, không cấp quyền split vượt S-38.

## 5. Rủi ro phải xử lý trước khi tích hợp 3B.2

- BFS hiện có cache 60 giây; Recall phải gọi `use_cache=False`. Giới hạn max_nodes hiện dừng và trả một phần: Recall cần từ chối kết quả thiếu/truncated, không mở lệnh hay báo hoàn tất trên danh sách thiếu.
- BFS đang dùng visited_expanded kết hợp path; cần kiểm tra chu trình toàn đồ thị (ví dụ DFS màu/Kahn trên adjacency snapshot) trước giao dịch Recall. Test cycle đơn giản hiện có chưa chứng minh mọi đồ thị hội tụ đều an toàn. Không sửa thuật toán production trong 3B.1B.
- Khử trùng giữa các tầng; lô xuất hiện qua nhiều đường không làm tăng tổng tồn hay tạo ACK/event trùng. Đánh dấu merge khác nguồn dựa trên tập root tổ tiên và lan xuống hậu duệ; không chỉ dựa relation_type của cạnh trực tiếp.
- Cần kiểm thử đồng thời Recall-vs-split/merge/handover/consume, bảo đảm guard và mutation cùng transaction/khóa phù hợp SQLite hoặc PostgreSQL; schema unique không đủ chặn giao dịch vật lý.
- Notification, quyền xem chi tiết, ACK append-only, guard S-38, completion, rollback lỗi ghi event và idempotency HTTP phải được kiểm thử khi triển khai 3B.2; test design này không chứng nhận các chức năng chưa có.
- Script cũ ở repo và startup `init_db` vẫn có khả năng thay đổi schema khi được chạy; không chạy chúng trong lần kiểm tra này. PostgreSQL compose/schema chỉ được đọc, chưa xác nhận môi trường PostgreSQL chạy thật.

## 6. Kiểm thử và an toàn dữ liệu

Bộ test mới `backend/tests/test_stage3b1b_recall_design.py` có 26 trường hợp: rerun DDL; FK/enum/reason/timestamp; unique Recall OPEN và COMPLETED; acknowledgment; idempotency scope; rollback DDL lỗi giữa chừng; từ chối file/missing schema/FK chưa bật; nguồn đọc không đổi; CLI từ chối apply/target; oracle từng tầng/từng lô/tổ chức/tổng khối lượng/cross-origin/hash-chain; RBAC và seed từ chối database file.

Lệnh từ thư mục backend, đặt DATABASE_URL trỏ file tạm trước import app (không dùng default ttcs.db):

```powershell
$env:DATABASE_URL = 'sqlite:///' + (Join-Path $env:TEMP 'agritrace_codex_test_guard.db').Replace('\','/')
.\.venv\Scripts\python.exe -m pytest -q --disable-warnings
.\.venv\Scripts\python.exe scripts/migrate_stage3b_recall.py --dry-run
.\.venv\Scripts\python.exe -m scripts.seed_recall_s39
```

Dry-run trên snapshot chỉ đọc database gốc: integrity `ok`; ba bảng mới đều 0 bản ghi; bảng cũ được giữ nguyên; 26 vi phạm FK lịch sử được báo cáo nguyên trạng. Seed memory: 7 lô, 5 hậu duệ, 4 tầng gồm root.

Đối chiếu trước/sau lưu ở `docs/qa/recall_db_before.json` và `recall_db_after.json`; log test ở `recall_tests.txt`. Đây là SHA-256 của biểu diễn có thứ tự tất cả row từng bảng, không chứa giá trị tài khoản/sự kiện. File gốc đang bị khóa với Get-FileHash nên bằng chứng dùng fingerprint dữ liệu qua SQLite read-only; không tuyên bố có đối chiếu SHA-256 byte toàn file. Không dừng tiến trình của người dùng để mở khóa.

Kết quả toàn bộ suite cuối và đối chiếu dữ liệu: xem mục kết quả bổ sung phía dưới.

## 7. Phê duyệt cần có trước 3B.2

Gói thiết kế sẵn sàng review. Đề nghị xác nhận chính sách một Recall duy nhất suốt đời root; chặn consume bổ sung; công thức thống kê và xử lý dữ liệu thiếu chứng cứ; ACK scope/đối soát động; hợp đồng API/session/idempotency; quy tắc fail-closed khi đồ thị thiếu/chu trình. S-39 vẫn cần hai người đếm độc lập và ghi lại xác nhận thật. Không tự động bắt đầu 3B.2, không migration thật, không triển khai production.

## 8. Kết quả cuối

- Toàn bộ suite: **193 passed, 2 warnings, 74.15s** (167 có sẵn + 26 test design mới). Log: `docs/qa/recall_tests.txt`. Sau chỉnh đóng kết nối nguồn đúng cách, chạy lại 26 test liên quan: 26 passed, 0.43s.
- Database gốc qua kiểm tra chỉ đọc: **integrity_check = ok**; **110 batch_events**, **26 orphan events**. Fingerprint số lượng và SHA-256 dữ liệu của **tất cả 11 bảng** trước/sau giống hệt, không có bảng Recall mới trên nguồn.
- DDL Recall chỉ thử trong memory trên backup chỉ đọc; script không cung cấp migration file. Không sửa lịch sử hoặc orphan, không gọi các migration cũ.
- Không thêm/sửa production app, frontend, launcher; thay đổi lần này giới hạn script thử Recall, seed memory, oracle, test design và báo cáo/evidence.
- 3B.1B sẵn sàng phê duyệt về thiết kế. S-39 còn chờ hai người đếm độc lập; 3B.2 chưa bắt đầu.

Kiểm tra `git diff --check` còn báo whitespace trong thay đổi có sẵn: `backend/app/routers/batches.py:1295`, `backend/app/security.py:231`, `frontend/js/app.js:1653`. Không sửa các file này trong 3B.1B. Hai warnings pytest không làm test thất bại.
