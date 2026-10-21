"""Phase C API, mass/hash integrity, atomic CSV and eight-role policy on QA only."""

from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import select, func
from app.main import app
from app.database import get_db
from app.models import Organization, Farm, Plot, Product, Batch, BatchRelation, BatchEvent, User, Handover
from app.security import get_current_user
from app.hash_chain import record_event, verify_batch_chain
from app.services.location_migration import apply_phase_c_schema
from app.services.traceability import clear_trace_cache


@pytest.fixture
def cq(engine, session_factory):
    apply_phase_c_schema(engine)
    with session_factory() as db:
        org = Organization(name="C QA", code="C-QA")
        other = Organization(name="C Other", code="C-OTHER")
        db.add_all([org, other])
        db.flush()
        farm = Farm(name="C Plot", location="Origin", area=1, owner="QA", organization_id=org.id)
        db.add(farm)
        db.flush()
        plot = Plot(id=farm.id, name=farm.name, location=farm.location, area=1, owner="QA", organization_id=org.id)
        product = Product(name="C Product", unit="kg")
        db.add_all([plot, product])
        db.flush()
        user = User(username="c_actor", email="c@qa.local", password="unused", role="distributor", organization_id=org.id)
        db.add(user)
        db.flush()
        root = Batch(
            code="C-ROOT",
            plot_id=plot.id,
            product_id=product.id,
            harvest_date=date(2026, 10, 1),
            initial_quantity=Decimal("100"),
            remaining_quantity=Decimal("100"),
            current_org_id=org.id,
            status="ACTIVE",
        )
        zero = Batch(
            code="C-ZERO",
            plot_id=plot.id,
            product_id=product.id,
            harvest_date=date(2026, 10, 1),
            initial_quantity=Decimal("100"),
            remaining_quantity=Decimal("0"),
            current_org_id=org.id,
            status="SPLIT",
        )
        db.add_all([root, zero])
        db.flush()
        record_event(db=db, batch_id=root.id, event_type="HARVEST", payload={"quantity": 100}, org_id=org.id, user_id=user.id)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        app.dependency_overrides[get_current_user] = lambda: user
        ids = {"root": root.id, "zero": zero.id, "org": org.id, "other": other.id, "user": user}
    clear_trace_cache()
    yield ids
    app.dependency_overrides.pop(get_current_user, None)
    clear_trace_cache()


