"""Forward API compatibility, real merge edges and eight-role isolation."""
from datetime import date
from decimal import Decimal
import pytest
from app.main import app
from app.models import Batch, BatchRelation, Organization, Plot, Product, User
from app.security import get_current_user
from app.services.traceability import clear_trace_cache

@pytest.fixture
def graph_qa(session_factory):
    with session_factory() as db:
        orgs = [Organization(name=f"Graph QA {i}", code=f"GRAPH-QA-{i}") for i in range(1,4)]
        db.add_all(orgs); db.flush()
        plot = Plot(name="Graph QA", organization_id=orgs[0].id, area=1, location="Origin QA", owner="QA")
        product = Product(name="Graph QA", unit="kg")
        db.add_all([plot,product]); db.flush()
        # The unrelated second source is not a descendant of root.
        lots = [Batch(code=f"G-{i}", plot_id=plot.id, product_id=product.id,
                      harvest_date=date(2026,10,1), initial_quantity=Decimal("10"),
                      remaining_quantity=Decimal("10"), current_org_id=orgs[2 if i==4 else 1 if i==5 else 0].id,
                      status="ACTIVE") for i in range(6)]
        db.add_all(lots); db.flush()
        pairs=[(0,1,"SPLIT"),(0,2,"SPLIT"),(1,3,"MERGE"),(2,3,"MERGE"),(5,3,"MERGE"),(3,4,"SPLIT")]
        db.add_all([BatchRelation(parent_batch_id=lots[a].id,child_batch_id=lots[b].id,
                                 relation_type=t,transferred_quantity=Decimal("5")) for a,b,t in pairs])
        db.commit()
        return [o.id for o in orgs], [b.id for b in lots]

@pytest.mark.parametrize("role,org_index,allowed",[
    ("farmer",0,True),("processor",0,True),("processor",1,False),
    ("transporter",1,False),("distributor",2,True),("inspector",None,True),
    ("system_admin",0,True),("org_admin",0,True)])
def test_eight_role_scope_and_real_edges(client,session_factory,graph_qa,role,org_index,allowed):
    orgs, lots = graph_qa
    clear_trace_cache()
    with session_factory() as db:
        user=User(username="graph_actor",email="graph_actor@qa.local",password="unused",
                  role=role,organization_id=None if org_index is None else orgs[org_index])
        db.add(user); db.commit(); db.refresh(user); db.expunge(user)
    app.dependency_overrides[get_current_user]=lambda: user
    try:
        response=client.get(f"/batches/{lots[0]}/trace-forward")
        assert response.status_code==(200 if allowed else 403)
        if not allowed: return
        data=response.json()
        assert {"target_batch","descendants_by_level","terminal_batches","total_descendants","edges"} <= data.keys()
        assert data["total_descendants"]==4
        nodes=[n for group in data["descendants_by_level"].values() for n in group]
        assert all({"parent_batch_id","location","owner","initial_quantity","remaining_quantity","is_masked"}<=n.keys() for n in nodes)
        pairs={(e["parent_batch_id"],e["child_batch_id"]) for e in data["edges"]}
        expected={(lots[0],lots[1]),(lots[0],lots[2]),(lots[1],lots[3]),(lots[2],lots[3])}
        if role in ("inspector", "distributor"): expected.add((lots[3],lots[4]))
        assert pairs==expected
        assert all(e["relation_type"] in ("SPLIT","MERGE") and e["transferred_quantity"]==5 for e in data["edges"])
        assert lots[5] not in {n["batch_id"] for n in nodes}
        assert all(e["parent_batch_id"]!=lots[5] for e in data["edges"])
        # Cached raw service response must not be modified by caller masking.
        app.dependency_overrides[get_current_user]=lambda: User(id=user.id,role="inspector",organization_id=None)
        again=client.get(f"/batches/{lots[0]}/trace-forward").json()
        assert len(again["edges"])==5
        assert all(not n["is_masked"] for group in again["descendants_by_level"].values() for n in group)
    finally:
        app.dependency_overrides.pop(get_current_user,None)
        clear_trace_cache()

def test_old_response_without_edges_still_valid():
    from app.schemas import TraceForwardResponse
    old={"target_batch":{"id":1},"descendants_by_level":{},"terminal_batches":[],"total_descendants":0}
    parsed=TraceForwardResponse.model_validate(old)
    assert parsed.edges==[]
    assert parsed.model_dump(exclude={"edges"})==old
