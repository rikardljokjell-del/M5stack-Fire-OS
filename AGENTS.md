# Instructions for this repository

## Scope and ownership
- All FIRE OS AI Developer backend work belongs in `M5Stack-backend/`.
- Use `M5Stack-backend/` for all future backend updates. Do not create another backend at the repository root or maintain the old flat layout.
- `M5Stack-device/` contains the user's device/firmware project. Read it for integration context, but do not add, edit, move, build, flash, or delete anything there unless the user explicitly authorizes device work.
- Root documentation may be updated to reflect the backend's actual status.

## Backend constraints
- Python 3.11+, FastAPI, Uvicorn, WebSocket, Pydantic, OpenAI Python SDK; local, one backend process, file-based storage.
- Use OpenAI directly. The running backend must not depend on the ChatGPT or Codex desktop app.
- Never put API keys in device messages, source control, packages or logs. `.env`, `.venv` and runtime `workspace/` stay local and ignored.
- Require explicit `build_confirm` with the current proposal ID and `run_confirm` with the tested package ID. Enforce this in backend code.
- AI apps use restricted Lua packages, never firmware binaries, OTA or arbitrary flashing.
- Keep inspected hardware/OS facts separate from physical runtime verification. Backend protocol/audio can be implemented without claiming that firmware implements them.
- Physical integration uses `M5Stack-backend/docs/PROTOCOL-v0.2.md` and `docs/LUA_API.md`. Keep code, schemas and those contracts consistent. PC simulation never establishes physical installation/running/current.

## Working and checking
- Run commands from `M5Stack-backend/`, or use the scripts there which select their own working directory.
- Offline start: `.\start.ps1 -Mock`; interactive client: `.\mock.ps1 -Demo`.
- Tests: `.\.venv\Scripts\python.exe -m pytest -q`.
- With a running mock server: `.\.venv\Scripts\python.exe scripts\smoke_test.py --all-examples`.
- Preserve tested packages and logs locally. Commit source, tests, documentation and configuration examples, not installed dependencies or runtime data.
- Keep `STATUS.md` truthful about mock versus live OpenAI verification and physical device support.

See `STATUS.md` for current delivery status and `M5Stack-backend/README.md` for details.
