# Backend - TTCS K18C4

Backend API cho đề tài **"Truy xuất nguồn gốc và giám sát chuỗi lạnh nông sản"**.

- **Framework:** Python + FastAPI
- **Database:** SQLite (file local, không cần cài server)
- **ORM:** SQLAlchemy 2.0
- **Sprint 1 (nền tảng):** cấu hình FastAPI, kết nối SQLite, endpoint kiểm tra
  hệ thống `GET /health`.
- **Sprint 2 (đang làm):** module **Farm** — quản lý vùng trồng (`POST /farms`,
  `GET /farms`) và module **Batch** — quản lý lô nông sản (`POST /batches`,
  `GET /batches`, `GET /batches/{batch_id}`).
  Quan hệ dữ liệu: `Farm 1 ---- N Batch`.
  *Chưa có* QR code, blockchain hay nghiệp vụ chuỗi lạnh.

---

## 1. Cấu trúc thư mục

```
backend/
├── app/
│   ├── __init__.py          # Đánh dấu package + khai báo __version__
│   ├── main.py              # Khởi tạo FastAPI, CORS, lifespan, đăng ký router
│   ├── database.py          # Engine SQLite, SessionLocal, Base, get_db, init_db
│   ├── models.py            # ORM models: Farm → "farms", Batch → "batches"
│   ├── schemas.py           # Pydantic: Health / Farm / Batch (Create + Response)
│   └── routers/
│       ├── __init__.py      # Export các router
│       ├── health.py        # GET /health
│       ├── farms.py         # POST /farms, GET /farms
│       └── batches.py       # POST /batches, GET /batches, GET /batches/{id}
├── requirements.txt         # Danh sách thư viện Python
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

---

## 3. API hiện có

| Method | Endpoint | Mô tả | Mã trả về |
| --- | --- | --- | --- |
| GET | `/health` | Kiểm tra hệ thống đang chạy | `200` |
| POST | `/farms` | Tạo vùng trồng mới | `201` thành công · `422` dữ liệu sai |
| GET | `/farms` | Lấy danh sách vùng trồng (sắp xếp theo `id` tăng dần) | `200` |
| POST | `/batches` | Tạo lô nông sản (kiểm tra `farm_id` tồn tại) | `201` · `404` farm không tồn tại · `422` dữ liệu sai |
| GET | `/batches` | Lấy danh sách lô nông sản (sắp xếp theo `id` tăng dần) | `200` |
| GET | `/batches/{batch_id}` | Xem chi tiết một lô nông sản | `200` · `404` không tìm thấy |

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

---

## 4. Hướng dẫn test API bằng Swagger

### 4.1. Test trực tiếp trên Swagger UI

1. Chạy server: `uvicorn app.main:app --reload`
2. Mở <http://127.0.0.1:8000/docs>
3. **Tạo vùng trồng:** mở `POST /farms` → bấm **Try it out** → dán JSON body bên
   dưới vào ô *Request body* → bấm **Execute**
   → mong đợi **`201 Created`**, response body có thêm `id` do database sinh ra.
4. **Lấy danh sách:** mở `GET /farms` → **Try it out** → **Execute**
   → mong đợi **`200 OK`** và một mảng JSON (mảng rỗng `[]` nếu chưa có dữ liệu).
5. **Kiểm tra validate:** gửi lại `POST /farms` với `"area": -1` hoặc bỏ trống
   `name` → mong đợi **`422 Unprocessable Entity`** kèm mô tả lỗi.
6. **Tạo lô nông sản:** mở `POST /batches` → **Try it out** → dán JSON body thứ hai
   bên dưới (nhớ `farm_id` là id vùng trồng vừa tạo ở bước 3) → **Execute**
   → mong đợi **`201 Created`**.
7. **Danh sách lô:** mở `GET /batches` → **Try it out** → **Execute**
   → mong đợi **`200 OK`** và mảng các lô nông sản.
8. **Chi tiết một lô:** mở `GET /batches/{batch_id}` → **Try it out** → nhập `1`
   → **Execute** → mong đợi **`200 OK`**; thử nhập `999` → **`404 Not Found`**.
9. **Kiểm tra chặn dữ liệu sai của Batch:** gửi `POST /batches` với `"farm_id": 999`
   → mong đợi **`404`** kèm `"Không tìm thấy vùng trồng có id=999."`;
   gửi `"quantity": -1` hoặc để trống `product_name` → mong đợi **`422`**.
10. **Kiểm tra `/health` vẫn hoạt động:** mở `GET /health` → **Execute**
    → mong đợi `200` + `{"status": "running"}`.

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
# 1. Kiểm tra hệ thống
Invoke-RestMethod http://127.0.0.1:8000/health

# 2. Tạo vùng trồng mới
$body = '{"name":"Vung trong xoai Cao Lanh","location":"Xa My Xuong, Cao Lanh, Dong Thap","area":2.5,"owner":"HTX Xoai My Xuong"}'
Invoke-RestMethod -Uri http://127.0.0.1:8000/farms -Method Post -ContentType 'application/json; charset=utf-8' -Body $body

# 3. Lấy danh sách vùng trồng
Invoke-RestMethod http://127.0.0.1:8000/farms | ConvertTo-Json

# 4. Tạo lô nông sản cho vùng trồng id=1
$batch = '{"farm_id":1,"product_name":"Xoai cat Chu","quantity":120.5,"harvest_date":"2026-01-15"}'
Invoke-RestMethod -Uri http://127.0.0.1:8000/batches -Method Post -ContentType 'application/json; charset=utf-8' -Body $batch

# 5. Danh sách lô + chi tiết lô id=1
Invoke-RestMethod http://127.0.0.1:8000/batches | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/batches/1 | ConvertTo-Json
```

