import unittest
import test_native_guards as support


class FirmwareStagingTests(unittest.TestCase):
    def test_actual_staging_and_sd_phase_guards(self):
        output = support.NativeGuardTests.run_native(self, "native_firmware_staging.cpp")
        self.assertIn("PASS actual firmware PSRAM bounds and TLS/SD phase guards", output)
