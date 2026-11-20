import os

import uvicorn

from .app import create_app
from .config import Settings
from pydantic import ValidationError


def main():
    try:
        settings = Settings()
    except ValidationError:
        raise SystemExit("Invalid backend configuration. Check .env values, port, limits and LAN token.") from None
    lock_path = settings.fire_workspace.resolve() / "backend.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # OS advisory lock: stale files do not prevent restart; two writers cannot run.
    # a+b lets a second process open the file without truncating the locked byte.
    with lock_path.open("a+b") as lock:
        if lock_path.stat().st_size == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit("Another backend already uses this workspace. Stop it first.") from None
        uvicorn.run(create_app(settings), host=settings.fire_backend_host,
                    port=settings.fire_backend_port, workers=1, access_log=False, ws_max_size=8192,
                    log_level="info")


if __name__ == "__main__":
    main()
