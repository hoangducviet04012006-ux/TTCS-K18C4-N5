"""Explicit, confirmed restore within the fixed practice directory only."""
import hashlib
import json
import socket
import sqlite3
from datetime import datetime
from pathlib import Path
from contextlib import closing

ROOT=Path(__file__).resolve().parents[2]
PRACTICE=(ROOT/'.sprint123-trial/practice').resolve()
PRACTICE_PORT=8772


def main():
    target=PRACTICE/'qa_practice.db'
    snapshot=PRACTICE/'snapshot.db'
    for path in (target,snapshot):
        if path.is_symlink() or path.resolve().parent != PRACTICE or not path.is_file():
            raise SystemExit('Tu choi duong dan khong an toan hoac tep bi thieu.')
    if target.stat().st_nlink != 1 or snapshot.stat().st_nlink != 1:
        raise SystemExit('Tu choi hardlink.')
    for path in (target,snapshot):
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            if db.execute("SELECT value FROM sprint_demo_marker WHERE name='practice'").fetchone()!=('TH1-TH2',):
                raise SystemExit('Khong phai database thuc hanh TH1-TH2; tu choi khoi phuc.')
        for suffix in ('-wal','-journal'):
            journal=Path(str(path)+suffix)
            if journal.exists() and journal.stat().st_size:
                raise SystemExit('Database con journal dang hoat dong; hay dung server va thu lai.')
    with socket.socket() as probe:
        try: probe.bind(('127.0.0.1',PRACTICE_PORT))
        except OSError: raise SystemExit('Hay dung server thuc hanh 8772 truoc khi khoi phuc.')
    expected=json.loads((PRACTICE/'snapshot-fingerprint.json').read_text())['sha256']
    if hashlib.sha256(snapshot.read_bytes()).hexdigest()!=expected:
        raise SystemExit('Snapshot da thay doi; tu choi khoi phuc.')
    print('Khoi phuc TH1 va TH2. Moi thao tac thuc hanh hien tai se duoc luu vao backup rieng.')
    print('Chi thay the .sprint123-trial/practice/qa_practice.db; khong dong toi database khac.')
    if input('Nhap KHOI PHUC de xac nhan: ').strip()!='KHOI PHUC':
        print('Da huy.');return
    # Hold an exclusive lock to reject any concurrent writer, even on another port.
    with closing(sqlite3.connect(target,timeout=0)) as db:
        db.execute('BEGIN EXCLUSIVE')
        backup=PRACTICE/('before-restore-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.db')
        backup.write_bytes(db.serialize())
        db.rollback()
    staging=PRACTICE/'restore-pending.db'
    if staging.exists():raise SystemExit('Tep khoi phuc dang ton tai; tu choi ghi de.')
    with closing(sqlite3.connect(snapshot.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(staging)) as dst:
        src.backup(dst)
        assert dst.execute('PRAGMA integrity_check').fetchone()==('ok',)
        assert not dst.execute('PRAGMA foreign_key_check').fetchall()
    staging.replace(target)
    print('Da khoi phuc. Mo start_practice.bat de thuc hanh lai.')


if __name__=='__main__':main()
