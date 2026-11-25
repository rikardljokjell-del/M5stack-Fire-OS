"""Local usage accounting and conservative spending reservations.

Costs are list-price estimates, not an OpenAI invoice. Raw prompts, audio,
responses, credentials and provider error bodies never belong in this ledger.
Display reset is separate from immutable request history and budget accounting.
"""
import math
import json
import re
import threading
import time
from statistics import median
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .storage import new_id
from .model_catalog import PRICING_DATE, RATES, MINUTE_RATES, EXPLICIT_CACHE_MODELS, LONG_CONTEXT_MODELS


OPERATIONS = {'generate', 'review', 'dialog', 'transcribe', 'speech', 'runtime_ai'}


class UsageBudgetError(ValueError):
    def __init__(self, message='Kostnadsgrensen er nådd', *, code='cost_limit'):
        self.code = code
        super().__init__(message)


def _mapping(value):
    if hasattr(value, 'model_dump'):
        value = value.model_dump()
    return value if isinstance(value, dict) else {}


def _count(value):
    return value if type(value) is int and value >= 0 else 0


def _finite(value, default=0):
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0 else default


def _safe_id(value):
    return value if isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', value) else None


def _tokens(usage, cache_write_ttl=None):
    """Normalize Responses and Realtime usage; cache/reasoning are subsets.

    Realtime audio token counts belong inside the aggregate input/output totals,
    never add them a second time. Responses output already includes reasoning.
    """
    data = _mapping(usage)
    if not data or not any(k in data for k in ('input_tokens', 'output_tokens', 'prompt_tokens', 'completion_tokens')):
        return None
    if any(type(v) is not int or v < 0 for v in (
            data.get('input_tokens', data.get('prompt_tokens')),
            data.get('output_tokens', data.get('completion_tokens')))):
        return None
    inp = _count(data.get('input_tokens', data.get('prompt_tokens')))
    out = _count(data.get('output_tokens', data.get('completion_tokens')))
    ind = _mapping(data.get('input_token_details', data.get('input_tokens_details', data.get('prompt_tokens_details'))))
    oud = _mapping(data.get('output_token_details', data.get('output_tokens_details', data.get('completion_tokens_details'))))
    ai = min(inp, _count(ind.get('audio_tokens')))
    ao = min(out, _count(oud.get('audio_tokens')))
    ti, to = inp - ai, out - ao
    cached = min(inp, _count(ind.get('cached_tokens')))
    cd = _mapping(ind.get('cached_tokens_details'))
    ca = min(ai, cached, _count(cd.get('audio_tokens')))
    ct = min(ti, cached - ca)
    # When audio cache has a declared count, preserve its split exactly.
    if 'text_tokens' in cd:
        ct = min(ti, cached - ca, _count(cd.get('text_tokens')))
    write = _count(ind.get('cache_write_tokens'))
    wd = _mapping(ind.get('cache_write_tokens_details'))
    split_known = not write or bool(wd) or cache_write_ttl in {'30m', '12h'}
    if wd:
        w30, w12 = _count(wd.get('ttl_30m_tokens')), _count(wd.get('ttl_12h_tokens'))
        if 'cache_write_tokens' not in ind:write = w30 + w12
        if w30 + w12 != write:return None
    else:
        # The current provider explicitly requests 30m. Older SDK versions may
        # expose only the write total; use the known request TTL in that case.
        # Unknown lifetime stays conservative rather than becoming ordinary input.
        w30, w12 = (write, 0) if cache_write_ttl == '30m' else (0, write)
    if write > ti - ct:return None
    return {'input_tokens': inp, 'output_tokens': out, 'input_text_tokens': ti,
            'output_text_tokens': to, 'input_audio_tokens': ai, 'output_audio_tokens': ao,
            'cached_tokens': ct + ca, 'cached_text_tokens': ct, 'cached_audio_tokens': ca,
            'cache_write_tokens': write, 'cache_write_30m_tokens': w30, 'cache_write_12h_tokens': w12,
            'cache_write_split_known': split_known,
            'reasoning_tokens': min(out, _count(oud.get('reasoning_tokens')))}


