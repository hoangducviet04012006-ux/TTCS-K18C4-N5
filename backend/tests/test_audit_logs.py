"""Test Sprint 7 - lịch sử thao tác (audit log).

Bao phủ yêu cầu:

1. Bảng ``audit_logs`` có đủ 6 cột theo yêu cầu: ``id``, ``user_id``, ``action``,
   ``entity``, ``entity_id``, ``created_at``.
2. Ghi log đúng cho **6 thao tác**: tạo/sửa/xoá Farm và tạo/sửa/xoá Batch.
3. Log ghi đúng **ai đã làm gì** (admin và farmer đều được ghi đúng ``user_id``).
4. Thao tác **thất bại** (401/403/404/422) không để lại log; các API **đọc**
   (GET) và đăng nhập cũng không ghi log.
5. ``GET /audit-logs``: **chỉ admin** xem được (farmer -> 403, chưa đăng nhập ->
   401), sắp xếp mới nhất trước, hỗ trợ lọc ``entity`` / ``user_id`` / ``limit``
   và không có API nào để sửa/xoá log.

Chạy: ``python -m pytest`` (từ thư mục ``backend``).
"""

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import AuditLog, User
from app.security import utcnow
from tests.conftest import TEST_PASSWORD, TEST_USERNAME_ADMIN, TEST_USERNAME_FARMER

AUDIT_LOGS_URL = "/audit-logs"

FARM_PAYLOAD: dict[str, object] = {
    "name": "Vùng trồng xoài Cao Lãnh",
    "location": "Cao Lãnh, Đồng Tháp",
    "area": 2.5,
    "owner": "Hợp tác xã xoài Cao Lãnh",
}


def _batch_payload(farm_id: int) -> dict[str, object]:
    """Body tạo/sửa lô nông sản (dùng chung cho cả POST và PUT)."""
    return {
        "farm_id": farm_id,
        "product_name": "Xoài cát Chu",
        "quantity": 120.5,
        "harvest_date": "2026-01-15",
    }


# ------------------------------------------------------------------- Helper ---
def _auth(username: str = TEST_USERNAME_ADMIN) -> tuple[str, str]:
    """Thông tin HTTP Basic để gọi API (mặc định là tài khoản admin)."""
    return username, TEST_PASSWORD


def _create_farm(client: TestClient, username: str = TEST_USERNAME_ADMIN) -> dict:
    """Tạo một vùng trồng qua API và trả về body JSON (đã có ``id``)."""
    response = client.post("/farms", json=FARM_PAYLOAD, auth=_auth(username))
    assert response.status_code == 201, response.text
    return response.json()


