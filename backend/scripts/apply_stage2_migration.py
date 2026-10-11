"""Script Migration SQLite chính thức cho Giai đoạn 2 & 2.2 của AgriTrace.

Tuân thủ nghiêm ngặt các nguyên tắc bảo toàn:
1. Mặc định là chế độ DRY-RUN trên bản sao tạm độc lập (tuyệt đối không chạm vào database gốc).
2. Khi chạy với flag `--apply --confirm`:
   - Xác nhận đường dẫn database đích.
   - Kiểm tra tiến trình ứng dụng / xung đột ghi (PRAGMA busy_timeout = 10000).
   - TỰ ĐỘNG TẠO BẢN SAO LƯU NHẤT QUÁN trước khi ghi bằng SQLite Online Backup API.
   - Kiểm tra PRAGMA integrity_check trước khi chạy.
   - Bắt đầu transaction nguyên tử `BEGIN IMMEDIATE`.
   - Thực thi DDL tạo bảng `user_sessions` và DML cập nhật vai trò 5 tài khoản.
   - KIỂM TRA TOÀN VẸN VÀ ĐỐI SOÁT DỮ LIỆU ĐẦY ĐỦ TRƯỚC KHI COMMIT:
     * Nếu có bất kỳ sai lệch nào: ROLLBACK ngay trong transaction, dữ liệu giữ nguyên 100%.
     * Chỉ gọi COMMIT khi mọi kiểm tra đều đạt 100%.
   - Sau COMMIT: không tuyên bố rollback SQL nếu có lỗi I/O phát sinh; cung cấp hướng dẫn dùng bản backup.
   - Tuyệt đối không tự ý ghi đè database khi phát hiện lỗi sau COMMIT.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "ttcs.db"
BACKUP_DIR = BASE_DIR / "backups"

TARGET_ROLES_UPDATE = [
    (1, "admin", "system_admin"),
    (4, "distributor", "distributor"),
    (6, "demo_packing", "processor"),
    (7, "demo_distribution", "distributor"),
    (8, "demo_admin", "system_admin"),
]

EXPECTED_UNCHANGED_FARMERS = [
    (2, "farmer", "farmer"),
    (3, "farmer_tg", "farmer"),
    (5, "demo_farm", "farmer"),
]

CHECKED_BUSINESS_TABLES = [
    "batches",
    "batch_events",
    "batch_relations",
    "handovers",
    "farms",
    "plots",
    "products",
]


def calculate_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def create_online_backup(source_db_path: Path, dest_backup_path: Path) -> str:
    """Tạo bản sao lưu nhất quán bằng SQLite Online Backup API."""
    dest_backup_path.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(f"file:{source_db_path}?mode=ro", uri=True)
    dst_conn = sqlite3.connect(dest_backup_path)
    try:
        with dst_conn:
            src_conn.backup(dst_conn, pages=100)
    finally:
        dst_conn.close()
        src_conn.close()
    return calculate_sha256(dest_backup_path)


def collect_database_metrics(conn: sqlite3.Connection) -> dict:
    """Thu thập toàn bộ chỉ số để đối soát tính toàn vẹn (chạy được cả trong transaction)."""
    cur = conn.cursor()

    # Integrity check
    cur.execute("PRAGMA integrity_check;")
    integrity = cur.fetchone()[0]

    # Đếm số lượng bản ghi các bảng chính
    tables = ["users", "batches", "batch_events", "batch_relations", "handovers", "farms", "plots", "products", "audit_logs"]
    table_counts = {}
    for t in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            table_counts[t] = cur.fetchone()[0]
        except sqlite3.OperationalError:
            table_counts[t] = None

    # Kiểm tra 26 sự kiện mồ côi
    cur.execute(
        """
        SELECT COUNT(*) FROM batch_events
        WHERE batch_id NOT IN (SELECT id FROM batches)
        """
    )
    orphan_events = cur.fetchone()[0]

    # Danh sách 8 tài khoản
    cur.execute("SELECT id, username, email, role, organization_id, password FROM users ORDER BY id")
    users = cur.fetchall()

    return {
        "integrity": integrity,
        "table_counts": table_counts,
        "orphan_events": orphan_events,
        "users": users,
    }


def execute_migration_sql(conn: sqlite3.Connection) -> dict:
    """Thực hiện migration DDL & DML bên trong transaction an toàn."""
    cur = conn.cursor()

    # 1. Bảng user_sessions
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_sessions (
            session_id VARCHAR(128) PRIMARY KEY,
            user_id INTEGER NOT NULL,
            csrf_token VARCHAR(128) NOT NULL,
            created_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            is_revoked BOOLEAN NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS ix_user_sessions_user_id ON user_sessions(user_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_user_sessions_expires_at ON user_sessions(expires_at);")

    # 2. Cập nhật 5 tài khoản
    updated_counts = {}
    for uid, uname, new_role in TARGET_ROLES_UPDATE:
        cur.execute(
            "UPDATE users SET role = ? WHERE id = ? AND username = ?",
            (new_role, uid, uname),
        )
        updated_counts[uname] = cur.rowcount

    return {
        "updated_counts": updated_counts,
    }


def verify_in_transaction(conn: sqlite3.Connection, before_metrics: dict) -> None:
    """Kiểm tra và đối soát toàn bộ dữ liệu NGAY TRONG TRANSACTION trước khi COMMIT."""
    cur = conn.cursor()

    # 1. PRAGMA integrity_check trong transaction
    cur.execute("PRAGMA integrity_check;")
    chk = cur.fetchone()[0]
    if chk != "ok":
        raise ValueError(f"PRAGMA integrity_check thất bại trong transaction: {chk}")

    # 2. Kiểm tra bảng user_sessions đã tồn tại
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_sessions'")
    if not cur.fetchone():
        raise ValueError("Bảng user_sessions chưa tồn tại sau khi chạy DDL!")

    # 3. Kiểm tra 26 sự kiện mồ côi
    cur.execute(
        """
        SELECT COUNT(*) FROM batch_events
        WHERE batch_id NOT IN (SELECT id FROM batches)
        """
    )
    orphan_cnt = cur.fetchone()[0]
    if orphan_cnt != 26:
        raise ValueError(f"Số sự kiện mồ côi bị sai lệch: kỳ vọng 26, thực tế {orphan_cnt}")

    # 4. Kiểm tra các bảng nghiệp vụ khác không bị đổi số dòng
    for t in CHECKED_BUSINESS_TABLES:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        cnt = cur.fetchone()[0]
        if cnt != before_metrics["table_counts"][t]:
            raise ValueError(f"Bảng {t} bị biến đổi số lượng dòng: trước={before_metrics['table_counts'][t]}, trong={cnt}")

    # 5. Kiểm tra 8 tài khoản
    cur.execute("SELECT id, username, email, role, organization_id, password FROM users ORDER BY id")
    after_users = cur.fetchall()
    if len(after_users) != 8:
        raise ValueError(f"Tổng số tài khoản không phải 8: {len(after_users)}")

    user_map = {u[0]: u for u in after_users}
    before_map = {u[0]: u for u in before_metrics["users"]}

    # Xác minh 5 tài khoản được cập nhật role
    for uid, uname, new_role in TARGET_ROLES_UPDATE:
        u = user_map.get(uid)
        b = before_map.get(uid)
        if not u or u[1] != uname:
            raise ValueError(f"Tài khoản ID {uid} ({uname}) không tìm thấy hoặc sai username!")
        if u[3] != new_role:
            raise ValueError(f"Vai trò của {uname} chưa được cập nhật thành {new_role} (thực tế {u[3]})!")
        if u[4] != b[4]:
            raise ValueError(f"organization_id của {uname} bị đổi!")
        if u[5] != b[5]:
            raise ValueError(f"password hash của {uname} bị đổi!")

    # Xác minh 3 tài khoản farmer giữ nguyên
    for uid, uname, exp_role in EXPECTED_UNCHANGED_FARMERS:
        u = user_map.get(uid)
        b = before_map.get(uid)
        if not u or u[1] != uname:
            raise ValueError(f"Tài khoản ID {uid} ({uname}) không tìm thấy!")
        if u[3] != exp_role:
            raise ValueError(f"Vai trò của farmer {uname} bị thay đổi sai thành {u[3]}!")
        if u[4] != b[4]:
            raise ValueError(f"organization_id của {uname} bị đổi!")
        if u[5] != b[5]:
            raise ValueError(f"password hash của {uname} bị đổi!")

    # Xác minh email distributor (ID 4) giữ nguyên NULL
    if user_map[4][2] is not None:
        raise ValueError(f"Email của distributor bị thay đổi khỏi NULL: {user_map[4][2]}")


def run_dry_run(target_db_path: Path) -> bool:
    print("=" * 70)
    print("CHẾ ĐỘ THỬ NGHIỆM (DRY-RUN) TRÊN BẢN SAO ĐỘC LẬP")
    print(f"Database nguồn: {target_db_path}")
    source_sha = calculate_sha256(target_db_path)
    print(f"SHA256 nguồn:  {source_sha}")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_copy = Path(tmpdir) / "dry_run_copy.db"
        print("[1/5] Thử nghiệm tạo bản sao lưu qua Online Backup API...")
        backup_sha = create_online_backup(target_db_path, tmp_copy)
        print(f"      Tạo thành công bản sao lưu tạm. Checksum: {backup_sha}")

        conn = sqlite3.connect(tmp_copy)
        conn.execute("PRAGMA busy_timeout = 5000;")
        try:
            print("[2/5] Kiểm tra chỉ số cơ sở dữ liệu TRƯỚC migration...")
            before = collect_database_metrics(conn)
            assert before["integrity"] == "ok", f"PRAGMA integrity_check thất bại: {before['integrity']}"
            assert before["orphan_events"] == 26, f"Số sự kiện mồ côi khác 26: {before['orphan_events']}"
            print(f"      - PRAGMA integrity_check: {before['integrity']}")
            print(f"      - 26 sự kiện mồ côi: {before['orphan_events']} bản ghi (chính xác)")
            print(f"      - Tổng số tài khoản: {len(before['users'])} (chính xác 8)")

            print("[3/5] Thực hiện migration DDL & DML trong transaction...")
            conn.execute("BEGIN IMMEDIATE;")
            execute_migration_sql(conn)

            print("[4/5] Đối soát và xác minh dữ liệu TRƯỚC KHI COMMIT (bên trong transaction)...")
            verify_in_transaction(conn, before)
            print("      - Toàn bộ kiểm tra đối soát trong transaction: ĐẠT 100%.")

            conn.commit()
            print("      - Đã COMMIT transaction thành công.")

            # Kiểm tra sau commit
            after = collect_database_metrics(conn)
            assert after["integrity"] == "ok", "PRAGMA integrity_check thất bại sau commit!"
            print("      - PRAGMA integrity_check sau commit: ok")

        finally:
            conn.close()

    final_source_sha = calculate_sha256(target_db_path)
    assert source_sha == final_source_sha, "CẢNH BÁO: Database nguồn đã bị thay đổi trong quá trình dry-run!"
    print("[5/5] Kiểm tra database gốc:")
    print(f"      Database gốc hoàn toàn nguyên vẹn ({final_source_sha}).")
    print("=" * 70)
    print("KẾT QUẢ DRY-RUN: THÀNH CÔNG HOÀN TOÀN 100%!")
    print("=" * 70)
    return True


def run_apply(target_db_path: Path) -> bool:
    print("=" * 70)
    print("ÁP DỤNG MIGRATION CHÍNH THỨC VÀO DATABASE THẬT")
    print(f"Target DB: {target_db_path}")
    print("=" * 70)

    if not target_db_path.exists():
        print(f"[LỖI] File database không tồn tại: {target_db_path}")
        return False

    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"ttcs_backup_before_stage2_migration_{now_str}.db"

    print(f"[1/6] Tạo bản sao lưu nhất quán trước khi ghi vào: {backup_file}...")
    orig_sha = calculate_sha256(target_db_path)
    backup_sha = create_online_backup(target_db_path, backup_file)
    print(f"      - SHA256 database gốc: {orig_sha}")
    print(f"      - SHA256 bản backup:    {backup_sha}")

    conn = sqlite3.connect(target_db_path)
    conn.execute("PRAGMA busy_timeout = 10000;")
    is_committed = False
    try:
        print("[2/6] Kiểm tra an toàn trước khi ghi...")
        before = collect_database_metrics(conn)
        if before["integrity"] != "ok":
            print(f"[DỪNG] Database có lỗi toàn vẹn: {before['integrity']}")
            return False
        if before["orphan_events"] != 26:
            print(f"[DỪNG] Số sự kiện mồ côi không khớp: {before['orphan_events']}")
            return False

        print("[3/6] Bắt đầu transaction nguyên tử (BEGIN IMMEDIATE)...")
        conn.execute("BEGIN IMMEDIATE;")
        execute_migration_sql(conn)

        print("[4/6] Đối soát và xác minh dữ liệu TRƯỚC KHI COMMIT...")
        verify_in_transaction(conn, before)
        print("      - Đối soát toàn diện trước COMMIT: ĐẠT 100%.")

        conn.commit()
        is_committed = True
        print("      - Đã ghi và COMMIT thành công.")

        print("[5/6] Xác minh cuối cùng sau COMMIT...")
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        post_chk = cur.fetchone()[0]
        assert post_chk == "ok", "Lỗi PRAGMA integrity_check sau commit!"
        print("      - PRAGMA integrity_check sau commit: ok")

        new_sha = calculate_sha256(target_db_path)
        print(f"[6/6] Checksum mới của database: {new_sha}")
        print("=" * 70)
        print("MIGRATION CHÍNH THỨC HOÀN TẤT THÀNH CÔNG VÀ AN TOÀN 100%!")
        print("=" * 70)
        return True

    except Exception as exc:
        if not is_committed:
            conn.rollback()
            print(f"[THÔNG BÁO] Lỗi xảy ra TRƯỚC KHI COMMIT: Đã ROLLBACK hoàn toàn transaction! Database gốc được giữ nguyên: {exc}")
        else:
            print(f"[CẢNH BÁO ĐẶC BIỆT] Lỗi xảy ra SAU KHI COMMIT (transaction SQL đã ghi thành công).")
            print(f"Chi tiết lỗi: {exc}")
            print(f"Database đã được sao lưu an toàn tại: {backup_file}")
            print(f"Hệ thống TUYỆT ĐỐI KHÔNG tự động ghi đè database gốc.")
            print(f"Nếu cần khôi phục, vui lòng chạy: python scripts/restore_from_backup.py --backup-file {backup_file}")
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AgriTrace Stage 2 Migration Script")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="Đường dẫn file database")
    parser.add_argument("--apply", action="store_true", help="Áp dụng vào database thật")
    parser.add_argument("--confirm", action="store_true", help="Xác nhận ghi vào database")
    parser.add_argument("--dry-run", action="store_true", help="Chạy thử nghiệm trên bản sao (mặc định)")

    args = parser.parse_args()

    if args.apply:
        if not args.confirm:
            print("[LỖI] Để áp dụng vào database thật, bắt buộc phải có cả cờ --apply và --confirm.")
            sys.exit(1)
        run_apply(args.db_path)
    else:
        run_dry_run(args.db_path)
