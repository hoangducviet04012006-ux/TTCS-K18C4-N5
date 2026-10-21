"""Public safety and milestone semantics, using the real lineage/Recall services."""
import json

from sqlalchemy import select

from app.hash_chain import record_event
from app.models import Batch, BatchRelation, Organization, User
from app.recall_models import Recall
from tests.test_public_trace_s48 import _create_sample_batch, _farmer_headers


def test_pending_handover_is_not_complete_or_mislabelled(client, session_factory):
    batch = _create_sample_batch(client)
    with session_factory() as db:
        user = db.scalar(select(User).where(User.username == 'farmer'))
        target = Organization(name='Private Logistics carrier', code='PRIVATE-CARRIER')
        db.add(target)
        db.flush()
        record_event(db, batch['id'], 'HANDOVER_INIT', {'note': 'private note'},
                     user.organization_id, user.id, to_org_id=target.id)
        db.commit()
    response = client.get('/public/trace/' + batch['code'])
    assert response.status_code == 200
    milestone = response.json()['milestones'][-1]
    assert milestone['status'] == 'Chờ xác nhận'
    assert milestone['organization_type'] == 'Đơn vị vận chuyển'
    assert 'Private Logistics carrier' not in response.text and 'private note' not in response.text


def test_recall_public_warning_covers_descendants_without_private_reason(client, session_factory):
    batch = _create_sample_batch(client)
    split = client.post(f'/batches/{batch["id"]}/split', json={'child_quantities': [500, 1000]},
                        headers=_farmer_headers())
    assert split.status_code == 201
    with session_factory() as db:
        user = db.scalar(select(User).where(User.username == 'farmer'))
        recall = Recall(recall_code='RECALL-PUBLIC-TEST', root_batch_id=batch['id'],
                        reason='SECRET INTERNAL REASON', status='OPEN',
                        created_by_user_id=user.id, created_by_org_id=user.organization_id)
        db.add(recall)
        db.commit()
        child_id = db.scalar(select(BatchRelation.child_batch_id).where(BatchRelation.parent_batch_id == batch['id']))
        child_code = db.get(Batch, child_id).code
    for code in (batch['code'], child_code):
        response = client.get('/public/trace/' + code)
        assert response.status_code == 200
        public = response.json()
        assert public['recall_warning'] and 'Không sử dụng' in public['status']
        assert 'SECRET INTERNAL REASON' not in response.text and 'reason' not in json.dumps(public)
        assert any(m['stage'] == 'Thu hoạch tại vùng trồng' for m in public['milestones'])


def test_recall_milestones_distinguish_root_init_and_child_affected(client, session_factory):
    """Test S-49/S-48: Phân biệt rõ mốc Khởi tạo thu hồi (lô gốc) và Áp dụng thu hồi lan truyền (lô con)."""
    batch = _create_sample_batch(client)
    split = client.post(f'/batches/{batch["id"]}/split', json={'child_quantities': [300, 700]},
                        headers=_farmer_headers())
    assert split.status_code == 201
    with session_factory() as db:
        user = db.scalar(select(User).where(User.username == 'farmer'))
        # Tạo sự kiện RECALL_INIT cho lô gốc và RECALL_AFFECTED cho lô con
        child_id = db.scalar(select(BatchRelation.child_batch_id).where(BatchRelation.parent_batch_id == batch['id']))
        child = db.get(Batch, child_id)
        record_event(db, batch['id'], 'RECALL_INIT', {'recall_code': 'RECALL-TEST-DIFF'},
                     user.organization_id, user.id)
        record_event(db, child.id, 'RECALL_AFFECTED', {'recall_code': 'RECALL-TEST-DIFF'},
                     user.organization_id, user.id)
        db.commit()
        child_code = child.code

    res = client.get('/public/trace/' + child_code)
    assert res.status_code == 200
    milestone_stages = [m['stage'] for m in res.json()['milestones']]
    assert "Khởi tạo lệnh thu hồi (lô gốc)" in milestone_stages
    assert "Áp dụng thu hồi lan truyền (lô thành phẩm phái sinh)" in milestone_stages
    # Đảm bảo 2 mốc không bị trùng lặp nhãn
    assert milestone_stages.count("Thu hồi / cách ly sản phẩm") == 0
