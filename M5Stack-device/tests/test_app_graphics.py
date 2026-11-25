import unittest
import test_native_guards as support


class AppGraphicsTests(unittest.TestCase):
    def test_native_raster_helpers(self):
        output = support.NativeGuardTests.run_native(self, "native_app_graphics.cpp")
        self.assertIn("PASS native graphics clipping, gradients, polygons and legacy grid equivalence", output)

    def test_native_bitmap_reader(self):
        output = support.NativeGuardTests.run_native(self, "native_app_bitmap.cpp")
        self.assertIn("PASS bitmap font UTF-8 metrics", output)
