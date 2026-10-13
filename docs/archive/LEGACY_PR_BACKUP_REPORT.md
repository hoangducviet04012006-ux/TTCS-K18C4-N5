# BÁO CÁO SAO LƯU CHI TIẾT CÁC PULL REQUEST (PR #1 - PR #4)

> Thời điểm sao lưu: 11/10/2026 | Người thực hiện: Scrum Master / Tech Lead AgriTrace
> Mục đích: Lưu trữ toàn bộ siêu dữ liệu, lịch sử commit, danh sách file thay đổi của các PR cũ trước khi chuẩn hóa nhánh.

## 1. Pull Request #1: Implement S-08 S-09 S-14
- **Tác giả (Author)**: `dtc245200137-alt`
- **Trạng thái (State)**: `OPEN` (Draft: `False`)
- **Nhánh nguồn (Head)**: `hoangducviet04012006-ux:S08-S09-S14` (Commit: `c3a5e242b3e79d148628208c60f44ecce0a54dba`)
- **Nhánh đích (Base)**: `main`
- **Thời gian tạo**: `2026-10-06T17:04:05Z` | **Cập nhật**: `2026-10-06T17:11:27Z`
- **Link GitHub**: https://github.com/hoangducviet04012006-ux/TTCS-K18C4-N5/pull/1
- **Thống kê thay đổi**: +134 dòng, -55 dòng, 3 files, 2 commits

### Mô tả ban đầu (PR Body):
```markdown
Implement S-08, S-09, S-14.

- Add automatic batch code generation
- Add batch data validation
- Update batch API
```

### Danh sách commits:
- `82be3e09` - *Implement S-08 S-09 S-14* (Tác giả: Nguyen Thi Thanh Thao, Ngày: 2026-10-06T16:55:13Z)
- `c3a5e242` - *Complete S08 S09 S14* (Tác giả: Nguyen Thi Thanh Thao, Ngày: 2026-10-06T17:11:16Z)

### Danh sách files thay đổi:
- `backend/app/models.py`: +8 / -1 (`modified`)
- `backend/app/routers/batches.py`: +82 / -49 (`modified`)
- `backend/app/schemas.py`: +44 / -5 (`modified`)

---

## 1. Pull Request #2: Feature/s14 danh sach lo dang giu
- **Tác giả (Author)**: `dtc245200424-collab`
- **Trạng thái (State)**: `OPEN` (Draft: `False`)
- **Nhánh nguồn (Head)**: `hoangducviet04012006-ux:feature/S14-danh-sach-lo-dang-giu` (Commit: `58e9d2a363469b2e126fb90721c9bf6429501472`)
- **Nhánh đích (Base)**: `main`
- **Thời gian tạo**: `2026-10-06T21:44:32Z` | **Cập nhật**: `2026-10-06T21:44:32Z`
- **Link GitHub**: https://github.com/hoangducviet04012006-ux/TTCS-K18C4-N5/pull/2
- **Thống kê thay đổi**: +4994 dòng, -168 dòng, 30 files, 9 commits

### Mô tả ban đầu (PR Body):
```markdown
(Không có mô tả)
```

