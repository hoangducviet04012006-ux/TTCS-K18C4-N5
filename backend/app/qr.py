import io
import qrcode
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Batch

router = APIRouter(prefix="/qr", tags=["QR Code"])

@router.get("/generate/{batch_id}")
def generate_batch_qr(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Không tìm thấy lô nông sản")

    # Đường dẫn trang truy xuất công khai
    trace_url = f"http://127.0.0.1:5500/frontend/trace.html?batch_id={batch_id}"

    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(trace_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return StreamingResponse(
        buf, 
        media_type="image/png", 
        headers={"Content-Disposition": f"attachment; filename=QR_Batch_{batch_id}.png"}
    )