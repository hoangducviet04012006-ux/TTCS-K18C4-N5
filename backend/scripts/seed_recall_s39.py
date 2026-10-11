"""Synthetic S-39 snapshot builder, allowed only in an explicit in-memory Session.
No production SessionLocal, CLI, startup registration, or Recall implementation.
Oracle lives separately in tests/fixtures/recall_s39_ground_truth.json.
"""
from datetime import date
from decimal import Decimal
from app.models import Organization, User, Farm, Plot, Product, Batch, BatchRelation
from app.hash_chain import record_event


def seed_recall_s39(db):
    engine = db.get_bind()
    if engine.dialect.name != "sqlite" or engine.url.database not in (None, "", ":memory:"):
        raise ValueError("S-39 fixture requires an explicit in-memory database")
    orgs = {}
    for code in ("ORG-FARM", "ORG-PROC", "ORG-DIST"):
        org = Organization(code=code, name=code)
        db.add(org)
        db.flush()
        orgs[code] = org.id
    actor = User(username="s39_fixture", email="fixture@s39.invalid", password="fixture-disabled", role="org_admin", organization_id=orgs["ORG-FARM"])
    product = Product(name="S39 Mango", unit="kg")
    plot = Plot(name="S39 Plot", location="Dong Thap", area=1, owner="Fixture", organization_id=orgs["ORG-FARM"])
    farm = Farm(name="S39 Farm", location="Dong Thap", area=1, owner="Fixture", organization_id=orgs["ORG-FARM"])
    db.add_all([actor, product, plot, farm]); db.flush()
    specs = [
        ("S39-ROOT-A", "ORG-FARM", 1000, 0, "SPLIT"),
        ("S39-CLEAN-X", "ORG-PROC", 200, 0, "MERGED"),
        ("S39-SPLIT-B1", "ORG-PROC", 400, 0, "MERGED"),
        ("S39-SPLIT-B2", "ORG-DIST", 600, 0, "CONSUMED"),
        ("S39-MERGE-C1", "ORG-PROC", 600, 0, "SPLIT"),
        ("S39-FINAL-D1", "ORG-DIST", 250, 250, "ACTIVE"),
        ("S39-FINAL-D2", "ORG-PROC", 350, 350, "ACTIVE"),
    ]
    batches = {}
    for code, org, initial, remaining, status in specs:
        b = Batch(code=code, plot_id=plot.id, farm_id=farm.id, product_id=product.id, harvest_date=date(2026,10,10), initial_quantity=Decimal(initial), remaining_quantity=Decimal(remaining), current_org_id=orgs[org], status=status)
        db.add(b); db.flush(); batches[code] = b
        record_event(db=db, batch_id=b.id, event_type="HARVEST" if code in ("S39-ROOT-A", "S39-CLEAN-X") else "SPLIT" if "SPLIT" in code or "FINAL" in code else "MERGE", payload={"fixture": "S39", "initial_quantity": str(initial)}, org_id=b.current_org_id, user_id=actor.id)
        if status == "CONSUMED":
            record_event(db=db, batch_id=b.id, event_type="CONSUMED", payload={"previous_remaining_quantity": str(initial), "remaining_quantity": "0.00"}, org_id=b.current_org_id, user_id=actor.id)
    edges = [
        ("S39-ROOT-A", "S39-SPLIT-B1", 400, "SPLIT"),
        ("S39-ROOT-A", "S39-SPLIT-B2", 600, "SPLIT"),
        ("S39-SPLIT-B1", "S39-MERGE-C1", 400, "MERGE"),
        ("S39-CLEAN-X", "S39-MERGE-C1", 200, "MERGE"),
        ("S39-MERGE-C1", "S39-FINAL-D1", 250, "SPLIT"),
        ("S39-MERGE-C1", "S39-FINAL-D2", 350, "SPLIT"),
    ]
    for parent, child, quantity, kind in edges:
        db.add(BatchRelation(parent_batch_id=batches[parent].id, child_batch_id=batches[child].id, transferred_quantity=Decimal(quantity), relation_type=kind))
    db.flush()
    return {code: batch.id for code, batch in batches.items()}


if __name__ == "__main__":
    import json
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.services.traceability import trace_forward
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            ids = seed_recall_s39(db)
            result = trace_forward(db, ids["S39-ROOT-A"], use_cache=False)
            print(json.dumps({"mode": "memory_only", "batches": len(ids), "descendants": result["total_descendants"], "levels_including_root": 1 + len(result["descendants_by_level"])}))
    finally:
        engine.dispose()
