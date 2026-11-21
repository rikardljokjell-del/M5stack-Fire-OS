"""Executable entry: a GUI normally, a restricted child worker with --lua-worker."""
import json
from pathlib import Path
import sys


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--lua-worker":
        from fire_backend.lua_worker import simulate
        try:
            path = Path(sys.argv[2])
            if path.stat().st_size > 220000:
                raise ValueError("Worker input exceeds limit")
            result = simulate(json.loads(path.read_text(encoding="utf-8")))
        except BaseException as error:
            result = {"ok": False, "error": (type(error).__name__ + ": " + str(error))[:6000]}
        Path(sys.argv[3]).write_text(json.dumps(result, ensure_ascii=True, allow_nan=False), encoding="utf-8")
        raise SystemExit(0 if result["ok"] else 1)
    from fire_backend.desktop_ui import main as ui_main
    ui_main()


if __name__ == "__main__":
    main()
