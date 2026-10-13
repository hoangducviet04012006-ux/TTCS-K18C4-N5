# AgriTrace — kết quả Backend Recall 3B.2A

Ngày: 10/10/2026. Phạm vi được phê duyệt: lập trình backend và thử trên database riêng. Không triển khai frontend Recall, không triển khai production, không migration database gốc.

## 1. Kết quả triển khai

Đã triển khai ORM, Recall service, router, kiểm tra phong tỏa dùng chung, sự kiện hash-chain và audit log. Giữ nguyên `batches.status`; Recall độc lập với ACTIVE/SPLIT/MERGED/CONSUMED. Bốn thao tác handover/split/merge/consume bị chặn khi lô nằm trong Recall OPEN hoặc COMPLETED; chặn cả nhận một handover đã PENDING trước khi mở Recall và các alias endpoint hiện có.

Chính sách **một Recall cho mỗi root trong suốt vòng đời là tạm thời, chờ mentor xác nhận**. Chính sách có unique index tại DB và nhãn `ONE_RECALL_PER_ROOT_LIFETIME_PENDING_MENTOR` trong phản hồi API. COMPLETED không tự mở lại; hậu duệ phát sinh sau đó vẫn bị phong tỏa và trả cảnh báo bất thường.

## 2. File tạo mới và thay đổi trong lần này

Các đường dẫn dưới đây tính từ `D:/TTCS_K23C_N5/TTCS-K18C4-N5`. Các thay đổi đã tồn tại từ Antigravity/Codex trước 3B.2A được giữ lại, không reset/commit.

| File mới | Mục đích |
|---|---|
| backend/app/recall_models.py | ORM ba bảng, constraints/index, bảo vệ tạo schema trên DB gốc |
| backend/app/services/recall_database.py | Nhận diện DB gốc kể cả hardlink, kiểm tra schema/index/FK, khóa ghi và snapshot đọc |
| backend/app/services/recall_graph.py | Đồ thị đầy đủ không cache, Kahn phát hiện cycle, max_nodes, nguồn gộp, chứng cứ tiêu thụ |
| backend/app/services/recall.py | Create/ACK nguyên tử, idempotency, audit, tiến độ, cô lập tổ chức, cảnh báo, guard chung |
| backend/app/routers/recalls.py | Năm API, input validation, Idempotency-Key, session/Basic/CSRF hiện có |
| backend/scripts/prepare_recall_test_database.py | Dry-run mặc định; chỉ tạo một bản sao thử mới khi chỉ định rõ, không overwrite/apply file có sẵn |
| backend/tests/test_stage3b2a_recall_api.py | Bộ kiểm thử API và concurrency trên từng SQLite file tạm riêng |

| File đã sửa trong lần này | Nội dung |
|---|---|
| backend/app/models.py | Re-export Recall models; đăng ký unique index chứng cứ Recall trên batch_events |
| backend/app/database.py | Startup bỏ qua toàn bộ create/migration/seed khi engine là DB gốc; không tự tạo ba bảng Recall trên bất kỳ engine startup nào |
| backend/app/main.py | Đăng ký router /recalls, không đổi prefix hiện có |
| backend/app/routers/batches.py | Guard split/merge/consume; khóa consume trước đọc; kiểm cả tập đầu vào merge trước lỗi quantity |
| backend/app/routers/handovers.py | Guard tạo và nhận handover |
| backend/app/routers/events.py | Cấm endpoint sự kiện thủ công giả mạo bốn sự kiện Recall, gồm alias và chữ thường |
| backend/scripts/seed_recall_s39.py | Bổ sung Farm tương ứng với Plot để fixture hợp lệ khi bật FK; giữ nguyên bảy lô/đồ thị/oracle |
| backend/scripts/migrate_stage3b_recall.py | Cập nhật docstring trỏ sang script tạo test copy; vẫn dry-run memory mặc định và từ chối --apply |

Tài liệu/bằng chứng mới: báo cáo này; `docs/qa/recall_3b2a_schema.sql`, `recall_3b2a_migration.json`, `recall_3b2a_before.json`, `recall_3b2a_after.json`, `recall_3b2a_tests.txt`. Database thử tổng hợp tại `.recall-trial/recall_3b2a.db`; file DB được ignore bởi quy tắc Git có sẵn.

## 3. Schema thực trên bản sao đã migrate

DDL thực trích xuất từ `sqlite_master`, không phải bản mô tả dự kiến: **docs/qa/recall_3b2a_schema.sql**. File chỉ để review; không thực thi trên ttcs.db.