def _price(model, tokens, audio_seconds=0):
    if model in MINUTE_RATES:
        return audio_seconds / 60 * MINUTE_RATES[model]
    rate = RATES.get(model)
    if rate is None:
        raise UsageBudgetError('Modellen mangler prisgrunnlag. Velg en støttet modell.', code='unknown_model_price')
    ti, tc, to, ai, ac, ao = rate
    if model in LONG_CONTEXT_MODELS and tokens['input_tokens'] > 272000:
        ti, tc, to = ti * 2, tc * 2, to * 1.5
    if ((tokens['input_audio_tokens'] and ai is None) or
            (tokens['output_audio_tokens'] and ao is None)):
        raise UsageBudgetError('Modellen mangler pris for denne lydtypen.', code='unknown_model_price')
    writes = tokens.get('cache_write_tokens', 0)
    return ((tokens['input_text_tokens'] - tokens['cached_text_tokens'] - writes) * ti +
            tokens['cached_text_tokens'] * tc + tokens.get('cache_write_30m_tokens', 0) * ti * 1.25 +
            tokens.get('cache_write_12h_tokens', 0) * ti * 2.5 +
            tokens['output_text_tokens'] * to +
            (tokens['input_audio_tokens'] - tokens['cached_audio_tokens']) * (ai or 0) +
            tokens['cached_audio_tokens'] * (ac or 0) + tokens['output_audio_tokens'] * (ao or 0)) / 1_000_000


