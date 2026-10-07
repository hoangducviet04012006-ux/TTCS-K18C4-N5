# TÀI LIỆU TRIỂN KHAI S-11 & S-12: EVENT LOGGING APPEND-ONLY & KIỂM TRA TOÀN VẸN CHUỖI SỰ KIỆN (CRYPTOGRAPHIC HASH CHAIN)

> **Mã tài liệu:** S11-S12-DOC  
> **Dự án:** Hệ thống Truy xuất nguồn gốc và Giám sát Chuỗi lạnh Nông sản (TTCS)  
> **Ngày triển khai:** 2026-10-06  
> **Trạng thái:** Đã hoàn thành 100% (48/48 unit & integration tests passed)  

---

## 1. Tổng Quan Triển Khai

Tài liệu này ghi nhận chi tiết việc triển khai hai yêu cầu kỹ thuật quan trọng của hệ thống:
- **S-11: Không đường nào trong ứng dụng có thể sửa hoặc xoá sự kiện đã ghi.**
- **S-12: Kiểm tra toàn vẹn chuỗi sự kiện của một lô và chỉ ra chính xác chỗ đứt mạch.**

---

## 2. Sprint S-11: Cơ Chế Sự Kiện Lô Nông Sản Append-Only

### 2.1 Cấu trúc Bảng `batch_events`

Bảng `batch_events` được tự động khởi tạo khi ứng dụng khởi chạy (`init_db()`), tối thiểu gồm 7 cột:

```sql
CREATE TABLE IF NOT EXISTS batch_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    event_type VARCHAR(100) NOT NULL,
    event_data VARCHAR(2000) NULL,
    created_at DATETIME NOT NULL,
    prev_hash VARCHAR(64) NOT NULL,
    record_hash VARCHAR(64) NOT NULL
);
```

### 2.2 Bảo Vệ Đa Lớp Ngăn Ngừa UPDATE & DELETE

Hệ thống triển khai cơ chế bảo vệ 3 tầng chống chỉnh sửa và xóa dữ liệu:

1. **Tầng Database Engine (Database Triggers)**:
   Khi ứng dụng khởi động, backend khởi tạo 2 Triggers trực tiếp trong cơ sở dữ liệu:
   ```sql
   CREATE TRIGGER IF NOT EXISTS prevent_batch_events_update
   BEFORE UPDATE ON batch_events
   BEGIN
       SELECT RAISE(ABORT, 'S-11: Updates to batch_events table are strictly prohibited (append-only log).');
   END;

   CREATE TRIGGER IF NOT EXISTS prevent_batch_events_delete
   BEFORE DELETE ON batch_events
   BEGIN
       SELECT RAISE(ABORT, 'S-11: Deletions from batch_events table are strictly prohibited (append-only log).');
   END;
   ```
   *Bất kỳ câu lệnh SQL thô nào (`UPDATE batch_events...` hoặc `DELETE FROM batch_events...`) đều bị DB Engine abort ngay lập tức.*

2. **Tầng ORM Level (SQLAlchemy Event Listeners)**:
   Trên model `BatchEvent` trong `app/models.py`, hai listener `before_update` và `before_delete` được gắn trực tiếp:
   ```python
   @event.listens_for(BatchEvent, "before_update")
   def _prevent_batch_event_update(mapper, connection, target):
       raise PermissionError("S-11: Batch events are append-only and cannot be updated.")

   @event.listens_for(BatchEvent, "before_delete")
   def _prevent_batch_event_delete(mapper, connection, target):
       raise PermissionError("S-11: Batch events are append-only and cannot be deleted.")
   ```

3. **Tầng Backend REST API**:
   - Chỉ cung cấp 2 nhóm route:
     - `POST /batches/{batch_id}/events` (Ghi sự kiện mới)
     - `GET /batches/{batch_id}/events`, `GET /events`, `GET /events/{event_id}` (Truy vấn đọc sự kiện)
   - Hoàn toàn **không** tồn tại bất kỳ endpoint `PUT`, `PATCH` hay `DELETE` nào. Mọi request gọi `PUT /events/{id}` hay `DELETE /events/{id}` đều nhận về `HTTP 404` / `HTTP 405`.

---

## 3. Sprint S-12: Kiểm Tra Toàn Vẹn Chuỗi Sự Kiện (Hash Chain Verification)

### 3.1 Quy Tắc Hash Chain

1. **Sự kiện Genesis (index = 0)**:
   $$\text{prev\_hash} = \text{"0"}\times 64$$
2. **Sự kiện tiếp theo (index $i \ge 1$)**:
   $$\text{prev\_hash}_i = \text{record\_hash}_{i-1}$$
3. **Mã băm bản ghi (`record_hash`)**:
   $$\text{record\_hash}_i = \text{SHA256}\left(\text{batch\_id} \mathbin{\Vert} \text{event\_type} \mathbin{\Vert} \text{event\_data} \mathbin{\Vert} \text{created\_at\_iso} \mathbin{\Vert} \text{prev\_hash}_i\right)$$

### 3.2 Thuật Toán Xác Định Chính Xác Vị Trí Đứt Mạch

