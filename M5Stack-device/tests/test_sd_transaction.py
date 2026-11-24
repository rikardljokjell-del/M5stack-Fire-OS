import unittest
import test_native_guards as support


class SdTransactionTests(unittest.TestCase):
    def test_actual_sd_transaction_guards(self):
        output = support.NativeGuardTests.run_native(self, "native_sd_transaction.cpp")
        self.assertIn("PASS actual SD short-write/readback/publish guards", output)
