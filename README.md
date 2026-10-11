# AgriTrace — Hệ thống Quản trị & Truy xuất Nguồn gốc Chuỗi Cung ứng Nông sản

> **Mã học phần / Đề tài:** TTCS-K18C4-N5
> **Repository:** [hoangducviet04012006-ux/TTCS-K18C4-N5](https://github.com/hoangducviet04012006-ux/TTCS-K18C4-N5)
> **Trạng thái hệ thống:** Sprint 1–2 Hoàn thành (Release `main`) | Sprint 3 Đang triển khai (`develop` - S-26 Merged)

---

> [!IMPORTANT]
> **HƯỚNG DẪN KHỞI CHẠY DEMO CHÍNH THỨC (SPRINT 1–3):**
> Tại thư mục gốc của dự án, nhấp đúp file **`start_demo.bat`** (hoặc chạy trong PowerShell: `.\start_demo.bat`).
> Hệ thống sử dụng cơ sở dữ liệu demo độc lập: **`.sprint123-trial/demo_sprint123.db`**.
> **Lưu ý an toàn dữ liệu:** Cơ sở dữ liệu gốc `backend/ttcs.db` được bảo vệ nghiêm ngặt. Launcher tự động tìm kiếm cổng khả dụng từ `8765`, in PID và mở trình duyệt tự động; launcher không reset, seed đè hoặc chạy migration khi khởi động bình thường.
> **Phân biệt phạm vi:** Bản demo hiện hữu chạy qua `start_demo.bat` phản ánh phiên bản hệ thống Sprint 1–2 đã kiểm chứng hoàn chỉnh. Các tính năng mở rộng của Sprint 3 (như tối ưu BFS S-26 và các story tiếp theo) hiện được tích hợp trên nhánh `develop` để kiểm thử tự động, chưa phát hành lên `main` cho bản demo người dùng cuối.
> Chi tiết xem tại [Hướng dẫn Demo chi tiết](docs/DEMO.md) và [Cấu trúc bàn giao](docs/PROJECT_STRUCTURE.md).

---

## 👥 1. Đội ngũ phát triển dự án (Nhóm AgriTrace)

Dự án được xây dựng và phát triển bởi đội ngũ 10 thành viên:

| STT | Họ và tên | Vai trò dự án | Phân công trọng tâm Sprint 3 (Tổng 40 SP) |
| :---: | :--- | :---: | :--- |
| 1 | **Hoàng Đức Việt** | **Leader kiêm Scrum Master** | **S-26 (5 SP):** Tối ưu thuật toán BFS phả hệ đa tầng, cycle detection, điều phối & review PR |
| 2 | **Nguyễn Thị Quỳnh Thơ** | Thành viên | **S-27 (3 SP):** Gom metadata hậu duệ (tổ chức, địa điểm, tồn kho) trong bulk fetch query |
| 3 | **Chu Thị Thảo** | Thành viên | **S-28 (3 SP):** Sơ đồ phả hệ cây tương tác collapsible 3 vùng, cuộn ngang mobile (`lineage_tree.js`) |
| 4 | **Nguyễn Thị Thanh Thảo** | Thành viên | **S-29 + S-31 (4 SP):** Nghiệp vụ tiêu thụ CONSUMED + Middleware AuditLog ghi failed login |
| 5 | **Lý Kiều Trang** | Thành viên | **S-30 (3 SP):** Model `Location`, migration bảng, CRUD địa điểm, điều chuyển lô nội bộ |
| 6 | **Hoàng Anh Tú** | Thành viên | **S-32 (2 SP):** Service nhập danh mục CSV nguyên tử (báo lỗi dòng/cột) & hỗ trợ UI địa điểm |
| 7 | **Ma Thị Thanh Tú** | Thành viên | **S-39 + S-33 (5 SP):** Fixture kiểm chuẩn 4 tầng có đáp án đếm tay + Mở lệnh thu hồi, băm RECALL_INIT |
| 8 | **Ma Thị Uyên** | Thành viên | **S-34 (5 SP):** Duyệt đồ thị thu hồi động từ root, phát hiện lô gộp chéo nguồn |
| 9 | **Nguyễn Hải Đăng** | Thành viên | **S-35 + S-38 (5 SP):** Định lượng tồn kho vs tiêu thụ tích hợp địa chỉ S-30 + Guard phong tỏa 4 thao tác |
| 10 | **Nguyễn Tuấn Đạt** | Thành viên | **S-36 + S-37 (5 SP):** Cảnh báo In-App `my-alerts`, xác nhận ACK + State machine tự động COMPLETED |

---

## 🏗️ 2. Cấu trúc thư mục dự án

| Thư mục / Tệp tin | Vai trò & Nội dung |
| --- | --- |
| `start_demo.bat` | Điểm khởi động demo AgriTrace Sprint 1–3 dành cho người dùng tại thư mục gốc |
| `backend/` | Backend API duy nhất: FastAPI + SQLite + SQLAlchemy 2.0 (chi tiết xem [backend/README.md](backend/README.md)) |
| `frontend/` | Demo giao diện tập trung: `index.html`, `css/style.css`, `js/app.js` — HTML5 + CSS + JavaScript thuần |
| `docs/` | Tài liệu dự án: [DEMO.md](docs/DEMO.md), [PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md), [SPRINT3_IMPLEMENTATION_SPECIFICATION.md](docs/SPRINT3_IMPLEMENTATION_SPECIFICATION.md), [COMPLETION_REPORT.md](docs/COMPLETION_REPORT.md); QA artifacts trong `docs/qa/` |
| `scripts/` | Script phụ nội bộ (`start_demo.ps1`); người dùng chỉ chạy `start_demo.bat` ở gốc |
| `.sprint123-trial/` | Database demo (`demo_sprint123.db`) và cấu hình mật khẩu local riêng; không đưa lên Git |
| `.demo-logs/` | Log khởi động hệ thống; không đưa lên Git |
| `tools/backups/` | Bản sao script/cấu hình trước thay đổi; không đưa lên Git |
| `.github/workflows/ci.yml` | Pipeline CI/CD tự động kiểm tra cú pháp, kiểm thử 299 tests và staging health check |

---

## ⚡ 3. Công nghệ chủ đạo

- **Backend:** Python 3.11, [FastAPI](https://fastapi.tiangolo.com/), [SQLAlchemy 2.0](https://www.sqlalchemy.org/), [Pydantic v2](https://docs.pydantic.dev/), SQLite.
- **Bảo mật & Phân quyền:** Argon2id (băm mật khẩu), HTTP Basic Auth, cơ chế chống dò mật khẩu tạm khóa 15 phút sau 5 lần sai, phân quyền RBAC 7 vai trò đa tổ chức.
- **Frontend:** Pure HTML5, Modern CSS (Responsive Grid/Flexbox, không dùng thư viện cồng kềnh), JavaScript ES6+ Vanilla.
- **Toàn vẹn dữ liệu:** Bảng chỉ thêm (Append-only), Chuỗi băm SHA-256 kết hợp Canonical JSON (`sort_keys=True`, `separators=(',', ':')`), Bảo vệ 2 lớp (ORM Listener + SQLite Triggers).
- **Kiểm thử & CI/CD:** Pytest (**299 bài test tự động** PASS 100%), Flake8, Docker Buildx, GitHub Actions CI/CD Pipeline.

---

## 🚀 4. Hướng dẫn khởi chạy

### Cách 1: Khởi chạy Demo chính thức bằng `start_demo.bat` (Khuyến nghị cho nghiệm thu)
Tại thư mục gốc của dự án, chạy lệnh hoặc nhấp đúp file:
```powershell
.\start_demo.bat
```
- Launcher tự động tìm cổng khả dụng bắt đầu từ `8765` (nếu bận sẽ tự thử cổng kế tiếp, tối đa 100 cổng).
- Database demo độc lập: `.sprint123-trial/demo_sprint123.db`.
- Tự động in PID, URL và mở trình duyệt Web. Để chỉ định cổng bắt đầu tìm: `.\start_demo.bat -Port 8769`.
- Để dừng đúng tiến trình: `Stop-Process -Id <PID>`.

### Cách 2: Khởi chạy trực tiếp cho Lập trình viên (Local Development)

**1. Chạy Backend:**
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```
- API: <http://127.0.0.1:8000>
- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>

**2. Chạy Frontend (Demo server):**
```powershell
cd frontend
python -m http.server 5500
```
- Mở trình duyệt tại: <http://127.0.0.1:5500> (Frontend gọi API tại `http://127.0.0.1:8000`).

**3. Chạy kiểm thử tự động toàn diện (299 tests):**
```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/ -v
```

### Cách 3: Khởi chạy bằng Docker Compose
Yêu cầu máy đã cài [Docker Desktop](https://www.docker.com/). Tại thư mục gốc:
```bash
docker-compose up -d --build
```
- Giao diện Web: <http://localhost>
- Backend API: <http://localhost:8000>
- Swagger UI: <http://localhost:8000/docs> (hoặc qua proxy <http://localhost/docs>)

Dừng hệ thống Docker:
```bash
docker-compose down
```

---

## 🔐 5. Tài khoản demo & Phân quyền truy cập (Sprint 1–2 Baseline)

Hệ thống thiết lập 8 tài khoản demo phân theo 7 vai trò trong chuỗi cung ứng:

| Khóa tài khoản | Email đăng nhập | Vai trò | Tổ chức | Thao tác chính trên giao diện |
| :--- | :--- | :--- | :--- | :--- |
| `farm` | `s123_farm@demo.local` | `farmer` | HTX-DT | Vùng trồng, thu hoạch lô, tách lô |
| `packing` | `s123_packing@demo.local` | `processor` | HTX-DT | Đóng gói, gộp lô, bàn giao sang HTX-TG |
| `receiver` | `s123_receiver@demo.local` | `processor` | HTX-TG | Tiếp nhận bàn giao, kiểm tra chủ sở hữu mới |
| `transport` | `s123_transport@demo.local` | `transporter` | HTX-TG | Vận chuyển, cập nhật nhật ký chuỗi lạnh |
| `distribution` | `s123_distribution@demo.local` | `distributor` | DN-XNK | Tiếp nhận phân phối, xuất kho thương mại |
| `inspector` | `s123_inspector@demo.local` | `inspector` | Toàn cảnh | Xem phả hệ và lịch sử liên tổ chức |
| `admin` | `s123_admin@demo.local` | `system_admin` | HTX-DT | Quản trị tài khoản, danh mục hệ thống |
| `org_admin` | `s123_org_admin@demo.local` | `org_admin` | HTX-DT | Quản trị tài khoản nội bộ tổ chức |

- **Mật khẩu local:** Cấu hình trong `.sprint123-trial/credentials.local` (file được bảo vệ, Git ignore, mở xem bằng `notepad .\.sprint123-trial\credentials.local`).
- **Bảo mật đăng nhập (Lockout):** Nhập sai mật khẩu **5 lần liên tiếp** → tài khoản bị tạm khóa **15 phút** (`403` kèm header `Retry-After`).
- **Lịch sử thao tác (Audit Log):** Mọi thao tác tạo/sửa/xóa vùng trồng và lô nông sản được tự động ghi nhận vào bảng `audit_logs` (`GET /audit-logs`, chỉ `admin`).

---

## 🔒 6. Bảng chỉ thêm (Append-only) & Chuỗi băm bất biến (Sprint 2 / T-26, T-27)

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

---

## 📈 7. Tiến độ thực hiện các Sprint

### ✅ Sprint 1 & Sprint 2: Đã hoàn thành (Baseline đã phát hành lên `main`)
- Đã nghiệm thu toàn diện và phát hành chính thức lên nhánh `main` qua **Pull Request #4** (Merge commit `4e0d31c`).
- Hoàn thành đầy đủ: Quản trị vùng trồng (Farm), quản trị lô (Batch), vòng đời sự kiện, chuỗi băm SHA-256 bất biến, phân quyền RBAC 7 vai trò, bảo mật khóa tài khoản sai 5 lần, Audit log và giao diện Web Dashboard tập trung.

### 🔄 Sprint 3: Đang triển khai (Quy mô 14 User Stories | Tổng 40 Story Points)
Sprint 3 tập trung vào tối ưu hóa truy xuất nguồn gốc chuyên sâu, mở rộng quản lý địa điểm, sơ đồ phả hệ tương tác và hệ thống điều hành thu hồi nông sản (Recall Management).

- **Kế hoạch triển khai:**
  - **Wave 1:** Gồm 5 User Stories: **S-26** (Leader), **S-30** (TV5), **S-31** (TV4), **S-32** (TV6), và **S-39** (TV7).
  - **Wave 2:** Gồm 9 User Stories: **S-27**, **S-28**, **S-29**, **S-33**, **S-34**, **S-35**, **S-36**, **S-37**, **S-38**.

- **Trạng thái chi tiết từng User Story:**
  - **S-26 / SCRUM-63 — Tối ưu hóa truy xuất hậu duệ đa tầng bằng Bulk BFS (Leader — 5 SP):**
    - **Trạng thái:** **ĐÃ HOÀN THÀNH & MERGED VÀO DEVELOP** qua **Pull Request #6** (Merge commit `3b9cc30`).
    - **Kết quả nghiệm thu:**
      - Thuật toán lặp Level-by-Level Bulk BFS kết hợp gom truy vấn SQL `in_()`.
      - Phát hiện chu trình có hướng chính xác bằng thuật toán DFS 3 trạng thái.
      - Hiệu năng vượt trội: Truy xuất đồ thị 1.000 nút chỉ mất **~59.1 ms** (yêu cầu đặt ra: $< 2$ giây).
      - Đạt **299/299 tests pytest PASS 100%** và GitHub Actions CI/CD Staging Health Check PASS.
  - **Các User Stories còn lại (S-27 đến S-39):**
    - Hiện đang được các thành viên trong đội ngũ chuẩn bị và triển khai độc lập theo phân công tại [docs/SPRINT3_IMPLEMENTATION_SPECIFICATION.md](docs/SPRINT3_IMPLEMENTATION_SPECIFICATION.md).
    - Chưa nghiệm thu hoặc đánh dấu hoàn thành trên nhánh tích hợp khi chưa có Pull Request được merge vào `develop`.

---

## 🌿 8. Quy trình Git & Kiểm thử CI/CD cho đội ngũ

### 1. Phân nhánh Git
- `main`: Nhánh Release sản phẩm chính thức, được bảo vệ nghiêm ngặt.
- `develop`: Nhánh tích hợp Sprint đang hoạt động.
- `feat/<story-id>-<short-description>`: Nhánh tính năng cá nhân của từng thành viên.
- `docs/<topic>`: Nhánh tài liệu dự án.

### 2. Quy tắc làm việc & an toàn mã nguồn
- Mỗi thành viên tạo nhánh feature từ `origin/develop` mới nhất.
- Khi cần đồng bộ mã nguồn mới nhất từ nhóm, thực hiện `git fetch origin` và `git merge origin/develop` vào nhánh feature (không bắt buộc dùng rebase phức tạp để tránh rủi ro conflict).
- **Tuyệt đối nghiêm cấm:** Không `git push --force` lên `main` hoặc `develop`; không sử dụng `git reset --hard`; không can thiệp trực tiếp vào file cơ sở dữ liệu `backend/ttcs.db` hoặc `.env`.

### 3. Tiêu chuẩn GitHub Actions CI/CD
- **Khi mở Pull Request vào `develop`:**
  - Job **`Backend Lint & Automated Tests`** bắt buộc phải **PASS** (kiểm tra Flake8 code style và toàn bộ 299 bài test pytest).
  - Job **`Deploy Staging & Health Check`** được **SKIPPED** (chỉ kích hoạt khi push/merge vào các nhánh chính).
- **Sau khi Pull Request được MERGE vào `develop`:**
  - GitHub Actions tự động kích hoạt cả hai jobs: Lint & Test và Deploy Staging.
  - Phải kiểm tra và xác nhận bước **Kiểm tra sức khỏe hệ thống (Health Check)** tại Staging container đạt trạng thái `SUCCESS`.
- Mọi Pull Request phải được Leader (`hoangducviet04012006-ux`) phê duyệt trước khi merge.
