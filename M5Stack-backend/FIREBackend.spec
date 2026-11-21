# Reproducible Windows directory bundle; keep _internal beside FIREBackend.exe.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

data = collect_data_files('fire_backend')
for dependency in ('openai', 'lupa', 'pydantic'):
    data += copy_metadata(dependency)

a = Analysis(['fire_backend/desktop_entry.py'], pathex=['.'], binaries=[], datas=data,
             hiddenimports=collect_submodules('uvicorn') + ['lupa.lua54', 'websockets.asyncio.client'],
             hookspath=[], runtime_hooks=[], excludes=['pytest', 'IPython', 'notebook'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='FIREBackend', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          disable_windowed_traceback=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='FIREBackend')
