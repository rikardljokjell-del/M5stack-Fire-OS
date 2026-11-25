"""Trusted Lua 5.4 validator/simulator; started with -I and a scrubbed environment.

No generated code is evaluated by Python. The Lua environment contains no
Python objects/callbacks, standard library loaders, filesystem or process APIs.
This is an interpreter capability boundary, not a full OS security sandbox.
"""
import json
import hashlib
import re
import sys
from pathlib import Path

from lupa.lua54 import LuaRuntime


REGISTRY=json.loads((Path(__file__).parent/"data/HARDWARE_API-v0.2.json").read_text(encoding="utf-8"))
METHODS={service:{name for name,m in spec["methods"].items() if m["since"]=="fire-lua-0.1"}
         for service,spec in REGISTRY["services"].items() if any(m["since"]=="fire-lua-0.1" for m in spec["methods"].values())}
SDK_DATA=Path(__file__).parent/'data/app_sdk'
SDK_WRAPPER=json.loads((SDK_DATA/'contract.json').read_text(encoding='utf-8'))
SDK=SDK_WRAPPER['registry'];SDK_VERSION=SDK['api_version']
SDK_HASH=hashlib.sha256(json.dumps(SDK,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
if SDK_HASH!=SDK_WRAPPER['api_contract']:raise ValueError('SDK contract checksum mismatch')
AI_WRAPPER=json.loads((Path(__file__).parent/'data/RUNTIME_AI-v1.json').read_text(encoding='utf-8'))
AI=AI_WRAPPER['registry'];AI_HASH=AI_WRAPPER['api_contract']
if hashlib.sha256(json.dumps(AI,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()!=AI_HASH:raise ValueError('Runtime AI contract checksum mismatch')
AI_EXTENSION={'version':AI['api_version'],'contract':AI_HASH}
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


def validate_api(source, services, api_version="fire-lua-0.1"):
    methods=METHODS if api_version=="fire-lua-0.1" else {s:set(spec["methods"]) for s,spec in REGISTRY["services"].items()}
    if api_version==SDK_VERSION:
        methods['display']|=set(SDK['display']['methods'])
        methods['ui']=set(SDK['ui_methods'])
        methods['ai']=set(AI['methods'])
    clean = without_literals(source)
    banned = FORBIDDEN.intersection(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", clean))
    if banned:
        raise ValueError("Forbidden Lua capability: " + ", ".join(sorted(banned)))
    if re.search(r"\bfire\s*\[", clean):
        raise ValueError("Use explicit fire.service.method calls")
    for service, method in re.findall(r"\bfire\s*\.\s*(\w+)\s*[.:]\s*(\w+)", clean):
        if service=='ui' and api_version==SDK_VERSION:
            if 'display' not in services or method not in methods['ui']:raise ValueError('Unknown or undeclared SDK UI method')
            continue
        if service not in services or method not in methods.get(service, set()):
            raise ValueError(f"Unknown or undeclared API fire.{service}.{method}")
        specs=AI if service=='ai' else REGISTRY['services'][service]
        if not set(specs['methods'].get(method,{}).get('requires',[]))<=set(services):
            raise ValueError("Undeclared dependent hardware service")
    for service in re.findall(r"\bfire\s*\.\s*(\w+)", clean):
        if service=='ui' and api_version==SDK_VERSION and 'display' in services:continue
        if service not in services:
            raise ValueError(f"Undeclared service fire.{service}")


HARNESS = r'''
local source, services, memory_ms, frames, profile, operation_limit, api_version, specs, resources, hardware_factory, app_memory_budget, sequence, interval_ms, native_guard, capture_times, sdk_factory, sdk_fonts, sdk_assets, sdk_ui, ai_limits = ...
local sdk_enabled=sdk_factory~=nil
local sequence_index, next_input_ms = 1,16
local compile, hook = load, debug.sethook
local count, total, elapsed = 0, 0, 0
local callback_ops, callback_work, peak_ops, peak_work = 0,0,0,0
local callback_phase, clear_count, visible_ops, background = "",0,0,0
local next_background,frame_background=0,0
local frame_active,frame_dirty,frame_clear_consumed=false,false,false
local elided_clears,real_clears=0,0
local text_bytes, peak_text_bytes = 0,0
local grid_pixels, peak_grid_pixels = 0,0
local grid_cells,peak_grid_cells,rgb_calls,peak_rgb_calls=0,0,0,0
local min_update_draws, update_count, peak_clears = nil,0,0
local frames_run = 0
local os_suppressed, os_suspended, os_exited, os_navigation = 0,0,false,""
local host_baseline, app_memory_peak = 0,0
local diagnostic_bytes,diagnostic_active=0,false
-- Only trusted, retained diagnostic tables are allocated between these calls.
-- No app callback runs here; app/UI allocation and callback guards are intact.
local function diagnostic_begin()
  diagnostic_active=true;collectgarbage("stop")
  return collectgarbage("count")*1024
end
local function diagnostic_end(before)
  diagnostic_bytes=diagnostic_bytes+math.max(0,collectgarbage("count")*1024-before)
  diagnostic_active=false;collectgarbage("restart")
end
local hardware
local has_display = string.match(services,"display") ~= nil
local trace, trace_count = {}, 0
local button = ""
local imu_reads=0
local scenes, led_state, scene = {},{},nil
local rgb_written,rgb_nonzero={},{}
for i=1,10 do rgb_written[i],rgb_nonzero[i]=false,false end
local rgb_writes=0
local function rgb_summary()
 local written,active,final={}, {}, {}
 local left,right=false,false
 for i=0,9 do
  if rgb_written[i+1] then written[#written+1]=i end
  if rgb_nonzero[i+1] then active[#active+1]=i;if i<5 then left=true else right=true end end
  final[i+1]=led_state[i] or 0
 end
 return {writes=rgb_writes,written_indices=written,nonzero_indices=active,left_nonzero=left,right_nonzero=right,final_rgb=final}
end
local checkpoints={400,1400,3400,5400,7400}
local next_checkpoint=1
local visual_frames, visual_current, visual_index = {},nil,1
local visual_button, visual_inputs = "",0
local function capture(name,...)
  if not visual_current then return end
  if #visual_current.ops>=64 then error("Visual capture operation bound exceeded") end
  local diagnostic_before=diagnostic_begin()
  local values={name,...}
  if name=="grid" then
    local cells,palette={},{}
    for i=1,#values[8] do cells[i]=values[8][i] end
    for i=1,#values[9] do palette[i]=values[9][i] end
    values[8],values[9]=cells,palette
  else
    for k,v in pairs(values) do
      if type(v)=="table" then local copy={};for i=1,#v do copy[i]=v[i] end;values[k]=copy end
    end
  end
  visual_current.ops[#visual_current.ops+1]=values
  diagnostic_end(diagnostic_before)
end
local function imu_value()
  if profile=="imu_motion" then
    if elapsed<2000 or elapsed>=6000 then return {x=0,y=0,z=1} end
    local sign=elapsed<4000 and 1 or -1
    return {x=-0.5*sign,y=0.5*sign,z=math.sqrt(0.5)}
  end
  if profile=="imu_flat" then return {x=0,y=0,z=1} end
  if profile=="imu_tilt" or profile=="imu_calibration" then return {x=-0.5,y=0.5,z=math.sqrt(0.5)} end
  if profile=="imu_vertical" then return {x=1,y=0,z=0} end
  if profile=="imu_zero" then return {x=0,y=0,z=0} end
  if profile=="imu_tolerance" then return {x=-math.sin(math.pi/90),y=0,z=math.cos(math.pi/90)} end
  if profile=="imu_recovery" then
    if elapsed>=2000 and elapsed<4000 then return {x=0,y=0,z=0} end
    if elapsed>=4000 and elapsed<6000 then return {x=1,y=0,z=0} end
    return {x=-0.5,y=0.5,z=math.sqrt(0.5)}
  end
  return {x=0.5*math.sin(elapsed/1000),y=0.5*math.cos(elapsed/1000),z=math.sqrt(0.75)}
end
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
  if sdk_enabled and hardware then
    if name=="rgb" then hardware.charge_base("rgb.set",1) else hardware.charge_sdk(name,name=="text" and #select(3,...) or 1) end
  end
  if name~="rgb" and name~="grid" then capture(name,...) end
  total = total + 1
  callback_ops=callback_ops+1
  local a,b,c,d=...
  local clear_elided=false
  if name=="rgb" then
    rgb_calls=rgb_calls+1;peak_rgb_calls=math.max(peak_rgb_calls,rgb_calls)
    if native_guard and rgb_calls>1 then error("Native host RGB budget exceeded: at most ONE rgb.set per callback; each call synchronously transmits the whole strip. Queue changes across updates.") end
  end
  if scene and name=="text" and #scene.texts<12 then scene.texts[#scene.texts+1]=c end
  if scene and name=="fill_circle" and #scene.circles<4 then scene.circles[#scene.circles+1]={x=a,y=b,r=c} end
  if profile and has_display and callback_phase=="on_button" and name~="rgb" then
    error("Visual frame: on_button must change state only; render in update")
  end
  if name=="clear" then
    clear_count=clear_count+1
    peak_clears=math.max(peak_clears,clear_count)
    if profile and not sdk_enabled and (clear_count>1 or visible_ops>0) then
      error("Visual frame: clear at most once BEFORE drawing; never erase a completed scene")
    end
    if sdk_enabled then
      clear_elided=frame_active and not frame_dirty and not frame_clear_consumed and a==frame_background
      frame_clear_consumed=true
      if clear_elided then elided_clears=elided_clears+1
      else real_clears=real_clears+1;frame_dirty=true end
    end
    background=a
    visible_ops=0
  elseif name~="rgb" then
    if sdk_enabled then frame_dirty=true end
    local ink = name=="grid" and select(7,...) or name=="pixel" and c or (name=="text" or name=="circle" or name=="fill_circle") and d or select(5,...)
    local empty=name=="rect" and (c==0 or d==0)
    if not empty and ink~=background and (name~="text" or #c>0) then visible_ops=visible_ops+1 end
  end
  local work=0
  if name=="clear" then work=clear_elided and 0 or 76800
  elseif name=="rect" then work=2*(c+d)
  elseif name=="fill_rect" then work=c*d
  elseif name=="line" then work=math.max(math.abs(c-a),math.abs(d-b))+1
  elseif name=="circle" then work=math.ceil(7*c)
  elseif name=="fill_circle" then work=math.ceil(math.pi*c*c)
  elseif name=="grid" then
    grid_cells=grid_cells+select(5,...)*select(6,...);peak_grid_cells=math.max(peak_grid_cells,grid_cells)
    if native_guard and grid_cells>(sdk_enabled and 384 or 128) then error("Native host grid cell budget exceeded: cumulative cells include black cells; compact cached glyphs/boards.") end
    work=c*d*select(5,...)*select(6,...)
    grid_pixels=grid_pixels+work;peak_grid_pixels=math.max(peak_grid_pixels,grid_pixels)
    if profile and grid_pixels>32768 then error("Native grid raster budget exceeded; compact the complete board and merge static/dynamic cells") end
  elseif name=="text" then
    work=#c*48;text_bytes=text_bytes+#c;peak_text_bytes=math.max(peak_text_bytes,text_bytes)
    if profile and text_bytes>256 then error("Per-callback text budget exceeded; cache labels and simplify the complete frame") end
  end
  callback_work=callback_work+work
  peak_ops=math.max(peak_ops,callback_ops)
  peak_work=math.max(peak_work,callback_work)
  if profile and not sdk_enabled and (callback_ops>24 or callback_work>120000) then
    error("Per-callback display work budget exceeded; simplify the complete scene, never split a visible frame")
  end
  if total > operation_limit then error("API operation budget exceeded") end
  if trace_count < 240 then
    trace_count = trace_count + 1
    local before=diagnostic_begin();trace[trace_count] = {name, ...};diagnostic_end(before)
  end
end
local function xy(x,y) whole(x,0,319); whole(y,0,239) end
local function color(c) whole(c,0,65535) end
local display = {
  clear = function(c) color(c); record("clear",c) end,
  circle = function(x,y,r,c)
    xy(x,y); whole(r,0,160); color(c)
    if profile and not sdk_enabled and (x-r<0 or x+r>319 or y-r<0 or y+r>239) then error("Visual frame: circle clipped by screen bounds") end
    record("circle",x,y,r,c)
  end,
  rect = function(x,y,w,h,c)
    xy(x,y); whole(w,0,320); whole(h,0,240); color(c)
    if profile and not sdk_enabled and (x+w>320 or y+h>240 or w==0 or h==0) then error("Visual frame: rectangle clipped or empty") end
    record("rect",x,y,w,h,c)
  end,
  line = function(x,y,a,b,c) xy(x,y); xy(a,b); color(c); record("line",math.floor(x),math.floor(y),math.floor(a),math.floor(b),c) end,
  text = function(x,y,s,c)
    xy(x,y); color(c)
    if type(s) ~= "string" or #s > 80 then error("Text exceeds 80 bytes") end
    if profile and ((not sdk_enabled and (x+#s*6>320 or y+8>240)) or string.find(s,"[\r\n\t]")) then
      error("Visual frame: text clipped or multiline; use short labels with a conservative 6x8 font footprint")
    end
    record("text",math.floor(x),math.floor(y),s,c)
  end
}
if api_version~="fire-lua-0.1" then
  display.fill_rect=function(x,y,w,h,c)
    xy(x,y);whole(w,1,320);whole(h,1,240);color(c)
    if not sdk_enabled and (x+w>320 or y+h>240) then error("Visual frame: filled rectangle clipped") end
    record("fill_rect",x,y,w,h,c)
  end
  display.fill_circle=function(x,y,r,c)
    xy(x,y);whole(r,0,160);color(c)
    if not sdk_enabled and (x-r<0 or x+r>319 or y-r<0 or y+r>239) then error("Visual frame: filled circle clipped") end
    record("fill_circle",x,y,r,c)
  end
  display.pixel=function(x,y,c)xy(x,y);color(c);record("pixel",x,y,c)end
  display.grid=function(x,y,w,h,cols,rows,cells,palette)
    xy(x,y);whole(w,1,32);whole(h,1,32);whole(cols,1,32);whole(rows,1,32)
    if cols*rows>384 or not sdk_enabled and (x+w*cols>320 or y+h*rows>240) then error("Visual frame: grid clipped or too large") end
    if type(cells)~="table" or #cells~=cols*rows or type(palette)~="table" or #palette<1 or #palette>16 then error("Invalid grid data") end
    local ink=0;local count=0
    for k,c in pairs(palette) do whole(k,1,#palette);color(c);count=count+1 end
    if count~=#palette then error("Grid palette must be dense") end
    count=0
    for k,index in pairs(cells) do
      whole(k,1,cols*rows);whole(index,0,#palette-1);count=count+1
      if palette[index+1]~=background then ink=palette[index+1] end
    end
    if count~=cols*rows then error("Grid data must be dense") end
    if scene and #scene.grids<2 then
      local digits={};for i=1,#cells do digits[i]=string.char(48+cells[i]) end
      scene.grids[#scene.grids+1]={x=x,y=y,cols=cols,rows=rows,cells=table.concat(digits)}
    end
    capture("grid",x,y,w,h,cols,rows,cells,palette)
    record("grid",x,y,w,h,cols,rows,ink)
  end
end
local available = {
  display = display,
  time = {millis=function() return 60000+elapsed end},
  rgb = {set=function(i,r,g,b)
    whole(i,0,9); whole(r,0,255); whole(g,0,255); whole(b,0,255)
    record("rgb",i,r,g,b)
    led_state[i]=r*65536+g*256+b
    rgb_written[i+1]=true;rgb_writes=rgb_writes+1
    if r+g+b>0 then rgb_nonzero[i+1]=true end
  end},
  imu = {accel=function() imu_reads=imu_reads+1;return imu_value() end},
  buttons = {pressed=function(b)
    if b~="A" and b~="B" and b~="C" then error("Unknown button") end
    return b==button
  end}
}
local service_set={};for service in string.gmatch(services,"[a-z0-9_]+") do service_set[service]=true end
hardware=nil
if api_version~="fire-lua-0.1" then
  hardware=hardware_factory(available,specs,resources,profile,function()return elapsed end,function(name,bytes)
    total=total+1;if total>operation_limit then error("API operation budget exceeded") end
    if trace_count<240 then trace_count=trace_count+1;local before=diagnostic_begin();trace[trace_count]={name,bytes};diagnostic_end(before) end
  end,service_set,ai_limits,function()return callback_phase end)
end
if sdk_enabled then
  -- Existing simulated base queries predate the extended I/O meter. Native
  -- charges these calls too; SDK must enforce one combined callback quota.
  for _,entry in ipairs({{"time","millis"},{"imu","accel"},{"buttons","pressed"}}) do
    local service,method=entry[1],entry[2]
    local original=available[service][method]
    available[service][method]=function(...)
      hardware.charge_base(service.."."..method,1)
      total=total+1;if total>operation_limit then error("API operation budget exceeded") end
      return original(...)
    end
  end
  sdk_factory(display,sdk_fonts,sdk_assets,function(name,work,ink,...)
    total=total+1;callback_ops=callback_ops+1;callback_work=callback_work+work
    peak_ops=math.max(peak_ops,callback_ops);peak_work=math.max(peak_work,callback_work)
    if callback_ops>64 or total>operation_limit then error("SDK display operation budget exceeded") end
    if callback_phase=="on_button" then error("Visual frame: SDK drawing belongs in update") end
    frame_dirty=true
    if ink~=nil and ink~=background and work>0 then visible_ops=visible_ops+1 end
    capture(name,...)
    if trace_count<240 then trace_count=trace_count+1;local before=diagnostic_begin();trace[trace_count]={name,...};diagnostic_end(before) end
  end,function(name,bytes)
    hardware.charge_sdk(name,bytes)
    if name=="text_style" or name=="measure_text" then
      text_bytes=text_bytes+bytes;peak_text_bytes=math.max(peak_text_bytes,text_bytes)
      if text_bytes>256 then error("SDK cumulative text and measurement budget exceeded") end
    end
    if name=="measure_text" or name=="set_background" then
      total=total+1;if total>operation_limit then error("API operation budget exceeded") end
    end
  end,function(color) next_background=color end)
end
local fire = {}
for service in string.gmatch(services,"[a-z0-9_]+") do
  if not available[service] then error("Unsupported service") end
  fire[service] = available[service]
end
local env = {
  fire=fire, math={abs=math.abs,floor=math.floor,ceil=math.ceil,min=math.min,
    max=math.max,sqrt=math.sqrt,sin=math.sin,cos=math.cos,pi=math.pi},
  type=type,tonumber=tonumber,tostring=tostring,pairs=pairs,ipairs=ipairs,next=next
}
if hardware then env.string=hardware.string;env.table=hardware.table end
local string_meta=getmetatable("")
if string_meta then string_meta.__index=hardware and hardware.string or {};string_meta.__metatable=false end
local function memory_check()
  if hardware and host_baseline>0 and not diagnostic_active then
    collectgarbage("step",20)
    local used=math.max(0,math.ceil(collectgarbage("count")*1024-host_baseline-diagnostic_bytes))
    app_memory_peak=math.max(app_memory_peak,used)
    if used>app_memory_budget then error("App memory budget exceeded") end
  end
end
local function quota()
  count=count+1000
  if count>(profile and not sdk_enabled and 20000 or 200000) then error("Instruction budget exceeded") end
  memory_check()
end
local function call(fn, ...)
  if callback_phase=="on_button" then visual_button=...;visual_inputs=visual_inputs+1 end
  count=0
  callback_ops,callback_work=0,0
  text_bytes=0
  grid_pixels=0
  grid_cells,rgb_calls=0,0
  if hardware then hardware.begin_callback() end
  clear_count,visible_ops,background=0,0,(sdk_enabled and callback_phase=="update") and frame_background or 0
  hook(quota,"",1000)
  fn(...)
  hook()
  memory_check()
  if profile and has_display and callback_phase=="update" then
    update_count=update_count+1
    min_update_draws=math.min(min_update_draws or visible_ops,visible_ops)
    if visible_ops==0 then
      error("Visual frame: no visible output in update; FIRE clears its sprite each frame. Render the complete scene on EVERY update, including paused, game-over and between simulation ticks")
    end
  end
end
if hardware then collectgarbage("collect");host_baseline=collectgarbage("count")*1024 end
local program, syntax_error = compile(source,"main.lua","t",env)
if not program then error(syntax_error) end
if sdk_enabled then
  local prelude,err=compile(sdk_ui,"fire-ui.lua","t",env)
  if not prelude then error(err) end
  local result=nil;call(function()result=prelude()end)
  if type(result)~="table" then error("Trusted UI prelude must return a table") end
  fire.ui=result
end
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
  local suspend_update=false
  if profile and string.sub(profile,1,4)=="imu_" and next_checkpoint<=#checkpoints and elapsed>=checkpoints[next_checkpoint] then
    scene={at_ms=elapsed,texts={},grids={},circles={},leds={}}
  else scene=nil end
  if sequence and #sequence>0 then
    button=""
    if sequence_index<=#sequence and elapsed>=next_input_ms then
      button=sequence[sequence_index];sequence_index=sequence_index+1;next_input_ms=elapsed+interval_ms
      if env.on_button then callback_phase="on_button";call(env.on_button,button,"pressed") end
    end
  elseif profile and string.sub(profile,1,4)=="imu_" then
    button=""
    local event=false
    if (profile=="imu_calibration" or profile=="imu_recovery") and elapsed-dt<1000 and elapsed>=1000 then event=true end
    if profile=="imu_recovery" and ((elapsed-dt<3000 and elapsed>=3000) or (elapsed-dt<5000 and elapsed>=5000)) then event=true end
    if (profile=="imu_vertical" or profile=="imu_zero") and elapsed-dt<1000 and elapsed>=1000 then event=true end
    local selected="B"
    if profile=="imu_tolerance" then
      if elapsed-dt<1000 and elapsed>=1000 then event=true;selected="A" end
      if (elapsed-dt<3000 and elapsed>=3000) or (elapsed-dt<5000 and elapsed>=5000) then event=true;selected="C" end
    end
    if event and env.on_button then callback_phase="on_button";call(env.on_button,selected,"pressed") end
  elseif profile=="os_long_a" or profile=="os_long_b" or profile=="os_long_c" then
    -- Synthetic OS-owned gesture: raw state exists before ownership is claimed,
    -- but a consumed hold never becomes an application short-press callback.
    local selected=string.upper(string.sub(profile,-1))
    if elapsed<650 then button=selected
    else
      button=""
      if os_suppressed==0 then
        os_suppressed=1
        os_navigation=selected=="A" and "home" or selected=="B" and "quick_settings" or "back"
      end
      if selected~="B" then os_exited=true;break end
      -- Model an OS overlay suspending app updates, then returning control.
      if elapsed<1150 then suspend_update=true end
    end
  elseif profile=="os_double" then
    -- A configured OS double-click shortcut consumes both short clicks.
    -- The physical B down-state may still be observed before the shortcut.
    button=(frame<=4 or frame>=10 and frame<=13) and "B" or ""
    if frame==5 or frame==14 then os_suppressed=os_suppressed+1 end
    if frame>=14 then
      os_navigation="configured_double_shortcut"
      if frame<45 then suspend_update=true end
    end
  elseif profile=="start_b_idle" or profile=="play_directions" or profile=="long_session" then
    button=""
    if frame==1 then button="B"
    elseif profile~="start_b_idle" and frame%30==0 then
      local step=frame//30
      button=step%8==0 and "B" or step%2==0 and "A" or "C"
    end
    if button~="" and env.on_button then callback_phase="on_button";call(env.on_button,button,"pressed") end
  elseif profile=="idle" then
    button=""
  elseif profile=="hold_a" or profile=="hold_b" or profile=="hold_c" then
    local selected=string.upper(string.sub(profile,-1))
    if frame==1 and env.on_button then callback_phase="on_button"; call(env.on_button,selected,"pressed") end
    button=selected
  elseif frame%(profile=="rapid" and 2 or 30)==0 then
    button=({"A","B","C"})[(frame//(profile=="rapid" and 2 or 30)-1)%3+1]
    if env.on_button then callback_phase="on_button"; call(env.on_button,button,"pressed") end
  elseif button~="" then
    button=""
  end
  if suspend_update then os_suspended=os_suspended+1
  else
    callback_phase="update"
    -- Model the OS's actual prefill/ownership acknowledgement, not a Lua call.
    frame_background=sdk_enabled and next_background or 0
    frame_active=sdk_enabled;frame_dirty=false;frame_clear_consumed=false
    if visual_index<=#capture_times and elapsed>=capture_times[visual_index] then
      local before=diagnostic_begin();visual_current={at_ms=elapsed,frame=frame,button=visual_button,input_count=visual_inputs,frame_background=frame_background,ops={}};diagnostic_end(before)
    end
    call(env.update,dt)
    frame_active=false
    frames_run=frames_run+1
    if visual_current then
      local before=diagnostic_begin();visual_frames[#visual_frames+1]=visual_current;visual_current=nil;diagnostic_end(before)
      visual_index=visual_index+1
    end
  end
  if scene then
    for i=0,9 do scene.leds[i+1]=led_state[i] or 0 end
    scenes[#scenes+1]=scene;next_checkpoint=next_checkpoint+1
  end
  if profile and elapsed>=memory_ms then break end
end
return {frames=frames_run,elapsed_ms=elapsed,api_operations=total,trace=trace,max_callback_operations=peak_ops,max_callback_display_work=peak_work,
        elided_clears=elided_clears,real_clears=real_clears,next_background=next_background,
        min_update_draws=min_update_draws or 0,update_count=update_count,max_callback_clears=peak_clears,max_callback_text_bytes=peak_text_bytes,
        rgb_feedback=rgb_summary(),hardware_metrics=hardware and hardware.metrics() or nil,app_memory_peak=app_memory_peak,diagnostic_memory_bytes=math.ceil(diagnostic_bytes),
        os_reserved_callbacks_suppressed=os_suppressed,os_updates_suspended=os_suspended,os_exited=os_exited,os_navigation=os_navigation,
        max_callback_grid_pixels=peak_grid_pixels,max_callback_grid_cells=peak_grid_cells,max_callback_rgb_calls=peak_rgb_calls,
        imu_reads=imu_reads,imu_scenes=scenes,visual_frames=visual_frames}
'''


def simulate(request):
    source = request["main_lua"]
    sequence=request.get("button_sequence",[])
    interval=request.get("interval_ms",250)
    if (not isinstance(sequence,list) or len(sequence)>32 or any(type(b) is not str or b not in {"A","B","C"} for b in sequence)
            or type(interval) is not int or not 100<=interval<=1000):raise ValueError("Invalid bounded button sequence")
    capture_times=request.get("capture_at_ms",[])
    if (not isinstance(capture_times,list) or len(capture_times)>8
            or any(type(t) is not int or not 16<=t<=600000 for t in capture_times)
            or capture_times!=sorted(set(capture_times))):
        raise ValueError("Invalid bounded visual capture times")
    if len(source.encode("utf-8")) > 100000:
        raise ValueError("Lua source too large")
    services = request["required_services"]
    api_version=request.get("api_version","fire-lua-0.1")
    if api_version not in {"fire-lua-0.1","fire-lua-0.2",SDK_VERSION}:raise ValueError("Unsupported Lua API version")
    if api_version==SDK_VERSION and request.get('api_contract')!=SDK_HASH:raise ValueError('SDK contract mismatch')
    if api_version==SDK_VERSION and 'display' not in services:raise ValueError('SDK requires display permission')
    if 'ai' in services and (api_version!=SDK_VERSION or request.get('runtime_ai')!=AI_EXTENSION):raise ValueError('Runtime AI requires exact SDK extension')
    if not set(services) <= (METHODS.keys() if api_version=="fire-lua-0.1" else set(REGISTRY['services'])|({'ai'} if api_version==SDK_VERSION else set())):
        raise ValueError("Unsupported service")
    validate_api(source, services,api_version)
    app_memory=min(request.get("max_memory",262144),262144)
    lua = LuaRuntime(
        register_eval=False, register_builtins=False,
        max_memory=app_memory+(524288 if api_version!="fire-lua-0.1" else 0),
    )
    lua.compile(source, name="main.lua", mode="t")  # syntax only, never executes here
    configured_ms = request.get("max_runtime_ms", 10000)
    horizon=request.get("test_horizon_ms")
    if horizon is not None:
        if type(horizon) is not int or not 1000<=horizon<=600000:
            raise ValueError("Test horizon must be an integer from 1000 to 600000 ms")
        if configured_ms!=0:
            raise ValueError("An extended test horizon requires an until-exit app")
    default_horizon=600000 if request.get("profile")=="long_session" else 60000
    max_ms=(horizon if horizon is not None else default_horizon) if configured_ms==0 else min(configured_ms,10000)
    preview_ms=request.get('preview_duration_ms')
    if preview_ms is not None:
        if (type(preview_ms) is not int or not 16<=preview_ms<=12000
                or request.get('profile')!='idle'):
            raise ValueError('Invalid bounded preview duration')
        max_ms=min(max_ms,preview_ms)
    specs={s:(AI['methods'] if s=='ai' else REGISTRY['services'][s]['methods']) for s in services} if api_version!="fire-lua-0.1" else {}
    if 'ai' in services:specs['ai']={'request':{**AI['methods']['request'],'returns':'job'}}
    helper=(Path(__file__).parent/'data/runtime_ai_sim.lua').read_text(encoding='utf-8') if 'ai' in services else ''
    factory=lua.execute(helper+(Path(__file__).parent/"data/hardware_sim.lua").read_text(encoding="utf-8")) if api_version!="fire-lua-0.1" else None
    sdk_factory=None;sdk_fonts={};sdk_assets={};sdk_ui=''
    if api_version==SDK_VERSION:
        sdk_factory=lua.execute((Path(__file__).parent/'data/sdk_sim.lua').read_text(encoding='utf-8'))
        fontdata=json.loads((SDK_DATA/'fonts.json').read_text(encoding='utf-8'))['fonts']
        sdk_fonts={name:{'line_height':f['line_height'],'advances':{int(cp):g['advance'] for cp,g in f['glyphs'].items()}} for name,f in fontdata.items()}
        assetdata=json.loads((SDK_DATA/'assets.json').read_text(encoding='utf-8'))['assets']
        sdk_assets={a['id']:a['width']+a['height']*256+(65536 if a.get('tintable') else 0) for a in assetdata}
        sdk_ui=(SDK_DATA/'ui.lua').read_text(encoding='utf-8')
    result = lua.execute(HARNESS, source, ",".join(services), max_ms,
                         (max_ms+15)//16 if request.get("profile") else min(180, max_ms // 16), request.get("profile"),
                         max(20000, ((max_ms+15)//16)*128 if api_version==SDK_VERSION else max_ms*2),api_version,lua.table_from(specs,recursive=True),lua.table_from(request.get("hardware") or {},recursive=True),factory,app_memory,lua.table_from(sequence),interval,
                         request.get("native_host_policy")=="fire-native-host-v1",lua.table_from(capture_times),sdk_factory,
                         lua.table_from(sdk_fonts,recursive=True),lua.table_from(sdk_assets),sdk_ui,lua.table_from(AI['limits']))
    hardware_metrics=result["hardware_metrics"]
    resources_used={kind:[values[i] for i in range(1,len(values)+1)] for kind,values in hardware_metrics["resources_used"].items()} if hardware_metrics else {}
    def unpack(value):
        if hasattr(value,"items"):
            keys=list(value.keys())
            if keys and all(type(k) is int for k in keys):return [unpack(value[k]) for k in sorted(keys)]
            return {k:unpack(v) for k,v in value.items()} if keys else []
        return value
    trace=unpack(result['trace'])
    return {"ok": True, "syntax": "passed", "api_validation": "passed",
            "native_callback_budgets":{key:SDK['budgets'][key] for key in
                ('callback_ms','init_callback_ms','sdk_update_callback_ms') if key!='sdk_update_callback_ms' or api_version==SDK_VERSION},
            "native_timing_measured":False,
            "runtime_ai_simulated":'ai' in services,
            "frames": result["frames"], "elapsed_ms": result["elapsed_ms"],
            "api_operations": result["api_operations"], "trace": trace,
            "elided_clears":result["elided_clears"],"real_clears":result["real_clears"],"next_background":result["next_background"],
            "max_callback_operations":result["max_callback_operations"],"max_callback_display_work":result["max_callback_display_work"],
            "min_update_draws":result["min_update_draws"],"update_count":result["update_count"],"max_callback_clears":result["max_callback_clears"],
            "max_callback_text_bytes":result["max_callback_text_bytes"],"resources_used":resources_used,
            "max_callback_grid_pixels":result["max_callback_grid_pixels"],
            "max_callback_grid_cells":result["max_callback_grid_cells"],"max_callback_rgb_calls":result["max_callback_rgb_calls"],
            "imu_reads":result["imu_reads"],"imu_scenes":unpack(result["imu_scenes"]),
            "visual_frames":unpack(result["visual_frames"]),"rgb_feedback":unpack(result["rgb_feedback"]),
            "hardware_simulated":api_version!="fire-lua-0.1","app_memory_peak":result["app_memory_peak"],"diagnostic_memory_bytes":result["diagnostic_memory_bytes"],"max_io_calls":hardware_metrics["max_io_calls"] if hardware_metrics else 0,
            "max_io_bytes":hardware_metrics["max_io_bytes"] if hardware_metrics else 0,"max_jobs":hardware_metrics["max_jobs"] if hardware_metrics else 0,
            "io_calls":dict(hardware_metrics["calls"].items()) if hardware_metrics else {},
            "jobs_started":dict(hardware_metrics["jobs_started"].items()) if hardware_metrics else {},
            "os_reserved_callbacks_suppressed":result["os_reserved_callbacks_suppressed"],
            "os_updates_suspended":result["os_updates_suspended"],"os_exited":result["os_exited"],"os_navigation":result["os_navigation"],
            "os_gesture_simulated":request.get("profile") in {"os_long_a","os_long_b","os_long_c","os_double"}}


if __name__ == "__main__":
    try:
        request = json.loads(sys.stdin.buffer.read(220000))
        response = simulate(request)
    except BaseException as error:
        response = {"ok": False, "error": (type(error).__name__ + ": " + str(error))[:6000]}
    print(json.dumps(response, ensure_ascii=True, allow_nan=False))
    sys.exit(0 if response["ok"] else 1)
