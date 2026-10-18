from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from datetime import datetime
from pydantic import BaseModel
from app.database import get_db
from app.models import TemperatureLog

router = APIRouter(prefix="/temperature", tags=["Temperature"])

class TemperatureCreate(BaseModel):
    trip_id: int
    temperature: float
    recorded_at: datetime

@router.post("/log", status_code=status.HTTP_201_CREATED)
def log_temperature(data: TemperatureCreate, db: Session = Depends(get_db)):
    # Lấy bản ghi nhiệt độ mới nhất của chuyến hàng
    latest_log = db.query(TemperatureLog)\
        .filter(TemperatureLog.trip_id == data.trip_id)\
        .order_by(TemperatureLog.recorded_at.desc())\
        .first()

    # Bỏ qua nếu thời gian nhỏ hơn hoặc bằng bản ghi mới nhất (trùng hoặc cũ hơn)
    if latest_log and data.recorded_at <= latest_log.recorded_at:
        return {
            "status": "ignored",
            "message": "Số đo cũ hoặc trùng mốc thời gian. Bỏ qua ghi nhận.",
            "latest_recorded_at": latest_log.recorded_at
        }

    # Lưu bản ghi hợp lệ
    new_log = TemperatureLog(
        trip_id=data.trip_id,
        temperature=data.temperature,
        recorded_at=data.recorded_at
    )
    db.add(new_log)
    db.commit()
    db.refresh(new_log)

    return {
        "status": "success",
        "message": "Ghi nhận nhiệt độ thành công",
        "data": new_log
    }