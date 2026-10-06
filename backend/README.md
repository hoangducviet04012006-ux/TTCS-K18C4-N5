# Backend - TTCS K18C4

Backend API cho đề tài **"Truy xuất nguồn gốc và giám sát chuỗi lạnh nông sản"**.

- **Framework:** Python + FastAPI
- **Database:** SQLite (file local, không cần cài server)
- **ORM:** SQLAlchemy 2.0
- **Sprint 1 (nền tảng):** cấu hình FastAPI, kết nối SQLite, endpoint kiểm tra
  hệ thống `GET /health`.
- **Sprint 2:** module **Farm** — quản lý vùng trồng (`POST /farms`, `GET /farms`).
- **Sprint 3:** module **Batch** — quản lý lô nông sản (`POST /batches`,
  `GET /batches`, `GET /batches/{batch_id}`).
  Quan hệ dữ liệu: `Farm 1 ---- N Batch`.
- **Sprint 4:** **đăng nhập + phân quyền cơ bản** — bảng `users`, `POST /auth/login`,
  `GET /users` (chỉ admin) và dependency `require_admin` / `require_farmer`.
  *Không dùng JWT*: API cần quyền xác thực bằng **HTTP Basic**
  (Swagger UI có sẵn nút **Authorize**).
- **Sprint 5:** hoàn thiện **CRUD đầy đủ** — bổ sung `PUT` / `DELETE`
  cho `/farms` và `/batches` (xoá **chỉ dành cho `admin`**) kèm schema
  `FarmUpdate`/`BatchUpdate`/`DeleteResponse`; frontend ẩn/hiện theo trạng thái
  đăng nhập, thêm cột **Thao tác** (Sửa/Xoá) và dashboard thống kê
  (tổng vùng trồng, tổng lô nông sản, tổng sản lượng).
- **Sprint 6:** **bảo mật đăng nhập** — sai mật khẩu **5 lần liên tiếp** thì khoá
  tài khoản **5 phút** và trả `403` (kèm header `Retry-After`); đăng nhập thành
  công hoặc hết thời gian khoá thì bộ đếm tự đặt lại; database cũ tự được thêm 2
  cột qua migration khi server khởi động; kèm bộ test `pytest` trong `tests/`.
- **Sprint 7:** **lịch sử thao tác (audit log)** — bảng `audit_logs` ghi lại
  **ai đã làm gì, lúc nào** mỗi khi tạo/sửa/xoá Farm hoặc Batch (ghi tự động
  trong cùng transaction với thao tác); xem lại bằng `GET /audit-logs`
  (**chỉ admin**, có lọc theo `entity`/`user_id`/`limit`). Không thay đổi API cũ.
  *Chưa có* QR code, blockchain hay nghiệp vụ chuỗi lạnh.

---

## 1. Cấu trúc thư mục

```
backend/
├── app/
│   ├── __init__.py          # Đánh dấu package + khai báo __version__
│   ├── main.py              # Khởi tạo FastAPI, CORS, lifespan, đăng ký router
│   ├── database.py          # Engine SQLite, SessionLocal, Base, get_db, init_db
│   ├── models.py            # ORM models: Farm → "farms", Batch → "batches",
│   │                        #             User → "users",
│   │                        #             AuditLog → "audit_logs" (Sprint 7)
│   ├── schemas.py           # Pydantic: Health / Farm / Batch / Auth / AuditLog
│   │                        #   (Create + Update + Response + DeleteResponse)
│   ├── security.py          # Băm mật khẩu, xác thực/phân quyền (Sprint 4)
│   │                        # + chống dò mật khẩu / khoá tài khoản (Sprint 6)
│   ├── audit.py             # Ghi & đọc lịch sử thao tác (Sprint 7)
│   └── routers/
│       ├── __init__.py      # Export các router
│       ├── health.py        # GET /health
│       ├── auth.py          # POST /auth/login (Sprint 4)
│       ├── users.py         # GET /users - chỉ admin (Sprint 4)
│       ├── farms.py         # CRUD /farms: POST, GET, PUT {id}, DELETE {id} (Sprint 5)
│       ├── batches.py       # CRUD /batches: POST, GET, GET {id}, PUT {id}, DELETE {id}
│       └── audit.py         # GET /audit-logs - chỉ admin (Sprint 7)
├── tests/                   # Test pytest trên SQLite in-memory (Sprint 6/7):
│   ├── conftest.py          # fixture client + database tạm cho mỗi test
│   ├── test_login_lockout.py       # đăng nhập sai 5 lần -> khoá -> 403
│   ├── test_audit_logs.py          # audit log: 6 thao tác, phân quyền, bộ lọc
│   └── test_database_migration.py  # migration thêm cột/bảng cho DB cũ
├── requirements.txt         # Danh sách thư viện Python (kèm pytest/httpx để test)
├── .gitignore               # Bỏ qua file DB, __pycache__, .venv...
└── README.md                # Tài liệu này
```

> File `ttcs.db` (SQLite) sẽ được **tự sinh** trong thư mục `backend/` ở lần
> chạy đầu tiên — không cần commit file này lên Git.

---

## 2. Cách chạy

### Bước 1 — Tạo môi trường ảo (khuyến nghị)

Mở PowerShell tại thư mục `backend/`:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> Nếu PowerShell báo lỗi `Activate.ps1 cannot be loaded`, chạy trước:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
> (hoặc dùng `cmd`: `.venv\Scripts\activate.bat`)

### Bước 2 — Cài thư viện

```powershell
pip install -r requirements.txt
```

### Bước 3 — Chạy server

```powershell
uvicorn app.main:app --reload
```

> Bắt buộc chạy lệnh ở **thư mục `backend/`** vì code dùng absolute import
> dạng `from app.database import ...`.

Server mặc định: <http://127.0.0.1:8000>

### Bước 4 — Kiểm tra

| Mục | Địa chỉ |
| --- | --- |
| Health check | <http://127.0.0.1:8000/health> |
| Swagger UI | <http://127.0.0.1:8000/docs> |
| ReDoc | <http://127.0.0.1:8000/redoc> |

Kiểm tra nhanh bằng `curl`:

```powershell
curl.exe http://127.0.0.1:8000/health
```

Kết quả mong đợi:

```json
{ "status": "running" }
```

Hoặc chạy không cần bật sẵn server (dùng TestClient của FastAPI):

```powershell
pip install httpx
python -c "from fastapi.testclient import TestClient; from app.main import app; c = TestClient(app); print(c.get('/health').status_code, c.get('/health').json())"
```

Kết quả mong đợi: `200 {'status': 'running'}`

### Bước 5 — Đăng nhập (Sprint 4)

Tài khoản demo được tạo tự động ở lần chạy đầu tiên:

| Tài khoản | Mật khẩu | Vai trò |
| --- | --- | --- |
| `admin` | `123456` | admin (toàn quyền, xem được `GET /users`) |
| `farmer` | `123456` | farmer (quản lý vùng trồng + lô nông sản) |

Kiểm tra nhanh bằng `curl.exe`:

```powershell
# Đăng nhập đúng -> 200 + {"username":"admin","role":"admin"}
curl.exe --% -s -X POST http://127.0.0.1:8000/auth/login -H "Content-Type: application/json" -d "{\"username\":\"admin\",\"password\":\"123456\"}"

# Không gửi thông tin đăng nhập -> 401 (GET /farms nay cần quyền)
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8000/farms

# Gửi kèm Basic auth -> 200
curl.exe -s -u admin:123456 http://127.0.0.1:8000/farms
```

> Sau khi đăng nhập ở bước này, mở <http://127.0.0.1:8000/docs> và bấm nút
> **Authorize** để test các API cần quyền ngay trên Swagger UI.
>
> **Sprint 5 — quyền xoá dữ liệu:** chỉ tài khoản **`admin`** gọi được
> `DELETE /farms/{id}` và `DELETE /batches/{id}`. Tài khoản `farmer` vẫn
> thêm/sửa dữ liệu nông sản nhưng sẽ nhận **`403 Forbidden`** khi xoá, và trên
> giao diện frontend thì **nút Xoá không hiện** với farmer.

