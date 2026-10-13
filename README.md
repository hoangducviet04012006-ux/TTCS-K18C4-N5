# TTCS-K18C4-N5

> **Demo chính thức Sprint 1–3:** chạy `start_demo.bat`, dùng database riêng `.sprint123-trial/demo_sprint123.db`. Xem [hướng dẫn chạy, mật khẩu local và xử lý cổng](docs/DEMO.md). Launcher không seed/reset/migration khi khởi động. Các hướng dẫn Docker, hai server, seed và mật khẩu trong tài liệu cũ dưới đây không phải cấu hình demo này.
Dự án TTCS K18C4 - Truy xuất nguồn gốc và giám sát chuỗi lạnh nông sản

Xem [cấu trúc bàn giao và quy tắc dữ liệu](docs/PROJECT_STRUCTURE.md).

## Cấu trúc thư mục

| Thư mục | Nội dung |
| --- | --- |
| `backend/` | FastAPI + SQLite + SQLAlchemy (chi tiết xem `backend/README.md`) |
| `frontend/` | Demo giao diện: `index.html`, `css/style.css`, `js/app.js` — HTML5 + CSS + JavaScript thuần, không framework |
| `docs/` | Tài liệu dự án; kết quả kiểm thử và ảnh trong `docs/qa/` |
| `scripts/` | Script phụ nội bộ; người dùng chỉ chạy `start_demo.bat` ở gốc |
| `.sprint123-trial/` | Database demo hiện hữu và cấu hình local riêng; không đưa lên Git |
| `.demo-logs/` | Log khởi động, không đưa lên Git |
| `tools/backups/` | Bản sao script/cấu hình trước thay đổi, không đưa lên Git |

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

| Email hoặc tài khoản | Mật khẩu | Thấy được trên giao diện |
| --- | --- | --- |
| `admin@gmail.com` (hoặc `admin`) | `123456` | Toàn bộ: thẻ vùng trồng, lô nông sản **và thẻ "Tài khoản hệ thống" (`GET /users`)** |
| `farmer@gmail.com` (hoặc `farmer`) | `123456` | Vùng trồng + lô nông sản (thẻ "Tài khoản hệ thống" **bị ẩn**) |

- **Đăng nhập bằng email (S-04):** ô nhập đầu tiên chấp nhận **email hoặc tên đăng
  nhập** (email không phân biệt hoa/thường). Các nút *Đăng nhập nhanh* tự điền
  email tài khoản demo.
- **Không dùng JWT:** sau khi đăng nhập, frontend lưu `username`/`password` vào
  `sessionStorage` (khoá `ttcs.session`) và gửi kèm header **HTTP Basic** ở mỗi
  request cần quyền.
- Đóng tab là mất phiên (sessionStorage); bấm nút **Đăng xuất** để xoá phiên ngay.
- Backend trả **`401`** khi thiếu/sai thông tin đăng nhập và **`403`** khi đã đăng
  nhập nhưng sai vai trò (chi tiết xem `backend/README.md`, mục Sprint 4).
- **Bảo mật (S-04 / Sprint 6):** nhập sai mật khẩu **5 lần liên tiếp** → tài khoản
  bị **tạm khoá 15 phút** (`403` kèm thông báo + thời gian chờ còn lại); trong thời
  gian khoá, gõ **đúng** mật khẩu vẫn bị chặn. Hết thời gian khoá thì tự mở khoá và
  bộ đếm về 0 (chi tiết: `backend/README.md`, mục *Bảo mật đăng nhập*).

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

---

## 🔒 Bảng chỉ thêm (Append-only) & Chuỗi băm bất biến (Sprint 2 / T-26, T-27)

### 1. Quy ước bảo vệ Cơ sở dữ liệu
Bảng `batch_events` lưu trữ toàn bộ lịch sử vòng đời của lô nông sản (thu hoạch, bàn giao, tiếp nhận, từ chối). Nhằm bảo đảm tính toàn vẹn và bất biến tuyệt đối của dữ liệu truy xuất nguồn gốc:
- **Tuyệt đối không có API sửa/xóa:** Không cung cấp bất kỳ endpoint `PUT`, `PATCH`, hoặc `DELETE` nào trên tài nguyên `/batch_events` hay `/events`.
- **Bảo vệ hai lớp (Defense-in-Depth):**
  1. **Lớp ORM (SQLAlchemy):** Đăng ký event listener `before_update` và `before_delete` trên model `BatchEvent`. Mọi nỗ lực cập nhật hoặc xóa thông qua ORM session đều bị chặn ngay lập tức và ném ra `PermissionError("Bảng batch_events là bảng chỉ thêm (append-only)...")`.
  2. **Lớp Cơ sở dữ liệu (SQLite Triggers):** Tự động tạo trigger `prevent_update_batch_events` và `prevent_delete_batch_events` với lệnh `RAISE(ABORT, ...)`. Kể cả khi câu lệnh SQL thô `UPDATE` hoặc `DELETE` được thực thi trực tiếp trên database file, hệ quản trị CSDL vẫn từ chối thực hiện.

### 2. Kết luận từ Spike K-01: Tại sao chọn Hash-Chain SHA-256 thay vì Blockchain?
Trong quá trình nghiên cứu kiến trúc (Spike K-01), nhóm phát triển đã so sánh việc ứng dụng Blockchain phân tán (Ethereum, Hyperledger Fabric) so với Chuỗi băm mật mã nội bộ (Cryptographic Hash-Chain):

| Tiêu chí so sánh | Blockchain Phân tán | Hash-Chain SHA-256 (Hệ thống áp dụng) |
| :--- | :--- | :--- |
| **Chi phí vận hành** | Tốn phí giao dịch (Gas fees), tài nguyên duy trì các nodes | **0 chi phí phụ trội**, chạy trực tiếp trên CSDL quan hệ sẵn có |
| **Độ trễ ghi nhận** | 5s – 15s (hoặc hơn) phụ thuộc thuật toán đồng thuận | **Tức thì (< 1ms)**, phù hợp môi trường nông hộ/đồng ruộng |
| **Độ phức tạp hạ tầng** | Rất cao (Smart contract, ví Web3, RPC nodes, validator) | **Gọn nhẹ**, bảo trì đơn giản, chuẩn hoá định dạng Canonical JSON |
| **Khả năng phát hiện giả mạo** | Bất biến nhờ cơ chế đồng thuận phân tán | **Toàn vẹn toán học (Tamper-evident)**: Chỉ cần thay đổi 1 byte dữ liệu hoặc xóa 1 bản ghi, hàm `verify_batch_chain` sẽ phát hiện ngay vị trí vi phạm qua đứt gãy SHA-256 |

**Kết luận:** Với bài toán truy xuất nguồn gốc nông sản chuỗi lạnh cấp hợp tác xã và doanh nghiệp vừa và nhỏ, mô hình **Append-only Hash-Chain kết hợp Genesis Hash (`"0" * 64`) và Canonical JSON (`sort_keys=True`, `separators=(',', ':')`)** đáp ứng hoàn hảo yêu cầu kỹ thuật: minh bạch, bất biến, phát hiện gian lận tức thì mà không gây gánh nặng chi phí hay hạ tầng.
