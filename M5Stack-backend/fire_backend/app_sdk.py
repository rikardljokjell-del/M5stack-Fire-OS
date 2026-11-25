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


def callback_budgets(api_version):
    """Declared native phase limits, not timing measured by the PC simulator."""
    budgets = contract()['registry']['budgets']
    keys = ['callback_ms', 'init_callback_ms']
    if api_version == SDK_VERSION:
        keys.append('sdk_update_callback_ms')
    return {key: budgets[key] for key in keys}


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
    'dashboard': ('sensordashboard sensor dashboard', 'sensor_monitor', 'professional_instrument', 'activity thermometer battery gauge'),
    'instrument': ('imu vater instrument måler temperatur elektronikk i2c gpio pwm uart', 'instrument', 'professional_instrument', 'gauge activity thermometer compass cpu circuit-board'),
    'weather': ('vær vaer weather vind regn sol', 'dashboard', 'nature', 'sun cloud rain wind thermometer'),
    'calculator': ('kalkulator regne calculator', 'calculator', 'minimal', 'calculator hash equal percent'),
    'racing': ('bil racing race kjøretøy kjoretoy', 'racing', 'neon', 'car-top bus-top car flag fuel'),
    'space': ('romskip space shooter skytespill asteroide ufo', 'arcade', 'sci_fi', 'ufo projectile star bomb heart-full'),
    'platformer': ('plattform platformer hopp mario', 'platformer', 'pixel_art', 'blue-alien-idle coin flag key heart-full'),
    'adventure': ('rpg eventyr adventure dungeon historie', 'adventure', 'adventure', 'knight key coin chest heart-full'),
    'puzzle': ('tetris snake slange prikkjakt puzzle pusle sjakk', 'puzzle', 'retro_arcade', 'coin heart-full trophy play pause'),
}


# Prefixes are restricted to actual app nouns, not arbitrary substring matches.
# Norwegian compounds are normal user language (bilspill, værapp, måleinstrument).
CATEGORY_PATTERNS={
 'clock':r'\b(?:stoppeklokk\w*|stopwatch\w*|tidtak\w*|nedtell\w*|klokke\w*|clock\w*)',
 'dashboard':r'\b(?:sensor(?:dashboard|monitor)\w*|sensordashbord\w*|dashboard\w*|dashbord\w*)',
 'instrument':r'\b(?:måleinstrument\w*|maaleinstrument\w*|instrument\w*|vater\w*|inclinometer\w*|imu|kompass\w*|compass\w*)',
 'weather':r'\b(?:vær\w*|vaer\w*|weather\w*|forecast\w*)',
 'calculator':r'\b(?:kalkulator\w*|calculator\w*)',
 'racing':r'\b(?:bilspill\w*|billøp\w*|billop\w*|biler|racing\w*|race|car\s+(?:game|racing)|driving\w*)',
 'space':r'\b(?:romskip\w*|romspill\w*|space\s*(?:shooter|game)|shooter\w*|asteroid\w*)',
 'platformer':r'\b(?:plattform\w*|platform\w*|jump(?:ing)?\s+game)',
 'adventure':r'\b(?:eventyr\w*|adventure\w*|rpg|dungeon\w*)',
 'puzzle':r'\b(?:tetris\w*|snake\w*|slangespill\w*|prikkjakt\w*|pacman|sjakk\w*|chess\w*|puzzle\w*|pusle\w*)',
}


def classify(summary):
    words=set(re.findall(r'[a-zæøå0-9-]+',summary.casefold()))
    scores={key:len(words.intersection(value[0].split()))+2*bool(re.search(CATEGORY_PATTERNS[key],summary,re.I))
            for key,value in CATEGORIES.items()}
    best=max(scores,key=scores.get)
    return best if scores[best] else None


def glyph_coverage():
    """Small factual groups derived from shipped masks, never system fonts."""
    groups={};printable=set(range(32,127))
    for name,font in _json(DATA/'fonts.json')['fonts'].items():
        points=frozenset(map(int,font['glyphs']))
        groups.setdefault(points,[]).append(name)
    result=[]
    for points,names in groups.items():
        extra=''.join(chr(p) for p in sorted(points-printable))
        result.append({'fonts':sorted(names),'printable_ascii':printable<=points,
            'extra_characters':extra[:32],'extra_count':len(extra),'extra_list_complete':len(extra)<=32})
    return {'groups':result,'unsupported_character_renders_as':'?'}