### Bước 6 — Chạy test tự động (Sprint 6 / Sprint 7)

Bộ test dùng `pytest` + `TestClient` (cần `httpx`), chạy trên SQLite **in-memory**
nên **không** đụng tới file `ttcs.db`:

```powershell
cd backend
python -m pytest                                  # chạy toàn bộ (29 test)
python -m pytest tests/test_login_lockout.py -v   # chỉ test bảo mật đăng nhập
python -m pytest tests/test_audit_logs.py -v      # chỉ test lịch sử thao tác
```

Các kịch bản được kiểm tra:

- **Đăng nhập (Sprint 6):** login đúng vẫn **200**, sai 4 lần vẫn **401**,
  sai **lần thứ 5 → 403** + ghi `failed_login_attempts`/`locked_until` vào database,
  đang bị khoá thì đúng mật khẩu vẫn **403**, hết thời gian khoá thì đăng nhập lại
  được (**200**, bộ đếm về 0), và migration thêm 2 cột cho database cũ.
- **Lịch sử thao tác (Sprint 7):** bảng `audit_logs` đủ 6 cột; **6 thao tác**
  (tạo/sửa/xoá Farm, tạo/sửa/xoá Batch) đều sinh đúng 1 dòng log
  (`action`/`entity`/`entity_id`); log ghi đúng **người thực hiện** (admin/farmer);
  thao tác thất bại (**401/403/404/422**) và các API **đọc** không sinh log;
  `GET /audit-logs` chỉ admin xem được (farmer **403**, chưa đăng nhập **401**),
  mới nhất trước, lọc được theo `entity`/`user_id`/`limit` và `init_db()` tự tạo
  bảng `audit_logs` cho database cũ.

---

## 3. API hiện có

| Method | Endpoint | Mô tả | Quyền | Mã trả về |
| --- | --- | --- | --- | --- |
| GET | `/health` | Kiểm tra hệ thống đang chạy | công khai | `200` |
| POST | `/auth/login` | Kiểm tra tài khoản, trả về `{username, role}` | công khai | `200` · `401` sai tài khoản · `403` tài khoản đang bị tạm khoá · `422` thiếu dữ liệu |
| GET | `/farms` | Lấy danh sách vùng trồng (sắp xếp theo `id` tăng dần) | farmer **hoặc** admin | `200` · `401` |
| POST | `/farms` | Tạo vùng trồng mới | farmer **hoặc** admin | `201` · `401` · `422` dữ liệu sai |
| PUT | `/farms/{farm_id}` | Cập nhật (thay thế) vùng trồng theo `id` | farmer **hoặc** admin | `200` · `401` · `404` không tìm thấy · `422` dữ liệu sai |
| DELETE | `/farms/{farm_id}` | Xoá vùng trồng **và các lô nông sản của nó** | **chỉ admin** | `200` · `401` · `403` sai vai trò · `404` không tìm thấy |
| GET | `/batches` | Lấy danh sách lô nông sản (sắp xếp theo `id` tăng dần) | công khai | `200` |
| GET | `/batches/{batch_id}` | Xem chi tiết một lô nông sản | công khai | `200` · `404` không tìm thấy |
| POST | `/batches` | Tạo lô nông sản (kiểm tra `farm_id` tồn tại) | farmer **hoặc** admin | `201` · `401` · `404` farm không tồn tại · `422` dữ liệu sai |
| PUT | `/batches/{batch_id}` | Cập nhật (thay thế) lô nông sản - đổi được `farm_id` nếu tồn tại | farmer **hoặc** admin | `200` · `401` · `404` lô/farm không tồn tại · `422` |
| DELETE | `/batches/{batch_id}` | Xoá một lô nông sản | **chỉ admin** | `200` · `401` · `403` sai vai trò · `404` không tìm thấy |
| GET | `/users` | Danh sách tài khoản (không kèm mật khẩu) | **chỉ admin** | `200` · `401` · `403` sai vai trò |
| GET | `/audit-logs` | **Lịch sử thao tác** (mới nhất trước) - lọc `?entity=farm\|batch`, `?user_id=`, `?limit=1..500` | **chỉ admin** | `200` · `401` · `403` sai vai trò · `422` tham số lọc sai |

> ✅ **Sprint 5 hoàn thiện CRUD:** cả Farm và Batch đều có đủ `POST` / `GET` /
> `GET {id}` (Batch) / `PUT` / `DELETE`. `PUT` là cập nhật **thay thế**: client
> gửi đầy đủ các trường như khi tạo mới, thiếu trường → `422`.
>
> ⚠️ **Thay đổi so với Sprint 3/4:** `PUT` / `DELETE` là endpoint **mới**, trong
> đó nhóm `DELETE` **chỉ admin** gọi được (farmer → `403`, giao diện cũng **ẩn nút
> Xoá**). `GET /health`, `GET /batches`, `GET /batches/{id}` vẫn **công khai**;
> `GET /farms`, `POST /farms`, `PUT /farms/{id}`, `POST /batches`, `PUT /batches/{id}`
> yêu cầu đăng nhập (farmer hoặc admin).

### Phân quyền theo từng thao tác (Sprint 5)

| Thao tác | farmer | admin |
| --- | --- | --- |
| Xem dữ liệu (`GET /farms`) | ✅ | ✅ |
| Thêm dữ liệu (`POST /farms`, `POST /batches`) | ✅ | ✅ |
| Sửa dữ liệu (`PUT /farms/{id}`, `PUT /batches/{id}`) | ✅ | ✅ |
| Xoá dữ liệu (`DELETE /farms/{id}`, `DELETE /batches/{id}`) | ❌ `403 Forbidden` | ✅ |
| Quản lý tài khoản (`GET /users`) | ❌ `403 Forbidden` | ✅ |
| Xem lịch sử thao tác (`GET /audit-logs`) | ❌ `403 Forbidden` | ✅ |

### Xoá dữ liệu — cơ chế xoá dây chuyền (Sprint 5)

- **`DELETE /farms/{farm_id}`** xoá vùng trồng **và toàn bộ lô nông sản của nó**
  nhờ `cascade="all, delete-orphan"` khai báo ở quan hệ `Farm 1-N Batch`
  (`app/models.py`) → không để lại dữ liệu mồ côi. Số lô bị xoá kèm được trả về
  ở field `deleted_batches`.
- **`DELETE /batches/{batch_id}`** chỉ xoá lô đó → `deleted_batches` là `null`.
- Cả hai trả **`200 OK`** kèm `DeleteResponse` (không dùng `204 No Content` để
  giao diện hiển thị được thông báo cho người dùng):

```json
{
  "message": "Đã xoá vùng trồng #2 và 2 lô nông sản thuộc vùng đó.",
  "deleted_id": 2,
  "deleted_batches": 2
}
```

### Cấu trúc bảng `farms`

| Cột | Kiểu | Ràng buộc |
| --- | --- | --- |
| `id` | INTEGER | Khoá chính, tự tăng |
| `name` | VARCHAR(255) | Bắt buộc |
| `location` | VARCHAR(255) | Bắt buộc |
| `area` | FLOAT | Bắt buộc, **> 0** (đơn vị hecta) |
| `owner` | VARCHAR(255) | Bắt buộc |

> Bảng `farms` **không cần tạo bằng tay**: `init_db()` trong `lifespan` gọi
> `Base.metadata.create_all()` mỗi lần server khởi động, nên bảng mới sẽ tự
> được tạo nếu chưa tồn tại (không làm mất dữ liệu các bảng đã có).

### Cấu trúc bảng `batches` (lô nông sản)

| Cột | Kiểu | Ràng buộc |
| --- | --- | --- |
| `id` | INTEGER | Khoá chính, tự tăng |
| `farm_id` | INTEGER | **Khoá ngoại → `farms.id`**, bắt buộc, có index |
| `product_name` | VARCHAR(255) | Bắt buộc |
| `quantity` | FLOAT | Bắt buộc, **> 0** (đơn vị kg) |
| `harvest_date` | DATE | Bắt buộc, định dạng `yyyy-MM-dd` |