| Bảng | Trường chính / ràng buộc |
|---|---|
| recalls | id, recall_code unique, root_batch_id FK RESTRICT, reason TRIM >=20, created_by_user_id/org_id FK RESTRICT, status OPEN/COMPLETED, created_at, completed_at nhất quán; unique root trọn đời + partial unique OPEN |
| recall_acknowledgments | id, recall_id/org_id FK RESTRICT, status PENDING/ACKNOWLEDGED, actor/time/notes; unique (recall_id, organization_id); ACK phải có actor và timestamp, PENDING chưa có chúng |
| idempotency_records | PK (user_id, endpoint, key), FK user RESTRICT, request_hash, response_code, response_body, created_at; key dài 1–128 |

Thêm **unique expression index `uq_recall_event_evidence`** trên `batch_events`: event_type, batch_id, recall_id trong JSON và organization_id trong JSON (COALESCE -1 khi không có). Chỉ áp dụng bốn loại sự kiện Recall. Ngăn chèn lặp cùng chứng cứ ngay ở tầng SQLite, không cập nhật bất kỳ dòng sự kiện cũ nào. Trigger append-only batch_events hiện có vẫn giữ nguyên.

ORM và DDL script có thể khác thứ tự cột composite PK/tên các index tra cứu; các khóa ghép, tên cột và semantics tương thích. Đã kiểm tra bằng API thật trên bản sao chỉ có schema nền, sau khi chạy migration script: tạo Recall, ACK ba tổ chức, COMPLETED.

Bản thử giữ nguyên bảy lô và tám sự kiện fixture S-39; ba bảng Recall ban đầu rỗng. Kết quả migration: nguồn không đổi, toàn bộ bảng cũ giữ nguyên, integrity=ok, FK violations=0; Python SQLite **3.45.1**. Tài khoản fixture không có mật khẩu demo dùng để đăng nhập; đây là artifact kiểm tra schema, không phải database demo production. Test API tự tạo các tài khoản riêng trong mỗi database tạm.

## 4. API và phân quyền

| API | Kết quả / quyền |
|---|---|
| POST /recalls | 201; inspector hoặc org_admin đang giữ root; reason strip >=20; bắt buộc Idempotency-Key |
| GET /recalls | 200; inspector xem toàn cảnh; người dùng tổ chức chỉ thấy lệnh liên quan và phần lô của mình |
| GET /recalls/{id} | 200; không liên quan trả 403, không tồn tại trả 404 |
| GET /recalls/my-alerts | 200; phần tổ chức mình, severity CRITICAL cho OPEN/bất thường; COMPLETED vẫn báo QUARANTINED |
| POST /recalls/{id}/acknowledge | 200; chỉ org_admin thuộc tổ chức liên quan; không nhận organization_id từ client; Idempotency-Key bắt buộc |

Không đổi router prefix. `/my-alerts` được đăng ký trước `/{id}`. Input sai trả 422; vai trò/tổ chức sai trả 403; xung đột Recall/idempotency/ACK/phong tỏa trả 409, gồm mã Recall khi phù hợp. Thiếu schema/index/FK hoặc chọn DB gốc trả 503. Database bận trả 503 + Retry-After; client retry cùng key. API thử nghiệm chỉ hỗ trợ SQLite riêng, không kích hoạt trên PostgreSQL.

Dùng get_current_user hiện có; cookie bắt buộc CSRF cho POST. Giới hạn database chạy **trước authentication**, tránh việc xác thực Basic cập nhật hash mật khẩu hoặc failed-login trên DB gốc. Không tự cấp quyền Recall cho system_admin. Inspector chỉ có ngoại lệ mở Recall, không được ACK thay tổ chức.

Phản hồi chứa lô, trạng thái, tổ chức, lượng tồn/tiêu thụ, cờ merge khác nguồn, metrics theo đơn vị, tiến độ và cảnh báo. Inspector thấy toàn bộ; tổ chức chỉ thấy lô hiện thuộc mình và chi tiết ACK của mình, không thấy location/notes bên khác. Tổng tiến độ x/y vẫn có để theo dõi. `location` hiện lấy từ Plot nguồn theo dữ liệu có sẵn; hệ thống chưa có trường vị trí kho/cửa hàng hiện thời để bảo đảm một địa chỉ lưu kho cụ thể. Không suy đoán địa chỉ đó.

## 5. Transaction, concurrency và chứng cứ

Create/ACK mỗi lần chỉ có một commit trong Recall service; mọi lỗi rollback Recall, ACK projection, sự kiện, audit và idempotency cùng nhau. Không commit trong các helper. Khóa ghi SQLite được lấy trước khi đọc trạng thái quyết định và giữ đến commit/rollback. Split/merge/handover dùng khóa ghi hiện có; consume được bổ sung cùng cơ chế. Snapshot GET bắt đầu transaction đọc rõ ràng vì pysqlite legacy không tự BEGIN cho SELECT.

