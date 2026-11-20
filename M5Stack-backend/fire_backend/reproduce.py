"""Revalidate frozen source and reproduce the exact package without OpenAI."""
import argparse
import asyncio
import json

from .builds import sha256, simulate, verify_archive, write_archive
from .config import Settings
from .security import Redactor
from .storage import Store, identifier


async def reproduce(build_id):
    settings = Settings()
    store = Store(settings.fire_workspace, Redactor(settings.openai_api_key.get_secret_value()), settings.fire_max_workspace_mb * 1024 * 1024)
    identifier(build_id)
    folder = store.path("builds", build_id, "")
    metadata = json.loads((folder / "build-manifest.json").read_text(encoding="utf-8"))
    source = (folder / "main.lua").read_bytes()
    if sha256(source) != metadata["manifest"]["checksum"]:
        raise ValueError("Frozen source checksum mismatch")
    await simulate({"main_lua": source.decode("utf-8"), **metadata["manifest"]}, store, build_id)
    output = folder / "reproduced.zip"
    store.reserve(metadata["size_bytes"])
    write_archive(output, metadata["manifest"], source)
    verify_archive(output, metadata["manifest"], metadata["archive_sha256"])
    print(json.dumps({"status": "identical", "archive_sha256": metadata["archive_sha256"], "path": str(output)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("build_id")
    asyncio.run(reproduce(parser.parse_args().build_id))
