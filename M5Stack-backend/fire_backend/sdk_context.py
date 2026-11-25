"""One version-specific SDK policy, replacing legacy instructions, not layering them."""
from importlib.resources import files
import json
import re

from .app_sdk import SDK_VERSION, SDK_CONTRACT, available, classify, contract

VERSION='fire-sdk-generation-v6'
MARKER='\nFIRE SDK request contract:\n'
_BUDGETS=contract()['registry']['budgets']

POLICY='''
FIRE App SDK development and acceptance policy, version6:
Build exactly the confirmed app with sensible defaults. Preserve working code
during correction; fix concrete defects rather than redesigning or adding scope.
Use the real fire.ui kit, shared fonts and selected canonical assets for standard
widgets. Use a tested ui.set_theme/theme palette, not guessed RGB565 constants.
Do not recreate large digit fonts or standard UI from per-pixel/segment loops.
Compose a polished readable320x240 frame with clear hierarchy and short labels.

Define BOTH mandatory global callbacks init() and update(dt_ms), even if init
has no work. Optional on_button(button,action) receives short "pressed" events.
Minimal valid lifecycle (replace the screen with the complete requested app):
function init() fire.ui.set_theme("modern_dark") end
function update(dt_ms) fire.ui.screen("APP") end
The OS clears its OFFSCREEN sprite before EVERY update and presents it afterwards.
Set the UI theme in init as above: it configures the next OS-prepared background.
Theme/background configuration in on_button applies to the next update; a change
inside update applies to the following frame. set_background never draws.
Only the first pristine matching clear may reuse the actual OS prefill; later or
different clears really erase. Keep one complete scene and avoid redundant fills.
Draw the COMPLETE scene every update, including menu/pause/wait/end; init-only
graphics vanish. Never alternate blank/drawn frames or split one visible scene
across updates. Clear at most once before drawing. No app-owned present/flush.
Native text_style aligns INSIDE a top-left textbox, not around a center anchor:
text_style(10,85,value,color,"digits28","center",300) centers on the screen.
Use integer coordinates, bounded measured text, actual supported font IDs and
canonical asset IDs. The shared text is transparent; never invent API arguments.

Actual SDK callback quotas:64 TOTAL I/O calls (including measurements, buttons,
time and sensors),2048 I/O bytes,256 cumulative UTF8 text bytes INCLUDING measure,
384 cumulative grid cells and32768 grid pixels. Keep the announced app-memory
quota including the UI module.
''' + f'''Native callback guards: SDK update {_BUDGETS['sdk_update_callback_ms']}ms,
on_button {_BUDGETS['callback_ms']}ms, init {_BUDGETS['init_callback_ms']}ms;
{_BUDGETS['callback_instructions']} instructions. Only SDK update was calibrated;
legacy update/button remain {_BUDGETS['callback_ms']}ms and init remains {_BUDGETS['init_callback_ms']}ms.
''' + '''
PC display-work is an ESTIMATE, never a measurement of native callback time.
Only these SDK quotas apply; recommended draw-count targets are not release gates.
Prefer compact cached geometry/text, bounded tables/loops, no waits or loaders.

A=previous/up, B=select/confirm, C=next/down by default. ui.buttons(a,b,c)
labels the PHYSICAL left/middle/right buttons; match actual on_button bindings.
UI drawing helpers do not activate controls. Bind EVERY visible menu action,
settings item, pause/return/restart button. Use short pressed actions, not custom
chords/long/double gestures. OS owns long A=Home, B=Quick settings, C=Back(650ms)
and configured double clicks. on_button changes state; the next update performs
scheduled work and renders it. This is immediate responsive input, not a defect.
Avoid unnecessary input queues; if needed bound them and visibly reject NEW
overflow before accepting it, without dropping already accepted actions.

Apps run until user exit when lifetime=0. Handle reset, empty/full state, index
bounds, held/rapid input, error/disconnect/unavailable services and cleanup.
Use real announced sensors with correct units; distinguish stale/invalid samples
from fresh data, handle zero/vertical IMU and calibration. No fabricated hardware.
Poll asynchronous jobs without waiting. Stop/cancel/close jobs on mute, reset,
pause/exit and scene transitions; service outstanding jobs in ALL scenes, not
only gameplay. No resource leaks after game over or return to menu.

When RGB is available use both five-LED bars for meaningful status/events. Limit
to one changed rgb.set per callback, compare colour VALUES rather than new table
identity, and don't resend unchanged colours. Cache a desired pattern when state
changes. Blue=good, red=error, amber=busy; toggling RGB off clears both bars.
Games need a quick actual Start/settings menu, intuitive three-button mechanics,
distinct actors/board/score/progression and real pause/restart/return paths.
When speaker/jobs is advertised supply pleasant meaningful music/cues and a
working sound toggle BEFORE play, sound initially off. Primary channel gain255
under OS master/mute; don't confuse gain with percentage. OS owns backlight.
Conversation audio grants no Lua hardware. Never invent missing services.

Review only concrete defects against the literal request and chosen visible
features. No new lap-history/chaining/gameplay features as release blockers.
Put optional polish and unmeasured native timing in verification_notes. In-bounds
SDK operations or PC-work alone do not prove a native phase-time violation. Cite an actual
source defect/violated negotiated bound or actual matching physical evidence.
Keep real logic/unit/cleanup/clipping/control/readability defects as blockers.
Normally one generation and one existing multimodal review, targeted correction
when needed. PC results never establish physical installation, timing or success.
'''