### Danh sách commits:
- `659102b8` - *feat(handover): implement batch handover and response flow (SCRUM-27, SCRUM-28)* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T02:12:10Z)
- `1b03bf3d` - *ci: add GitHub Actions pipeline, health check endpoint and staging verification (SCRUM-16, SCRUM-17)* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T02:12:24Z)
- `396c517d` - *feat: Trien khai S-11 (append-only batch events) va S-12 (hash chain integrity check)* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T13:38:09Z)
- `f8f7714a` - *style: Fix all flake8 linter formatting errors (imports, line lengths, blank lines)* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T14:08:15Z)
- `c1364e50` - *Merge remote-tracking branch 'origin/main' into develop* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T14:18:34Z)
- `0766f764` - *Merge branch 'develop' of https://github.com/hoangducviet04012006-ux/TTCS-K18C4-N5 into develop* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T14:24:39Z)
- `1c5efb9e` - *feat: Trien khai [S-25] Trang chi tiet lo (Batch Detail View, Parent-Child batch relationships, current holder & remaining quantity)* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T14:35:47Z)
- `c5ba95cf` - *feat: Trien khai [T-58] Truy van tong hop chi tiet lo kem lo me va lo con truc tiep (get_batch_with_direct_relations, no N+1 query, GET /batches/{id}/tree)* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T14:39:28Z)
- `58e9d2a3` - *feat: [T-59] Trang chi tiet lien ket sang dong thoi gian va danh sach to tien  Them cac chuc nang T-59: - GET /batches/{id}/ancestors: API tra ve chuoi to tien theo quan he parent_id - Frontend: 2 nut 'Xem dong thoi gian' va 'Xem danh sach to tien' trong trang chi tiet lo (S-25) - Frontend: 2 modal hien thi timeline (events) va ancestors voi loading/error/empty states - Modal dong bang nut x va click backdrop - Them parent_id vao BatchCreate schema de cho phep tao lo con - 7 unit tests cho ancestors API va timeline events API (71/71 passed) - flake8: 0 loi* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T15:03:26Z)

### Danh sách files thay đổi:
- `.flake8`: +13 / -0 (`added`)
- `.github/workflows/ci.yml`: +87 / -12 (`modified`)
- `backend/app/batch_tree.py`: +166 / -0 (`added`)
- `backend/app/database.py`: +84 / -0 (`modified`)
- `backend/app/events.py`: +189 / -0 (`added`)
- `backend/app/main.py`: +38 / -3 (`modified`)
- `backend/app/models.py`: +240 / -0 (`modified`)
- `backend/app/routers/audit.py`: +108 / -108 (`modified`)
- `backend/app/routers/auth.py`: +0 / -1 (`modified`)
- `backend/app/routers/batches.py`: +173 / -10 (`modified`)
- `backend/app/routers/events.py`: +175 / -0 (`added`)
- `backend/app/routers/handovers.py`: +361 / -0 (`added`)
- `backend/app/routers/health.py`: +16 / -12 (`modified`)
- `backend/app/schemas.py`: +290 / -4 (`modified`)
- `backend/requirements.txt`: +2 / -2 (`modified`)
- `backend/tests/conftest.py`: +2 / -0 (`modified`)
- `backend/tests/test_audit_logs.py`: +0 / -3 (`modified`)
- `backend/tests/test_batch_ancestors.py`: +204 / -0 (`added`)
- `backend/tests/test_batch_detail.py`: +142 / -0 (`added`)
- `backend/tests/test_batch_events.py`: +234 / -0 (`added`)
- `backend/tests/test_batch_events_integrity.py`: +237 / -0 (`added`)
- `backend/tests/test_batch_tree.py`: +193 / -0 (`added`)
- `backend/tests/test_handovers.py`: +407 / -0 (`added`)
- `backend/tests/test_health.py`: +16 / -0 (`added`)
- `docs/CI_CD_AND_BRANCH_PROTECTION.md`: +102 / -0 (`added`)
- `docs/S11_S12_IMPLEMENTATION.md`: +172 / -0 (`added`)
- `frontend/css/style.css`: +450 / -0 (`modified`)
- `frontend/index.html`: +252 / -1 (`modified`)
- `frontend/js/app.js`: +640 / -11 (`modified`)
- `nginx.conf`: +1 / -1 (`modified`)

---

## 1. Pull Request #3: SCRUM-39: [S-24] Hiển thị cảnh báo bàn giao quá hạn 24h chưa xác nhận
- **Tác giả (Author)**: `dtc245200424-collab`
- **Trạng thái (State)**: `OPEN` (Draft: `False`)
- **Nhánh nguồn (Head)**: `hoangducviet04012006-ux:feature/S24-ban-giao-qua-han` (Commit: `c70f0f2c5d2a6564206704e578f8be0e64095a09`)
- **Nhánh đích (Base)**: `main`
- **Thời gian tạo**: `2026-10-07T05:46:32Z` | **Cập nhật**: `2026-10-07T05:46:32Z`
- **Link GitHub**: https://github.com/hoangducviet04012006-ux/TTCS-K18C4-N5/pull/3
- **Thống kê thay đổi**: +6177 dòng, -509 dòng, 30 files, 11 commits

