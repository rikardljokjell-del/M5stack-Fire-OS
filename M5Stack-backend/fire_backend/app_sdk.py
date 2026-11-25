"""Adapters to the single canonical FIRE App SDK; no second asset catalog."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re


DATA = Path(__file__).parent / 'data' / 'app_sdk'
SDK_VERSION = 'fire-app-sdk-1.0'


def _json(path, maximum=16777216):
    if path.stat().st_size > maximum:
        raise ValueError('Canonical SDK resource exceeds bound')
    return json.loads(path.read_text(encoding='utf-8'))


def contract():
    packaged = DATA / 'contract.json'
    path = packaged if packaged.exists() else Path(__file__).resolve().parents[1] / 'contracts' / 'APP_SDK-v1.json'
    data = _json(path, 131072)
    registry = data['registry']
    checksum = hashlib.sha256(json.dumps(registry, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if registry['api_version'] != SDK_VERSION or checksum != data['api_contract']:
        raise ValueError('Canonical SDK contract checksum mismatch')
    return data


SDK_CONTRACT = contract()['api_contract']


def available(capabilities):
    extension = (capabilities or {}).get('app_sdk') or {}
    return (extension.get('version') == SDK_VERSION and extension.get('contract') == SDK_CONTRACT
            and 'display' in (capabilities or {}).get('services', []))


def package_api(capabilities):
    return SDK_VERSION if available(capabilities) else (capabilities or {}).get('api_version', 'fire-lua-0.1')


def data_fingerprint():
    names=('ui.lua','fonts.json','assets.json','sdk.json','contract.json')
    signature=tuple((name,(DATA/name).stat().st_mtime_ns,(DATA/name).stat().st_size) for name in names)
    return _fingerprint(signature)


@lru_cache(maxsize=4)
def _fingerprint(signature):
    hashes={name:hashlib.sha256((DATA/name).read_bytes()).hexdigest() for name,_,_ in signature}
    return hashlib.sha256(json.dumps(hashes,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def assets():
    return _assets(data_fingerprint())


@lru_cache(maxsize=2)
def _assets(fingerprint):
    data = _json(DATA / 'assets.json')
    if data.get('schema') != 1 or not isinstance(data.get('assets'), list):
        raise ValueError('Invalid canonical asset catalog')
    return {item['id']: item for item in data['assets']}


def ui_source():
    return _ui_source(data_fingerprint())


@lru_cache(maxsize=2)
def _ui_source(fingerprint):
    text = (DATA / 'ui.lua').read_text(encoding='utf-8')
    if len(text.encode('utf-8')) > 100000:
        raise ValueError('Trusted SDK UI source exceeds bound')
    return text


CATEGORIES = {
    'clock': ('klokke tidtaker stoppeklokke nedtelling timer clock watch', 'clock', 'modern_dark', 'clock timer alarm calendar'),
    'instrument': ('sensor dashboard imu vater instrument måler temperatur elektronikk i2c gpio pwm uart', 'instrument', 'professional_instrument', 'gauge activity thermometer compass cpu circuit-board'),
    'weather': ('vær vaer weather vind regn sol', 'dashboard', 'nature', 'sun cloud rain wind thermometer'),
    'calculator': ('kalkulator regne calculator', 'calculator', 'minimal', 'calculator hash equal percent'),
    'racing': ('bil racing race kjøretøy kjoretoy', 'racing', 'neon', 'car-top bus-top car flag fuel'),
    'space': ('romskip space shooter skytespill asteroide ufo', 'arcade', 'sci_fi', 'ufo projectile star bomb heart-full'),
    'platformer': ('plattform platformer hopp mario', 'platformer', 'pixel_art', 'blue-alien-idle coin flag key heart-full'),
    'adventure': ('rpg eventyr adventure dungeon historie', 'adventure', 'adventure', 'knight key coin chest heart-full'),
    'puzzle': ('tetris snake slange prikkjakt puzzle pusle sjakk', 'puzzle', 'retro_arcade', 'coin heart-full trophy play pause'),
}


def selected_context(summary, capabilities):
    if not available(capabilities):
        return ''
    words = set(re.findall(r'[a-zæøå0-9-]+', summary.casefold()))
    best = max(CATEGORIES, key=lambda k: len(words.intersection(CATEGORIES[k][0].split())))
    score = len(words.intersection(CATEGORIES[best][0].split()))
    _, layout, theme, hints = CATEGORIES[best] if score else ('', 'dashboard', 'modern_dark', 'activity settings check circle-help')
    wanted = words | set(hints.split())
    ranked = []
    for asset in assets().values():
        searchable = set(re.findall(r'[a-z0-9-]+', ' '.join(str(asset.get(k) or '') for k in
                              ('id', 'alias', 'description', 'category', 'style')).casefold()))
        rank = len(searchable.intersection(wanted))
        if rank:
            ranked.append((rank, asset['id'], asset))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    chosen = [{k: a.get(k) for k in ('id', 'alias', 'width', 'height', 'kind', 'style', 'description', 'tintable')}
              for _, _, a in ranked[:12]]
    functions = _json(DATA / 'sdk.json')['ui_signatures']
    common = ['set_theme', 'screen', 'label', 'title', 'panel', 'card', 'button', 'buttons', 'menu',
              'toggle', 'icon', 'progress', 'navigate']
    specific = {'instrument': ['gauge', 'ring', 'line_chart', 'compass'], 'clock': ['clock', 'timer', 'countdown'],
                'racing': ['sprite', 'hud', 'game_menu', 'pause', 'game_over', 'collides'],
                'arcade': ['sprite', 'hud', 'game_menu', 'pause', 'game_over', 'burst'],
                'platformer': ['sprite', 'hud', 'game_menu', 'collides', 'particles'],
                'puzzle': ['hud', 'game_menu', 'pause', 'game_over'],
                'adventure': ['sprite', 'dialog', 'hud', 'game_menu', 'game_over']}.get(layout, ['tabs', 'empty', 'error'])
    payload = {'version': SDK_VERSION, 'api_contract': SDK_CONTRACT, 'suggested_layout': layout,
               'suggested_theme': theme, 'alternative_themes': ['modern_dark', 'minimal'],
               'ui': {name: functions[name] for name in dict.fromkeys(common + specific) if name in functions},
               'fonts': {name: {'line_height': f['line_height']} for name, f in _json(DATA / 'fonts.json')['fonts'].items()},
               'assets': chosen, 'native_display': contract()['registry']['display'],
               'rules': ['Use fire.ui and selected real asset IDs to avoid regenerating standard widgets.',
                         'Aliases are search metadata, never runtime asset IDs.',
                         'Compose a distinctive readable full frame; UI helpers do not own a framebuffer.',
                         'Shared text_style is transparent and clips its aligned box; legacy text remains unchanged.',
                         'SDK supersedes legacy-only 24-call/120000-work/128-grid policies: 64 TOTAL I/O calls, 2048 I/O bytes, 256 text bytes including measure, 384 grid cells and 32768 grid pixels per callback. Display work is an estimate, not native timing. 128KiB app quota includes UI prelude; keep app allocations small.',
                         'Keep old callback/memory/I/O/time limits. SDK grid permits 384 cumulative cells and 32768 pixels.',
                         'Choose defaults and preserve agreed scope; normally one generation and one review, targeted corrections only.']}
    return '\nAuthoritative selected FIRE App SDK context (overrides legacy-only font/UI restrictions):\n' + json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