**Cách 2 — `curl.exe` (bắt buộc dùng `--%`, xem lưu ý bên dưới):**

```powershell
curl.exe --% -s http://127.0.0.1:8000/health

curl.exe --% -s -X POST http://127.0.0.1:8000/farms -H "Content-Type: application/json" -d "{\"name\":\"Vung trong xoai Cao Lanh\",\"location\":\"Cao Lanh, Dong Thap\",\"area\":2.5,\"owner\":\"HTX Xoai\"}"

curl.exe -s http://127.0.0.1:8000/farms

curl.exe --% -s -X POST http://127.0.0.1:8000/batches -H "Content-Type: application/json" -d "{\"farm_id\":1,\"product_name\":\"Xoai cat Chu\",\"quantity\":120.5,\"harvest_date\":\"2026-01-15\"}"

curl.exe -s http://127.0.0.1:8000/batches
curl.exe -s http://127.0.0.1:8000/batches/1
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
`ttcs.db`, chạy lại server (bảng sẽ được tạo mới, rỗng).

---

## 5. Giải thích từng file

| File | Vai trò |
| --- | --- |
| `app/main.py` | Entrypoint: tạo `FastAPI(...)`, cấu hình CORS, dùng `lifespan` để gọi `init_db()` khi server start, và `include_router` để gom các endpoint. Khi mở rộng, chỉ cần thêm 1 dòng `app.include_router(...)`. |
| `app/database.py` | Tầng hạ tầng dữ liệu: tạo `engine` kết nối SQLite (`check_same_thread=False` vì FastAPI có thể xử lý request trên thread khác — tham số này chỉ dành riêng cho SQLite), `SessionLocal` để mở session mỗi request, `Base` (DeclarativeBase) cho mọi model, `get_db()` (dependency đóng session tự động) và `init_db()` (tạo bảng từ metadata). |
| `app/models.py` | Nơi khai báo bảng ORM (SQLAlchemy 2.0 style: `Mapped` + `mapped_column`). Hiện có: `Farm` → bảng `farms` (`id`, `name`, `location`, `area`, `owner`) và `Batch` → bảng `batches` (`id`, `farm_id` FK → `farms.id`, `product_name`, `quantity`, `harvest_date`) với quan hệ 2 chiều `Farm 1-N Batch` (`farm.batches` ↔ `batch.farm`). Thêm bảng mới ở đây thì `init_db()` sẽ tự tạo. |
| `app/schemas.py` | Pydantic models mô tả dữ liệu request/response: `HealthResponse`, `FarmCreate`/`FarmResponse`, `BatchCreate`/`BatchResponse` (`farm_id > 0`, chuỗi không rỗng, `quantity > 0`, `harvest_date` kiểu `date`). `*Response` dùng `from_attributes=True` để trả thẳng ORM object kèm `id`. Tách khỏi `models.py` để không lộ cấu trúc bảng ra API. |
| `app/routers/health.py` | Router chứa endpoint `GET /health`, khai báo `response_model=HealthResponse`, trả về `{"status": "running"}`. |
| `app/routers/farms.py` | Router module Farm: `POST /farms` (thêm bản ghi, `commit` + `refresh`, rollback nếu lỗi DB) và `GET /farms` (truy vấn bằng `select()` của SQLAlchemy 2.0). |
| `app/routers/batches.py` | Router module Batch: `POST /batches` (**404** nếu `farm_id` không tồn tại — kiểm tra bằng `db.get(Farm, ...)` trước khi ghi), `GET /batches` (danh sách, sắp theo `id`) và `GET /batches/{batch_id}` (**404** nếu không thấy). |
| `app/routers/__init__.py` | Gom và export các router con để `main.py` import ngắn gọn (`from app.routers import batches, farms, health`). |
| `app/__init__.py` | Đánh dấu `app` là package Python; khai báo `__version__ = "0.1.0"` dùng cho metadata Swagger. |
| `requirements.txt` | Ghim phiên bản thư viện: `fastapi`, `uvicorn[standard]`, `SQLAlchemy`, `pydantic` — đảm bảo cả nhóm cài ra môi trường giống nhau. |
| `.gitignore` | Bỏ qua `.venv/`, `__pycache__/`, `*.db`... để không commit rác và dữ liệu local. |

---

## 6. Hướng mở rộng ở Sprint sau

1. **Thêm bảng:** khai báo model mới trong `app/models.py` → bảng tự được tạo
   ở lần chạy tiếp theo.
2. **Thêm endpoint:** tạo file mới trong `app/routers/` (ví dụ `cold_chain.py`),
   thêm schema tương ứng vào `app/schemas.py`, rồi đăng ký router trong
   `app/main.py`.
3. **Bổ sung CRUD:** `GET /farms/{farm_id}` (trả 404 nếu không thấy), `PUT`/`DELETE`
   cho cả Farm và Batch; cho `GET /batches` hỗ trợ lọc theo vùng trồng
   (`?farm_id=1`) và phân trang (`skip`, `limit`).
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
9. **Kiểm thử:** thêm `tests/` với `pytest` + `fastapi.testclient` (cần `httpx`).

---

## 7. Lịch sử thay đổi

| Giai đoạn | Nội dung |
| --- | --- |
| Sprint 1 | Khung dự án: FastAPI + SQLite + SQLAlchemy, endpoint `GET /health`. |
| Sprint 2 | Module **Farm** (quản lý vùng trồng): model `Farm` → bảng `farms` (tự tạo), schemas `FarmCreate`/`FarmResponse`, router `app/routers/farms.py` với `POST /farms` (**201**) và `GET /farms` (**200**). `GET /health` giữ nguyên. |
| Sprint 3 | Module **Batch** (quản lý lô nông sản): model `Batch` → bảng `batches` (FK `farm_id` → `farms.id`, quan hệ `Farm 1 ---- N Batch`), schemas `BatchCreate`/`BatchResponse`, router `app/routers/batches.py` với `POST /batches` (**201**, trả **404** nếu `farm_id` không tồn tại), `GET /batches` (**200**) và `GET /batches/{batch_id}` (**200**/**404**). `GET /health`, `POST /farms`, `GET /farms` giữ nguyên. |

