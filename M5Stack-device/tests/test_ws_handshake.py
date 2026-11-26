import json
import re
import unittest
import test_native_guards as native

class WebSocketHandshakeTests(unittest.TestCase):
    def test_worker_tls_deadline_preserves_tcp_and_trust(self):
        source=(native.ROOT/"src/fire_async_client.cpp").read_text(encoding="utf-8")
        constant=re.search(r"constexpr unsigned long kTlsHandshakeSeconds = ([0-9]+);",source)
        self.assertIsNotNone(constant)
        # Bounded causal candidate for measured state17 timeouts; never an
        # unbounded/default handshake or a change to TCP/CA authentication.
        self.assertGreater(int(constant[1]),5)
        self.assertLessEqual(int(constant[1]),12)
        self.assertIn("tls.setHandshakeTimeout(kTlsHandshakeSeconds);",source)
        self.assertRegex(source,r"tls\.connect\(host_,\s*port_,\s*5000\)")
        self.assertIn("tls.useSharedBundle();",source)
        self.assertNotIn("setInsecure(",source)
        self.assertIn("FIRE net_ready connect_ms=%lu",source)

    def test_actual_upgrade_validator(self):
        output = native.NativeGuardTests().run_native("native_ws_handshake.cpp")
        self.assertIn("PASS strict WebSocket", output)
        self.assertIn("PASS async connect polling",output)
        self.assertIn("PASS actual session/app/mode producers",output)
        rows=[json.loads(line.split(" ",1)[1]) for line in output.splitlines() if line.startswith("SELECTION_JSON ")]
        self.assertEqual(len(rows),6)
        self.assertEqual(rows[0],{"event":"session_start","resume_session_id":"old-session"})
        self.assertEqual(rows[1],{"event":"app_select","app_mode":"new"})
        self.assertEqual(rows[2],{"event":"app_select","app_mode":"update","project_id":"project-two","base_package_id":"package-two"})
        self.assertEqual(rows[3],{"event":"session_start","resume_session_id":"old-session","development_context_id":"context-exact"})
        self.assertEqual(rows[4],{"event":"mode_select","conversation_mode":"chat"})
        self.assertEqual(rows[5]["project_id"],'a"\\\n\r\t')

if __name__ == "__main__": unittest.main()
