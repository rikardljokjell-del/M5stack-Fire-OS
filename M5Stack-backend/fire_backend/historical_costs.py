"""Persisted, explicitly approximate pre-metering build costs, never API usage.

Only retained artifacts establish an estimate. Hidden reasoning, cache hits,
lost responses and old voice turns cannot be reconstructed. Bounds are scenario
estimates, not confidence intervals or invoice limits.
"""
import json
import math
import time
import zipfile

from .model_catalog import RATES, PRICING_DATE


METHOD = 'retained-artifacts-v2'


def _text(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _read(path):
    return path.read_text(encoding='utf-8') if path.is_file() else ''


def backfill(store, tracking_started_at):
    """Run at startup; immutable per-build snapshots survive artifact deletion."""
    for build in store.list('builds'):
        build_id = build['id']
        if store.path('historical_costs', build_id).exists():
            if store.get('historical_costs', build_id).get('method') == METHOD:
                continue
        folder = store.path('builds', build_id, '')
        request_path = folder / 'request.json'
        if not request_path.is_file():
            continue
        # Require actual age evidence, not merely absence of a usage record.
        stamp = build.get('created_at', request_path.stat().st_mtime)
        if not isinstance(stamp, (float, int)) or not math.isfinite(stamp) or stamp >= tracking_started_at:
            continue
        try:
            request = json.loads(_read(request_path))
        except (ValueError, UnicodeError):
            continue  # A damaged old artifact must not prevent backend startup.
        if not isinstance(request, dict):
            continue
        if request.get('mode') != 'openai':
            continue
        model = request.get('model')
        sources = sorted(folder.glob('attempt-*.lua'))
        # Deterministic metadata/audio-gain repairs do not call a model.
        if not sources or model not in RATES:
            continue
        review_model = request.get('review_model', model)
        if review_model not in RATES:
            continue
        previous = ''
        base = request.get('base_package_id')
        if base:
            archive = store.path('packages', base, '.zip')
            if archive.is_file():
                try:
                    with zipfile.ZipFile(archive) as package:
                        candidates=[n for n in package.namelist() if n=='main.lua' or n.endswith('/main.lua')]
                        if len(candidates)==1 and package.getinfo(candidates[0]).file_size<=100000:
                            previous = package.read(candidates[0]).decode('utf-8')
                except (KeyError, ValueError, UnicodeError, zipfile.BadZipFile):
                    pass
        common = len(_text(request.get('context', ''))) + len(_text(request.get('capabilities', {}))) + len(_text(request.get('summary', '')))
        simulation = _read(folder / 'simulation.json')
        parts = []
        sources=[p for p in sources if p.stem.split('-')[-1].isdigit()]
        for source_path in sorted(sources, key=lambda p: int(p.stem.split('-')[-1])):
            number = source_path.stem.split('-')[-1]
            source = _read(source_path)
            # Schema/instructions and response JSON overhead are estimated too.
            parts.append(_part('generate', model, common + len(previous) + 4096, len(source) + 1024, 8000, 1500))
            review = _read(folder / f'review-{number}.json')
            if review:
                parts.append(_part('review', review_model, common + len(source) + len(simulation) + 4096, len(review), 4000, 1000))
            previous = source
        if not parts:
            continue
        store.put('historical_costs', build_id, {
            'id': build_id, 'build_id': build_id, 'project_id': build.get('project_id'),
            'method': METHOD, 'estimated_at': time.time(), 'build_timestamp': stamp,
            'pricing_date': PRICING_DATE, 'parts': parts,
            'coverage': 'retained_generation_and_reviews_only',
            'assumptions': 'Characters/4; range characters/5..3. Assumed reasoning: generate 1500, review 1000; high scenario old output cap. No cache discount. Review model defaults to saved code model. Unretained attempts, dialogue and audio excluded.',
        }, critical=True)


def _part(operation, model, input_chars, output_chars, cap, reasoning):
    rate = RATES[model]
    central = (math.ceil(input_chars / 4) * rate[0] + min(cap, math.ceil(output_chars / 4) + reasoning) * rate[2]) / 1e6
    low = (math.ceil(input_chars / 5) * rate[0] + min(cap, math.ceil(output_chars / 5)) * rate[2]) / 1e6
    high = (math.ceil(input_chars / 3) * rate[0] * 2.5 + cap * rate[2]) / 1e6
    return {'operation': operation, 'model': model, 'estimated_usd': central,
            'low_usd': low, 'high_usd': max(central, high),
            'input_chars': input_chars, 'output_chars': output_chars}


def totals(store, records):
    # A subsequently imported real measurement replaces that build/operation's
    # historical approximation instead of being added to it.
    measured = {(r.get('build_id'), r.get('operation')) for r in records}
    grouped = {}
    for item in store.list('historical_costs'):
        parts = [p for p in item['parts'] if (item['build_id'], p['operation']) not in measured]
        if not parts or not item.get('project_id'):
            continue
        row = grouped.setdefault(item['project_id'], {'estimated_usd': 0, 'low_usd': 0, 'high_usd': 0,
            'builds': 0, 'estimated_calls': 0, 'models': set(), 'coverage': item['coverage'], 'method': METHOD})
        row['builds'] += 1
        row['estimated_calls'] += len(parts)
        row['models'].update(p['model'] for p in parts)
        for field in ('estimated_usd', 'low_usd', 'high_usd'):
            row[field] += sum(p[field] for p in parts)
    for row in grouped.values():
        row['models'] = sorted(row['models'])
    return grouped
