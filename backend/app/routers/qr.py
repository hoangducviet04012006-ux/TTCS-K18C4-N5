"""Authenticated QR preview/download for a batch (S-46)."""
from io import BytesIO
import os
from urllib.parse import quote

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Batch, User
from app.security import get_current_user
from app.services.permissions import can_view_batch

router = APIRouter(tags=["Batch QR"])


def _trace_url(batch_code: str) -> str:
    base = os.getenv("PUBLIC_TRACE_BASE_URL", "").strip().rstrip("/")
    if not base:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chưa cấu hình PUBLIC_TRACE_BASE_URL cho trang truy xuất công khai.",
        )
    if not base.startswith(("https://", "http://")):
        raise HTTPException(status_code=500, detail="PUBLIC_TRACE_BASE_URL phải là URL HTTP(S) hợp lệ.")
    return f"{base}/{quote(batch_code.strip(), safe='-_')}"


def _authorized_batch(batch_id: int, current_user: User, db: Session) -> Batch:
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy lô nông sản.")
    if not can_view_batch(db, current_user.organization_id, batch_id, user_role=current_user.role):
        raise HTTPException(status_code=403, detail="Bạn không có quyền xem mã QR của lô này.")
    if not batch.code or not batch.code.strip():
        raise HTTPException(status_code=409, detail="Lô nông sản chưa có mã lô hợp lệ.")
    return batch


@router.get("/batches/{batch_id}/qr-info", summary="Thông tin QR truy xuất nguồn gốc")
def batch_qr_info(
    batch_id: int = Path(..., ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch = _authorized_batch(batch_id, current_user, db)
    return {
        "batch_code": batch.code.strip(),
        "product_name": batch.product_name or (batch.product.name if batch.product else "Nông sản"),
        "trace_url": _trace_url(batch.code),
    }


@router.get(
    "/batches/{batch_id}/qr",
    summary="Xem hoặc tải ảnh QR truy xuất nguồn gốc (PNG)",
    responses={200: {"content": {"image/png": {}}}, 401: {"description": "Chưa đăng nhập."},
               403: {"description": "Không có quyền xem lô."}, 404: {"description": "Không tìm thấy lô."}},
)
def download_batch_qr(
    batch_id: int = Path(..., ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    batch = _authorized_batch(batch_id, current_user, db)
    trace_url = _trace_url(batch.code)
    image = qrcode.make(trace_url, box_size=10, border=4)
    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    safe_code = "".join(ch for ch in batch.code if ch.isalnum() or ch in "-_")
    return StreamingResponse(
        output, media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="QR-{safe_code}.png"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
