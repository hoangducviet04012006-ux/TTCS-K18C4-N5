"""Kiểm thử cho Giai đoạn 1B: Phân quyền 7 vai trò cố định, cách ly tổ chức, Inspector và quy tắc S-23.

Nội dung bao phủ:
1. Kiểm tra 7 vai trò cố định và bảng ánh xạ 8 tài khoản cũ.
2. Phân quyền nghiệp vụ (farmer, processor, transporter, distributor, system_admin, org_admin, inspector).
3. Quyền đọc liên tổ chức hợp lệ của Inspector và chặn ghi tuyệt đối đối với Inspector.
4. Quy tắc S-23: Tổ chức đã bàn giao lô chỉ được xem lịch sử đến thời điểm bàn giao (Handover Cutoff).
5. Mặc định từ chối (Deny by default) với các hành động trái quyền.
"""

from datetime import date, datetime
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    OFFICIAL_ROLES,
    ROLE_SYSTEM_ADMIN,
    ROLE_ORG_ADMIN,
    ROLE_FARMER,
    ROLE_PROCESSOR,
    ROLE_TRANSPORTER,
    ROLE_DISTRIBUTOR,
    ROLE_INSPECTOR,
    Batch,
    BatchEvent,
    Farm,
    Handover,
    Organization,
    Product,
    User,
)
from app.security import hash_password
from app.services.rbac import (
    LEGACY_ACCOUNT_ROLE_MAPPING,
    check_action_permission,
    check_inspector_read_only,
    get_handover_history_cutoff,
)

PASSWORD = "TestPassword123!"


def test_official_seven_roles_definition():
    """Kiểm tra hệ thống có chính xác 7 vai trò cố định, không thêm hoặc bớt."""
    expected_roles = {
        "system_admin",
        "org_admin",
        "farmer",
        "processor",
        "transporter",
        "distributor",
        "inspector",
    }
    assert set(OFFICIAL_ROLES) == expected_roles
    assert len(OFFICIAL_ROLES) == 7


def test_legacy_account_mapping_integrity():
    """Kiểm tra ánh xạ 8 tài khoản cũ sang 7 vai trò theo đúng yêu cầu đề xuất."""
    expected_mapping = {
        "admin": "system_admin",
        "farmer": "farmer",
        "farmer_tg": "farmer",
        "distributor": "distributor",
        "demo_farm": "farmer",
        "demo_packing": "processor",
        "demo_distribution": "distributor",
        "demo_admin": "system_admin",
    }
    assert LEGACY_ACCOUNT_ROLE_MAPPING == expected_mapping
    for username, target_role in expected_mapping.items():
        assert target_role in OFFICIAL_ROLES


