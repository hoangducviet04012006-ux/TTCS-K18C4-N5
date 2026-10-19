"""Tạo ảnh QR PNG có thể in cho mã lô thật (S-46)."""

from io import BytesIO

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Batch, User
from app.security import get_current_user
from app.services.permissions import can_view_batch

router = APIRouter(tags=["Batch QR"])


@router.get(
    "/batches/{batch_id}/qr",
    summary="Tải mã QR của lô dưới dạng PNG (S-46)",
    responses={
        200: {"content": {"image/png": {}}, "description": "Ảnh QR PNG của mã lô."},
        401: {"description": "Chưa đăng nhập."},
        403: {"description": "Không có quyền xem lô."},
        404: {"description": "Không tìm thấy lô."},
    },
)
def download_batch_qr(
    batch_id: int = Path(..., ge=1, description="ID nội bộ dùng để tra cứu lô."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Chỉ trả QR sau khi xác thực và kiểm tra quyền truy cập lô."""
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )
    if not can_view_batch(
        db, current_user.organization_id, batch_id, user_role=current_user.role
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền tải mã QR của lô nông sản này.",
        )
    if not batch.code or not batch.code.strip():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lô nông sản chưa có mã lô hợp lệ để tạo QR.",
        )

    image = qrcode.make(batch.code.strip())
    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    safe_code = "".join(ch for ch in batch.code if ch.isalnum() or ch in "-_")
    return StreamingResponse(
        output,
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="QR-{safe_code}.png"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