def from_context(context):
    for marker in (MARKER,'\nAuthoritative selected FIRE App SDK context (overrides legacy-only font/UI restrictions):\n'):
        if marker not in context:continue
        try:
            value,_=json.JSONDecoder().raw_decode(context.split(marker,1)[1])
        except ValueError:continue
        if value.get('api_version',value.get('version'))==SDK_VERSION and value.get('api_contract')==SDK_CONTRACT:
            return True
    return False


def detailed_services(summary,caps,base_manifest=None):
    from .api_registry import service_closure
    from .hardware_requests import TERMS
    allowed=set(caps.get('services',[]))
    selected={'display','buttons','rgb','time'}
    from .runtime_contract import explicitly_requested
    if explicitly_requested(summary):selected.update({'ai','jobs'})
    selected.update(name for name,pattern in TERMS.items() if re.search(pattern,summary,re.I))
    if re.search(r'imu|sensor|dashboard|vater|instrument|kompass|compass',summary,re.I):selected.add('imu')
    if re.search(r'vær|vaer|weather|nett|internet|web',summary,re.I):selected.update({'wifi','jobs'})
    from .data_contract import available as data_available
    if data_available(caps) and re.search(r'måling|maaling|measure|logg?|record|registrer|capture|signal|vibr|sammenlign|compare|analy[sz]|diagnos|rådata|raw.data|datasett?|dataset|datagrunnlag',summary,re.I):
        selected.update({'data','sd','jobs'})
    if classify(summary) in {'racing','space','platformer','adventure','puzzle'}:selected.update({'speaker','jobs','sd'})
    selected.update((base_manifest or {}).get('required_services',[]))
    return sorted(set(service_closure(selected&allowed,SDK_VERSION))&allowed)


def normalize(context,*,capabilities=None,summary='',base_manifest=None):
    """Replace known old policy blocks; all common safety rules live in POLICY."""
    sdk=available(capabilities) if capabilities is not None else from_context(context)
    if not sdk:return context
    # A retained/resumed SDK context may carry an older consolidated policy.
    if context.lstrip().startswith('FIRE App SDK development and acceptance policy, version') and MARKER in context:
        context=context[context.index(MARKER):]
    from .rendering import VISUAL_POLICY
    from .app_quality import APP_QUALITY_POLICY
    from .build_strategy import POLICY as DEVELOPMENT_POLICY
    from .quality import RULES
    from .failure_learning import REGRESSION_CHECKS
    from .api_registry import generation_contract
    old_context=files('fire_backend').joinpath('data/FIRE_DEVICE_CONTEXT.md').read_text(encoding='utf-8')
    for old in (old_context,VISUAL_POLICY,APP_QUALITY_POLICY,DEVELOPMENT_POLICY,RULES['budget'],REGRESSION_CHECKS['budget'],POLICY):
        context=context.replace(old,'')
    # Remove our previous canonical marker before inserting exactly one.
    if MARKER in context:
        before,after=context.split(MARKER,1)
        try:
            _,end=json.JSONDecoder().raw_decode(after);context=before+after[end:]
        except ValueError:pass
    if capabilities is not None:
        marker='\nExact negotiated host contract (arguments, returns, dependencies, units and bounds):\n'
        if marker in context:
            before,after=context.split(marker,1)
            try:
                _,end=json.JSONDecoder().raw_decode(after);context=before+after[end:]
            except ValueError:pass
        selection=summary+(' data recording' if 'Frozen development context.' in context else '')
        detail=generation_contract(SDK_VERSION,detailed_services(selection,capabilities,base_manifest),capabilities)
        context+='\nExact negotiated host contract (arguments, returns, dependencies, units and bounds):\n'+json.dumps(detail,ensure_ascii=False,separators=(',',':'))
    anchor={'api_version':SDK_VERSION,'api_contract':SDK_CONTRACT,'policy_version':VERSION}
    return POLICY+MARKER+json.dumps(anchor,separators=(',',':'))+'\n'+context.strip()


GENERATION_STAGE="""
This is the CODE stage after explicit current build_confirm. Return complete
executable main_lua, a short Norwegian purpose-based name (1-3 words, max32chars),
bare required_services and bounded test_sequences. No prose, Markdown, invented
APIs, credentials, confirmation requests or claims of installation/RUN.
Use the exact selected signatures/options and palette. Keep the app simple and
complete; every visible feature must work. For real async hardware, include short
A/B/C sequences that START operations and exercise stop/return paths, max32buttons
at100..1000ms intervals. Correct tests rather than deleting agreed features.
"""
