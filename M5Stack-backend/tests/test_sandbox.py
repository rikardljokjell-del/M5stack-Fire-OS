from importlib.resources import files

import pytest

from fire_backend.lua_worker import simulate, without_literals


def request(source, services=None):
    return {"main_lua": source, "required_services": services or []}


def test_circle_moves():
    source = files("fire_backend").joinpath("data/circle.lua").read_text()
    result = simulate(request(source, ["display"]))
    circles = [c for c in result["trace"] if c[0] == "circle"]
    assert len({c[1] for c in circles}) > 20


@pytest.mark.parametrize("name,services,command", [
    ("snake", ["display", "buttons"], "rect"),
    ("rgb", ["rgb"], "rgb"),
    ("imu", ["display", "imu"], "line"),
])
def test_additional_prototypes(name, services, command):
    source = files("fire_backend").joinpath(f"data/{name}.lua").read_text()
    result = simulate(request(source, services))
    assert result["frames"] == 180
    assert any(c[0] == command for c in result["trace"])


@pytest.mark.parametrize("body", [
    "while true do end",
    "local t={} while true do t[#t+1]={1,2,3,4,5,6,7,8} end",
    "os.execute('echo unsafe')", "python.eval('1')", "require('io')",
    "debug.sethook()", "local env=_ENV", "pcall(function() while true do end end)",
    "fire.sd.read('../otherapp/key')", "fire.display.restart()",
    "fire.display.circle(999,120,20,2016)",
])
def test_forbidden_or_unbounded_code_rejected(body):
    with pytest.raises(Exception):
        simulate(request("function init() end\nfunction update(dt) " + body + " end", ["display"]))


def test_syntax_undeclared_api_and_missing_callback():
    for source in ("function init( end", "function init() end", "function init() fire.rgb.set(0,1,2,3) end function update(dt) end"):
        with pytest.raises(Exception):
            simulate(request(source, ["display"]))


def test_literals_and_comments_not_false_positives():
    source = '''-- require("os")
--[==[ debug.sethook() ]==]
local s = [=[_ENV python]=]
function init() fire.display.text(0,0,"os debug python",65535) end
function update(dt) end
'''
    assert simulate(request(source, ["display"]))["ok"]


def test_no_python_bridge_via_alias():
    with pytest.raises(Exception):
        simulate(request("local f=fire function init() f['python'].eval('1') end function update(dt) end"))
