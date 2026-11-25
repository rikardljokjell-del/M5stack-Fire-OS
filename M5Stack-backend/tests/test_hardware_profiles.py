import json
from urllib.parse import urlparse
import pytest
from fire_backend.hardware_profiles import CATALOG, MAX_CONTEXT_BYTES, context_for, select


def test_catalog_documents_facts_without_granting_physical_verification():
    ids = [p['id'] for p in CATALOG['profiles']]
    assert len(ids) == len(set(ids)) >= 15
    for p in CATALOG['profiles']:
        assert p['evidence'] == 'manufacturer_documentation'
        assert p['physical_verified'] is False
        assert p['source_urls']
        for url in p['source_urls']:
            u = urlparse(url)
            assert u.scheme == 'https' and u.hostname in {'docs.m5stack.com', 'docs.espressif.com'}


@pytest.mark.parametrize('query,id', [('Mål med Unit ENV-IV', 'env-family'),
    ('Capture vibrations from IMU', 'fire-imu'), ('Unit Color TCS3472', 'color'),
    ('Logg AT6558 GNSS', 'gps-uart'), ('Les INA226', 'ina226')])
def test_relevant_explicit_module_selection(query, id):
    assert select(query)[0]['id'] == id


def test_no_module_is_invented_for_ordinary_app_requests():
    assert context_for('Lag et bilspill med tidsur', {'services': ['display']}) == ''
    assert select('possibly available') == []


def test_actual_services_and_native_timing_are_preserved():
    text = context_for('Lag et BLE-verktøy', {'services': ['display', 'jobs']})
    d = json.loads(text.split('\n', 2)[2])
    p = d['profiles'][0]
    assert p['api_services_available'] is False
    assert p['missing_services'] == ['bluetooth'] and p['attached'] is False
    p = json.loads(context_for('bare HX711', {'services': ['gpio', 'jobs']}).split('\n', 2)[2])['profiles'][0]
    assert p['native_adapter_required'] and not p['api_services_available']


def test_bounded_json_and_catalog_not_mutated_by_callers():
    source = json.dumps(CATALOG, sort_keys=True)
    picked = select('ENV-IV, MCP4725, TCS3472, GNSS, INA226, Bluetooth')
    picked[0]['facts'].append('untrusted caller claim')
    text = context_for('ENV-IV MCP4725 TCS3472 GNSS INA226 Bluetooth', {})
    assert len(text.encode()) <= MAX_CONTEXT_BYTES
    assert len(json.loads(text.split('\n', 2)[2])['profiles']) <= 3
    assert json.dumps(CATALOG, sort_keys=True) == source
