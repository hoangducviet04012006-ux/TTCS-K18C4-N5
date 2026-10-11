import sqlite3
import json

conn = sqlite3.connect("file:ttcs.db?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

orphans = [2, 4, 5, 6, 7, 8, 9, 10, 12, 25, 26]

import sys

out_file = open("scripts/orphans_report.txt", "w", encoding="utf-8")
def log(s=""):
    out_file.write(s + "\n")

log(f"=== BÁO CÁO CHI TIẾT 11 BATCH ID MỒ CÔI (Tổng 26 sự kiện) ===\n")

for bid in orphans:
    evs = conn.execute("SELECT * FROM batch_events WHERE batch_id=? ORDER BY id", (bid,)).fetchall()
    rels_parent = conn.execute("SELECT * FROM batch_relations WHERE parent_batch_id=?", (bid,)).fetchall()
    rels_child = conn.execute("SELECT * FROM batch_relations WHERE child_batch_id=?", (bid,)).fetchall()

    event_summaries = []
    codes = set()
    products = set()
    quantities = []
    harvest_dates = set()
    org_ids = set()
    evidence_fields = set()
    unverified_fields = {"plot_id", "current_remaining_quantity", "is_deleted_original_reason"}

    for e in evs:
        ev_type = e["event_type"]
        ts = e["timestamp"]
        org_id = e["organization_id"]
        if org_id:
            org_ids.add(org_id)
            evidence_fields.add("organization_id")

        p = json.loads(e["payload"]) if e["payload"] and isinstance(e["payload"], str) else (e["payload"] or {})
        
        # Kiểm tra các trường trong payload
        if "batch_code" in p:
            codes.add(p["batch_code"])
            evidence_fields.add("code")
        if "code" in p:
            codes.add(p["code"])
            evidence_fields.add("code")
        if "product_name" in p:
            products.add(p["product_name"])
            evidence_fields.add("product_name")
        if "product_id" in p:
            products.add(f"id:{p['product_id']}")
            evidence_fields.add("product_id")
        if "initial_quantity" in p:
            quantities.append(f"initial:{p['initial_quantity']}")
            evidence_fields.add("initial_quantity")
        if "quantity" in p:
            quantities.append(f"qty:{p['quantity']}")
            evidence_fields.add("quantity")
        if "harvest_date" in p:
            harvest_dates.add(p["harvest_date"])
            evidence_fields.add("harvest_date")

        event_summaries.append({
            "id": e["id"],
            "event_type": ev_type,
            "timestamp": ts,
            "org_id": org_id,
            "user_id": e["user_id"] or e["created_by_user_id"],
            "payload_keys": list(p.keys()),
            "prev_hash": e["prev_hash"][:10] + "..." if e["prev_hash"] else None,
            "current_hash": e["current_hash"][:10] + "..." if e["current_hash"] else None,
        })

    parent_relations = [dict(r) for r in rels_parent]
    child_relations = [dict(r) for r in rels_child]

    log(f"--------------------------------------------------------------------------------")
    log(f"BATCH ID: {bid}")
    log(f"  - Số sự kiện tham chiếu: {len(evs)}")
    log(f"  - Mã lô xác minh được: {list(codes) if codes else 'KHÔNG TÌM THẤY TRONG PAYLOAD'}")
    log(f"  - Sản phẩm: {list(products) if products else 'Không có trong payload'}")
    log(f"  - Khối lượng ghi nhận: {quantities if quantities else 'Không có'}")
    log(f"  - Ngày thu hoạch: {list(harvest_dates) if harvest_dates else 'Không có'}")
    log(f"  - Tổ chức liên quan: {list(org_ids) if org_ids else 'None'}")
    log(f"  - Quan hệ làm cha (Parent trong batch_relations): {parent_relations}")
    log(f"  - Quan hệ làm con (Child trong batch_relations): {child_relations}")
    log(f"  - Các trường CÓ BẰNG CHỨNG: {sorted(list(evidence_fields))}")
    log(f"  - Các trường KHÔNG THỂ XÁC MINH: {sorted(list(unverified_fields))}")
    log(f"  - Chi tiết từng sự kiện:")
    for es in event_summaries:
        log(f"      * Event #{es['id']}: type={es['event_type']}, ts={es['timestamp']}, org={es['org_id']}, payload_keys={es['payload_keys']}")

conn.close()
out_file.close()
print("Saved report to scripts/orphans_report.txt")
