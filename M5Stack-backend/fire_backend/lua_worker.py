"""Trusted Lua 5.4 validator/simulator; started with -I and a scrubbed environment.

No generated code is evaluated by Python. The Lua environment contains no
Python objects/callbacks, standard library loaders, filesystem or process APIs.
This is an interpreter capability boundary, not a full OS security sandbox.
"""
import json
import re
import sys

from lupa.lua54 import LuaRuntime


METHODS = {
    "display": {"clear", "circle", "rect", "line", "text"},
    "buttons": {"pressed"}, "rgb": {"set"}, "imu": {"accel"}, "time": {"millis"},
}
FORBIDDEN = {
    "python", "require", "package", "load", "loadfile", "dofile", "io", "os", "debug",
    "ffi", "collectgarbage", "getmetatable", "setmetatable", "rawget", "rawset",
    "pcall", "xpcall", "coroutine", "_G", "_ENV", "jit",
}


def without_literals(source):
    # Lua short strings, line comments and arbitrary-level long strings/comments.
    token = re.compile(r"--\[(=*)\[|\[(=*)\[|--[^\n]*|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", re.S)
    position = 0
    parts = []
    while match := token.search(source, position):
        parts.append(source[position:match.start()])
        end = match.end()
        if match.group(1) is not None or match.group(2) is not None:
            equals = match.group(1) if match.group(1) is not None else match.group(2)
            closing = source.find("]" + equals + "]", end)
            if closing < 0:
                raise ValueError("Unterminated Lua long string/comment")
            end = closing + len(equals) + 2
        parts.append(" ")
        position = end
    parts.append(source[position:])
    return "".join(parts)


def validate_api(source, services):
    clean = without_literals(source)
    banned = FORBIDDEN.intersection(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", clean))
    if banned:
        raise ValueError("Forbidden Lua capability: " + ", ".join(sorted(banned)))
    if re.search(r"\bfire\s*\[", clean):
        raise ValueError("Use explicit fire.service.method calls")
    for service, method in re.findall(r"\bfire\s*\.\s*(\w+)\s*[.:]\s*(\w+)", clean):
        if service not in services or method not in METHODS.get(service, set()):
            raise ValueError(f"Unknown or undeclared API fire.{service}.{method}")
    for service in re.findall(r"\bfire\s*\.\s*(\w+)", clean):
        if service not in services:
            raise ValueError(f"Undeclared service fire.{service}")


HARNESS = r'''
local source, services, memory_ms, frames = ...
local compile, hook = load, debug.sethook
local count, total, elapsed = 0, 0, 0
local trace, trace_count = {}, 0
local button = ""
local function integer(v, lo, hi)
  if type(v) ~= "number" or v ~= v or v < lo or v > hi then
    error("API argument outside bounds")
  end
end
local function record(name, ...)
  total = total + 1
  if total > 20000 then error("API operation budget exceeded") end
  if trace_count < 240 then
    trace_count = trace_count + 1
    trace[trace_count] = {name, ...}
  end
end
local function xy(x,y) integer(x,0,319); integer(y,0,239) end
local function color(c) integer(c,0,65535) end
local display = {
  clear = function(c) color(c); record("clear",c) end,
  circle = function(x,y,r,c) xy(x,y); integer(r,0,160); color(c); record("circle",x,y,r,c) end,
  rect = function(x,y,w,h,c) xy(x,y); integer(w,0,320); integer(h,0,240); color(c); record("rect",x,y,w,h,c) end,
  line = function(x,y,a,b,c) xy(x,y); xy(a,b); color(c); record("line",x,y,a,b,c) end,
  text = function(x,y,s,c)
    xy(x,y); color(c)
    if type(s) ~= "string" or #s > 80 then error("Text exceeds 80 bytes") end
    record("text",x,y,s,c)
  end
}
local available = {
  display = display,
  time = {millis=function() return elapsed end},
  rgb = {set=function(i,r,g,b)
    integer(i,0,9); integer(r,0,255); integer(g,0,255); integer(b,0,255)
    record("rgb",i,r,g,b)
  end},
  imu = {accel=function() return {x=math.sin(elapsed/1000),y=math.cos(elapsed/1000),z=1} end},
  buttons = {pressed=function(b)
    if b~="A" and b~="B" and b~="C" then error("Unknown button") end
    return b==button
  end}
}
local fire = {}
for service in services:gmatch("[a-z]+") do
  if not available[service] then error("Unsupported service") end
  fire[service] = available[service]
end
local env = {
  fire=fire, math={abs=math.abs,floor=math.floor,ceil=math.ceil,min=math.min,
    max=math.max,sqrt=math.sqrt,sin=math.sin,cos=math.cos,pi=math.pi},
  type=type,tonumber=tonumber,tostring=tostring,pairs=pairs,ipairs=ipairs,next=next
}
local function quota()
  count=count+1000
  if count>200000 then error("Instruction budget exceeded") end
end
local function call(fn, ...)
  count=0
  hook(quota,"",1000)
  fn(...)
  hook()
end
local program, syntax_error = compile(source,"main.lua","t",env)
if not program then error(syntax_error) end
call(program)
if type(env.init)~="function" or type(env.update)~="function" then
  error("App must define init() and update(dt_ms)")
end
if env.on_button~=nil and type(env.on_button)~="function" then error("Invalid on_button") end
call(env.init)
for frame=1,frames do
  elapsed=elapsed+16
  if elapsed>memory_ms then error("Runtime budget exceeded") end
  if frame%30==0 then
    button=({"A","B","C"})[(frame//30-1)%3+1]
    if env.on_button then call(env.on_button,button,"pressed") end
  elseif button~="" then
    if env.on_button then call(env.on_button,button,"released") end
    button=""
  end
  call(env.update,16)
end
return {frames=frames,elapsed_ms=elapsed,api_operations=total,trace=trace}
'''


def simulate(request):
    source = request["main_lua"]
    if len(source.encode("utf-8")) > 100000:
        raise ValueError("Lua source too large")
    services = request["required_services"]
    if not set(services) <= METHODS.keys():
        raise ValueError("Unsupported service")
    validate_api(source, services)
    lua = LuaRuntime(
        register_eval=False, register_builtins=False,
        max_memory=min(request.get("max_memory", 262144), 262144),
    )
    lua.compile(source, name="main.lua", mode="t")  # syntax only, never executes here
    result = lua.execute(HARNESS, source, ",".join(services), min(request.get("max_runtime_ms", 10000), 10000), 180)
    trace = []
    for i in range(1, len(result["trace"]) + 1):
        command = result["trace"][i]
        trace.append([command[j] for j in range(1, len(command) + 1)])
    return {"ok": True, "syntax": "passed", "api_validation": "passed",
            "frames": result["frames"], "elapsed_ms": result["elapsed_ms"],
            "api_operations": result["api_operations"], "trace": trace}


if __name__ == "__main__":
    try:
        request = json.loads(sys.stdin.buffer.read(110000))
        response = simulate(request)
    except BaseException as error:
        response = {"ok": False, "error": (type(error).__name__ + ": " + str(error))[:6000]}
    print(json.dumps(response, ensure_ascii=True, allow_nan=False))
    sys.exit(0 if response["ok"] else 1)
