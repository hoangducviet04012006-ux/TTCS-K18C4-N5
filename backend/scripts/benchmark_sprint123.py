"""Read-only-to-production benchmarks. Synthetic SQLite memory only, no migration."""
import json
from datetime import date
from time import perf_counter
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Batch, BatchRelation, Organization, User
from app.seeds.seed_lineage_graph import seed_lineage_graph
from app.hash_chain import record_event, verify_batch_chain
from app.services.traceability import trace_backwards
from app.routers.events import list_events_for_batch
from app.routers.batches import list_batches, get_batch_summary


def run():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if not t.info.get("recall_trial")])
    counters = {"queries": 0}
    @event.listens_for(engine, "before_cursor_execute")
    def count(*_):
        counters["queries"] += 1
    results = {}
    with Session(engine) as db:
        ids = seed_lineage_graph(db)
        root = db.get(Batch, ids["B-ROOT-01"])
        org = db.scalar(select(Organization).where(Organization.code == "HTX-DT"))
        actor = User(username="benchmark_actor", role="farmer", password="disabled", organization_id=org.id)
        db.add(actor); db.flush()
        def new_batch(code):
            b = Batch(code=code, farm_id=root.farm_id, plot_id=root.plot_id, product_id=root.product_id, harvest_date=date.today(), initial_quantity=100, remaining_quantity=100, current_org_id=org.id, status="ACTIVE")
            db.add(b)
            return b
        chain_batch = new_batch("BENCH-EVENTS-1000"); timeline = new_batch("BENCH-TIMELINE-200")
        db.flush()
        start = perf_counter()
        for i in range(1000):
            record_event(db, chain_batch.id, "BENCHMARK", {"i": i}, org.id, actor.id)
        db.commit()
        results["write_1000_events_seconds"] = perf_counter()-start
        start = perf_counter(); valid = verify_batch_chain(db, chain_batch.id)
        results["verify_1000_events"] = {"seconds":perf_counter()-start,"valid":valid["is_valid"],"events":valid["total_events"]}
        for i in range(200):
            record_event(db, timeline.id, "BENCHMARK", {"i":i}, org.id, actor.id)
        db.commit()
        start = perf_counter(); rows = list_events_for_batch(timeline.id, actor, db)
        results["timeline_200_events"] = {"seconds":perf_counter()-start,"events":len(rows)}
        nodes=[new_batch(f"BENCH-NODE-{i:04d}") for i in range(1000)]
        db.flush()
        db.add_all([BatchRelation(parent_batch_id=nodes[i-1].id,child_batch_id=nodes[i].id,transferred_quantity=1,relation_type="SPLIT") for i in range(1,1000)])
        db.commit()
        last_id=nodes[-1].id
        db.expire_all()
        start=perf_counter(); trace=trace_backwards(db,last_id,use_cache=False)
        results["backwards_1000_nodes"]={"seconds":perf_counter()-start,"ancestors":trace["total_ancestors"]}
        for i in range(4000): new_batch(f"BENCH-LIST-{i:04d}")
        db.commit(); db.expire_all()
        counters["queries"]=0; start=perf_counter()
        rows=list_batches(current_user=actor,db=db,page=1,limit=20,search=None,product_id=None)
        # Include normal response serialization, which can trigger lazy queries.
        from app.schemas import BatchResponse
        [BatchResponse.model_validate(b) for b in rows]
        results["list_5000plus_batches"]={"seconds":perf_counter()-start,"returned":len(rows),"queries":counters["queries"]}
        db.expire_all(); _ = actor.organization_id; counters["queries"]=0; start=perf_counter()
        result=get_batch_summary(batch_id=ids["B-MERGE-01"],current_user=actor,db=db)
        results["summary"]={"seconds":perf_counter()-start,"queries":counters["queries"],"parents":len(result.direct_parents)}
    engine.dispose()
    return results


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
