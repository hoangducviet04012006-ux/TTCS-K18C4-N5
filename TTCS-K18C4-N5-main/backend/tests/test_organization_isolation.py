"""Kiểm thử tự động Sprint 1: Phân quyền tổ chức (Multi-tenant), Ràng buộc thửa đất, và Bảo mật.

Bao phủ các yêu cầu chính của Sprint 1:
1. Cô lập dữ liệu giữa 2 tổ chức (HTX Đồng Tháp vs HTX Tiền Giang):
   - Thửa đất (Farm) tự động gắn organization_id của người tạo.
   - User của tổ chức này không thể xem (GET), sửa (PUT), xóa (DELETE) thửa đất của tổ chức khác -> trả về 403 Forbidden.
   - GET /farms tự động lọc chỉ hiển thị các thửa đất thuộc tổ chức của user đang đăng nhập.
   - User không thể tạo lô nông sản (Batch) gắn với thửa đất của tổ chức khác -> trả về 403 Forbidden.
2. Ràng buộc diện tích thửa đất (area > 0):
   - Tầng Pydantic Schema: diện tích <= 0 bị từ chối với mã 422 Unprocessable Entity.
   - Tầng Database: CheckConstraint("area > 0") từ chối ghi và ném IntegrityError khi cố tình chèn dữ liệu không hợp lệ.
3. Hỗ trợ tọa độ GPS (coordinates):
   - Lưu trữ và trả về chính xác tọa độ GPS dạng chuỗi ("lat, long").
4. Khóa tài khoản 15 phút và băm mật khẩu Argon2id:
   - Nhập sai 5 lần liên tiếp -> khóa 15 phút (900 giây).
   - Lần thứ 6 dù nhập đúng mật khẩu vẫn bị chặn với mã 403 Forbidden.
   - Cơ chế băm mật khẩu sử dụng Argon2id chuẩn bảo mật cao.
"""

from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    ROLE_ADMIN,
    ROLE_FARMER,
    Farm,
    Organization,
    User,
)
from app.security import (
    LOCKOUT_DURATION,
    MAX_FAILED_LOGIN_ATTEMPTS,
    hash_password,
    verify_password,
)

PASSWORD = "test-password-123"


@pytest.fixture()
def setup_orgs_and_users(session_factory: sessionmaker[Session]) -> dict[str, int]:
    """Khởi tạo 2 tổ chức (HTX Đồng Tháp và HTX Tiền Giang) kèm các user tương ứng."""
    from sqlalchemy import select
    with session_factory() as session:
        # 1. Tìm hoặc tạo HTX Đồng Tháp
        org_dt = session.scalar(select(Organization).where(Organization.code == "HTX-DT"))
        if org_dt is None:
            org_dt = Organization(
                name="Hợp tác xã Nông sản An Toàn Đồng Tháp",
                code="HTX-DT",
                description="HTX tại Đồng Tháp",
            )
            session.add(org_dt)
            session.flush()

        # Tìm hoặc tạo HTX Tiền Giang
        org_tg = session.scalar(select(Organization).where(Organization.code == "HTX-TG"))
        if org_tg is None:
            org_tg = Organization(
                name="Hợp tác xã Nông nghiệp Sạch Tiền Giang",
                code="HTX-TG",
                description="HTX tại Tiền Giang",
            )
            session.add(org_tg)
            session.flush()

        # 2. Tạo users cho từng tổ chức nếu chưa có
        for username, role, org_id in [
            ("admin_dt", ROLE_ADMIN, org_dt.id),
            ("farmer_dt", ROLE_FARMER, org_dt.id),
            ("farmer_tg", ROLE_FARMER, org_tg.id),
            ("admin_tg", ROLE_ADMIN, org_tg.id),
        ]:
            if not session.scalar(select(User).where(User.username == username)):
                session.add(
                    User(
                        email=f"{username}@gmail.com",
                        username=username,
                        password=hash_password(PASSWORD),
                        role=role,
                        organization_id=org_id,
                    )
                )
        session.flush()

        # 3. Tạo sẵn 1 thửa đất thuộc HTX Tiền Giang
        farm_tg = Farm(
            name="Vườn sầu riêng Cai Lậy",
            location="Cai Lậy, Tiền Giang",
            area=3.5,
            owner="HTX Tiền Giang",
            coordinates="10.4123, 106.0123",
            organization_id=org_tg.id,
        )
        session.add(farm_tg)
        session.commit()

        return {
            "org_dt_id": org_dt.id,
            "org_tg_id": org_tg.id,
            "farm_tg_id": farm_tg.id,
        }


