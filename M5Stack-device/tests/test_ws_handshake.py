import json
import unittest
import test_native_guards as native

class WebSocketHandshakeTests(unittest.TestCase):
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
