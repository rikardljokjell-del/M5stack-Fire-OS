import math
import struct

import pytest

from fire_backend.data_processing import DataProcessingError, compare, spectrum, statistics, moving_average


def csv_signal(tmp_path, values, rate=1024):
    path = tmp_path / 'raw.csv'
    path.write_text('value\n' + '\n'.join(str(v) for v in values), encoding='utf-8')
    return path, {'columns': ['value'], 'sample_rate_hz': rate}


def test_streamed_stats_preserve_raw_invalid_measurements_and_compute_rms(tmp_path):
    path, metadata = csv_signal(tmp_path, [1, 2, 'nan', 'bad', 3, 4])
    original = path.read_bytes()
    stats = statistics(path, 'csv', metadata, 'value')
    assert stats['valid_samples'] == 4 and stats['invalid_samples'] == 2
    assert stats['mean'] == 2.5 and stats['rms'] == pytest.approx(math.sqrt(7.5))
    assert stats['stddev'] == pytest.approx(math.sqrt(1.25))
    assert stats['min'] == 1 and stats['max'] == 4
    assert path.read_bytes() == original and not stats['physical_interpretation_verified']


def test_empty_or_invalid_data_is_not_a_fabricated_zero(tmp_path):
    path, metadata = csv_signal(tmp_path, ['nan', 'inf', 'bad'])
    result = statistics(path, 'csv', metadata, 'value')
    assert result['valid_samples'] == 0 and result['invalid_samples'] == 3
    assert result['mean'] is result['rms'] is result['min'] is result['max'] is None


def test_spectrum_finds_known_frequency_and_amplitude_with_explicit_assumptions(tmp_path):
    path, metadata = csv_signal(tmp_path, (2 + .7 * math.sin(2 * math.pi * 64 * i / 1024) for i in range(1024)))
    result = spectrum(path, 'csv', metadata, 'value', rate_basis={'kind':'synthetic_uniform_fixture'})
    assert result['peaks'][0]['frequency_hz'] == 64
    assert result['peaks'][0]['amplitude'] == pytest.approx(.7, abs=.001)
    assert result['removed_mean'] == pytest.approx(2)
    assert 'aliasing' in result['assumption'].lower() and not result['physical_interpretation_verified']
    with pytest.raises(DataProcessingError):
        spectrum(path, 'csv', metadata, 'value', window=8192)
    unverified=spectrum(path,'csv',{'columns':['value']},'value')
    assert 'frequency_hz' not in unverified['peaks'][0] and unverified['peaks'][0]['cycles_per_sample']==64/1024


def test_pcm16_and_cancel_do_not_require_loading_whole_recording(tmp_path):
    path = tmp_path / 'audio.pcm'
    path.write_bytes(struct.pack('<hhhh', -32768, 0, 16384, 0))
    metadata = {'encoding': 'pcm_s16le', 'channels': 1}
    result = statistics(path, 'audio', metadata)
    assert result['valid_samples'] == 4 and result['mean'] == -.125
    with pytest.raises(DataProcessingError, match='cancelled'):
        statistics(path, 'audio', metadata, cancelled=lambda: True)
    path.write_bytes(path.read_bytes() + b'x')
    with pytest.raises(DataProcessingError, match='Truncated'):
        statistics(path, 'audio', metadata)


def test_compare_is_numerical_not_a_physical_diagnosis(tmp_path):
    path, metadata = csv_signal(tmp_path, [1, 2, 3])
    old = statistics(path, 'csv', metadata, 'value')
    path, metadata = csv_signal(tmp_path, [2, 3, 4])
    new = statistics(path, 'csv', metadata, 'value')
    result = compare(old, new)
    assert result['deltas']['mean'] == 1 and not result['physical_interpretation_verified']
    with pytest.raises(DataProcessingError):
        compare(old, {**new, 'column': 'another-signal'})


