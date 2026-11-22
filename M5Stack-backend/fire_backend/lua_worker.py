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
local source, services, memory_ms, frames, profile, operation_limit = ...
local compile, hook = load, debug.sethook
local count, total, elapsed = 0, 0, 0
local callback_ops, callback_work, peak_ops, peak_work = 0,0,0,0
local callback_phase, clear_count, visible_ops, background = "",0,0,0
local min_update_draws, update_count, peak_clears = nil,0,0
local frames_run = 0
local has_display = services:match("display") ~= nil
local trace, trace_count = {}, 0
local button = ""
local function integer(v, lo, hi)
  if type(v) ~= "number" or v ~= v or v < lo or v > hi then
    error("API argument outside bounds")
  end
end
local function whole(v, lo, hi)
  integer(v,lo,hi)
  if math.floor(v)~=v then error("API argument must be an integer") end
end
local function record(name, ...)
  total = total + 1
  callback_ops=callback_ops+1
  local a,b,c,d=...
  if profile and has_display and callback_phase=="on_button" and name~="rgb" then
    error("Visual frame: on_button must change state only; render in update")
  end
  if name=="clear" then
    clear_count=clear_count+1
    peak_clears=math.max(peak_clears,clear_count)
    if profile and (clear_count>1 or visible_ops>0) then
      error("Visual frame: clear at most once BEFORE drawing; never erase a completed scene")
    end
    background=a
    visible_ops=0
  elseif name~="rgb" then
    local ink = name=="text" and d or (name=="circle" and d or select(5,...))
    if ink~=background and (name~="text" or #c>0) then visible_ops=visible_ops+1 end
  end
  local work=0
  if name=="clear" then work=76800
  elseif name=="rect" then work=2*(c+d)
  elseif name=="line" then work=math.max(math.abs(c-a),math.abs(d-b))+1
  elseif name=="circle" then work=math.ceil(7*c)
  elseif name=="text" then work=#c*48 end
  callback_work=callback_work+work
  peak_ops=math.max(peak_ops,callback_ops)
  peak_work=math.max(peak_work,callback_work)
  if profile and (callback_ops>24 or callback_work>120000) then
    error("Per-callback display work budget exceeded; simplify the complete scene, never split a visible frame")
  end
  if total > operation_limit then error("API operation budget exceeded") end
  if trace_count < 240 then
    trace_count = trace_count + 1
    trace[trace_count] = {name, ...}
  end
end
local function xy(x,y) whole(x,0,319); whole(y,0,239) end
local function color(c) whole(c,0,65535) end
local display = {
  clear = function(c) color(c); record("clear",c) end,
  circle = function(x,y,r,c)
    xy(x,y); whole(r,0,160); color(c)
    if profile and (x-r<0 or x+r>319 or y-r<0 or y+r>239) then error("Visual frame: circle clipped by screen bounds") end
    record("circle",x,y,r,c)
  end,
  rect = function(x,y,w,h,c)
    xy(x,y); whole(w,0,320); whole(h,0,240); color(c)
    if profile and (x+w>320 or y+h>240 or w==0 or h==0) then error("Visual frame: rectangle clipped or empty") end
    record("rect",x,y,w,h,c)
  end,
  line = function(x,y,a,b,c) xy(x,y); xy(a,b); color(c); record("line",math.floor(x),math.floor(y),math.floor(a),math.floor(b),c) end,
  text = function(x,y,s,c)
    xy(x,y); color(c)
    if type(s) ~= "string" or #s > 80 then error("Text exceeds 80 bytes") end
    if profile and (x+#s*6>320 or y+8>240 or s:find("[\r\n\t]")) then
      error("Visual frame: text clipped or multiline; use short labels with a conservative 6x8 font footprint")
    end
    record("text",math.floor(x),math.floor(y),s,c)
  end
}
local available = {
  display = display,
  time = {millis=function() return 60000+elapsed end},
  rgb = {set=function(i,r,g,b)
    whole(i,0,9); whole(r,0,255); whole(g,0,255); whole(b,0,255)
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
  if count>(profile and 20000 or 200000) then error("Instruction budget exceeded") end
end
local function call(fn, ...)
  count=0
  callback_ops,callback_work=0,0
  clear_count,visible_ops,background=0,0,0
  hook(quota,"",1000)
  fn(...)
  hook()
  if profile and has_display and callback_phase=="update" then
    update_count=update_count+1
    min_update_draws=math.min(min_update_draws or visible_ops,visible_ops)
    if visible_ops==0 then
      error("Visual frame: no visible output in update; FIRE clears its sprite each frame. Render the complete scene on EVERY update, including paused, game-over and between simulation ticks")
    end
  end
end
local program, syntax_error = compile(source,"main.lua","t",env)
if not program then error(syntax_error) end
call(program)
if type(env.init)~="function" or type(env.update)~="function" then
  error("App must define init() and update(dt_ms)")
end
if env.on_button~=nil and type(env.on_button)~="function" then error("Invalid on_button") end
callback_phase="init"
call(env.init)
for frame=1,frames do
  local dt=16
  if profile=="jitter" then dt=({7,16,33,80,120})[(frame-1)%5+1] end
  if profile then dt=math.min(dt,memory_ms-elapsed) end
  if dt<=0 then break end
  elapsed=elapsed+dt
  if elapsed>memory_ms then error("Runtime budget exceeded") end
  if profile=="idle" then
    button=""
  elseif profile=="hold_a" or profile=="hold_b" or profile=="hold_c" then
    local selected=profile:sub(-1):upper()
    if frame==1 and env.on_button then callback_phase="on_button"; call(env.on_button,selected,"pressed") end
    button=selected
  elseif frame%(profile=="rapid" and 2 or 30)==0 then
    button=({"A","B","C"})[(frame//(profile=="rapid" and 2 or 30)-1)%3+1]
    if env.on_button then callback_phase="on_button"; call(env.on_button,button,"pressed") end
  elseif button~="" then
    button=""
  end
  callback_phase="update"
  call(env.update,dt)
  frames_run=frames_run+1
  if profile and elapsed>=memory_ms then break end
end
return {frames=frames_run,elapsed_ms=elapsed,api_operations=total,trace=trace,max_callback_operations=peak_ops,max_callback_display_work=peak_work,
        min_update_draws=min_update_draws or 0,update_count=update_count,max_callback_clears=peak_clears}
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
    configured_ms = request.get("max_runtime_ms", 10000)
    max_ms = 60000 if configured_ms == 0 else min(configured_ms, 10000)
    result = lua.execute(HARNESS, source, ",".join(services), max_ms,
                         (max_ms+15)//16 if request.get("profile") else min(180, max_ms // 16), request.get("profile"),
                         max(20000, max_ms*2))
    trace = []
    for i in range(1, len(result["trace"]) + 1):
        command = result["trace"][i]
        trace.append([command[j] for j in range(1, len(command) + 1)])
    return {"ok": True, "syntax": "passed", "api_validation": "passed",
            "frames": result["frames"], "elapsed_ms": result["elapsed_ms"],
            "api_operations": result["api_operations"], "trace": trace,
            "max_callback_operations":result["max_callback_operations"],"max_callback_display_work":result["max_callback_display_work"],
            "min_update_draws":result["min_update_draws"],"update_count":result["update_count"],"max_callback_clears":result["max_callback_clears"]}


if __name__ == "__main__":
    try:
        request = json.loads(sys.stdin.buffer.read(220000))
        response = simulate(request)
    except BaseException as error:
        response = {"ok": False, "error": (type(error).__name__ + ": " + str(error))[:6000]}
    print(json.dumps(response, ensure_ascii=True, allow_nan=False))
    sys.exit(0 if response["ok"] else 1)
