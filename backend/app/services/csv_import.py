"""S-32 atomic UTF-8 CSV import; permissions match manual CRUD."""

import csv
import io
import math
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, func
from app.models import Product, Farm, Plot, ACTION_CREATE, ENTITY_FARM
from app.schemas import ProductCreate, FarmCreate
from app.services.rbac import check_action_permission
from app.services.recall_database import acquire_write_lock
from app.audit import record_action


def norm(value):
    return str(value or "").strip().casefold()


def import_csv(db, user, entity, raw):  # noqa: C901 - atomic validation before any insert
    if entity not in ("product", "plot"):
        raise HTTPException(422, "Loại dữ liệu CSV không hợp lệ.")
    check_action_permission(user, "PRODUCT_CREATE" if entity == "product" else "FARM_MANAGE")
    if entity == "plot" and user.organization_id is None:
        raise HTTPException(403, "Tài khoản chưa có tổ chức.")
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(413, "CSV vượt giới hạn 2 MB.")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            422,
            {
                "message": "CSV cần UTF-8.",
                "errors": [{"row": 1, "column": "file", "message": "Encoding không hợp lệ."}],
                "created_count": 0,
            },
        )
    reader = csv.DictReader(io.StringIO(content), strict=True)
    required = {"name", "unit"} if entity == "product" else {"name", "location", "area", "owner"}
    allowed = required if entity == "product" else required | {"coordinates"}
    try:
        headers = reader.fieldnames or []
    except csv.Error as exc:
        raise HTTPException(
            422,
            {
                "message": "Header CSV không hợp lệ.",
                "created_count": 0,
                "errors": [{"row": 1, "column": "header", "message": str(exc)}],
            },
        ) from exc
    if len(set(headers)) != len(headers) or not required <= set(headers) or set(headers) - allowed:
        raise HTTPException(
            422,
            {
                "message": "Cột CSV thiếu, trùng hoặc không được phép.",
                "errors": [{"row": 1, "column": "header", "message": "Cột cần: " + ", ".join(sorted(required))}],
                "created_count": 0,
            },
        )
    acquire_write_lock(db)
    errors = []
    plans = []
    seen = {}
    skipped = 0
    products = {norm(p.name): p for p in db.scalars(select(Product))}
    farms = list(db.scalars(select(Farm).where(Farm.organization_id == user.organization_id))) if entity == "plot" else []
    plots = list(db.scalars(select(Plot).where(Plot.organization_id == user.organization_id))) if entity == "plot" else []
    try:
        for row in reader:
            number = reader.line_num
            if number > 5001:
                errors.append({"row": number, "column": "file", "message": "Tối đa 5.000 dòng."})
                break
            if not any(row.values()):
                continue
            if None in row or any(value is None for value in row.values()):
                errors.append({"row": number, "column": "row", "message": "Số cột không khớp header."})
                continue
            clean = {k: v.strip() for k, v in row.items()}
            if entity == "plot":
                clean["coordinates"] = clean.get("coordinates") or None
            try:
                parsed = (ProductCreate if entity == "product" else FarmCreate).model_validate(clean)
                values = parsed.model_dump()
                if entity == "plot" and not math.isfinite(values["area"]):
                    raise ValueError("Diện tích cần hữu hạn.")
            except (ValidationError, ValueError) as exc:
                detail = exc.errors() if isinstance(exc, ValidationError) else [{"loc": ("area",), "msg": str(exc)}]
                errors.extend({"row": number, "column": str(e["loc"][0]), "message": e["msg"]} for e in detail)
                continue
            key = norm(values["name"]) if entity == "product" else (norm(values["name"]), norm(values["location"]))
            if key in seen:
                if seen[key] == values:
                    skipped += 1
                else:
                    errors.append({"row": number, "column": "name", "message": "Khóa trùng trong file nhưng nội dung khác."})
                continue
            seen[key] = values
            if entity == "product":
                old = products.get(key)
                if old:
                    if old.unit == values["unit"]:
                        skipped += 1
                    else:
                        errors.append({"row": number, "column": "unit", "message": "Sản phẩm đã tồn tại với đơn vị khác."})
                    continue
            else:
                fs = [p for p in farms if (norm(p.name), norm(p.location)) == key]
                ps = [p for p in plots if (norm(p.name), norm(p.location)) == key]
                if fs or ps:

                    def same(p):
                        return all(getattr(p, k) == v for k, v in values.items())

                    if len(fs) == len(ps) == 1 and fs[0].id == ps[0].id and same(fs[0]) and same(ps[0]):
                        skipped += 1
                    else:
                        errors.append(
                            {
                                "row": number,
                                "column": "name",
                                "message": (
                                    "Thửa đã có nhưng mirror Farm/Plot thiếu, mâu thuẫn "
                                    "hoặc nội dung khác; không tự ghi đè."
                                ),
                            }
                        )
                    continue
            plans.append(values)
    except csv.Error as exc:
        errors.append({"row": reader.line_num, "column": "file", "message": str(exc)})
    if not seen and not errors:
        errors.append({"row": 2, "column": "file", "message": "CSV không có dòng dữ liệu."})
    if errors:
        db.rollback()
        raise HTTPException(
            422,
            {
                "message": "CSV có lỗi; toàn bộ giao dịch đã hoàn tác.",
                "errors": errors,
                "created_count": 0,
                "error_count": len(errors),
            },
        )
    try:
        next_id = max(db.scalar(select(func.max(Farm.id))) or 0, db.scalar(select(func.max(Plot.id))) or 0) + 1
        for values in plans:
            if entity == "product":
                product = Product(**values)
                db.add(product)
                db.flush()
                record_action(db, user, ACTION_CREATE, "product", product.id, operation="csv_import")
            else:
                farm = Farm(id=next_id, organization_id=user.organization_id, **values)
                plot = Plot(id=next_id, organization_id=user.organization_id, **values)
                db.add_all([farm, plot])
                db.flush()
                record_action(db, user, ACTION_CREATE, ENTITY_FARM, next_id, operation="csv_import")
                next_id += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "message": "Nhập CSV hoàn tất.",
        "created_count": len(plans),
        "skipped_count": skipped,
        "error_count": 0,
        "success_count": len(plans),
        "total_count": len(plans) + skipped,
    }
