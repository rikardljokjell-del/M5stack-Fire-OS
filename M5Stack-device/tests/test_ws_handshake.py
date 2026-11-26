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
#include "fire_package_delivery.h"
using fire_backend_policy::ConnectFailure;
constexpr ConnectFailure empty;
constexpr ConnectFailure failed(768,-1,5800,2);
static_assert(empty.phase==0 && empty.error==0 && empty.elapsedMs==0 && empty.attempt==0,"default");
static_assert(failed.phase==768 && failed.error==-1 && failed.elapsedMs==5800 && failed.attempt==2,"fields");
static_assert(sizeof(ConnectFailure)==16,"bounded snapshot");
void assign(ConnectFailure& value) { value={}; value={768,-1,5800,2}; }
void delivery() { fire_package_delivery::Gate gate; gate.begin(1,true); (void)gate.poll(1,true,false,true,false,false,false); }
""",encoding="utf-8")
            command=prefix+["-std=c++11","-Wall","-Wextra","-Werror","-pedantic",
                            "-I",str(native.ROOT/"src"),"-c",str(source),"-o",str(Path(directory)/"policy.o")]
            result=subprocess.run(command,capture_output=True,text=True,timeout=90)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_package_install_receipt_ownership(self):
        manager=(native.ROOT/"src/fire_lua_package_manager.cpp").read_text(encoding="utf-8")
        self.assertNotIn("completed.exchange(false)",manager)
        service=manager.split("void FireLuaPackageManager::service(",1)[1].split("void FireLuaPackageManager::task",1)[0]
        self.assertIn("client_.running(),io_.completed",service)
        self.assertLess(service.index("resultCallback_("),service.index("receiptFrozen_=true"))
        self.assertIn("Action::Start) startWorker()",service)
        os_source=(native.ROOT/"src/fire_os.cpp").read_text(encoding="utf-8")
        callback=os_source.split("void FireOS::packageResult(",1)[1].split("void FireOS::servicePackageInstall",1)[0]
        self.assertIn('amendOutcome(false,"metadata_error")',callback)
        self.assertNotIn("deviceInstallResult(",callback)
        self.assertNotIn("confirmRun(",callback)
        delivery=os_source.split("void FireOS::servicePackageInstall",1)[1].split("bool FireOS::handlePackageReceipt",1)[0]
        self.assertLess(delivery.index("admittedScope("),delivery.index("packageManager_->service("))
        self.assertIn("backendClient_->networkIdle()",delivery)
        self.assertIn("homeApp_.networkIdle()",delivery)
        self.assertIn("packageManager_->receiptEvent()",delivery)
        self.assertIn("backendCommandUnexpired(packageManager_->installExpiry())",delivery)
        final=os_source.split("void FireOS::finishPackageReceipt",1)[1].split("void FireOS::firmwareStatus",1)[0]
        self.assertIn("const bool ok=recorded && packageManager_->outcomeOk();",final)
        self.assertIn("package==userRunAfterInstall_",final)
        self.assertIn("if (ok && backendClient_ && backendClient_->confirmRun(package))",final)
        binding=os_source.split("else if(!luaAiBindSent_",1)[1].split("luaAiBindSent_=",1)[0]
        self.assertIn("!(packageManager_ && packageManager_->busy())",binding)

    def test_actual_package_preconnect_handoff(self):
        source=(native.ROOT/"src/fire_lua_package_manager.cpp").read_text(encoding="utf-8")
        spawn=source.split("void FireLuaPackageManager::startWorker()",1)[1].split("void FireLuaPackageManager::service(",1)[0]
        self.assertLess(spawn.index("handoffReady("),spawn.index("xTaskCreate("))
        self.assertIn('xTaskCreate(task,"fire-package",16384',spawn)
        waiting=source.split("void FireLuaPackageManager::preconnect()",1)[1].split("void FireLuaPackageManager::startWorker",1)[0]
        self.assertIn("client_.connect(",waiting)
        self.assertNotIn("xTaskCreate(",waiting)
        worker=source.split("void FireLuaPackageManager::serviceWorker",1)[1]
        handoff=worker.split("if (preconnectedTls_)",1)[1].split("else if (!reverseClient_)",1)[0]
        self.assertNotIn("connect(",handoff)
        self.assertIn("handoffReady(",handoff)
        failure=source.split("void FireLuaPackageManager::queuedFailure",1)[1].split("String FireLuaPackageManager::connectionFailure",1)[0]
        self.assertLess(failure.index("client_.stop()"),failure.index("Phase::Cleanup"))

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
        self.assertIn("PASS package exclusive worker barriers",output)
        self.assertIn("PASS TLS-before-package allocation ordering",output)
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