**Quan hệ:** `Farm 1 ---- N Batch`, khai báo 2 chiều trong `app/models.py` bằng
`relationship(back_populates=...)`:

- `farm.batches` → danh sách lô của vùng trồng (có `cascade="all, delete-orphan"`).
- `batch.farm` → vùng trồng xuất xứ của lô.

Khi tạo lô, backend **kiểm tra `farm_id` có tồn tại trước khi ghi** → nếu không
tìm thấy vùng trồng, API trả `404 Not Found` thay vì tạo dữ liệu mồ côi.

### Cấu trúc bảng `users` (Sprint 4)

| Cột | Kiểu | Ràng buộc |
| --- | --- | --- |
| `id` | INTEGER | Khoá chính, tự tăng |
| `username` | VARCHAR(50) | Bắt buộc, **unique + index** |
| `password` | VARCHAR(64) | Bắt buộc, **SHA-256 hex** (không lưu mật khẩu gốc) |
| `role` | VARCHAR(20) | Bắt buộc, `admin` hoặc `farmer` |
| `failed_login_attempts` | INTEGER | Bắt buộc, mặc định `0` - số lần đăng nhập **sai liên tiếp** (Sprint 6) |
| `locked_until` | DATETIME | Cho phép `NULL` - thời điểm **mở khoá** (UTC); `NULL` = không bị khoá (Sprint 6) |

> Database tạo từ Sprint 4 chưa có 2 cột cuối: `init_db()` gọi
> `migrate_user_security_columns()` để `ALTER TABLE` thêm cột còn thiếu ngay khi
> server khởi động - **không mất dữ liệu tài khoản**, không cần xoá `ttcs.db`.

**Tài khoản mặc định** do `seed_default_users()` trong `app/database.py` tạo ở lần
chạy đầu tiên và **không ghi đè** nếu tài khoản đã tồn tại:

| Tài khoản | Mật khẩu | Vai trò (`role`) | Quyền |
| --- | --- | --- | --- |
| `admin` | `123456` | `admin` | Toàn bộ chức năng, xem được `GET /users` |
| `farmer` | `123456` | `farmer` | Quản lý vùng trồng + lô nông sản (`/farms`, `POST /batches`) |

### Cơ chế đăng nhập & phân quyền (Sprint 4 - không dùng JWT)

- **Đăng nhập:** `POST /auth/login` nhận `{username, password}`, băm mật khẩu bằng
  `hashlib.sha256` rồi so sánh bằng `hmac.compare_digest` với hash trong bảng
  `users`; đúng thì trả `{username, role}`, sai thì `401` (**không** phân biệt
  "sai username" hay "sai mật khẩu" để tránh dò tài khoản).
- **Không có JWT/session:** response `/auth/login` chỉ trả `username` + `role`.
  Các API cần quyền nhận thông tin đăng nhập qua header
  **`Authorization: Basic base64(username:password)`** - dependency
  `get_current_user` (dùng `HTTPBasic`) giải mã và tra bảng `users` cho mọi request.
- **Hai mức quyền** (khai báo trong `app/security.py`):
  - `require_farmer` → cho phép **farmer và admin**: `GET /farms`, `POST /farms`, `POST /batches`;
  - `require_admin` → **chỉ admin**: `GET /users`.
- **Mã lỗi:** `401 Unauthorized` = thiếu/sai thông tin đăng nhập (hoặc header Basic
  sai định dạng); `403 Forbidden` = đã đăng nhập nhưng **không đủ vai trò**.
- **Swagger UI:** nhờ `HTTPBasic` khai báo trong security, `/docs` tự hiện nút
  **Authorize** (nhập `admin` / `123456` là gọi được mọi API).
- ⚠️ **Lưu ý bảo mật (đủ cho bài tập):** SHA-256 **không salt**, mật khẩu gửi lại ở
  mỗi request và chưa có hết hạn phiên - Sprint sau nên thay bằng `bcrypt` + JWT.

### Bảo mật đăng nhập — khoá tài khoản khi nhập sai nhiều lần (Sprint 6)

Chính sách (hằng số khai báo ở đầu `app/security.py`, đổi 1 chỗ là đổi cả hệ thống):

| Hằng số | Giá trị | Ý nghĩa |
| --- | --- | --- |
| `MAX_FAILED_LOGIN_ATTEMPTS` | `5` | Số lần nhập sai **liên tiếp** tối đa |
| `LOCKOUT_DURATION` | `timedelta(minutes=5)` | Thời gian tạm khoá tài khoản |

Luồng xử lý của `POST /auth/login` (`authenticate_user_with_lockout()`):

1. Sai tên đăng nhập → **`401`** như trước (`failed_login_attempts` **không** tăng vì
   không có tài khoản nào để ghi nhận, và cố tình không phân biệt "sai username"
   với "sai mật khẩu").
2. Sai mật khẩu lần 1–4 → **`401`** + `failed_login_attempts` tăng 1 sau mỗi lần.
3. Sai mật khẩu **lần thứ 5** → khoá tài khoản: `locked_until = now + 5 phút`, trả
   **`403 Forbidden`** kèm message nêu rõ thời gian chờ.
4. Đang trong thời gian khoá → **`403`** với mọi lần thử, **kể cả đúng mật khẩu**
   (API cần quyền gọi bằng HTTP Basic của tài khoản bị khoá cũng trả `403`).
5. Đăng nhập thành công → `failed_login_attempts = 0` và `locked_until = NULL`.
6. Hết thời gian khoá → tài khoản **tự mở khoá** ở lần đăng nhập kế tiếp, bộ đếm
   bắt đầu lại từ `0` (không cần thao tác admin).

Response 403 có dạng (kèm header `Retry-After` = số giây còn phải chờ):

```json
{
  "detail": "Tài khoản 'admin' đã bị tạm khoá do nhập sai mật khẩu 5 lần liên tiếp. Vui lòng thử lại sau 4 phút 32 giây."
}
```

Kiểm tra nhanh (sai 5 lần là bị khoá; `-w` in ra mã HTTP):

```powershell
# Chạy 5 lần liên tiếp: 4 lần đầu 401, lần thứ 5 trả 403
1..5 | ForEach-Object { curl.exe --% -s -o NUL -w "%{http_code}`n" -X POST http://127.0.0.1:8000/auth/login -H "Content-Type: application/json" -d "{\"username\":\"admin\",\"password\":\"sai-mat-khau\"}" }

