"""Agreed product-specific boundaries and automatic immutable evidence."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.hash_chain import verify_batch_chain
from app.models import Batch, BatchEvent, Product
from app.trip_models import TemperatureLog, TemperatureViolation
from tests.test_s45_temperature_violations import setup_s45_data as _seed_s45, _auth_header


@pytest.fixture
def setup_s45_data(session_factory):
    return _seed_s45.__wrapped__(session_factory)


def send(client, data, minute, temp=15):
    stamp = datetime(2026, 10, 20, 1) + timedelta(minutes=minute)
    return client.post(f'/trips/{data["trip_id"]}/readings',
                       json={"temperature": temp, "recorded_at": stamp.isoformat() + 'Z'},
                       headers=_auth_header('trans_s45'))


def configure(client, product_id, low=2, high=8, delay=30):
    return client.put(f'/products/{product_id}/temperature-policy',
                      json={"min_temperature": low, "max_temperature": high, "delay_minutes": delay},
                      headers=_auth_header('sysadmin_s45'))


def test_each_product_independent_strict_boundary_and_replay(client, session_factory, setup_s45_data):
    d = setup_s45_data
    with session_factory() as db:
        b1, b2 = [db.get(Batch, d[key]) for key in ('batch_1_id', 'batch_2_id')]
        product1 = b1.product_id
        product2 = Product(name='Second product', unit='kg')
        db.add(product2)
        db.flush()
        b2.product_id = product2.id
        product2_id = product2.id
        db.commit()
    assert configure(client, product1).status_code == 200
    assert configure(client, product2_id, 10, 20).status_code == 200
    for minute in range(31):
        assert send(client, d, minute).status_code == 201
    with session_factory() as db:
        assert list(db.scalars(select(TemperatureViolation))) == []
    assert send(client, d, 31).status_code == 201
    assert send(client, d, 31, 99).status_code == 201
    assert send(client, d, 20, 99).status_code == 201
    assert send(client, d, 32).status_code == 201
    with session_factory() as db:
        violations = list(db.scalars(select(TemperatureViolation)))
        assert len(violations) == 1
        assert violations[0].batch_id == d['batch_1_id']
        assert violations[0].source_trip_id == d['trip_id']
        assert db.get(Batch, d['batch_1_id']).temperature_violation_count == 1
        assert not db.get(Batch, d['batch_2_id']).has_temperature_violation
        assert verify_batch_chain(db, d['batch_1_id'])['is_valid']
        assert verify_batch_chain(db, d['batch_2_id'])['is_valid']
        assert len(list(db.scalars(select(TemperatureLog)))) == 33
    response = client.get(f'/trips/{d["trip_id"]}/violations', headers=_auth_header('trans_s45'))
    assert len(response.json()) == 1
    response = client.get(f'/trips/{d["trip_id"]}', headers=_auth_header('trans_s45'))
    assert response.json()['violation_count'] == 1


def test_missing_configuration_is_not_safe(client, setup_s45_data):
    d = setup_s45_data
    assert send(client, d, 0).status_code == 201
    assert send(client, d, 45).status_code == 201
    result = client.get(f'/trips/{d["trip_id"]}/evaluation', headers=_auth_header('trans_s45'))
    assert all(not row['configured'] and 'Không thể đánh giá' in row['message'] for row in result.json())
    assert client.get(f'/trips/{d["trip_id"]}/violations', headers=_auth_header('trans_s45')).json() == []


def test_policy_permissions_validation_and_persistence(client, session_factory, setup_s45_data):
    with session_factory() as db:
        pid = db.get(Batch, setup_s45_data['batch_1_id']).product_id
    body = {"min_temperature": 2, "max_temperature": 8, "delay_minutes": 30}
    assert client.put(f'/products/{pid}/temperature-policy', json=body,
                      headers=_auth_header('trans_s45')).status_code == 403
    assert configure(client, pid, 8, 2).status_code == 422
    assert configure(client, pid, delay=29).status_code == 422
    assert configure(client, pid).status_code == 200
    result = client.get(f'/products/{pid}/temperature-policy', headers=_auth_header('trans_s45')).json()
    assert result['configured'] and result['policy'] == body


def test_automatic_event_failure_rolls_back_reading_and_counter(client, session_factory, setup_s45_data):
    d = setup_s45_data
    with session_factory() as db:
        pid = db.get(Batch, d['batch_1_id']).product_id
    assert configure(client, pid).status_code == 200
    assert send(client, d, 0).status_code == 201
    with patch('app.services.cold_chain.record_event', side_effect=RuntimeError('injected')):
        with pytest.raises(RuntimeError):
            send(client, d, 31)
    with session_factory() as db:
        assert len(list(db.scalars(select(TemperatureLog)))) == 1
        assert not list(db.scalars(select(TemperatureViolation)))
        assert not list(db.scalars(select(BatchEvent).where(BatchEvent.event_type == 'TEMPERATURE_VIOLATION')))
        assert db.get(Batch, d['batch_1_id']).temperature_violation_count == 0


def test_recovery_resets_burst_and_low_temperature_peak(client, session_factory, setup_s45_data):
    d = setup_s45_data
    with session_factory() as db:
        pid = db.get(Batch, d['batch_1_id']).product_id
    assert configure(client, pid).status_code == 200
    for minute, temperature in [(0, 15), (20, 5), (21, -4), (51, -5)]:
        assert send(client, d, minute, temperature).status_code == 201
    assert client.get(f'/trips/{d["trip_id"]}/violations', headers=_auth_header('trans_s45')).json() == []
    assert send(client, d, 52, -6).status_code == 201
    result = client.get(f'/trips/{d["trip_id"]}/violations', headers=_auth_header('trans_s45')).json()
    assert len(result) == 2  # both batches share this explicitly configured product
    assert all(v['violation_type'] == 'FREEZING_RISK' and v['peak_temperature'] == -6 for v in result)


def test_configuring_a_product_does_not_rejudge_preconfiguration_samples(client, session_factory, setup_s45_data):
    d = setup_s45_data
    assert send(client, d, 0).status_code == 201
    with session_factory() as db:
        pid = db.get(Batch, d['batch_1_id']).product_id
    assert configure(client, pid).status_code == 200
    assert send(client, d, 31).status_code == 201
    assert client.get(f'/trips/{d["trip_id"]}/violations', headers=_auth_header('trans_s45')).json() == []
    assert send(client, d, 62).status_code == 201
    assert len(client.get(f'/trips/{d["trip_id"]}/violations', headers=_auth_header('trans_s45')).json()) == 2