def test_oversized_csv_rows_and_header_mismatch_are_rejected(tmp_path):
    path, metadata = csv_signal(tmp_path, ['2' * 5000])
    with pytest.raises(DataProcessingError, match='row too large'):
        statistics(path, 'csv', metadata)
    with pytest.raises(DataProcessingError, match='header'):
        statistics(path, 'csv', {'columns': ['other']})


def test_filter_creates_separate_derived_csv_and_does_not_fill_gaps_with_zero(tmp_path):
    path, metadata = csv_signal(tmp_path, [1, 3, 'nan', 9, 11])
    raw = path.read_bytes()
    output = tmp_path / 'filtered.csv'
    result = moving_average(path, 'csv', metadata, output, 'value', window=2)
    lines = output.read_text(encoding='utf-8').splitlines()
    assert lines == ['source_row,value', '1,1', '2,2', '3,', '4,9', '5,10']
    assert result['valid_samples'] == 4 and result['invalid_samples'] == 1
    assert path.read_bytes() == raw
    with pytest.raises(DataProcessingError, match='overwritten'):
        moving_average(path, 'csv', metadata, path)


def test_fifo_frequency_requires_contiguous_index_and_actual_sample_sequence(tmp_path):
    import json
    from fire_backend.data_processing import sidecar_summary, fifo_rate_basis
    path=tmp_path/'fifo.csv'
    metadata={'columns':['sample_index','ax','received_us'],'sample_rate_hz':100}
    raw='sample_index,ax,received_us\n'+''.join(f'{i},{i%2},{i*10000}\n' for i in range(64))
    path.write_text(raw,encoding='utf-8')
    index=tmp_path/'index.jsonl';events=tmp_path/'events.jsonl';events.write_bytes(b'')
    index.write_text(json.dumps({'offset':0,'length':path.stat().st_size,'monotonic_us':630000})+'\n',encoding='utf-8')
    summary=sidecar_summary(index,events,path.stat().st_size)
    assert fifo_rate_basis(path,metadata,'native_imu_fifo',summary)
    assert fifo_rate_basis(path,metadata,'app_recorded',summary) is None
    index.write_bytes(b'')
    assert fifo_rate_basis(path,metadata,'native_imu_fifo',sidecar_summary(index,events,path.stat().st_size)) is None
    path.write_text(raw.replace('32,0,320000','32,0,9999999'),encoding='utf-8')
    assert fifo_rate_basis(path,metadata,'native_imu_fifo',summary) is None


def test_wav_header_must_match_declared_pcm_not_just_metadata(tmp_path):
    import wave
    path=tmp_path/'capture.wav'
    with wave.open(str(path),'wb') as target:
        target.setnchannels(1);target.setsampwidth(2);target.setframerate(16000);target.writeframes(b'\0\0'*16)
    meta={'encoding':'pcm_s16le_wav','channels':1,'sample_rate_hz':8000}
    with pytest.raises(DataProcessingError,match='rate'):
        statistics(path,'audio',meta)
    meta['sample_rate_hz']=16000
    assert statistics(path,'audio',meta)['valid_samples']==16


@pytest.mark.parametrize('length,valid',[(-1,False),(8,False),(True,False),(3,True),(0,True),(None,True)])
def test_ble_optional_advertising_boundary_preserves_legacy_and_refuses_invalid_length(tmp_path,length,valid):
    import json
    from fire_backend.data_processing import ble_content
    row={'t_us':1000,'address':'AA:BB:CC:DD:EE:FF','address_type':0,'rssi':-45,'event_type':0,'payload_hex':'02010603FFABCD'}
    if length is not None:row['adv_length']=length
    path=tmp_path/'ble.jsonl';path.write_text(json.dumps(row)+'\n',encoding='utf-8')
    result=ble_content(path)
    assert result['valid_records']==int(valid) and result['invalid_records']==int(not valid)
    if valid:
        assert result['records'][0]['payload_hex']==row['payload_hex']
        assert ('adv_length' in result['records'][0])==(length is not None)
