"""Design checks only: no Recall endpoints, production migration or real database writes."""
import json
import sqlite3
from pathlib import Path
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.database import Base
from app.models import Batch, BatchEvent, User
from app.hash_chain import verify_batch_chain
from app.services.traceability import trace_forward, trace_backwards
from app.services.rbac import can_recall_batch
from scripts.migrate_stage3b_recall import run_migration_on_connection, trial, snapshot_state
from scripts.seed_recall_s39 import seed_recall_s39


@pytest.fixture
def trial_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    for table in ("batches", "users", "organizations", "batch_events"):
        conn.execute(f"CREATE TABLE {table}(id INTEGER PRIMARY KEY)")
        conn.execute(f"INSERT INTO {table} VALUES(1)")
    conn.commit()
    yield conn
    conn.close()


def migrated(conn):
    run_migration_on_connection(conn)
    conn.commit()


def recall(conn, code="R1", root=1, reason="Valid reason twenty characters", status="OPEN", completed=None):
    conn.execute("INSERT INTO recalls(recall_code,root_batch_id,reason,created_by_user_id,status,completed_at) VALUES(?,?,?,?,?,?)", (code, root, reason, 1, status, completed))


def test_schema_rerun_preserves_base(trial_conn):
    before = snapshot_state(trial_conn)
    migrated(trial_conn); migrated(trial_conn)
    after = snapshot_state(trial_conn)
    assert all(after[t] == v for t,v in before.items() if t != "schema_sha256")
    assert trial_conn.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("kwargs", [{"root":999}, {"reason":"short"}, {"status":"INVALID"}, {"status":"COMPLETED"}, {"completed":"2026-10-10"}])
def test_invalid_recall_constraints(trial_conn, kwargs):
    migrated(trial_conn)
    with pytest.raises(sqlite3.IntegrityError): recall(trial_conn, **kwargs)


@pytest.mark.parametrize("completed", [False, True])
def test_one_recall_per_root_lifetime(trial_conn, completed):
    migrated(trial_conn)
    recall(trial_conn, status="COMPLETED" if completed else "OPEN", completed="2026-10-10" if completed else None)
    with pytest.raises(sqlite3.IntegrityError): recall(trial_conn, code="R2")


def test_ack_constraints_and_restrict(trial_conn):
    migrated(trial_conn); recall(trial_conn)
    trial_conn.execute("INSERT INTO recall_acknowledgments(recall_id,organization_id) VALUES(1,1)")
    for sql in ["INSERT INTO recall_acknowledgments(recall_id,organization_id) VALUES(1,1)", "UPDATE recall_acknowledgments SET status='ACKNOWLEDGED'", "DELETE FROM organizations WHERE id=1", "DELETE FROM recalls WHERE id=1"]:
        with pytest.raises(sqlite3.IntegrityError): trial_conn.execute(sql)
    trial_conn.execute("UPDATE recall_acknowledgments SET status='ACKNOWLEDGED', acknowledged_by_user_id=1, acknowledged_at='2026-10-10'")


def test_idempotency_is_scoped(trial_conn):
    migrated(trial_conn)
    trial_conn.execute("INSERT INTO users VALUES(2)")
    sql="INSERT INTO idempotency_records(key,user_id,endpoint,request_hash,response_code,response_body) VALUES('same',?,?,?,201,'{}')"
    for user, endpoint in [(1,'create'),(2,'create'),(1,'ack')]: trial_conn.execute(sql,(user,endpoint,'a'*64))
    with pytest.raises(sqlite3.IntegrityError): trial_conn.execute(sql,(1,'create','a'*64))


def test_ddl_rolls_back_on_failure(trial_conn):
    trial_conn.execute("CREATE TABLE recall_acknowledgments(id INTEGER PRIMARY KEY)")
    before=snapshot_state(trial_conn)
    with pytest.raises(sqlite3.OperationalError): run_migration_on_connection(trial_conn)
    trial_conn.rollback()
    assert snapshot_state(trial_conn)==before


def test_files_are_never_migrated(tmp_path):
    path=tmp_path/'source.db'
    conn=sqlite3.connect(path)
    with pytest.raises(ValueError): run_migration_on_connection(conn)
    conn.close()
    assert path.stat().st_size==0


