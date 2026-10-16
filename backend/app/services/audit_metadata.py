"""Additive audit metadata; legacy database reads/writes remain supported."""

import json
from contextvars import ContextVar
from ipaddress import ip_address
from sqlalchemy import inspect, text

request_ip = ContextVar("audit_request_ip", default=None)
COLUMNS = {
    "source_ip": "VARCHAR(45)",
    "operation": "VARCHAR(40)",
    "organization_id": "INTEGER",
    "batch_ids": "TEXT",
    "location_id": "INTEGER",
    "location_name": "TEXT",
    "location_address": "TEXT",
}


def clean_ip(value):
    try:
        return str(ip_address(value)) if value else None
    except ValueError:
        return None


def ready(db):
    engine = db.get_bind()
    if not hasattr(engine, "_audit_d_ready"):
        found = {c["name"] for c in inspect(db.connection()).get_columns("audit_logs")}
        engine._audit_d_ready = set(COLUMNS).issubset(found)
    return engine._audit_d_ready


def save(db, log, user, operation, batch_ids, location):
    if not ready(db):
        return
    db.flush()
    scope_org = user.organization_id
    # Administrative actions on foreign targets must not become visible in the actor's org.
    if log.entity in {"farm", "user", "organization"}:
        from app.models import Farm, User, Organization

        model = {"farm": Farm, "user": User, "organization": Organization}[log.entity]
        target = db.get(model, log.entity_id)
        target_org = target.id if log.entity == "organization" and target else getattr(target, "organization_id", None)
        if log.action.lower() != "delete" and target_org != scope_org:
            scope_org = None
    values = {
        "id": log.id,
        "source_ip": request_ip.get(),
        "operation": operation,
        "organization_id": scope_org,
        "batch_ids": json.dumps(sorted(set(batch_ids))),
        "location_id": (location or {}).get("id"),
        "location_name": (location or {}).get("name"),
        "location_address": (location or {}).get("address"),
    }
    assignments = ",".join(key + "=:" + key for key in COLUMNS)
    db.execute(text("UPDATE audit_logs SET " + assignments + " WHERE id=:id"), values)
    log._audit_details = {k: values[k] for k in COLUMNS}
    log._audit_details["batch_ids"] = json.loads(values["batch_ids"])


def hydrate(db, logs):
    if not logs or not ready(db):
        return logs
    params = {"id" + str(i): log.id for i, log in enumerate(logs)}
    rows = db.execute(
        text("SELECT id," + ",".join(COLUMNS) + " FROM audit_logs WHERE id IN (" + ",".join(":" + k for k in params) + ")"),
        params,
    ).mappings()
    details = {}
    for row in rows:
        data = dict(row)
        data["batch_ids"] = json.loads(data["batch_ids"] or "[]")
        details[data["id"]] = data
    for log in logs:
        log._audit_details = details.get(log.id, {})
    return logs
