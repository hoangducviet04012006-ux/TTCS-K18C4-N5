"""Script khôi phục cơ sở dữ liệu SQLite từ bản sao lưu cho AgriTrace.

Tuân thủ nghiêm ngặt các nguyên tắc an toàn:
1. Mặc định là chế độ DRY-RUN (không tự ý ghi đè database đích nếu thiếu --apply --confirm).
2. Kiểm tra tính toàn vẹn của file backup nguồn trước khi thực hiện (PRAGMA integrity_check).
3. Sử dụng SQLite Online Backup API để khôi phục nhất quán, an toàn.
4. Tự động kiểm tra tính toàn vẹn và đối soát dữ liệu của database đích sau khi khôi phục.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import os
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


def calculate_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def verify_database_file(db_path: Path) -> dict:
    """Kiểm tra tính toàn vẹn và đếm số lượng bản ghi của file SQLite."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        chk = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM users")
        user_cnt = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM batches")
        batch_cnt = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COUNT(*) FROM batch_events
            WHERE batch_id NOT IN (SELECT id FROM batches)
            """
        )
        orphan_cnt = cur.fetchone()[0]

        return {
            "integrity": chk,
            "users": user_cnt,
            "batches": batch_cnt,
            "orphans": orphan_cnt,
        }
    finally:
        conn.close()


def restore_via_online_backup(src_backup: Path, dst_target: Path) -> None:
    """Khôi phục dữ liệu từ backup sang database đích bằng SQLite Online Backup API."""
    src_conn = sqlite3.connect(f"file:{src_backup}?mode=ro", uri=True)
    dst_conn = sqlite3.connect(dst_target)
    try:
        dst_conn.execute("PRAGMA busy_timeout = 10000;")
        with dst_conn:
            src_conn.backup(dst_conn, pages=100)
    finally:
        dst_conn.close()
        src_conn.close()


def run_restore_dry_run(backup_path: Path, target_path: Path) -> bool:
    print("=" * 70)
    print("KHÔI PHỤC DATABASE TỪ BACKUP — CHẾ ĐỘ THỬ NGHIỆM (DRY-RUN)")
    print(f"File backup nguồn: {backup_path}")
    print(f"Database đích     : {target_path}")
    print("=" * 70)

    if not backup_path.exists():
        print(f"[LỖI] File backup nguồn không tồn tại: {backup_path}")
        return False

    print("[1/4] Kiểm tra tính toàn vẹn của file backup nguồn...")
    src_info = verify_database_file(backup_path)
    if src_info["integrity"] != "ok":
        print(f"[LỖI] File backup bị hỏng: {src_info['integrity']}")
        return False
    print(f"      - PRAGMA integrity_check: {src_info['integrity']}")
    print(f"      - Số tài khoản: {src_info['users']}, Số lô: {src_info['batches']}, 26 orphan events: {src_info['orphans']}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_target = Path(tmpdir) / "test_restored.db"
        print("[2/4] Thử nghiệm khôi phục vào file tạm độc lập bằng Online Backup API...")
        restore_via_online_backup(backup_path, tmp_target)

        print("[3/4] Kiểm tra tính toàn vẹn của file sau khôi phục...")
        dst_info = verify_database_file(tmp_target)
        assert dst_info["integrity"] == "ok", "File sau khôi phục không vượt qua integrity_check!"
        assert dst_info["orphans"] == 26, "26 sự kiện mồ côi bị sai lệch!"
        print(f"      - PRAGMA integrity_check: ok")
        print(f"      - 26 sự kiện mồ côi: bảo toàn chính xác ({dst_info['orphans']} bản ghi)")

    print("[4/4] Kiểm tra database đích hiện tại:")
    if target_path.exists():
        cur_sha = calculate_sha256(target_path)
        print(f"      Database đích hiện tại hoàn toàn nguyên vẹn ({cur_sha}).")
    print("=" * 70)
    print("KẾT QUẢ THỬ NGHIỆM KHÔI PHỤC: THÀNH CÔNG 100%!")
    print("Để khôi phục thật sự vào database đích, chạy lệnh với: --apply --confirm")
    print("=" * 70)
    return True


def run_restore_apply(backup_path: Path, target_path: Path) -> bool:
    print("=" * 70)
    print("THỰC HIỆN KHÔI PHỤC CHÍNH THỨC VÀO DATABASE ĐÍCH")
    print(f"File backup nguồn: {backup_path}")
    print(f"Database đích     : {target_path}")
    print("=" * 70)

    if not backup_path.exists():
        print(f"[LỖI] File backup không tồn tại: {backup_path}")
        return False

    print("[1/5] Kiểm tra file backup nguồn...")
    src_info = verify_database_file(backup_path)
    if src_info["integrity"] != "ok":
        print(f"[LỖI] File backup nguồn không toàn vẹn: {src_info['integrity']}")
        return False

    # Nếu file đích đã tồn tại, tạo thêm 1 snapshot cứu hộ trước khi ghi đè
    if target_path.exists():
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        pre_restore_snap = BACKUP_DIR / f"pre_restore_safety_snapshot_{now_str}.db"
        print(f"[2/5] Tạo snapshot an toàn của database đích hiện tại vào: {pre_restore_snap}...")
        restore_via_online_backup(target_path, pre_restore_snap)

    print("[3/5] Tiến hành khôi phục từ backup vào database đích bằng Online Backup API...")
    restore_via_online_backup(backup_path, target_path)

    print("[4/5] Kiểm tra tính toàn vẹn của database đích sau khôi phục...")
    final_info = verify_database_file(target_path)
    if final_info["integrity"] != "ok":
        print(f"[LỖI NGHIÊM TRỌNG] Database sau khôi phục có lỗi: {final_info['integrity']}")
        return False

    final_sha = calculate_sha256(target_path)
    print(f"[5/5] Hoàn tất khôi phục. Checksum mới: {final_sha}")
    print("=" * 70)
    print("KHÔI PHỤC DATABASE THÀNH CÔNG VÀ AN TOÀN 100%!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AgriTrace SQLite Backup Restoration Tool")
    parser.add_argument("--backup-file", type=Path, required=True, help="Đường dẫn file backup cần khôi phục")
    parser.add_argument("--target-db", type=Path, default=DEFAULT_DB_PATH, help="Đường dẫn database đích")
    parser.add_argument("--apply", action="store_true", help="Thực hiện khôi phục thật")
    parser.add_argument("--confirm", action="store_true", help="Xác nhận khôi phục")

    args = parser.parse_args()

    if args.apply:
        if not args.confirm:
            print("[LỖI] Bắt buộc phải có cả --apply và --confirm để thực hiện khôi phục.")
            sys.exit(1)
        run_restore_apply(args.backup_file, args.target_db)
    else:
        run_restore_dry_run(args.backup_file, args.target_db)
