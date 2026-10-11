"""Regression for approved Sprint 1–3 RBAC fixes, on fixture databases only."""
from datetime import date

import pytest

from app.models import AuditLog, Batch, Farm, Organization, Plot, Product, User
from app.security import hash_password
from tests.conftest import TEST_PASSWORD


ACCOUNTS = [
    ("farm", "farmer", 1), ("packing", "processor", 1),
    ("receiver", "processor", 2), ("transport", "transporter", 2),
    ("distribution", "distributor", 3), ("inspector", "inspector", None),
    ("admin", "system_admin", 1), ("org_admin", "org_admin", 1),
]


@pytest.fixture
def rbac_data(client, session_factory):
    with session_factory() as db:
        db.add_all([Organization(id=2, code="RBAC2", name="RBAC 2"),
                    Organization(id=3, code="RBAC3", name="RBAC 3")])
        password = hash_password(TEST_PASSWORD)
        db.add_all([User(username="rbac_" + name, role=role,
                         organization_id=org, password=password) for name, role, org in ACCOUNTS])
        product = Product(name="RBAC produce", unit="kg")
        db.add(product)
        db.flush()
        for org in [1, 2, 3]:
            db.add(Farm(id=org, organization_id=org, name=f"Farm {org}", location="Test", area=1, owner="Test"))
            db.add(Plot(id=org, organization_id=org, name=f"Plot {org}", location="Test", area=1, owner="Test"))
        db.flush()
        for org in [1, 2, 3]:
            db.add(Batch(id=org, code=f"RBAC-{org}", farm_id=org, plot_id=org,
                         product_id=product.id, product_name=product.name, current_org_id=org,
                         initial_quantity=100, remaining_quantity=100, quantity=100,
                         harvest_date=date(2026, 1, 1), status="ACTIVE"))
        db.commit()
        return {"product": product.id}


def auth(account):
    return "rbac_" + account, TEST_PASSWORD


@pytest.mark.parametrize("account,role,org", ACCOUNTS)
def test_eight_account_action_matrix(client, rbac_data, account, role, org):
    credentials = auth(account)
    target = org or 1
    farm_payload = {"name": "Changed", "location": "Test", "area": 2, "owner": "Test"}
    manage = role in {"farmer", "org_admin"}
    assert client.post("/farms", auth=credentials, json=farm_payload).status_code == (201 if manage else 403)
    assert client.put(f"/farms/{target}", auth=credentials, json=farm_payload).status_code == (200 if manage else 403)
    assert client.post("/products", auth=credentials, json={"name": "New shared product", "unit": "kg"}).status_code == (201 if role == "system_admin" else 403)
    operational = role not in {"system_admin", "inspector"}
    assert client.put(f"/batches/{target}", auth=credentials, json={"harvest_date": "2026-01-01"}).status_code == (200 if operational else 403)
    assert client.post(f"/batches/{target}/events", auth=credentials,
                       json={"event_type": "QUALITY_CHECK", "event_data": "Test"}).status_code == (201 if operational else 403)
    assert client.post("/batches", auth=credentials,
                       json={"farm_id": target, "product_id": rbac_data["product"],
                             "quantity": 10, "harvest_date": "2026-01-01"}).status_code == (201 if role == "farmer" else 403)
    summary = client.get(f"/batches/{target}/summary", auth=credentials)
    assert summary.status_code == 200
    assert summary.json()["can_split"] == (role in {"farmer", "processor", "distributor"})
    assert summary.json()["can_merge"] == (role == "processor")
    assert summary.json()["can_handover"] == (role in {"farmer", "processor", "transporter", "distributor"})
    if not manage:
        assert client.put("/farms/999", auth=credentials, json=farm_payload).status_code == 403
    if role in {"system_admin", "inspector"}:
        assert client.put("/batches/999", auth=credentials, json={"harvest_date": "2026-01-01"}).status_code == 403


def test_org_audit_scope_filters_before_limit_and_hides_foreign_targets(client, rbac_data, session_factory):
    with session_factory() as db:
        own = db.query(User).filter_by(username="rbac_farm").one()
        other = db.query(User).filter_by(username="rbac_receiver").one()
        logs = [AuditLog(user_id=own.id, entity="farm", entity_id=1, action="create"),
                AuditLog(user_id=other.id, entity="farm", entity_id=2, action="create"),
                AuditLog(user_id=own.id, entity="farm", entity_id=2, action="update"),
                AuditLog(user_id=own.id, entity="farm", entity_id=999, action="delete")]
        db.add_all(logs); db.commit()
        own_id, other_id = own.id, other.id
    rows = client.get("/audit-logs?limit=1", auth=auth("org_admin"))
    assert rows.status_code == 200
    assert len(rows.json()) == 1
    assert rows.json()[0]["user_id"] == own_id
    assert rows.json()[0]["entity_id"] == 1
    assert client.get(f"/audit-logs?entity=farm&user_id={other_id}", auth=auth("org_admin")).status_code == 403
    assert client.get("/audit-logs?user_id=999", auth=auth("org_admin")).status_code == 403
    for account in ["admin", "inspector"]:
        assert len(client.get("/audit-logs", auth=auth(account)).json()) == 4


def test_cross_organization_and_unauthenticated_requests(client, rbac_data):
    payload = {"name": "Changed", "location": "Test", "area": 2, "owner": "Test"}
    assert client.put("/farms/2", auth=auth("org_admin"), json=payload).status_code == 403
    assert client.put("/batches/2", auth=auth("farm"), json={"harvest_date": "2026-01-01"}).status_code == 403
    assert client.get("/batches/2", auth=auth("farm")).status_code == 403
    assert client.get("/batches/2", auth=auth("inspector")).status_code == 200
    assert client.post("/farms", json=payload).status_code == 401
    assert client.get("/audit-logs").status_code == 401
