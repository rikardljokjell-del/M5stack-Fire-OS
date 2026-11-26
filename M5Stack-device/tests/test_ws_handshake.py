import json
import os
from pathlib import Path
import subprocess
import tempfile
import re
import unittest
import test_native_guards as native

class WebSocketHandshakeTests(unittest.TestCase):
    def test_connect_failure_cpp11_construction(self):
        compiler=native.host_compiler()
        if compiler is None:
            self.skipTest("No C++ host compiler")
        if Path(compiler).stem.lower() in ("cl","clang-cl"):
            self.skipTest("This compiler has no strict C++11 language mode")
        zig=Path(compiler).stem.lower()=="zig"
        prefix=[compiler,"c++"] if zig else [compiler]
        if zig and os.name=="nt":
            prefix += ["-target","x86_64-windows-gnu"]
        with tempfile.TemporaryDirectory(prefix="fire-cpp11-policy-") as directory:
            source=Path(directory)/"policy.cpp"
            source.write_text("""#include "fire_backend_policy.h"
using fire_backend_policy::ConnectFailure;
constexpr ConnectFailure empty;
constexpr ConnectFailure failed(768,-1,5800,2);
static_assert(empty.phase==0 && empty.error==0 && empty.elapsedMs==0 && empty.attempt==0,"default");
static_assert(failed.phase==768 && failed.error==-1 && failed.elapsedMs==5800 && failed.attempt==2,"fields");
static_assert(sizeof(ConnectFailure)==16,"bounded snapshot");
void assign(ConnectFailure& value) { value={}; value={768,-1,5800,2}; }
""",encoding="utf-8")
            command=prefix+["-std=c++11","-Wall","-Wextra","-Werror","-pedantic",
                            "-I",str(native.ROOT/"src"),"-c",str(source),"-o",str(Path(directory)/"policy.o")]
            result=subprocess.run(command,capture_output=True,text=True,timeout=90)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

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
