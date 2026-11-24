"""Compile and execute the actual portable firmware guards, without PlatformIO.

Run: python -m unittest discover -s tests -p test_native_guards.py -v
Requires g++, clang++, Zig, or an MSVC Developer Command Prompt. CXX may select
an executable path (including zig.exe); Zig runs its c++ subcommand. Build output is temporary; no firmware or dependency download
occurs. A missing host compiler is reported as SKIPPED, never as a passing test.
"""

import os
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

    def test_actual_cpp_guards(self):
        output = self.run_native("native_guards.cpp")
        self.assertIn("PASS queue counter overflow", output)
        self.assertIn("PASS queue SPSC concurrency", output)
        self.assertIn("PASS JSON preflight", output)

    def test_existing_native_core(self):
        self.assertIn("PASS native", self.run_native("native_core.cpp"))


if __name__ == "__main__":
    unittest.main()
