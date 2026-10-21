"""Khai báo tập trung danh sách trường công khai và schema bảo vệ dữ liệu (Story S-48).

Tiêu chuẩn S-48:
- Danh sách trường công khai được khai báo tập trung ở MỘT NƠI DUY NHẤT.
- Mặc định mọi trường là nội bộ (deny-by-default, whitelist).
- Gọi trực tiếp API công khai không thể lấy được bất kỳ trường nội bộ nào:
  + Tuyệt đối KHÔNG để lộ khối lượng (quantity, remaining_quantity, initial_quantity, v.v.).
  + Tuyệt đối KHÔNG để lộ giá cả / chi phí (price, cost).
  + Tuyệt đối KHÔNG để lộ tên riêng của các đối tác thương mại trung gian (from_org_name, to_org_name).
    Tên tổ chức trung gian chỉ hiển thị theo loại đơn vị (Hợp tác xã, Đơn vị vận chuyển, Nhà phân phối...).
  + Ngoại lệ: Vùng trồng gốc được phép hiển thị tên trang trại và địa phương để minh bạch xuất xứ ("trừ vùng trồng").
  + Tuyệt đối KHÔNG để lộ ID database nội bộ (id, batch_id, farm_id, plot_id, user_id, org_id...).
"""

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


# ==============================================================================
# 1. KHAI BÁO TẬP TRUNG DANH SÁCH TRƯỜNG CÔNG KHAI (WHITELIST - SINGLE SOURCE OF TRUTH)
# ==============================================================================

# Danh sách trường được phép trả về ở cấp cao nhất của thông tin lô công khai
PUBLIC_BATCH_FIELDS: frozenset[str] = frozenset({
    "batch_code",
    "product_name",
    "harvest_date",
    "status",
    "origin",
    "root_batches",
    "milestones",
    "recall_warning",
    "recall_message",
})

# Danh sách trường công khai của thông tin xuất xứ / vùng trồng gốc
PUBLIC_ORIGIN_FIELDS: frozenset[str] = frozenset({
    "farm_name",
    "plot_name",
    "location",
})

# Danh sách trường công khai của mỗi lô nguồn gốc (trong trường hợp lô gộp nhiều nguồn)
PUBLIC_ROOT_BATCH_FIELDS: frozenset[str] = frozenset({
    "batch_code",
    "product_name",
    "harvest_date",
    "farm_name",
    "plot_name",
    "location",
})

# Danh sách trường công khai của mỗi mốc hành trình chuỗi cung ứng
PUBLIC_MILESTONE_FIELDS: frozenset[str] = frozenset({
    "step",
    "stage",
    "organization_type",
    "timestamp",
    "status",
})

# Danh mục các trường dữ liệu nội bộ / nhạy cảm TUYỆT ĐỐI CẤM rò rỉ ra ngoài trang công khai
INTERNAL_SENSITIVE_FIELDS: frozenset[str] = frozenset({
    # Khối lượng & định lượng nội bộ
    "quantity",
    "initial_quantity",
    "remaining_quantity",
    "transferred_quantity",
    "total_quantity",
    "total_split_quantity",
    "quantity_taken",
    "weight",
    # Giá cả & chi phí thương mại
    "price",
    "cost",
    "unit_price",
    "total_amount",
    # Tên riêng đối tác thương mại trung gian (S-48 bảo mật cấu trúc kinh doanh)
    "from_org_name",
    "to_org_name",
    "current_org_name",
    "partner_name",
    "owner",
    # Khóa chính & ID cơ sở dữ liệu nội bộ
    "id",
    "batch_id",
    "farm_id",
    "plot_id",
    "user_id",
    "organization_id",
    "current_org_id",
    "from_org_id",
    "to_org_id",
    "location_id",
    "tampered_event_id",
    "parent_id",
    "parent_batch_id",
    "child_batch_ids",
    # Diện tích thửa đất nội bộ
    "plot_area",
    "area",
})


# ==============================================================================
# 2. PYDANTIC SCHEMAS CHO DỮ LIỆU CÔNG KHAI (CHẶN MỌI TRƯỜNG LẠ VỚI extra="forbid")
# ==============================================================================

class PublicOriginInfo(BaseModel):
    """Thông tin xuất xứ vùng trồng công khai."""

    model_config = ConfigDict(extra="forbid")

    farm_name: str | None = Field(None, description="Tên trang trại / vùng trồng nông sản.")
    plot_name: str | None = Field(None, description="Tên thửa đất canh tác.")
    location: str | None = Field(None, description="Địa phương / tỉnh thành nơi canh tác.")


