"""Pydantic schemas cho Story S-50: Kiểm tra tính toàn vẹn dữ liệu truy xuất."""

from typing import Any, Optional
from pydantic import BaseModel, Field


class TraceNodeIntegrity(BaseModel):
    """Kết quả thẩm định tính toàn vẹn của một mắt xích (lô nông sản) trong phả hệ."""

    batch_id: int = Field(..., description="ID lô nông sản.")
    code: str = Field(..., description="Mã lô nông sản.")
    level: int = Field(0, description="Cấp bậc phả hệ tính từ lô đích (0 là lô đích, 1 là cha, 2 là ông...).")
    product_name: Optional[str] = Field(None, description="Tên nông sản.")
    current_org_id: Optional[int] = Field(None, description="ID tổ chức đang nắm giữ.")
    current_org_name: Optional[str] = Field(None, description="Tên tổ chức đang nắm giữ.")
    total_events: int = Field(0, description="Tổng số sự kiện trong chuỗi băm của lô.")
    is_valid: bool = Field(..., description="Trạng thái toàn vẹn của chuỗi băm lô này.")
    status: str = Field(..., description="Mã trạng thái thẩm định ('VERIFIED', 'TAMPERED', 'CHAIN_BROKEN', 'NO_EVENTS').")
    latest_hash: Optional[str] = Field(None, description="Mã băm SHA-256 của sự kiện mới nhất trong lô.")
    genesis_hash: Optional[str] = Field(None, description="Mã băm khởi nguyên của lô.")
    error_type: Optional[str] = Field(None, description="Mã lỗi nếu phát hiện vi phạm toàn vẹn.")
    tampered_event_id: Optional[int] = Field(None, description="ID sự kiện bị can thiệp nếu có.")
    message: Optional[str] = Field(None, description="Mô tả kết quả thẩm định.")


class TraceabilityIntegrityResponse(BaseModel):
    """Schema phản hồi toàn diện cho việc kiểm tra toàn vẹn chuỗi truy xuất nguồn gốc."""

    is_valid: bool = Field(..., description="Toàn bộ chuỗi truy xuất nguồn gốc có nguyên vẹn và hợp lệ không.")
    valid: bool = Field(..., description="Alias tương thích ngược của is_valid.")
    batch_id: int = Field(..., description="ID của lô nông sản đích.")
    batch_code: str = Field(..., description="Mã của lô nông sản đích.")
    status: str = Field(..., description="Trạng thái tổng thể ('VERIFIED', 'TAMPERED', 'CHAIN_BROKEN', 'NO_EVENTS').")
    total_batches_checked: int = Field(..., description="Tổng số lô nông sản trong phả hệ đã thẩm định.")
    total_events_checked: int = Field(..., description="Tổng số sự kiện mật mã đã xác thực xuyên suốt chuỗi.")
    root_hashes: list[str] = Field(default_factory=list, description="Danh sách mã băm của các lô thu hoạch gốc.")
    latest_hash: Optional[str] = Field(None, description="Mã băm của sự kiện mới nhất tại lô đích.")
    verification_seal: str = Field(..., description="Con dấu mật mã SHA-256 niêm phong kết quả thẩm định.")
    verified_at: str = Field(..., description="Mốc thời gian thẩm định chuẩn ISO 8601 UTC.")
    message: str = Field(..., description="Thông điệp kết luận thẩm định cho người dùng.")
    nodes: list[TraceNodeIntegrity] = Field(
        default_factory=list, description="Danh sách chi tiết kết quả thẩm định từng mắt xích."
    )
    tampered_node: Optional[dict[str, Any]] = Field(
        None, description="Chi tiết mắt xích đầu tiên bị can thiệp nếu phát hiện vi phạm."
    )
