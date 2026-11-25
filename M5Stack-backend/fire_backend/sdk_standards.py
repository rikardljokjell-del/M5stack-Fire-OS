"""Backend-owned SDK defaults from confirmed input and actual capabilities."""
import hashlib
import re

from .app_sdk import available, classify
from .app_quality import experience_contract
from .storage import canonical


VERSION='fire-sdk-standards-v1'


def _opt_out(summary,feature):
    # Permanent exceptions only; 'starts off' / an off-on menu is not an opt-out.
    names=r'(?:rgb|led(?:s|lys)?|lys)' if feature=='rgb' else r'(?:(?:spill)?lyd|musikk|audio|(?:game\s+)?sound|music)'
    pattern=r'\b(?:uten|ingen|ikke\s+(?:bruk|ha)|without|no)\s+'+names+r'\b'
    for match in re.finditer(pattern,summary,re.I):
        # A sound on/off clause must not cancel a separate 'without RGB' choice.
        boundary=r'[,;.!]|\b(?:og|and|men|but|med|with)\b'
        before=re.split(boundary,summary[max(0,match.start()-24):match.start()],flags=re.I)[-1]
        after=re.split(boundary,summary[match.end():match.end()+64],flags=re.I)[0]
        nearby=before+match.group()+after
        if re.search(r'fra start|ved start|som standard|by default|initially|av\s*/\s*på|på\s*/\s*av|on\s*/\s*off|off\s*/\s*on',nearby,re.I):continue
        return True
    return False


def contract(capabilities,summary):
    if not available(capabilities):return None
    caps=capabilities or {};experience=experience_contract(caps)
    category=classify(summary)
    # The shared classifier recognizes Norwegian compounds and named game genres.
    # A candidate's own kind/service list must not turn a confirmed game into a tool.
    game=category in {'puzzle','racing','space','platformer','adventure'}
    explicit_audio=bool(re.search(r'\b(?:melodi\w*|musikk\w*|music\w*|lyd\w*|audio|sound|synth\w*)\b',summary,re.I))
    rgb_off,audio_off=_opt_out(summary,'rgb'),_opt_out(summary,'audio')
    return {'version':VERSION,'authority':'actual capabilities and confirmed request; candidate declarations do not reduce defaults',
        'capabilities_sha256':hashlib.sha256(canonical(caps)).hexdigest(),
        'request_sha256':hashlib.sha256(summary.encode('utf-8')).hexdigest(),
        'announced_services':sorted(caps.get('services',[])),
        'game_requested':game,'rgb_available':experience['rgb_available'],
        'audio_available':experience['game_audio_available'],
        'rgb_required':experience['rgb_available'] and not rgb_off,
        'audio_required':experience['game_audio_available'] and (game or explicit_audio) and not audio_off,
        'explicit_rgb_opt_out':rgb_off,'explicit_audio_opt_out':audio_off,'physical_verified':False}


def verify(expected,required_services,validation,source_sha256):
    """Measure execution, not candidate/reviewer claims of availability."""
    if not expected:return None
    services=set(required_services);failures=[]
    profiles=[p for p in (validation.get('profiles') or [validation])
              if p.get('profile') not in {'io_error','io_timeout','io_disconnect'}]
    left=any(p.get('rgb_feedback',{}).get('left_nonzero',False) for p in profiles)
    right=any(p.get('rgb_feedback',{}).get('right_nonzero',False) for p in profiles)
    rgb_writes=sum(p.get('rgb_feedback',{}).get('writes',0) for p in profiles)
    from .api_registry import REGISTRY
    speaker_methods={'speaker.'+name for name,spec in REGISTRY['services']['speaker']['methods'].items() if spec['returns']=='job'}
    audio_jobs=sum(n for p in profiles for name,n in p.get('jobs_started',{}).items() if name in speaker_methods)
    if expected['rgb_required'] and ('rgb' not in services or not left or not right):
        failures.append('Actual device announces RGB: declare rgb and exercise meaningful nonzero feedback on BOTH five-LED sides. Keep the working app; add one changed LED per update, and test RGB-enabled states. Candidate service omission is not an opt-out.')
    if expected['audio_required'] and (not {'speaker','jobs'}<=services or not audio_jobs):
        failures.append('Confirmed app requires available audio: retain speaker/jobs and dependencies, a working sound setting, and a test sequence that ENABLES sound and STARTS real speaker jobs. Keep core gameplay; do not remove the agreed sound feature.')
    missing=validation.get('io_coverage_missing',[])
    if missing:
        failures.append('I/O coverage missing for '+', '.join(missing)+'. Correct test_sequences to START the operations and stop/return paths; preserve the working core and all agreed features.')
    return {'version':VERSION,'source_sha256':source_sha256,
        'contract_sha256':hashlib.sha256(canonical(expected)).hexdigest(),
        'passed':not failures,'rgb':{'writes':rgb_writes,'left_nonzero':left,'right_nonzero':right},
        'audio':{'speaker_jobs_started':audio_jobs},'failures':failures,'physical_verified':False}


def require_passed(record):
    if record and not record['passed']:
        raise ValueError('SDK standard requirements missing: '+' '.join(record['failures']))


MARKER='\nBackend SDK standard contract (actual capabilities and confirmed request):\n'


def context_with_contract(context,expected):
    import json
    if MARKER in context:
        before,after=context.split(MARKER,1)
        try:
            _,end=json.JSONDecoder().raw_decode(after);context=before+after[end:]
        except ValueError:pass
    return context+MARKER+json.dumps(expected,ensure_ascii=False,separators=(',',':')) if expected else context
