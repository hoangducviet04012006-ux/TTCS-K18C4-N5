"""Atomic Recall commands, immutable event evidence and organization views."""
import hashlib
import json
import logging
from collections import defaultdict
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.audit import record_action
from app.hash_chain import event_now, record_event
from app.models import BatchEvent, Organization
from app.recall_models import IdempotencyRecord, Recall, RecallAcknowledgment
from app.services.rbac import can_recall_batch, get_effective_role
from app.services.recall_database import (
    acquire_write_lock, begin_read_snapshot, recall_schema_available, require_recall_database,
)
from app.services.recall_graph import consumed_evidence, graph_snapshot

logger = logging.getLogger(__name__)


def related(db, recall, user, graph):
    if get_effective_role(user) == "inspector":
        return True
    if user.organization_id is None:
        return False
    return any(b.current_org_id == user.organization_id for b in graph["batches"]) or db.scalar(
        select(RecallAcknowledgment.id).where(
            RecallAcknowledgment.recall_id == recall.id,
            RecallAcknowledgment.organization_id == user.organization_id,
        )
    ) is not None


def affected_evidence_ids(db, recall):
    ids = {recall.root_batch_id}
    for event in db.scalars(select(BatchEvent).where(
        BatchEvent.event_type.in_(["RECALL_INIT", "RECALL_AFFECTED"])
    )).all():
        if isinstance(event.payload, dict) and event.payload.get("recall_id") == recall.id:
            ids.add(event.batch_id)
    return ids


def detail(db, recall, user, graph=None, filters=None):
    graph = graph or graph_snapshot(db, recall.root_batch_id)
    if not related(db, recall, user, graph):
        raise HTTPException(403, "Recall does not involve your organization")
    inspector = get_effective_role(user) == "inspector"
    batches = graph["batches"]
    visible = [b for b in batches if inspector or b.current_org_id == user.organization_id]
    evidence = consumed_evidence(db, visible)
    metrics = defaultdict(lambda: {
        "reclaimable": Decimal("0"), "consumed_known": Decimal("0"), "unknown_consumed_batch_ids": []
    })
    nodes = []
    for batch in visible:
        consumed = evidence[batch.id]
        metric = metrics[batch.unit]
        metric["reclaimable"] += batch.remaining_quantity
        if consumed is None:
            metric["unknown_consumed_batch_ids"].append(batch.id)
        else:
            metric["consumed_known"] += consumed
        nodes.append({
            "batch_id": batch.id, "code": batch.code, "level": graph["levels"][batch.id],
            "organization_id": batch.current_org_id, "organization_name": batch.current_org_name,
            "location": batch.plot.location if batch.plot else None,
            "status": batch.status, "unit": batch.unit,
            "remaining_quantity": str(batch.remaining_quantity),
            "consumed_quantity": None if consumed is None else str(consumed),
            "consumed_evidence_missing": consumed is None,
            "is_merged_cross_origin": len(graph["origins"][batch.id]) > 1,
        })
    acknowledgments = list(db.scalars(select(RecallAcknowledgment).where(
        RecallAcknowledgment.recall_id == recall.id
    ).order_by(RecallAcknowledgment.organization_id)).all())
    projected = {ack.organization_id: ack for ack in acknowledgments}
    required = {b.current_org_id for b in batches} | set(projected)
    new_ids = set(graph["levels"]) - affected_evidence_ids(db, recall)
    changed_ack_scope = any(
        b.id in new_ids and b.current_org_id in projected
        and projected[b.current_org_id].status == "ACKNOWLEDGED" for b in batches
    )
    anomaly = bool(new_ids) and (recall.status == "COMPLETED" or changed_ack_scope)
    anomaly_code = (
        "NEW_DESCENDANTS_AFTER_COMPLETION" if recall.status == "COMPLETED" else "GRAPH_CHANGED_AFTER_ACK"
    )
    if anomaly:
        logger.warning(
            "Recall anomaly: %s has %d new descendants after completion or acknowledgment (%s)",
            recall.recall_code, len(new_ids), anomaly_code,
        )
    progress = []
    for org_id in sorted(required):
        if not inspector and org_id != user.organization_id:
            continue
        ack = projected.get(org_id)
        org = db.get(Organization, org_id)
        progress.append({
            "organization_id": org_id, "organization_name": org.name if org else None,
            "status": ack.status if ack else "PENDING",
            "acknowledged_at": ack.acknowledged_at.isoformat() if ack and ack.acknowledged_at else None,
            "notes": ack.notes if ack else None,
        })
    root_batch = next((b for b in batches if b.id == recall.root_batch_id), batches[0] if batches else None)
    from app.services.recall_views import enrich
    return enrich(db, {
        "id": recall.id, "recall_code": recall.recall_code, "root_batch_id": recall.root_batch_id,
        "batch_code": root_batch.code if root_batch else None,
        "reason": recall.reason, "status": recall.status,
        "incident_status": "Có sự cố",
        "created_at": recall.created_at.isoformat(),
        "created_by_user_id": recall.created_by_user_id,
        "completed_at": recall.completed_at.isoformat() if recall.completed_at else None,
        "policy": "ONE_RECALL_PER_ROOT_LIFETIME_PENDING_MENTOR",
        "affected_batches": nodes, "visible_batch_count": len(nodes),
        "total_affected_batch_count": len(batches) if inspector else None,
        "metrics_by_unit": {unit: {
            "reclaimable_quantity": str(m["reclaimable"]),
            "consumed_quantity": None if m["unknown_consumed_batch_ids"] else str(m["consumed_known"]),
            "known_consumed_quantity": str(m["consumed_known"]),
            "unknown_consumed_batch_ids": m["unknown_consumed_batch_ids"],
        } for unit, m in metrics.items()},
        "acknowledgments": progress,
        "progress": {
            "acknowledged": sum(a.status == "ACKNOWLEDGED" for a in acknowledgments), "required": len(required)
        },
        "anomaly": {
            "code": anomaly_code,
            "new_batch_ids": [b.id for b in visible if b.id in new_ids],
            "quarantine_continues": True,
        } if anomaly else None,
        "quarantined": True,
    }, user, filters)


