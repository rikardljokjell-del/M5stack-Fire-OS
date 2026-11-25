-- Trusted PC host. No sockets, hardware, files or Python callbacks are exposed.
return function(available, specs, resources, profile, now, trace, services, ai_limits, phase)
  local jobs, used, pins, pwm, uart, spi, files, handles, gpio_modes, gpio_values = {},{},{},{},{},{},{},{},{},{}
  local next_job, next_handle, io_calls, io_bytes, peak_io, peak_bytes = 0,0,0,0,0,0
  local active_jobs, peak_jobs = 0,0
  local calls, jobs_started = {},{}
  local function contains(t,v) for _,n in ipairs(t or {}) do if n==v then return true end end return false end
  local function resource(kind,value)
    if not contains(resources[kind],value) then error("Unannounced hardware resource: "..kind) end
    used[kind]=used[kind] or {};used[kind][value]=true
  end
  local function note(name,bytes,quiet)
    io_calls=io_calls+1;io_bytes=io_bytes+(bytes or 0)
    peak_io=math.max(peak_io,io_calls);peak_bytes=math.max(peak_bytes,io_bytes)
    if io_calls>64 or io_bytes>2048 then error("Hardware callback I/O budget exceeded") end
    if not quiet then trace(name,bytes or 0) end
  end
  local function check(v,s)
    local t=s.type
    if t=="integer" then
      if type(v)~="number" or v~=v or v%1~=0 or v<s.min or v>s.max then error("Hardware integer outside bounds") end
    elseif t=="boolean" then if type(v)~="boolean" then error("Hardware boolean required") end
    elseif t=="enum" then if not contains(s.values,v) then error("Invalid hardware enum") end
    elseif t=="bytes" or t=="indices" or t=="colors" then
      if type(v)~="table" or #v>s.max_items then error("Hardware array exceeds limit") end
      local entries=0
      for k,n in pairs(v) do
        entries=entries+1
        if type(k)~="number" or k%1~=0 or k<1 or k>#v then error("Hardware array must be dense") end
        check(n,{type="integer",min=0,max=t=="colors" and 65535 or t=="indices" and 15 or 255})
      end
      if entries~=#v then error("Hardware array must be dense") end
    else
      if type(v)~="string" or #v>s.max_bytes or string.find(v,"%z") then error("Hardware string exceeds limit") end
      if t=="path" then
        if string.find(v,"[\\:%c]") or string.sub(v,1,1)=="/" then error("App-private relative path required") end
        for part in string.gmatch(v,"[^/]+") do if part==".." or part=="." then error("Path traversal rejected") end end
      elseif t=="url" then
        if not string.match(v,"^https?://[^/%s]+") or string.find(v,"[%c@]") then error("Bounded HTTP(S) URL without embedded credentials required") end
      end
    end
  end
  local function args_ok(args,spec)
    if args.n>#spec.args then error("Wrong hardware argument count") end
    for i,s in ipairs(spec.args) do
      if i>args.n or args[i]==nil and s.optional then if not s.optional then error("Wrong hardware argument count") end;args[i]=s.default end
      check(args[i],s)
    end
    args.n=#spec.args
    for _,name in ipairs(spec.requires or {}) do if not services[name] then error("Undeclared dependent service: "..name) end end
    if spec.resource then resource(spec.resource.kind,args[spec.resource.arg]) end
  end
  local function claim(pin,owner)
    if pins[pin] and pins[pin]~=owner then return nil,"busy" end
    pins[pin]=owner;return true
  end
  local function release(owner) for pin,v in pairs(pins) do if v==owner then pins[pin]=nil end end end
  local function payload(job)
    local a,k=job.args,job.kind
    if k=='ai.request' then
      if job.fixture_bytes>ai_limits.result_bytes then return {ok=false,error_code='result_too_large'} end
      return {ok=true,data=job.fixture}
    end
    if k=="i2c.scan" then return {ok=true,addresses={64,104,117}} end
    if k=="wifi.scan" then return {ok=true,networks={{ssid="PC-SIMULATED",rssi=-55,secure=true}}} end
    if k=="wifi.connect" then return {ok=true,connected=true,ssid="PC-SIMULATED",ip="192.0.2.1",rssi=-55} end
    if k=="wifi.request" then return {ok=true,status=200,body="simulated response"} end
    if k=="bluetooth.scan" then return {ok=true,devices={{name="PC-SIMULATED",address="00:00:00:00:00:01",rssi=-55}}} end
    if k=="bluetooth.connect" or k=="bluetooth.advertise" then
      local count=0;for _ in pairs(handles) do count=count+1 end
      if count>=4 then return {ok=false,error_code="busy"} end
      next_handle=next_handle+1;handles[next_handle]=true;return {ok=true,handle=next_handle}
    end
    if k=="sd.write" then files[a[1]]=(a[3] and files[a[1]] or "")..a[2];return {ok=true,written=#a[2]} end
    if k=="sd.remove" then files[a[1]]=nil;return {ok=true} end
    if k=="sd.read" and files[a[1]]==nil then return {ok=false,error_code="not_found"} end
    if k=="sd.list" then
      local entries={};for path,data in pairs(files) do if #entries<32 then entries[#entries+1]={name=path,size_bytes=#data,is_directory=false} end end
      return {ok=true,entries=entries}
    end
    if k=="mic.record" then files[a[1]]="PC WAV fixture";return {ok=true,path=a[1],size_bytes=a[2]*a[3]//500,sample_rate=a[3]} end
    if k=="uart.read" or k=="bluetooth.read" then return {ok=true,text="FIRE\r\n",bytes={70,73,82,69,13,10}} end
    if job.result=="bytes" then
      local bytes={};local count=16
      if k=="i2c.read" then count=a[4] elseif k=="spi.transfer" then count=#a[2] elseif k=="sd.read" then count=a[3] end
      local text=k=="sd.read" and string.sub(files[a[1]] or "",a[2]+1,a[2]+count) or ""
      if k=="sd.read" then count=#text end
      for i=1,count do bytes[i]=k=="sd.read" and string.byte(text,i) or 0 end
      return {ok=true,bytes=bytes,text=text}
    end
    return {ok=true,written=type(a[#a])=="string" and #a[#a] or 0}
  end
  local function poll(job)
    if not job then return {state="failed",done=true,error_code="invalid_handle"} end
    local delay=job.kind=="mic.record" and job.args[2] or job.kind=="speaker.tone" and job.args[2] or 32
    if job.state=="pending" and now()-job.at>=delay then
      if profile=="io_timeout" and now()-job.at<(job.kind=='ai.request' and job.args[4] or 3000) then return {state="pending",done=false,error_code=""} end
      local fault=profile=="io_error" and "io_error" or profile=="io_disconnect" and "disconnected" or profile=="io_timeout" and "timeout" or nil
      if fault then job.state="failed";job.data={ok=false,error_code=fault}
      else job.data=payload(job);job.state=job.data.ok and "ready" or "failed" end
    end
    return {state=job.state,done=job.state~="pending",error_code=job.data and job.data.error_code or ""}
  end
  local function invoke(service,name,spec,...)
    local a=table.pack(...);args_ok(a,spec)
    local k=service.."."..name
    calls[k]=(calls[k] or 0)+1
    if k=="power.brightness" then error("OS backlight setting is authoritative; apps must not override brightness") end
    local bytes=0;for i=1,a.n do if type(a[i])=="string" or type(a[i])=="table" then bytes=bytes+#a[i] end end
    note(k,bytes)
    local ai_fixture,ai_size
    if k=='ai.request' then
      if phase()~='update' and phase()~='on_button' then return nil,'stale_run' end
      if bytes>ai_limits.request_bytes then return nil,'payload_too_large' end
      local err;ai_fixture,err,ai_size=runtime_ai_parser(a[2],a[3],ai_limits)
      if not ai_fixture then return nil,err end
      for _,job in pairs(jobs) do if job.kind==k and job.state=='pending' then return nil,'busy' end end
    end
    if service=="jobs" then
      local job=jobs[a[1]]
      if name=="poll" then return poll(job) end
      if name=="result" then
        local status=poll(job)
        return status.done and (job and job.data or {ok=false,error_code="invalid_handle"}) or {ok=false,error_code="not_ready"}
      end
      if not job then return false end
      if name=="cancel" then job.state="cancelled";job.data={ok=false,error_code="cancelled"};return true end
      jobs[a[1]]=nil;active_jobs=active_jobs-1;return true
    end
    local cleanup=name=="close" or name=="stop" or name=="release"
    if spec.returns~="job" and not cleanup and (profile=="io_error" or profile=="io_disconnect") then
      return nil,profile=="io_error" and "io_error" or "disconnected"
    end
    if service=="gpio" then
      if name=="mode" then
        local kind=(a[2]=="output" or a[2]=="open_drain") and "gpio_write" or "gpio_read";resource(kind,a[1])
        if a[1]>=34 and a[2]~="input" then error("Input-only GPIO has no internal pull resistor") end
        local ok,err=claim(a[1],"gpio");if ok then gpio_modes[a[1]]=a[2] end;return ok,err
      elseif name=="release" then
        if not contains(resources.gpio_read,a[1]) and not contains(resources.gpio_write,a[1]) then error("Unannounced GPIO resource") end
        if pins[a[1]]=="gpio" then pins[a[1]]=nil;gpio_modes[a[1]]=nil end;return true
      elseif pins[a[1]]~="gpio" then return nil,"not_open"
      elseif name=="write" and gpio_modes[a[1]]~="output" and gpio_modes[a[1]]~="open_drain" then return nil,"read_only"
      elseif name=="write" then gpio_values[a[1]]=a[2];return true
      elseif name=="read" then return gpio_values[a[1]] or 0
      end
    elseif service=="uart" and name=="open" then
      resource("gpio_read",a[3]);resource("gpio_write",a[4])
      if a[3]==a[4] then error("UART RX and TX must differ") end
      if pins[a[3]] and pins[a[3]]~="uart"..a[1] or pins[a[4]] and pins[a[4]]~="uart"..a[1] then return nil,"busy" end
      claim(a[3],"uart"..a[1]);claim(a[4],"uart"..a[1]);uart[a[1]]=true;return true
    elseif service=="uart" and name=="close" then uart[a[1]]=nil;release("uart"..a[1]);return true
    elseif service=="spi" and name=="open" then
      resource("gpio_read",a[3]);for _,i in ipairs({2,4,5}) do resource("gpio_write",a[i]) end
      local seen={};for i=2,5 do if seen[a[i]] then error("SPI pins must differ") end;seen[a[i]]=true end
      for i=2,5 do if pins[a[i]] and pins[a[i]]~="spi"..a[1] then return nil,"busy" end end
      for i=2,5 do claim(a[i],"spi"..a[1]) end;spi[a[1]]=true;return true
    elseif service=="spi" and name=="close" then spi[a[1]]=nil;release("spi"..a[1]);return true
    elseif service=="pwm" then
      if name=="configure" then
        if a[2]*2^a[3]>40000000 then error("PWM frequency/resolution conflict") end
        local ok,err=claim(a[1],"pwm");if not ok then return nil,err end;pwm[a[1]]=a[3];return true
      elseif name=="write" then if not pwm[a[1]] or a[2]>=2^pwm[a[1]] then error("PWM must be configured with a valid duty") end
      else pwm[a[1]]=nil;if pins[a[1]]=="pwm" then pins[a[1]]=nil end;return true end
    elseif service=="dac" and name=="stop" then resource("dac",a[1]);if pins[a[1]]=="dac" then pins[a[1]]=nil end;return true
    elseif service=="dac" then local ok,err=claim(a[1],"dac");if not ok then return nil,err end
    end
    if service=="uart" and not uart[a[1]] then return nil,"not_open" end
    if service=="spi" and not spi[a[1]] then return nil,"not_open" end
    if service=="adc" and pins[a[1]] then return nil,"busy" end
    if service=="bluetooth" and (name=="read" or name=="write" or name=="close") then
      if not handles[a[1]] then return nil,"invalid_handle" end
      if name=="close" then handles[a[1]]=nil;return true end
    end
    if k=="i2c.write" then resource("i2c_write_addresses",a[2]) end
    if service=="sd" and name=="remove" and a[1]=="" then error("Cannot remove app root") end
    if spec.returns=="job" then
      if active_jobs>=4 then return nil,"busy" end
      next_job=next_job+1;if next_job>65535 then error("Job ID budget exceeded") end
      jobs[next_job]={state="pending",at=now(),kind=k,args=a,result=spec.result,fixture=ai_fixture,fixture_bytes=ai_size}
      jobs_started[k]=(jobs_started[k] or 0)+1
      active_jobs=active_jobs+1;peak_jobs=math.max(peak_jobs,active_jobs);return next_job
    end
    if spec.returns=="boolean" then return true end
    if spec.returns=="integer" then return service=="adc" and 2048 or 1 end
    if spec.returns=="number" then return service=="mic" and 0.2 or 25 end
    if spec.returns=="vector" then return {x=0,y=0,z=0} end
    if spec.returns=="wifi_status" then return {connected=true,ssid="PC-SIMULATED",ip="192.0.2.1",rssi=-55} end
    if spec.returns=="power_status" then return {battery_percent=75,voltage=3.9,charging=false,usb=true} end
    if spec.returns=="clock" then return {epoch=1795305600,year=2026,month=11,day=22,hour=0,minute=0,second=0} end
  end
  for service,methods in pairs(specs) do
    available[service]=available[service] or {}
    for name,spec in pairs(methods) do
      if not available[service][name] and service~="display" then
        available[service][name]=function(...) return invoke(service,name,spec,...) end
      end
    end
  end
  local function limited(s) if type(s)~="string" or #s>512 then error("String exceeds safe API limit") end;return s end
  local safe_string={len=function(s)return #limited(s) end,sub=function(s,a,b)return string.sub(limited(s),a,b) end,
    byte=function(s,a,b)return string.byte(limited(s),a,b) end,
    char=function(...) if select("#",...)>128 then error("String char limit") end;return string.char(...) end}
  local safe_table={}
  for _,name in ipairs({"concat","insert","remove"}) do safe_table[name]=function(t,...)
    if type(t)~="table" or #t>128 or name=="insert" and #t>=128 then error("Table helper size limit") end
    if name=="concat" then
      local sep=select(1,...) or "";limited(sep)
      local size=math.max(0,#t-1)*#sep;for _,s in ipairs(t) do size=size+#tostring(s) end
      if size>512 then error("Table concat size limit") end
    end
    local result=table[name](t,...)
    if name=="concat" then limited(result) end
    return result
  end end
  return {begin_callback=function()io_calls,io_bytes=0,0 end,string=safe_string,table=safe_table,
    charge_sdk=function(name,bytes)local k="display."..name;calls[k]=(calls[k] or 0)+1;note(k,bytes,true)end,
    charge_base=function(name,bytes)calls[name]=(calls[name] or 0)+1;note(name,bytes,true)end,
    metrics=function()
      local resources_used={};for kind,values in pairs(used) do local list={};for v in pairs(values) do list[#list+1]=v end;table.sort(list);resources_used[kind]=list end
      return {resources_used=resources_used,max_io_calls=peak_io,max_io_bytes=peak_bytes,max_jobs=peak_jobs,calls=calls,jobs_started=jobs_started}
    end}
end
