local ui=fire.ui
local running,elapsed,laps=false,0,0
function init() ui.set_theme("professional_instrument") end
function on_button(button,action)
 if action~="pressed" then return end
 if button=="B" then running=not running elseif button=="A" then elapsed=0;laps=0 elseif button=="C" and running then laps=laps+1 end
end
function update(dt_ms)
 if running then elapsed=elapsed+dt_ms end
 ui.screen("STOPPEKLOKKE",running and "Måling pågår" or "Klar når du er")
 ui.card(10,54,300,139,"TID", "",{icon="icon.timer"})
 ui.timer(30,102,elapsed,{width=260,align="center"})
 ui.label(22,163,"RUNDER "..tostring(laps),{width=270,color=ui.theme().muted})
 ui.buttons("Nullstill",running and "Pause" or "Start",running and "Runde" or nil,"B")
end