def get_recall(db, recall_id):
    recall = db.get(Recall, recall_id)
    if recall is None:
        raise HTTPException(404, "Recall not found")
    return recall


def list_recalls(db, user, alerts=False):
    require_recall_database(db)
    begin_read_snapshot(db)
    if alerts and user.organization_id is None:
        return []
    result = []
    for recall in db.scalars(select(Recall).order_by(Recall.id.desc())).all():
        graph = graph_snapshot(db, recall.root_batch_id)
        if related(db, recall, user, graph):
            view = detail(db, recall, user, graph)
            if alerts:
                view["alert_severity"] = "CRITICAL" if recall.status == "OPEN" or view["anomaly"] else "QUARANTINED"
            result.append(view)
    return result


def event(db, recall, batch, kind, user, **extra):
    return record_event(
        db=db, batch_id=batch.id, event_type=kind,
        payload={"recall_id": recall.id, "recall_code": recall.recall_code, **extra},
        org_id=user.organization_id or batch.current_org_id, user_id=user.id,
    )


def synchronize_open(db, recall, graph, user):
    """Reconcile newly visible orgs/nodes atomically, without duplicating evidence."""
    orgs = {b.current_org_id for b in graph["batches"]}
    acknowledgments = list(db.scalars(select(RecallAcknowledgment).where(
        RecallAcknowledgment.recall_id == recall.id
    )).all())
    existing = {ack.organization_id for ack in acknowledgments}
    acknowledged_orgs = {ack.organization_id for ack in acknowledgments if ack.status == "ACKNOWLEDGED"}
    known = affected_evidence_ids(db, recall)
    if any(b.id not in known and b.current_org_id in acknowledged_orgs for b in graph["batches"]):
        # A previous immutable ACK cannot certify out-of-band additions. Never
        # reset its evidence or silently complete; keep OPEN for inspector review.
        raise HTTPException(409, {"code": "GRAPH_CHANGED_AFTER_ACK", "recall_code": recall.recall_code})
    for org_id in sorted(orgs - existing):
        db.add(RecallAcknowledgment(recall_id=recall.id, organization_id=org_id))
    for batch in graph["batches"]:
        if batch.id not in known:
            event(db, recall, batch, "RECALL_AFFECTED", user)
    db.flush()


def command(db, user, endpoint, key, payload, execute):
    """Single owner of commit/rollback for every successful Recall command."""
    require_recall_database(db)
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    request_hash = hashlib.sha256(encoded).hexdigest()
    try:
        acquire_write_lock(db)
        prior = db.get(IdempotencyRecord, (key, user.id, endpoint))
        visibility_scope = {"role": get_effective_role(user), "organization_id": user.organization_id}
        if prior:
            if prior.request_hash != request_hash:
                raise HTTPException(409, {
                    "code": "IDEMPOTENCY_CONFLICT", "message": "Key was used with another payload"
                })
            stored = json.loads(prior.response_body)
            if stored.get("scope") != visibility_scope:
                raise HTTPException(
                    403, "Replay visibility changed; stored response is not available in this role or organization"
                )
            response = stored["response"]
            # Reauthorize every replay against current role and organization state.
            recall = get_recall(db, response["id"])
            graph = graph_snapshot(db, recall.root_batch_id)
            if endpoint == "recall.create":
                can_recall_batch(user, graph["batches"][0])
            elif get_effective_role(user) != "org_admin" or not related(db, recall, user, graph):
                raise HTTPException(403, "Only a related organization admin may acknowledge")
            db.rollback()
            return response
        response = execute()
        db.add(IdempotencyRecord(
            key=key, user_id=user.id, endpoint=endpoint, request_hash=request_hash,
            response_code=201 if endpoint == "recall.create" else 200,
            response_body=json.dumps({"scope": visibility_scope, "response": response}, ensure_ascii=False),
        ))
        db.commit()
        return response
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, {
            "code": "RECALL_CONFLICT",
            "message": "Concurrent Recall or acknowledgment conflicts with existing evidence",
        }) from exc
    except OperationalError as exc:
        db.rollback()
        raise HTTPException(
            503, "Recall database is busy; retry with the same Idempotency-Key", headers={"Retry-After": "1"}
        ) from exc
    except Exception:
        db.rollback()
        raise


