-- Handwritten integration fixture, not AI-generated or physically verified.
local ui=fire.ui
local position,target,score,elapsed=2,3,0,0
local job=nil
local last_data=nil
local label='Lokal: gå til høyre'
function init() ui.set_theme('neon') end
function on_button(b,action)
 if action~='pressed' then return end
 if b=='A' then position=math.max(1,position-1)
 elseif b=='C' then position=math.min(3,position+1)
 elseif b=='B' and not job then
  local data='{"position":'..tostring(position)..',"score":'..tostring(score)..'}'
  if data==last_data then return end
  local schema='{"type":"object","properties":{"target":{"type":"integer","minimum":1,"maximum":3},"label":{"type":"string","maxLength":24}},"required":["target","label"],"additionalProperties":false}'
  job=fire.ai.request('Velg et nytt lite spilloppdrag i felt1..3. Bruk en kort norsk etikett uten emoji eller Markdown.',data,schema,30000)
  label=job and 'AI: lager oppdrag' or 'Lokal: gå til målet'
  if job then last_data=data end
 end
 if position==target then score=score+1;target=4-target end
end
function update(dt)
 elapsed=elapsed+dt
 if job and elapsed>=150 then
  elapsed=0;local state=fire.jobs.poll(job)
  if state.done then
   local result=fire.jobs.result(job);fire.jobs.close(job);job=nil
   if result.ok and result.data then target=result.data.target;label='AI: '..result.data.label
   else label='Lokal: prøv AI igjen';last_data=nil end
  end
 end
 local c=ui.theme();ui.screen('OPPDRAGSJAKT',label)
 ui.label(12,62,'POENG '..tostring(score),{width=296,font='ui16'})
 for i=1,3 do
  fire.display.round_rect(14+(i-1)*102,105,86,65,6,i==target and c.good or c.panel,true)
  if i==position then ui.icon(40+(i-1)*102,122,'icon.star',i==target and c.bg or c.accent) end
 end
 ui.label(12,184,'AI er valgfritt; lokal lek virker',{width=296,font='ui12'})
 ui.buttons('Venstre','AI-oppdrag','Høyre','B')
end