# Đúng mật khẩu trong lúc đang bị khoá -> vẫn 403
curl.exe --% -s -X POST http://127.0.0.1:8000/auth/login -H "Content-Type: application/json" -d "{\"username\":\"admin\",\"password\":\"123456\"}"
```

> Muốn thử lại ngay mà không chờ 5 phút: mở `/docs`, gọi `GET /users` bằng tài
> khoản admin khác, hoặc đặt lại 2 cột bằng `sqlite3`:
> `UPDATE users SET failed_login_attempts = 0, locked_until = NULL WHERE username = 'admin';`

### Lịch sử thao tác — audit log (Sprint 7)

Mục tiêu: trả lời câu hỏi **"ai đã làm gì trong hệ thống"**. Mỗi thao tác **ghi**
dữ liệu thành công đều sinh **đúng 1 dòng log**:

| Thao tác | Log sinh ra (`action` / `entity`) |
| --- | --- |
| `POST /farms` | `create` / `farm` |
| `PUT /farms/{farm_id}` | `update` / `farm` |
| `DELETE /farms/{farm_id}` | `delete` / `farm` (các lô bị xoá kèm theo cascade **không** sinh log riêng) |
| `POST /batches` | `create` / `batch` |
| `PUT /batches/{batch_id}` | `update` / `batch` |
| `DELETE /batches/{batch_id}` | `delete` / `batch` |

- **Không** ghi log cho: các API **đọc** (`GET ...`), đăng nhập, và các request bị
  chặn (**401/403/404/422**) — vì log được `db.add()` vào **cùng transaction** với
  thao tác (`record_action()` trong `app/audit.py`): rollback thì dòng log cũng bị
  huỷ theo, nên lịch sử chỉ chứa thao tác **thực sự đã xảy ra**.
- **Không có API** để client tự thêm/sửa/xoá log: bảng `audit_logs` chỉ được ghi
  tự động bởi backend (gọi `POST/PUT/DELETE /audit-logs` → `405`).
- **Xem log:** `GET /audit-logs` — **chỉ admin** (farmer → `403`, chưa đăng nhập →
  `401`). Mặc định trả **100 dòng mới nhất trước**, sắp theo `id` giảm dần (để các
  log phát sinh trong cùng một thời điểm vẫn đúng thứ tự).

```json
[
  {
    "id": 5,
    "user_id": 1,
    "username": "admin",
    "action": "delete",
    "entity": "farm",
    "entity_id": 2,
    "created_at": "2026-01-20T03:15:42.371143"
  }
]
```

Tham số lọc (tuỳ chọn):

| Tham số | Ví dụ | Ý nghĩa |
| --- | --- | --- |
| `entity` | `?entity=farm` | Chỉ lấy log của Farm (hoặc `batch`); giá trị khác → `422` |
| `user_id` | `?user_id=2` | Chỉ lấy thao tác do một tài khoản thực hiện |
| `limit` | `?limit=20` | Số dòng tối đa (mặc định `100`, tối đa `500`) |

### Cấu trúc bảng `audit_logs` (Sprint 7)

| Cột | Kiểu | Ràng buộc |
| --- | --- | --- |
| `id` | INTEGER | Khoá chính, tự tăng |
| `user_id` | INTEGER | Bắt buộc, **khoá ngoại → `users.id`**, có index — *ai* đã làm |
| `action` | VARCHAR(20) | Bắt buộc — `create` / `update` / `delete` |
| `entity` | VARCHAR(50) | Bắt buộc — `farm` / `batch` |
| `entity_id` | INTEGER | Bắt buộc — ID bản ghi bị tác động |
| `created_at` | DATETIME | Bắt buộc, tự sinh khi INSERT (UTC, naive) — *lúc nào* |

> `audit_logs` là bảng **mới** nên `init_db()` (chạy mỗi lần server khởi động) tự
> tạo thêm cho cả database cũ — **không** phải xoá `ttcs.db`, không mất dữ liệu.
>
> Log **cố ý không** có khoá ngoại tới `farms`/`batches`: khi vùng trồng/lô bị xoá
> thì lịch sử vẫn còn (`entity_id` chỉ là con số tham chiếu tới bản ghi đã xoá).

---

## 4. Hướng dẫn test API bằng Swagger

### 4.1. Test trực tiếp trên Swagger UI

1. Chạy server: `uvicorn app.main:app --reload`
2. Mở <http://127.0.0.1:8000/docs>
3. **Đăng nhập (Sprint 4):** bấm nút **Authorize** (biểu tượng ổ khoá ở góc phải
   trên) → nhập Username `admin`, Password `123456` → **Authorize** → **Close**.
   Từ đó mọi request gửi từ Swagger đều kèm header `Authorization: Basic ...`.
   *Chưa đăng nhập* thì `GET /farms`, `POST /farms`, `POST /batches` trả **`401`**.
4. **Tạo vùng trồng:** mở `POST /farms` → bấm **Try it out** → dán JSON body bên
   dưới vào ô *Request body* → bấm **Execute**
   → mong đợi **`201 Created`**, response body có thêm `id` do database sinh ra.
5. **Lấy danh sách:** mở `GET /farms` → **Try it out** → **Execute**
   → mong đợi **`200 OK`** và một mảng JSON (mảng rỗng `[]` nếu chưa có dữ liệu).
6. **Kiểm tra validate:** gửi lại `POST /farms` với `"area": -1` hoặc bỏ trống
   `name` → mong đợi **`422 Unprocessable Entity`** kèm mô tả lỗi.
7. **Tạo lô nông sản:** mở `POST /batches` → **Try it out** → dán JSON body thứ hai
   bên dưới (nhớ `farm_id` là id vùng trồng vừa tạo ở bước 4) → **Execute**
   → mong đợi **`201 Created`**.
8. **Danh sách lô:** mở `GET /batches` → **Try it out** → **Execute**
   → mong đợi **`200 OK`** và mảng các lô nông sản.
9. **Chi tiết một lô:** mở `GET /batches/{batch_id}` → **Try it out** → nhập `1`
   → **Execute** → mong đợi **`200 OK`**; thử nhập `999` → **`404 Not Found`**.
10. **Kiểm tra chặn dữ liệu sai của Batch:** gửi `POST /batches` với `"farm_id": 999`
    → mong đợi **`404`** kèm `"Không tìm thấy vùng trồng có id=999."`;
    gửi `"quantity": -1` hoặc để trống `product_name` → mong đợi **`422`**.
11. **Kiểm tra `/health` vẫn hoạt động:** mở `GET /health` → **Execute**
    → mong đợi `200` + `{"status": "running"}`.

**Kiểm tra phân quyền (Sprint 4):**

12. Mở `POST /auth/login` → **Try it out** → body
    `{"username": "admin", "password": "123456"}` → **Execute**
    → mong đợi **`200`** + `{"username": "admin", "role": "admin"}`;
    thử lại với `"password": "sai"` → mong đợi **`401`**.
13. `GET /users` **khi đang Authorize bằng `admin`** → **`200`** (danh sách 2 tài
    khoản, **không** có trường `password`). Bấm **Authorize** →
    **Logout** rồi đăng nhập lại bằng `farmer` / `123456` → gọi `GET /users`
    → mong đợi **`403 Forbidden`** (`"Chỉ tài khoản admin được phép..."`),
    còn `GET /farms` với `farmer` → **`200`** (farmer vẫn quản lý được nông sản).

**Kiểm tra CRUD mới (Sprint 5)** — bấm **Authorize** lại bằng `admin` / `123456`:

14. **Sửa vùng trồng:** `PUT /farms/{farm_id}` → **Try it out** → nhập `farm_id` = `1`
    → dán JSON body vùng trồng (đổi `name`/`area` tuỳ ý) → **Execute**
    → mong đợi **`200 OK`** với dữ liệu mới. Thử `farm_id` = `999` → **`404`**;
    xoá bớt 1 trường trong body → **`422`**.
15. **Sửa lô nông sản:** `PUT /batches/{batch_id}` → **Try it out** → `batch_id` = `1`
    → đổi `product_name`/`quantity` → **`200 OK`**. Đổi `farm_id` sang id không
    tồn tại → **`404`** (`"Không tìm thấy vùng trồng..."`).
16. **Phân quyền xoá:** đang Authorize bằng `admin` → **Logout** → Authorize bằng
    `farmer` / `123456` → `DELETE /batches/{batch_id}` → mong đợi **`403 Forbidden`**.
17. **Xoá lô nông sản (admin):** Authorize lại bằng `admin` → **Try it out** →
    `batch_id` của một lô vừa tạo → **Execute** → mong đợi **`200 OK`** + body
    `{"message": "...", "deleted_id": <id>, "deleted_batches": null}`;
    gọi lại lần 2 với cùng id → **`404`**.
18. **Xoá vùng trồng (admin, xoá dây chuyền):** tạo 1 vùng trồng mới → tạo 1-2 lô
    cho vùng đó → `DELETE /farms/{farm_id}` → **`200 OK`** với `deleted_batches`
    đúng bằng số lô vừa tạo → kiểm tra `GET /batches` → các lô đó **đã biến mất**.

**Kiểm tra lịch sử thao tác (Sprint 7)** — vẫn đang Authorize bằng `admin` / `123456`:

19. **Xem lịch sử:** mở `GET /audit-logs` → **Try it out** → **Execute** → mong đợi
    **`200 OK`** + mảng log **mới nhất trước**: sau các bước trên sẽ thấy những dòng
    `create`/`update`/`delete` cho `farm`/`batch` vừa thao tác, kèm `username` của
    người thực hiện và `created_at` (UTC).
20. **Lọc log:** nhập `entity` = `farm` → **`200`** (chỉ log của vùng trồng);
    nhập `entity` = `user` → **`422`**; nhập `limit` = `20` → **`200`** (tối đa 20
    dòng); nhập `limit` = `0` → **`422`**.
21. **Phân quyền xem log:** **Logout** → Authorize bằng `farmer` / `123456` →
    `GET /audit-logs` → mong đợi **`403 Forbidden`** (chỉ admin xem được lịch sử);
    đổi sang `GET /farms` bằng `farmer` → vẫn **`200`** (các API cũ không đổi).

JSON body mẫu để dán vào Swagger:

```json
{
  "name": "Vùng trồng xoài Cao Lãnh",
  "location": "Xã Mỹ Xương, Huyện Cao Lãnh, Tỉnh Đồng Tháp",
  "area": 2.5,
  "owner": "Hợp tác xã Xoài Mỹ Xương"
}
```

```json
{
  "farm_id": 1,
  "product_name": "Xoài cát Chu",
  "quantity": 120.5,
  "harvest_date": "2026-01-15"
}
```

### 4.2. Test bằng PowerShell khi server đang chạy

**Cách 1 — `Invoke-RestMethod` (khuyến nghị, không gặp lỗi escaping):**

```powershell
# 1. Kiểm tra hệ thống (công khai, không cần đăng nhập)
Invoke-RestMethod http://127.0.0.1:8000/health

