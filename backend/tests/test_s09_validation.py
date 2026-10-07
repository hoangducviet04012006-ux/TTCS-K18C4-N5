"""Ki?m th? S-09 - server-side validation v? ch?ng t?o l? tr?ng."""

from datetime import date, timedelta
import re

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Batch
from tests.conftest import TEST_PASSWORD, TEST_USERNAME_FARMER


def _headers() -> dict[str, str]:
    import base64

    credentials = f"{TEST_USERNAME_FARMER}:{TEST_PASSWORD}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {encoded}"}


def _create_farm(client: TestClient) -> int:
    response = client.post(
        "/farms",
        json={
            "name": "V?ng tr?ng S-09",
            "location": "H? N?i",
            "area": 2.0,
            "owner": "HTX S-09",
        },
        headers=_headers(),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _base_payload(farm_id: int) -> dict:
    return {
        "farm_id": farm_id,
        "product_name": "Xo?i S-09",
        "quantity": 100.0,
        "harvest_date": date.today().isoformat(),
    }


def test_s09_ngay_thu_hoach_tuong_lai_bi_chan(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    farm_id = _create_farm(client)
    payload = _base_payload(farm_id)
    payload["harvest_date"] = (date.today() + timedelta(days=1)).isoformat()

    response = client.post(
        "/batches",
        json=payload,
        headers=_headers(),
    )

    assert response.status_code == 422

    with session_factory() as session:
        assert session.scalar(select(Batch.id)) is None


def test_s09_khoi_luong_bang_0_bi_chan(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    farm_id = _create_farm(client)
    payload = _base_payload(farm_id)
    payload["quantity"] = 0

    response = client.post(
        "/batches",
        json=payload,
        headers=_headers(),
    )

    assert response.status_code == 422

    with session_factory() as session:
        assert session.scalar(select(Batch.id)) is None


def test_s09_khoi_luong_am_bi_chan(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    farm_id = _create_farm(client)
    payload = _base_payload(farm_id)
    payload["quantity"] = -1

    response = client.post(
        "/batches",
        json=payload,
        headers=_headers(),
    )

    assert response.status_code == 422

    with session_factory() as session:
        assert session.scalar(select(Batch.id)) is None


def test_s09_idempotency_key_khong_tao_hai_lo(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    farm_id = _create_farm(client)
    payload = _base_payload(farm_id)
    headers = {
        **_headers(),
        "Idempotency-Key": "s09-double-click-001",
    }

    first = client.post(
        "/batches",
        json=payload,
        headers=headers,
    )
    second = client.post(
        "/batches",
        json=payload,
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 201

    first_data = first.json()
    second_data = second.json()

    assert second_data["id"] == first_data["id"]
    assert second_data["batch_code"] == first_data["batch_code"]

    with session_factory() as session:
        batches = list(session.scalars(select(Batch)).all())
        assert len(batches) == 1
        assert batches[0].id == first_data["id"]


def test_s09_lo_hop_le_tao_ma_8_ky_tu_in_hoa_de_doc(
    client: TestClient,
) -> None:
    farm_id = _create_farm(client)

    response = client.post(
        "/batches",
        json=_base_payload(farm_id),
        headers=_headers(),
    )

    assert response.status_code == 201

    data = response.json()
    batch_code = data["batch_code"]

    assert len(batch_code) == 8
    assert re.fullmatch(r"[A-HJ-NP-Z2-9]{8}", batch_code)


def test_s09_invalid_data_khong_duoc_luu(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    farm_id = _create_farm(client)
    payload = _base_payload(farm_id)
    payload["quantity"] = 0

    response = client.post(
        "/batches",
        json=payload,
        headers={
            **_headers(),
            "Idempotency-Key": "s09-invalid-001",
        },
    )

    assert response.status_code == 422

    with session_factory() as session:
        assert session.scalar(select(Batch.id)) is None