### Mô tả ban đầu (PR Body):
```markdown
### 🎯 Mục tiêu
Hiển thị cảnh báo bàn giao quá hạn (`⚠️ Quá hạn 24h`) cho các yêu cầu bàn giao chưa xác nhận vượt quá 24h ở cả hai phía (Bên gửi và Bên nhận).

### 🛠 Thay đổi thực hiện
- Bổ sung hàm `isOverdueHandover()` trong `app.js` tính toán chênh lệch thời gian 24 giờ.
- Tích hợp nhãn cảnh báo `overdueTag` vào bảng **Lô hàng chờ xác nhận bàn giao** (`renderPendingHandovers`).
- Tích hợp nhãn cảnh báo `overdueTag` vào bảng **Danh sách lô nông sản** (`renderBatches`).

### 🧪 Kiểm thử (Testing)
- Kết nối thành công Backend FastAPI/Uvicorn (`http://127.0.0.1:8000`).
- Kiểm tra render giao diện Frontend, không phát sinh lỗi Console.
```

### Danh sách commits:
- `659102b8` - *feat(handover): implement batch handover and response flow (SCRUM-27, SCRUM-28)* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T02:12:10Z)
- `1b03bf3d` - *ci: add GitHub Actions pipeline, health check endpoint and staging verification (SCRUM-16, SCRUM-17)* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T02:12:24Z)
- `396c517d` - *feat: Trien khai S-11 (append-only batch events) va S-12 (hash chain integrity check)* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T13:38:09Z)
- `f8f7714a` - *style: Fix all flake8 linter formatting errors (imports, line lengths, blank lines)* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T14:08:15Z)
- `c1364e50` - *Merge remote-tracking branch 'origin/main' into develop* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T14:18:34Z)
- `0766f764` - *Merge branch 'develop' of https://github.com/hoangducviet04012006-ux/TTCS-K18C4-N5 into develop* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T14:24:39Z)
- `1c5efb9e` - *feat: Trien khai [S-25] Trang chi tiet lo (Batch Detail View, Parent-Child batch relationships, current holder & remaining quantity)* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T14:35:47Z)
- `c5ba95cf` - *feat: Trien khai [T-58] Truy van tong hop chi tiet lo kem lo me va lo con truc tiep (get_batch_with_direct_relations, no N+1 query, GET /batches/{id}/tree)* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T14:39:28Z)
- `58e9d2a3` - *feat: [T-59] Trang chi tiet lien ket sang dong thoi gian va danh sach to tien  Them cac chuc nang T-59: - GET /batches/{id}/ancestors: API tra ve chuoi to tien theo quan he parent_id - Frontend: 2 nut 'Xem dong thoi gian' va 'Xem danh sach to tien' trong trang chi tiet lo (S-25) - Frontend: 2 modal hien thi timeline (events) va ancestors voi loading/error/empty states - Modal dong bang nut x va click backdrop - Them parent_id vao BatchCreate schema de cho phep tao lo con - 7 unit tests cho ancestors API va timeline events API (71/71 passed) - flake8: 0 loi* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T15:03:26Z)
- `5ae45db9` - *SCRUM-39: [S-24] Ban giao qua han chua xac nhan bi danh dau cho ca hai ben* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-07T05:19:09Z)
- `c70f0f2c` - *SCRUM-39: Hoan thanh hien thi danh dau qua han 24h cho ca hai ben* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-07T05:26:57Z)

### Danh sách files thay đổi:
- `.flake8`: +13 / -0 (`added`)
- `.github/workflows/ci.yml`: +87 / -12 (`modified`)
- `backend/app/batch_tree.py`: +166 / -0 (`added`)
- `backend/app/database.py`: +84 / -0 (`modified`)
- `backend/app/events.py`: +189 / -0 (`added`)
- `backend/app/main.py`: +38 / -3 (`modified`)
- `backend/app/models.py`: +240 / -0 (`modified`)
- `backend/app/routers/audit.py`: +108 / -108 (`modified`)
- `backend/app/routers/auth.py`: +0 / -1 (`modified`)
- `backend/app/routers/batches.py`: +173 / -10 (`modified`)
- `backend/app/routers/events.py`: +175 / -0 (`added`)
- `backend/app/routers/handovers.py`: +361 / -0 (`added`)
- `backend/app/routers/health.py`: +16 / -12 (`modified`)
- `backend/app/schemas.py`: +290 / -4 (`modified`)
- `backend/requirements.txt`: +2 / -2 (`modified`)
- `backend/tests/conftest.py`: +2 / -0 (`modified`)
- `backend/tests/test_audit_logs.py`: +0 / -3 (`modified`)
- `backend/tests/test_batch_ancestors.py`: +204 / -0 (`added`)
- `backend/tests/test_batch_detail.py`: +142 / -0 (`added`)
- `backend/tests/test_batch_events.py`: +234 / -0 (`added`)
- `backend/tests/test_batch_events_integrity.py`: +237 / -0 (`added`)
- `backend/tests/test_batch_tree.py`: +193 / -0 (`added`)
- `backend/tests/test_handovers.py`: +407 / -0 (`added`)
- `backend/tests/test_health.py`: +16 / -0 (`added`)
- `docs/CI_CD_AND_BRANCH_PROTECTION.md`: +102 / -0 (`added`)
- `docs/S11_S12_IMPLEMENTATION.md`: +172 / -0 (`added`)
- `frontend/css/style.css`: +529 / -6 (`modified`)
- `frontend/index.html`: +906 / -291 (`modified`)
- `frontend/js/app.js`: +1090 / -56 (`modified`)
- `nginx.conf`: +1 / -1 (`modified`)

---

## 1. Pull Request #4: Release S-07, S-08, S-09 to main
- **Tác giả (Author)**: `ChThao`
- **Trạng thái (State)**: `OPEN` (Draft: `False`)
- **Nhánh nguồn (Head)**: `hoangducviet04012006-ux:develop` (Commit: `685234b547e205c27313e147bdda3707bb76e4fc`)
- **Nhánh đích (Base)**: `main`
- **Thời gian tạo**: `2026-10-07T07:03:42Z` | **Cập nhật**: `2026-10-07T07:03:42Z`
- **Link GitHub**: https://github.com/hoangducviet04012006-ux/TTCS-K18C4-N5/pull/4
- **Thống kê thay đổi**: +7546 dòng, -764 dòng, 34 files, 15 commits

### Mô tả ban đầu (PR Body):
```markdown
- Hoàn thành S-07: Màn hình & API quản lý danh mục sản phẩm, đơn vị tính
- Hoàn thành S-08: Form tạo lô thu hoạch & sinh mã lô ngẫu nhiên 8 ký tự
- Hoàn thành S-09: Validate ngày thu hoạch, khối lượng và chống double-click
```

### Danh sách commits:
- `659102b8` - *feat(handover): implement batch handover and response flow (SCRUM-27, SCRUM-28)* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T02:12:10Z)
- `1b03bf3d` - *ci: add GitHub Actions pipeline, health check endpoint and staging verification (SCRUM-16, SCRUM-17)* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T02:12:24Z)
- `396c517d` - *feat: Trien khai S-11 (append-only batch events) va S-12 (hash chain integrity check)* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T13:38:09Z)
- `f8f7714a` - *style: Fix all flake8 linter formatting errors (imports, line lengths, blank lines)* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T14:08:15Z)
- `c1364e50` - *Merge remote-tracking branch 'origin/main' into develop* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T14:18:34Z)
- `0766f764` - *Merge branch 'develop' of https://github.com/hoangducviet04012006-ux/TTCS-K18C4-N5 into develop* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T14:24:39Z)
- `1c5efb9e` - *feat: Trien khai [S-25] Trang chi tiet lo (Batch Detail View, Parent-Child batch relationships, current holder & remaining quantity)* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T14:35:47Z)
- `c5ba95cf` - *feat: Trien khai [T-58] Truy van tong hop chi tiet lo kem lo me va lo con truc tiep (get_batch_with_direct_relations, no N+1 query, GET /batches/{id}/tree)* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T14:39:28Z)
- `58e9d2a3` - *feat: [T-59] Trang chi tiet lien ket sang dong thoi gian va danh sach to tien  Them cac chuc nang T-59: - GET /batches/{id}/ancestors: API tra ve chuoi to tien theo quan he parent_id - Frontend: 2 nut 'Xem dong thoi gian' va 'Xem danh sach to tien' trong trang chi tiet lo (S-25) - Frontend: 2 modal hien thi timeline (events) va ancestors voi loading/error/empty states - Modal dong bang nut x va click backdrop - Them parent_id vao BatchCreate schema de cho phep tao lo con - 7 unit tests cho ancestors API va timeline events API (71/71 passed) - flake8: 0 loi* (Tác giả: hoangducviet04012006-ux, Ngày: 2026-10-06T15:03:26Z)
- `9021d9aa` - *feat: add product and unit catalog models* (Tác giả: Chu Thao, Ngày: 2026-10-07T00:42:33Z)
- `95930d9e` - *fix: update models schemas and catalogs router* (Tác giả: Chu Thao, Ngày: 2026-10-07T01:54:52Z)
- `77b70d53` - *feat: add product unit catalog and harvest batch support* (Tác giả: Chu Thao, Ngày: 2026-10-07T04:51:52Z)
- `e1c2def5` - *feat: complete S-09 server validation for harvest batches* (Tác giả: Chu Thao, Ngày: 2026-10-07T06:00:53Z)
- `a3e67855` - *feat: hoan thanh giao dien va logic S-07 S-08 S-09* (Tác giả: Chu Thao, Ngày: 2026-10-07T06:56:38Z)
- `685234b5` - *feat: cap nhat frontend cho S-07 S-08 S-09* (Tác giả: Chu Thao, Ngày: 2026-10-07T06:57:47Z)

### Danh sách files thay đổi:
- `.flake8`: +13 / -0 (`added`)
- `.github/workflows/ci.yml`: +87 / -12 (`modified`)
- `backend/app/batch_tree.py`: +166 / -0 (`added`)
- `backend/app/database.py`: +248 / -25 (`modified`)
- `backend/app/events.py`: +189 / -0 (`added`)
- `backend/app/main.py`: +40 / -3 (`modified`)
- `backend/app/models.py`: +390 / -1 (`modified`)
- `backend/app/routers/audit.py`: +108 / -108 (`modified`)
- `backend/app/routers/auth.py`: +0 / -1 (`modified`)
- `backend/app/routers/batches.py`: +374 / -116 (`modified`)
- `backend/app/routers/catalogs.py`: +390 / -0 (`added`)
- `backend/app/routers/events.py`: +175 / -0 (`added`)
- `backend/app/routers/handovers.py`: +361 / -0 (`added`)
- `backend/app/routers/health.py`: +16 / -12 (`modified`)
- `backend/app/schemas.py`: +491 / -121 (`modified`)
- `backend/requirements.txt`: +2 / -2 (`modified`)
- `backend/tests/conftest.py`: +2 / -0 (`modified`)
- `backend/tests/test_audit_logs.py`: +0 / -3 (`modified`)
- `backend/tests/test_batch_ancestors.py`: +204 / -0 (`added`)
- `backend/tests/test_batch_detail.py`: +142 / -0 (`added`)
- `backend/tests/test_batch_events.py`: +234 / -0 (`added`)
- `backend/tests/test_batch_events_integrity.py`: +237 / -0 (`added`)
- `backend/tests/test_batch_tree.py`: +193 / -0 (`added`)
- `backend/tests/test_handovers.py`: +407 / -0 (`added`)
- `backend/tests/test_health.py`: +16 / -0 (`added`)
- `backend/tests/test_s09_validation.py`: +183 / -0 (`added`)
- `docs/CI_CD_AND_BRANCH_PROTECTION.md`: +102 / -0 (`added`)
- `docs/S11_S12_IMPLEMENTATION.md`: +172 / -0 (`added`)
- `frontend/css/style.css`: +450 / -0 (`modified`)
- `frontend/index.html`: +512 / -110 (`modified`)

---