def create_recall(db, user, root_batch_id, reason, key):
    def execute():
        graph = graph_snapshot(db, root_batch_id)
        root = graph["batches"][0]
        can_recall_batch(user, root)
        existing = db.scalar(select(Recall).where(Recall.root_batch_id == root_batch_id))
        if existing:
            raise HTTPException(409, {
                "code": "ROOT_ALREADY_RECALLED", "recall_code": existing.recall_code, "recall_id": existing.id
            })
        recall = Recall(
            recall_code="REC-" + event_now().strftime("%Y%m") + "-" + uuid4().hex[:12].upper(),
            root_batch_id=root_batch_id, reason=reason, created_by_user_id=user.id,
            created_by_org_id=user.organization_id, status="OPEN",
        )
        db.add(recall)
        db.flush()
        event(db, recall, root, "RECALL_INIT", user, reason=reason)
        for batch in graph["batches"][1:]:
            event(db, recall, batch, "RECALL_AFFECTED", user)
        for org_id in sorted({b.current_org_id for b in graph["batches"]}):
            db.add(RecallAcknowledgment(recall_id=recall.id, organization_id=org_id))
        record_action(db, user, "CREATE", "recall", recall.id,
                      operation="recall", batch_ids=[root_batch_id])
        db.flush()
        return detail(db, recall, user, graph)
    return command(db, user, "recall.create", key, {"root_batch_id": root_batch_id, "reason": reason}, execute)


def acknowledge(db, user, recall_id, notes, key):
    def execute():
        if get_effective_role(user) != "org_admin" or user.organization_id is None:
            raise HTTPException(403, "Only a related organization admin may acknowledge")
        recall = get_recall(db, recall_id)
        graph = graph_snapshot(db, recall.root_batch_id)
        if not related(db, recall, user, graph):
            raise HTTPException(403, "Cannot acknowledge for another organization")
        if recall.status == "COMPLETED":
            raise HTTPException(409, {"code": "RECALL_COMPLETED", "recall_code": recall.recall_code})
        synchronize_open(db, recall, graph, user)
        ack = db.scalar(select(RecallAcknowledgment).where(
            RecallAcknowledgment.recall_id == recall.id,
            RecallAcknowledgment.organization_id == user.organization_id,
        ))
        if ack is None:
            raise HTTPException(403, "Organization is not part of this Recall")
        if ack.status == "ACKNOWLEDGED":
            raise HTTPException(409, {"code": "ALREADY_ACKNOWLEDGED", "recall_code": recall.recall_code})
        ack.status = "ACKNOWLEDGED"
        ack.acknowledged_by_user_id = user.id
        ack.acknowledged_at = event_now()
        ack.notes = notes
        root = graph["batches"][0]
        event(db, recall, root, "RECALL_ACKNOWLEDGED", user, organization_id=user.organization_id, notes=notes)
        record_action(db, user, "UPDATE", "recall", recall.id,
                      operation="confirm", batch_ids=[recall.root_batch_id])
        db.flush()
        pending = db.scalar(select(RecallAcknowledgment.id).where(
            RecallAcknowledgment.recall_id == recall.id, RecallAcknowledgment.status == "PENDING"
        ).limit(1))
        if pending is None:
            recall.status = "COMPLETED"
            recall.completed_at = event_now()
            event(db, recall, root, "RECALL_COMPLETED", user)
            record_action(db, user, "COMPLETE", "recall", recall.id,
                          operation="recall_complete", batch_ids=[recall.root_batch_id])
            db.flush()
        return detail(db, recall, user, graph)
    return command(db, user, f"recall.ack:{recall_id}", key, {"notes": notes}, execute)


def ensure_not_recalled(db, batch_id):
    """Common physical-operation gate; caller holds the SQLite writer lock."""
    if not recall_schema_available(db):
        return
    for recall in db.scalars(select(Recall).order_by(Recall.id)).all():
        graph = graph_snapshot(db, recall.root_batch_id)
        if batch_id in graph["levels"]:
            raise HTTPException(409, {
                "code": "BATCH_QUARANTINED", "recall_code": recall.recall_code,
                "recall_status": recall.status,
                "anomaly": recall.status == "COMPLETED" and bool(
                    set(graph["levels"]) - affected_evidence_ids(db, recall)
                ),
            })
