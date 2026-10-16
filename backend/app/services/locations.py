"""Location storage boundary compatible with databases not yet migrated."""

from fastapi import HTTPException
from sqlalchemy import inspect, text
from app.services.recall_database import acquire_write_lock


def probe_schema(db):
    inspector = inspect(db.connection())
    ready = "locations" in inspector.get_table_names() and any(
        c["name"] == "location_id" for c in inspector.get_columns("batches")
    )
    db.get_bind()._phase_c_ready = ready
    return ready


def schema_available(db):
    return getattr(db.get_bind(), "_phase_c_ready", False)


def require_schema(db):
    if not schema_available(db):
        raise HTTPException(503, "Địa điểm chưa sẵn sàng; cần migration trên database QA riêng.")


def begin_write(db):
    require_schema(db)
    db.connection().exec_driver_sql("PRAGMA foreign_keys=ON")
    if db.connection().exec_driver_sql("PRAGMA foreign_keys").scalar() != 1:
        raise HTTPException(503, "Địa điểm cần bật kiểm tra khóa ngoại.")
    acquire_write_lock(db)


def location_map(db, batch_ids):
    if not batch_ids or not schema_available(db):
        return {}
    ids = list(set(batch_ids))
    params = {f"id{i}": value for i, value in enumerate(ids)}
    placeholders = ",".join(":" + key for key in params)
    rows = db.execute(
        text(
            "SELECT b.id AS batch_id,l.id,l.code,l.name,l.address FROM batches b "
            "JOIN locations l ON l.id=b.location_id AND l.organization_id=b.current_org_id "
            f"WHERE b.id IN ({placeholders})"
        ),
        params,
    ).mappings()
    return {row["batch_id"]: dict(row) for row in rows}


def hydrate(db, batches):
    info = location_map(db, [b.id for b in batches])
    for batch in batches:
        batch._phase_c_location = info.get(batch.id, {})
    return batches


def set_location(db, batch_id, location_id):
    require_schema(db)
    db.execute(text("UPDATE batches SET location_id=:location_id WHERE id=:id"), {"id": batch_id, "location_id": location_id})


def inherited_location(db, parents):
    info = location_map(db, [p.id for p in parents])
    values = [info.get(p.id, {}).get("id") for p in parents]
    return values[0] if values and len(set(values)) == 1 else None


def clear_on_handover(db, batch_id):
    if schema_available(db):
        set_location(db, batch_id, None)


def attach_forward_locations(db, result):
    nodes = [n for group in result["descendants_by_level"].values() for n in group]
    nodes += result["terminal_batches"]
    target = result["target_batch"]
    info = location_map(db, [target["id"], *[n["batch_id"] for n in nodes]])
    for node in [target, *nodes]:
        data = info.get(node.get("batch_id", node.get("id")), {})
        node["location_id"] = data.get("id")
        node["current_location"] = data.get("address")
        node["current_location_name"] = data.get("name")
    return result


def restrict_forward_locations_and_edges(db, user, root_id, result, descendants, terminals, permissions):
    """New location metadata and topology require view permission at both ends."""
    from app.services.permissions import can_view_batch
    from app.models import ROLE_INSPECTOR

    nodes = [node for group in descendants.values() for node in group]
    represented_ids = {root_id, *[node["batch_id"] for node in nodes]}
    if user.role == ROLE_INSPECTOR:
        viewable_ids = represented_ids
    else:
        for node_id in represented_ids:
            if node_id not in permissions:
                permissions[node_id] = can_view_batch(db, user.organization_id, node_id, user_role=user.role)
        viewable_ids = {node_id for node_id, allowed in permissions.items() if allowed}
    for node in [*nodes, *terminals]:
        if node["batch_id"] not in viewable_ids:
            for field in ("location_id", "current_location", "current_location_name"):
                node[field] = None
    return [
        dict(edge)
        for edge in result.get("edges", [])
        if edge["parent_batch_id"] in viewable_ids and edge["child_batch_id"] in viewable_ids
    ]
