"""Integration/regression coverage for account lifecycle, isolation and demo workflows."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select, text

from app.hash_chain import verify_batch_chain
from app.models import AuditLog, Batch, BatchEvent, BatchRelation, Handover, Organization, User
from app.seeds.seed_demo import seed_demo
from app.security import hash_password, verify_password

ADMIN = ("admin", "123456")
FARMER = ("farmer", "123456")
SECRET = "Local-Demo-Secret-2026!"


def account(client, **changes):
    payload = {"username": "new_farmer", "email": "new_farmer@demo.local", "password": SECRET,
               "role": "farmer", "organization_id": 1, **changes}
    return client.post("/users", json=payload, auth=ADMIN)


def harvest(client):
    farm = client.post("/farms", auth=FARMER, json={"name": "Test orchard", "location": "Dong Thap", "area": 2, "owner": "HTX"}).json()
    result = client.post("/batches", auth=("farmer", "123456"), json={"farm_id": farm["id"], "product_name": "Mango", "quantity": 100, "harvest_date": str(date.today())})
    assert result.status_code == 201, result.text
    return result.json()


def test_account_creation_assignment_login_and_audit(client, session_factory):
    with session_factory() as db:
        org = Organization(code="OTHER", name="Other organization")
        db.add(org); db.commit(); org_id = org.id
    result = account(client, organization_id=org_id)
    assert result.status_code == 201, result.text
    assert not {"password", "password_hash"} & result.json().keys()
    login = client.post("/auth/login", json={"username": "NEW_FARMER@DEMO.LOCAL", "password": SECRET})
    assert login.status_code == 200
    assert login.json()["organization_id"] == org_id
    with session_factory() as db:
        user = db.get(User, result.json()["id"])
        assert user.password.startswith("$argon2id$") and verify_password(SECRET, user.password)
        log = db.scalar(select(AuditLog).where(AuditLog.entity == "user"))
        assert log.entity_id == user.id and log.action == "create"


@pytest.mark.parametrize("body,status", [({"password": "short"}, 422), ({"email": "bad"}, 422),
    ({"role": "superadmin"}, 422), ({"organization_id": 999}, 404), ({"is_active": True}, 422)])
def test_invalid_account_input(client, body, status):
    assert account(client, **body).status_code == status


def test_identity_conflict_and_filters(client):
    first = account(client).json()
    assert account(client, username="different", email="NEW_FARMER@demo.local").status_code == 409
    assert account(client, username="NEW_FARMER", email="different@demo.local").status_code == 409
    result = client.get("/users?search=new_farmer&role=farmer&organization_id=1&limit=1", auth=ADMIN)
    assert [u["id"] for u in result.json()] == [first["id"]]
    assert client.get("/users?page=2&limit=100", auth=ADMIN).json() == []


def test_lock_disable_unlock_and_password_reset(client):
    user = account(client).json(); path = f"/users/{user['id']}"
    auth = (user["username"], SECRET)
    for changes in ({"is_locked": True}, {"is_locked": False, "is_active": False}):
        assert client.patch(path, auth=ADMIN, json=changes).status_code == 200
        assert client.get("/farms", auth=auth).status_code == 403
        assert client.post("/auth/login", json={"username": auth[0], "password": auth[1]}).status_code == 403
    assert client.patch(path, auth=ADMIN, json={"is_active": True}).status_code == 200
    assert client.get("/farms", auth=auth).status_code == 200
    reset = {"admin_password": "incorrect", "new_password": SECRET + "-new"}
    assert client.post(path + "/reset-password", auth=ADMIN, json=reset).status_code == 403
    reset["admin_password"] = ADMIN[1]
    assert client.post(path + "/reset-password", auth=ADMIN, json=reset).status_code == 200
    assert client.get("/farms", auth=auth).status_code == 401
    assert client.get("/farms", auth=(auth[0], reset["new_password"])).status_code == 200
    logs = client.get("/audit-logs?entity=user", auth=ADMIN).json()
    assert logs[0]["action"] == "reset_password" and SECRET not in str(logs)


@pytest.mark.parametrize("changes", [{"role": "farmer"}, {"is_active": False}, {"is_locked": True}])
def test_last_admin_is_protected(client, changes):
    admin = client.get("/users?role=admin", auth=ADMIN).json()[0]
    assert client.patch(f"/users/{admin['id']}", auth=ADMIN, json=changes).status_code == 409
    assert client.get("/users", auth=ADMIN).status_code == 200


def test_concurrent_admin_deactivation_keeps_one_admin(client, session_factory):
    other = account(client, username="second_admin", email="second@demo.local", role="admin").json()
    admin_id = client.get("/users?search=admin", auth=ADMIN).json()[0]["id"]
    def deactivate(pair):
        user_id, credentials = pair
        return client.patch(f"/users/{user_id}", json={"is_active": False}, auth=credentials).status_code
    with ThreadPoolExecutor(2) as pool:
        statuses = list(pool.map(deactivate, [(admin_id, ADMIN), (other["id"], ("second_admin", SECRET))]))
    assert sorted(statuses) == [200, 409]
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))) == 1


def test_farmer_cannot_manage_any_accounts(client):
    user = account(client).json()
    auth = ("farmer", "123456")
    assert client.get("/users", auth=auth).status_code == 403
    assert client.post("/users", auth=auth, json={}).status_code == 403
    assert client.patch(f"/users/{user['id']}", auth=auth, json={"role": "admin"}).status_code == 403
    assert client.post(f"/users/{user['id']}/reset-password", auth=auth, json={"admin_password": "123456", "new_password": SECRET}).status_code == 403


def test_event_endpoints_require_authentication_and_related_org(client, session_factory):
    batch = harvest(client)
    with session_factory() as db:
        org = Organization(code="UNRELATED", name="Unrelated"); db.add(org); db.flush()
        db.add(User(username="unrelated", role="farmer", organization_id=org.id, password=hash_password(SECRET)))
        db.commit()
    event_id = client.get(f"/batches/{batch['id']}/events", auth=ADMIN).json()[0]["id"]
    paths = [f"/batches/{batch['id']}/events", f"/api/batches/{batch['id']}/events",
             f"/batches/{batch['id']}/integrity", f"/events/verify/{batch['id']}", f"/events/{event_id}"]
    for path in paths:
        assert client.get(path).status_code == 401
        assert client.get(path, auth=("unrelated", SECRET)).status_code == 403
    assert client.get("/events", auth=("unrelated", SECRET)).json() == []
    assert client.get("/events").status_code == 401


def test_updates_are_validated_logged_and_do_not_replenish_split_stock(client):
    batch = harvest(client); path = f"/batches/{batch['id']}"
    payload = {"quantity": 100, "harvest_date": str(date.today())}
    assert client.put(path, auth=FARMER, json={**payload, "harvest_date": str(date.today() + timedelta(days=1))}).status_code == 400
    assert client.put(path, auth=FARMER, json={**payload, "quantity": -1}).status_code == 400
    assert client.put(path, auth=FARMER, json={**payload, "remaining_quantity": 101}).status_code == 400
    assert client.put(path, auth=FARMER, json={**payload, "quantity": 120}).status_code == 200
    events = client.get(path + "/events", auth=ADMIN).json()
    assert events[-1]["event_type"] == "BATCH_UPDATED"
    assert events[-1]["payload"]["before"]["initial_quantity"] == "100.00"
    assert client.post(path + "/split", auth=FARMER, json={"child_quantities": [20, 30]}).status_code == 201
    assert client.put(path, auth=FARMER, json={**payload, "quantity": 120}).status_code == 200
    assert client.get(path, auth=ADMIN).json()["remaining_quantity"] == 70
    assert client.put(path, auth=FARMER, json={**payload, "quantity": 130}).status_code == 409
    assert client.delete(path, auth=ADMIN).status_code == 409
    assert client.get(path + "/integrity", auth=ADMIN).json()["is_valid"]


def test_concurrent_events_form_one_chain(client):
    batch = harvest(client); path = f"/batches/{batch['id']}"
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda i: client.post(path + "/events", auth=FARMER,
            json={"event_type": "QUALITY_CHECK", "event_data": f"check {i}"}), range(2)))
    assert all(r.status_code == 201 for r in responses)
    assert client.get(path + "/integrity", auth=ADMIN).json()["total_events"] == 3


def test_hash_detects_event_metadata_tampering(client, session_factory):
    batch = harvest(client)
    with session_factory() as db:
        event = db.scalar(select(BatchEvent).where(BatchEvent.batch_id == batch["id"]))
        db.execute(text("DROP TRIGGER prevent_batch_events_update"))
        db.execute(text("UPDATE batch_events SET event_type='FORGED' WHERE id=:id"), {"id": event.id})
        db.commit()
        result = verify_batch_chain(db, batch["id"])
        assert not result["is_valid"] and result["tampered_event_id"] == event.id


def test_demo_is_repeatable_preserves_real_data_and_has_valid_flows(client, session_factory):
    real_batch = harvest(client)
    with session_factory() as db:
        real = db.get(Batch, real_batch["id"])
        before = (real.code, real.remaining_quantity, real.current_org_id)
        first = seed_demo(db, SECRET)
        counts = {model.__name__: db.scalar(select(func.count()).select_from(model))
                  for model in (User, Batch, BatchEvent, Handover, BatchRelation)}
        second = seed_demo(db, SECRET + "ignored-on-rerun")
        assert first == second
        assert counts == {model.__name__: db.scalar(select(func.count()).select_from(model)) for model in (User, Batch, BatchEvent, Handover, BatchRelation)}
        real = db.get(Batch, real_batch["id"])
        assert before == (real.code, real.remaining_quantity, real.current_org_id)
        pending = db.scalar(select(Handover).where(Handover.batch_id == first["roots"]["pending"]))
        overdue = db.scalar(select(Handover).where(Handover.batch_id == first["roots"]["overdue"]))
        assert not pending.is_overdue and overdue.is_overdue
        merged = db.get(Batch, first["trace_batch_id"])
        assert merged.remaining_quantity == 400
        actor = db.scalar(select(User).where(User.username == "demo_distribution"))
        assert merged.current_org_id == actor.organization_id
        assert verify_password(SECRET, actor.password)
    credentials = ("demo_distribution", SECRET)
    history = client.get(f"/batches/{first['trace_batch_id']}/events", auth=credentials)
    assert history.status_code == 200
    for event in history.json():
        if event["organization_id"] != actor.organization_id:
            assert event["username"] is None and "note" not in event["payload"]
    trace = client.get(f"/batches/{first['trace_batch_id']}/trace-back", auth=credentials)
    assert trace.status_code == 200 and trace.json()["root_batches"]
    assert client.get(f"/batches/{first['roots']['held']}", auth=credentials).status_code == 403


def test_demo_rejects_production_and_weak_secret(session_factory, monkeypatch):
    with session_factory() as db:
        with pytest.raises(ValueError):
            seed_demo(db, "weak")
        monkeypatch.setenv("TTCS_ENV", "production")
        with pytest.raises(RuntimeError):
            seed_demo(db, SECRET)


def test_self_password_change_revokes_old_credentials_and_audits(client):
    body = {"current_password": "wrong", "new_password": SECRET}
    assert client.post("/auth/change-password", auth=("farmer", "123456"), json=body).status_code == 403
    body["current_password"] = "123456"
    assert client.post("/auth/change-password", auth=("farmer", "123456"), json=body).status_code == 200
    assert client.get("/farms", auth=("farmer", "123456")).status_code == 401
    assert client.get("/farms", auth=("farmer", SECRET)).status_code == 200
    logs = client.get("/audit-logs?entity=user", auth=ADMIN).json()
    assert logs[0]["action"] == "change_password" and SECRET not in str(logs)


def test_basic_auth_cannot_bypass_failed_login_lockout(client):
    for _ in range(4):
        assert client.get("/farms", auth=("farmer", "wrong")).status_code == 401
    assert client.get("/farms", auth=("farmer", "wrong")).status_code == 403
    assert client.get("/farms", auth=("farmer", "123456")).status_code == 403


@pytest.mark.parametrize("quantity", [0.001, 100000000, float("inf")])
def test_quantity_schema_rejects_unrepresentable_values(quantity):
    from pydantic import ValidationError
    from app.schemas import BatchCreate, BatchSplitItem, BatchMergeItem
    with pytest.raises(ValidationError):
        BatchCreate(quantity=quantity, harvest_date=date.today())
    with pytest.raises(ValidationError):
        BatchSplitItem(quantity=quantity)
    with pytest.raises(ValidationError):
        BatchMergeItem(parent_batch_id=1, quantity=quantity)


def test_lifecycle_events_cannot_be_forged_through_annotation_api(client):
    batch = harvest(client)
    for kind in ["HARVEST", "HANDOVER_ACCEPT", "SPLIT", "MERGE", "BATCH_UPDATED"]:
        assert client.post(f"/batches/{batch['id']}/events", auth=FARMER,
                           json={"event_type": kind, "event_data": "forged"}).status_code == 400
    assert client.get(f"/batches/{batch['id']}/integrity", auth=ADMIN).json()["total_events"] == 1


def test_concurrent_handover_response_changes_owner_once(client, session_factory):
    batch = harvest(client)
    with session_factory() as db:
        org = Organization(code="RECEIVER", name="Receiver"); db.add(org); db.flush()
        db.add(User(username="receiver", role="farmer", organization_id=org.id, password=hash_password(SECRET)))
        db.commit(); org_id = org.id
    h = client.post(f"/batches/{batch['id']}/handover", auth=("farmer", "123456"), json={"to_org_id": org_id}).json()
    def respond(action):
        return client.post(f"/handovers/{h['id']}/{action}", auth=("receiver", SECRET),
                           json={"reject_reason": "Rejected for quality reasons"}).status_code
    with ThreadPoolExecutor(2) as pool:
        statuses = list(pool.map(respond, ["accept", "reject"]))
    assert sorted(statuses) == [200, 400]
    with session_factory() as db:
        handover = db.get(Handover, h["id"])
        current = db.get(Batch, batch["id"])
        assert current.current_org_id == (org_id if handover.status == "ACCEPTED" else batch["current_org_id"])
        assert verify_batch_chain(db, current.id)["total_events"] == 3


def test_handover_uses_remaining_quantity_unit_and_retains_late_accept_history(client, session_factory):
    from datetime import datetime, timezone
    from app.models import Product, ProductUnit
    from app.services.overdue_job import check_overdue_handovers
    batch = harvest(client)
    with session_factory() as db:
        product = Product(name="Rice units", unit=ProductUnit.TAN)
        org = Organization(code="UNIT_RECEIVER", name="Receiver")
        db.add_all([product, org]); db.flush()
        db.add(User(username="unit_receiver", role="farmer", organization_id=org.id,
                    password=hash_password(SECRET)))
        db.commit(); product_id, org_id = product.id, org.id
    path = f"/batches/{batch['id']}"
    assert client.put(path, auth=FARMER, json={"quantity": 100, "product_id": product_id,
                     "harvest_date": str(date.today())}).status_code == 200
    assert client.post(path + "/split", auth=("farmer", "123456"), json={"child_quantities": [30, 20]}).status_code == 201
    result = client.post(path + "/handover", auth=("farmer", "123456"), json={"to_org_id": org_id, "note": "Quality checked"})
    assert result.status_code == 201
    h = result.json()
    assert h["batch_quantity"] == 50 and h["batch_unit"] == "tấn" and h["note"] == "Quality checked"
    with session_factory() as db:
        db.get(Handover, h["id"]).created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=49)
        db.commit()
        assert check_overdue_handovers(db) == 1
    accepted = client.post(f"/handovers/{h['id']}/accept", auth=("unit_receiver", SECRET))
    assert accepted.status_code == 200 and not accepted.json()["is_overdue"]
    events = client.get(path + "/events", auth=("unit_receiver", SECRET)).json()
    assert events[-1]["payload"]["is_overdue"] is True
    assert events[-1]["payload"]["unit"] == "tấn"
    assert client.get(path + "/integrity", auth=("unit_receiver", SECRET)).json()["is_valid"]


def test_exhausted_batch_cannot_be_handed_over(client, session_factory):
    batch = harvest(client)
    with session_factory() as db:
        org = Organization(code="EMPTY_RECEIVER", name="Receiver")
        db.add(org); db.commit(); org_id = org.id
    path = f"/batches/{batch['id']}"
    assert client.post(path + "/split", auth=FARMER, json={"child_quantities": [40, 60]}).status_code == 201
    assert client.post(path + "/handover", auth=FARMER, json={"to_org_id": org_id}).status_code == 400

