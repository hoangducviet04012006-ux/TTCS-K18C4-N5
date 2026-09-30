"""Khai báo ORM models (bảng dữ liệu) bằng SQLAlchemy 2.0.

Sprint 1: khung dự án + endpoint ``GET /health`` (chưa có bảng nghiệp vụ).
Sprint 2: module **Farm** (quản lý vùng trồng - bảng ``farms``)
và module **Batch** (quản lý lô nông sản - bảng ``batches``).
Sprint 4: module **Auth** (đăng nhập + phân quyền - bảng ``users``).
Sprint 7: module **Audit log** (lịch sử thao tác - bảng ``audit_logs``).

Quan hệ giữa các bảng::

    Farm 1 ---- N Batch     (một vùng trồng có nhiều lô nông sản)
    User 1 ---- N AuditLog  (một tài khoản có nhiều bản ghi lịch sử thao tác)

File này là điểm duy nhất (single source of truth) khai báo bảng dữ liệu.
Mọi model đều kế thừa ``Base`` và bảng sẽ được ``init_db()`` trong
``app/database.py`` tự động tạo khi ứng dụng khởi động (xem ``lifespan``
ở ``app/main.py``) - không cần chạy script SQL thủ công.
"""

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Farm(Base):
    """Vùng trồng nông sản - mắt xích đầu tiên của chuỗi cung ứng.

    Attributes:
        id: Khoá chính, tự tăng.
        name: Tên vùng trồng (ví dụ: "Vùng trồng xoài Cao Lãnh").
        location: Địa điểm của vùng trồng (xã/huyện/tỉnh).
        area: Diện tích canh tác, đơn vị hecta (ha).
        owner: Chủ sở hữu vùng trồng (hộ nông dân / hợp tác xã / doanh nghiệp).
        batches: Các lô nông sản thu hoạch từ vùng trồng này (quan hệ 1-N).
    """

    __tablename__ = "farms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    area: Mapped[float] = mapped_column(Float, nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)

    # Quan hệ 1-N: một vùng trồng có nhiều lô nông sản.
    # `cascade="all, delete-orphan"`: khi Farm bị xoá thì các Batch của nó cũng
    # bị xoá theo -> không để lại dữ liệu mồ côi. Hành vi này được dùng bởi
    # `DELETE /farms/{farm_id}` (xem `app/routers/farms.py`).
    batches: Mapped[list["Batch"]] = relationship(
        back_populates="farm",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - chỉ dùng khi debug/log
        return f"<Farm id={self.id} name={self.name!r} area={self.area}ha>"


class Batch(Base):
    """Lô nông sản thu hoạch từ một vùng trồng.

    Quan hệ: ``Farm 1 ---- N Batch``.

    Attributes:
        id: Khoá chính, tự tăng.
        farm_id: Khoá ngoại trỏ tới ``farms.id`` (vùng trồng xuất xứ).
        product_name: Tên sản phẩm của lô (ví dụ: "Xoài cát Chu").
        quantity: Số lượng / khối lượng của lô, đơn vị kg.
        harvest_date: Ngày thu hoạch.
        farm: Đối tượng ``Farm`` tương ứng (chiều N-1 của quan hệ).
    """

    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # `index=True` để tra cứu "các lô của một vùng trồng" nhanh hơn.
    farm_id: Mapped[int] = mapped_column(
        ForeignKey("farms.id"),
        nullable=False,
        index=True,
    )
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    harvest_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Quan hệ N-1: nhiều lô có thể thuộc về một vùng trồng.
    farm: Mapped["Farm"] = relationship(back_populates="batches")

    def __repr__(self) -> str:  # pragma: no cover - chỉ dùng khi debug/log
        return (
            f"<Batch id={self.id} farm_id={self.farm_id} "
            f"product_name={self.product_name!r}>"
        )


# ------------------------------------------------------------- Vai trò ---
# Khai báo thành hằng số để không phải gõ chuỗi "admin"/"farmer" rải rác
# trong code (tránh lỗi gõ sai, chỉ cần đổi giá trị ở một chỗ nếu sau này
# muốn thêm vai trò mới như "inspector" hay "retailer").
ROLE_ADMIN: str = "admin"
ROLE_FARMER: str = "farmer"
ROLES: tuple[str, ...] = (ROLE_ADMIN, ROLE_FARMER)


class User(Base):
    """Tài khoản đăng nhập của hệ thống - bảng ``users``.

    Sprint 4 dùng bảng này cho chức năng **đăng nhập + phân quyền cơ bản**.
    Hệ thống **không dùng JWT**, không token/session phía server: client gửi
    kèm `username`/`password` (HTTP Basic) ở mỗi request, backend tra bảng này
    để biết người gọi là ai (xem ``app/security.py``).

    Attributes:
        id: Khoá chính, tự tăng.
        username: Tên đăng nhập, **duy nhất** (có index để tra cứu nhanh).
        password: Mật khẩu **đã băm** (SHA-256 hex = 64 ký tự) - không bao giờ
            lưu mật khẩu dạng thô, và API cũng không bao giờ trả cột này ra.
        role: Vai trò của tài khoản: ``"admin"`` (quản trị - toàn quyền) hoặc
            ``"farmer"`` (nông dân - quản lý nông sản).
        failed_login_attempts: Số lần đăng nhập **sai liên tiếp** (Sprint 6 - bảo
            mật đăng nhập). Đăng nhập thành công sẽ đưa về ``0``.
        locked_until: Thời điểm tài khoản được **mở khoá trở lại** (UTC, naive);
            ``None`` nghĩa là tài khoản không bị khoá.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        unique=True,
        index=True,
    )
    # 64 ký tự là độ dài chuỗi hex của SHA-256 (xem `hash_password`).
    password: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=ROLE_FARMER)

    # ------------------------------------------- Bảo mật đăng nhập (Sprint 6) ---
    # Đếm số lần đăng nhập sai liên tiếp. Khi đạt ngưỡng
    # `MAX_FAILED_LOGIN_ATTEMPTS` (xem `app/security.py`), tài khoản bị tạm khoá
    # tới thời điểm `locked_until` -> mọi lần đăng nhập tiếp theo đều bị từ chối
    # bằng HTTP 403, kể cả khi gửi đúng mật khẩu. Đăng nhập thành công (hoặc hết
    # thời gian khoá) sẽ đưa cả hai cột về trạng thái ban đầu.
    # `server_default="0"`: cần thiết để database cũ (tạo từ Sprint 4) nhận được
    # giá trị mặc định khi nâng cấp bằng `ALTER TABLE ... DEFAULT 0`.
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - chỉ dùng khi debug/log
        # Không in `password` để tránh lộ mật khẩu đã băm ra log.
        return f"<User id={self.id} username={self.username!r} role={self.role}>"


# ------------------------------------- Lịch sử thao tác (audit log) - Sprint 7 ---
# Hai hằng số dưới đây là **giá trị hợp lệ** của 2 cột trong bảng `audit_logs`
# (`action` và `entity`). Khai báo tập trung để router không phải gõ chuỗi rải
# rác (tránh lỗi gõ sai và dễ mở rộng khi thêm nghiệp vụ mới như "export").

#: Hành động đã xảy ra với dữ liệu (cột ``audit_logs.action``).
ACTION_CREATE: str = "create"
ACTION_UPDATE: str = "update"
ACTION_DELETE: str = "delete"
ACTIONS: tuple[str, ...] = (ACTION_CREATE, ACTION_UPDATE, ACTION_DELETE)

#: Loại dữ liệu bị tác động (cột ``audit_logs.entity``).
ENTITY_FARM: str = "farm"
ENTITY_BATCH: str = "batch"
ENTITIES: tuple[str, ...] = (ENTITY_FARM, ENTITY_BATCH)


def _naive_utcnow() -> datetime:
    """Thời điểm hiện tại theo UTC, **không** kèm ``tzinfo``.

    Dùng làm giá trị mặc định cho cột thời gian ``audit_logs.created_at``.
    Cùng quy ước với ``security.utcnow()`` (cột ``DATETIME`` của SQLite không
    lưu offset nên phải dùng naive datetime khi so sánh), nhưng khai báo ngay
    tại đây để tránh import vòng: ``app/security.py`` import ``app/models.py``.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuditLog(Base):
    """Một dòng lịch sử thao tác (audit log) - bảng ``audit_logs``.

    Trả lời câu hỏi "**ai** đã **làm gì**, vào lúc nào": mỗi lần client tạo /
    sửa / xoá vùng trồng hoặc lô nông sản thành công, backend ghi thêm một bản
    ghi vào bảng này (xem ``app/audit.py``) - **trong cùng transaction** với
    thao tác nghiệp vụ, nên thao tác thất bại thì cũng không có log.

    Attributes:
        id: Khoá chính, tự tăng.
        user_id: Tài khoản đã thực hiện thao tác (khoá ngoại -> ``users.id``).
        action: Hành động: ``"create"`` / ``"update"`` / ``"delete"``
            (các hằng số ``ACTION_*`` ở trên).
        entity: Loại dữ liệu bị tác động: ``"farm"`` hoặc ``"batch"``
            (các hằng số ``ENTITY_*`` ở trên).
        entity_id: ID của bản ghi bị tác động (trong bảng ``farms`` hoặc ``batches``).
        created_at: Thời điểm ghi log (UTC, naive) - tự sinh khi INSERT.
        user: Đối tượng ``User`` tương ứng (chiều N-1 của quan hệ).
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # `index=True`: API `GET /audit-logs` lọc theo người thực hiện (`user_id`).
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    # Lưu chuỗi (không dùng Enum) để thêm hành động mới không phải ALTER TABLE.
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    entity: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_naive_utcnow,
    )

    # Quan hệ N-1: nhiều dòng log có thể do cùng một tài khoản thực hiện.
    user: Mapped["User"] = relationship()

    @property
    def username(self) -> str:
        """Tên đăng nhập của người thực hiện thao tác.

        Chỉ là **tiện ích hiển thị** cho API ``GET /audit-logs`` (đỡ phải tra
        bảng ``users`` lần nữa); dữ liệu gốc vẫn nằm ở cột ``user_id``.
        Router nạp sẵn quan hệ ``user`` bằng ``joinedload`` nên không phát sinh
        truy vấn phụ (xem ``app/audit.py``).
        """
        return self.user.username if self.user is not None else ""

    def __repr__(self) -> str:  # pragma: no cover - chỉ dùng khi debug/log
        return (
            f"<AuditLog id={self.id} user_id={self.user_id} "
            f"action={self.action!r} entity={self.entity!r} "
            f"entity_id={self.entity_id}>"
        )


__all__ = [
    "ACTION_CREATE",
    "ACTION_DELETE",
    "ACTION_UPDATE",
    "ACTIONS",
    "AuditLog",
    "Base",
    "Batch",
    "ENTITIES",
    "ENTITY_BATCH",
    "ENTITY_FARM",
    "Farm",
    "ROLE_ADMIN",
    "ROLE_FARMER",
    "ROLES",
    "User",
]