def _create_batch(
    client: TestClient,
    farm_id: int,
    username: str = TEST_USERNAME_ADMIN,
) -> dict:
    """Tạo một lô nông sản qua API và trả về body JSON (đã có ``id``)."""
    response = client.post(
        "/batches", json=_batch_payload(farm_id), auth=_auth(username)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _get_logs(
    client: TestClient,
    username: str = TEST_USERNAME_ADMIN,
    **params: object,
) -> list[dict]:
    """Gọi ``GET /audit-logs`` bằng tài khoản admin và trả về danh sách log."""
    response = client.get(AUDIT_LOGS_URL, params=params, auth=_auth(username))
    assert response.status_code == 200, response.text
    return response.json()


def _actions(client: TestClient, **params: object) -> list[tuple[str, str, int]]:
    """Rút gọn log thành ``(action, entity, entity_id)`` - mới nhất trước."""
    return [
        (log["action"], log["entity"], log["entity_id"])
        for log in _get_logs(client, **params)
    ]


def _read_logs(session_factory: sessionmaker[Session]) -> list[AuditLog]:
    """Đọc trực tiếp bảng ``audit_logs`` (tăng dần theo ``id`` = thứ tự phát sinh)."""
    with session_factory() as session:
        return list(session.scalars(select(AuditLog).order_by(AuditLog.id)).all())


def _user_id(session_factory: sessionmaker[Session], username: str) -> int:
    """Lấy ``id`` của một tài khoản test từ database."""
    with session_factory() as session:
        user = session.scalar(select(User).where(User.username == username))
        assert user is not None, f"Không tìm thấy tài khoản {username!r}"
        return user.id


# ------------------------------------- 0. Bảng audit_logs đúng yêu cầu đề bài ---
def test_bang_audit_logs_co_du_sau_cot(engine: Engine) -> None:
    """Bảng ``audit_logs`` phải có đúng 6 cột (đúng thứ tự khai báo trong model)."""
    with engine.begin() as connection:
        columns = [
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(audit_logs)")
        ]

    assert columns == ["id", "user_id", "action", "entity", "entity_id", "created_at"]


# --------------------------------------- 1. Ghi log 6 thao tác Farm và Batch ---
def test_tao_farm_ghi_log(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """``POST /farms`` -> 1 dòng log ``create`` / ``farm`` kèm đúng người thực hiện."""
    farm = _create_farm(client)

    logs = _get_logs(client)
    assert len(logs) == 1

    log = logs[0]
    assert (log["action"], log["entity"], log["entity_id"]) == (
        "create",
        "farm",
        farm["id"],
    )
    assert log["user_id"] == _user_id(session_factory, TEST_USERNAME_ADMIN)
    assert log["username"] == TEST_USERNAME_ADMIN
    # `created_at` là UTC (naive) và phải gần với thời điểm hiện tại.
    elapsed = (utcnow() - datetime.fromisoformat(log["created_at"])).total_seconds()
    assert abs(elapsed) < 60


def test_sua_farm_ghi_log(client: TestClient) -> None:
    """``PUT /farms/{id}`` -> 1 dòng log ``update`` / ``farm``."""
    farm = _create_farm(client)

    response = client.put(
        f"/farms/{farm['id']}",
        json={**FARM_PAYLOAD, "area": 9.9, "owner": "Hợp tác xã mới"},
        auth=_auth(),
    )
    assert response.status_code == 200

    assert _actions(client) == [
        ("update", "farm", farm["id"]),
        ("create", "farm", farm["id"]),
    ]


def test_xoa_farm_ghi_log_va_khong_ghi_cho_batch_bi_xoa_kem(client: TestClient) -> None:
    """``DELETE /farms/{id}`` -> log ``delete``/``farm``; batch cascade không sinh log."""
    farm = _create_farm(client)
    batches = [_create_batch(client, farm["id"]) for _ in range(2)]

    response = client.delete(f"/farms/{farm['id']}", auth=_auth())
    assert response.status_code == 200
    assert response.json()["deleted_batches"] == 2

    assert _actions(client) == [
        ("delete", "farm", farm["id"]),
        ("create", "batch", batches[1]["id"]),
        ("create", "batch", batches[0]["id"]),
        ("create", "farm", farm["id"]),
    ]


def test_tao_batch_ghi_log(client: TestClient) -> None:
    """``POST /batches`` -> 1 dòng log ``create`` / ``batch``."""
    farm = _create_farm(client)
    batch = _create_batch(client, farm["id"])

    assert _actions(client) == [
        ("create", "batch", batch["id"]),
        ("create", "farm", farm["id"]),
    ]


def test_sua_batch_ghi_log(client: TestClient) -> None:
    """``PUT /batches/{id}`` -> 1 dòng log ``update`` / ``batch``."""
    farm = _create_farm(client)
    batch = _create_batch(client, farm["id"])

    response = client.put(
        f"/batches/{batch['id']}",
        json={**_batch_payload(farm["id"]), "quantity": 99.9},
        auth=_auth(),
    )
    assert response.status_code == 200

    assert _actions(client)[0] == ("update", "batch", batch["id"])


def test_xoa_batch_ghi_log(client: TestClient) -> None:
    """``DELETE /batches/{id}`` -> 1 dòng log ``delete`` / ``batch``."""
    farm = _create_farm(client)
    batch = _create_batch(client, farm["id"])

    response = client.delete(f"/batches/{batch['id']}", auth=_auth())
    assert response.status_code == 200

    assert _actions(client)[0] == ("delete", "batch", batch["id"])


def test_chuoi_sau_thao_tac_duoc_ghi_theo_thu_tu_moi_nhat_truoc(
    client: TestClient,
) -> None:
    """Đủ 6 thao tác (3 Farm + 3 Batch) -> 6 dòng log, mới nhất đứng đầu."""
    farm = _create_farm(client)
    batch = _create_batch(client, farm["id"])
    client.put(f"/farms/{farm['id']}", json=FARM_PAYLOAD, auth=_auth())
    client.put(f"/batches/{batch['id']}", json=_batch_payload(farm["id"]), auth=_auth())
    client.delete(f"/batches/{batch['id']}", auth=_auth())
    client.delete(f"/farms/{farm['id']}", auth=_auth())

    logs = _get_logs(client)
    assert [(log["action"], log["entity"], log["entity_id"]) for log in logs] == [
        ("delete", "farm", farm["id"]),
        ("delete", "batch", batch["id"]),
        ("update", "batch", batch["id"]),
        ("update", "farm", farm["id"]),
        ("create", "batch", batch["id"]),
        ("create", "farm", farm["id"]),
    ]
    # Log vẫn còn nguyên dù bản ghi farm/batch đã bị xoá (không xoá dây chuyền).
    assert [log["id"] for log in logs] == [6, 5, 4, 3, 2, 1]


# ---------------------------------------------- 2. Ghi log đúng người thực hiện ---
def test_log_ghi_dung_nguoi_thuc_hien(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Farmer tạo farm/batch, admin xoá batch -> mỗi dòng log đúng người thực hiện."""
    farm = _create_farm(client, TEST_USERNAME_FARMER)
    batch = _create_batch(client, farm["id"], TEST_USERNAME_FARMER)
    client.delete(f"/batches/{batch['id']}", auth=_auth(TEST_USERNAME_ADMIN))

    logs = _get_logs(client)
    assert [(log["username"], log["action"], log["entity"]) for log in logs] == [
        (TEST_USERNAME_ADMIN, "delete", "batch"),
        (TEST_USERNAME_FARMER, "create", "batch"),
        (TEST_USERNAME_FARMER, "create", "farm"),
    ]

    farmer_id = _user_id(session_factory, TEST_USERNAME_FARMER)
    admin_id = _user_id(session_factory, TEST_USERNAME_ADMIN)
    assert [log["user_id"] for log in logs] == [admin_id, farmer_id, farmer_id]


# ------------------------------------------- 3. Thao tác thất bại không ghi log ---
def test_thao_tac_that_bai_khong_ghi_log(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """404 / 403 / 401 / 422 -> dữ liệu không đổi thì cũng không sinh log."""
    farm = _create_farm(client)
    farm_id = farm["id"]

    # 404: bản ghi (hoặc vùng trồng tham chiếu) không tồn tại.
    assert client.put("/farms/999", json=FARM_PAYLOAD, auth=_auth()).status_code == 404
    assert client.delete("/farms/999", auth=_auth()).status_code == 404
    assert (
        client.post("/batches", json=_batch_payload(999), auth=_auth()).status_code
        == 404
    )
    assert (
        client.put(
            "/batches/999", json=_batch_payload(farm_id), auth=_auth()
        ).status_code
        == 404
    )
    assert client.delete("/batches/999", auth=_auth()).status_code == 404
    # 403: farmer không được xoá.
    assert (
        client.delete(f"/farms/{farm_id}", auth=_auth(TEST_USERNAME_FARMER)).status_code
        == 403
    )
    # 401: chưa đăng nhập.
    assert client.post("/farms", json=FARM_PAYLOAD).status_code == 401
    # 422: dữ liệu sai (quantity <= 0) -> Pydantic chặn trước khi ghi database.
    assert (
        client.post(
            "/batches",
            json={**_batch_payload(farm_id), "quantity": 0},
            auth=_auth(),
        ).status_code
        == 422
    )

    logs = _read_logs(session_factory)
    assert len(logs) == 1  # chỉ có log "tạo farm" ở đầu test
    assert (logs[0].action, logs[0].entity, logs[0].entity_id) == (
        "create",
        "farm",
        farm_id,
    )
    assert logs[0].user_id == _user_id(session_factory, TEST_USERNAME_ADMIN)


def test_api_doc_va_dang_nhap_khong_ghi_log(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """GET dữ liệu, xem log, đăng nhập (đúng/sai) đều **không** được ghi log."""
    farm = _create_farm(client)
    batch = _create_batch(client, farm["id"])

    client.get("/health")
    client.get("/farms", auth=_auth())
    client.get("/batches")
    client.get(f"/batches/{batch['id']}")
    client.get("/users", auth=_auth())
    client.get(AUDIT_LOGS_URL, auth=_auth())
    client.post(
        "/auth/login",
        json={"username": TEST_USERNAME_ADMIN, "password": TEST_PASSWORD},
    )
    client.post(
        "/auth/login",
        json={"username": TEST_USERNAME_ADMIN, "password": "mat-khau-sai"},
    )

    # Chỉ có 2 log của 2 thao tác GHI dữ liệu ở trên.
    assert len(_read_logs(session_factory)) == 2


# ------------------------------------------------- 4. API GET /audit-logs ------
def test_get_audit_logs_chi_admin(client: TestClient) -> None:
    """Admin -> 200, farmer -> 403, chưa đăng nhập -> 401."""
    _create_farm(client)

    admin_response = client.get(AUDIT_LOGS_URL, auth=_auth())
    farmer_response = client.get(AUDIT_LOGS_URL, auth=_auth(TEST_USERNAME_FARMER))
    anonymous_response = client.get(AUDIT_LOGS_URL)

    assert admin_response.status_code == 200
    assert len(admin_response.json()) == 1
    assert farmer_response.status_code == 403
    assert anonymous_response.status_code == 401


def test_chua_co_thao_tac_thi_tra_mang_rong(client: TestClient) -> None:
    """Chưa có log nào -> ``200 OK`` + mảng rỗng (không phải ``404``)."""
    assert _get_logs(client) == []


def test_khong_the_sua_hay_xoa_log_qua_api(client: TestClient) -> None:
    """Bảng log chỉ được ghi tự động: không có endpoint POST/PUT/DELETE cho nó."""
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)(AUDIT_LOGS_URL, auth=_auth())
        assert response.status_code == 405, f"{method.upper()} phải bị chặn"


def test_loc_theo_entity_va_user_id(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Bộ lọc ``?entity=`` và ``?user_id=`` trả đúng tập con của lịch sử."""
    farm = _create_farm(client, TEST_USERNAME_FARMER)
    _create_batch(client, farm["id"], TEST_USERNAME_FARMER)
    _create_batch(client, farm["id"], TEST_USERNAME_ADMIN)

    farmer_id = _user_id(session_factory, TEST_USERNAME_FARMER)
    admin_id = _user_id(session_factory, TEST_USERNAME_ADMIN)

    assert _actions(client, entity="farm") == [("create", "farm", farm["id"])]
    assert _actions(client, entity="batch") == [
        ("create", "batch", 2),
        ("create", "batch", 1),
    ]
    # Lọc theo người thực hiện.
    assert [log["username"] for log in _get_logs(client, user_id=farmer_id)] == [
        TEST_USERNAME_FARMER,
        TEST_USERNAME_FARMER,
    ]
    assert [log["username"] for log in _get_logs(client, user_id=admin_id)] == [
        TEST_USERNAME_ADMIN
    ]
    # Kết hợp cả hai bộ lọc + trường hợp không có thao tác nào.
    assert _actions(client, entity="batch", user_id=farmer_id) == [
        ("create", "batch", 1)
    ]
    assert _get_logs(client, user_id=999) == []


def test_limit_va_gia_tri_loc_khong_hop_le(client: TestClient) -> None:
    """``limit`` giới hạn số dòng; giá trị ngoài khoảng / sai kiểu -> 422."""
    for _ in range(3):
        _create_farm(client)

    assert [log["id"] for log in _get_logs(client, limit=2)] == [3, 2]
    assert len(_get_logs(client, limit=3)) == 3

    limit_zero = client.get(AUDIT_LOGS_URL, params={"limit": 0}, auth=_auth())
    limit_too_big = client.get(AUDIT_LOGS_URL, params={"limit": 501}, auth=_auth())
    bad_entity = client.get(AUDIT_LOGS_URL, params={"entity": "user"}, auth=_auth())
    bad_user_id = client.get(AUDIT_LOGS_URL, params={"user_id": 0}, auth=_auth())

    assert limit_zero.status_code == 422
    assert limit_too_big.status_code == 422
    assert bad_entity.status_code == 422
    assert bad_user_id.status_code == 422



