# TÀI LIỆU TRIỂN KHAI S-48: TRANG CÔNG KHAI CHỈ TRẢ VỀ TRƯỜNG ĐƯỢC ĐÁNH DẤU CÔNG KHAI

> **Mã tài liệu:** S48-DOC  
> **Dự án:** Hệ thống Truy xuất Nguồn gốc & Giám sát Chuỗi Cung ứng Nông sản (TTCS - AgriTrace)  
> **User Story:** S-48 (Epic E-08: Trang truy xuất công khai quét QR)  
> **Trạng thái:** Đã hoàn thành 100% (Tất cả test cases kiểm thử tự động đạt chuẩn, flake8 0 lỗi)  

---

## 1. Tổng Quan Yêu Cầu Nghiệp Vụ (User Story S-48)

- **User Story:**
  > *"Là nhà phân phối tôi muốn trang công khai không lộ khối lượng, giá và tên đối tác của tôi để đối thủ không đọc được cấu trúc kinh doanh"*

- **Tiêu chuẩn nghiệm thu (Acceptance Criteria - AC):**
  1. **Danh sách trường công khai khai báo ở một chỗ duy nhất** (`backend/app/schemas_public.py`), áp dụng chính sách bảo mật **mặc định từ chối** (deny-by-default / whitelist): mọi trường không thuộc danh mục công khai đều bị xem là nội bộ và loại bỏ triệt để.
  2. **Gọi thẳng API công khai cũng không lấy được trường nội bộ**:
     - Tuyệt đối không lộ khối lượng (`quantity`, `initial_quantity`, `remaining_quantity`, `transferred_quantity`...).
     - Tuyệt đối không lộ giá cả, chi phí (`price`, `cost`, `unit_price`...).
     - Tuyệt đối không lộ ID cơ sở dữ liệu nội bộ (`id`, `batch_id`, `farm_id`, `plot_id`, `user_id`, `org_id`...).
     - Tuyệt đối không lộ diện tích thửa đất nội bộ (`plot_area`, `area`).
  3. **Ẩn danh đối tác thương mại trung gian theo loại hình**:
     - Tên tổ chức trung gian (vận chuyển, chế biến, phân phối) chỉ hiển thị theo loại đơn vị chung (ví dụ: *"Hợp tác xã nông nghiệp"*, *"Đơn vị vận chuyển"*, *"Nhà phân phối"*, *"Cơ sở sơ chế / chế biến"*, *"Điểm bán lẻ"*), tuyệt đối không để lộ tên riêng doanh nghiệp đối tác nhằm bảo vệ bí mật kinh doanh.
     - **Ngoại lệ:** Vùng trồng gốc được hiển thị tên trang trại và địa phương minh bạch cho người tiêu dùng (*"trừ vùng trồng"*).
  4. **Kiểm thử tự động so sánh phản hồi với danh sách cho phép (Whitelist Verification)**.

---

## 2. Kiến Trúc Triển Khai Kỹ Thuật

### 2.1. Khai Báo Tập Trung Danh Sách Trường Công Khai (`backend/app/schemas_public.py`)

Toàn bộ hợp đồng dữ liệu công khai được quản lý duy nhất tại tệp `backend/app/schemas_public.py`:

```python
# Danh mục trường công khai cấp cao nhất của lô
PUBLIC_BATCH_FIELDS: frozenset[str] = frozenset({
    "batch_code",
    "product_name",
    "harvest_date",
    "status",
    "origin",
    "root_batches",
    "milestones",
})

# Danh mục trường công khai cho thông tin xuất xứ
PUBLIC_ORIGIN_FIELDS: frozenset[str] = frozenset({
    "farm_name",
    "plot_name",
    "location",
})

# Danh mục trường công khai cho mỗi lô thu hoạch gốc (cho lô gộp nhiều nguồn)
PUBLIC_ROOT_BATCH_FIELDS: frozenset[str] = frozenset({
    "batch_code",
    "product_name",
    "harvest_date",
    "farm_name",
    "plot_name",
    "location",
})

# Danh mục trường công khai cho mỗi mốc hành trình chuỗi cung ứng
PUBLIC_MILESTONE_FIELDS: frozenset[str] = frozenset({
    "step",
    "stage",
    "organization_type",
    "timestamp",
    "status",
})
```

### 2.2. Cơ Chế Chặn Trường Lạ Cấp Độ ORM/Pydantic (`extra="forbid"`)

Tất cả Pydantic response models trong `schemas_public.py` đều được thiết lập:

```python
class PublicBatchTraceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ...
```

Bất kỳ nỗ lực chèn thêm trường dữ liệu nào nằm ngoài whitelist đều lập tức kích hoạt `pydantic.ValidationError` và bị chặn đứng từ tầng schema.

### 2.3. Dịch Vụ Chuẩn Hóa và Làm Sạch Dữ Liệu (`backend/app/services/public_trace.py`)

- **Hàm `get_public_batch_trace(batch_code: str, db: Session)`**:
  - Truy vấn thông tin lô từ SQLite.
  - Sử dụng thuật toán `trace_backwards` duyệt ngược đồ thị phả hệ, chỉ lấy thông tin nông sản gốc của các tổ tiên bậc 0 (root batches) mà không để lộ các tỷ lệ pha trộn hay khối lượng chuyển giao (`transferred_quantity`).
  - Tổng hợp các sự kiện lịch sử (`BatchEvent`) thành danh sách các mốc chuỗi cung ứng (`milestones`).
  - Hàm `get_public_organization_type` phân loại tự động tổ chức thành các nhóm:
    + Đơn vị vận chuyển chuỗi lạnh
    + Cơ sở sơ chế / chế biến
    + Nhà phân phối
    + Điểm bán lẻ
    + Hợp tác xã nông nghiệp

