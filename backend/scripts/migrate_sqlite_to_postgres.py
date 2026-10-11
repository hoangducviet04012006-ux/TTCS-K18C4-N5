"""Script tạo kịch bản migration và chuyển đổi dữ liệu từ SQLite sang PostgreSQL.

CHỈ ĐỌC BẢN SAO LƯU - TUYỆT ĐỐI KHÔNG SỬA DATABASE GỐC.

- Bảo toàn chính xác 100% ID các bản ghi.
- Bảo toàn chính xác byte-for-byte chuỗi hash (prev_hash, current_hash).
- Ánh xạ 8 tài khoản sang 7 vai trò mới.
- Sinh các lệnh setval() cho Sequences của PostgreSQL.
"""

import json
import os
import sqlite3
from decimal import Decimal

BACKUP_DB = r"d:\TTCS_K23C_N5\TTCS-K18C4-N5\backend\backups\ttcs_backup_stage1a_20261010.db"
OUTPUT_SQL = r"d:\TTCS_K23C_N5\TTCS-K18C4-N5\backend\scripts\postgres_data_dump.sql"

ROLE_MAPPING = {
    "admin": "system_admin",
    "farmer": "farmer",
    "farmer_tg": "farmer",
    "distributor": "distributor",
    "demo_farm": "farmer",
    "demo_packing": "processor",
    "demo_distribution": "distributor",
    "demo_admin": "system_admin",
}

ORPHAN_BATCH_IDS = [2, 4, 5, 6, 7, 8, 9, 10, 12, 25, 26]


def escape_sql_str(val: str | None) -> str:
    if val is None:
        return "NULL"
    escaped = val.replace("'", "''")
    return f"'{escaped}'"


