# TTCS-K18C4-N5
Dự án TTCS K18C4 - Truy xuất nguồn gốc và giám sát chuỗi lạnh nông sản

## Cấu trúc thư mục

| Thư mục | Nội dung |
| --- | --- |
| `backend/` | FastAPI + SQLite + SQLAlchemy (chi tiết xem `backend/README.md`) |
| `frontend/` | Demo giao diện: `index.html`, `css/style.css`, `js/app.js` — HTML5 + CSS + JavaScript thuần, không framework |
| `docs/` | Tài liệu dự án |

## 🚀 Khởi chạy nhanh bằng một lệnh (Docker Compose)

Yêu cầu máy đã cài [Docker Desktop](https://www.docker.com/). Tại thư mục gốc của dự án, chạy lệnh:

```bash
docker-compose up -d --build
```

Sau khi khởi chạy thành công:
- **Giao diện Web Nông sản:** <http://localhost> (hoặc <http://127.0.0.1>)
- **Backend API:** <http://localhost:8000>
- **Tài liệu API Swagger UI:** <http://localhost:8000/docs> (hoặc qua proxy <http://localhost/docs>)
- **Tài liệu ReDoc:** <http://localhost:8000/redoc> (hoặc qua proxy <http://localhost/redoc>)

Dữ liệu SQLite được bảo toàn tự động qua volume `sqlite_data`. Khi muốn dừng hệ thống:
```bash
docker-compose down
```

---

## 🛠️ Chạy trực tiếp (Local Development)

### 1. Chạy backend

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

- API: <http://127.0.0.1:8000>
- Swagger UI: <http://127.0.0.1:8000/docs>

## Chạy frontend (demo)

```powershell
cd frontend
python -m http.server 5500
```

Mở <http://127.0.0.1:5500>. Có thể mở trực tiếp `frontend/index.html`,
nhưng nên chạy qua static server để `fetch`/CORS hoạt động ổn định nhất.

### 3. Kiểm thử tự động (CI / Pytest)

Hệ thống tích hợp GitHub Actions CI Pipeline (`.github/workflows/ci.yml`) tự động kích hoạt khi `push`/`pull_request` vào `main`, `master`, `develop`.

Chạy toàn bộ 38 bài test tự động từ thư mục gốc:

```powershell
pytest backend/tests/ -v
```

Frontend gọi API tại `http://127.0.0.1:8000` (hằng số `API_BASE_URL` trong `frontend/js/app.js`).

### Đăng nhập (Sprint 4)

Mở trang → hiện **màn hình đăng nhập** (`POST /auth/login`). Tài khoản demo do
backend tạo tự động ở lần chạy đầu tiên:

| Tài khoản | Mật khẩu | Thấy được trên giao diện |
| --- | --- | --- |
| `admin` | `123456` | Toàn bộ: thẻ vùng trồng, lô nông sản **và thẻ "Tài khoản hệ thống" (`GET /users`)** |
| `farmer` | `123456` | Vùng trồng + lô nông sản (thẻ "Tài khoản hệ thống" **bị ẩn**) |

- **Không dùng JWT:** sau khi đăng nhập, frontend lưu `username`/`password` vào
  `sessionStorage` (khoá `ttcs.session`) và gửi kèm header **HTTP Basic** ở mỗi
  request cần quyền.
- Đóng tab là mất phiên (sessionStorage); bấm nút **Đăng xuất** để xoá phiên ngay.
- Backend trả **`401`** khi thiếu/sai thông tin đăng nhập và **`403`** khi đã đăng
  nhập nhưng sai vai trò (chi tiết xem `backend/README.md`, mục Sprint 4).
- **Bảo mật (Sprint 6):** nhập sai mật khẩu **5 lần liên tiếp** → tài khoản bị
  **tạm khoá 5 phút** (`403` kèm header `Retry-After`); trong thời gian khoá, gõ
  **đúng** mật khẩu vẫn bị chặn. Hết 5 phút thì tự mở khoá và bộ đếm về 0
  (chi tiết: `backend/README.md`, mục *Bảo mật đăng nhập*).

### CRUD & phân quyền (Sprint 5)

Sau khi đăng nhập, giao diện hiện **dashboard** gồm 3 thẻ thống kê (tổng vùng
trồng, tổng lô nông sản, tổng sản lượng kg) và 2 bảng dữ liệu có cột **Thao tác**:

| Tài khoản | Thêm | Sửa | Xoá | Quản lý tài khoản |
| --- | --- | --- | --- | --- |
| `admin` | ✅ | ✅ | ✅ | ✅ (`GET /users`) |
| `farmer` | ✅ | ✅ | ❌ **không có nút Xoá** (cố gọi API xoá → `403`) | ❌ |

- Bấm **Sửa** ở bảng → form phía trên tự điền dữ liệu và chuyển sang chế độ sửa
  (nút đổi thành **Cập nhật...**); bấm **Huỷ sửa** để quay lại chế độ thêm mới.
- Bấm **Xoá** → hộp thoại xác nhận → gọi `DELETE`. Xoá **vùng trồng** sẽ xoá kèm
  toàn bộ lô nông sản của vùng đó (backend trả về số lô bị xoá kèm để hiển thị).
- **Chưa đăng nhập:** chỉ hiện màn hình đăng nhập — dashboard, bảng dữ liệu và
  form nhập bị ẩn hoàn toàn. Bấm **Đăng xuất** → xoá phiên, xoá dữ liệu đang hiện
  và quay về màn hình đăng nhập.
- API tương ứng: `POST` / `GET` / `PUT` / `DELETE` cho `/farms` và `/batches`
  (bảng endpoint đầy đủ: xem `backend/README.md`, mục 3).

### Lịch sử thao tác — audit log (Sprint 7)

Theo dõi **ai đã làm gì trong hệ thống**: mỗi lần tạo/sửa/xoá **vùng trồng** hoặc
**lô nông sản** thành công, backend tự ghi 1 dòng vào bảng `audit_logs`
(`user_id`, `action` = `create`/`update`/`delete`, `entity` = `farm`/`batch`,
`entity_id`, `created_at`). Thao tác bị chặn (`401`/`403`/`404`/`422`) **không**
sinh log, và log **không** sửa/xoá được qua API.

| Endpoint | Quyền | Ghi chú |
| --- | --- | --- |
| `GET /audit-logs` | **chỉ `admin`** (farmer → `403`) | Trả log **mới nhất trước**; lọc `?entity=farm\|batch`, `?user_id=`, `?limit=` |

- Đây là phần **backend**; giao diện frontend hiện **chưa** có màn hình xem lịch sử
  (xem log nhanh bằng Swagger UI tại <http://127.0.0.1:8000/docs> → `GET /audit-logs`).
- **Không thay đổi API cũ:** status code và body của `/farms`, `/batches`,
  `/auth/login`, `/users` giữ nguyên như Sprint 5/6 — chỉ ghi thêm log khi thao tác
  thành công.
- Database cũ (`backend/ttcs.db`) **không cần xoá**: bảng `audit_logs` được tạo tự
  động khi server khởi động (`init_db()`), dữ liệu sẵn có vẫn nguyên vẹn.
