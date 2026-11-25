-- SDK visual/regression fixture. Example values are explicitly labelled.
local ui=fire.ui
local page,elapsed=1,0
local samples={12,15,14,21,24,22,28,30,27,32,36,35,39,37,42,46}
local palettes={"modern_dark","professional_instrument","sci_fi","retro_arcade","nature","modern_light"}
local names={"OVERSIKT","INSTRUMENT","GRAF","SPILL","KOMPASS","LYST TEMA"}
function init() ui.set_theme(palettes[page]) end
function on_button(button,action)
 if action~="pressed" then return end
 if button=="A" then page=(page-2)%6+1 elseif button=="C" or button=="B" then page=page%6+1 end
 ui.set_theme(palettes[page])
end
function update(dt_ms)
 elapsed=elapsed+dt_ms
 if page==4 then ui.background() else ui.screen(names[page],"SDK-eksempeldata") end
 if page==1 or page==6 then
  ui.card(10,50,145,72,"TEMPERATUR","21.4°",{icon="icon.thermometer",detail="Eksempel"})
  ui.card(165,50,145,72,"BATTERI","84%",{icon="icon.battery",detail="Eksempel"})
  ui.card(10,130,145,72,"STATUS","Klar",{icon="icon.circle-check"})
  ui.card(165,130,145,72,"FORBRUK","126 W",{icon="icon.zap"})
 elseif page==2 then
  ui.gauge(97,116,56,36,0,60,"VOLT",{color=64960})
  ui.ring(247,108,40,0.72,{label="72%",color=2024,thickness=6})
  ui.progress(191,174,111,9,0.72,{color=2024})
 elseif page==3 then
  ui.line_chart(10,54,300,94,samples,0,50)
  ui.bar_chart(10,157,300,44,{3,7,5,9,6,10,8,12},12)
 elseif page==4 then
  ui.hud(1240,3,2)
  fire.display.gradient_rect(8,38,304,165,2083,6215,true)
  ui.sprite(48,91,"tiny-dungeon.096",elapsed,{scale=3})
  ui.sprite(135,91,"alien.walk",elapsed,{scale=3})
  ui.sprite(228,91,"one-bit.ufo",elapsed,{scale=3,tint=2047})
  ui.sprite(99,160,"coin.spin",elapsed,{scale=2})
  ui.sprite(197,155,"one-bit.car-top",elapsed,{scale=2,tint=64960})
 elseif page==5 then
  ui.compass(85,115,43,(elapsed/50)%360)
  ui.radar(239,116,52,{{0.2,0.4},{-0.5,0.2},{0.1,-0.7}},elapsed)
 end
 ui.buttons("Forrige","Bytt","Neste","B")
end
