"""Deterministic, bounded data analysis; raw inputs are never rewritten.

CSV is streamed row by row. PCM reads use small blocks. Only an explicitly
bounded FFT window is materialized, rather than an entire recording.
"""
import cmath
import csv
import math
import json
import re
import struct
import wave
from collections import deque


class DataProcessingError(ValueError):
    pass


def _check(cancelled):
    if cancelled and cancelled():
        raise DataProcessingError('cancelled')


def samples(path, kind, metadata, column=None, cancelled=None):
    """Yield (position,value); malformed samples remain invalid, never zero."""
    if kind == 'csv':
        columns = metadata.get('columns')
        if not isinstance(columns, list) or not columns or len(columns) > 8:
            raise DataProcessingError('CSV requires declared columns')
        names = [c.get('name') if isinstance(c, dict) else c for c in columns]
        if any(not isinstance(n, str) or not n or len(n.encode()) > 48 for n in names) or len(set(names)) != len(names):
            raise DataProcessingError('Invalid columns')
        if column is None:
            column = names[0]
        if column not in names:
            raise DataProcessingError('Unknown column')
        # Bound individual rows before csv parsing; no huge parser allocation.
        with path.open('r', encoding='utf-8', errors='strict', newline='') as handle:
            def lines():
                while True:
                    line = handle.readline(4097)
                    if not line:
                        return
                    _check(cancelled)
                    if len(line.encode('utf-8')) > 4096:
                        raise DataProcessingError('CSV row too large')
                    yield line
            reader = csv.reader(lines(), strict=True)
            first = True
            try:
                for position, row in enumerate(reader):
                    if first and metadata.get('header', True):
                        first = False
                        if row != names:
                            raise DataProcessingError('CSV header does not match columns')
                        continue
                    first = False
                    try:
                        value = float(row[names.index(column)]) if len(row) == len(names) else math.nan
                    except (ValueError, IndexError):
                        value = math.nan
                    yield position, value if math.isfinite(value) else None
            except (csv.Error, UnicodeError) as error:
                raise DataProcessingError('Invalid CSV encoding or row') from error
    elif kind == 'audio':
        encoding = metadata.get('encoding')
        if encoding in {'wav_s16le','pcm_s16le_wav'}:
            try:
                with wave.open(str(path), 'rb') as source:
                    if source.getsampwidth() != 2 or source.getnchannels() != 1 or source.getcomptype() != 'NONE':
                        raise DataProcessingError('Only mono PCM16 WAV is supported')
                    expected_rate = metadata.get('sample_rate_hz')
                    if expected_rate and expected_rate != source.getframerate():
                        raise DataProcessingError('WAV sample rate contradicts metadata')
                    position = 0
                    while True:
                        _check(cancelled)
                        block = source.readframes(2048)
                        if not block:
                            break
                        for (value,) in struct.iter_unpack('<h', block):
                            yield position, value / 32768
                            position += 1
            except (wave.Error, EOFError, struct.error) as error:
                raise DataProcessingError('Invalid PCM WAV') from error
        elif encoding == 'pcm_s16le' and metadata.get('channels', 1) == 1:
            position = 0
            with path.open('rb') as source:
                while True:
                    _check(cancelled)
                    block = source.read(4096)
                    if not block:
                        break
                    if len(block) % 2:
                        raise DataProcessingError('Truncated PCM16 sample')
                    for (value,) in struct.iter_unpack('<h', block):
                        yield position, value / 32768
                        position += 1
        else:
            raise DataProcessingError('Audio encoding is not declared or supported')
    else:
        raise DataProcessingError('Numeric processing requires CSV or declared PCM audio')


