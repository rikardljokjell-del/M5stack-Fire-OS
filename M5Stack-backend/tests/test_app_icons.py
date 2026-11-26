import json
from importlib.resources import files

import pytest

from fire_backend.app_icons import ALLOWED_ICONS, select_icon, valid_icon


@pytest.mark.parametrize('name,expected', [
    ('Luna-stoppeklokke','timer'), ('Kalkulator','calculator'), ('Prikkjakt','crosshair'),
    ('AI Oppdrag GC test','crosshair'), ('Vær','cloud-sun'), ('STRØM','zap'),
    ('Måledata kontroll','activity'), ('Home','house'), ('Bluetooth lys','lightbulb'),
    ('Vibrasjonsanalyse','activity'), ('Loggbok','file-text'), ('Slange spill','gamepad-2'),
])
def test_existing_names_have_appropriate_icons(name, expected):
    assert select_icon(name)=='icon.'+expected


def test_known_icon_preserved_and_untrusted_paths_never_used():
    assert select_icon('Stopwatch','',base_icon='icon.house')=='icon.house'
    assert select_icon('Stopwatch','',base_icon='icon.house',proposed_icon='icon.timer')=='icon.timer'
    assert select_icon('Unknown','measure vibration',proposed_icon='../../secret')=='icon.activity'
    assert select_icon('Unknown',proposed_icon='<script>')=='icon.code'
    assert not valid_icon(None) and not valid_icon('icon.not-a-real-icon')


def test_every_icon_is_an_existing_sdk_asset_and_rules_are_shared():
    assets=json.loads(files('fire_backend').joinpath('data/app_sdk/assets.json').read_text())['assets']
    assert set(ALLOWED_ICONS)<={a['id'] for a in assets}
    from scripts.build_app_icons import generate, HEADER
    assert HEADER.read_text(encoding='utf-8')==generate()