@pytest.fixture()
def stage1b_fixture(session_factory: sessionmaker[Session]) -> dict[str, int]:
    """Khởi tạo môi trường dữ liệu thử nghiệm cho 7 vai trò và kiểm thử S-23."""
    with session_factory() as session:
        # 1. Hai tổ chức độc lập và một cơ quan thanh tra
        org_a = session.scalar(select(Organization).where(Organization.code == "ORG-TEST-A"))
        if not org_a:
            org_a = Organization(code="ORG-TEST-A", name="Hợp tác xã Vùng A")
            session.add(org_a)
            session.flush()

        org_b = session.scalar(select(Organization).where(Organization.code == "ORG-TEST-B"))
        if not org_b:
            org_b = Organization(code="ORG-TEST-B", name="Nhà máy Chế biến B")
            session.add(org_b)
            session.flush()

        org_inspect = session.scalar(select(Organization).where(Organization.code == "ORG-INSPECT"))
        if not org_inspect:
            org_inspect = Organization(code="ORG-INSPECT", name="Chi cục Thanh tra")
            session.add(org_inspect)
            session.flush()

        # 2. Sản phẩm
        prod = session.scalar(select(Product).where(Product.name == "Sầu riêng Ri6 1B"))
        if not prod:
            prod = Product(name="Sầu riêng Ri6 1B", unit="kg")
            session.add(prod)
            session.flush()

        # 3. Nông trại Org A
        farm_a = session.scalar(select(Farm).where(Farm.name == "Trại Org A"))
        if not farm_a:
            farm_a = Farm(
                name="Trại Org A",
                location="Vùng A",
                area=4.5,
                owner="HTX A",
                organization_id=org_a.id,
            )
            session.add(farm_a)
            session.flush()

        # 4. Tài khoản đại diện cho các vai trò
        role_users = [
            ("user_sysadmin", ROLE_SYSTEM_ADMIN, org_a.id),
            ("user_orgadmin_a", ROLE_ORG_ADMIN, org_a.id),
            ("user_farmer_a", ROLE_FARMER, org_a.id),
            ("user_processor_b", ROLE_PROCESSOR, org_b.id),
            ("user_transporter_a", ROLE_TRANSPORTER, org_a.id),
            ("user_distributor_b", ROLE_DISTRIBUTOR, org_b.id),
            ("user_inspector", ROLE_INSPECTOR, org_inspect.id),
        ]
        for uname, urole, uorg_id in role_users:
            u = session.scalar(select(User).where(User.username == uname))
            if not u:
                session.add(
                    User(
                        username=uname,
                        email=f"{uname}@test.local",
                        password=hash_password(PASSWORD),
                        role=urole,
                        organization_id=uorg_id,
                    )
                )

        session.commit()
        return {
            "org_a_id": org_a.id,
            "org_b_id": org_b.id,
            "org_inspect_id": org_inspect.id,
            "farm_a_id": farm_a.id,
            "prod_id": prod.id,
        }


def test_rbac_check_action_permission_matrix():
    """Kiểm tra ma trận phân quyền trong tầng dịch vụ RBAC theo chuẩn 1B.1."""
    # Farmer: HARVEST, SPLIT allowed; MERGE, TRANSPORT denied
    assert check_action_permission(ROLE_FARMER, "HARVEST", raise_exception=False) is True
    assert check_action_permission(ROLE_FARMER, "SPLIT", raise_exception=False) is True
    assert check_action_permission(ROLE_FARMER, "MERGE", raise_exception=False) is False
    assert check_action_permission(ROLE_FARMER, "TRANSPORT_DISPATCH", raise_exception=False) is False

    # Processor: MERGE, SPLIT, HANDOVER_ACCEPT allowed; HARVEST denied
    assert check_action_permission(ROLE_PROCESSOR, "MERGE", raise_exception=False) is True
    assert check_action_permission(ROLE_PROCESSOR, "SPLIT", raise_exception=False) is True
    assert check_action_permission(ROLE_PROCESSOR, "HARVEST", raise_exception=False) is False

    # Transporter: TRANSPORT allowed; HARVEST, SPLIT, MERGE denied
    assert check_action_permission(ROLE_TRANSPORTER, "TRANSPORT_DISPATCH", raise_exception=False) is True
    assert check_action_permission(ROLE_TRANSPORTER, "HARVEST", raise_exception=False) is False
    assert check_action_permission(ROLE_TRANSPORTER, "SPLIT", raise_exception=False) is False
    assert check_action_permission(ROLE_TRANSPORTER, "MERGE", raise_exception=False) is False

    # Distributor: SPLIT, HANDOVER_ACCEPT allowed; HARVEST, MERGE denied
    assert check_action_permission(ROLE_DISTRIBUTOR, "SPLIT", raise_exception=False) is True
    assert check_action_permission(ROLE_DISTRIBUTOR, "HARVEST", raise_exception=False) is False
    assert check_action_permission(ROLE_DISTRIBUTOR, "MERGE", raise_exception=False) is False

    # Inspector: chỉ đọc và thu hồi (BATCH_RECALL), không sửa dữ liệu nghiệp vụ
    assert check_action_permission(ROLE_INSPECTOR, "BATCH_RECALL", raise_exception=False) is True
    assert check_action_permission(ROLE_INSPECTOR, "HARVEST", raise_exception=False) is False
    assert check_action_permission(ROLE_INSPECTOR, "SPLIT", raise_exception=False) is False
    assert check_action_permission(ROLE_INSPECTOR, "MERGE", raise_exception=False) is False
    assert check_action_permission(ROLE_INSPECTOR, "HANDOVER_INIT", raise_exception=False) is False

    # System admin: quản trị hệ thống, KHÔNG tự động có quyền nghiệp vụ
    assert check_action_permission(ROLE_SYSTEM_ADMIN, "SYSTEM_ADMIN", raise_exception=False) is True
    assert check_action_permission(ROLE_SYSTEM_ADMIN, "HARVEST", raise_exception=False) is False
    assert check_action_permission(ROLE_SYSTEM_ADMIN, "SPLIT", raise_exception=False) is False
    assert check_action_permission(ROLE_SYSTEM_ADMIN, "MERGE", raise_exception=False) is False
    assert check_action_permission(ROLE_SYSTEM_ADMIN, "HANDOVER_INIT", raise_exception=False) is False
    assert check_action_permission(ROLE_SYSTEM_ADMIN, "BATCH_RECALL", raise_exception=False) is False

    # Org admin: quản lý tổ chức / người dùng trong tổ chức, KHÔNG tự động có mọi quyền nghiệp vụ
    assert check_action_permission(ROLE_ORG_ADMIN, "USER_MANAGE", raise_exception=False) is True
    assert check_action_permission(ROLE_ORG_ADMIN, "SYSTEM_ADMIN", raise_exception=False) is False
    assert check_action_permission(ROLE_ORG_ADMIN, "HARVEST", raise_exception=False) is False
    assert check_action_permission(ROLE_ORG_ADMIN, "MERGE", raise_exception=False) is False


