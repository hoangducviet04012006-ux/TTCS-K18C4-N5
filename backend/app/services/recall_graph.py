"""Uncached complete Recall graph with global cycle checks and unique nodes."""
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import select

from app.hash_chain import verify_batch_chain
from app.models import Batch, BatchEvent, BatchRelation

MAX_GRAPH_NODES = 1000


def descendant_levels(outgoing, root_id):
    levels = {root_id: 0}
    queue = deque([root_id])
    while queue:
        parent = queue.popleft()
        for child in sorted(outgoing[parent]):
            if child not in levels:
                levels[child] = levels[parent] + 1
                if len(levels) > MAX_GRAPH_NODES:
                    raise HTTPException(409, {"code": "INCOMPLETE_GRAPH", "message": "Recall graph exceeds max_nodes"})
                queue.append(child)
    return levels


def bounded_ancestors(incoming, levels):
    relevant = set(levels)
    queue = deque(relevant)
    while queue:
        child = queue.popleft()
        for parent in incoming[child]:
            if parent not in relevant:
                relevant.add(parent)
                if len(relevant) > MAX_GRAPH_NODES:
                    raise HTTPException(409, {
                        "code": "INCOMPLETE_GRAPH", "message": "Recall ancestry exceeds max_nodes"
                    })
                queue.append(parent)
    return relevant


def origins_or_fail(outgoing, incoming, relevant):
    indegree = {node: len(incoming[node] & relevant) for node in relevant}
    queue = deque(sorted(node for node, degree in indegree.items() if degree == 0))
    origins = defaultdict(set)
    ordered = []
    while queue:
        node = queue.popleft()
        ordered.append(node)
        if not incoming[node]:
            origins[node].add(node)
        for child in outgoing[node] & relevant:
            origins[child].update(origins[node])
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(ordered) != len(relevant):
        raise HTTPException(400, {"code": "CYCLE_DETECTED", "message": "Cycle detected in Recall graph"})
    return origins


def graph_snapshot(db, root_id):
    """Validate affected descendants AND their ancestors, including other origins.

    Traversal does not stop at CONSUMED: anomalous later children stay confined.
    No truncated result or visited-path shortcut can bypass a cycle check.
    """
    if db.get(Batch, root_id) is None:
        raise HTTPException(404, "Batch not found")
    outgoing, incoming = defaultdict(set), defaultdict(set)
    for parent, child in db.execute(select(BatchRelation.parent_batch_id, BatchRelation.child_batch_id)):
        outgoing[parent].add(child)
        incoming[child].add(parent)
    levels = descendant_levels(outgoing, root_id)
    relevant = bounded_ancestors(incoming, levels)
    origins = origins_or_fail(outgoing, incoming, relevant)
    batches = {b.id: b for b in db.scalars(select(Batch).where(Batch.id.in_(relevant))).all()}
    if set(batches) != relevant:
        raise HTTPException(409, {"code": "INCOMPLETE_GRAPH", "message": "Dangling batch relation"})
    return {
        "batches": [batches[node] for node in sorted(levels, key=lambda n: (levels[n], n))],
        "levels": levels,
        "origins": origins,
        "incoming": incoming,
    }


def consumed_evidence(db, batches):
    evidence = defaultdict(list)
    for event in db.scalars(select(BatchEvent).where(
        BatchEvent.batch_id.in_([b.id for b in batches]), BatchEvent.event_type == "CONSUMED"
    )).all():
        evidence[event.batch_id].append(event)
    result = {}
    for batch in batches:
        events = evidence[batch.id]
        if not events:
            result[batch.id] = None if batch.status == "CONSUMED" else Decimal("0")
            continue
        if len(events) != 1 or not verify_batch_chain(db, batch.id)["is_valid"]:
            result[batch.id] = None
            continue
        total = Decimal("0")
        for event in events:
            try:
                value = Decimal(str(event.payload["previous_remaining_quantity"]))
                if not value.is_finite() or value < 0:
                    raise ValueError("Invalid consumed evidence")
                total += value
            except (KeyError, TypeError, InvalidOperation, ValueError):
                total = None
                break
        result[batch.id] = total
    return result
