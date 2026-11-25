-- Original small SDK example: A/C lane changes, B pause/restart.
local ui=fire.ui
local lane,enemy_lane,distance,offset,score=2,1,0,0,0
local mode="start"
function init() ui.set_theme("retro_arcade") end
function on_button(button,action)
 if action~="pressed" then return end
 if button=="B" then
  if mode=="start" or mode=="over" then mode="play";distance=0;offset=0;score=0;lane=2
  elseif mode=="play" then mode="pause" else mode="play" end
 elseif mode=="play" then
  if button=="A" then lane=math.max(1,lane-1) elseif button=="C" then lane=math.min(3,lane+1) end
 end
end
function update(dt_ms)
 if mode=="play" then
  distance=distance+dt_ms*0.002;offset=(offset+dt_ms*0.08)%30
  if distance>=180 then distance=0;enemy_lane=enemy_lane%3+1;score=score+10 end
  if distance>119 and distance<160 and lane==enemy_lane then mode="over" end
 end
 if mode=="start" then ui.game_menu("NATTLØP","Tre felt. Ett forsøk.",1)
 elseif mode=="over" then ui.game_over(score,score)
 else
  ui.background();ui.hud(score,1,1)
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