# 2. Đăng nhập -> nhận username + role (không có token vì KHÔNG dùng JWT)
$login = '{"username":"admin","password":"123456"}'
Invoke-RestMethod -Uri http://127.0.0.1:8000/auth/login -Method Post -ContentType 'application/json; charset=utf-8' -Body $login

# 3. Tạo header xác thực HTTP Basic để tái sử dụng cho các request sau
$token = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('admin:123456'))
$auth = @{ Authorization = "Basic $token" }

# 4. Tạo vùng trồng mới (CẦN QUYỀN: thiếu -Headers $auth sẽ nhận 401)
$body = '{"name":"Vung trong xoai Cao Lanh","location":"Xa My Xuong, Cao Lanh, Dong Thap","area":2.5,"owner":"HTX Xoai My Xuong"}'
Invoke-RestMethod -Uri http://127.0.0.1:8000/farms -Method Post -Headers $auth -ContentType 'application/json; charset=utf-8' -Body $body

# 5. Lấy danh sách vùng trồng (CẦN QUYỀN)
Invoke-RestMethod http://127.0.0.1:8000/farms -Headers $auth | ConvertTo-Json

# 6. Tạo lô nông sản cho vùng trồng id=1 (CẦN QUYỀN)
$batch = '{"farm_id":1,"product_name":"Xoai cat Chu","quantity":120.5,"harvest_date":"2026-01-15"}'
Invoke-RestMethod -Uri http://127.0.0.1:8000/batches -Method Post -Headers $auth -ContentType 'application/json; charset=utf-8' -Body $batch

# 7. Danh sách lô + chi tiết lô id=1 (công khai, không cần header)
Invoke-RestMethod http://127.0.0.1:8000/batches | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/batches/1 | ConvertTo-Json

# 8. Phân quyền: /users chỉ admin xem được
Invoke-RestMethod http://127.0.0.1:8000/users -Headers $auth | ConvertTo-Json

# 9. farmer gọi /users -> 403 Forbidden (đã đăng nhập nhưng sai vai trò)
$farmerToken = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('farmer:123456'))
Invoke-RestMethod http://127.0.0.1:8000/users -Headers @{ Authorization = "Basic $farmerToken" }

# 10. Sửa vùng trồng id=1 (PUT) - farmer và admin đều được phép
$farmUpdate = '{"name":"Vung trong xoai Cao Lanh (da sua)","location":"Cao Lanh, Dong Thap","area":3.2,"owner":"HTX Xoai My Xuong"}'
Invoke-RestMethod -Uri http://127.0.0.1:8000/farms/1 -Method Put -Headers $auth -ContentType 'application/json; charset=utf-8' -Body $farmUpdate

# 11. Sửa lô nông sản id=1 (PUT) - đổi tên sản phẩm + số lượng
$batchUpdate = '{"farm_id":1,"product_name":"Xoai cat Chu loai 1","quantity":150,"harvest_date":"2026-01-16"}'
Invoke-RestMethod -Uri http://127.0.0.1:8000/batches/1 -Method Put -Headers $auth -ContentType 'application/json; charset=utf-8' -Body $batchUpdate

# 12. farmer xoá dữ liệu -> 403 Forbidden (chỉ admin được xoá)
try {
    Invoke-RestMethod -Uri http://127.0.0.1:8000/batches/2 -Method Delete -Headers @{ Authorization = "Basic $farmerToken" }
} catch {
    "farmer xoa -> HTTP $($_.Exception.Response.StatusCode.value__)"
}

# 13. admin xoá lô nông sản -> 200 OK + {message, deleted_id, deleted_batches}
Invoke-RestMethod -Uri http://127.0.0.1:8000/batches/2 -Method Delete -Headers $auth

# 14. admin xoá vùng trồng -> xoá kèm mọi lô của vùng đó (deleted_batches > 0)
Invoke-RestMethod -Uri http://127.0.0.1:8000/farms/2 -Method Delete -Headers $auth

# 15. Xem lịch sử thao tác (Sprint 7, chỉ admin) - mới nhất trước
Invoke-RestMethod http://127.0.0.1:8000/audit-logs -Headers $auth | ConvertTo-Json -Depth 5

# 16. Lọc log: theo loại dữ liệu / người thực hiện / số dòng
Invoke-RestMethod 'http://127.0.0.1:8000/audit-logs?entity=farm&limit=5' -Headers $auth | ConvertTo-Json -Depth 5
Invoke-RestMethod 'http://127.0.0.1:8000/audit-logs?user_id=1' -Headers $auth | ConvertTo-Json -Depth 5

# 17. farmer gọi /audit-logs -> 403 Forbidden (chỉ admin xem được lịch sử)
try {
    Invoke-RestMethod http://127.0.0.1:8000/audit-logs -Headers @{ Authorization = "Basic $farmerToken" }
} catch {
    "farmer xem audit log -> HTTP $($_.Exception.Response.StatusCode.value__)"
}
```

**Cách 2 — `curl.exe` (bắt buộc dùng `--%`, xem lưu ý bên dưới):**

```powershell
# Công khai
curl.exe -s http://127.0.0.1:8000/health
curl.exe -s http://127.0.0.1:8000/batches
curl.exe -s http://127.0.0.1:8000/batches/1

# Đăng nhập (trả về username + role)
curl.exe --% -s -X POST http://127.0.0.1:8000/auth/login -H "Content-Type: application/json" -d "{\"username\":\"admin\",\"password\":\"123456\"}"

# API cần quyền: dùng -u (curl tự mã hoá Basic base64)
curl.exe -s -u admin:123456 http://127.0.0.1:8000/farms

curl.exe --% -s -X POST http://127.0.0.1:8000/farms -u admin:123456 -H "Content-Type: application/json" -d "{\"name\":\"Vung trong xoai Cao Lanh\",\"location\":\"Cao Lanh, Dong Thap\",\"area\":2.5,\"owner\":\"HTX Xoai\"}"

curl.exe --% -s -X POST http://127.0.0.1:8000/batches -u farmer:123456 -H "Content-Type: application/json" -d "{\"farm_id\":1,\"product_name\":\"Xoai cat Chu\",\"quantity\":120.5,\"harvest_date\":\"2026-01-15\"}"

# Quên -u -> 401 ; dùng tài khoản farmer cho /users -> 403
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8000/farms
curl.exe -s -u farmer:123456 -o NUL -w "%{http_code}`n" http://127.0.0.1:8000/users

