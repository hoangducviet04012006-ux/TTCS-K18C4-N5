"""Recall S-33..S-39 API tests, exclusively against per-test SQLite files."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import threading

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, create_event_immutability_triggers, get_db
from app.hash_chain import verify_batch_chain
from app.main import app
from app.models import AuditLog, Batch, BatchEvent, BatchRelation, Handover, Organization, User
from app.recall_models import IdempotencyRecord, Recall, RecallAcknowledgment
from app.security import hash_password
from app.services import recall as service
from app.services import recall_graph
from app.services.recall_database import is_protected_engine
from scripts.prepare_recall_test_database import prepare
from scripts.seed_recall_s39 import seed_recall_s39

PASSWORD = "RecallTestPassword123!"
HASHED_PASSWORD = hash_password(PASSWORD)
REASON = "Unsafe pesticide residue detected in this batch"


@pytest.fixture
def engine(tmp_path):
    """Seed memory and backup to a fresh file; independent DBAPI connections for races."""
    memory = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(memory)
    with Session(memory) as db:
        seed_recall_s39(db)
        orgs = {org.code: org.id for org in db.scalars(select(Organization)).all()}
        other = Organization(code="OTHER", name="Unrelated secret org")
        db.add(other)
        db.flush()
        roles = [
            ("inspector", "inspector", None), ("system", "system_admin", None),
            ("farm_admin", "org_admin", orgs["ORG-FARM"]),
            ("proc_admin", "org_admin", orgs["ORG-PROC"]),
            ("dist_admin", "org_admin", orgs["ORG-DIST"]),
            ("outsider", "org_admin", other.id),
            ("farmer", "farmer", orgs["ORG-FARM"]),
            ("processor", "processor", orgs["ORG-PROC"]),
            ("distributor", "distributor", orgs["ORG-DIST"]),
            ("transporter", "transporter", orgs["ORG-PROC"]),
        ]
        db.add_all([User(username=name, email=name+"@recall.invalid", password=HASHED_PASSWORD,
                         role=role, organization_id=org) for name, role, org in roles])
        db.commit()
    path = tmp_path / "recall_api.db"
    raw = memory.raw_connection()
    with sqlite3.connect(path) as disk:
        raw.driver_connection.backup(disk)
    raw.close()
    memory.dispose()
    engine = create_engine("sqlite:///" + path.as_posix(), connect_args={"check_same_thread": False, "timeout": 10})
    @event.listens_for(engine, "connect")
    def enable_fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    create_event_immutability_triggers(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def ids(session_factory):
    with session_factory() as db:
        return {batch.code: batch.id for batch in db.scalars(select(Batch)).all()}


@pytest.fixture
def users():
    # The module's engine fixture already supplies the complete role matrix.
    return []


def post_recall(client, root, actor="inspector", key="create-1", reason=REASON):
    return client.post("/recalls", json={"root_batch_id": root, "reason": reason},
                       auth=(actor, PASSWORD), headers={"Idempotency-Key": key})


def ack(client, recall_id, actor, key=None, notes="Removed from shelves"):
    return client.post(f"/recalls/{recall_id}/acknowledge", json={"notes": notes},
                       auth=(actor, PASSWORD), headers={"Idempotency-Key": key or actor+"-ack"})


def completed(client, ids):
    response = post_recall(client, ids["S39-ROOT-A"])
    assert response.status_code == 201, response.text
    recall_id = response.json()["id"]
    for actor in ("farm_admin", "proc_admin", "dist_admin"):
        response = ack(client, recall_id, actor)
        assert response.status_code == 200, response.text
    assert response.json()["status"] == "COMPLETED"
    return recall_id


def counts(db):
    return {model.__tablename__: len(db.scalars(select(model)).all())
            for model in (Recall, RecallAcknowledgment, IdempotencyRecord, BatchEvent, AuditLog)}


def add_child(db, parent, code, org_id=None):
    child = Batch(code=code, plot_id=parent.plot_id, farm_id=None, product_id=parent.product_id,
                  harvest_date=date(2026, 10, 10), initial_quantity=Decimal("10"),
                  remaining_quantity=Decimal("10"), current_org_id=org_id or parent.current_org_id)
    db.add(child)
    db.flush()
    db.add(BatchRelation(parent_batch_id=parent.id, child_batch_id=child.id,
                         transferred_quantity=Decimal("10"), relation_type="SPLIT"))
    db.flush()
    return child.id


def test_s39_api_oracle_events_and_original_status(client, ids, session_factory):
    with session_factory() as db:
        before = {b.id: b.status for b in db.scalars(select(Batch)).all()}
        old_events = [(e.id, e.current_hash, e.payload) for e in db.scalars(select(BatchEvent)).all()]
    response = post_recall(client, ids["S39-ROOT-A"])
    assert response.status_code == 201, response.text
    data = response.json()
    oracle = json.loads((Path(__file__).parent/"fixtures/recall_s39_ground_truth.json").read_text(encoding="utf-8"))
    assert len(data["affected_batches"]) == 1 + oracle["expected_total_descendants"]
    assert data["metrics_by_unit"]["kg"]["reclaimable_quantity"] == "600.00"
    assert Decimal(data["metrics_by_unit"]["kg"]["consumed_quantity"]) == Decimal("600")
    assert data["progress"] == {"acknowledged": 0, "required": 3}
    assert sum(n["is_merged_cross_origin"] for n in data["affected_batches"]) == 3
    actual = {n["code"]: n for n in data["affected_batches"]}
    for expected in oracle["descendants"]:
        node = actual[expected["code"]]
        assert Decimal(node["remaining_quantity"]) == Decimal(str(expected["remaining_quantity"]))
        assert node["level"] == expected["level"] and node["status"] == expected["status"]
    with session_factory() as db:
        assert {b.id: b.status for b in db.scalars(select(Batch)).all()} == before
        assert [(db.get(BatchEvent, eid).id, db.get(BatchEvent, eid).current_hash, db.get(BatchEvent, eid).payload) for eid, _, _ in old_events] == old_events
        events = list(db.scalars(select(BatchEvent).where(BatchEvent.event_type.like("RECALL%"))).all())
        assert [e.event_type for e in events].count("RECALL_INIT") == 1
        assert [e.event_type for e in events].count("RECALL_AFFECTED") == 5
        for batch_id in ids.values(): assert verify_batch_chain(db, batch_id)["is_valid"]
        assert counts(db)["audit_logs"] == 1


@pytest.mark.parametrize("actor,allowed", [("inspector", True), ("farm_admin", True), ("proc_admin", False),
                                          ("system", False), ("farmer", False), ("processor", False),
                                          ("distributor", False), ("transporter", False), ("outsider", False)])
def test_create_roles(client, ids, actor, allowed):
    response = post_recall(client, ids["S39-ROOT-A"], actor=actor)
    assert response.status_code == (201 if allowed else 403), response.text


def test_create_validation_and_missing_root(client, ids):
    for reason in ["short", " " * 30]:
        assert post_recall(client, ids["S39-ROOT-A"], reason=reason).status_code == 422
    assert post_recall(client, 999999).status_code == 404
    assert client.post("/recalls", auth=("inspector", PASSWORD), json={"root_batch_id": ids["S39-ROOT-A"], "reason": REASON}).status_code == 422


def test_duplicate_root_lifetime_and_idempotency(client, ids, session_factory):
    first = post_recall(client, ids["S39-ROOT-A"])
    replay = post_recall(client, ids["S39-ROOT-A"])
    assert replay.status_code == 201 and replay.json() == first.json()
    conflict = post_recall(client, ids["S39-ROOT-A"], key="different")
    assert conflict.status_code == 409 and conflict.json()["detail"]["recall_code"] == first.json()["recall_code"]
    assert post_recall(client, ids["S39-ROOT-A"], reason=REASON+" changed").status_code == 409
    with session_factory() as db:
        assert counts(db)["recalls"] == 1 and counts(db)["idempotency_records"] == 1


def test_idempotency_scoped_actor_and_endpoint(client, ids):
    root = post_recall(client, ids["S39-ROOT-A"], key="shared")
    clean = post_recall(client, ids["S39-CLEAN-X"], actor="proc_admin", key="shared")
    assert root.status_code == 201 and clean.status_code == 201
    assert ack(client, root.json()["id"], "proc_admin", key="shared").status_code == 200


def test_consumed_root_preserved_and_missing_evidence(client, ids, session_factory):
    root_id = ids["S39-SPLIT-B2"]
    response = post_recall(client, root_id, actor="dist_admin")
    assert response.status_code == 201
    assert response.json()["affected_batches"][0]["status"] == "CONSUMED"
    with session_factory() as db:
        parent = db.get(Batch, ids["S39-FINAL-D2"])
        child_id = add_child(db, parent, "NO-CONSUMED-EVIDENCE")
        child = db.get(Batch, child_id)
        child.status = "CONSUMED"
        child.remaining_quantity = Decimal("0")
        db.commit()
    response = post_recall(client, child_id, key="missing-evidence")
    assert response.status_code == 201
    assert response.json()["metrics_by_unit"]["kg"]["consumed_quantity"] is None
    assert response.json()["affected_batches"][0]["consumed_evidence_missing"]


def test_organization_privacy_list_detail_alerts(client, ids):
    response = post_recall(client, ids["S39-ROOT-A"])
    recall_id = response.json()["id"]
    for path in ("/recalls", "/recalls/my-alerts"):
        assert client.get(path, auth=("outsider", PASSWORD)).json() == []
        assert client.get(path, auth=("system", PASSWORD)).json() == []
        own = client.get(path, auth=("proc_admin", PASSWORD))
        assert own.status_code == 200 and len(own.json()) == 1
        assert {n["organization_id"] for n in own.json()[0]["affected_batches"]} == {own.json()[0]["acknowledgments"][0]["organization_id"]}
    assert client.get(f"/recalls/{recall_id}", auth=("outsider", PASSWORD)).status_code == 403
    assert client.get(f"/recalls/{recall_id}", auth=("system", PASSWORD)).status_code == 403
    assert client.get("/recalls/999999", auth=("inspector", PASSWORD)).status_code == 404


@pytest.mark.parametrize("actor", ["inspector", "system", "outsider", "processor", "distributor", "farmer", "transporter"])
def test_ack_role_and_organization(client, ids, actor):
    recall_id = post_recall(client, ids["S39-ROOT-A"]).json()["id"]
    assert ack(client, recall_id, actor).status_code == 403


def test_ack_completed_append_only_and_lifetime(client, ids, session_factory):
    recall_id = completed(client, ids)
    replay = ack(client, recall_id, "dist_admin")
    assert replay.status_code == 200 and replay.json()["status"] == "COMPLETED"
    assert ack(client, recall_id, "dist_admin", key="new-key").status_code == 409
    assert ack(client, recall_id, "dist_admin", notes="Changed notes").status_code == 409
    assert post_recall(client, ids["S39-ROOT-A"], key="reopen").status_code == 409
    with session_factory() as db:
        kinds = list(db.scalars(select(BatchEvent.event_type).where(BatchEvent.event_type.like("RECALL%"))).all())
        assert kinds.count("RECALL_ACKNOWLEDGED") == 3 and kinds.count("RECALL_COMPLETED") == 1
        assert len(db.scalars(select(RecallAcknowledgment)).all()) == 3
        assert counts(db)["audit_logs"] == 5
        assert verify_batch_chain(db, ids["S39-ROOT-A"])["is_valid"]
    with pytest.raises(Exception):
        with session_factory() as db:
            db.connection().exec_driver_sql("UPDATE batch_events SET notes='tampered' WHERE event_type='RECALL_ACKNOWLEDGED'")


@pytest.mark.parametrize("complete", [False, True])
def test_all_physical_operations_quarantined(client, ids, session_factory, complete):
    recall_id = completed(client, ids) if complete else post_recall(client, ids["S39-ROOT-A"]).json()["id"]
    with session_factory() as db:
        proc_org = db.get(Batch, ids["S39-FINAL-D2"]).current_org_id
        target_org = db.get(Batch, ids["S39-FINAL-D1"]).current_org_id
        product = db.get(Batch, ids["S39-FINAL-D2"]).product_id
        before = counts(db)
    batch_id = ids["S39-FINAL-D2"]
    calls = [
        (f"/batches/{batch_id}/handover", "processor", {"to_org_id": target_org}),
        (f"/batches/{batch_id}/split", "processor", {"items": [{"quantity": 10}]}),
        ("/batches/merge", "processor", {"items": [{"parent_batch_id": batch_id, "quantity": 10}, {"parent_batch_id": ids["S39-CLEAN-X"], "quantity": 10}], "product_id": product}),
        (f"/batches/{batch_id}/consume", "proc_admin", {}),
        (f"/api/v1/batches/{batch_id}/consume", "proc_admin", {}),
    ]
    for path, actor, body in calls:
        response = client.post(path, json=body, auth=(actor, PASSWORD))
        assert response.status_code == 409, (path, response.text)
        assert response.json()["detail"]["code"] == "BATCH_QUARANTINED"
    with session_factory() as db:
        assert counts(db) == before
        assert db.get(Recall, recall_id).status == ("COMPLETED" if complete else "OPEN")
        assert proc_org == db.get(Batch, batch_id).current_org_id


def test_accept_preexisting_handover_is_blocked(client, ids, session_factory):
    with session_factory() as db:
        source = db.get(Batch, ids["S39-FINAL-D2"])
        target = db.get(Batch, ids["S39-FINAL-D1"])
        h = Handover(batch_id=source.id, from_org_id=source.current_org_id,
                     to_org_id=target.current_org_id, status="PENDING")
        db.add(h); db.commit(); handover_id = h.id
    post_recall(client, ids["S39-ROOT-A"])
    response = client.post(f"/handovers/{handover_id}/accept", auth=("distributor", PASSWORD))
    assert response.status_code == 409, response.text
    with session_factory() as db: assert db.get(Handover, handover_id).status == "PENDING"


def test_completed_new_descendant_alert_and_quarantine(client, ids, session_factory, caplog):
    recall_id = completed(client, ids)
    with session_factory() as db:
        new_id = add_child(db, db.get(Batch, ids["S39-FINAL-D2"]), "ANOMALY-AFTER-DONE")
        db.commit()
        before = counts(db)
    response = client.get(f"/recalls/{recall_id}", auth=("inspector", PASSWORD))
    assert response.json()["status"] == "COMPLETED"
    assert response.json()["anomaly"]["new_batch_ids"] == [new_id]
    assert "new descendants after completion" in caplog.text
    alerts = client.get("/recalls/my-alerts", auth=("proc_admin", PASSWORD))
    assert alerts.json()[0]["alert_severity"] == "CRITICAL"
    assert client.post(f"/batches/{new_id}/consume", json={}, auth=("proc_admin", PASSWORD)).status_code == 409
    with session_factory() as db:
        assert counts(db) == before
        assert db.get(Recall, recall_id).status == "COMPLETED"


def test_open_new_org_reconciles_before_completion_without_duplicate_events(client, ids, session_factory):
    recall_id = post_recall(client, ids["S39-ROOT-A"]).json()["id"]
    ack(client, recall_id, "farm_admin")
    ack(client, recall_id, "proc_admin")
    with session_factory() as db:
        outsider_org = db.scalar(select(User.organization_id).where(User.username == "outsider"))
        child_id = add_child(db, db.get(Batch, ids["S39-FINAL-D2"]), "OPEN-NEW-ORG", outsider_org)
        db.commit()
    fresh = client.get(f"/recalls/{recall_id}", auth=("inspector", PASSWORD)).json()
    assert fresh["progress"] == {"acknowledged": 2, "required": 4}
    response = ack(client, recall_id, "dist_admin")
    assert response.status_code == 200 and response.json()["status"] == "OPEN"
    response = ack(client, recall_id, "outsider")
    assert response.status_code == 200 and response.json()["status"] == "COMPLETED"
    with session_factory() as db:
        assert len(db.scalars(select(RecallAcknowledgment)).all()) == 4
        matches = [e for e in db.scalars(select(BatchEvent).where(BatchEvent.batch_id == child_id)).all() if e.event_type == "RECALL_AFFECTED"]
        assert len(matches) == 1


def test_diamond_cross_layer_cycle_and_max_nodes(client, ids, session_factory, monkeypatch):
    with session_factory() as db:
        db.add(BatchRelation(parent_batch_id=ids["S39-SPLIT-B2"], child_batch_id=ids["S39-MERGE-C1"], transferred_quantity=Decimal("0"), relation_type="MERGE"))
        db.commit()
    response = post_recall(client, ids["S39-ROOT-A"])
    assert response.status_code == 201 and response.json()["total_affected_batch_count"] == 6
    with session_factory() as db:
        db.add(BatchRelation(parent_batch_id=ids["S39-FINAL-D2"], child_batch_id=ids["S39-SPLIT-B1"], transferred_quantity=Decimal("0"), relation_type="SPLIT"))
        db.commit()
        before = counts(db)
    assert post_recall(client, ids["S39-CLEAN-X"], key="cycle").status_code == 400
    with session_factory() as db: assert counts(db) == before
    monkeypatch.setattr(recall_graph, "MAX_GRAPH_NODES", 2)
    response = post_recall(client, ids["S39-ROOT-A"], key="over-limit")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "INCOMPLETE_GRAPH"


@pytest.mark.parametrize("failure_kind", ["RECALL_INIT", "RECALL_AFFECTED", "RECALL_ACKNOWLEDGED", "RECALL_COMPLETED"])
def test_rollback_event_failure(client, ids, session_factory, monkeypatch, failure_kind):
    if failure_kind in ("RECALL_INIT", "RECALL_AFFECTED"):
        operation = lambda: post_recall(client, ids["S39-ROOT-A"])
    else:
        recall_id = post_recall(client, ids["S39-ROOT-A"]).json()["id"]
        if failure_kind == "RECALL_COMPLETED":
            ack(client, recall_id, "farm_admin")
            ack(client, recall_id, "proc_admin")
        operation = lambda: ack(client, recall_id, "dist_admin")
    with session_factory() as db: before = counts(db)
    original = service.record_event
    def injected(**kwargs):
        if kwargs["event_type"] == failure_kind: raise RuntimeError("Injected event failure")
        return original(**kwargs)
    monkeypatch.setattr(service, "record_event", injected)
    with pytest.raises(RuntimeError, match="Injected event failure"): operation()
    with session_factory() as db:
        assert counts(db) == before
        for batch_id in ids.values(): assert verify_batch_chain(db, batch_id)["is_valid"]
        if failure_kind in ("RECALL_ACKNOWLEDGED", "RECALL_COMPLETED"):
            dist_org = db.scalar(select(User.organization_id).where(User.username == "dist_admin"))
            entry = db.scalar(select(RecallAcknowledgment).where(RecallAcknowledgment.organization_id == dist_org))
            assert entry.status == "PENDING" and entry.notes is None
            assert db.get(Recall, recall_id).status == "OPEN"


def test_cookie_csrf_and_ack_extra_org_field(client, ids):
    login = client.post("/auth/login", json={"username": "farm_admin", "password": PASSWORD})
    assert login.status_code == 200
    body = {"root_batch_id": ids["S39-ROOT-A"], "reason": REASON}
    assert client.post("/recalls", json=body, headers={"Idempotency-Key": "cookie"}).status_code == 403
    token = login.json()["csrf_token"]
    response = client.post("/recalls", json=body, headers={"Idempotency-Key": "cookie", "X-CSRF-Token": token})
    assert response.status_code == 201, response.text
    response = client.post(f"/recalls/{response.json()['id']}/acknowledge", json={"organization_id": 999, "notes": "try to impersonate"}, headers={"Idempotency-Key": "cookie-ack", "X-CSRF-Token": token})
    assert response.status_code == 422


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_create(client, ids, session_factory, same_key):
    barrier = threading.Barrier(2)
    # Do not enter TestClient lifespan: it targets the configured bootstrap engine.
    def request(index):
        c = TestClient(app)
        try:
            barrier.wait(timeout=10)
            return post_recall(c, ids["S39-ROOT-A"], key="race" if same_key else "race-"+str(index))
        finally: c.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(request, [1, 2]))
    assert sorted(r.status_code for r in responses) == ([201, 201] if same_key else [201, 409])
    with session_factory() as db:
        assert counts(db)["recalls"] == 1
        assert counts(db)["recall_acknowledgments"] == 3
        assert len(db.scalars(select(BatchEvent).where(BatchEvent.event_type.like("RECALL%"))).all()) == 6
        for batch_id in ids.values(): assert verify_batch_chain(db, batch_id)["is_valid"]


def test_concurrent_ack_and_last_two_complete(client, ids, session_factory):
    recall_id = post_recall(client, ids["S39-ROOT-A"]).json()["id"]
    barrier = threading.Barrier(2)
    def request(actor):
        c = TestClient(app)
        try:
            barrier.wait(timeout=10)
            return ack(c, recall_id, actor)
        finally: c.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        duplicates = list(pool.map(request, ["farm_admin", "farm_admin"]))
    assert [r.status_code for r in duplicates] == [200, 200]
    barrier.reset()
    with ThreadPoolExecutor(max_workers=2) as pool:
        last = list(pool.map(request, ["proc_admin", "dist_admin"]))
    assert [r.status_code for r in last] == [200, 200]
    with session_factory() as db:
        assert db.get(Recall, recall_id).status == "COMPLETED"
        events = list(db.scalars(select(BatchEvent.event_type)).all())
        assert events.count("RECALL_ACKNOWLEDGED") == 3 and events.count("RECALL_COMPLETED") == 1
        assert verify_batch_chain(db, ids["S39-ROOT-A"])["is_valid"]


def test_concurrent_recall_vs_consume(client, ids, session_factory):
    barrier = threading.Barrier(2)
    batch_id = ids["S39-FINAL-D2"]
    def request(kind):
        c = TestClient(app)
        try:
            barrier.wait(timeout=10)
            if kind == "recall": return post_recall(c, batch_id)
            return c.post(f"/batches/{batch_id}/consume", json={}, auth=("proc_admin", PASSWORD))
        finally: c.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        recall_response, consume_response = list(pool.map(request, ["recall", "consume"]))
    assert recall_response.status_code == 201
    assert consume_response.status_code in (200, 409)
    with session_factory() as db:
        chain = list(db.scalars(select(BatchEvent).where(BatchEvent.batch_id == batch_id).order_by(BatchEvent.id)).all())
        kinds = [e.event_type for e in chain]
        if "CONSUMED" in kinds: assert kinds.index("CONSUMED") < kinds.index("RECALL_INIT")
        assert verify_batch_chain(db, batch_id)["is_valid"]


def test_new_copy_migration_and_protected_aliases(tmp_path, engine, monkeypatch):
    source = Path(engine.url.database)
    target = tmp_path/"migrated_copy.db"
    result = prepare(source, target)
    assert result["source_unchanged"] and result["mode"] == "new_test_copy"
    copy_engine = create_engine("sqlite:///" + target.as_posix())
    assert {"recalls", "recall_acknowledgments", "idempotency_records"} <= set(inspect(copy_engine).get_table_names())
    copy_engine.dispose()
    with pytest.raises(ValueError): prepare(source, source)
    # Use a disposable surrogate instead of ever opening the actual protected DB.
    import app.services.recall_database as boundary
    import app.database as database
    surrogate = tmp_path/"protected_surrogate.db"
    surrogate.write_bytes(b"")
    monkeypatch.setattr(boundary, "DATABASE_FILE", surrogate)
    protected = create_engine("sqlite:///" + surrogate.as_posix())
    assert is_protected_engine(protected)
    alias = tmp_path/"protected_hardlink.db"
    alias.hardlink_to(surrogate)
    alias_engine = create_engine("sqlite:///" + alias.as_posix())
    assert is_protected_engine(alias_engine)
    alias_engine.dispose()
    monkeypatch.setattr(database, "engine", protected)
    database.init_db()
    assert surrogate.stat().st_size == 0
    with pytest.raises(RuntimeError): Base.metadata.create_all(protected)
    assert surrogate.stat().st_size == 0
    protected.dispose()


@pytest.mark.parametrize("kind", ["split", "merge", "handover"])
def test_concurrent_recall_vs_physical_mutations(client, ids, session_factory, kind):
    batch_id = ids["S39-FINAL-D2"]
    with session_factory() as db:
        parent = db.get(Batch, batch_id)
        product_id = parent.product_id
        destination = db.get(Batch, ids["S39-FINAL-D1"]).current_org_id
        clean = Batch(code="RACE-UNRELATED", plot_id=parent.plot_id, farm_id=parent.farm_id,
                      product_id=product_id, harvest_date=parent.harvest_date,
                      initial_quantity=Decimal("50"), remaining_quantity=Decimal("50"),
                      current_org_id=parent.current_org_id)
        db.add(clean); db.commit(); clean_id = clean.id
    barrier = threading.Barrier(2)
    def request(action):
        c = TestClient(app)
        try:
            barrier.wait(timeout=10)
            if action == "recall": return post_recall(c, batch_id)
            if kind == "split":
                return c.post(f"/batches/{batch_id}/split", json={"items": [{"quantity": 10}]}, auth=("processor", PASSWORD))
            if kind == "merge":
                return c.post("/batches/merge", json={"product_id": product_id, "items": [{"parent_batch_id": batch_id, "quantity": 10}, {"parent_batch_id": clean_id, "quantity": 10}]}, auth=("processor", PASSWORD))
            return c.post(f"/batches/{batch_id}/handover", json={"to_org_id": destination}, auth=("processor", PASSWORD))
        finally: c.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        recall_response, physical_response = list(pool.map(request, ["recall", "physical"]))
    assert recall_response.status_code == 201, recall_response.text
    assert physical_response.status_code in (201, 409), physical_response.text
    with session_factory() as db:
        chain = list(db.scalars(select(BatchEvent).where(BatchEvent.batch_id == batch_id).order_by(BatchEvent.id)).all())
        kinds = [e.event_type for e in chain]
        recall_index = kinds.index("RECALL_INIT")
        assert all(index < recall_index for index, event_type in enumerate(kinds) if event_type in ("SPLIT", "EXPORT_MERGE", "HANDOVER_INIT") and index > 0)
        if kind in ("split", "merge") and physical_response.status_code == 201:
            graph = recall_graph.graph_snapshot(db, batch_id)
            assert len(graph["batches"]) > 1
            events = list(db.scalars(select(BatchEvent).where(BatchEvent.event_type == "RECALL_AFFECTED")).all())
            assert len(events) == len(graph["batches"]) - 1
        for batch in db.scalars(select(Batch)).all(): assert verify_batch_chain(db, batch.id)["is_valid"]


def test_fresh_migration_api_compatibility(client, engine, ids, tmp_path, session_factory):
    legacy = tmp_path/"base_without_recall.db"
    raw = engine.raw_connection()
    with sqlite3.connect(legacy) as disk:
        raw.driver_connection.backup(disk)
        for name in ("recall_acknowledgments", "idempotency_records", "recalls"):
            disk.execute(f"DROP TABLE {name}")
        disk.commit()
    raw.close()
    source_bytes = legacy.read_bytes()
    output = tmp_path/"trial_migrated.db"
    result = prepare(legacy, output)
    assert result["existing_tables_preserved"] and legacy.read_bytes() == source_bytes
    copied_engine = create_engine("sqlite:///"+output.as_posix(), connect_args={"check_same_thread": False})
    previous = app.dependency_overrides[get_db]
    def override():
        with Session(copied_engine) as db: yield db
    app.dependency_overrides[get_db] = override
    try:
        response = post_recall(client, ids["S39-ROOT-A"])
        assert response.status_code == 201, response.text
        recall_id = response.json()["id"]
        for actor in ("farm_admin", "proc_admin", "dist_admin"):
            response = ack(client, recall_id, actor)
            assert response.status_code == 200, response.text
        assert response.json()["status"] == "COMPLETED"
    finally:
        app.dependency_overrides[get_db] = previous
        copied_engine.dispose()


def test_protected_api_rejected_before_authentication(client, session_factory, engine, monkeypatch):
    import app.services.recall_database as boundary
    monkeypatch.setattr(boundary, "DATABASE_FILE", Path(engine.url.database))
    with session_factory() as db:
        before = [(u.id, u.failed_login_attempts, u.password) for u in db.scalars(select(User)).all()]
    response = client.post("/recalls", json={"root_batch_id": 1, "reason": REASON},
                           auth=("inspector", "wrong-password"), headers={"Idempotency-Key": "protected"})
    assert response.status_code == 503
    with session_factory() as db:
        assert [(u.id, u.failed_login_attempts, u.password) for u in db.scalars(select(User)).all()] == before


def test_database_rejects_duplicate_recall_event(client, ids, session_factory):
    recall_id = post_recall(client, ids["S39-ROOT-A"]).json()["id"]
    with session_factory() as db:
        before = counts(db)
        actor = db.scalar(select(User).where(User.username == "inspector"))
        batch = db.get(Batch, ids["S39-SPLIT-B1"])
        with pytest.raises(IntegrityError):
            service.record_event(db=db, batch_id=batch.id, event_type="RECALL_AFFECTED",
                                 payload={"recall_id": recall_id}, org_id=batch.current_org_id, user_id=actor.id)
        db.rollback()
        assert counts(db) == before
        assert verify_batch_chain(db, batch.id)["is_valid"]


@pytest.mark.parametrize("value", ["NaN", "-10", None])
def test_invalid_consumed_evidence_is_unknown(client, ids, session_factory, value):
    with session_factory() as db:
        parent = db.get(Batch, ids["S39-FINAL-D2"])
        batch_id = add_child(db, parent, "INVALID-EVIDENCE")
        batch = db.get(Batch, batch_id)
        batch.status = "CONSUMED"
        batch.remaining_quantity = Decimal("0")
        actor = db.scalar(select(User).where(User.username == "proc_admin"))
        payload = {} if value is None else {"previous_remaining_quantity": value}
        service.record_event(db=db, batch_id=batch.id, event_type="CONSUMED", payload=payload,
                             org_id=batch.current_org_id, user_id=actor.id)
        db.commit()
    response = post_recall(client, batch_id)
    assert response.status_code == 201
    assert response.json()["metrics_by_unit"]["kg"]["consumed_quantity"] is None


def test_replay_reauthorizes_changed_role(client, ids, session_factory):
    recall_id = post_recall(client, ids["S39-ROOT-A"]).json()["id"]
    assert ack(client, recall_id, "proc_admin").status_code == 200
    with session_factory() as db:
        user = db.scalar(select(User).where(User.username == "proc_admin"))
        user.role = "processor"
        db.commit()
    assert ack(client, recall_id, "proc_admin").status_code == 403


def test_missing_event_index_refuses_api(client, session_factory):
    with session_factory() as db:
        db.connection().exec_driver_sql("DROP INDEX uq_recall_event_evidence")
        db.commit()
    assert client.get("/recalls", auth=("inspector", PASSWORD)).status_code == 503


@pytest.mark.parametrize("replay_kind", ["create", "ack"])
def test_replay_does_not_leak_former_visibility(client, ids, session_factory, replay_kind):
    recall_id = post_recall(client, ids["S39-ROOT-A"]).json()["id"]
    if replay_kind == "ack": assert ack(client, recall_id, "proc_admin").status_code == 200
    with session_factory() as db:
        if replay_kind == "create":
            user = db.scalar(select(User).where(User.username == "inspector"))
            user.role = "org_admin"
            user.organization_id = db.get(Batch, ids["S39-ROOT-A"]).current_org_id
        else:
            user = db.scalar(select(User).where(User.username == "proc_admin"))
            user.organization_id = db.get(Batch, ids["S39-FINAL-D1"]).current_org_id
        db.commit()
    response = post_recall(client, ids["S39-ROOT-A"]) if replay_kind == "create" else ack(client, recall_id, "proc_admin")
    assert response.status_code == 403


def test_new_batch_after_organization_ack_cannot_silently_complete(client, ids, session_factory):
    recall_id = post_recall(client, ids["S39-ROOT-A"]).json()["id"]
    ack(client, recall_id, "farm_admin")
    ack(client, recall_id, "proc_admin")
    with session_factory() as db:
        add_child(db, db.get(Batch, ids["S39-FINAL-D2"]), "AFTER-ORG-ACK")
        db.commit()
        before = counts(db)
    response = ack(client, recall_id, "dist_admin")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "GRAPH_CHANGED_AFTER_ACK"
    detail = client.get(f"/recalls/{recall_id}", auth=("inspector", PASSWORD)).json()
    assert detail["status"] == "OPEN" and detail["anomaly"]["code"] == "GRAPH_CHANGED_AFTER_ACK"
    with session_factory() as db:
        assert counts(db) == before
        assert db.get(Recall, recall_id).status == "OPEN"


@pytest.mark.parametrize("kind", ["RECALL_INIT", "RECALL_AFFECTED", "RECALL_ACKNOWLEDGED", "RECALL_COMPLETED"])
@pytest.mark.parametrize("prefix", ["/batches", "/api/batches"])
def test_manual_event_endpoint_cannot_forge_recall_evidence(client, ids, session_factory, kind, prefix):
    with session_factory() as db: before = counts(db)
    response = client.post(f"{prefix}/{ids['S39-FINAL-D2']}/events",
                           json={"event_type": kind.lower(), "payload": {"recall_id": 123}},
                           auth=("processor", PASSWORD))
    assert response.status_code == 400
    with session_factory() as db: assert counts(db) == before
