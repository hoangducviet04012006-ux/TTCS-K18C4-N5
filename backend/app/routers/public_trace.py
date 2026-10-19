"""Public read-only trace data for QR landing pages."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import Batch
from app.services.traceability import trace_backwards

router = APIRouter(tags=["Public Traceability"])

@router.get("/public/trace/{batch_code}", summary="Thông tin truy xuất công khai theo mã lô")
def public_trace_by_code(batch_code: str, db: Session = Depends(get_db)):
    batch = (
        db.query(Batch)
        .options(joinedload(Batch.product), joinedload(Batch.plot), joinedload(Batch.farm))
        .filter(Batch.code == batch_code)
        .first()
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy lô nông sản.")
    lineage = trace_backwards(db, batch.id)
    roots = []
    for nodes in lineage.get("ancestors_by_level", {}).values():
        for node in nodes:
            if not node.get("has_parents", False):
                roots.append({
                    "batch_code": node.get("code"),
                    "product_name": node.get("product_name"),
                    "harvest_date": node.get("harvest_date"),
                    "location": node.get("location"),
                    "farm_name": node.get("farm_name"),
                    "plot_name": node.get("plot_name"),
                })
    plot, farm = batch.plot, batch.farm
    return {
        "batch_code": batch.code,
        "product_name": batch.product_name or (batch.product.name if batch.product else "Nông sản"),
        "harvest_date": str(batch.harvest_date) if batch.harvest_date else None,
        "status": batch.status,
        "origin": {
            "location": (plot.location if plot else None) or (farm.location if farm else None),
            "farm_name": (farm.name if farm else None) or (plot.name if plot else None),
            "plot_name": plot.name if plot else None,
            "plot_area": float(plot.area) if plot and plot.area is not None else None,
        },
        "root_batches": roots,
    }
