"""Dịch vụ kiểm soát truy cập dựa trên vai trò tập trung (RBAC Policy Engine) - Giai đoạn 1B.

Hỗ trợ 7 vai trò chính thức:
1. system_admin : Quản trị hệ thống, quản lý tài khoản, cấu hình toàn cục.
2. org_admin    : Quản trị một tổ chức cụ thể, quản lý nhân sự tổ chức.
3. farmer       : Nông dân/canh tác, quản lý thửa đất, thu hoạch (HARVEST).
4. processor    : Sơ chế, đóng gói, tách lô (SPLIT), gộp lô (MERGE).
5. transporter  : Vận chuyển chuỗi lạnh, bàn giao logistics (HANDOVER).
6. distributor  : Doanh nghiệp phân phối, xuất nhập khẩu nông sản.
7. inspector    : Thanh tra, kiểm tra toàn vẹn hash-chain (Read-only liên tổ chức).

Quy tắc:
- Mặc định từ chối (Deny by Default).
- Inspector được quyền đọc liên tổ chức nhưng KHÔNG được sửa đổi dữ liệu nghiệp vụ.
- Quy tắc S-23: Tổ chức đã bàn giao chỉ được xem lịch sử tính đến thời điểm bàn giao.
"""

from datetime import datetime
from typing import Any
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    EVENT_HANDOVER_ACCEPT,
    HANDOVER_ACCEPTED,
    ROLE_ADMIN,
    ROLE_DISTRIBUTOR,
    ROLE_FARMER,
    ROLE_INSPECTOR,
    ROLE_ORG_ADMIN,
    ROLE_PROCESSOR,
    ROLE_SYSTEM_ADMIN,
    ROLE_TRANSPORTER,
    Batch,
    BatchEvent,
    Handover,
    User,
)

# Nhóm vai trò quản trị
ADMIN_ROLES = (ROLE_SYSTEM_ADMIN, ROLE_ORG_ADMIN, ROLE_ADMIN)

# Nhóm vai trò nghiệp vụ chuỗi cung ứng
OPERATIONAL_ROLES = (
    ROLE_FARMER,
    ROLE_PROCESSOR,
    ROLE_TRANSPORTER,
    ROLE_DISTRIBUTOR,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    ROLE_ADMIN,
)

# Quyền đọc thanh tra
READ_AUDIT_ROLES = (ROLE_INSPECTOR, ROLE_SYSTEM_ADMIN, ROLE_ORG_ADMIN, ROLE_ADMIN)

# Ánh xạ chính thức cho 8 tài khoản cũ sang 7 vai trò cố định
LEGACY_ACCOUNT_ROLE_MAPPING: dict[str, str] = {
    "admin": ROLE_SYSTEM_ADMIN,
    "farmer": ROLE_FARMER,
    "farmer_tg": ROLE_FARMER,
    "distributor": ROLE_DISTRIBUTOR,
    "demo_farm": ROLE_FARMER,
    "demo_packing": ROLE_PROCESSOR,
    "demo_distribution": ROLE_DISTRIBUTOR,
    "demo_admin": ROLE_SYSTEM_ADMIN,
}