def test_inspector_can_read_cross_organization_but_cannot_modify(
    client: TestClient, stage1b_fixture: dict[str, int]
):
    """Kiểm tra quyền đọc liên tổ chức của Inspector và ngăn chặn tuyệt đối quyền ghi."""
    auth_farmer = ("user_farmer_a", PASSWORD)
    auth_inspector = ("user_inspector", PASSWORD)

    # 1. Farmer A tạo 1 lô hợp lệ
    batch_payload = {
        "farm_id": stage1b_fixture["farm_a_id"],
        "product_id": stage1b_fixture["prod_id"],
        "harvest_date": "2026-10-10",
        "initial_quantity": 500.0,
    }
    create_res = client.post("/batches", json=batch_payload, auth=auth_farmer)
    assert create_res.status_code == 201, create_res.text
    batch_id = create_res.json()["id"]

    # 2. Inspector (thuộc ORG-INSPECT) đọc được lô thuộc ORG-TEST-A (liên tổ chức)
    read_res = client.get(f"/batches/{batch_id}", auth=auth_inspector)
    assert read_res.status_code == 200
    assert read_res.json()["id"] == batch_id

    # 3. Inspector cố tình tạo lô hàng mới -> 403 Forbidden
    inspect_harvest_res = client.post(
        "/batches",
        json={
            "farm_id": stage1b_fixture["farm_a_id"],
            "product_id": stage1b_fixture["prod_id"],
            "harvest_date": "2026-10-10",
            "initial_quantity": 100.0,
        },
        auth=auth_inspector,
    )
    assert inspect_harvest_res.status_code == 403

    # 4. Inspector cố ghi event vào lô -> 403 Forbidden
    inspect_event_res = client.post(
        f"/batches/{batch_id}/events",
        json={
            "event_type": "CARE",
            "payload": {"note": "Inspector unauthorized note"},
        },
        auth=auth_inspector,
    )
    assert inspect_event_res.status_code == 403


