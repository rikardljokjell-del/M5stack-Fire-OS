"""Run the actual device Lua runtime with host-only clock/allocator adapters."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_native_guards as support


class AppRuntimeTests(unittest.TestCase):
    def test_actual_lua32_runtime(self):
        compiler = support.host_compiler()
        if compiler is None:
            self.skipTest("No host C++ compiler")
        name = Path(compiler).stem.lower()
        if name in {"cl", "clang-cl"}:
            self.skipTest("Lua multi-source host test requires GCC/Clang/Zig")
        prefix = [compiler, "c++"] if name == "zig" else [compiler]
        if name == "zig" and os.name == "nt":
            prefix += ["-target", "x86_64-windows-gnu"]
        root = support.ROOT
        lua = root / "lib/lua54/src"
        excluded = {"lua.c", "luac.c", "linit.c", "lbaselib.c", "lmathlib.c", "ldo.c", "ldblib.c",
                    "liolib.c", "loadlib.c", "loslib.c", "lstrlib.c", "ltablib.c", "lutf8lib.c", "lcorolib.c"}
        sources = sorted(p for p in lua.glob("*.c") if p.name not in excluded)
        sources += [lua / "ldo.cpp", root / "src/fire_lua_runtime.cpp", root / "tests/native_app_runtime.cpp"]
        common = ["-O1", "-UNDEBUG", "-DLUA_32BITS=1", "-DLUA_USE_C89=1", "-I", str(lua),
                  "-I", str(root / "tests/host_runtime"), "-I", str(root / "src")]
        with tempfile.TemporaryDirectory(prefix="fire-lua32-sdk-") as directory:
            objects = []
            for index, source in enumerate(sources):
                output = Path(directory) / f"{index}.o"
                language = ["-x", "c", "-std=c99"] if source.suffix == ".c" else ["-std=c++17"]
                built = subprocess.run(prefix + common + language + ["-c", str(source), "-o", str(output)],
                                       capture_output=True, text=True, timeout=90)
                self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                objects.append(str(output))
            executable = Path(directory) / ("runtime.exe" if os.name == "nt" else "runtime")
            linked = subprocess.run(prefix + objects + ["-o", str(executable), "-lm"],
                                    capture_output=True, text=True, timeout=90)
            self.assertEqual(linked.returncode, 0, linked.stdout + linked.stderr)
            try:
                fixtures = root.parent / "M5Stack-backend/fire_backend/data/app_sdk"
                checked = subprocess.run([str(executable), str(fixtures)], capture_output=True, text=True, timeout=90)
            except OSError as error:
                if getattr(error, "winerror", None) == 4551:
                    self.skipTest("Compiled/linked; Windows Application Control blocked runtime (4551); Linux CI must execute")
                raise
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            print(checked.stdout, end="")  # Sanitized host VM/raster observations for CI review.
            self.assertIn("PASS production Lua32 SDK", checked.stdout)
            self.assertIn("PASS canonical SDK gallery six pages", checked.stdout)