### 2.4. Endpoint API Công Khai (`backend/app/routers/public_trace.py`)

- **Route:** `GET /public/trace/{batch_code}`
- Không yêu cầu Header xác thực (`Authorization`) hoặc Session Cookie.
- Áp dụng `response_model=PublicBatchTraceResponse`.
- Khi mã lô không tồn tại: Trả về `HTTP 404 Not Found` với thông báo thân thiện, không rò rỉ bất kỳ chi tiết nội bộ nào của cơ sở dữ liệu.

### 2.5. Giao Diện Web Truy Xuất Nguồn Gốc (`frontend/trace.html` & `frontend/js/trace.js`)

- Thiết kế nhẹ, tối ưu tải nhanh trên thiết bị di động khi người tiêu dùng quét mã QR.
- Hiển thị đầy đủ:
  + Thẻ xác nhận đạt chuẩn bảo mật dữ liệu công khai S-48.
  + Thông tin lô hàng (mã lô, tên nông sản, ngày thu hoạch, trạng thái).
  + Xuất xứ vùng trồng / thửa đất.
  + Danh sách các vùng trồng gốc (đối với lô gộp).
  + Hành trình chuỗi cung ứng theo từng bước kèm loại hình đơn vị thực hiện.
- Hoàn toàn không hiển thị hay gửi yêu cầu tới bất kỳ trường khối lượng hay thông tin kinh doanh nhạy cảm nào.

---

## 3. Bảng Đối Chiếu Dữ Liệu (Công Khai vs. Nội Bộ)

| Nhóm dữ liệu | Trường dữ liệu | Trạng thái theo S-48 | Lý do bảo vệ |
| :--- | :--- | :---: | :--- |
| **Khối lượng** | `quantity`, `remaining_quantity`, `initial_quantity` | ❌ **Bị loại bỏ 100%** | Ngăn đối thủ cạnh tranh đọc quy mô sản xuất và năng lực tồn kho |
| **Giá cả** | `price`, `cost`, `unit_price` | ❌ **Bị loại bỏ 100%** | Bảo mật bí mật định giá và cơ cấu chiết khấu thương mại |
| **Đối tác trung gian** | Tên riêng doanh nghiệp vận tải, tổng kho | ❌ **Ẩn danh thành loại hình** | Thay bằng *"Đơn vị vận chuyển"*, *"Nhà phân phối"* để bảo vệ quan hệ đối tác |
| **Vùng trồng gốc** | Tên trang trại, thửa đất, tỉnh thành | ✅ **Hiển thị công khai** | Minh bạch xuất xứ phục vụ người tiêu dùng quét mã QR (*"trừ vùng trồng"*) |
| **Khóa DB** | `id`, `batch_id`, `farm_id`, `plot_id`, `user_id` | ❌ **Bị loại bỏ 100%** | Phòng ngừa tấn công ID enumeration và tấn công dò quét SQL |
| **Mã công khai** | `batch_code` | ✅ **Hiển thị công khai** | Mã định danh duy nhất in trên tem QR bao bì sản phẩm |

---

## 4. Kiểm Thử Tự Động (Automated Test Suite)

Tệp kiểm thử tự động: [`backend/tests/test_public_trace_s48.py`](../backend/tests/test_public_trace_s48.py) bao phủ toàn diện 6 ca kiểm thử độc lập:

1. `test_public_trace_fields_strictly_match_allowed_whitelist`: Kiểm tra so sánh phản hồi JSON thực tế với danh sách cho phép (whitelist).
2. `test_direct_api_call_never_exposes_internal_sensitive_fields`: Quét đệ quy toàn bộ JSON response bảo đảm không chứa bất kỳ trường nào trong `INTERNAL_SENSITIVE_FIELDS`.
3. `test_intermediate_organizations_masked_to_type_not_private_name`: Xác nhận tên riêng các đơn vị vận tải và phân phối được ẩn danh, trong khi vùng trồng gốc vẫn hiển thị minh bạch.
4. `test_multi_source_merged_batch_returns_only_public_fields_for_all_roots`: Lô gộp từ nhiều nguồn hiển thị đúng mọi vùng trồng gốc nhưng không để lộ khối lượng pha trộn.
5. `test_public_endpoint_unauthenticated_and_404_no_data_leak`: Gọi không cần đăng nhập thành công; mã không tồn tại trả về 404 sạch không lộ dấu vết DB.
6. `test_pydantic_schema_extra_forbid_strictly_enforces_whitelist`: Xác nhận Pydantic ném lỗi `ValidationError` khi cố ý chèn thêm trường nội bộ.

---

## 5. Kết Quả Nghiệm Thu

```bash
backend/tests/test_public_trace_s48.py::test_public_trace_fields_strictly_match_allowed_whitelist PASSED
backend/tests/test_public_trace_s48.py::test_direct_api_call_never_exposes_internal_sensitive_fields PASSED
backend/tests/test_public_trace_s48.py::test_intermediate_organizations_masked_to_type_not_private_name PASSED
backend/tests/test_public_trace_s48.py::test_multi_source_merged_batch_returns_only_public_fields_for_all_roots PASSED
backend/tests/test_public_trace_s48.py::test_public_endpoint_unauthenticated_and_404_no_data_leak PASSED
backend/tests/test_public_trace_s48.py::test_pydantic_schema_extra_forbid_strictly_enforces_whitelist PASSED
============================== 6 passed in 4.04s ==============================
```

- **Kiểm tra Lint (`flake8 backend/app backend/tests/test_public_trace_s48.py`)**: 0 lỗi vi phạm chuẩn mã nguồn.