# Sửa dữ liệu (PUT): farmer cũng làm được
curl.exe --% -s -X PUT http://127.0.0.1:8000/farms/1 -u farmer:123456 -H "Content-Type: application/json" -d "{\"name\":\"Vung trong xoai (da sua)\",\"location\":\"Cao Lanh, Dong Thap\",\"area\":3.2,\"owner\":\"HTX Xoai\"}"

curl.exe --% -s -X PUT http://127.0.0.1:8000/batches/1 -u farmer:123456 -H "Content-Type: application/json" -d "{\"farm_id\":1,\"product_name\":\"Xoai cat Chu\",\"quantity\":150,\"harvest_date\":\"2026-01-16\"}"

# Xoá dữ liệu (DELETE): farmer -> 403, admin -> 200
curl.exe -s -u farmer:123456 -X DELETE -o NUL -w "%{http_code}`n" http://127.0.0.1:8000/batches/2
curl.exe -s -u admin:123456 -X DELETE http://127.0.0.1:8000/batches/2
curl.exe -s -u admin:123456 -X DELETE http://127.0.0.1:8000/farms/2

# Lịch sử thao tác (Sprint 7): chỉ admin xem được -> farmer trả 403
curl.exe -s -u admin:123456 http://127.0.0.1:8000/audit-logs
curl.exe -s -u admin:123456 "http://127.0.0.1:8000/audit-logs?entity=batch&limit=5"
curl.exe -s -u farmer:123456 -o NUL -w "%{http_code}`n" http://127.0.0.1:8000/audit-logs
```

> ⚠️ **Lưu ý quan trọng (đã kiểm chứng thực tế):** trên **PowerShell 5.1**, cách viết
> `curl.exe -d '{"name":"..."}'` (nháy đơn) hoặc `-d "{\"name\":\"...\"}"` (không có `--%`)
> sẽ bị PowerShell làm hỏng dấu nháy → server trả **`422 JSON decode error`**.
> Hãy dùng `--%` (stop-parsing) hoặc `Invoke-RestMethod`.
>
> Với tên tiếng Việt **có dấu**, nên test bằng **Swagger UI** (xử lý UTF-8 chuẩn) thay vì
> dán trực tiếp trong terminal, để tránh lỗi hiển thị/encoding của PowerShell/CMD.
>
> Nếu chạy script Python in ra chữ tiếng Việt mà bị `UnicodeEncodeError: 'charmap'
> codec...` (thường gặp khi **pipe/redirect output** trên Windows), hãy đặt biến môi
> trường trước khi chạy: `$env:PYTHONIOENCODING='utf-8'`.

### 4.3. Xem dữ liệu đã lưu trong SQLite

Database là file `backend/ttcs.db` (tự sinh). Xem nhanh bằng Python:

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3; print(sqlite3.connect('ttcs.db').execute('SELECT * FROM farms').fetchall())"
```

Hoặc mở file bằng DB Browser for SQLite. Muốn **reset dữ liệu**: tắt server, xoá
`ttcs.db`, chạy lại server (bảng sẽ được tạo mới, rỗng và `seed_default_users()`
**tạo lại 2 tài khoản demo** `admin`/`farmer` với mật khẩu `123456`).

