-- Original small SDK example: A/C lane changes, B pause/restart.
local ui=fire.ui
local lane,enemy_lane,distance,offset,score=2,1,0,0,0
local mode="start"
local selected,speed,best=1,2,0
function init() ui.set_theme("retro_arcade") end
function on_button(button,action)
 if action~="pressed" then return end
 if mode=="start" then
  local activate; selected,activate=ui.navigate(selected,button,3)
  if activate then
   if selected==1 then mode="play";distance=0;offset=0;score=0;lane=2;enemy_lane=1
   elseif selected==2 then mode="settings" else mode="help" end
  end
 elseif mode=="settings" then
  if button=="B" then mode="start" else speed=ui.navigate(speed,button,3) end
 elseif mode=="help" then mode="start"
 elseif mode=="over" then
  if button=="A" then mode="start"
  elseif button=="B" then mode="play";distance=0;offset=0;score=0;lane=2;enemy_lane=1 end
 elseif mode=="pause" then
  if button=="A" then mode="start" elseif button=="B" or button=="C" then mode="play" end
 elseif button=="B" then mode="pause"
 elseif mode=="play" then
  if button=="A" then lane=math.max(1,lane-1) elseif button=="C" then lane=math.min(3,lane+1) end
 end
end
function update(dt_ms)
 if mode=="play" then
  distance=distance+dt_ms*0.001*speed;offset=(offset+dt_ms*0.04*speed)%30
  if distance>=180 then distance=0;enemy_lane=enemy_lane%3+1;score=score+10 end
  if distance>119 and distance<160 and lane==enemy_lane then mode="over";best=math.max(best,score) end
 end
 if mode=="start" then
  ui.screen("NATTLØP","Tre felt. Ett forsøk.")
  ui.menu({"Start","Innstillinger","Hjelp"},selected,40,79,240,3)
  ui.buttons("Forrige","Velg","Neste","B")
 elseif mode=="settings" then
  ui.screen("INNSTILLINGER","Velg tempo med A og C")
  ui.selector(20,78,280,"HASTIGHET",({"Rolig","Normal","Rask"})[speed],true)
  ui.buttons("Roligere","Lagre","Raskere","B")
 elseif mode=="help" then
  ui.screen("SLIK SPILLER DU","A og C bytter felt")
  ui.label(20,75,"Unngå den røde bussen.")
  ui.label(20,104,"B pauser. Hold C for å gå ut.")
  ui.buttons(nil,"Til meny",nil,"B")
 elseif mode=="over" then ui.game_over(score,best)
 else
  ui.background();ui.hud(score,1,1)
  for i=0,2 do
   ui.sprite(14,44+i*53,"tiny-town.004",0,{scale=2})
   ui.sprite(274,44+i*53,"tiny-town.004",0,{scale=2})
  end
  fire.display.round_rect(69,31,183,176,0,10565,true)
  fire.display.round_rect(73,31,3,176,0,64960,true)
  fire.display.round_rect(245,31,3,176,0,64960,true)
  for i=0,5 do
   local y=math.floor(34+i*30+offset)
   fire.display.round_rect(130,y,2,12,0,33840,true)
   fire.display.round_rect(190,y,2,12,0,33840,true)
  end
  ui.sprite(82+(lane-1)*60,162,"one-bit.car-top",0,{scale=2,tint=2047})
  ui.sprite(82+(enemy_lane-1)*60,math.floor(32+distance),"one-bit.bus-top",0,{scale=2,tint=64170})
  ui.buttons("Venstre","Pause","Høyre","B")
  if mode=="pause" then ui.pause() end
 end
end
