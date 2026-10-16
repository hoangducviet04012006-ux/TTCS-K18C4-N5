"""Restore safety checks run only against temporary miniature practice databases."""
import hashlib
import json
import sqlite3
import socket
from contextlib import closing

import pytest
from scripts import restore_practice


@pytest.fixture
def practice(tmp_path,monkeypatch):
    monkeypatch.setattr(restore_practice,'PRACTICE',tmp_path)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0))
        monkeypatch.setattr(restore_practice,'PRACTICE_PORT',probe.getsockname()[1])
    for name,value in [('qa_practice.db','changed'),('snapshot.db','clean')]:
        with closing(sqlite3.connect(tmp_path/name)) as db:
            db.execute('CREATE TABLE sprint_demo_marker (name TEXT PRIMARY KEY,value TEXT)')
            db.execute("INSERT INTO sprint_demo_marker VALUES ('practice','TH1-TH2')")
            db.execute('CREATE TABLE evidence (value TEXT)')
            db.execute('INSERT INTO evidence VALUES (?)',(value,))
            db.commit()
    (tmp_path/'snapshot-fingerprint.json').write_text(json.dumps({'sha256':hashlib.sha256((tmp_path/'snapshot.db').read_bytes()).hexdigest()}))
    return tmp_path


def test_cancel_never_changes_practice(practice,monkeypatch):
    before=(practice/'qa_practice.db').read_bytes()
    monkeypatch.setattr('builtins.input',lambda _: 'HUY')
    restore_practice.main()
    assert (practice/'qa_practice.db').read_bytes()==before
    assert not list(practice.glob('before-restore-*'))


def test_confirm_restores_and_keeps_original_backup(practice,monkeypatch):
    before=(practice/'qa_practice.db').read_bytes()
    monkeypatch.setattr('builtins.input',lambda _: 'KHOI PHUC')
    restore_practice.main()
    with sqlite3.connect(practice/'qa_practice.db') as db:
        assert db.execute('SELECT value FROM evidence').fetchone()==('clean',)
    backup=next(practice.glob('before-restore-*.db'))
    assert backup.read_bytes()==before


def test_changed_snapshot_is_refused(practice,monkeypatch):
    with sqlite3.connect(practice/'snapshot.db') as db:db.execute("UPDATE evidence SET value='tampered'")
    monkeypatch.setattr('builtins.input',lambda _: pytest.fail('Must refuse before confirmation'))
    before=(practice/'qa_practice.db').read_bytes()
    with pytest.raises(SystemExit,match='Snapshot da thay doi'):restore_practice.main()
    assert (practice/'qa_practice.db').read_bytes()==before


def test_running_server_is_refused(practice,monkeypatch):
    monkeypatch.setattr('builtins.input',lambda _: pytest.fail('Must refuse before confirmation'))
    with socket.socket() as listener:
        try:listener.bind(('127.0.0.1',restore_practice.PRACTICE_PORT))
        except OSError:pytest.skip('Practice server is already running')
        listener.listen()
        with pytest.raises(SystemExit,match='dung server'):restore_practice.main()


def test_wrong_database_marker_is_refused(practice,monkeypatch):
    with sqlite3.connect(practice/'qa_practice.db') as db:db.execute("UPDATE sprint_demo_marker SET value='outside'")
    monkeypatch.setattr('builtins.input',lambda _: pytest.fail('Must refuse before confirmation'))
    with pytest.raises(SystemExit,match='Khong phai database'):restore_practice.main()
