"""Ghi & đọc lịch sử thao tác (audit log) - Sprint 7.

Module này là **điểm duy nhất** biết cách ghi/đọc bảng ``audit_logs``, nhờ vậy
router nghiệp vụ chỉ cần gọi một hàm ngắn gọn:

- ``record_action(...)``: thêm 1 dòng log vào **session đang mở** của thao tác
  (không tự commit) -> log và dữ liệu nghiệp vụ được commit trong *cùng một
  transaction*. Hệ quả: thao tác thành công thì chắc chắn có log, thao tác thất
  bại (404/403/500) thì **không** để lại log rác.
- ``fetch_audit_logs(...)``: đọc log cho API ``GET /audit-logs`` (chỉ admin),
  sắp xếp **mới nhất trước** kèm bộ lọc ``entity`` / ``user_id`` / ``limit``.

Ví dụ dùng trong router::

    from app.audit import record_action
    from app.models import ACTION_CREATE, ENTITY_FARM

    db.add(farm)
    db.flush()  # cần `id` trước khi ghi log
    record_action(db, current_user, ACTION_CREATE, ENTITY_FARM, farm.id)
    db.commit()
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import AuditLog, User

#: Số dòng log trả về mặc định cho một lần gọi ``GET /audit-logs``.
DEFAULT_AUDIT_LOG_LIMIT: int = 100

#: Số dòng log tối đa client được yêu cầu (chặn ``?limit=100000``).
MAX_AUDIT_LOG_LIMIT: int = 500


def record_action(
    db: Session,
    user: User,
    action: str,
    entity: str,
    entity_id: int,
) -> AuditLog:
    """Thêm 1 bản ghi lịch sử vào session hiện tại (**chưa** commit).

    Hàm được gọi ngay trước ``db.commit()`` của thao tác nghiệp vụ, nên nếu
    thao tác thất bại (rollback) thì dòng log cũng bị huỷ theo - nhờ vậy lịch
    sử chỉ chứa những thao tác **thực sự đã xảy ra**.

    Args:
        db: Session SQLAlchemy của request (dependency ``get_db``).
        user: Tài khoản đã thực hiện thao tác (lấy ``id`` ghi vào cột ``user_id``).
        action: Hành động - dùng hằng số ``ACTION_CREATE`` / ``ACTION_UPDATE`` /
            ``ACTION_DELETE`` trong ``app/models.py``.
        entity: Loại dữ liệu bị tác động - ``ENTITY_FARM`` hoặc ``ENTITY_BATCH``.
        entity_id: ID bản ghi bị tác động (phải là ID **thật** của bản ghi; với
            thao tác tạo mới, gọi ``db.flush()`` trước để có ``id``).

    Returns:
        AuditLog: Đối tượng vừa được ``db.add()`` (``id``/``created_at`` chỉ có
        giá trị sau khi commit).
    """
    log = AuditLog(
        user_id=user.id,
        action=action,
        entity=entity,
        entity_id=entity_id,
    )
    db.add(log)
    return log


def fetch_audit_logs(
    db: Session,
    entity: str | None = None,
    user_id: int | None = None,
    limit: int = DEFAULT_AUDIT_LOG_LIMIT,
) -> list[AuditLog]:
    """Đọc bảng ``audit_logs`` cho API ``GET /audit-logs`` (chỉ admin gọi được).

    Args:
        db: Session SQLAlchemy của request.
        entity: Lọc theo loại dữ liệu (``"farm"`` / ``"batch"``); ``None`` = lấy tất cả.
        user_id: Lọc theo người thực hiện; ``None`` = lấy tất cả.
        limit: Số dòng tối đa trả về (mặc định ``DEFAULT_AUDIT_LOG_LIMIT``).

    Returns:
        list[AuditLog]: Log **mới nhất trước** (giảm dần theo ``id``). Dùng
        ``id`` giảm dần thay vì ``created_at`` vì các log trong cùng một giây
        vẫn được sắp xếp đúng thứ tự phát sinh.
    """
    statement = (
        select(AuditLog)
        # Nạp sẵn tài khoản để serialize `username` mà không phát sinh truy vấn phụ.
        .options(joinedload(AuditLog.user))
        .order_by(AuditLog.id.desc())
        .limit(limit)
    )

    if entity is not None:
        statement = statement.where(AuditLog.entity == entity)
    if user_id is not None:
        statement = statement.where(AuditLog.user_id == user_id)

    return list(db.scalars(statement).all())


__all__ = [
    "DEFAULT_AUDIT_LOG_LIMIT",
    "MAX_AUDIT_LOG_LIMIT",
    "fetch_audit_logs",
    "record_action",
]
