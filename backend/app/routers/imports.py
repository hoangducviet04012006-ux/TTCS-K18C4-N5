from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.security import get_current_user
from app.services.csv_import import import_csv
from app.services.rbac import check_action_permission

router = APIRouter(prefix="/catalogs", tags=["CSV"])


@router.post("/import-csv")
async def upload_csv(
    entity_type: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_action_permission(user, "PRODUCT_CREATE" if entity_type == "product" else "FARM_MANAGE")
    raw = await file.read(2 * 1024 * 1024 + 1)
    return import_csv(db, user, entity_type, raw)


@router.get("/template/{entity_type}")
def template(entity_type: str, user: User = Depends(get_current_user)):
    from fastapi import HTTPException

    if entity_type not in ("product", "plot"):
        raise HTTPException(422, "Loại dữ liệu không hợp lệ.")
    check_action_permission(user, "PRODUCT_CREATE" if entity_type == "product" else "FARM_MANAGE")
    content = (
        "name,unit\nChè mẫu QA Tân Cương,kg\n"
        if entity_type == "product"
        else "name,location,area,owner,coordinates\nThửa mẫu QA Tân Cương,Thái Nguyên,1.5,HTX mẫu QA,\n"
    )
    return Response(
        content.encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{entity_type}-template.csv"'},
    )