def statistics(path, kind, metadata, column=None, cancelled=None):
    count = invalid = 0
    mean = m2 = squares = 0.0
    low = high = None
    for _, value in samples(path, kind, metadata, column, cancelled):
        if value is None:
            invalid += 1
            continue
        count += 1
        delta = value - mean
        mean += delta / count
        m2 += delta * (value - mean)
        squares += value * value
        low = value if low is None else min(low, value)
        high = value if high is None else max(high, value)
        if not all(math.isfinite(x) for x in (mean, m2, squares)):
            raise DataProcessingError('Numeric range exceeds analysis precision')
    return {'operation': 'stats', 'column': column, 'valid_samples': count, 'invalid_samples': invalid,
            'min': low, 'max': high, 'mean': mean if count else None,
            'rms': math.sqrt(squares / count) if count else None,
            'stddev': math.sqrt(max(0, m2 / count)) if count else None,
            'evidence': 'deterministic_computation', 'physical_interpretation_verified': False}


def spectrum(path, kind, metadata, column=None, *, window=1024, start=0, cancelled=None, rate_basis=None):
    if type(window) is not int or not 16 <= window <= 4096 or window & (window - 1):
        raise DataProcessingError('FFT window must be a power of two in 16..4096')
    if type(start) is not int or start < 0:
        raise DataProcessingError('Invalid window start')
    rate = metadata.get('sample_rate_hz')
    if rate is not None and (type(rate) not in (int, float) or not math.isfinite(rate) or rate <= 0):
        raise DataProcessingError('Invalid declared sample rate')
    hz_allowed = rate is not None and rate_basis is not None
    values = []
    seen = 0
    for _, value in samples(path, kind, metadata, column, cancelled):
        if seen < start:
            seen += 1
            continue
        if value is None:
            raise DataProcessingError('FFT window contains invalid samples')
        values.append(value)
        if len(values) == window:
            break
    if len(values) != window:
        raise DataProcessingError('Not enough samples for FFT window')
    center = sum(values) / window
    weights = [.5 - .5 * math.cos(2 * math.pi * i / (window - 1)) for i in range(window)]
    values = [complex((v - center) * w) for v, w in zip(values, weights)]
    j = 0
    for i in range(1, window):
        bit = window >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            values[i], values[j] = values[j], values[i]
    size = 2
    while size <= window:
        _check(cancelled)
        root = cmath.exp(-2j * math.pi / size)
        for offset in range(0, window, size):
            factor = 1 + 0j
            for k in range(size // 2):
                a, b = values[offset + k], factor * values[offset + k + size // 2]
                values[offset + k], values[offset + k + size // 2] = a + b, a - b
                factor *= root
        size *= 2
    gain = sum(weights)
    bins = [(i, abs(values[i]) * (1 if i == window // 2 else 2) / gain) for i in range(1, window // 2 + 1)]
    if any(not math.isfinite(a) for _, a in bins):
        raise DataProcessingError('Numeric range exceeds FFT precision')
    peaks = sorted(bins, key=lambda item: (-item[1], item[0]))[:5]
    return {'operation': 'spectrum', 'column': column, 'declared_sample_rate_hz': rate, 'window': window,
            'start': start, 'window_function': 'hann', 'removed_mean': center,
            'resolution_cycles_per_sample': 1/window,
            **({'resolution_hz': rate/window} if hz_allowed else {}),
            'peaks': [{'cycles_per_sample': i/window, 'amplitude': a,
                       **({'frequency_hz': i * rate / window} if hz_allowed else {})} for i, a in peaks],
            'rate_basis': rate_basis or 'Unknown sampling clock; cycles/sample only',
            'assumption': 'Aliasing and sensor-clock calibration error are not excluded',
            'evidence': 'deterministic_computation', 'physical_interpretation_verified': False}


def compare(left, right):
    if left.get('operation') != 'stats' or right.get('operation') != 'stats' or left.get('column') != right.get('column'):
        raise DataProcessingError('Compare requires matching statistics columns')
    return {'operation': 'compare', 'column': left.get('column'),
            'left_valid_samples': left['valid_samples'], 'right_valid_samples': right['valid_samples'],
            'deltas': {key: right[key] - left[key] if right[key] is not None and left[key] is not None else None
                       for key in ('min', 'max', 'mean', 'rms', 'stddev')},
            'evidence': 'deterministic_computation', 'physical_interpretation_verified': False}


def moving_average(path, kind, metadata, output, column=None, *, window=8, cancelled=None, max_bytes=16777216):
    """Write a derived file with source-row references; gaps remain gaps."""
    if type(window) is not int or not 1 <= window <= 256:
        raise DataProcessingError('Filter window must be in 1..256')
    if path.resolve() == output.resolve():
        raise DataProcessingError('Raw input cannot be overwritten')
    values = deque(maxlen=window)
    count = invalid = 0
    with output.open('x', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle, lineterminator='\n')
        writer.writerow(['source_row', 'value'])
        for position, value in samples(path, kind, metadata, column, cancelled):
            if handle.tell() > max_bytes - 80:
                raise DataProcessingError('Derived file exceeds dataset limit')
            if value is None:
                values.clear()
                invalid += 1
                writer.writerow([position, ''])
                continue
            values.append(value)
            average = sum(values) / len(values)
            if not math.isfinite(average):
                raise DataProcessingError('Numeric range exceeds filter precision')
            writer.writerow([position, format(average, '.17g')])
            count += 1
    return {'operation': 'filter', 'method': 'moving_average', 'window': window,
            'valid_samples': count, 'invalid_samples': invalid, 'column': column,
            'output_columns': ['source_row', 'value'], 'warmup': 'available valid samples since last gap',
            'evidence': 'deterministic_computation', 'physical_interpretation_verified': False}


def sidecar_summary(index_path, events_path, raw_size, cancelled=None):
    """Keep timing/markers as reported provenance, never certified sensor facts."""
    result = {'append_records': 0, 'marker_records': 0, 'invalid_index': 0, 'invalid_events': 0,
              'first_monotonic_us': None, 'last_monotonic_us': None, 'markers': [],
              'evidence': 'device_uploaded_index_and_events', 'user_observation_confirmed': False}
    def records(path):
        with path.open('rb') as handle:
            while True:
                _check(cancelled)
                line = handle.readline(4097)
                if not line:
                    return
                if len(line) > 4096:
                    raise DataProcessingError('Sidecar row too large')
                try:
                    from .runtime_contract import parse, RuntimeAIError
                    value = parse(line.decode('utf-8'), 4096)
                    if not isinstance(value, dict):
                        yield None
                    else:
                        yield value
                except (UnicodeError, RuntimeAIError):
                    yield None
    last_offset = 0
    for row in records(index_path):
        if (row is None or set(row) != {'offset','length','monotonic_us'} or
                any(type(row.get(k)) is not int or row[k] < 0 for k in ('offset','length','monotonic_us')) or
                row['offset'] + row['length'] > raw_size or row['offset'] != last_offset):
            result['invalid_index'] += 1
            continue
        stamp = row['monotonic_us']
        if result['last_monotonic_us'] is not None and stamp < result['last_monotonic_us']:
            result['invalid_index'] += 1
            continue
        last_offset = row['offset'] + row['length']
        result['append_records'] += 1
        if result['first_monotonic_us'] is None:
            result['first_monotonic_us'] = stamp
        result['last_monotonic_us'] = stamp
    result['indexed_bytes'] = last_offset
    result['index_complete'] = last_offset == raw_size
    for row in records(events_path):
        if (row is None or set(row) != {'label','offset','monotonic_us'} or
                not isinstance(row.get('label'),str) or len(row['label'].encode()) > 64 or
                any(type(row.get(k)) is not int or row[k] < 0 for k in ('offset','monotonic_us')) or row['offset'] > raw_size):
            result['invalid_events'] += 1
            continue
        result['marker_records'] += 1
        if len(result['markers']) == 6:
            result['markers'].pop(0)
        result['markers'].append(row)
    result['markers_omitted'] = result['marker_records'] - len(result['markers'])
    return result


def content_windows(path, kind, markers=(), cancelled=None):
    """Small marker-related byte ranges, not an entire text/log/protocol dump."""
    size = path.stat().st_size
    positions = [m['offset'] for m in list(markers)[-2:]] if markers else [0, max(0, size-24)]
    positions = list(dict.fromkeys(max(0, min(size-24, p-8)) for p in positions))
    windows = []
    with path.open('rb') as handle:
        for position in positions[:2]:
            _check(cancelled)
            handle.seek(position)
            raw = handle.read(24 if kind == 'binary' else 96)
            row = {'offset':position, 'length':len(raw)}
            if kind == 'text':
                try:
                    row['text'] = raw.decode('utf-8')
                except UnicodeError:
                    row['hex'] = raw.hex()
            else:
                row['hex'] = raw.hex()
            windows.append(row)
    return {'selection':'last marker byte windows' if markers else 'bounded first/last byte windows',
            'windows':windows, 'same_windows':len(windows)==2 and
            (windows[0].get('hex',windows[0].get('text')) == windows[1].get('hex',windows[1].get('text'))),
            'raw_bytes_retained':True, 'evidence':'deterministic_content_selection'}


def ble_content(path, markers=(), cancelled=None):
    """Decode the agreed generic AD record, never infer a product protocol."""
    targets = [m['offset'] for m in list(markers)[-2:]]
    chosen = [None] * len(targets)
    first = last = None
    count = invalid = changes = duplicates = 0
    previous = None; at = 0
    with path.open('rb') as handle:
        while True:
            _check(cancelled)
            line = handle.readline(4097)
            if not line:
                break
            offset = at; at += len(line)
            if len(line) > 4096:
                raise DataProcessingError('BLE record too large')
            try:
                from .runtime_contract import parse, RuntimeAIError
                row = parse(line.decode('utf-8'), 4096)
                required={'t_us','address','address_type','rssi','event_type','payload_hex'}
                if (not isinstance(row,dict) or not required <= set(row) or set(row)-required-{'adv_length'} or
                        type(row['t_us']) is not int or row['t_us'] < 0 or
                        not isinstance(row['address'],str) or not re.fullmatch(r'(?:[A-Fa-f0-9]{2}:){5}[A-Fa-f0-9]{2}',row['address']) or
                        any(type(row[k]) is not int for k in ('address_type','rssi','event_type')) or
                        not -127 <= row['rssi'] <= 20 or not 0 <= row['address_type'] <= 3 or not 0 <= row['event_type'] <= 255 or
                        not isinstance(row['payload_hex'],str) or len(row['payload_hex']) > 124 or len(row['payload_hex'])%2 or
                        any(c not in '0123456789abcdefABCDEF' for c in row['payload_hex'])):
                    raise ValueError('bad record')
                if 'adv_length' in row and (type(row['adv_length']) is not int or not 0 <= row['adv_length'] <= len(row['payload_hex'])//2):
                    raise ValueError('bad advertising length')
            except (ValueError,UnicodeError,RuntimeAIError):
                invalid += 1
                continue
            row['offset'] = offset
            signature = (row['address'], row['payload_hex'])
            if previous is not None:
                duplicates += signature == previous
                changes += signature != previous
            previous = signature
            count += 1; first = first or row; last = row
            for i,target in enumerate(targets):
                if chosen[i] is None and offset >= target:
                    chosen[i] = row
    selected = [r or last for r in chosen] if targets else [first,last]
    if len(selected) == 1 and last and selected[0]['offset'] != last['offset']:
        selected.append(last)
    records = []; seen = set()
    for row in selected:
        if row and row['offset'] not in seen:
            seen.add(row['offset']); records.append(row)
    return {'selection':'records at/after selected marker offsets' if targets else 'first/last valid AD records',
            'records':records, 'valid_records':count, 'invalid_records':invalid,
            'consecutive_duplicate_records':duplicates, 'consecutive_changed_records':changes,
            'selected_delta_us':records[-1]['t_us']-records[0]['t_us'] if len(records)==2 else None,
            'protocol_interpretation':'Unknown; raw advertising and scan-response bytes only',
            'evidence':'deterministic_content_selection'}


def signal_columns(metadata):
    names = [c.get('name') if isinstance(c,dict) else c for c in metadata.get('columns',[])]
    return [n for n in names if isinstance(n,str) and n.casefold() not in
            {'sample_index','sample','index','received_us','timestamp','timestamp_ms','time','time_ms','t','t_us','t_ms'}]


def statistics_many(path, metadata, selected, cancelled=None):
    """One pass for bounded multi-axis signals; no entire-series table."""
    columns = metadata.get('columns',[])
    names = [c.get('name') if isinstance(c,dict) else c for c in columns]
    if not names or len(names)>8 or len(set(names)) != len(names) or not set(selected)<=set(names):
        raise DataProcessingError('Invalid columns')
    states = {name:{'n':0,'bad':0,'mean':0.,'m2':0.,'ss':0.,'min':None,'max':None} for name in selected}
    with path.open('r',encoding='utf-8',newline='') as handle:
        def lines():
            while True:
                _check(cancelled)
                line=handle.readline(4097)
                if not line:return
                if len(line.encode())>4096:raise DataProcessingError('CSV row too large')
                yield line
        first=True
        try:
            for row in csv.reader(lines(),strict=True):
                if first and metadata.get('header',True):
                    first=False
                    if row!=names:raise DataProcessingError('CSV header does not match columns')
                    continue
                first=False
                for name,state in states.items():
                    try:value=float(row[names.index(name)]) if len(row)==len(names) else math.nan
                    except (ValueError,IndexError):value=math.nan
                    if not math.isfinite(value):state['bad']+=1;continue
                    state['n']+=1;delta=value-state['mean'];state['mean']+=delta/state['n']
                    state['m2']+=delta*(value-state['mean']);state['ss']+=value*value
                    state['min']=value if state['min'] is None else min(state['min'],value)
                    state['max']=value if state['max'] is None else max(state['max'],value)
                    if not all(math.isfinite(state[k]) for k in ('mean','m2','ss')):
                        raise DataProcessingError('Numeric range exceeds analysis precision')
        except (csv.Error,UnicodeError) as error:raise DataProcessingError('Invalid CSV') from error
    return {name:{'operation':'stats','column':name,'valid_samples':s['n'],'invalid_samples':s['bad'],
        'min':s['min'],'max':s['max'],'mean':s['mean'] if s['n'] else None,
        'rms':math.sqrt(s['ss']/s['n']) if s['n'] else None,
        'stddev':math.sqrt(max(0,s['m2']/s['n'])) if s['n'] else None,
        'evidence':'deterministic_computation','physical_interpretation_verified':False} for name,s in states.items()}


def fifo_rate_basis(path, metadata, acquisition, index_summary, cancelled=None):
    """Check nominal FIFO clock against sequential data and actual host timing.

    Receipt timing is not a per-sample clock. This does not certify calibration;
    it only allows explicitly labeled Hz when that nominal clock is consistent.
    """
    if (acquisition != 'native_imu_fifo' or index_summary['invalid_index'] or index_summary['invalid_events']
            or not index_summary.get('index_complete')):
        return None
    rate = metadata.get('sample_rate_hz')
    if type(rate) not in (int,float) or not math.isfinite(rate) or rate <= 0:
        return None
    count = 0; first = last = previous_index = None; max_gap = 0
    with path.open('r', encoding='utf-8', newline='') as handle:
        header = handle.readline(4097).strip().split(',')
        if 'sample_index' not in header or 'received_us' not in header:
            return None
        seq_at, time_at = header.index('sample_index'), header.index('received_us')
        for line in handle:
            _check(cancelled)
            if len(line.encode()) > 4096:
                return None
            try:
                row = line.strip().split(','); sequence, received = int(row[seq_at]), int(row[time_at])
            except (ValueError,IndexError):
                return None
            if sequence < 0 or received < 0 or previous_index is not None and sequence != previous_index+1:
                return None
            if last is not None:
                if received < last:
                    return None
                max_gap = max(max_gap, received-last)
            first = received if first is None else first
            last = received; previous_index = sequence; count += 1
    if count < 16 or last <= first:
        return None
    observed = (count-1)*1_000_000/(last-first)
    if abs(observed/rate-1) > .10 or max_gap > max(100000, 16_000_000/rate):
        return None
    return {'kind':'reported_FIFO_nominal_clock_consistent_with_host_receipts', 'nominal_hz':rate,
            'receipt_span_us':last-first, 'samples':count, 'receipt_average_hz':observed,
            'max_receipt_gap_us':max_gap, 'clock_calibration_verified':False}
