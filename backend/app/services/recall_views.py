"""Recall projections: real locations/edges and filters after permission scoping."""

from collections import defaultdict
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select
from app.models import BatchRelation
from app.services.locations import location_map


def enrich(db, response, user, filters=None):
    rows = response["affected_batches"]
    places = location_map(db, [b["batch_id"] for b in rows])
    for node in rows:
        p = places.get(node["batch_id"], {})
        node.update(location_id=p.get("id"), current_location=p.get("address"), current_location_name=p.get("name"))
    response["filter_options"] = {
        "organizations": sorted({(n["organization_id"], n["organization_name"]) for n in rows}),
        "locations": sorted({(n["location_id"], n["current_location_name"]) for n in rows if n["location_id"] is not None}),
    }
    filters = filters or {}
    org = filters.get("organization_id")
    if org is not None and user.role != "inspector" and org != user.organization_id:
        raise HTTPException(403, "Không có quyền lọc Recall của tổ chức khác.")
    selected = [
        n
        for n in rows
        if (org is None or n["organization_id"] == org)
        and (filters.get("location_id") is None or n["location_id"] == filters["location_id"])
        and (not filters.get("unknown_location") or n["location_id"] is None)
        and (not filters.get("batch_status") or n["status"] == filters["batch_status"])
    ]
    visible_ids = {n["batch_id"] for n in selected}
    response["affected_edges"] = [
        {
            "parent_batch_id": edge.parent_batch_id,
            "child_batch_id": edge.child_batch_id,
            "relation_type": edge.relation_type,
            "transferred_quantity": str(edge.transferred_quantity),
        }
        for edge in db.scalars(
            select(BatchRelation).where(
                BatchRelation.parent_batch_id.in_(visible_ids), BatchRelation.child_batch_id.in_(visible_ids)
            )
        )
    ]
    response["affected_batches"] = selected
    response["filtered_batch_count"] = len(selected)
    response["filters"] = filters
    totals = defaultdict(
        lambda: {"reclaimable_quantity": Decimal(0), "known_consumed_quantity": Decimal(0), "unknown_consumed_batch_ids": []}
    )
    for node in selected:
        metric = totals[node["unit"]]
        metric["reclaimable_quantity"] += Decimal(node["remaining_quantity"])
        if node["consumed_quantity"] is None:
            metric["unknown_consumed_batch_ids"].append(node["batch_id"])
        else:
            metric["known_consumed_quantity"] += Decimal(node["consumed_quantity"])
    response["filtered_metrics_by_unit"] = {
        unit: {
            "reclaimable_quantity": str(m["reclaimable_quantity"]),
            "known_consumed_quantity": str(m["known_consumed_quantity"]),
            "consumed_quantity": None if m["unknown_consumed_batch_ids"] else str(m["known_consumed_quantity"]),
            "unknown_consumed_batch_ids": m["unknown_consumed_batch_ids"],
        }
        for unit, m in totals.items()
    }
    own = next((a for a in response["acknowledgments"] if a["organization_id"] == user.organization_id), None)
    response["can_acknowledge"] = (
        user.role == "org_admin" and response["status"] == "OPEN" and bool(own and own["status"] == "PENDING")
    )
    response["reminder"] = {
        "mode": "IN_APP_STUB",
        "delivery": "Không gửi email/SMS",
        "escalation_after_hours": 24,
        "pending": any(a["status"] == "PENDING" for a in response["acknowledgments"]),
    }
    return response
