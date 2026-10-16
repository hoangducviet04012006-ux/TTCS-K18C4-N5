"""Deep genealogy regression on isolated QA databases; preserve the BFS contract."""
from datetime import date
from decimal import Decimal

from app.models import Batch, BatchRelation, Organization, Product, Plot
from app.services.traceability import _detect_directed_cycle_3state, trace_forward


def test_iterative_cycle_detection_deep_and_shared_child():
    graph = {i: [i + 1] for i in range(5000)}
    assert _detect_directed_cycle_3state(graph, 0) is None
    graph[5000] = [2500]
    assert _detect_directed_cycle_3state(graph, 0) == 2500
    assert _detect_directed_cycle_3state({1: [2, 3], 2: [4], 3: [4]}, 1) is None
    assert _detect_directed_cycle_3state({1: [], 9: [10], 10: [9]}, 1) == 9


def test_forward_chain_1000_descendants(session_factory, client):
    with session_factory() as db:
        org = Organization(name="Depth QA", code="DEPTH-QA")
        product = Product(name="Depth QA", unit="kg")
        db.add_all([org, product])
        db.flush()
        plot = Plot(name="Depth QA", organization_id=org.id, area=1, location="QA", owner="QA")
        db.add(plot)
        db.flush()
        lots = [Batch(code=f"DEPTH-{i}", product_id=product.id, plot_id=plot.id,
                      harvest_date=date(2026, 10, 1), initial_quantity=Decimal("1"),
                      remaining_quantity=Decimal("1"), current_org_id=org.id,
                      status="ACTIVE") for i in range(1001)]
        db.add_all(lots)
        db.flush()
        db.add_all([BatchRelation(parent_batch_id=a.id, child_batch_id=b.id,
                                 relation_type="SPLIT", transferred_quantity=Decimal("1"))
                    for a, b in zip(lots, lots[1:])])
        db.commit()
        result = trace_forward(db, lots[0].id, use_cache=False)
        assert result["total_descendants"] == 1000
        assert result["target_batch"]["is_truncated"] is False
        assert result["terminal_batches"][0]["batch_id"] == lots[-1].id
        assert len(result["descendants_by_level"]) == 1000

        # Exercise the actual HTTP response/schema/permission path too.
        from app.main import app
        from app.security import get_current_user
        from app.models import User
        app.dependency_overrides[get_current_user] = lambda: User(role="inspector", organization_id=None)
        try:
            response = client.get(f"/batches/{lots[0].id}/trace-forward")
            assert response.status_code == 200
            payload = response.json()
            assert payload["total_descendants"] == 1000
            assert len(payload["edges"]) == 1000
            assert payload["target_batch"]["is_truncated"] is False
        finally:
            app.dependency_overrides.pop(get_current_user, None)