# ==============================================================================
# 1. TEST CÔ LẬP DỮ LIỆU TỔ CHỨC (MULTI-TENANT DATA ISOLATION)
# ==============================================================================

def test_tao_thua_dat_tu_dong_gan_organization_id(
    client: TestClient, setup_orgs_and_users: dict[str, int]
) -> None:
    """Tạo thửa đất mới sẽ tự động gán organization_id của user đang đăng nhập."""
    payload = {
        "name": "Vườn xoài Cát Chu Tháp Mười",
        "location": "Tháp Mười, Đồng Tháp",
        "area": 2.5,
        "owner": "Nông dân Nguyễn Văn A",
        "coordinates": "10.5432, 105.7890",
    }
    response = client.post("/farms", json=payload, auth=("farmer_dt", PASSWORD))
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == payload["name"]
    assert data["area"] == payload["area"]
    assert data["coordinates"] == payload["coordinates"]
    assert data["organization_id"] == setup_orgs_and_users["org_dt_id"]


def test_danh_sach_thua_dat_tu_dong_loc_theo_to_chuc(
    client: TestClient, setup_orgs_and_users: dict[str, int]
) -> None:
    """GET /farms chỉ hiển thị các thửa đất thuộc tổ chức của user đang đăng nhập."""
    # Farmer ĐT tạo 1 thửa đất của HTX Đồng Tháp
    client.post(
        "/farms",
        json={
            "name": "Vườn xoài Cao Lãnh",
            "location": "Cao Lãnh, Đồng Tháp",
            "area": 1.8,
            "owner": "HTX Đồng Tháp",
            "coordinates": "10.4500, 105.6300",
        },
        auth=("farmer_dt", PASSWORD),
    )

    # Farmer ĐT truy vấn danh sách -> chỉ thấy thửa đất của HTX Đồng Tháp
    resp_dt = client.get("/farms", auth=("farmer_dt", PASSWORD))
    assert resp_dt.status_code == 200
    farms_dt = resp_dt.json()
    assert len(farms_dt) == 1
    assert farms_dt[0]["name"] == "Vườn xoài Cao Lãnh"
    assert farms_dt[0]["organization_id"] == setup_orgs_and_users["org_dt_id"]

    # Farmer TG truy vấn danh sách -> chỉ thấy thửa đất của HTX Tiền Giang (đã tạo ở fixture)
    resp_tg = client.get("/farms", auth=("farmer_tg", PASSWORD))
    assert resp_tg.status_code == 200
    farms_tg = resp_tg.json()
    assert len(farms_tg) == 1
    assert farms_tg[0]["name"] == "Vườn sầu riêng Cai Lậy"
    assert farms_tg[0]["organization_id"] == setup_orgs_and_users["org_tg_id"]


def test_truy_cap_cheo_thua_dat_to_chuc_khac_bi_chan_403(
    client: TestClient, setup_orgs_and_users: dict[str, int]
) -> None:
    """User thuộc HTX Đồng Tháp không thể xem chi tiết, sửa hoặc xóa thửa đất của HTX Tiền Giang."""
    farm_tg_id = setup_orgs_and_users["farm_tg_id"]

    # 1. Farmer ĐT cố tình GET thửa đất của Tiền Giang -> 403 Forbidden
    resp_get = client.get(f"/farms/{farm_tg_id}", auth=("farmer_dt", PASSWORD))
    assert resp_get.status_code == 403
    assert "tổ chức khác" in resp_get.json()["detail"]

    # 2. Farmer ĐT cố tình PUT sửa thửa đất của Tiền Giang -> 403 Forbidden
    resp_put = client.put(
        f"/farms/{farm_tg_id}",
        json={
            "name": "Chiếm quyền sửa vườn",
            "location": "Đồng Tháp",
            "area": 5.0,
            "owner": "Hacker",
            "coordinates": "10.0, 105.0",
        },
        auth=("farmer_dt", PASSWORD),
    )
    assert resp_put.status_code == 403
    assert "tổ chức khác" in resp_put.json()["detail"]

    # 3. Admin ĐT cố tình DELETE thửa đất của Tiền Giang -> 403 Forbidden
    resp_del = client.delete(f"/farms/{farm_tg_id}", auth=("admin_dt", PASSWORD))
    assert resp_del.status_code == 403
    assert "tổ chức khác" in resp_del.json()["detail"]