def place(client, code):
    response = client.post("/organizations/locations", json={"code": code, "name": code, "address": "Current address " + code})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_allocation_location_trace_consume(client, session_factory, cq):
    a, b = place(client, "STORE-A"), place(client, "STORE-B")
    response = client.post(
        f"/batches/{cq['root']}/allocate-stores",
        json={"items": [{"location_id": a, "quantity": 40}, {"location_id": b, "quantity": 60}]},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    children = data["child_batches"]
    assert data["parent_batch"]["remaining_quantity"] == 0
    assert data["parent_batch"]["status"] == "SPLIT"
    assert [n["location_id"] for n in children] == [a, b]
    forward = client.get(f"/batches/{cq['root']}/trace-forward").json()
    nodes = forward["descendants_by_level"]["1"]
    assert {n["current_location"] for n in nodes} == {"Current address STORE-A", "Current address STORE-B"}
    assert all(n["location"] == "Origin" for n in nodes)
    assert len(forward["edges"]) == 2
    assert client.patch(f"/organizations/locations/{a}", json={"is_active": False}).status_code == 409
    sold = client.post(f"/batches/{children[0]['id']}/consume", json={})
    assert sold.status_code == 200 and sold.json()["batch"]["remaining_quantity"] == 0
    assert client.post(f"/batches/{children[0]['id']}/consume", json={}).status_code == 400
    assert client.patch(f"/organizations/locations/{a}", json={"is_active": False}).status_code == 200
    with session_factory() as db:
        assert sum(db.get(Batch, c["id"]).initial_quantity for c in children) == Decimal("100")
        assert db.scalar(select(func.count(BatchRelation.id))) == 2
        for bid in [cq["root"], *[c["id"] for c in children]]:
            assert verify_batch_chain(db, bid)["is_valid"]


def test_zero_consume_no_side_effect(client, session_factory, cq):
    with session_factory() as db:
        before = db.scalar(select(func.count(BatchEvent.id)))
    assert client.post(f"/batches/{cq['zero']}/consume", json={}).status_code == 400
    with session_factory() as db:
        assert db.get(Batch, cq["zero"]).status == "SPLIT"
        assert db.scalar(select(func.count(BatchEvent.id))) == before


def test_allocation_validation_and_foreign_store(client, session_factory, cq):
    a, b = place(client, "A"), place(client, "B")
    assert (
        client.post(
            f"/batches/{cq['root']}/allocate-stores",
            json={"items": [{"location_id": a, "quantity": 40}, {"location_id": b, "quantity": 59}]},
        ).status_code
        == 422
    )
    with session_factory() as db:
        assert db.get(Batch, cq["root"]).remaining_quantity == 100
        assert db.scalar(select(func.count(Batch.id))) == 2
    from app.location_models import Location

    with session_factory() as db:
        foreign = Location(code="X", name="X", address="private", organization_id=cq["other"])
        db.add(foreign)
        db.commit()
        fid = foreign.id
    assert client.post(f"/batches/{cq['root']}/transfer-location", json={"location_id": fid}).status_code == 403


def test_transfer_split_inheritance_and_location_mask(client, session_factory, cq):
    a = place(client, "A")
    r = client.post(f"/batches/{cq['root']}/transfer-location", json={"location_id": a})
    assert r.status_code == 200 and r.json()["location_id"] == a
    assert client.get(f"/batches/{cq['root']}").json()["location_id"] == a
    split = client.post(f"/batches/{cq['root']}/split", json={"items": [{"quantity": 20}, {"quantity": 30}]})
    assert split.status_code == 201, split.text
    assert all(c["location_id"] == a for c in split.json()["child_batches"])
    assert split.json()["parent_batch"]["remaining_quantity"] == 50


@pytest.mark.parametrize("role", ["farmer", "processor", "transporter", "inspector", "system_admin"])
def test_denied_location_management(client, cq, role):
    cq["user"].role = role
    assert client.get("/organizations/locations").status_code == 403
    assert client.post("/organizations/locations", json={"code": "A", "name": "A", "address": "A"}).status_code == 403


def csv_post(client, entity, data):
    return client.post("/catalogs/import-csv", data={"entity_type": entity}, files={"file": ("input.csv", data, "text/csv")})


def test_csv_atomic_idempotent_product_and_plot(client, session_factory, cq):
    cq["user"].role = "system_admin"
    raw = "name,unit\nCSV Product,kg\n"
    first = csv_post(client, "product", raw.encode("utf-8-sig"))
    assert first.status_code == 200 and first.json()["created_count"] == 1
    assert csv_post(client, "product", raw.encode()).json()["skipped_count"] == 1
    bad = csv_post(client, "product", b"name,unit\nShould rollback,kg\nBad,invalid\n")
    assert bad.status_code == 422 and bad.json()["detail"]["created_count"] == 0
    with session_factory() as db:
        assert db.scalar(select(Product).where(Product.name == "Should rollback")) is None
    cq["user"].role = "org_admin"
    raw = b"name,location,area,owner,coordinates\nCSV Plot,North,2.5,QA,\n"
    assert csv_post(client, "plot", raw).json()["created_count"] == 1
    assert csv_post(client, "plot", raw).json()["skipped_count"] == 1
    with session_factory() as db:
        farm = db.scalar(select(Farm).where(Farm.name == "CSV Plot"))
        plot = db.scalar(select(Plot).where(Plot.name == "CSV Plot"))
        assert farm.id == plot.id and farm.organization_id == cq["org"]
    assert csv_post(client, "product", b"name,unit\nForbidden,kg\n").status_code == 403


@pytest.mark.parametrize(
    "role,product,plot",
    [
        ("farmer", 403, 200),
        ("processor", 403, 403),
        ("processor", 403, 403),
        ("transporter", 403, 403),
        ("distributor", 403, 403),
        ("inspector", 403, 403),
        ("system_admin", 200, 403),
        ("org_admin", 403, 200),
    ],
)
def test_csv_eight_accounts_permission(client, cq, role, product, plot):
    cq["user"].role = role
    assert client.get("/catalogs/template/product").status_code == product
    assert client.get("/catalogs/template/plot").status_code == plot


def test_missing_location_schema_legacy_reads(client, session_factory):
    # Existing legacy schema (no batches.location_id) must keep legacy APIs usable.
    assert client.get("/products").status_code == 200


def test_allocation_rollback_mid_transaction(client, session_factory, cq, monkeypatch):
    a, b = place(client, "A"), place(client, "B")
    from app.routers import locations

    original = locations.record_event
    calls = 0

    def fail_second(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("QA fault injection")
        return original(**kwargs)

    monkeypatch.setattr(locations, "record_event", fail_second)
    with pytest.raises(RuntimeError):
        client.post(
            f"/batches/{cq['root']}/allocate-stores",
            json={"items": [{"location_id": a, "quantity": 40}, {"location_id": b, "quantity": 60}]},
        )
    with session_factory() as db:
        assert db.scalar(select(func.count(Batch.id))) == 2
        assert db.scalar(select(func.count(BatchRelation.id))) == 0
        assert db.get(Batch, cq["root"]).remaining_quantity == 100


def test_org_admin_not_granted_split(client, cq):
    cq["user"].role = "org_admin"
    a, b = place(client, "ADMIN-A"), place(client, "ADMIN-B")
    response = client.post(
        f"/batches/{cq['root']}/allocate-stores",
        json={"items": [{"location_id": a, "quantity": 40}, {"location_id": b, "quantity": 60}]},
    )
    assert response.status_code == 403


def test_migrated_summary_keeps_three_queries(client, session_factory, cq, engine):
    from sqlalchemy import event
    from app.routers.batches import get_batch_summary

    a = place(client, "SUMMARY")
    assert client.post(f"/batches/{cq['root']}/transfer-location", json={"location_id": a}).status_code == 200
    with session_factory() as db:
        queries = []

        def count(*args):
            queries.append(args[2])

        event.listen(engine, "before_cursor_execute", count)
        try:
            result = get_batch_summary(cq["root"], cq["user"], db)
            assert result.batch.current_location == "Current address SUMMARY"
            assert len(queries) == 3
        finally:
            event.remove(engine, "before_cursor_execute", count)


def test_concurrent_consume_one_event(client, session_factory, cq):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post(f"/batches/{cq['root']}/consume", json={}).status_code, range(2)))
    assert sorted(results) == [200, 400]
    with session_factory() as db:
        assert db.scalar(select(func.count(BatchEvent.id)).where(BatchEvent.event_type == "CONSUMED")) == 1
        assert verify_batch_chain(db, cq["root"])["is_valid"]