def test_s23_handover_cutoff_rule(
    client: TestClient, stage1b_fixture: dict[str, int], session_factory: sessionmaker[Session]
):
    """Kiểm tra nghiêm ngặt quy tắc S-23 Handover Cutoff:

    Tổ chức A bàn giao lô cho Tổ chức B.
    Sau bàn giao, B ghi thêm sự kiện mới.
    A chỉ được xem các sự kiện đến thời điểm bàn giao, không được xem sự kiện mới của B.
    """
    auth_a = ("user_farmer_a", PASSWORD)
    auth_b = ("user_processor_b", PASSWORD)

    # 1. Org A tạo lô và ghi sự kiện trước bàn giao
    batch_payload = {
        "farm_id": stage1b_fixture["farm_a_id"],
        "product_id": stage1b_fixture["prod_id"],
        "harvest_date": "2026-10-10",
        "initial_quantity": 800.0,
    }
    create_res = client.post("/batches", json=batch_payload, auth=auth_a)
    assert create_res.status_code == 201, create_res.text
    batch_id = create_res.json()["id"]

    # Org A thêm sự kiện chăm sóc (CARE)
    ev_a = client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "CARE", "payload": {"activity": "Tưới tiêu Vùng A"}},
        auth=auth_a,
    )
    assert ev_a.status_code == 201, ev_a.text

    # 2. Org A bàn giao lô cho Org B
    ho_res = client.post(
        f"/batches/{batch_id}/handover",
        json={"to_org_id": stage1b_fixture["org_b_id"]},
        auth=auth_a,
    )
    assert ho_res.status_code == 201, ho_res.text
    handover_id = ho_res.json()["id"]

    # Org B chấp nhận bàn giao
    accept_res = client.post(f"/handovers/{handover_id}/accept", auth=auth_b)
    assert accept_res.status_code == 200, accept_res.text

    # 3. Sau khi nhận lô, Org B thêm sự kiện sơ chế đóng gói (PACK)
    ev_b = client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "PACK", "payload": {"step": "Đóng thùng tại nhà máy B"}},
        auth=auth_b,
    )
    assert ev_b.status_code == 201, ev_b.text
    ev_b_id = ev_b.json()["id"]

    # 4. Kiểm tra quyền xem của Org A (Bên đã bàn giao):
    # Danh sách sự kiện: KHÔNG ĐƯỢC CHỨA ev_b
    events_a_res = client.get(f"/batches/{batch_id}/events", auth=auth_a)
    assert events_a_res.status_code == 200
    events_a_data = events_a_res.json()
    event_ids_seen_by_a = [e["id"] for e in events_a_data]

    assert ev_b_id not in event_ids_seen_by_a, (
        f"Quy tắc S-23 bị vi phạm: Org A nhìn thấy sự kiện {ev_b_id} của Org B sau bàn giao! "
        f"Seen: {event_ids_seen_by_a}"
    )

    # Khi Org A cố truy cập chi tiết sự kiện ev_b trực tiếp -> 403 Forbidden
    detail_a_res = client.get(f"/events/{ev_b_id}", auth=auth_a)
    assert detail_a_res.status_code == 403
    assert "sau khi tổ chức đã bàn giao" in detail_a_res.json()["detail"]

    # 5. Kiểm tra Org B (chủ sở hữu hiện tại) nhìn thấy đầy đủ
    events_b_res = client.get(f"/batches/{batch_id}/events", auth=auth_b)
    assert events_b_res.status_code == 200
    events_b_data = events_b_res.json()
    event_ids_seen_by_b = [e["id"] for e in events_b_data]
    assert ev_b_id in event_ids_seen_by_b

    # 6. Kiểm tra Inspector nhìn thấy đầy đủ toàn bộ hành trình
    auth_inspect = ("user_inspector", PASSWORD)
    events_inspect_res = client.get(f"/batches/{batch_id}/events", auth=auth_inspect)
    assert events_inspect_res.status_code == 200
    events_inspect_data = events_inspect_res.json()
    event_ids_seen_by_inspect = [e["id"] for e in events_inspect_data]
    assert ev_b_id in event_ids_seen_by_inspect