Xem nhanh bảng tài khoản (cột `password` là hash SHA-256, không phải mật khẩu thô):

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3; print(sqlite3.connect('ttcs.db').execute('SELECT id, username, role FROM users').fetchall())"
```

Xem lịch sử thao tác (Sprint 7) - join sang bảng `users` để biết **ai** đã làm gì:

```powershell
.\.venv\Scripts\python.exe -c "import sqlite3; print(sqlite3.connect('ttcs.db').execute('SELECT a.id, u.username, a.action, a.entity, a.entity_id, a.created_at FROM audit_logs a LEFT JOIN users u ON u.id = a.user_id ORDER BY a.id').fetchall())"
```

---

## 5. Giải thích từng file

| File | Vai trò |
| --- | --- |
| `app/main.py` | Entrypoint: tạo `FastAPI(...)`, cấu hình CORS, dùng `lifespan` để gọi `init_db()` khi server start, và `include_router` để gom các endpoint. Khi mở rộng, chỉ cần thêm 1 dòng `app.include_router(...)`. |
| `app/database.py` | Tầng hạ tầng dữ liệu: tạo `engine` kết nối SQLite (`check_same_thread=False` vì FastAPI có thể xử lý request trên thread khác — tham số này chỉ dành riêng cho SQLite), `SessionLocal` để mở session mỗi request, `Base` (DeclarativeBase) cho mọi model, `get_db()` (dependency đóng session tự động), `init_db()` (tạo bảng từ metadata **rồi gọi `migrate_user_security_columns()` để thêm 2 cột bảo mật còn thiếu cho database cũ** - `create_all()` không tự thêm cột vào bảng đã tồn tại) và `seed_default_users()` (tạo 2 tài khoản demo `admin`/`farmer` nếu chưa có). |
| `app/models.py` | Nơi khai báo bảng ORM (SQLAlchemy 2.0 style: `Mapped` + `mapped_column`). Hiện có: `Farm` → bảng `farms` (`id`, `name`, `location`, `area`, `owner`) và `Batch` → bảng `batches` (`id`, `farm_id` FK → `farms.id`, `product_name`, `quantity`, `harvest_date`) với quan hệ 2 chiều `Farm 1-N Batch` (`farm.batches` ↔ `batch.farm`), cùng `User` → bảng `users` (`id`, `username` unique, `password` = hash SHA-256, `role`) kèm hằng số `ROLE_ADMIN`/`ROLE_FARMER`. Sprint 6 bổ sung 2 cột phục vụ khoá tài khoản: `failed_login_attempts` (mặc định `0`) và `locked_until` (nullable). Sprint 7 bổ sung `AuditLog` → bảng `audit_logs` (`id`, `user_id` khoá ngoại → `users.id`, `action`, `entity`, `entity_id`, `created_at` tự sinh UTC) kèm hằng số `ACTION_*`/`ENTITY_*` dùng chung cho router và test. Thêm bảng mới ở đây thì `init_db()` sẽ tự tạo. |
| `app/schemas.py` | Pydantic models mô tả dữ liệu request/response: `HealthResponse`, `FarmCreate`/`FarmResponse`, `BatchCreate`/`BatchResponse` (`farm_id > 0`, chuỗi không rỗng, `quantity > 0`, `harvest_date` kiểu `date`). `*Response` dùng `from_attributes=True` để trả thẳng ORM object kèm `id`; Sprint 4 bổ sung `LoginRequest` (`username`, `password`), `LoginResponse` (`username`, `role`) và `UserResponse` (**không** có trường `password`); Sprint 5 bổ sung `FarmUpdate`/`BatchUpdate` (kế thừa `*Create` để dùng lại validate, phục vụ `PUT`) và `DeleteResponse` (`message`, `deleted_id`, `deleted_batches`). Sprint 6 bổ sung `AccountLockedResponse` (`message` mô tả thời gian tạm khoá, dùng cho response **403**). Sprint 7 bổ sung `AuditLogResponse` (`id`, `user_id`, `username`, `action`, `entity`, `entity_id`, `created_at`) cho `GET /audit-logs` - `username` là trường **suy ra** từ `user_id` cho tiện hiển thị, không phải cột trong database. Tách khỏi `models.py` để không lộ cấu trúc bảng ra API. |
| `app/security.py` | **Sprint 4** — xác thực & phân quyền *không JWT*: `hash_password()` / `verify_password()` (SHA-256 + `hmac.compare_digest`, chỉ dùng thư viện chuẩn), `authenticate_user()` (tra bảng `users`), `basic_scheme = HTTPBasic(auto_error=False)` và 3 dependency: `get_current_user()` (**401** nếu thiếu/sai thông tin đăng nhập), `require_admin()` (**403** nếu không phải admin), `require_farmer()` (cho cả farmer và admin). Router chỉ cần thêm `user = Depends(require_admin)` là đã có phân quyền. **Sprint 6 — chống dò mật khẩu:** thêm `utcnow()`, `AccountLockedError`, hằng số `MAX_FAILED_LOGIN_ATTEMPTS = 5` / `LOCKOUT_DURATION = 5 phút` cùng các hàm `get_user_by_username()`, `is_account_locked()`, `lockout_seconds_remaining()`, `build_lockout_message()`, `register_failed_login()`, `reset_login_attempts()` và `authenticate_user_with_lockout()` (đếm số lần sai liên tiếp, khoá 5 phút khi chạm ngưỡng, tự mở khoá khi hết hạn); `get_current_user()` cũng từ chối tài khoản đang bị khoá bằng **403** nên mọi API cần quyền đều được bảo vệ. Hàm `authenticate_user()` cũ được giữ nguyên (không đếm/không chặn) để không phá luồng cũ. |
| `app/audit.py` | **Sprint 7** — lớp dịch vụ cho lịch sử thao tác: `record_action(db, user, action, entity, entity_id)` chỉ `db.add()` một dòng `AuditLog` vào session đang mở (**không** tự commit) để log và thao tác nghiệp vụ được commit/rollback **cùng nhau**; `fetch_audit_logs(db, entity, user_id, limit)` đọc log **mới nhất trước** kèm `joinedload(AuditLog.user)` để lấy `username` mà không phát sinh truy vấn phụ; hằng số `DEFAULT_AUDIT_LOG_LIMIT = 100` / `MAX_AUDIT_LOG_LIMIT = 500`. |
| `app/routers/auth.py` | **Sprint 4** — router `Auth`: `POST /auth/login` kiểm tra `username`/`password` với bảng `users`, trả `{username, role}` (**200**); sai thì **401**; tài khoản đang bị tạm khoá thì **403** kèm header `Retry-After` (số giây còn phải chờ) - xem mục *Bảo mật đăng nhập* ở phần 3. **Không sinh token** — client dùng lại thông tin đăng nhập qua header HTTP Basic cho các request sau (mục đích chính của endpoint này là để frontend biết vai trò). |
| `app/routers/users.py` | **Sprint 4** — router `Users`: `GET /users` trả danh sách tài khoản sắp theo `id` và **không kèm mật khẩu**. Dùng `Depends(require_admin)` nên: admin → **200**, farmer → **403**, chưa đăng nhập → **401**. |
| `app/routers/health.py` | Router chứa endpoint `GET /health`, khai báo `response_model=HealthResponse`, trả về `{"status": "running"}`. |
| `app/routers/farms.py` | Router module Farm - **CRUD đầy đủ**: `POST /farms` (thêm bản ghi, `commit` + `refresh`, rollback nếu lỗi DB), `GET /farms` (truy vấn bằng `select()` của SQLAlchemy 2.0), `PUT /farms/{farm_id}` (Sprint 5 - ghi đè từng trường bằng `setattr`, **404** nếu không thấy) và `DELETE /farms/{farm_id}` (Sprint 5 - **chỉ admin**, xoá kèm các lô nhờ cascade, trả `DeleteResponse`). Sprint 7: cả 3 endpoint ghi (`POST`/`PUT`/`DELETE`) gọi `record_action(db, current_user, ...)` trước `commit` để lưu 1 dòng lịch sử `entity="farm"` (khi tạo mới có `db.flush()` để lấy `id`); status code và body trả về **không đổi** so với trước. |
| `app/routers/batches.py` | Router module Batch - **CRUD đầy đủ**: `POST /batches` (**404** nếu `farm_id` không tồn tại — kiểm tra bằng `db.get(Farm, ...)` trước khi ghi), `GET /batches` (danh sách, sắp theo `id`), `GET /batches/{batch_id}` (**404** nếu không thấy), `PUT /batches/{batch_id}` (Sprint 5 - kiểm tra lại `farm_id` mới trước khi ghi) và `DELETE /batches/{batch_id}` (Sprint 5 - **chỉ admin**). Sprint 7: `POST`/`PUT`/`DELETE` ghi thêm 1 dòng lịch sử `entity="batch"` (`record_action()` trong cùng transaction, tạo mới dùng `db.flush()` để có `id`); các endpoint `GET` vẫn **công khai** và **không** ghi log. |
| `app/routers/audit.py` | **Sprint 7** — router `Audit logs`: `GET /audit-logs` (chỉ admin, dùng `Depends(require_admin)`) trả lịch sử thao tác mới nhất trước, hỗ trợ lọc `entity` (`Literal["farm", "batch"]` → giá trị lạ nhận **422**), `user_id`, `limit` (1..500); **chỉ có 1 endpoint `GET`** — không có POST/PUT/DELETE nên log không sửa/xoá được qua API. |
| `app/routers/__init__.py` | Gom và export các router con để `main.py` import ngắn gọn (`from app.routers import audit, auth, batches, farms, health, users`). |
| `app/__init__.py` | Đánh dấu `app` là package Python; khai báo `__version__ = "0.2.0"` dùng cho metadata Swagger. |
| `tests/` | **Sprint 6/7** — test tự động bằng `pytest` + `fastapi.testclient`: `conftest.py` tạo engine SQLite **in-memory** và fixture `client` (override dependency `get_db`, không bật `lifespan` để không đụng `ttcs.db`), `test_login_lockout.py` phủ luồng khoá tài khoản (**401** khi sai 1–4 lần → **403** ở lần thứ 5 → **403** khi đúng mật khẩu trong lúc khoá → **200** khi đã hết 5 phút), `test_database_migration.py` phủ `migrate_user_security_columns()` (thêm 2 cột, giữ nguyên dữ liệu, chạy lại nhiều lần vẫn an toàn) và `init_db()` trên database cũ (tự tạo bảng `audit_logs`), `test_audit_logs.py` (Sprint 7) phủ lịch sử thao tác: bảng đủ 6 cột, **6 thao tác** (tạo/sửa/xoá Farm + Batch) sinh đúng 1 dòng log, ghi đúng người thực hiện (admin/farmer), thao tác thất bại (401/403/404/422) & API đọc **không** sinh log, `GET /audit-logs` chỉ admin (farmer **403**, ẩn danh **401**) kèm bộ lọc `entity`/`user_id`/`limit` và `405` khi thử POST/PUT/DELETE. |
| `requirements.txt` | Ghim phiên bản thư viện: `fastapi`, `uvicorn[standard]`, `SQLAlchemy`, `pydantic` — đảm bảo cả nhóm cài ra môi trường giống nhau. **Sprint 4 không thêm thư viện nào**: băm mật khẩu dùng `hashlib`/`hmac` có sẵn, xác thực dùng `fastapi.security.HTTPBasic` của FastAPI. Sprint 6 thêm `pytest` + `httpx` vào nhóm dev để chạy test tự động. |
| `.gitignore` | Bỏ qua `.venv/`, `__pycache__/`, `*.db`... để không commit rác và dữ liệu local. |

---

## 6. Hướng mở rộng ở Sprint sau

1. **Thêm bảng:** khai báo model mới trong `app/models.py` → bảng tự được tạo
   ở lần chạy tiếp theo.
2. **Thêm endpoint:** tạo file mới trong `app/routers/` (ví dụ `cold_chain.py`),
   thêm schema tương ứng vào `app/schemas.py`, rồi đăng ký router trong
   `app/main.py`.
3. **Bổ sung CRUD:** `GET /farms/{farm_id}` (trả 404 nếu không thấy); cho
   `GET /batches` hỗ trợ lọc theo vùng trồng (`?farm_id=1`) và phân trang
   (`skip`, `limit`). *(`PUT`/`DELETE` cho cả Farm và Batch đã hoàn thành ở Sprint 5.)*
4. **Trả kèm thông tin vùng trồng trong chi tiết lô:** thêm trường
   `farm: FarmResponse` vào schema chi tiết lô (dùng `joinedload` để tránh N+1).
5. **Index & ràng buộc:** thêm `unique=True, index=True` cho cột cần tra cứu
   `name` (vùng trồng) để tăng tốc truy vấn.
6. **Dùng database trong endpoint:**
   ```python
   from fastapi import Depends
   from sqlalchemy.orm import Session
   from app.database import get_db

   @router.get("/cold-chain")
   def list_logs(db: Session = Depends(get_db)):
       ...
   ```
7. **Migration:** khi schema thay đổi nhiều, bổ sung Alembic thay vì
   `create_all()`.
8. **Cấu hình theo môi trường:** chuyển `DATABASE_URL`, CORS origin... sang biến
   môi trường (`.env` + `pydantic-settings`).
9. **Kiểm thử:** mở rộng `tests/` (đã có từ Sprint 6 với `pytest` + `fastapi.testclient`
   chạy trên SQLite in-memory) bằng test cho CRUD `/farms`, `/batches`, phân quyền
   admin/farmer và đo độ phủ (`pytest --cov`). *(Audit log đã có test trong
   `tests/test_audit_logs.py` từ Sprint 7.)*
10. **Bảo mật nâng cao (bảo vệ mật khẩu):** thay SHA-256 không salt bằng
    `bcrypt`/`argon2` (qua `passlib`), thêm chức năng **đổi mật khẩu**, gia hạn
    thời gian khoá theo cấp số nhân khi tài khoản bị khoá lặp lại, ghi log các lần
    đăng nhập thất bại và bắt buộc HTTPS khi triển khai (HTTP Basic gửi mật khẩu ở
    mỗi request). *(Khoá tài khoản khi đăng nhập sai nhiều lần đã hoàn thành ở Sprint 6.)*
11. **Thay HTTP Basic bằng JWT/session:** phát hành access token có thời hạn
    (+ refresh token hoặc session cookie) để client không phải lưu và gửi lại mật
    khẩu; thêm `POST /auth/logout`, `GET /auth/me`.
12. **Phân quyền chi tiết hơn:** thêm vai trò `inspector`/`retailer`, thêm cột
    `owner_id` (FK → `users.id`) cho `farms` để **farmer chỉ sửa được vùng trồng
    của mình** (row-level permission). *(Việc ghi log ai đã tạo/sửa/xoá dữ liệu —
    audit trail — đã hoàn thành ở **Sprint 7** với bảng `audit_logs`.)*
13. **Xoá an toàn hơn:** chuyển sang **soft delete** (cột `deleted_at`) + endpoint
    khôi phục thay cho xoá cứng, yêu cầu xác nhận (`?force=true`) khi xoá vùng
    trồng còn lô nông sản. *(Log ai đã xoá bản ghi nào đã có ở Sprint 7 - xem
    `GET /audit-logs`.)*

---

## 7. Lịch sử thay đổi

| Giai đoạn | Nội dung |
| --- | --- |
| Sprint 1 | Khung dự án: FastAPI + SQLite + SQLAlchemy, endpoint `GET /health`. |
| Sprint 2 | Module **Farm** (quản lý vùng trồng): model `Farm` → bảng `farms` (tự tạo), schemas `FarmCreate`/`FarmResponse`, router `app/routers/farms.py` với `POST /farms` (**201**) và `GET /farms` (**200**). `GET /health` giữ nguyên. |
| Sprint 3 | Module **Batch** (quản lý lô nông sản): model `Batch` → bảng `batches` (FK `farm_id` → `farms.id`, quan hệ `Farm 1 ---- N Batch`), schemas `BatchCreate`/`BatchResponse`, router `app/routers/batches.py` với `POST /batches` (**201**, trả **404** nếu `farm_id` không tồn tại), `GET /batches` (**200**) và `GET /batches/{batch_id}` (**200**/**404**). `GET /health`, `POST /farms`, `GET /farms` giữ nguyên. |
| Sprint 4 | **Đăng nhập + phân quyền cơ bản (không JWT):** model `User` → bảng `users` (`username` unique, mật khẩu băm SHA-256, `role`), `seed_default_users()` tạo sẵn `admin`/`farmer` (mật khẩu `123456`); module `app/security.py` với `hash_password`/`verify_password`/`authenticate_user` và dependency `get_current_user` (**401**), `require_admin` (**403**), `require_farmer`; router `POST /auth/login` (**200**/**401**) và `GET /users` (**200**, chỉ admin); áp `require_farmer` cho `GET /farms`, `POST /farms`, `POST /batches`. Cơ chế xác thực là **HTTP Basic** (Swagger có nút **Authorize**), không token/refresh token. |
| Sprint 5 | **Hoàn thiện CRUD + phân quyền xoá:** thêm `PUT /farms/{farm_id}` (**200**/**404**/**422**), `DELETE /farms/{farm_id}` (**200**, **chỉ admin**, xoá kèm mọi lô của vùng nhờ `cascade="all, delete-orphan"`), `PUT /batches/{batch_id}` (**200**, **404** nếu lô hoặc `farm_id` mới không tồn tại), `DELETE /batches/{batch_id}` (**200**, **chỉ admin**); schemas `FarmUpdate`/`BatchUpdate` (kế thừa `*Create`) và `DeleteResponse` (`message`, `deleted_id`, `deleted_batches`); `require_admin` áp cho cả 2 endpoint `DELETE`. Frontend: sửa lỗi `[hidden]` bị `display` đè (trước đây dashboard vẫn hiện khi chưa đăng nhập), ẩn toàn bộ dashboard/form khi chưa login, cột **Thao tác** (Sửa cho farmer + admin, Xoá **chỉ admin**), form dùng chung cho thêm/sửa (PUT khi đang sửa) và dashboard 3 thẻ (tổng vùng trồng, tổng lô nông sản, tổng sản lượng kg). |
| Sprint 6 | **Bảo mật đăng nhập — khoá tài khoản khi nhập sai nhiều lần:** model `User` thêm `failed_login_attempts` + `locked_until`; `app/security.py` thêm bộ đếm sai liên tiếp và khoá tạm 5 phút (`MAX_FAILED_LOGIN_ATTEMPTS`, `LOCKOUT_DURATION`, `authenticate_user_with_lockout()`, `is_account_locked()`, `register_failed_login()`, `reset_login_attempts()`); `POST /auth/login` trả **403** kèm header `Retry-After` khi tài khoản đang bị khoá (đúng mật khẩu vẫn bị chặn), `get_current_user()` cũng chặn **403** nên mọi API cần quyền đều được bảo vệ; `migrate_user_security_columns()` trong `init_db()` tự thêm 2 cột cho database cũ (không mất dữ liệu); thêm bộ test `pytest` (`tests/`) chạy trên SQLite in-memory. |
| Sprint 7 | **Lịch sử thao tác (audit log):** thêm model `AuditLog` → bảng `audit_logs` (`id`, `user_id` khoá ngoại → `users.id` có index, `action`, `entity`, `entity_id`, `created_at` tự sinh UTC) cùng hằng số `ACTION_CREATE`/`ACTION_UPDATE`/`ACTION_DELETE` và `ENTITY_FARM`/`ENTITY_BATCH`; module mới `app/audit.py` với `record_action()` (ghi log **trong cùng transaction** với thao tác - rollback thì không có log rác) và `fetch_audit_logs()` (mới nhất trước, `joinedload` lấy `username`, mặc định 100 dòng/tối đa 500); `POST`/`PUT`/`DELETE` của `/farms` và `/batches` gọi `record_action()` (endpoint tạo mới thêm `db.flush()` để có `id`) - **status code và body của API cũ không đổi**; router mới `app/routers/audit.py` cung cấp `GET /audit-logs` (**chỉ admin**: farmer **403**, ẩn danh **401**) kèm bộ lọc `entity`/`user_id`/`limit`; schema `AuditLogResponse` (`username` suy ra từ `user_id`); database cũ tự có bảng mới khi `init_db()` chạy (không mất dữ liệu); thêm `tests/test_audit_logs.py` (16 test) và test `init_db()` tạo bảng `audit_logs` cho database cũ - tổng **29 test** đều pass. |

