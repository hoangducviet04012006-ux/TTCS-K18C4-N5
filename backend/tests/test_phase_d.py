"""S-31 audit metadata/permissions and S-29 where; isolated migrated QA fixtures."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from app.audit import record_action, fetch_audit_logs
from app.main import app
from app.models import AuditLog, Batch, User
from app.services.audit_migration import apply_audit_schema
from app.services.audit_metadata import request_ip
from tests.test_phase_c import cq, place  # noqa: F401 - shared clean Phase C fixture


@pytest.fixture
def dq(cq, engine):
    apply_audit_schema(engine)
    return cq


def logs(client, dq, **params):
    role = dq["user"].role
    dq["user"].role = "inspector"
    response = client.get("/audit-logs", params=params)
    dq["user"].role = role
    assert response.status_code == 200, response.text
    return response.json()


def test_consume_where_ip_immutable_snapshot(client, dq, session_factory):
    loc = place(client, "D-STORE")
    assert client.post(f"/batches/{dq['root']}/transfer-location", json={"location_id": loc}).status_code == 200

    async def connection_app(scope, receive, send):
        scope["client"] = ("192.0.2.5", 1234)
        await app(scope, receive, send)

    actual = TestClient(connection_app)
    response = actual.post(f"/batches/{dq['root']}/consume", json={}, headers={"X-Forwarded-For": "203.0.113.99"})
    assert response.status_code == 200, response.text
    rows = logs(client, dq, batch_id=dq["root"])
    sold = next(row for row in rows if row["operation"] == "sell_out")
    assert sold["source_ip"] == "192.0.2.5"
    assert sold["user_id"] == dq["user"].id and sold["created_at"]
    assert sold["location_id"] == loc and sold["location_address"] == "Current address D-STORE"
    assert client.patch(f"/organizations/locations/{loc}", json={"name": "Renamed", "address": "Changed"}).status_code == 200
    assert next(r for r in logs(client, dq) if r["id"] == sold["id"]) == sold
    count = len(logs(client, dq))
    assert client.post(f"/batches/{dq['root']}/consume", json={}).status_code == 400
    assert len(logs(client, dq)) == count


def test_consume_unknown_location_null(client, dq):
    assert client.post(f"/batches/{dq['root']}/consume", json={}).status_code == 200
    sold = logs(client, dq, batch_id=dq["root"])[0]
    assert sold["operation"] == "sell_out"
    assert sold["location_id"] is None and sold["location_address"] is None and sold["source_ip"] is None


@pytest.mark.parametrize(
    "role", ["farmer", "processor", "processor", "transporter", "distributor", "inspector", "system_admin", "org_admin"]
)
def test_eight_account_audit_policy(client, dq, role):
    dq["user"].role = role
    response = client.get("/audit-logs")
    assert response.status_code == (200 if role in {"inspector", "system_admin", "org_admin"} else 403)


def test_scope_snapshot_user_and_lot_filter_before_pagination(client, dq, session_factory):
    with session_factory() as db:
        actor = db.get(User, dq["user"].id)
        own = record_action(db, actor, "update", "batch", dq["root"], operation="split", batch_ids=[dq["root"], dq["zero"]])
        actor.organization_id = dq["other"]
        foreign = record_action(db, actor, "update", "batch", dq["zero"], operation="sell_out", batch_ids=[dq["zero"]])
        db.commit()
        own_id, foreign_id = own.id, foreign.id
    dq["user"].role = "org_admin"
    response = client.get("/audit-logs", params={"user_id": dq["user"].id, "batch_id": dq["zero"], "limit": 1})
    assert response.status_code == 200 and [r["id"] for r in response.json()] == [own_id]
    assert foreign_id not in [r["id"] for r in client.get("/audit-logs").json()]
    assert client.get("/audit-logs", params={"offset": 1, "batch_id": dq["zero"]}).json() == []
    for params in [{"batch_id": 0}, {"offset": -1}, {"limit": 501}]:
        assert client.get("/audit-logs", params=params).status_code == 422


def test_allocation_and_merge_lot_links(client, dq):
    a, b = place(client, "D-A"), place(client, "D-B")
    response = client.post(
        f"/batches/{dq['root']}/allocate-stores",
        json={"items": [{"location_id": a, "quantity": 40}, {"location_id": b, "quantity": 60}]},
    )
    assert response.status_code == 200, response.text
    children = response.json()["child_batches"]
    assert all(
        any(
            r["operation"] == "allocate_store" and c["id"] in r["batch_ids"] and dq["root"] in r["batch_ids"]
            for r in logs(client, dq, batch_id=c["id"])
        )
        for c in children
    )
    dq["user"].role = "processor"
    merged = client.post(
        "/batches/merge",
        json={
            "product_id": children[0]["product_id"],
            "items": [{"parent_batch_id": c["id"], "quantity": c["remaining_quantity"]} for c in children],
        },
    )
    assert merged.status_code == 201, merged.text
    for child in children:
        assert any(
            r["operation"] == "merge" and all(c["id"] in r["batch_ids"] for c in children)
            for r in logs(client, dq, batch_id=child["id"])
        )


def test_handover_all_actions_and_historical_scope(client, dq):
    initiated = client.post(f"/batches/{dq['root']}/handover", json={"to_org_id": dq["other"]})
    assert initiated.status_code == 201, initiated.text
    hid = initiated.json()["id"]
    dq["user"].role = "processor"
    dq["user"].organization_id = dq["other"]
    reject = client.post(f"/handovers/{hid}/reject", json={"reject_reason": "QA rejecting this lot safely"})
    assert reject.status_code == 200, reject.text
    dq["user"].role = "distributor"
    dq["user"].organization_id = dq["org"]
    again = client.post(f"/batches/{dq['root']}/handover", json={"to_org_id": dq["other"]})
    assert again.status_code == 201
    dq["user"].role = "processor"
    dq["user"].organization_id = dq["other"]
    assert client.post(f"/handovers/{again.json()['id']}/accept").status_code == 200
    operations = {r["operation"] for r in logs(client, dq, batch_id=dq["root"])}
    assert {"handover_init", "handover_accept", "handover_reject"} <= operations


def test_recall_confirm_audit_queryable_no_duplicate_on_replay(client, dq):
    dq["user"].role = "inspector"
    response = client.post(
        "/recalls",
        json={"root_batch_id": dq["root"], "reason": "QA audit inspection only"},
        headers={"Idempotency-Key": "d-recall"},
    )
    assert response.status_code == 201, response.text
    rid = response.json()["id"]
    dq["user"].role = "org_admin"
    confirmed = client.post(
        f"/recalls/{rid}/acknowledge", json={"notes": "QA confirmed"}, headers={"Idempotency-Key": "d-ack"}
    )
    assert confirmed.status_code == 200, confirmed.text
    operations = {r["operation"] for r in logs(client, dq, entity="recall", batch_id=dq["root"])}
    assert {"recall", "confirm", "recall_complete"} <= operations
    count = len(logs(client, dq))
    assert (
        client.post(
            f"/recalls/{rid}/acknowledge", json={"notes": "QA confirmed"}, headers={"Idempotency-Key": "d-ack"}
        ).status_code
        == 200
    )
    assert len(logs(client, dq)) == count


def test_migration_preserves_old_rows_and_rollback(engine, session_factory, cq):
    with session_factory() as db:
        record_action(db, db.get(User, cq["user"].id), "create", "batch", cq["root"])
        db.commit()
        before = db.execute(text("SELECT id,user_id,action,entity,entity_id,created_at FROM audit_logs ORDER BY id")).all()
    apply_audit_schema(engine)
    apply_audit_schema(engine)
    with session_factory() as db:
        after = db.execute(text("SELECT id,user_id,action,entity,entity_id,created_at FROM audit_logs ORDER BY id")).all()
        assert before == after
        old = fetch_audit_logs(db)[0]
        assert old.source_ip is None and old.operation is None and old.batch_ids == []
        record_action(db, db.get(User, cq["user"].id), "update", "batch", cq["root"], operation="sell_out")
        db.rollback()
        assert len(fetch_audit_logs(db)) == 1


def test_system_admin_foreign_target_not_exposed_to_org_admin(client, dq, session_factory):
    with session_factory() as db:
        actor = db.get(User, dq["user"].id)
        actor.role = "system_admin"
        foreign = User(username="d_foreign", password="unused", role="farmer", organization_id=dq["other"])
        db.add(foreign)
        db.flush()
        row = record_action(db, actor, "update", "user", foreign.id, operation="reset_password")
        db.commit()
        row_id = row.id
    dq["user"].role = "org_admin"
    assert row_id not in [r["id"] for r in client.get("/audit-logs").json()]
    assert row_id in [r["id"] for r in logs(client, dq)]