Cơ chế hiện tại dùng **khóa writer toàn database SQLite** qua no-op UPDATE status=status, không đổi giá trị status. Đây là cách serialize cho môi trường thử nghiệm, có chi phí contention; không tuyên bố khả năng mở rộng production hay khóa dòng PostgreSQL. Nếu thao tác vật lý thắng trước, Recall đọc đồ thị/trạng thái sau thao tác đó; nếu Recall thắng trước, thao tác vật lý bị chặn. Không có trường hợp vật lý thành công sau RECALL_INIT.

Đồ thị Recall đọc lại relation trực tiếp, không dùng cache BFS 60 giây. Kiểm tra đầy đủ tập root + hậu duệ và tổ tiên của hậu duệ (kể cả nguồn sạch khác). Bounded traversal không trả kết quả cắt; Kahn phát hiện mọi cycle trong tập liên quan, gồm hội tụ/chu trình nhiều nhánh. Duyệt cả hậu duệ bất thường của CONSUMED để tiếp tục phong tỏa; mỗi batch chỉ tính một lần và level là đường ngắn nhất từ root.

Sự kiện: RECALL_INIT trên root; RECALL_AFFECTED mỗi hậu duệ; RECALL_ACKNOWLEDGED trên chuỗi root với recall_id/org/actor/time/notes; RECALL_COMPLETED khi ACK đủ. Đây là chứng cứ append-only; bảng ACK là projection. Endpoint sự kiện thủ công không được ghi các loại Recall. Audit CREATE/UPDATE/COMPLETE nằm cùng transaction.

Idempotency scoped theo người dùng + endpoint (ACK gồm recall_id) + key; hash từ payload chuẩn hóa. Retry payload giống trả lại thành công đã lưu, không tạo sự kiện/ACK/audit mới. Payload khác trả 409. Response lưu là snapshot của lần thành công; dùng GET để đọc tiến độ mới nhất. Replay kiểm lại quyền và scope vai trò/tổ chức; đổi scope trả 403, không trả dữ liệu cũ thuộc quyền xem rộng hơn hoặc tổ chức cũ.

## 6. Khối lượng, dữ liệu động và bất thường

S-39: 4 tầng gồm root, 3 tổ chức, 7 lô, 5 hậu duệ của A, 3 lô chịu ảnh hưởng qua gộp khác nguồn, tồn 600 kg, tiêu thụ có chứng cứ 600 kg. Nguồn sạch X 200 kg không phải hậu duệ của A nhưng lô trộn và hậu duệ của nó phải thu hồi toàn bộ. API khớp từng lô/level/status/remaining với oracle viết trước code seed.

Tồn cộng remaining_quantity, không cộng lặp giữa đường/tầng; tổng riêng từng đơn vị. Tiêu thụ dùng CONSUMED.previous_remaining_quantity và chuỗi hash hợp lệ. Không có chứng cứ, payload lỗi/âm/NaN, nhiều chứng cứ CONSUMED bất thường hoặc chain không hợp lệ thì trả unknown/null; không suy ra từ initial-minus-remaining. Tổng gồm unknown trả consumed_quantity=null và vẫn cung cấp known_consumed_quantity + danh sách cần kiểm tra.

OPEN có lô mới tại tổ chức chưa ACK: GET tính lại ngay, ACK transaction thêm projection PENDING và sự kiện AFFECTED còn thiếu; không hoàn tất theo danh sách cũ. Nếu lô mới xuất hiện tại tổ chức **đã ACK**, chứng cứ cũ không được coi là xác nhận cho phần mới: giữ OPEN, trả GRAPH_CHANGED_AFTER_ACK, cảnh báo cần inspector review. Không sửa/reset ACK lịch sử và không tự tạo ACK lặp.

COMPLETED có hậu duệ mới: status vẫn COMPLETED, cảnh báo NEW_DESCENDANTS_AFTER_COMPLETION trong API/alerts và warning backend; phong tỏa cả lô mới. Không sửa lịch sử hay tự reopen. Cảnh báo ở đây là API + log, chưa có frontend banner/email/push.

## 7. Kiểm thử và an toàn database

