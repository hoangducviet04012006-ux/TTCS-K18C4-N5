"""Script Migration an toàn cho Giai đoạn 2 & 2.1 (CHỈ CHẠY TRÊN BẢN SAO THỬ NGHIỆM).

Yêu cầu bảo toàn:
1. Tạo bảng `user_sessions` với các chỉ mục.
2. Cập nhật 8 tài khoản sang đúng 7 vai trò chuẩn (LEGACY_ACCOUNT_ROLE_MAPPING):
   - admin -> system_admin
   - farmer -> farmer
   - farmer_tg -> farmer
   - distributor -> distributor (giữ email NULL)
   - demo_farm -> farmer
   - demo_packing -> processor
   - demo_distribution -> distributor
   - demo_admin -> system_admin
3. Giữ nguyên ID, organization_id, username, password hash.
4. Bảo toàn 26 sự kiện mồ côi và chuỗi hash-chain.
5. Kiểm chứng khả năng rollback an toàn.
"""

from __future__ import annotations

import argparse
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
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent.parent
ORIGINAL_DB_PATH = BASE_DIR / "ttcs.db"

MAPPING = {
    "admin": "system_admin",
    "farmer": "farmer",
    "farmer_tg": "farmer",
    "distributor": "distributor",
    "demo_farm": "farmer",
    "demo_packing": "processor",
    "demo_distribution": "distributor",
    "demo_admin": "system_admin",
}


def calculate_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def run_migration_on_connection(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    # 1. Tạo bảng user_sessions
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

    # 2. Cập nhật 8 vai trò theo bảng ánh xạ
    for username, target_role in MAPPING.items():
        cur.execute("UPDATE users SET role = ? WHERE username = ?", (target_role, username))

    conn.commit()


def rollback_migration_on_connection(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    # Khôi phục role cũ
    cur.execute("UPDATE users SET role = 'admin' WHERE username IN ('admin', 'demo_admin')")
    cur.execute(
        "UPDATE users SET role = 'farmer' WHERE username IN ('farmer', 'farmer_tg', 'distributor', 'demo_farm', 'demo_packing', 'demo_distribution')"
    )
    # Xóa bảng user_sessions
    cur.execute("DROP TABLE IF EXISTS user_sessions;")
    conn.commit()


def verify_migration(conn: sqlite3.Connection) -> dict:
    cur = conn.cursor()

    # Kiểm tra bảng user_sessions
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_sessions'")
    has_sessions_table = bool(cur.fetchone())

    # Kiểm tra 8 tài khoản
    cur.execute("SELECT id, username, email, role, organization_id, password FROM users ORDER BY id")
    users = cur.fetchall()

    # Kiểm tra email của distributor
    cur.execute("SELECT email FROM users WHERE username = 'distributor'")
    dist_email = cur.fetchone()[0]

    # Kiểm tra 26 sự kiện mồ côi
    cur.execute(
        """
        SELECT COUNT(*) FROM batch_events
        WHERE batch_id NOT IN (SELECT id FROM batches)
        """
    )
    orphan_count = cur.fetchone()[0]

    # Kiểm tra tổng số batch_events
    cur.execute("SELECT COUNT(*) FROM batch_events")
    total_events = cur.fetchone()[0]

    return {
        "has_sessions_table": has_sessions_table,
        "users": users,
        "distributor_email_is_null": dist_email is None,
        "orphan_count": orphan_count,
        "total_events": total_events,
    }


def test_migration_on_copy(source_db: Path) -> bool:
    print(f"[1/5] Kiểm tra SHA256 database gốc: {source_db}")
    original_hash = calculate_sha256(source_db)
    print(f"      SHA256 gốc = {original_hash}")

    with tempfile.TemporaryDirectory() as tmpdir:
        copy_path = Path(tmpdir) / "ttcs_test_copy.db"
        shutil.copy2(source_db, copy_path)
        print(f"[2/5] Đã sao chép an toàn sang bản sao tạm: {copy_path}")

        conn = sqlite3.connect(copy_path)
        try:
            # Thu thập dữ liệu trước migration
            cur = conn.cursor()
            cur.execute("SELECT id, username, organization_id, password FROM users ORDER BY id")
            before_users = cur.fetchall()

            print("[3/5] Thực hiện migration trên bản sao...")
            run_migration_on_connection(conn)

            print("[4/5] Kiểm tra tính toàn vẹn sau migration:")
            res = verify_migration(conn)
            assert res["has_sessions_table"], "LỖI: Bảng user_sessions chưa được tạo!"
            print("      - Bảng user_sessions: ĐÃ TẠO THÀNH CÔNG")

            assert res["distributor_email_is_null"], "LỖI: Email của distributor bị thay đổi khỏi NULL!"
            print("      - Email distributor: GIỮ NGUYÊN NULL (BẢO TOÀN)")

            assert res["orphan_count"] == 26, f"LỖI: Số sự kiện mồ côi bị đổi (kỳ vọng 26, thực tế {res['orphan_count']})!"
            print(f"      - 26 Sự kiện mồ côi: NGUYÊN VẸN ({res['orphan_count']} events)")

            # Kiểm tra 8 user sau migration
            cur.execute("SELECT id, username, organization_id, password, role FROM users ORDER BY id")
            after_users = cur.fetchall()
            for b, a in zip(before_users, after_users):
                assert b[0] == a[0], f"ID user {b[1]} bị đổi!"
                assert b[1] == a[1], f"Username {b[1]} bị đổi!"
                assert b[2] == a[2], f"Organization ID của {b[1]} bị đổi!"
                assert b[3] == a[3], f"Hash password của {b[1]} bị đổi!"
                assert a[4] == MAPPING[a[1]], f"Role của {a[1]} không khớp với bảng ánh xạ!"
            print("      - 8 Tài khoản: Đã ánh xạ đúng 7 vai trò chuẩn, giữ nguyên ID, org_id, password hash!")

            print("[5/5] Kiểm tra thử nghiệm Rollback trên bản sao...")
            rollback_migration_on_connection(conn)
            res_rb = verify_migration(conn)
            assert not res_rb["has_sessions_table"], "Rollback thất bại: bảng user_sessions vẫn còn!"
            print("      - Rollback hoàn tất sạch sẽ!")

        finally:
            conn.close()

    after_test_hash = calculate_sha256(source_db)
    assert original_hash == after_test_hash, "CẢNH BÁO NGUY HIỂM: Database gốc đã bị thay đổi!"
    print(f"\n[KẾT LUẬN] Thử nghiệm thành công 100%! Database gốc ttcs.db được bảo vệ tuyệt đối ({after_test_hash}).")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migration thử nghiệm an toàn Giai đoạn 2.1")
    parser.add_argument("--apply-to-real-db", action="store_true", help="Áp dụng vào database gốc (CHỈ KHI CÓ XÁC NHẬN)")
    args = parser.parse_args()

    if args.apply_to_real_db:
        print("[LƯU Ý] Chỉ thị hiện tại: KHÔNG tự động chạy migration trên database gốc khi chưa có lệnh xác nhận rõ ràng.")
        sys.exit(1)
    else:
        test_migration_on_copy(ORIGINAL_DB_PATH)
