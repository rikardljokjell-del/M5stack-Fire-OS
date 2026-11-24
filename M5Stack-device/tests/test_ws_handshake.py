import unittest
import test_native_guards as native

class WebSocketHandshakeTests(unittest.TestCase):
    def test_actual_upgrade_validator(self):
        output = native.NativeGuardTests().run_native("native_ws_handshake.cpp")
        self.assertIn("PASS strict WebSocket", output)

if __name__ == "__main__": unittest.main()
