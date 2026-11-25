-- Handwritten integration fixture, not AI-generated or physically verified.
local ui=fire.ui
local elapsed,samples,total,norm=0,0,0,nil
local job=nil
local last_data=nil
local cached_assessment=nil
local status='B: analyser måling'
local assessment='Lokal: måler tyngdekraft'
function init() ui.set_theme('professional_instrument') end
function on_button(b,action)
 if action~='pressed' then return end
 if b=='A' then
  if job then fire.jobs.cancel(job);fire.jobs.close(job);job=nil end
  assessment='Lokal: måler tyngdekraft';status='B: analyser måling'
 elseif b=='B' and not job then
  if samples<16 or not norm then status='Samler gyldige målinger';return end
  local mean=total/samples
  local data='{"norm_g":'..tostring(math.floor(mean*1000)/1000)..',"samples":'..tostring(samples)..'}'
  if data==last_data then assessment=cached_assessment or assessment;status='Viser siste AI-vurdering';return end
  local schema='{"type":"object","properties":{"status":{"type":"string","enum":["normal","sjekk"]},"vurdering":{"type":"string","maxLength":40}},"required":["status","vurdering"],"additionalProperties":false}'
  job=fire.ai.request('Vurder IMU-norm i g. Dette er observerte målinger, ikke en kalibrering. Gi en kort norsk vurdering. Ikke påstå fysisk verifisering.',data,schema,30000)
  status=job and 'AI: analyserer' or 'Lokal: AI utilgjengelig'
  if job then last_data=data end
 elseif b=='C' then
  if job then fire.jobs.cancel(job);fire.jobs.close(job);job=nil end
  samples,total,norm=0,0,nil;last_data=nil;cached_assessment=nil
  assessment='Lokal: samler nye prøver';status='Måling nullstilt'
 end
end
function update(dt)
 elapsed=elapsed+dt
 if elapsed>=150 then
  elapsed=0;local a=fire.imu.accel()
  if type(a)=='table' and type(a.x)=='number' and type(a.y)=='number' and type(a.z)=='number' and
      a.x==a.x and a.y==a.y and a.z==a.z and math.abs(a.x)<=1000 and math.abs(a.y)<=1000 and math.abs(a.z)<=1000 then
   norm=math.sqrt(a.x*a.x+a.y*a.y+a.z*a.z)
   if norm>0.0001 and samples<16 then samples=samples+1;total=total+norm end
  else norm=nil;status='Lokal: sensor ikke klar' end
  if job then
   local state=fire.jobs.poll(job)
   if state.done then
    local result=fire.jobs.result(job);fire.jobs.close(job);job=nil
    if result.ok and result.data then assessment='AI: '..result.data.vurdering;cached_assessment=assessment;status='AI-vurdering klar'
    else status='Lokal: prøv AI igjen';last_data=nil end
   end
  end
 end
 ui.screen('MALEANALYSE',status)
 local measured=samples>0 and tostring(math.floor(total/samples*1000)/1000)..' g' or 'Ingen måling'
 ui.card(10,57,300,77,'SNITT / '..tostring(samples)..' AV 16 PRØVER',measured,{icon='icon.activity'})
 ui.label(12,148,assessment,{width=296,font='ui12'})
 ui.label(12,174,'AI er et råd, ikke en måling',{width=296,font='ui12'})
 ui.buttons('Lokal','Analyser','Nullstill','B')
end
