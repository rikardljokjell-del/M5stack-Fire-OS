"""Small shared OS app-icon vocabulary; no extra model call or image assets."""
import json
from importlib.resources import files

RULES = json.loads(files('fire_backend').joinpath('data/app_icons.json').read_text(encoding='utf-8'))
ALLOWED_ICONS = tuple(dict.fromkeys([RULES['fallback'], *(r['icon'] for r in RULES['rules'])]))


def valid_icon(value):
    return isinstance(value, str) and value in ALLOWED_ICONS


def _normalise(value):
    # Kept identical to the bounded native fallback, including Nordic names.
    nordic = {'æ': 'ae', 'Æ': 'ae', 'ø': 'o', 'Ø': 'o', 'å': 'a', 'Å': 'a'}
    text = ''.join(nordic.get(c, c.lower() if c.isascii() and c.isalnum() else ' ')
                   for c in str(value or '')[:256])
    return ' '.join(text.split())[:255]


def select_icon(name, summary='', base_icon=None, proposed_icon=None):
    """An explicit supported icon wins; updates otherwise preserve their icon."""
    for icon in (proposed_icon, base_icon):
        if valid_icon(icon):
            return icon
    for value in (name, summary):
        text = _normalise(value)
        for rule in RULES['rules']:
            if any(text.startswith(word) or ' '+word in text for word in rule['keywords']):
                return rule['icon']
    return RULES['fallback']