# Ma trận phân quyền hành động nghiệp vụ (Quy định nghiêm ngặt Giai đoạn 1B.1)
ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "LOCATION_MANAGE": (ROLE_DISTRIBUTOR, ROLE_ORG_ADMIN),
    "PRODUCT_CREATE": (ROLE_SYSTEM_ADMIN, ROLE_ADMIN),
    # Existing operational edits; system administrators do not produce data.
    "BATCH_UPDATE": (ROLE_FARMER, ROLE_PROCESSOR, ROLE_TRANSPORTER, ROLE_DISTRIBUTOR, ROLE_ORG_ADMIN),
    "EVENT_CREATE": (ROLE_FARMER, ROLE_PROCESSOR, ROLE_TRANSPORTER, ROLE_DISTRIBUTOR, ROLE_ORG_ADMIN),
    # Thu hoạch lô mới (chỉ nông dân canh tác)
    "HARVEST": (ROLE_FARMER,),
    # Quản lý vùng trồng (nông dân và quản trị tổ chức)
    "FARM_MANAGE": (ROLE_FARMER, ROLE_ORG_ADMIN),
    # Sơ chế / chế biến (chỉ nhà chế biến)
    "PROCESS": (ROLE_PROCESSOR,),
    # Vận chuyển logistics (chỉ đơn vị vận chuyển)
    "TRANSPORT_DISPATCH": (ROLE_TRANSPORTER,),
    "TRANSPORT_DELIVER": (ROLE_TRANSPORTER,),
    # Tách lô (nông dân chia tại trại, nhà chế biến, nhà phân phối)
    "SPLIT": (ROLE_FARMER, ROLE_PROCESSOR, ROLE_DISTRIBUTOR),
    # Gộp lô (chỉ nhà chế biến)
    "MERGE": (ROLE_PROCESSOR,),
    # Khởi tạo bàn giao (các bên trực tiếp nắm giữ lô trong chuỗi cung ứng)
    "HANDOVER_INIT": (
        ROLE_FARMER,
        ROLE_PROCESSOR,
        ROLE_TRANSPORTER,
        ROLE_DISTRIBUTOR,
    ),
    # Tiếp nhận / phản hồi bàn giao (các bên tiếp nhận lô)
    "HANDOVER_RESPOND": (
        ROLE_PROCESSOR,
        ROLE_TRANSPORTER,
        ROLE_DISTRIBUTOR,
        ROLE_FARMER,
    ),
    # Xem danh sách / chi tiết lô (theo tổ chức + inspector toàn hệ thống)
    "BATCH_VIEW": (
        ROLE_FARMER,
        ROLE_PROCESSOR,
        ROLE_TRANSPORTER,
        ROLE_DISTRIBUTOR,
        ROLE_INSPECTOR,
        ROLE_ORG_ADMIN,
        ROLE_SYSTEM_ADMIN,
        ROLE_ADMIN,
    ),
    # Xem lịch sử sự kiện & toàn vẹn
    "INTEGRITY_VERIFY": (
        ROLE_FARMER,
        ROLE_PROCESSOR,
        ROLE_TRANSPORTER,
        ROLE_DISTRIBUTOR,
        ROLE_INSPECTOR,
        ROLE_ORG_ADMIN,
        ROLE_SYSTEM_ADMIN,
        ROLE_ADMIN,
    ),
    # Xem nhật ký kiểm toán (Audit logs: chỉ quản trị và thanh tra)
    "AUDIT_VIEW": (ROLE_SYSTEM_ADMIN, ROLE_INSPECTOR, ROLE_ORG_ADMIN, ROLE_ADMIN),
    # Quản trị tài khoản
    "USER_MANAGE": (ROLE_SYSTEM_ADMIN, ROLE_ORG_ADMIN, ROLE_ADMIN),
    # Quyền quản trị hệ thống
    "SYSTEM_ADMIN": (ROLE_SYSTEM_ADMIN, ROLE_ADMIN),
    # Quyền thu hồi / đình chỉ lô (Giai đoạn 2: Inspector và Org Admin khi giữ lô; System Admin không mặc định)
    "BATCH_RECALL": (ROLE_INSPECTOR, ROLE_ORG_ADMIN),
    # Ghi nhận lô đã bán hết cho người tiêu dùng (Sprint 4 - S-29)
    "BATCH_CONSUME": (ROLE_DISTRIBUTOR, ROLE_ORG_ADMIN),
}


def get_effective_role(user_or_role: Any) -> str:
    """Lấy vai trò thực tế để áp dụng ma trận quyền RBAC.

    Phân biệt rõ:
    - Role trong database (có thể là legacy chưa migrate).
    - Role thực tế tại từng API: ánh xạ các tài khoản cũ theo LEGACY_ACCOUNT_ROLE_MAPPING:
      + distributor, demo_distribution -> distributor (không có quyền farmer)
      + demo_packing -> processor (không có quyền farmer)
      + admin, demo_admin -> system_admin (không có quyền thu hoạch, tách/gộp, bàn giao)
    """
    if isinstance(user_or_role, str):
        if user_or_role == "admin":
            return ROLE_SYSTEM_ADMIN
        return user_or_role

    username = getattr(user_or_role, "username", None)
    if username and username in LEGACY_ACCOUNT_ROLE_MAPPING:
        return LEGACY_ACCOUNT_ROLE_MAPPING[username]

    role = getattr(user_or_role, "role", "")
    if role == "admin":
        return ROLE_SYSTEM_ADMIN
    return role


def check_action_permission(user_or_role: Any, action: str, raise_exception: bool = True) -> bool:
    """Kiểm tra vai trò người dùng có quyền thực hiện hành động hay không.

    Hỗ trợ truyền User instance hoặc chuỗi role.
    Nếu raise_exception=True và không có quyền -> ném HTTPException 403.
    Trả về bool True nếu được phép, False nếu bị từ chối.
    """
    role = get_effective_role(user_or_role)
    allowed_roles = ROLE_PERMISSIONS.get(action)
    if allowed_roles is None:
        if raise_exception:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Hành động '{action}' chưa được khai báo quyền (Mặc định từ chối).",
            )
        return False

    if role not in allowed_roles:
        if raise_exception:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Vai trò '{role}' không có quyền thực hiện hành động '{action}'.",
            )
        return False
    return True


def check_inspector_read_only(user: User, is_write_operation: bool) -> None:
    """Đảm bảo Inspector chỉ được quyền đọc, tuyệt đối không được ghi/sửa dữ liệu."""
    if get_effective_role(user) == ROLE_INSPECTOR and is_write_operation:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vai trò thanh tra (inspector) chỉ có quyền đọc giám sát, không được sửa đổi dữ liệu nghiệp vụ.",
        )


