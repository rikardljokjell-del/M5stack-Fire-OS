import zipfile

import pytest

from fire_backend.ai import MockProvider
from fire_backend.app_names import app_slug
from fire_backend.models import SessionStart
from fire_backend.service import Backend

from test_device_protocol import configured


@pytest.mark.parametrize("name, expected", [("Sprettsirkel", "sprettsirkel"), ("Snake", "snake"),
    ("Klokke på øya", "klokke-pa-oya"), ("../CON", "con-app"), ("ÆØÅ måler", "aeoa-maler"), ("///", "min-app")])
def test_short_portable_folder_names(name, expected):
    assert app_slug(name) == expected


class NamedProvider(MockProvider):
    name = "Klokke på øya"
    def __init__(self):
        self.previous = []

    async def generate(self, summary, context, error=None, previous=None):
        self.previous.append(previous)
        generated = await super().generate(summary, context, error, previous)
        return generated.model_copy(update={"name": self.name})


async def built(service, session):
    await service.text(session, "Lag en sirkel")
    await service.confirm_build(session, session.proposal_id)
    await session.task
    return service.store.get("packages", session.package_id)


async def test_folder_is_stable_across_versions_and_unique_between_apps(tmp_path):
    provider = NamedProvider()
    service = Backend(configured(tmp_path), provider)
    try:
        first = await service.start(SessionStart())
        package1 = await built(service, first)
        assert package1["manifest"]["id"] == "klokke-pa-oya" != first.project_id
        with zipfile.ZipFile(service.store.path("packages", package1["id"], ".zip")) as archive:
            assert set(archive.namelist()) == {"apps/klokke-pa-oya/"+p for p in ("manifest.json", "main.lua", "assets/", "appdata/")}
            original = archive.read("apps/klokke-pa-oya/main.lua").decode()
        provider.name = "Bedre klokke"
        package2 = await built(service, first)
        assert package2["manifest"]["id"] == package1["manifest"]["id"]
        assert package2["manifest"]["version"] == "0.1.2" and provider.previous[-1] == original
        await service.stop(first)
        provider.name = "Klokke på øya"
        second = await service.start(SessionStart())
        package3 = await built(service, second)
        assert package3["manifest"]["id"] == "klokke-pa-oya-2"
        assert service.store.get("projects", first.project_id)["app_id"] == "klokke-pa-oya"
    finally:
        await service.close()
