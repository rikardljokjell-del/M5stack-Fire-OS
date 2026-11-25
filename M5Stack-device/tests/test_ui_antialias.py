import json
from pathlib import Path
import subprocess
import sys
import unittest
import test_native_guards as native

ROOT = Path(__file__).resolve().parents[1]


class UiAntialiasTests(unittest.TestCase):
    def test_native_renderer(self):
        output = native.NativeGuardTests.run_native(self, 'native_ui_antialias.cpp')
        self.assertIn('PASS coverage blend', output)

    def test_generated_and_unchanged_font_metrics(self):
        subprocess.run([sys.executable, str(ROOT/'tools/build_ui_antialias.py'), '--check'], check=True)
        aa = json.loads((ROOT/'ui/fire_ui_aa.json').read_text(encoding='utf-8'))
        sdk = json.loads((ROOT.parent/'M5Stack-backend/fire_backend/data/app_sdk/fonts.json').read_text(encoding='utf-8'))['fonts']
        for name, font in aa['fonts'].items():
            if name == 'small10':
                continue
            self.assertEqual(font['line_height'], sdk[name]['line_height'])
            for cp, g in font['glyphs'].items():
                for field in ('width','height','advance','x_offset','y_offset'):
                    self.assertEqual(g[field], sdk[name]['glyphs'][cp][field])


if __name__ == '__main__':
    unittest.main()