Hàm `verify_batch_events_integrity(db, batch_id)` duyệt qua toàn bộ sự kiện của lô theo thứ tự tăng dần (`id` ASC):

1. **Kiểm tra liên kết `prev_hash` (Phát hiện event bị XÓA hoặc `prev_hash` bị sửa)**:
   - Với index $i = 0$: Kiểm tra `prev_hash == "0"*64`.
   - Với index $i \ge 1$: So sánh `event[i].prev_hash` với `event[i-1].record_hash`. Nếu không khớp $\rightarrow$ Báo lỗi `PREV_HASH_MISMATCH` ngay tại `event[i]` với `index = i`.
2. **Kiểm tra tính toán lại `record_hash` (Phát hiện `event_data`, `event_type` hoặc `record_hash` bị SỬA)**:
   - Tính toán lại mã băm $\text{computed\_hash}$ từ thông tin thực tế của `event[i]`.
   - So sánh $\text{computed\_hash}$ với `event[i].record_hash` trong DB.
   - Nếu không khớp $\rightarrow$ Báo lỗi `RECORD_HASH_MISMATCH` tại `event[i]` với `index = i`, `expected_hash` = $\text{computed\_hash}$, `actual_hash` = `event[i].record_hash`.
3. **Dừng kiểm tra tức thì khi gặp lỗi đầu tiên** để chỉ ra chính xác điểm đứt mạch đầu tiên.

### 3.3 API Endpoint Integrity Check

- **URL**: `GET /batches/{batch_id}/integrity`
- **Phản hồi khi hợp lệ (`valid: true`)**:
  ```json
  {
    "valid": true,
    "batch_id": 1,
    "total_events": 4,
    "message": "Toàn bộ 4 sự kiện của lô #1 đều hợp lệ và đảm bảo tính toàn vẹn dữ liệu."
  }
  ```
- **Phản hồi khi không hợp lệ (`valid: false`)**:
  ```json
  {
    "valid": false,
    "batch_id": 1,
    "event_id": 3,
    "index": 1,
    "error_type": "RECORD_HASH_MISMATCH",
    "expected_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "actual_hash": "a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e",
    "message": "Dữ liệu sự kiện tại vị trí index 1 (Event ID #3) đã bị chỉnh sửa hoặc giả mạo..."
  }
  ```

---

## 4. Giao Diện Người Dùng (Frontend UI)

Đã bổ sung Card **Kiểm tra toàn vẹn chuỗi sự kiện (Cryptographic Hash Chain)** trong giao diện web (`frontend/index.html` & `frontend/js/app.js`):
- Cho phép chọn từ danh sách dropdown các Lô nông sản hoặc nhập trực tiếp Mã ID Lô.
- Nút bấm **Kiểm tra toàn vẹn chuỗi** gọi API `GET /batches/{batch_id}/integrity`.
- Hiển thị thông báo trạng thái:
  - Bảng màu xanh lục nếu chuỗi hợp lệ.
  - Bảng màu đỏ cảnh báo nếu phát hiện đứt mạch, chỉ rõ **Mã sự kiện bị đứt mạch**, **Index**, **Loại lỗi**, **Expected Hash**, **Actual Hash** và thông điệp giải thích.

---

## 5. Danh Sách File Đã Cập Nhật

1. `backend/app/models.py`: Khai báo `BatchEvent` model và ORM immutability listeners.
2. `backend/app/database.py`: Thêm DB Triggers (`BEFORE UPDATE`, `BEFORE DELETE`) trên `batch_events`.
3. `backend/app/events.py`: Logic append-only event logging & Hash Chain integrity verification.
4. `backend/app/schemas.py`: Thêm `BatchEventCreate`, `BatchEventResponse`, `BatchIntegrityResponse`.
5. `backend/app/routers/events.py`: Các API endpoint cho Batch Events & Integrity Check.
6. `backend/app/routers/batches.py`: Tự động ghi event khi tạo mới hoặc sửa lô.
7. `backend/app/main.py`: Đăng ký `events.router`.
8. `frontend/index.html`: Thêm giao diện kiểm tra toàn vẹn chuỗi sự kiện.
9. `frontend/js/app.js`: Tích hợp hàm kiểm tra toàn vẹn và render kết quả lên UI.
10. `backend/tests/test_batch_events.py`: Unit test cho S-11 (Append-only & DB permissions).
11. `backend/tests/test_batch_events_integrity.py`: Unit test cho S-12 (Integrity check & Tamper detection).
12. `backend/tests/conftest.py`: Cập nhật in-memory SQLite test engine hỗ trợ DB Triggers.

---

## 6. Kết Quả Chạy Kiểm Thử (48/48 Passed)

```text
============================= test session starts =============================
platform win32 -- Python 3.10.9, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\Dell 9370\Downloads\TTCS-K18C4-N5-main\TTCS-K18C4-N5-main

tests\test_audit_logs.py ................................              [ 33%]
tests\test_batch_events.py ......                                      [ 45%]
tests\test_batch_events_integrity.py ....                              [ 54%]
tests\test_database_migration.py ....                                  [ 62%]
tests\test_login_lockout.py .........                                  [ 81%]
tests\test_organization_isolation.py .........                        [100%]

============================= 48 passed in 19.51s =============================
```