def test_trial_reads_source_without_changes(trial_conn, tmp_path):
    path=tmp_path/'source.db'
    with sqlite3.connect(path) as disk: trial_conn.backup(disk)
    before=path.read_bytes()
    result=trial(path)
    assert result['source_unchanged'] and result['existing_tables_preserved']
    assert path.read_bytes()==before


def test_missing_schema_refused():
    with sqlite3.connect(':memory:') as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        with pytest.raises(ValueError): run_migration_on_connection(conn)


def test_foreign_keys_must_be_enabled(trial_conn):
    trial_conn.execute('PRAGMA foreign_keys=OFF')
    with pytest.raises(ValueError): run_migration_on_connection(trial_conn)


def test_s39_independent_oracle():
    oracle=json.loads((Path(__file__).parent/'fixtures/recall_s39_ground_truth.json').read_text(encoding='utf-8'))
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            ids=seed_recall_s39(db)
            result=trace_forward(db, ids['S39-ROOT-A'], use_cache=False)
            assert result['total_descendants']==oracle['expected_total_descendants']
            assert {str(k): sorted(n['code'] for n in v) for k,v in result['descendants_by_level'].items()}=={k:sorted(v) for k,v in oracle['expected_levels'].items()}
            assert sorted(n['code'] for n in result['terminal_batches'])==sorted(oracle['expected_terminal_codes'])
            affected=[db.get(Batch, ids['S39-ROOT-A'])]+[db.get(Batch,ids[v['code']]) for v in oracle['descendants']]
            assert sum(b.remaining_quantity for b in affected)==Decimal('600')
            consumed=list(db.scalars(select(BatchEvent).where(BatchEvent.event_type=='CONSUMED')).all())
            assert sum(Decimal(e.payload['previous_remaining_quantity']) for e in consumed)==Decimal('600')
            # The old formula incorrectly yields 2600kg.
            assert sum(b.initial_quantity-b.remaining_quantity for b in affected)==Decimal('2600')
            ancestors=trace_backwards(db,ids['S39-FINAL-D1'],use_cache=False)
            assert {b['code'] for b in ancestors['root_batches']}=={'S39-ROOT-A','S39-CLEAN-X'}
            for batch_id in ids.values(): assert verify_batch_chain(db,batch_id)['is_valid']
            affected_orgs = {b.current_org.code for b in affected}
            assert affected_orgs == set(oracle['expected_metrics']['organizations_required_acknowledgment'])
            cross_codes = []
            for expected in oracle['descendants']:
                actual = db.get(Batch, ids[expected['code']])
                assert float(actual.remaining_quantity) == expected['remaining_quantity']
                assert float(actual.initial_quantity) == expected['initial_quantity']
                assert actual.status == expected['status']
                assert actual.current_org.code == expected['current_org_code']
                origins = trace_backwards(db, actual.id, use_cache=False)['root_batches']
                is_cross = len(origins) > 1
                assert is_cross == expected['is_merged_cross_origin']
                if is_cross: cross_codes.append(actual.code)
            assert len(cross_codes) == oracle['expected_metrics']['cross_origin_contaminated_batches_count']
            assert oracle['verified_by']==[]
    finally: engine.dispose()


@pytest.mark.parametrize('role,org,allowed', [('inspector',None,True),('org_admin',1,True),('org_admin',2,False),('system_admin',1,False),('farmer',1,False),('processor',1,False),('distributor',1,False),('transporter',1,False)])
def test_existing_recall_permission_contract(role,org,allowed):
    user=User(username='policy',password='disabled',role=role,organization_id=org)
    batch=Batch(current_org_id=1)
    assert can_recall_batch(user,batch,raise_exception=False) is allowed


def test_seed_refuses_file_database(session_factory):
    with session_factory() as db:
        with pytest.raises(ValueError): seed_recall_s39(db)


def test_cli_refuses_real_migration(tmp_path):
    import subprocess
    import sys
    script=Path(__file__).parents[1]/'scripts/migrate_stage3b_recall.py'
    for args in [['--apply'], ['--target-db', str(tmp_path/'never_created.db')]]:
        result=subprocess.run([sys.executable,str(script),*args],capture_output=True,text=True)
        assert result.returncode==2
        assert 'disabled' in result.stderr
    assert not (tmp_path/'never_created.db').exists()
