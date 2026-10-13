"""Kịch bản Migration an toàn cho Giai đoạn 2: Tạo bảng `user_sessions`.

CHẠY TRÊN BẢN SAO THỬ NGHIỆM ĐỂ KIỂM CHỨNG TÍNH TOÀN VẸN.
TUYỆT ĐỐI KHÔNG TỰ ĐỘNG CHẠY TRÊN DATABASE GỐC NẾU CHƯA CÓ XÁC NHẬN TỪ NGƯỜI DÙNG.
"""

import os
import shutil
import sqlite3
import sys
import tempfile

BACKUP_DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backups", "ttcs_backup_stage2_20261010.db"))

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS user_sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    is_revoked BOOLEAN NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at);
"""

ROLLBACK_SQL = """
DROP INDEX IF EXISTS idx_user_sessions_expires_at;
DROP INDEX IF EXISTS idx_user_sessions_user_id;
DROP TABLE IF EXISTS user_sessions;
"""


def test_migration_on_backup() -> bool:
    """Thử nghiệm migration trên bản sao tạm thời."""
    if not os.path.exists(BACKUP_DB):
        print(f"[LỖI] Không tìm thấy file backup tại: {BACKUP_DB}")
        return False

    tmp_dir = tempfile.mkdtemp(prefix="ttcs_stage2_test_")
    tmp_db = os.path.join(tmp_dir, "test_migration.db")
    shutil.copy2(BACKUP_DB, tmp_db)

    try:
        conn = sqlite3.connect(tmp_db)
        cursor = conn.cursor()

        # 1. Chạy migration
        cursor.executescript(MIGRATION_SQL)
        conn.commit()

        # 2. Kiểm tra bảng đã tạo
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_sessions'")
        table = cursor.fetchone()
        assert table is not None, "Bảng user_sessions chưa được tạo"

        # 3. Thử chèn bản ghi mẫu
        cursor.execute(
            """
            INSERT INTO user_sessions (session_id, user_id, csrf_token, created_at, expires_at, is_revoked)
            VALUES ('test_token_123', 1, 'csrf_abc_456', '2026-10-10 12:00:00', '2026-10-11 12:00:00', 0)
            """
        )
        conn.commit()

        # 4. Kiểm tra truy vấn
        cursor.execute("SELECT user_id, csrf_token FROM user_sessions WHERE session_id='test_token_123'")
        row = cursor.fetchone()
        assert row == (1, 'csrf_abc_456'), f"Dữ liệu session không khớp: {row}"

        # 5. Thử rollback
        cursor.executescript(ROLLBACK_SQL)
        conn.commit()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_sessions'")
        assert cursor.fetchone() is None, "Rollback thất bại: bảng user_sessions vẫn tồn tại"

        conn.close()
        print("[SUCCESS] Da kiem chung migration va rollback bang user_sessions tren ban sao thu nghiem!")
        return True
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    success = test_migration_on_backup()
    sys.exit(0 if success else 1)