def selected_context(summary, capabilities, *, include_native=True):
    if not available(capabilities):
        return ''
    words = set(re.findall(r'[a-zæøå0-9-]+', summary.casefold()))
    best=classify(summary)
    _, layout, theme, hints = CATEGORIES[best] if best else ('', 'dashboard', 'modern_dark', 'activity settings check circle-help')
    hint_words=set(hints.split())
    query_words=words-{'lag','lage','en','et','ei','app','spill','game','create','make','build','a','an','the','with','med'}
    wanted=query_words|hint_words
    ranked = []
    for asset in assets().values():
        searchable = set(re.findall(r'[a-z0-9-]+', ' '.join(str(asset.get(k) or '') for k in
                              ('id', 'alias', 'description', 'category', 'style')).casefold()))
        rank = 3*len(searchable.intersection(hint_words))+len(searchable.intersection(query_words))
        if rank and layout in {'racing','arcade','platformer','adventure','puzzle'} and asset.get('kind')=='sprite':rank+=3
        if rank:
            ranked.append((rank, asset['id'], asset))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    chosen = [{k: a.get(k) for k in ('id', 'alias', 'width', 'height', 'kind', 'style', 'description', 'tintable')}
              for _, _, a in ranked[:12]]
    metadata=_json(DATA / 'sdk.json')
    functions = metadata['ui_signatures']
    common = ['set_theme', 'theme', 'background', 'screen', 'label', 'title', 'panel', 'card', 'button', 'buttons', 'menu',
              'toggle', 'icon', 'progress', 'navigate']
    specific = {'sensor_monitor':['gauge','line_chart','table','battery'], 'instrument': ['gauge', 'ring', 'line_chart', 'compass'], 'clock': ['clock', 'timer', 'countdown'],
                'racing': ['sprite', 'hud', 'game_menu', 'pause', 'game_over', 'collides'],
                'arcade': ['sprite', 'hud', 'game_menu', 'pause', 'game_over', 'burst'],
                'platformer': ['sprite', 'hud', 'game_menu', 'collides', 'particles'],
                'puzzle': ['hud', 'game_menu', 'pause', 'game_over'],
                'adventure': ['sprite', 'dialog', 'hud', 'game_menu', 'game_over']}.get(layout, ['tabs', 'empty', 'error'])
    payload = {'version': SDK_VERSION, 'api_contract': SDK_CONTRACT, 'suggested_layout': layout,
               'suggested_theme': theme,
               'palette':{k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',re.search(r'\n\s*'+re.escape(theme)+r'=\{([^}]+)\}',ui_source()).group(1))}, 'alternative_themes': ['modern_dark', 'minimal'],
               'ui': {name: functions[name] for name in dict.fromkeys(common + specific) if name in functions},
               'fonts': {name: {'line_height': f['line_height']} for name, f in _json(DATA / 'fonts.json')['fonts'].items()},
               'font_glyph_coverage':glyph_coverage(),
               'assets': chosen,
               'ui_help':{name:metadata['ui_help'][name] for name in dict.fromkeys(common+specific) if name in metadata.get('ui_help',{})},
               'ui_options':{name:metadata['ui_options'][name] for name in dict.fromkeys(common+specific) if name in metadata.get('ui_options',{})},
               'examples':{'text':'local c=fire.ui.theme(); fire.ui.label(10,85,"12:34",{width=300,align="center",font="digits28",color=c.fg})',
                           'input':'local selected,mode=1,0\nfunction on_button(button,action)\n if action~="pressed" then return end\n local activate; selected,activate=fire.ui.navigate(selected,button,3)\n if activate then mode=selected end\nend',
                           'clock':'fire.ui.screen("STOPPEKLOKKE",running and "Måling" or "Klar"); fire.ui.timer(10,85,elapsed_ms,{width=300,align="center"})',
                           'controls':'fire.ui.buttons("Forrige","Velg","Neste","B") -- bind actual A/B/C actions; adapt labels to the app'},
               'rules': ['Use fire.ui and selected real asset IDs to avoid regenerating standard widgets.',
                         'Aliases are search metadata, never runtime asset IDs.',
                         'Compose a distinctive readable full frame; UI helpers do not own a framebuffer.',
                         'Shared text_style is transparent and clips its aligned box; legacy text remains unchanged.',
                         'SDK: 64 total I/O calls, 2048 I/O bytes, 256 text bytes including measurement, 384 grid cells and 32768 grid pixels per callback. Preserve announced app memory including UI prelude. Work estimates never prove native timing.',
                         'Use tested theme palette fields; UI helpers only draw and app owns EVERY action/state transition.',
                         'Choose defaults and preserve agreed scope; normally one generation and one review, targeted corrections only.']}
    if include_native:payload['native_display']=contract()['registry']['display']
    if layout in {'instrument','sensor_monitor'}:
        payload['math']={'available':['abs','floor','ceil','sqrt','sin','cos','min','max','pi'],
            'unavailable':['atan','atan2','asin','acos','pcall'],
            'angles':'Use finite normalized samples; reject near-zero norm, preserve vertical endpoints. Use bounded inverse-sin bisection with quadrant handling, not an inaccurate linear atan approximation.'}
    if layout in {'puzzle','platformer','racing','arcade','adventure'}:
        budgets=contract()['registry']['budgets']
        payload['grid_plan']={'cells':budgets['sdk_grid_cells_per_callback'],'pixels':budgets['sdk_grid_pixels_per_callback'],
            'calculation':'Sum(cols*rows)<=cells; sum(cols*rows*w*h)<=pixels per callback, including black cells. 10*20*8*8=200 cells/12800px.'}
    return '\nAuthoritative selected FIRE App SDK context (overrides legacy-only font/UI restrictions):\n' + json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
