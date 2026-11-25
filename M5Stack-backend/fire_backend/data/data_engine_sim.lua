-- Private bounded synthetic Data Engine host. No real SD, network or AI.
local function data_engine_factory(services,now,phase,limits,capture)
 local sets,next_id={},0
 local function parse(text)
  return runtime_data_decode(text,{json_depth=limits.json_depth,json_object_keys=limits.json_items,json_array_items=limits.json_items,json_string_bytes=limits.json_string_bytes})
 end
 local function bytes(value)
  if type(value)=='string' then return value end
  local result={};for i=1,#value do result[i]=string.char(value[i]) end;return table.concat(result)
 end
 local function make(label,kind)
  local count=0;for _ in pairs(sets) do count=count+1 end
  if count>=limits.datasets_per_app then return nil,'quota_exceeded' end
  next_id=next_id+1;local id='data-sim-'..next_id
  sets[id]={id=id,label=label,kind=kind,size=0,state='open',prefix=''}
  return sets[id]
 end
 local function info(d)
  return {ok=true,dataset_id=d.id,label=d.label,kind=d.kind,size=d.size,state=d.state,
    sha256=d.state=='sealed' and string.rep('0',64) or ''}
 end
 local function admit(name,a)
  if name=='create' then if not parse(a[3]) then return false,'invalid_json' end
  elseif name=='record' then
   local options=parse(a[2]);if not options then return false,'invalid_json' end
   local allowed=false;for _,source in ipairs(capture.capture_sources or {}) do if source==a[1] then allowed=true end end
   if not allowed then return false,'unsupported_source' end
   local bounds=(capture.capture_limits or {})[a[1]] or {}
   local duration=options.duration_ms or 1000
   if type(duration)~='number' or duration%1~=0 or duration<100 or duration>(bounds.duration_ms_max or 0) then return false,'invalid_argument' end
   if options.sample_rate_hz then
    if type(options.sample_rate_hz)~='number' or options.sample_rate_hz%1~=0 or options.sample_rate_hz<1 then return false,'invalid_argument' end
    if bounds.sample_rate_hz_min and options.sample_rate_hz<bounds.sample_rate_hz_min or bounds.sample_rate_hz_max and options.sample_rate_hz>bounds.sample_rate_hz_max then return false,'invalid_argument' end
    if bounds.sample_rates_hz then local found=false;for _,rate in ipairs(bounds.sample_rates_hz) do if rate==options.sample_rate_hz then found=true end end;if not found then return false,'invalid_argument' end end
   end
   if options.dataset_id then local d=sets[options.dataset_id];if not d or d.state~='open' or d.size~=0 then return false,'invalid_handle' end end
   local service=string.sub(a[1],1,3)=='ble' and 'bluetooth' or string.match(a[1],'^[^.]+')
   if not services[service] then return false,'permission_denied' end
  elseif name=='process' then if not parse(a[3]) then return false,'invalid_json' end
  elseif name=='develop' then return phase()=='on_button',nil end
  if name~='create' and name~='record' and name~='develop' then
   local d=sets[a[1]];if not d then return false,'invalid_handle' end
   if (name=='append' or name=='mark' or name=='seal') and d.state=='sealed' then return false,'sealed' end
   if (name=='process') and d.state~='sealed' then return false,'not_sealed' end
   if name=='read' and a[2]>d.size then return false,'invalid_argument' end
  end
  return true
 end
 local function result(job)
  local name=string.sub(job.kind,6);local a=job.args
  if name=='create' then local d,e=make(a[1],a[2]);return d and {ok=true,dataset_id=d.id,path='datasets/'..d.id,kind=d.kind} or {ok=false,error_code=e} end
  if name=='record' then
   local options=parse(a[2]);local d,e;local source=string.match(a[1],'^[^.]+')
   local kind=source=='mic' and 'audio' or source=='ble' and 'text' or 'csv'
   if options.dataset_id then d=sets[options.dataset_id] else d,e=make('PC recording',kind) end
   if not d then return {ok=false,error_code=e} end
   if d.kind~=kind then return {ok=false,error_code='invalid_data'} end
   local bounds=(capture.capture_limits or {})[a[1]] or {}
   local rate=options.sample_rate_hz or (source=='mic' and 16000 or 100)
   d.samples=source=='ble' and math.min(2,bounds.max_records or 2) or math.floor((options.duration_ms or 1000)*rate/1000)
   if source=='mic' then d.prefix=string.rep(string.char(0),limits.read_bytes)
   elseif source=='ble' then d.prefix='{"t_us":0,"address":"00:00:00:00:00:01","address_type":0,"rssi":-50,"event_type":0,"payload_hex":"020106","adv_length":3}\n'
   else d.prefix='sample_index,ax,ay,az,received_us\n0,0,0,1,0\n1,0,0,1,10000\n' end
   -- Fixture metadata reaches real app sampling thresholds, while raw reads
   -- remain explicitly limited to this tiny known synthetic prefix.
   d.size=math.max(#d.prefix,source=='mic' and d.samples*2 or #d.prefix)
   d.prefix=string.sub(d.prefix,1,limits.read_bytes);d.state='sealed'
   local out=info(d);out.samples=d.samples;out.dropped=0;return out
  end
  local d=sets[a[1]];if not d then return {ok=false,error_code='invalid_handle'} end
  if name=='append' then
   local value=bytes(a[2]);if d.size+#value>limits.dataset_bytes then return {ok=false,error_code='quota_exceeded'} end
   if #d.prefix<limits.read_bytes then d.prefix=string.sub(d.prefix..value,1,limits.read_bytes) end
   d.size=d.size+#value;return {ok=true,dataset_id=d.id,size=d.size}
  elseif name=='mark' then return {ok=true,dataset_id=d.id}
  elseif name=='seal' then d.state='sealed';return info(d)
  elseif name=='info' then return info(d)
  elseif name=='read' then
   local count=math.min(a[3],d.size-a[2]);local out={}
   -- Never invent successful bytes outside the bounded fixture's known prefix.
   if a[2]+count>#d.prefix then return {ok=false,error_code='unavailable'} end
   for i=1,count do out[i]=string.byte(d.prefix,a[2]+i) end
   return {ok=true,bytes=out,offset=a[2],eof=a[2]+count>=d.size}
  elseif name=='process' then return {ok=true,dataset_id=d.id,data={mean=0,rms=1,stddev=1,valid_samples=d.samples or 2,invalid_samples=0}} end
  return {ok=false,error_code='unsupported_operation'}
 end
 return {admit=admit,result=result}
end