def test_tao_lo_nong_san_cheo_to_chuc_bi_chan_403(
    client: TestClient, setup_orgs_and_users: dict[str, int]
) -> None:
    """User thuộc HTX Đồng Tháp không thể tạo lô nông sản trên thửa đất của HTX Tiền Giang."""
    farm_tg_id = setup_orgs_and_users["farm_tg_id"]

    batch_payload = {
        "farm_id": farm_tg_id,
        "product_name": "Xoài giả mạo",
        "quantity": 100.0,
        "harvest_date": "2026-03-01",
    }
    response = client.post("/batches", json=batch_payload, auth=("farmer_dt", PASSWORD))
    assert response.status_code == 403
    assert "tổ chức khác" in response.json()["detail"]


# ==============================================================================
# 2. TEST RÀNG BUỘC DIỆN TÍCH THỬA ĐẤT (AREA > 0)
# ==============================================================================

def test_dien_tich_bang_khong_bi_tu_choi_o_tang_pydantic(
    client: TestClient, setup_orgs_and_users: dict[str, int]
) -> None:
    """POST /farms với area = 0 bị từ chối với mã 422 (Pydantic validation)."""
    payload = {
        "name": "Thửa đất không diện tích",
        "location": "Đồng Tháp",
        "area": 0.0,
        "owner": "Nguyễn Văn A",
    }
    response = client.post("/farms", json=payload, auth=("farmer_dt", PASSWORD))
    assert response.status_code == 422


def test_dien_tich_am_bi_tu_choi_o_tang_pydantic(
    client: TestClient, setup_orgs_and_users: dict[str, int]
) -> None:
    """POST /farms với area âm (< 0) bị từ chối với mã 422."""
    payload = {
        "name": "Thửa đất diện tích âm",
        "location": "Đồng Tháp",
        "area": -1.5,
        "owner": "Nguyễn Văn A",
    }
    response = client.post("/farms", json=payload, auth=("farmer_dt", PASSWORD))
    assert response.status_code == 422


def test_dien_tich_be_hon_hoac_bang_khong_bi_tu_choi_o_database(
    session_factory: sessionmaker[Session], setup_orgs_and_users: dict[str, int]
) -> None:
    """Database CheckConstraint 'check_farm_area_positive' chặn ghi diện tích <= 0."""
    with session_factory() as session:
        farm_invalid = Farm(
            name="Thửa lách luật DB",
            location="Đồng Tháp",
            area=0.0,
            owner="Tester",
            organization_id=setup_orgs_and_users["org_dt_id"],
        )
        session.add(farm_invalid)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


# ==============================================================================
# 3. TEST KHÓA TÀI KHOẢN 15 PHÚT VÀ LẦN THỨ 6 NHẬP ĐÚNG VẪN BỊ CHẶN
# ==============================================================================

def test_khoa_tai_khoan_15_phut_va_lan_thu_6_dung_pass_van_bi_chan(
    client: TestClient, setup_orgs_and_users: dict[str, int]
) -> None:
    """Nhập sai 5 lần -> khóa 15 phút (900s). Lần thứ 6 dù nhập đúng pass vẫn nhận 403."""
    assert LOCKOUT_DURATION == timedelta(minutes=15)

    # 1. Nhập sai 5 lần liên tiếp
    for attempt in range(1, MAX_FAILED_LOGIN_ATTEMPTS + 1):
        resp = client.post(
            "/auth/login",
            json={"email": "farmer_dt@gmail.com", "password": "wrong-password"},
        )
        if attempt < MAX_FAILED_LOGIN_ATTEMPTS:
            assert resp.status_code == 401
        else:
            # Lần thứ 5: tài khoản chính thức bị khóa 15 phút
            assert resp.status_code == 403
            assert "khóa" in resp.json()["detail"] or "khoá" in resp.json()["detail"]
            assert "15 phút" in resp.json()["detail"]
            retry_after = int(resp.headers.get("Retry-After", 0))
            assert 0 < retry_after <= 900

    # 2. Lần thứ 6: nhập ĐÚNG mật khẩu nhưng vẫn trong thời gian khóa -> vẫn bị chặn 403
    resp_6 = client.post(
        "/auth/login",
        json={"email": "farmer_dt@gmail.com", "password": PASSWORD},
    )
    assert resp_6.status_code == 403
    assert "khóa" in resp_6.json()["detail"] or "khoá" in resp_6.json()["detail"]


# ==============================================================================
# 4. TEST BĂM MẬT KHẨU ARGON2ID
# ==============================================================================

def test_argon2id_password_hashing() -> None:
    """Mật khẩu được băm bằng thuật toán Argon2id chuẩn ($argon2id$)."""
    plain = "MySecretPass@2026"
    hashed = hash_password(plain)

    # Định dạng hash Argon2id luôn bắt đầu bằng $argon2id$v=19$
    assert hashed.startswith("$argon2id$v=19$")
    assert verify_password(plain, hashed) is True
    assert verify_password("wrong-pass", hashed) is False
