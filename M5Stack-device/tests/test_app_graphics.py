import unittest
import test_native_guards as support


class AppGraphicsTests(unittest.TestCase):
    def test_native_canvas_fill(self):
        output = support.NativeGuardTests.run_native(self, "native_canvas_fill.cpp")
        self.assertIn("PASS canvas raw16 all65536 colors", output)

    def test_native_raster_helpers(self):
        output = support.NativeGuardTests.run_native(self, "native_app_graphics.cpp")
        self.assertIn("PASS native graphics clipping, gradients, polygons and legacy grid equivalence", output)

    def test_native_bitmap_reader(self):
        output = support.NativeGuardTests.run_native(self, "native_app_bitmap.cpp")
        self.assertIn("PASS bitmap font UTF-8 metrics", output)
