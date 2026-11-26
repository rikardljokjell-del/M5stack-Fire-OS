import subprocess
import sys
import unittest
from pathlib import Path

import test_native_guards as native


class AppIconsTests(unittest.TestCase):
    def test_shared_selector_and_actual_icons(self):
        out=native.NativeGuardTests.run_native(self,'native_app_icons.cpp')
        self.assertIn('PASS shared app icons',out)

    def test_shared_generated_header(self):
        backend=Path(__file__).resolve().parents[2]/'M5Stack-backend'
        subprocess.run([sys.executable,str(backend/'scripts/build_app_icons.py'),'--check'],check=True)


if __name__=='__main__':unittest.main()
