"""Recall E regression on isolated migrated fixtures; never the official DB."""

import pytest
from sqlalchemy import select, func
from app.models import Batch, BatchEvent, AuditLog
from app.hash_chain import verify_batch_chain
from app.services.audit_migration import apply_audit_schema
from tests.test_phase_c import cq, place  # noqa: F401 - reuse clean C fixture


@pytest.fixture
def eq(cq, engine):
    apply_audit_schema(engine)
    return cq


def recall(client, eq, key="e-create"):
    old = eq["user"].role
    eq["user"].role = "inspector"
    r = client.post(
        "/recalls",
        json={"root_batch_id": eq["root"], "reason": "QA isolated recall regression reason"},
        headers={"Idempotency-Key": key},
    )
    eq["user"].role = old
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.parametrize(
    "role", ["farmer", "processor", "processor", "transporter", "distributor", "inspector", "system_admin", "org_admin"]
)
def test_recall_blocks_direct_quantity_update_eight_roles(client, eq, session_factory, role):
    recall(client, eq)
    eq["user"].role = role
    with session_factory() as db:
        counts = (db.scalar(select(func.count(BatchEvent.id))), db.scalar(select(func.count(AuditLog.id))))
    r = client.put(f"/batches/{eq['root']}", json={"harvest_date": "2026-10-01", "remaining_quantity": 100, "quantity": 200})
    assert r.status_code == (403 if role in ["inspector", "system_admin"] else 409), r.text
    with session_factory() as db:
        assert db.get(Batch, eq["root"]).remaining_quantity == 100
        assert counts == (db.scalar(select(func.count(BatchEvent.id))), db.scalar(select(func.count(AuditLog.id))))
        assert verify_batch_chain(db, eq["root"])["is_valid"]


def test_recall_real_location_edges_and_filters(client, eq):
    a, b = place(client, "E-A"), place(client, "E-B")
    split = client.post(
        f"/batches/{eq['root']}/allocate-stores",
        json={"items": [{"location_id": a, "quantity": 40}, {"location_id": b, "quantity": 60}]},
    )
    assert split.status_code == 200
    data = recall(client, eq)
    assert len(data["affected_batches"]) == 3 and len(data["affected_edges"]) == 2
    assert data["filtered_metrics_by_unit"]["kg"]["reclaimable_quantity"] == "100.00"
    eq["user"].role = "inspector"
    filtered = client.get(f"/recalls/{data['id']}", params={"location_id": a}).json()
    assert len(filtered["affected_batches"]) == 1 and filtered["affected_edges"] == []
    assert filtered["affected_batches"][0]["current_location"] == "Current address E-A"
    assert filtered["affected_batches"][0]["location"] == "Origin"
    assert filtered["filtered_metrics_by_unit"]["kg"]["reclaimable_quantity"] == "40.00"
    assert filtered["metrics_by_unit"] == data["metrics_by_unit"]
    unknown = client.get(f"/recalls/{data['id']}", params={"unknown_location": True}).json()
    assert [n["batch_id"] for n in unknown["affected_batches"]] == [eq["root"]]
    assert client.get(f"/recalls/{data['id']}", params={"batch_status": "ACTIVE"}).json()["filtered_batch_count"] == 2
    assert client.get(f"/recalls/{data['id']}", params={"unknown_location": True, "location_id": a}).status_code == 422
    eq["user"].role = "org_admin"
    assert client.get(f"/recalls/{data['id']}", params={"organization_id": eq["other"]}).status_code == 403


def test_recall_pending_complete_time_reminder_and_quarantine(client, eq, session_factory):
    data = recall(client, eq)
    assert data["reminder"]["mode"] == "IN_APP_STUB" and data["reminder"]["escalation_after_hours"] == 24
    assert data["status"] == "OPEN" and data["completed_at"] is None
    eq["user"].role = "org_admin"
    complete = client.post(
        f"/recalls/{data['id']}/acknowledge", json={"notes": "QA handled own portion"}, headers={"Idempotency-Key": "e-ack"}
    )
    assert complete.status_code == 200, complete.text
    result = complete.json()
    assert (
        result["status"] == "COMPLETED" and result["completed_at"] and result["progress"] == {"acknowledged": 1, "required": 1}
    )
    assert not result["can_acknowledge"] and result["quarantined"]
    assert (
        client.put(f"/batches/{eq['root']}", json={"harvest_date": "2026-10-01", "remaining_quantity": 90}).status_code == 409
    )
    with session_factory() as db:
        assert verify_batch_chain(db, eq["root"])["is_valid"]


def test_all_inventory_actions_rollback_under_recall(client, eq, session_factory):
    a = place(client, "E-GUARD")
    recall(client, eq)
    for path, body in [
        (f"/batches/{eq['root']}/consume", {}),
        (f"/batches/{eq['root']}/split", {"child_quantities": [40, 60]}),
        (f"/batches/{eq['root']}/handover", {"to_org_id": eq["other"]}),
        (f"/batches/{eq['root']}/transfer-location", {"location_id": a}),
        (
            f"/batches/{eq['root']}/allocate-stores",
            {"items": [{"location_id": a, "quantity": 40}, {"location_id": a, "quantity": 60}]},
        ),
    ]:
        r = client.post(path, json=body)
        assert r.status_code == 409, r.text
    eq["user"].role = "processor"
    merged = client.post(
        "/batches/merge",
        json={
            "product_id": 1,
            "items": [{"parent_batch_id": eq["root"], "quantity": 10}, {"parent_batch_id": eq["zero"], "quantity": 10}],
        },
    )
    assert merged.status_code == 409, merged.text
    with session_factory() as db:
        assert db.get(Batch, eq["root"]).remaining_quantity == 100
        assert verify_batch_chain(db, eq["root"])["is_valid"]


@pytest.mark.parametrize(
    "quantity,unit,known",
    [(100, "kg", True), (100, "tan", False), (101, "kg", False), (-1, "kg", False), ("NaN", "kg", False), (None, "kg", False)],
)
def test_legacy_northern_sold_quantity_verified_without_event_rewrite(eq, session_factory, quantity, unit, known):
    from app.hash_chain import record_event
    from app.services.recall_graph import consumed_evidence

    with session_factory() as db:
        batch = db.get(Batch, eq["root"])
        batch.status = "CONSUMED"
        batch.remaining_quantity = 0
        batch.quantity = 0
        db.flush()
        event = record_event(
            db=db,
            batch_id=batch.id,
            event_type="CONSUMED",
            payload={"quantity": quantity, "unit": unit},
            org_id=batch.current_org_id,
            user_id=eq["user"].id,
        )
        db.commit()
        eid = event.id
        payload = event.payload
        original_hash = event.current_hash
        result = consumed_evidence(db, [batch])[batch.id]
        assert (result == 100) if known else result is None
        db.refresh(event)
        assert event.id == eid and event.payload == payload and event.current_hash == original_hash
        assert verify_batch_chain(db, batch.id)["is_valid"]