def test_handover_clears_location(client, session_factory, cq):
    a = place(client, "HANDOVER")
    assert client.post(f"/batches/{cq['root']}/transfer-location", json={"location_id": a}).status_code == 200
    with session_factory() as db:
        h = Handover(batch_id=cq["root"], from_org_id=cq["org"], to_org_id=cq["other"], status="PENDING")
        db.add(h)
        db.commit()
        hid = h.id
    cq["user"].organization_id = cq["other"]
    response = client.post(f"/handovers/{hid}/accept")
    assert response.status_code == 200, response.text
    with session_factory() as db:
        from sqlalchemy import text

        assert db.scalar(text("SELECT location_id FROM batches WHERE id=:id"), {"id": cq["root"]}) is None


def test_csv_encoding_columns_and_duplicate_conflict(client, cq):
    cq["user"].role = "system_admin"
    assert csv_post(client, "product", b"\xff").status_code == 422
    assert csv_post(client, "product", b"name,unit,organization_id\nX,kg,1\n").status_code == 422
    response = csv_post(client, "product", b"name,unit\nX,kg\nX,thung\n")
    assert response.status_code == 422 and response.json()["detail"]["created_count"] == 0


def test_current_location_hidden_for_unauthorized_endpoint(client, session_factory, cq):
    a, b = place(client, "MASK-A"), place(client, "MASK-B")
    response = client.post(
        f"/batches/{cq['root']}/allocate-stores",
        json={"items": [{"location_id": a, "quantity": 40}, {"location_id": b, "quantity": 60}]},
    )
    child = response.json()["child_batches"][0]["id"]
    with session_factory() as db:
        db.get(Batch, child).current_org_id = cq["other"]
        db.commit()
    clear_trace_cache()
    data = client.get(f"/batches/{cq['root']}/trace-forward").json()
    node = next(n for nodes in data["descendants_by_level"].values() for n in nodes if n["batch_id"] == child)
    assert node["current_location"] is None and node["location_id"] is None
    assert all(edge["child_batch_id"] != child for edge in data["edges"])


@pytest.mark.parametrize("same_location", [True, False])
def test_merge_retains_only_common_location(client, session_factory, cq, same_location):
    a, b = place(client, "MERGE-A"), place(client, "MERGE-B")
    response = client.post(
        f"/batches/{cq['root']}/allocate-stores",
        json={"items": [{"location_id": a, "quantity": 40}, {"location_id": a if same_location else b, "quantity": 60}]},
    )
    children = response.json()["child_batches"]
    cq["user"].role = "processor"
    result = client.post(
        "/batches/merge",
        json={
            "product_id": children[0]["product_id"],
            "items": [{"parent_batch_id": c["id"], "quantity": c["remaining_quantity"]} for c in children],
        },
    )
    assert result.status_code == 201, result.text
    merged = result.json()["merged_batch"]
    assert merged["location_id"] == (a if same_location else None)
    assert merged["remaining_quantity"] == 100
    with session_factory() as db:
        assert verify_batch_chain(db, merged["id"])["is_valid"]


def test_malformed_csv_header_reports_422(client, cq):
    cq["user"].role = "system_admin"
    response = csv_post(client, "product", b'"name,unit\n')
    assert response.status_code == 422
    assert response.json()["detail"]["created_count"] == 0
    assert response.json()["detail"]["errors"][0]["column"] == "header"