class PublicRootBatchInfo(BaseModel):
    """Thông tin lô thu hoạch gốc phục vụ truy xuất đa nguồn."""

    model_config = ConfigDict(extra="forbid")

    batch_code: str = Field(..., description="Mã định danh lô thu hoạch gốc.")
    product_name: str = Field(..., description="Tên nông sản thu hoạch.")
    harvest_date: str | None = Field(None, description="Ngày thu hoạch (YYYY-MM-DD).")
    farm_name: str | None = Field(None, description="Tên trang trại / vùng trồng.")
    plot_name: str | None = Field(None, description="Tên thửa canh tác.")
    location: str | None = Field(None, description="Địa phương nơi thu hoạch.")


class PublicMilestoneInfo(BaseModel):
    """Một mốc sự kiện trong hành trình chuỗi cung ứng công khai."""

    model_config = ConfigDict(extra="forbid")

    step: int = Field(..., ge=1, description="Thứ tự công đoạn trong hành trình.")
    stage: str = Field(..., description="Tên công đoạn (Thu hoạch, Sơ chế, Vận chuyển, Phân phối...).")
    organization_type: str = Field(
        ...,
        description="Loại đơn vị thực hiện (Hợp tác xã, Đơn vị vận chuyển, Nhà phân phối...).",
    )
    timestamp: str | None = Field(None, description="Thời điểm ghi nhận mốc hành trình.")
    status: str | None = Field(None, description="Trạng thái hoàn thành của mốc.")


class PublicBatchTraceResponse(BaseModel):
    """Hợp đồng dữ liệu phản hồi công khai của lô nông sản quét mã QR (Story S-48).

    Bảo đảm tuân thủ 100% nguyên tắc:
    - Mọi trường không thuộc danh mục công khai đều bị từ chối (extra="forbid").
    - Không chứa bất kỳ thông tin nhạy cảm về khối lượng, giá hay tên riêng đối tác.
    """

    model_config = ConfigDict(extra="forbid")

    batch_code: str = Field(..., description="Mã công khai của lô nông sản.")
    product_name: str = Field(..., description="Tên loại nông sản.")
    harvest_date: str | None = Field(None, description="Ngày thu hoạch nông sản.")
    status: str = Field(..., description="Trạng thái công khai của lô nông sản.")
    recall_warning: bool = False
    recall_message: str = "Không ghi nhận cảnh báo thu hồi"
    origin: PublicOriginInfo = Field(..., description="Thông tin xuất xứ vùng trồng.")
    root_batches: list[PublicRootBatchInfo] = Field(
        default_factory=list,
        description="Danh sách các lô thu hoạch gốc của nông sản.",
    )
    milestones: list[PublicMilestoneInfo] = Field(
        default_factory=list,
        description="Hành trình các công đoạn chính của chuỗi cung ứng.",
    )


# ==============================================================================
# 3. TIỆN ÍCH LỌC VÀ CHUYỂN ĐỔI THEO CHUẨN S-48 (ANONYMIZATION & DATA SANITIZATION)
# ==============================================================================

def get_public_organization_type(org_name: str | None, role: str | None = None) -> str:
    """Chuyển đổi tên tổ chức riêng tư thành loại hình tổ chức chung theo S-48.

    Quy định S-48: Tên tổ chức trung gian hiển thị theo loại (hợp tác xã, đơn vị vận chuyển,
    nhà phân phối, cơ sở sơ chế) chứ không hiển thị tên riêng doanh nghiệp, nhằm bảo vệ
    cấu trúc kinh doanh và chống đối thủ đọc quan hệ đối tác.
    """
    if role:
        role_lower = role.lower()
        if "transporter" in role_lower:
            return "Đơn vị vận chuyển"
        if "processor" in role_lower:
            return "Cơ sở sơ chế / chế biến"
        if "distributor" in role_lower:
            return "Nhà phân phối"
        if "farmer" in role_lower:
            return "Hợp tác xã nông nghiệp"

    if not org_name:
        return "Đơn vị cung ứng"

    name_lower = org_name.lower()
    if any(k in name_lower for k in ("vận chuyển", "logistics", "xe", "giao vận", "transporter")):
        return "Đơn vị vận chuyển"
    if any(k in name_lower for k in ("sơ chế", "chế biến", "đóng gói", "nhà máy", "xưởng", "processor")):
        return "Cơ sở sơ chế / chế biến"
    if any(k in name_lower for k in ("phân phối", "distributor", "tổng kho", "đại lý sỉ")):
        return "Nhà phân phối"
    if any(k in name_lower for k in ("cửa hàng", "siêu thị", "bán lẻ", "retail", "mart")):
        return "Điểm bán lẻ"
    if any(k in name_lower for k in ("hợp tác xã", "htx", "nông dân", "vùng trồng", "nông nghiệp", "farmer")):
        return "Hợp tác xã nông nghiệp"

    return "Đơn vị liên kết chuỗi cung ứng"


def filter_public_dict(raw: dict[str, Any], allowed_keys: frozenset[str]) -> dict[str, Any]:
    """Hàm lọc dictionary theo whitelist (mặc định loại bỏ mọi trường không thuộc allowed_keys)."""
    return {k: v for k, v in raw.items() if k in allowed_keys}
