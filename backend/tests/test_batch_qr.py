"""Kiểm thử API tạo/tải QR mã lô (S-46)."""

import base64
import os
from datetime import date

from app.models import Batch, Organization, Plot, Product
from tests.conftest import TEST_PASSWORD, TEST_USERNAME_FARMER


def _farmer_headers():
    raw = f"{TEST_USERNAME_FARMER}:{TEST_PASSWORD}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


def _create_batch(client):
    headers = _farmer_headers()
    farm = client.post(
        "/farms",
        json={
            "name": "Vườn thử QR S-46",
            "location": "Cao Lãnh, Đồng Tháp",
            "area": 1.0,
            "owner": "HTX kiểm thử QR",
        },
        headers=headers,
    )
    assert farm.status_code == 201, farm.text
    created = client.post(
        "/batches",
        json={
            "farm_id": farm.json()["id"],
            "product_name": "Xoài kiểm thử QR S-46",
            "quantity": 20,
            "harvest_date": "2026-03-01",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_qr_download_returns_png_for_real_batch_code(client, monkeypatch):
    monkeypatch.setenv('PUBLIC_TRACE_BASE_URL', 'https://trace.example.test/trace')
    batch = _create_batch(client)
    response = client.get(f"/batches/{batch['id']}/qr", headers=_farmer_headers())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["content-disposition"] == f'inline; filename="QR-{batch["code"]}.png"'
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert batch["code"] != str(batch["id"])


def test_qr_download_requires_login(client, monkeypatch):
    monkeypatch.setenv('PUBLIC_TRACE_BASE_URL', 'https://trace.example.test/trace')
    batch = _create_batch(client)
    response = client.get(f"/batches/{batch['id']}/qr")
    assert response.status_code == 401


def test_qr_download_returns_404_for_missing_batch(client, monkeypatch):
    monkeypatch.setenv('PUBLIC_TRACE_BASE_URL', 'https://trace.example.test/trace')
    response = client.get("/batches/999999/qr", headers=_farmer_headers())
    assert response.status_code == 404


def test_qr_download_denies_user_without_batch_access(client, session_factory, monkeypatch):
    monkeypatch.setenv('PUBLIC_TRACE_BASE_URL', 'https://trace.example.test/trace')
    _create_batch(client)
    with session_factory() as db:
        other_org = Organization(name="Tổ chức QR khác", code="QR-OTHER")
        db.add(other_org)
        db.flush()
        foreign_plot = Plot(
            organization_id=other_org.id,
            name="Thửa QR ngoài phạm vi",
            location="Đồng Tháp",
            area=1.0,
            owner="Tổ chức QR khác",
        )
        db.add(foreign_plot)
        db.flush()
        product = db.query(Product).first()
        foreign_batch = Batch(
            code="FOREIGN46",
            plot_id=foreign_plot.id,
            farm_id=None,
            product_id=product.id,
            product_name="Lô ngoài phạm vi",
            harvest_date=date(2026, 3, 1),
            initial_quantity=10,
            remaining_quantity=10,
            quantity=10,
            current_org_id=other_org.id,
            status="ACTIVE",
        )
        db.add(foreign_batch)
        db.commit()
        foreign_id = foreign_batch.id

    response = client.get(f"/batches/{foreign_id}/qr", headers=_farmer_headers())
    assert response.status_code == 403


def test_qr_info_returns_clear_error_when_public_url_is_not_configured(client, monkeypatch):
    monkeypatch.delenv("PUBLIC_TRACE_BASE_URL", raising=False)
    batch = _create_batch(client)
    response = client.get(f"/batches/{batch['id']}/qr-info", headers=_farmer_headers())
    assert response.status_code == 503
    assert "PUBLIC_TRACE_BASE_URL" in response.json()["detail"]


def test_public_trace_is_available_without_login(client):
    batch = _create_batch(client)
    response = client.get(f"/public/trace/{batch['code']}")
    assert response.status_code == 200
    data = response.json()
    assert data["batch_code"] == batch["code"]
    assert data["product_name"] == "Xoài kiểm thử QR S-46"
    assert "origin" in data
    assert "root_batches" in data


def test_public_trace_returns_404_for_unknown_batch(client):
    response = client.get("/public/trace/NO-SUCH-BATCH-S46")
    assert response.status_code == 404