def generate_postgres_migration():
    conn = sqlite3.connect(f"file:{BACKUP_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    lines = []
    lines.append("-- ==============================================================================")
    lines.append("-- AGRITRACE: POSTGRESQL DATA MIGRATION DUMP (PHASE 1B)")
    lines.append("-- Generated from verified backup: ttcs_backup_stage1a_20261010.db")
    lines.append("-- ==============================================================================\n")
    lines.append("BEGIN;\n")

    # Tắt trigger tạm thời khi nạp dữ liệu lịch sử
    lines.append("ALTER TABLE batch_events DISABLE TRIGGER trg_batch_events_immutable;\n")

    # 1. ORGANIZATIONS
    c.execute("SELECT * FROM organizations ORDER BY id")
    orgs = c.fetchall()
    lines.append(f"-- 1. ORGANIZATIONS ({len(orgs)} records)")
    for o in orgs:
        lines.append(
            f"INSERT INTO organizations (id, name, code, description) "
            f"VALUES ({o['id']}, {escape_sql_str(o['name'])}, {escape_sql_str(o['code'])}, {escape_sql_str(o['description'])});"
        )
    lines.append(f"SELECT setval('organizations_id_seq', {max(o['id'] for o in orgs)});\n")

    # 2. USERS (Áp dụng ánh xạ 8 tài khoản sang 7 vai trò mới)
    c.execute("SELECT * FROM users ORDER BY id")
    users = c.fetchall()
    lines.append(f"-- 2. USERS ({len(users)} records with mapped 7 roles)")
    for u in users:
        new_role = ROLE_MAPPING.get(u["username"], u["role"])
        org_id_val = u["organization_id"] if u["organization_id"] is not None else "NULL"
        email_val = escape_sql_str(u["email"])
        lines.append(
            f"INSERT INTO users (id, username, email, password, role, organization_id, is_active, is_locked, failed_login_attempts) "
            f"VALUES ({u['id']}, {escape_sql_str(u['username'])}, {email_val}, {escape_sql_str(u['password'])}, "
            f"'{new_role}', {org_id_val}, {u['is_active']}, {u['is_locked']}, {u['failed_login_attempts']});"
        )
    lines.append(f"SELECT setval('users_id_seq', {max(u['id'] for u in users)});\n")

    # 3. PRODUCTS
    c.execute("SELECT * FROM products ORDER BY id")
    prods = c.fetchall()
    lines.append(f"-- 3. PRODUCTS ({len(prods)} records)")
    for p in prods:
        lines.append(
            f"INSERT INTO products (id, name, unit) "
            f"VALUES ({p['id']}, {escape_sql_str(p['name'])}, {escape_sql_str(p['unit'])});"
        )
    lines.append(f"SELECT setval('products_id_seq', {max(p['id'] for p in prods)});\n")

    # 4. FARMS
    c.execute("SELECT * FROM farms ORDER BY id")
    farms = c.fetchall()
    lines.append(f"-- 4. FARMS ({len(farms)} records)")
    for f in farms:
        lines.append(
            f"INSERT INTO farms (id, name, location, area, owner, coordinates, organization_id) "
            f"VALUES ({f['id']}, {escape_sql_str(f['name'])}, {escape_sql_str(f['location'])}, {f['area']}, "
            f"{escape_sql_str(f['owner'])}, {escape_sql_str(f['coordinates'])}, {f['organization_id']});"
        )
    lines.append(f"SELECT setval('farms_id_seq', {max(f['id'] for f in farms)});\n")

    # 5. PLOTS
    c.execute("SELECT * FROM plots ORDER BY id")
    plots = c.fetchall()
    lines.append(f"-- 5. PLOTS ({len(plots)} records)")
    for pl in plots:
        lines.append(
            f"INSERT INTO plots (id, organization_id, name, location, area, coordinates, owner) "
            f"VALUES ({pl['id']}, {pl['organization_id']}, {escape_sql_str(pl['name'])}, "
            f"{escape_sql_str(pl['location'])}, {pl['area']}, {escape_sql_str(pl['coordinates'])}, "
            f"{escape_sql_str(pl['owner'])});"
        )
    if plots:
        lines.append(f"SELECT setval('plots_id_seq', {max(pl['id'] for pl in plots)});\n")
    else:
        lines.append("")

    # 6. BATCHES (Tái dựng 11 lô lịch sử có đánh dấu nguồn gốc theo Phương án A)
    c.execute("SELECT * FROM batches ORDER BY id")
    batches = c.fetchall()
    existing_ids = set(b["id"] for b in batches)
    lines.append(f"-- 6. BATCHES ({len(batches)} active/existing + 11 historical reconstructed)")
    for b in batches:
        lines.append(
            f"INSERT INTO batches (id, code, plot_id, farm_id, product_id, product_name, harvest_date, initial_quantity, remaining_quantity, quantity, current_org_id, status, is_deleted, is_reconstructed) "
            f"VALUES ({b['id']}, {escape_sql_str(b['code'])}, {b['plot_id'] or 'NULL'}, {b['farm_id'] or 'NULL'}, {b['product_id']}, "
            f"{escape_sql_str(b['product_name'])}, '{b['harvest_date']}', {b['initial_quantity']}, {b['remaining_quantity']}, {b['quantity'] or b['remaining_quantity']}, {b['current_org_id']}, {escape_sql_str(b['status'])}, FALSE, FALSE);"
        )

    # 11 Lô tái dựng lịch sử
    for bid in ORPHAN_BATCH_IDS:
        c.execute("SELECT * FROM batch_events WHERE batch_id=? ORDER BY id", (bid,))
        evs = c.fetchall()
        b_code = f"HIST-ORPHAN-{bid}"
        p_id = 1
        p_name = "Nông sản"
        init_qty = Decimal("0.0")
        h_date = "2026-09-01"
        org_id = 1
        plot_id = 1
        for e in evs:
            payload = json.loads(e["payload"]) if isinstance(e["payload"], str) else (e["payload"] or {})
            if "batch_code" in payload:
                b_code = payload["batch_code"]
            if "product_id" in payload:
                p_id = payload["product_id"]
            if "product_name" in payload:
                p_name = payload["product_name"]
            if "initial_quantity" in payload:
                init_qty = Decimal(str(payload["initial_quantity"]))
            elif "quantity" in payload:
                init_qty = Decimal(str(payload["quantity"]))
            if "harvest_date" in payload:
                h_date = payload["harvest_date"]
            if e["organization_id"]:
                org_id = e["organization_id"]
            if "plot_id" in payload:
                plot_id = payload["plot_id"]

        notes = f"Tái dựng từ {len(evs)} sự kiện lịch sử (IDs: {[e['id'] for e in evs]})."
        unverified = json.dumps(["plot_id", "updated_at", "actual_remaining_quantity_at_deletion"])
        lines.append(
            f"INSERT INTO batches (id, code, plot_id, farm_id, product_id, product_name, harvest_date, initial_quantity, remaining_quantity, quantity, current_org_id, status, is_deleted, is_reconstructed, reconstruction_notes, unverified_fields) "
            f"VALUES ({bid}, {escape_sql_str(b_code)}, {plot_id}, {plot_id}, {p_id}, {escape_sql_str(p_name)}, '{h_date}', {float(init_qty)}, 0.0, {float(init_qty)}, {org_id}, 'HISTORICAL_ARCHIVED', TRUE, TRUE, {escape_sql_str(notes)}, '{unverified}'::jsonb);"
        )
    max_b_id = max(max(existing_ids), max(ORPHAN_BATCH_IDS))
    lines.append(f"SELECT setval('batches_id_seq', {max_b_id});\n")

    # 7. BATCH_EVENTS (110 sự kiện - HASH BẢO TOÀN NGUYÊN VẸN 100%)
    c.execute("SELECT * FROM batch_events ORDER BY id")
    events = c.fetchall()
    lines.append(f"-- 7. BATCH_EVENTS ({len(events)} events - 100% cryptographic hash preserved)")
    for e in events:
        payload_str = e["payload"] if isinstance(e["payload"], str) else json.dumps(e["payload"] or {})
        payload_escaped = payload_str.replace("'", "''")
        lines.append(
            f"INSERT INTO batch_events (id, batch_id, event_type, payload, event_data, organization_id, created_by_user_id, prev_hash, current_hash, record_hash, from_org_id, to_org_id, notes, timestamp) "
            f"VALUES ({e['id']}, {e['batch_id']}, {escape_sql_str(e['event_type'])}, '{payload_escaped}'::jsonb, "
            f"{escape_sql_str(e['event_data'])}, {e['organization_id'] or 'NULL'}, {e['created_by_user_id'] or 'NULL'}, "
            f"'{e['prev_hash']}', '{e['current_hash']}', {escape_sql_str(e['record_hash'])}, "
            f"{e['from_org_id'] or 'NULL'}, {e['to_org_id'] or 'NULL'}, {escape_sql_str(e['notes'])}, '{e['timestamp']}');"
        )
    lines.append(f"SELECT setval('batch_events_id_seq', {max(e['id'] for e in events)});\n")

    # Bật lại trigger bảo vệ tính bất biến sau khi nạp xong
    lines.append("ALTER TABLE batch_events ENABLE TRIGGER trg_batch_events_immutable;\n")

    # 8. HANDOVERS
    c.execute("SELECT * FROM handovers ORDER BY id")
    handovers = c.fetchall()
    lines.append(f"-- 8. HANDOVERS ({len(handovers)} records)")
    for h in handovers:
        lines.append(
            f"INSERT INTO handovers (id, batch_id, from_org_id, to_org_id, status, reject_reason, is_overdue, created_at, updated_at) "
            f"VALUES ({h['id']}, {h['batch_id']}, {h['from_org_id']}, {h['to_org_id']}, {escape_sql_str(h['status'])}, "
            f"{escape_sql_str(h['reject_reason'])}, {h['is_overdue']}, '{h['created_at']}', '{h['updated_at']}');"
        )
    if handovers:
        lines.append(f"SELECT setval('handovers_id_seq', {max(h['id'] for h in handovers)});\n")
    else:
        lines.append("")

    # 9. BATCH_RELATIONS
    c.execute("SELECT * FROM batch_relations ORDER BY id")
    relations = c.fetchall()
    lines.append(f"-- 9. BATCH_RELATIONS ({len(relations)} records)")
    for r in relations:
        lines.append(
            f"INSERT INTO batch_relations (id, parent_batch_id, child_batch_id, relation_type, transferred_quantity, created_at) "
            f"VALUES ({r['id']}, {r['parent_batch_id']}, {r['child_batch_id']}, {escape_sql_str(r['relation_type'])}, {r['transferred_quantity']}, '{r['created_at']}');"
        )
    if relations:
        lines.append(f"SELECT setval('batch_relations_id_seq', {max(r['id'] for r in relations)});\n")
    else:
        lines.append("")

    # 10. AUDIT_LOGS
    c.execute("SELECT * FROM audit_logs ORDER BY id")
    logs = c.fetchall()
    lines.append(f"-- 10. AUDIT_LOGS ({len(logs)} records)")
    for l in logs:
        lines.append(
            f"INSERT INTO audit_logs (id, user_id, action, entity, entity_id, created_at) "
            f"VALUES ({l['id']}, {l['user_id'] or 'NULL'}, {escape_sql_str(l['action'])}, "
            f"{escape_sql_str(l['entity'])}, {l['entity_id'] or 'NULL'}, '{l['created_at']}');"
        )
    lines.append(f"SELECT setval('audit_logs_id_seq', {max(l['id'] for l in logs)});\n")

    lines.append("COMMIT;\n")

    with open(OUTPUT_SQL, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    conn.close()
    print(f"[OK] Da sinh tep migration dump: {OUTPUT_SQL} ({len(lines)} dong SQL).")


if __name__ == "__main__":
    generate_postgres_migration()
