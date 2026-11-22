from importlib.resources import files

import pytest

from fire_backend.ai import MockProvider
from fire_backend.builds import validate_release
from fire_backend.quality import failure_class, require_deliverable
from fire_backend.rendering import VISUAL_POLICY
from fire_backend.security import Redactor
from fire_backend.service import Backend
from fire_backend.storage import Store
from test_device_protocol import configured
from test_quality import pc_package


DRAW = "fire.display.circle(40,40,8,2016)"


@pytest.mark.parametrize("source", [
    f"function init() {DRAW} end function update(dt) end",
    f"local t=0 function init() end function update(dt) t=t+dt if t<160 then return end t=0 {DRAW} end",
    f"local n=0 function init() end function update(dt) n=n+1 if n%2==0 then {DRAW} end end",
    f"local t=0 function init() end function update(dt) t=t+dt if t>5000 then return end {DRAW} end",
    f"function init() end function update(dt) if fire.buttons.pressed('A') then return end {DRAW} end",
    f"function init() end function update(dt) {DRAW} fire.display.clear(0) end",
    f"function init() end function update(dt) local d=fire.display d.clear(0) d.clear(0) {DRAW} end",
    f"function init() end function update(dt) {DRAW} end function on_button(b,a) {DRAW} end",
    "function init() end function update(dt) fire.display.circle(5,5,20,2016) end",
    "function init() end function update(dt) fire.display.rect(315,10,20,20,2016) end",
    "function init() end function update(dt) fire.display.text(300,10,'Too long',2016) end",
    "function init() end function update(dt) fire.display.text(10,238,'Low',2016) end",
])
async def test_release_rejects_disappearing_and_incoherent_frames(tmp_path, source):
    store=Store(tmp_path,Redactor(),10_000_000)
    with pytest.raises(ValueError,match="Visual frame"):
        await validate_release({"main_lua":source,"required_services":["display","buttons"]},store,"visual-bad")


@pytest.mark.parametrize("kind,services",[("circle",["display"]),("snake",["display","buttons"]),("imu",["display","imu"])])
async def test_examples_draw_every_frame_in_all_input_profiles(tmp_path,kind,services):
    source=files("fire_backend").joinpath(f"data/{kind}.lua").read_text()
    result=await validate_release({"main_lua":source,"required_services":services,"max_runtime_ms":0},Store(tmp_path,Redactor(),10_000_000),"visual-good")
    assert result["rendering_contract"]=="cleared-sprite-v1"
    assert all(p["min_update_draws"]>=1 and p["update_count"]==p["frames"] for p in result["profiles"])
    assert all(p["max_callback_operations"]<=24 and p["max_callback_clears"]<=1 for p in result["profiles"])


async def test_bad_rendering_is_corrected_before_any_package_is_delivered(tmp_path):
    class Provider(MockProvider):
        calls=0
        async def generate(self,summary,context,error=None,previous=None):
            assert VISUAL_POLICY in context
            self.calls+=1
            good=await super().generate(summary,context,error,previous)
            if self.calls==1:
                return good.model_copy(update={"main_lua":f"function init() {DRAW} end function update(dt) end"})
            assert "Visual frame" in error and "function update(dt) end" in previous
            return good
    provider=Provider();service=Backend(configured(tmp_path),provider)
    try:
        s,package=await pc_package(service)
        assert provider.calls==2 and len(service.store.list("packages"))==1
        assert package["validation"]["suite"]=="release-v4"
        assert any(c["category"]=="rendering" for c in service.quality.cases(s.project_id))
        assert "EVERY update" in service.quality.policy()
    finally:await service.close()


def test_prior_release_does_not_bypass_new_visual_checks():
    with pytest.raises(ValueError):require_deliverable({"validation":{"suite":"release-v2"}})
    assert failure_class("Skjermen flimrer") == "rendering"
