"""PlatformIO builds are allowed; signed USB migration owns initial flashing."""
Import("env")  # noqa: F821 - supplied by PlatformIO/SCons

def refuse_raw_upload(*args, **kwargs):
    raise RuntimeError(
        "Raw PlatformIO upload would replace the recovery-aware bootloader/table. "
        "Use the verified signed migration bundle and M5Stack-backend/scripts/migrate_fire.py. "
        "Later OS updates use the device signed GitHub/SD OTA flow."
    )

env.AddPreAction("upload", refuse_raw_upload)  # noqa: F821
env.AddPreAction("uploadfs", refuse_raw_upload)  # noqa: F821