Bộ mới **61 test API** bao phủ S-33–S-39: toàn bộ role matrix, tổ chức không liên quan, CSRF, validation, lô CONSUMED, chứng cứ thiếu/sai, nhiều tầng/diamond/cycle/max_nodes, idempotency khác payload/scope/replay sau đổi quyền, ACK/completion, bất thường sau COMPLETE/sau ACK, tất cả guard và alias, handover đã pending, giả mạo sự kiện thủ công, unique event tại DB, rollback lỗi từng loại sự kiện, tạo/ACK đồng thời, Recall-vs-bốn thao tác vật lý, migration fresh + API, từ chối DB gốc trước auth, hardlink và startup bảo vệ.

Mỗi test API sử dụng SQLite file tạm riêng với FK ON và append-only triggers; dùng nhiều kết nối thật cho concurrency. Không vào lifespan của app trong TestClient; get_db override theo từng test. DATABASE_URL đặt thành đường dẫn file tạm trước import app. Không reset hoặc seed backend/ttcs.db.

Lệnh từ backend:

```powershell
$env:DATABASE_URL = 'sqlite:///' + (Join-Path $env:TEMP 'agritrace_codex_test_guard.db').Replace('\','/')
.\.venv\Scripts\python.exe -m pytest -q --disable-warnings
.\.venv\Scripts\python.exe -m flake8 app/recall_models.py app/services/recall.py app/services/recall_graph.py app/services/recall_database.py app/routers/recalls.py scripts/prepare_recall_test_database.py --max-line-length=120
```

Thử migration mặc định trong bộ nhớ, trên artifact riêng:

```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_recall_test_database --source-db ..\.recall-trial\recall_3b2a.db
```

Chỉ tạo thêm một test copy khi chỉ định cả `--create-test-copy` và `--output-db NEW_TEST_FILE.db`. Script từ chối output có sẵn/DB gốc/hardlink; nguồn mở mode=ro và backup SQLite, không copy rời file WAL. Script cũ vẫn từ chối --apply/--target-db; không có đường tự apply vào database gốc.

Đối chiếu database gốc bằng SQLite chỉ đọc và fingerprints dữ liệu/schema, lưu trước/sau ở docs/qa/recall_3b2a_before.json và recall_3b2a_after.json. Đây là fingerprint logic và schema, không tuyên bố SHA-256 byte toàn file. Kết quả cuối ghi bên dưới sau khi toàn suite hoàn tất.

## 8. Giới hạn và quyết định còn chờ

- Chính sách một Recall/root trọn đời vẫn chờ mentor, dù người dùng đã cho phép áp dụng tạm trên test DB.
- S-39 có oracle trước code và kiểm tra tự động; **chưa có xác nhận đếm tay từ hai con người độc lập**. Không bịa tên người kiểm định.
- Chưa tích hợp frontend Recall, email/push hay migration production; không chạy demo/Docker/PostgreSQL.
- Xử lý bất thường giữ phong tỏa; quy trình xử lý hồ sơ ngoại lệ do inspector/mentor quyết định, không có API tự sửa dữ liệu hay xóa/reset chứng cứ.
- SQLite database-wide writer reservation và duyệt relation toàn bộ hiện phù hợp thử nghiệm; cần đánh giá tải/index/query theo dữ liệu thực trước production.
- DB gốc bị loại khỏi startup create/migrate/seed và Recall endpoints. Các endpoint cũ khác vẫn có hành vi cũ khi người dùng chủ động gọi; không gọi chúng trên DB gốc trong lần này.

## 9. Kết quả cuối đã xác minh

- **254/254 tests PASSED, 2 warnings, 85.81s**: toàn bộ 193 test có sẵn + 61 test Recall mới. Log đầy đủ: `docs/qa/recall_3b2a_tests.txt`.
- Flake8 các module mới và script test-copy: **0 lỗi** (max-line-length=120; gồm kiểm tra complexity).
- Migration chỉ trên snapshot tổng hợp riêng: integrity=ok, foreign_key_check=0, nguồn/bảng cũ giữ nguyên. Dry-run mặc định chạy lại trên artifact riêng cũng thành công và không ghi nguồn.
- **Database gốc: integrity=ok; 110 sự kiện; 26 sự kiện mồ côi; dữ liệu tất cả 11 bảng và fingerprint schema trước/sau giống hệt**. Không thêm bảng Recall hoặc index mới vào bản gốc. Không migration/reset/seed backend/ttcs.db.
- `git diff --check` vẫn báo whitespace có sẵn tại cuối batches.py, security.py và frontend/js/app.js; không dọn các thay đổi cũ ngoài phạm vi.
- Hoàn thành phạm vi backend thử nghiệm 3B.2A. Chưa triển khai production, frontend hay giai đoạn tiếp theo. Các quyết định mentor và xác nhận hai người cho S-39 vẫn chờ như mục 8.
