import unittest
import test_native_guards as native


class FirmwareHttpTests(unittest.TestCase):
    def test_actual_response_validator(self):
        output = native.NativeGuardTests().run_native("native_firmware_http.cpp")
        self.assertIn("PASS strict firmware HTTP", output)


if __name__ == "__main__":
    unittest.main()