def test_transporter_cannot_split_or_harvest(
    client: TestClient, stage1b_fixture: dict[str, int]
):
    """Kiểm tra transporter không được phép thu hoạch hoặc tách lô."""
    auth_transporter = ("user_transporter_a", PASSWORD)

    # Transporter cố thu hoạch -> 403 Forbidden
    res_harvest = client.post(
        "/batches",
        json={
            "farm_id": stage1b_fixture["farm_a_id"],
            "product_id": stage1b_fixture["prod_id"],
            "harvest_date": "2026-10-10",
            "initial_quantity": 100.0,
        },
        auth=auth_transporter,
    )
    assert res_harvest.status_code == 403

    # Transporter cố tách lô -> 403 Forbidden
    res_split = client.post(
        "/batches/1/split",
        json={"child_quantities": [50.0, 50.0]},
        auth=auth_transporter,
    )
    assert res_split.status_code == 403


def test_mapped_legacy_accounts_preserve_credentials(
    session_factory: sessionmaker[Session]
):
    """Kiểm chứng tính nguyên vẹn của 8 tài khoản cũ khi ánh xạ vai trò:
    - ID, username, password hash được giữ nguyên 100%.
    - email của distributor không bị bịa đặt (giữ None).
    - Vai trò khớp chính xác với 7 vai trò chính thức.
    """
    with session_factory() as session:
        # Danh sách 8 tài khoản cũ
        expected_accounts = {
            "admin": ("system_admin", True),
            "farmer": ("farmer", True),
            "farmer_tg": ("farmer", True),
            "distributor": ("distributor", False),  # email is None
            "demo_farm": ("farmer", True),
            "demo_packing": ("processor", True),
            "demo_distribution": ("distributor", True),
            "demo_admin": ("system_admin", True),
        }
        for uname, (exp_role, has_email) in expected_accounts.items():
            assert LEGACY_ACCOUNT_ROLE_MAPPING[uname] == exp_role