def can_recall_batch(user: User, batch: Any, raise_exception: bool = True) -> bool:
    """Kiểm tra quyền thu hồi lô hàng (RECALL) theo backlog mentor:
    - inspector: Được thực hiện thu hồi theo Acceptance Criteria.
    - org_admin: Chỉ được thu hồi lô khi tổ chức mình đang giữ lô (current_org_id == user.organization_id).
    - system_admin: Không mặc định có quyền RECALL.
    - Các vai trò khác: Không có quyền RECALL.
    """
    role = get_effective_role(user)
    if role == ROLE_INSPECTOR:
        return True

    if role == ROLE_ORG_ADMIN:
        batch_org_id = getattr(batch, "current_org_id", None)
        if user.organization_id is not None and batch_org_id == user.organization_id:
            return True
        if raise_exception:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Quản trị tổ chức (org_admin) chỉ được thu hồi lô hàng khi tổ chức mình đang trực tiếp nắm giữ lô.",
            )
        return False

    if raise_exception:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Vai trò '{role}' không có quyền thu hồi lô hàng.",
        )
    return False


def get_handover_cutoff_event_id(
    db: Session, batch_id: int, user_org_id: int | None, user_role: str
) -> int | None:
    """Quy tắc S-23 nâng cao (Giai đoạn 1B.1): Xác định ID sự kiện giới hạn khi xem lịch sử.

    Dựa trên khóa chính sự kiện (BatchEvent.id) và quan hệ nghiệp vụ,
    loại bỏ triệt để rủi ro từ timestamp trùng nhau hoặc sai lệch đồng hồ:

    1. Inspector / System Admin: Không bị giới hạn (trả về None - xem toàn diện).
    2. Nếu tổ chức hiện đang nắm giữ lô (batch.current_org_id == user_org_id):
       Không bị giới hạn (trả về None). Bao quát cả trường hợp nhận lại cùng lô (A -> B -> A).
    3. Nếu tổ chức đã bàn giao lô đi (batch.current_org_id != user_org_id):
       Tìm sự kiện HANDOVER_ACCEPT cuối cùng mà tổ chức này là bên giao (from_org_id == user_org_id).
       Trả về id của sự kiện đó làm mốc giới hạn (cutoff_event_id).
       Mọi sự kiện có event.id > cutoff_event_id đều bị ẩn hoặc từ chối truy cập 403.
    """
    if user_role in (ROLE_INSPECTOR, ROLE_SYSTEM_ADMIN, ROLE_ADMIN):
        return None

    if user_org_id is None:
        return None

    batch = db.get(Batch, batch_id)
    if batch is None:
        return None

    # Nếu tổ chức này đang trực tiếp nắm giữ lô -> xem đầy đủ lịch sử đến hiện tại
    # (Bao gồm trường hợp đã từng giao đi nhưng sau đó nhận lại ở một chặng sau)
    if batch.current_org_id == user_org_id:
        return None

    # Tìm sự kiện HANDOVER_ACCEPT gần nhất mà tổ chức này là bên giao (from_org_id)
    last_accept_event_id = db.scalar(
        select(BatchEvent.id)
        .where(
            BatchEvent.batch_id == batch_id,
            BatchEvent.event_type == EVENT_HANDOVER_ACCEPT,
            BatchEvent.from_org_id == user_org_id,
        )
        .order_by(BatchEvent.id.desc())
        .limit(1)
    )
    if last_accept_event_id is not None:
        return last_accept_event_id

    # Fallback kiểm tra qua bảng Handover nếu event chưa lưu from_org_id trực tiếp
    last_accepted_ho = db.scalar(
        select(Handover.id)
        .where(
            Handover.batch_id == batch_id,
            Handover.from_org_id == user_org_id,
            Handover.status == HANDOVER_ACCEPTED,
        )
        .order_by(Handover.id.desc())
        .limit(1)
    )
    if last_accepted_ho is not None:
        ev_id = db.scalar(
            select(BatchEvent.id)
            .where(
                BatchEvent.batch_id == batch_id,
                BatchEvent.event_type == EVENT_HANDOVER_ACCEPT,
            )
            .order_by(BatchEvent.id.desc())
            .limit(1)
        )
        return ev_id

    return None


def get_handover_history_cutoff(
    db: Session, batch_id: int, user_org_id: int | None, user_role: str
) -> datetime | None:
    """Tương thích ngược: Lấy timestamp ứng với cutoff_event_id."""
    cutoff_id = get_handover_cutoff_event_id(db, batch_id, user_org_id, user_role)
    if cutoff_id is None:
        return None
    ev = db.get(BatchEvent, cutoff_id)
    return ev.timestamp if ev else None
