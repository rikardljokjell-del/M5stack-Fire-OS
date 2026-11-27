"""Compile and execute the actual portable firmware guards, without PlatformIO.

Run: python -m unittest discover -s tests -p test_native_guards.py -v
Requires g++, clang++, Zig, or an MSVC Developer Command Prompt. CXX may select
an executable path (including zig.exe); Zig runs its c++ subcommand. Build output is temporary; no firmware or dependency download
occurs. A missing host compiler is reported as SKIPPED, never as a passing test.
"""

import os
import json
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def host_compiler():
    selected = os.environ.get("CXX")
    if selected:
        executable = shutil.which(selected)
        if not executable:
            raise RuntimeError("CXX must name an available compiler executable")
        return executable
    for name in ("clang++", "g++", "c++", "cl", "zig"):
        executable = shutil.which(name)
        if executable:
            return executable
    for executable in sorted((ROOT / ".tools").glob("zig-*/zig.exe"), reverse=True):
        if executable.is_file():
            return str(executable)
    return None


class NativeGuardTests(unittest.TestCase):
    def test_evolution_and_ai_menu_guards(self):
        output=self.run_native("native_evolution_menu.cpp")
        self.assertIn("PASS Evolution bounded aggregates",output)
        self.assertIn("PASS actual AI menu renderer",output)
        self.assertIn("PASS cached update decisions",output)
        self.assertIn("PASS bounded catalog refresh",output)
        self.assertIn("PASS exact work status READY Done",output)

    def test_local_app_update_decision_is_cache_only(self):
        source=(ROOT/"src/fire_os_ai_picker.inc").read_text(encoding="utf-8")
        decision=source.split("bool FireOS::requestLuaAppOpen(",1)[1].split("void FireOS::handleAppUpdateButton",1)[0]
        for forbidden in ("appList(","appDownload(","connect(","requestWifi(","scanLuaApps(","SD.","preferences.","delay("):
            self.assertNotIn(forbidden,decision)
        self.assertIn("return startLuaApp(path,name,package);",decision)
        opened=source.split("void FireOS::openAiJob()",1)[1].split("void FireOS::restoreAiJob",1)[0]
        self.assertIn("luaRepairRequested_=false",opened)
        self.assertNotIn("confirmBuild(",opened)
        self.assertNotIn("buildResume(",opened)
        choices=source.split("void FireOS::handleAppUpdateButton",1)[1].split("void FireOS::drawAppUpdatePrompt",1)[0]
        download=choices.split("if(action==fire_app_updates::Action::Download)",1)[1]
        self.assertNotIn("userRunAfterInstall_=",download)
        self.assertNotIn("confirmRun(",download)

    def test_catalog_refresh_retains_rows_and_owner_scope(self):
        source=(ROOT/"src/fire_os.cpp").read_text(encoding="utf-8")
        refresh=source.split("void FireOS::updateAppManagerBackend()",1)[1].split("void FireOS::parseBackendAppCatalog",1)[0]
        self.assertIn("sessionReady()",refresh)
        self.assertIn("catalogTimeout(",refresh)
        self.assertNotIn("backendAppCount_=0",refresh)
        self.assertNotIn("requestWifi(",refresh)
        parser=source.split("void FireOS::parseBackendAppCatalog",1)[1].split("void FireOS::parseBackendAppVersions",1)[0]
        self.assertLess(parser.index("catalogReply("),parser.index("backendCatalogSeen_|="))
        self.assertLess(parser.index("if (!completed)"),parser.index("uint8_t write=0"))
        self.assertIn("fire_app_updates::seen(",parser)
        clear=source.split("void FireOS::clearBackendCatalog",1)[1].split("void FireOS::updateAppManagerBackend",1)[0]
        self.assertIn("backendAppCount_=0",clear)
        config=source.split("bool FireOS::saveBackendSetupFields",1)[1].split("void FireOS::",1)[0]
        self.assertIn("if (changed) clearBackendCatalog();",config)
        backend_state=source.split("void FireOS::backendState",1)[1].split("void FireOS::packageStatus",1)[0]
        self.assertNotIn("backendAppCount_",backend_state)
        button=(ROOT/"src/fire_os_ai_picker.inc").read_text(encoding="utf-8").split("void FireOS::handleAppUpdateButton",1)[1].split("void FireOS::drawAppUpdatePrompt",1)[0]
        self.assertIn("fire_app_updates::knownEpoch(",button)
        self.assertNotIn("60000",button)

    def test_button_capture_and_ui_cadence(self):
        output=self.run_native("native_input.cpp")
        self.assertIn("PASS actual button edge replay",output)
        self.assertIn("PASS dirty static redraw",output)

    def test_data_storage_guards(self):
        output=self.run_native("native_data_engine.cpp")
        self.assertIn("PASS data journal",output)
        self.assertIn("PASS data protected paths",output)

    def run_native(self, source_name):
        compiler = host_compiler()
        if compiler is None:
            self.skipTest("No C++ host compiler: install LLVM/GCC/Zig or use an MSVC Developer Command Prompt")
        source = ROOT / "tests" / source_name
        with tempfile.TemporaryDirectory(prefix="fire-native-guards-") as directory:
            output = Path(directory) / ("native_guards.exe" if os.name == "nt" else "native_guards")
            if Path(compiler).name.lower() in ("cl", "cl.exe", "clang-cl", "clang-cl.exe"):
                command = [compiler, "/nologo", "/std:c++17", "/EHsc", "/utf-8", "/W4", "/WX", "/O2", "/UNDEBUG",
                           "/I" + str(ROOT / "src"), str(source), "/Fe" + str(output),
                           "/Fo" + str(Path(directory) / "native_guards.obj")]
            else:
                is_zig = Path(compiler).stem.lower() == "zig"
                prefix = [compiler, "c++"] if is_zig else [compiler]
                if is_zig and os.name == "nt":
                    prefix += ["-target", "x86_64-windows-gnu"]
                threading = [] if is_zig and os.name == "nt" else ["-pthread"]
                command = prefix + ["-std=c++17", "-O2", "-UNDEBUG", "-Wall", "-Wextra", "-Werror", "-pedantic",
                           *threading, "-I", str(ROOT / "src"), str(source), "-o", str(output)]
            built = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=240)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            checked = subprocess.run([str(output)], cwd=directory, capture_output=True, text=True, timeout=90)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            return checked.stdout

    def test_start_receipt_source_binding(self):
        # Evaluate the production serializer's bounded field expression without
        # hardware/network stubs; missing wire identity must fail this guard.
        source = (ROOT / "src/fire_backend_client.cpp").read_text(encoding="utf-8")
        method = source.split("bool FireBackendClient::appStarted(", 1)[1].split(
            "bool FireBackendClient::appHealthy(", 1)[0]
        expression = method.split("String fields =", 1)[1].split(";", 1)[0]
        values = {"runId": 'run-"escaped', "packageId": "build-tested", "sourceHash": "a" * 64}
        tokens = re.findall(r'"(?:\\.|[^"\\])*"|jsonEscape\((?:runId|packageId|sourceHash)\)|\+|\s+', expression)
        self.assertEqual("".join(tokens), expression)
        fields = ""
        for token in tokens:
            if token.startswith('"'):
                fields += json.loads(token)
            elif token.startswith("jsonEscape("):
                fields += json.dumps(values[token[11:-1]])[1:-1]
        self.assertEqual(json.loads("{" + fields[1:] + "}"), {
            "run_id": values["runId"], "package_id": values["packageId"],
            "source_sha256": values["sourceHash"],
        })
        # Canonical receipts now share one checked sending path. Both actual
        # launch/bind branches and an explicit duplicate must reach that path
        # with the current verified VM identity; centralization is not a reason
        # to weaken the source binding or permit a second VM launch.
        self.assertIn('fire_lua_install::hash(sourceHash.c_str())', method)
        self.assertIn('fields.concat(sourceHash.c_str())', method)
        os_source = (ROOT / "src/fire_os.cpp").read_text(encoding="utf-8")
        service = os_source.split('void FireOS::serviceLuaRunStatus()', 1)[1].split(
            'void FireOS::updateLuaApp()', 1)[0]
        calls = re.findall(r'appStarted\(\s*luaRunId_\s*,\s*luaPackageId_\s*,\s*([^,)]+)', service)
        self.assertEqual(calls, ["luaSourceHash_"])
        self.assertIn('luaRunId_!=entry.id', service)
        self.assertIn('luaPackageId_!=entry.package', service)
        self.assertIn('luaSourceHash_!=entry.source', service)
        self.assertIn('backendClient_->sessionId()!=delivery.session', service)
        self.assertIn('backendClient_->bootId()!=delivery.boot', service)
        run = os_source.split('if (type == "run_request")', 1)[1].split(
            'if (type == "stop_request")', 1)[0]
        duplicate = run.split('if(admission==fire_run_receipts::Admission::Duplicate)', 1)[1].split(
            'String path;', 1)[0]
        self.assertIn('luaSourceHash_==commandSource', duplicate)
        self.assertIn('luaRunDelivery_.duplicate();serviceLuaRunStatus();', duplicate)
        self.assertNotIn('startLuaApp(', duplicate)
        self.assertEqual(run.count('if(bindLuaRunStatus(receipt)) serviceLuaRunStatus();'), 2)
        self.assertIn('validSha256Hex(commandSource) && luaSourceHash_==commandSource', run)
        self.assertIn('resolveLuaPackage(packageId,commandHash,commandSource,path)', run)
        self.assertIn('startLuaApp(path, sdBaseName(path), packageId,commandSource)', run)
        self.assertLess(run.index('resolveLuaPackage('), run.index('startLuaApp('))

    def test_actual_cpp_guards(self):
        output = self.run_native("native_guards.cpp")
        self.assertIn("PASS queue counter overflow", output)
        self.assertIn("PASS queue SPSC concurrency", output)
        self.assertIn("PASS JSON preflight", output)

    def test_existing_native_core(self):
        self.assertIn("PASS native", self.run_native("native_core.cpp"))


if __name__ == "__main__":
    unittest.main()