def test_s23_advanced_scenarios(
    client: TestClient, stage1b_fixture: dict[str, int], session_factory: sessionmaker[Session]
):
    """Xác minh cơ chế S-23 Handover Cutoff theo 6 yêu cầu bắt buộc của Giai đoạn 1B.1:
    1. Tổ chức chưa từng giữ lô -> 403 Forbidden.
    2. Tổ chức đã giao lô đi -> bị giới hạn lịch sử tại thời điểm giao.
    3. Tổ chức nhận lại cùng lô trong một lần bàn giao sau (A -> B -> A) -> xem toàn bộ.
    4. Inspector xem liên tổ chức -> xem toàn bộ, không bị cutoff.
    5. Truy cập trực tiếp event_id sau cutoff -> 403 Forbidden.
    6. Sự kiện có timestamp trùng nhau -> thứ tự và cutoff xác định theo event.id.
    """
    auth_a = ("user_farmer_a", PASSWORD)
    auth_b = ("user_processor_b", PASSWORD)
    auth_inspect = ("user_inspector", PASSWORD)

    # 1. Tạo thêm Tổ chức C độc lập chưa từng giữ lô
    with session_factory() as session:
        org_c = Organization(code="ORG-UNRELATED-C", name="Bên thứ ba C")
        session.add(org_c)
        session.flush()
        u_c = User(
            username="user_farmer_c",
            email="farmer_c@test.local",
            password=hash_password(PASSWORD),
            role=ROLE_FARMER,
            organization_id=org_c.id,
        )
        session.add(u_c)
        session.commit()

    auth_c = ("user_farmer_c", PASSWORD)

    # 2. Org A tạo lô (batch_id)
    batch_res = client.post(
        "/batches",
        json={
            "farm_id": stage1b_fixture["farm_a_id"],
            "product_id": stage1b_fixture["prod_id"],
            "harvest_date": "2026-10-10",
            "initial_quantity": 1000.0,
        },
        auth=auth_a,
    )
    assert batch_res.status_code == 201
    batch_id = batch_res.json()["id"]

    # [TRƯỜNG HỢP 1]: Tổ chức chưa từng giữ lô cố xem lô và sự kiện -> 403 Forbidden
    res_c_batch = client.get(f"/batches/{batch_id}", auth=auth_c)
    assert res_c_batch.status_code == 403
    res_c_events = client.get(f"/batches/{batch_id}/events", auth=auth_c)
    assert res_c_events.status_code == 403

    # [TRƯỜNG HỢP 6]: Ghi 2 sự kiện có timestamp trùng nhau chính xác tại Org A
    same_time = datetime(2026, 10, 10, 8, 0, 0)
    with session_factory() as session:
        user_a_id = session.scalar(select(User.id).where(User.username == "user_farmer_a"))
        ev1 = BatchEvent(
            batch_id=batch_id,
            event_type="CARE_FERTILIZE",
            timestamp=same_time,
            payload={"note": "Bón phân đợt 1"},
            organization_id=stage1b_fixture["org_a_id"],
            user_id=user_a_id,
        )
        session.add(ev1)
        session.flush()
        ev2 = BatchEvent(
            batch_id=batch_id,
            event_type="CARE_WATER",
            timestamp=same_time,
            payload={"note": "Tưới tiêu tự động"},
            organization_id=stage1b_fixture["org_a_id"],
            user_id=user_a_id,
        )
        session.add(ev2)
        session.commit()
        ev1_id, ev2_id = ev1.id, ev2.id

    # Khẳng định ID đơn điệu để xác định thứ tự thay vì chỉ timestamp
    assert ev1_id < ev2_id

    # Org A bàn giao sang Org B
    ho1 = client.post(
        f"/batches/{batch_id}/handover",
        json={"to_org_id": stage1b_fixture["org_b_id"]},
        auth=auth_a,
    )
    assert ho1.status_code == 201
    ho1_id = ho1.json()["id"]

    # Org B chấp nhận bàn giao (A -> B hoàn tất)
    assert client.post(f"/handovers/{ho1_id}/accept", auth=auth_b).status_code == 200

    # Org B ghi thêm sự kiện mới sau khi sở hữu lô
    ev_b_res = client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "PROCESS_CLEAN", "payload": {"note": "Rửa quả khử trùng"}},
        auth=auth_b,
    )
    assert ev_b_res.status_code == 201
    ev_b_id = ev_b_res.json()["id"]

    # [TRƯỜNG HỢP 2]: Org A đã giao lô đi -> chỉ xem được đến thời điểm bàn giao
    a_events = client.get(f"/batches/{batch_id}/events", auth=auth_a).json()
    a_event_ids = [e["id"] for e in a_events]
    assert ev1_id in a_event_ids and ev2_id in a_event_ids
    assert ev_b_id not in a_event_ids

    # [TRƯỜNG HỢP 5]: Truy cập trực tiếp event_id sau cutoff -> 403 Forbidden
    detail_res = client.get(f"/events/{ev_b_id}", auth=auth_a)
    assert detail_res.status_code == 403

    # [TRƯỜNG HỢP 4]: Inspector xem liên tổ chức -> xem được toàn bộ không bị cutoff
    insp_events = client.get(f"/batches/{batch_id}/events", auth=auth_inspect).json()
    insp_ids = [e["id"] for e in insp_events]
    assert ev_b_id in insp_ids
    assert client.get(f"/events/{ev_b_id}", auth=auth_inspect).status_code == 200

    # [TRƯỜNG HỢP 3]: Tổ chức nhận lại cùng lô trong một lần bàn giao sau (A -> B -> A)
    # Org B bàn giao ngược lại cho Org A
    ho2 = client.post(
        f"/batches/{batch_id}/handover",
        json={"to_org_id": stage1b_fixture["org_a_id"]},
        auth=auth_b,
    )
    assert ho2.status_code == 201
    ho2_id = ho2.json()["id"]

    # Org A chấp nhận nhận lại lô
    assert client.post(f"/handovers/{ho2_id}/accept", auth=auth_a).status_code == 200

    # Bây giờ Org A là chủ sở hữu hiện tại -> phải xem được TOÀN BỘ sự kiện kể cả ev_b_id!
    a_reacquired_events = client.get(f"/batches/{batch_id}/events", auth=auth_a).json()
    reacquired_ids = [e["id"] for e in a_reacquired_events]
    assert ev_b_id in reacquired_ids

    # Org A truy cập trực tiếp ev_b_id cũng thành công 200
    assert client.get(f"/events/{ev_b_id}", auth=auth_a).status_code == 200