class UsageLedger:
    def __init__(self, store, settings, *, clock=time.time):
        self.store, self.settings, self.clock = store, settings, clock
        self.lock = threading.RLock()
        try:
            self.tz = ZoneInfo('Europe/Oslo')
            self.timezone = 'Europe/Oslo'
        except ZoneInfoNotFoundError:
            self.tz, self.timezone = timezone.utc, 'UTC'
        try:
            self.meta = self.store.get('usage', 'meta')
        except FileNotFoundError:
            self.meta = {'id': 'meta', 'tracking_started_at': self.clock(), 'reset_at': self.clock()}
            self.store.put('usage', 'meta', self.meta, critical=True)
        # A request which outlived its process may still have been billed.
        for record in self.records():
            if record['status'] == 'pending':
                record.update(status='unknown', finished_at=self.clock(), usage_source='reservation')
                self.store.put('usage', record['id'], record, critical=True)
        from .historical_costs import backfill
        backfill(self.store, self.meta['tracking_started_at'])

    def records(self):
        return [r for r in self.store.list('usage') if r.get('id') != 'meta']

    def _day(self, stamp):
        return datetime.fromtimestamp(stamp, self.tz).date().isoformat()

    def begin(self, operation, model, input_tokens, max_output_tokens, *, build_id=None,
              project_id=None, input_audio_tokens=0, max_output_audio_tokens=0, audio_seconds=None,session_id=None,turn_id=None,runtime_request_id=None):
        if operation not in OPERATIONS:
            raise ValueError('Unknown usage operation')
        if any(type(v) is not int or v < 0 for v in (input_tokens, max_output_tokens, input_audio_tokens, max_output_audio_tokens)):
            raise ValueError('Usage token bounds must be nonnegative integers')
        seconds = _finite(audio_seconds)
        if model in MINUTE_RATES and not seconds:
            raise UsageBudgetError('Opptakets varighet mangler.', code='unknown_model_price')
        tokens = {'input_tokens': input_tokens + input_audio_tokens,
                  'output_tokens': max_output_tokens + max_output_audio_tokens,
                  'input_text_tokens': input_tokens, 'output_text_tokens': max_output_tokens,
                  'input_audio_tokens': input_audio_tokens, 'output_audio_tokens': max_output_audio_tokens,
                  'cached_tokens': 0, 'cached_text_tokens': 0, 'cached_audio_tokens': 0,
                  'cache_write_tokens': 0, 'cache_write_30m_tokens': 0, 'cache_write_12h_tokens': 0,
                  'reasoning_tokens': 0}
        cache_ttl = '30m' if operation in {'generate', 'review'} and model in EXPLICIT_CACHE_MODELS else None
        if cache_ttl == '30m':
            # Responses defaults to paid 30m cache writes on current models.
            # Reserve the write rate for the whole input bound before sending.
            tokens.update(cache_write_tokens=input_tokens, cache_write_30m_tokens=input_tokens)
        elif operation in {'generate', 'review','runtime_ai'} and model.startswith('gpt-6'):
            # A custom supported model without an explicit request TTL may use
            # a different lifetime. Reserve its longer write rate conservatively.
            tokens.update(cache_write_tokens=input_tokens, cache_write_12h_tokens=input_tokens)
        if model in MINUTE_RATES:
            # The provider bills duration and need not report token counts. Do
            # not display input/output reservation bounds as measured tokens.
            tokens = {key: 0 for key in tokens}
        reserve = _price(model, tokens, seconds)
        if not project_id and _safe_id(build_id):
            try:project_id=self.store.get('builds',build_id).get('project_id')
            except FileNotFoundError:pass
        now = self.clock()
        with self.lock:
            records = self.records()
            today = sum(r['estimated_usd'] for r in records if self._day(r['started_at']) == self._day(now))
            build = sum(r['estimated_usd'] for r in records if build_id and r.get('build_id') == build_id)
            enforce=getattr(self.settings,'fire_cost_limits_enabled',False)
            if operation=='runtime_ai' and getattr(self.settings,'fire_runtime_ai_limits_enabled',False):
                runtime=[r for r in records if r['operation']=='runtime_ai' and self._day(r['started_at'])==self._day(now)]
                for limit,total in ((getattr(self.settings,'fire_runtime_ai_request_budget_usd',0),reserve),
                                    (getattr(self.settings,'fire_runtime_ai_daily_budget_usd',0),sum(r['estimated_usd'] for r in runtime)+reserve)):
                    if limit>0 and total>limit+1e-12:raise UsageBudgetError('Runtime AI-kostnadsgrensen er nådd.')
                calls=getattr(self.settings,'fire_runtime_ai_daily_calls',0)
                if calls>0 and len(runtime)>=calls:raise UsageBudgetError('Runtime AI-kallgrensen er nådd.')
            if enforce and self.settings.fire_request_budget_usd>0 and reserve > self.settings.fire_request_budget_usd + 1e-12:
                raise UsageBudgetError('Kallet overstiger kostnadsgrensen.')
            if enforce and self.settings.fire_daily_budget_usd>0 and today + reserve > self.settings.fire_daily_budget_usd + 1e-12:
                raise UsageBudgetError('Dagens kostnadsgrense er nådd.')
            if enforce and self.settings.fire_build_budget_usd>0 and build_id and build + reserve > self.settings.fire_build_budget_usd + 1e-12:
                raise UsageBudgetError('Byggets kostnadsgrense er nådd.')
            record = {'id': new_id('usage'), 'operation': operation, 'model': model,
                      'build_id': _safe_id(build_id), 'project_id': _safe_id(project_id),
                      'session_id':_safe_id(session_id),'turn_id':_safe_id(turn_id),
                      'runtime_request_id':_safe_id(runtime_request_id),
                      'status': 'pending', 'started_at': now, 'finished_at': None,
                      **tokens, 'audio_seconds': seconds, 'reserved_usd': reserve,
                      'estimated_usd': reserve, 'usage_source': 'reservation',
                      'cache_write_ttl': cache_ttl,
                      'request_id': None, 'pricing_date': PRICING_DATE}
            self.store.put('usage', record['id'], record, critical=True)
            return record['id']

    def finish(self, record_id, usage=None, *, status='completed', request_id=None, duration_seconds=None, response_meta=None):
        if status not in {'completed', 'failed', 'cancelled', 'unknown'}:
            raise ValueError('Unknown usage request status')
        with self.lock:
            record = self.store.get('usage', record_id)
            if record.get('status') != 'pending':
                return record  # Completion/replay must not charge twice.
            tokens = _tokens(usage, record.get('cache_write_ttl'))
            record.update(status=status, finished_at=self.clock(), request_id=_safe_id(request_id))
            if response_meta:
                record.update({k:response_meta[k] for k in ('provider_status','incomplete_reason','failure_code','max_output_tokens','reasoning_effort') if k in response_meta})
            if record['model'] in MINUTE_RATES:
                seconds = _finite(duration_seconds, record['audio_seconds'])
                if seconds and status == 'completed':
                    record.update(audio_seconds=seconds, estimated_usd=_price(record['model'], record, seconds),
                                  usage_source='duration')
                    # A duration-priced endpoint need not report token usage.
                    if tokens:record.update(tokens)
            elif tokens:
                try:
                    price = _price(record['model'], tokens)
                except UsageBudgetError:
                    # Unknown modality cannot turn an unpriced request into zero.
                    record['usage_source'] = 'reservation'
                else:
                    record.update(tokens, estimated_usd=price, usage_source='provider')
            self.store.put('usage', record_id, record, critical=True)
            return record

    def attribute_turn(self,session_id,turn_id,project_id):
        """Attach ASR/dialogue to the resolved app when a repair picks its target.

        Only attribution changes; financial amounts/status remain untouched.
        Explicit build attribution is authoritative and is never rewritten.
        """
        project_id=_safe_id(project_id)
        if not project_id or not _safe_id(session_id) or not _safe_id(turn_id):return
        with self.lock:
            records_all=self.records()
            for record in records_all:
                if (not record.get('build_id') and record.get('session_id')==session_id and
                        record.get('turn_id')==turn_id and record.get('project_id')!=project_id):
                    record.setdefault('original_project_id',record.get('project_id'))
                    record['project_id']=project_id
                    self.store.put('usage',record['id'],record,critical=True)

    def project_costs(self):
        """Lifetime app totals, independent of resets and package/version deletion."""
        with self.lock:
            builds={b['id']:b.get('project_id') for b in self.store.list('builds')}
            grouped={}
            records_all=self.records()
            # Runtime inference is consumption of an installed app, not its
            # accumulated development price. Keep it in its own counters.
            development=self.cost_records(records_all)
            for record in development:
                if record['operation']=='runtime_ai':continue
                project_id=record.get('project_id') or builds.get(record.get('build_id'))
                if project_id:grouped.setdefault(project_id,[]).append(record)
            result={project_id:{**self._totals(records),
                'by_operation':[{'operation':op,**self._totals([r for r in records if r['operation']==op])}
                                for op in sorted({r['operation'] for r in records})],
                'currency':'USD','scope':'all_versions_lifetime','tracking_started_at':self.meta['tracking_started_at']}
                    for project_id,records in grouped.items()}
            from .historical_costs import totals
            for project_id,history in totals(self.store,records_all).items():
                row=result.setdefault(project_id,{**self._totals([]),'by_operation':[],
                    'currency':'USD','scope':'all_versions_lifetime','tracking_started_at':self.meta['tracking_started_at']})
                row['historical_estimate']=history
                row['recorded_usd']=row['provider_calculated_usd']
                row['estimated_usd']+=history['estimated_usd']
            self._mark_untracked_history(result,records_all,'project_id')
            return result

    def _mark_untracked_history(self,result,records,group):
        """Absence of old artifacts is not evidence of a zero-price live job."""
        tracked={r.get('build_id') for r in records}
        history={r['build_id'] for r in self.store.list('historical_costs')}
        for b in self.store.list('builds'):
            if b['id'] in tracked or b['id'] in history:continue
            path=self.store.path('builds',b['id'],'')/'request.json'
            try:request=json.loads(path.read_text(encoding='utf-8'))
            except (OSError,ValueError):continue
            stamp=_finite(b.get('created_at'),path.stat().st_mtime)
            if request.get('mode')!='openai' or stamp>=self.meta['tracking_started_at']:continue
            key=b.get(group)
            if not key:continue
            row=result.setdefault(key,{**self._totals([]),'recorded_usd':0})
            row['unestimated_requests']+=1
            row['unknown_historical_jobs']=row.get('unknown_historical_jobs',0)+1

    def cost_records(self, records):
        """Public price views; never mistake an output ceiling for expenditure.

        Missing terminal usage can use the median of at least three measured
        requests of the same operation/model. No reservation enters that median.
        Unknown/pending requests stay explicit when no empirical basis exists.
        Immutable ledger amounts remain available for conservative admission.
        """
        samples={}
        for r in records:
            if r.get('usage_source') in {'provider','duration'} and r.get('status')=='completed' and r.get('cache_write_split_known') is not False:
                samples.setdefault((r['operation'],r['model']),[]).append(r)
        empirical_basis={}
        for key,rows in samples.items():
            peers=sorted(rows,key=lambda v:v['started_at'])[-20:]
            empirical_basis[key]=(len(peers),median(v['estimated_usd'] for v in peers))
        result=[]
        for raw in records:
            r=dict(raw);measured=r.get('usage_source') in {'provider','duration'}
            known=measured and r.get('cache_write_split_known') is not False
            count,typical=empirical_basis.get((r['operation'],r['model']),(0,0))
            empirical=typical if not known and r['status']!='pending' and count>=3 else None
            r.update(provider_calculated_usd=r['estimated_usd'] if known else 0,
                     empirical_estimated_usd=empirical or 0,
                     empirical_samples=count if empirical is not None else 0,
                     price_kind=r['usage_source'] if known else 'empirical' if empirical is not None else 'pending' if r['status']=='pending' else 'unknown',
                     budget_exposure_usd=raw['estimated_usd'],
                     budget_reserved_usd=raw.get('reserved_usd',0) if not known else 0,
                     estimated_usd=r['estimated_usd'] if known else empirical,
                     tokens_measured=measured,
                     latency_ms=max(0,round(((r.get('finished_at') or self.clock())-r['started_at'])*1000)))
            if not measured:
                for key in tuple(k for k in r if k.endswith('_tokens') and k!='max_output_tokens'):
                    r[key]=0
            result.append(r)
        return result

    def _totals(self, records):
        if any('price_kind' not in r for r in records):records=self.cost_records(records)
        return {'requests': len(records),
                **{k: sum(r.get(k, 0) for r in records) for k in (
                    'input_tokens', 'output_tokens', 'cached_tokens', 'cache_write_tokens', 'audio_seconds')},
                'estimated_usd':sum(_finite(r.get('estimated_usd')) for r in records),
                'provider_calculated_usd':sum(r.get('provider_calculated_usd',0) for r in records),
                'empirical_estimated_usd':sum(r.get('empirical_estimated_usd',0) for r in records),
                'empirically_estimated_requests':sum(r.get('price_kind')=='empirical' for r in records),
                'unestimated_requests':sum(r.get('price_kind') in {'unknown','pending'} for r in records),
                'budget_exposure_usd':sum(r.get('budget_exposure_usd',0) for r in records),
                'budget_reserved_usd':sum(r.get('budget_reserved_usd',0) for r in records),
                'latency_ms':sum(r.get('latency_ms',0) for r in records),
                'unknown_usage_requests': sum(r['usage_source'] == 'reservation' for r in records),
                'pending_requests': sum(r['status'] == 'pending' for r in records)}

    def build_costs(self):
        """Job lifetime, including continuations and separately marked legacy estimates."""
        with self.lock:
            records=self.cost_records(self.records());grouped={}
            for record in records:
                if record.get('build_id') and record['operation']!='runtime_ai':grouped.setdefault(record['build_id'],[]).append(record)
            result={key:{**self._totals(rows),'recorded_usd':self._totals(rows)['provider_calculated_usd']}
                for key,rows in grouped.items()}
            from .historical_costs import totals
            for key,history in totals(self.store,records,'build_id').items():
                row=result.setdefault(key,{**self._totals([]),'recorded_usd':0})
                row['historical_estimate']=history
                row['estimated_usd']+=history['estimated_usd']
            self._mark_untracked_history(result,records,'id')
            return result

    def conversation_costs(self):
        """One conversation row spans its session, never the whole project."""
        grouped={}
        for r in self.cost_records(self.records()):
            if r.get('session_id') and not r.get('build_id') and r['operation'] in {'dialog','transcribe','speech'}:
                grouped.setdefault(r['session_id'],[]).append(r)
        return {key:self._totals(rows) for key,rows in grouped.items()}

    def runtime_costs(self):
        """Lifetime installed-app inference, separate from app development."""
        grouped={}
        for r in self.cost_records(self.records()):
            if r['operation']=='runtime_ai' and r.get('project_id'):
                grouped.setdefault(r['project_id'],[]).append(r)
        return {key:self._totals(rows) for key,rows in grouped.items()}

    def snapshot(self):
        with self.lock:
            records = self.cost_records(self.records())
            now = self.clock()
            visible = [r for r in records if (r.get('finished_at') or r['started_at']) >= self.meta['reset_at']]
            today = [r for r in records if self._day(r['started_at']) == self._day(now)]
            def grouped(key):
                keys = {r.get(key) for r in visible if r.get(key)}
                rows = [{key: value, **self._totals([r for r in visible if r.get(key) == value])} for value in keys]
                if key == 'build_id':
                    for row in rows:
                        row['project_id'] = next(r.get('project_id') for r in visible if r.get(key) == row[key])
                return sorted(rows, key=lambda r: r['estimated_usd'], reverse=True)
            return {'currency': 'USD', 'estimated': True, 'pricing_date': PRICING_DATE,
                    'reset_at': self.meta['reset_at'], 'tracking_started_at': self.meta['tracking_started_at'],
                    'since_reset': self._totals(visible), 'today': self._totals(today), 'lifetime': self._totals(records),
                    'limits': {'enabled':getattr(self.settings,'fire_cost_limits_enabled',False),
                               'output_limits_enabled':getattr(self.settings,'fire_output_limits_enabled',False),
                               'daily_usd': self.settings.fire_daily_budget_usd,
                               'request_usd': self.settings.fire_request_budget_usd,
                               'build_usd': self.settings.fire_build_budget_usd,
                               'daily_remaining_usd': max(0, self.settings.fire_daily_budget_usd - self._totals(today)['budget_exposure_usd']) if getattr(self.settings,'fire_cost_limits_enabled',False) and self.settings.fire_daily_budget_usd>0 else None,
                               'budget_day': self._day(now), 'timezone': self.timezone},
                    'by_operation': grouped('operation'), 'by_model': grouped('model'), 'by_build': grouped('build_id')[:50],
                    'development':self._totals([r for r in visible if r['operation']!='runtime_ai']),
                    'runtime_ai':self._totals([r for r in visible if r['operation']=='runtime_ai']),
                    'recent': sorted(visible, key=lambda r: r.get('finished_at') or r['started_at'], reverse=True)[:100],
                    'note': 'Anslått USD fra registrert bruk og datert prisliste, ikke faktura. '
                            'Ukjent bruk er ukjent; empirisk anslag krever minst tre målte kall av samme type/modell. '
                            'Intern budsjettreserve er et maksimum, aldri kostnadsanslag. '
                            'Historiske byggeanslag vises separat under Apper, ikke i disse målingstellerne. '
                            'Nullstilling endrer bare visningstellerne.'}

    def reset(self):
        with self.lock:
            self.meta['reset_at'] = self.clock()
            self.store.put('usage', 'meta', self.meta, critical=True)
            return self.snapshot()
