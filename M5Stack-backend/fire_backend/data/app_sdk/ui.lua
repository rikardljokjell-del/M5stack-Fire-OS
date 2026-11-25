-- FIRE UI Kit 1.0. Trusted, app-private prelude. No I/O, loader or framebuffer.
local ui = {version="fire-app-sdk-1.0"}
local d, floor, min, max = fire.display, math.floor, math.min, math.max
local themes = {
 modern_dark={bg=2113,panel=6339,fg=65535,muted=35921,accent=1983,good=2024,bad=64170,border=10597},
 modern_light={bg=63422,panel=65535,fg=4258,muted=25388,accent=978,good=998,bad=49671,border=52857},
 minimal={bg=65535,panel=65535,fg=0,muted=29582,accent=0,good=1094,bad=51720,border=57083},
 professional_instrument={bg=2145,panel=4258,fg=65470,muted=33840,accent=64960,good=2024,bad=63488,border=14823},
 industrial={bg=4226,panel=10565,fg=65470,muted=40179,accent=64960,good=1824,bad=63810,border=23275},
 retro_arcade={bg=2049,panel=6147,fg=65535,muted=38066,accent=63519,good=2016,bad=63488,border=22575},
 pixel_art={bg=2116,panel=8457,fg=65502,muted=35955,accent=64810,good=2000,bad=63530,border=19051},
 sci_fi={bg=2083,panel=4199,fg=55295,muted=31760,accent=2047,good=2032,bad=63855,border=12782},
 adventure={bg=6369,panel=14849,fg=65468,muted=46416,accent=62854,good=26272,bad=60098,border=29444},
 nature={bg=2146,panel=6339,fg=63389,muted=35954,accent=22004,good=2024,bad=64170,border=16937},
 neon={bg=2051,panel=6215,fg=65535,muted=40180,accent=63519,good=2047,bad=64320,border=28787},
 classic_console={bg=8580,panel=16968,fg=65468,muted=48567,accent=64267,good=22240,bad=64268,border=29581}
}
local T=themes.modern_dark
local scratch={}
local widths={ui12=12,ui12b=13,ui16=16,title20=21,digits28=29,pixel8=8,legacy6x8=6}
local measured,measure_cursor={},1
local function n(v,default) local x=tonumber(v); if not x or x~=x or x>1000000000 or x< -1000000000 then return default or 0 end; return x end
local function clamp(v,a,b) return min(b,max(a,n(v,a))) end
local function integer(v) return floor(n(v)+0.5) end
local function text(x,y,s,color,font,width,align)
 s=tostring(s or ""); font=font or "ui12"; width=max(1,integer(width or 300))
 if font~="ui12" and #s*(widths[font] or 32)>width then
  local actual=nil
  for i=1,#measured do local m=measured[i]; if m[1]==s and m[2]==font then actual=m[3]; break end end
  if not actual then
   actual=d.measure_text(s,font); measured[measure_cursor]={s,font,actual}; measure_cursor=measure_cursor%8+1
  end
  if actual>width then font="ui12" end
 end
 d.text_style(integer(x),integer(y),s,color or T.fg,font,align or "left",width)
end
local function panel(x,y,w,h,color,r)
 local width,height=max(0,integer(w)),max(0,integer(h))
 if width==0 or height==0 then return end
 d.round_rect(integer(x),integer(y),width,height,min(r or 6,floor(min(width,height)/2)),color or T.panel,true)
end
local function ratio(v,lo,hi) if hi<=lo then return 0 end; return clamp((n(v)-lo)/(hi-lo),0,1) end
local function pad(v) local s=tostring(floor(max(0,n(v)))); if v<10 then return "0"..s end; return s end

function ui.set_theme(name) T=themes[name] or themes.modern_dark; return T end
function ui.theme(name) return themes[name] or T end
function ui.background(color) d.clear(color or T.bg) end
function ui.label(x,y,value,options)
 local o=options or {}; text(x,y,value,o.color,o.font,o.width,o.align)
end
function ui.title(title,subtitle)
 text(12,5,title,T.fg,"title20",296)
 if subtitle then text(12,32,subtitle,T.muted,"ui12",296) end
end
function ui.screen(title,subtitle) ui.background(); ui.title(title,subtitle) end
function ui.icon(x,y,id,color,scale) d.asset(integer(x),integer(y),id,scale or 1,color or T.accent,false,false) end
function ui.panel(x,y,w,h,options)
 local o=options or {}; panel(x,y,w,h,o.color,o.radius)
 if o.border and w>0 and h>0 then d.round_rect(integer(x),integer(y),integer(w),integer(h),min(o.radius or 6,floor(min(w,h)/2)),o.border,false) end
end
function ui.card(x,y,w,h,label,value,options)
 local o=options or {}; panel(x,y,w,h,o.background)
 if o.icon then ui.icon(x+w-34,y+6,o.icon,o.accent or T.accent) end
 text(x+10,y+7,label,T.muted,"ui12",w-(o.icon and 52 or 20))
 text(x+10,y+28,value,o.color or T.fg,o.font or "title20",w-20)
 if o.detail then text(x+10,y+h-20,o.detail,T.muted,"ui12",w-20) end
end
function ui.button(x,y,w,label,focused,options)
 local o=options or {}; panel(x,y,w,o.height or 25,focused and T.accent or T.panel,4)
 text(x+5,y+4,label,focused and T.bg or T.fg,"ui12b",w-10,"center")
end
function ui.buttons(a,b,c,focused)
 if a then ui.button(5,211,100,a,focused=="A") end
 if b then ui.button(110,211,100,b,focused=="B") end
 if c then ui.button(215,211,100,c,focused=="C") end
end
function ui.tabs(labels,selected,x,y,w)
 x=x or 8; y=y or 43; w=w or 304
 local count=min(#labels,6); if count<1 then return end
 local span=floor(w/count)
 for i=1,count do ui.button(x+(i-1)*span,y,span-3,labels[i],i==selected,{height=24}) end
end
function ui.menu(items,selected,x,y,w,visible)
 x=x or 10; y=y or 48; w=w or 300; visible=min(6,max(1,visible or 5))
 selected=max(1,min(#items,selected or 1)); local start=floor((selected-1)/visible)*visible+1
 for row=0,visible-1 do
  local i=start+row; if i>#items then break end
  local item=items[i]; local label=type(item)=="table" and item.label or item
  ui.button(x,y+row*30,w,label,i==selected,{height=27})
 end
end
function ui.toggle(x,y,label,on,w)
 w=w or 280; text(x,y,label,T.fg,"ui12",w-48)
 panel(x+w-40,y,38,19,on and T.accent or T.border,9)
 d.arc(integer(x+w-(on and 11 or 29)),integer(y+9),6,0,360,on and T.bg or T.muted,6)
end
function ui.checkbox(x,y,label,checked)
 d.round_rect(integer(x),integer(y),17,17,3,checked and T.accent or T.border,checked or false)
 if checked then d.polyline({integer(x+3),integer(y+8),integer(x+7),integer(y+12),integer(x+14),integer(y+4)},T.bg,false) end
 text(x+25,y,label,T.fg,"ui12",270)
end
function ui.selector(x,y,w,label,value,focused)
 panel(x,y,w,40,focused and T.border or T.panel)
 text(x+8,y+3,label,T.muted,"ui12",w-16)
 text(x+8,y+17,value,T.fg,"ui16",w-16)
end
function ui.dialog(title,message,confirm,cancel)
 panel(18,54,284,140,T.border,9); panel(20,56,280,136,T.panel,8)
 text(32,65,title,T.fg,"title20",256)
 text(32,101,message,T.muted,"ui12",256)
 ui.button(32,151,120,cancel or "Tilbake",false)
 ui.button(168,151,120,confirm or "OK",true)
end
function ui.toast(message,kind)
 local c=kind=="error" and T.bad or kind=="success" and T.good or T.accent
 panel(10,178,300,26,c,5); text(18,183,message,T.bg,"ui12b",284)
end
function ui.progress(x,y,w,h,value,options)
 local o=options or {}; panel(x,y,w,h,o.track or T.border,min(4,floor(h/2)))
 local fill=integer(w*clamp(value,0,1))
 if fill>0 then panel(x,y,fill,h,o.color or T.accent,min(4,floor(h/2))) end
end
function ui.loading(title,phase)
 ui.screen(title or "Laster"); ui.ring(160,112,30,phase or 0,{thickness=4})
 text(30,160,"Vent litt",T.muted,"ui12",260,"center")
end
function ui.ring(x,y,r,value,options)
 local o=options or {}; local thickness=o.thickness or max(2,floor(r/7))
 d.arc(integer(x),integer(y),integer(r),0,360,o.track or T.border,thickness)
 local angle=integer(360*clamp(value,0,1)); if angle>0 then d.arc(integer(x),integer(y),integer(r),0,angle,o.color or T.accent,thickness) end
 if o.label then text(x-r,y-9,o.label,T.fg,o.font or "ui16",r*2,"center") end
end
function ui.gauge(x,y,r,value,minimum,maximum,label,options)
 local o=options or {}; local v=ratio(value,minimum,maximum)
 d.arc(integer(x),integer(y),integer(r),135,360,T.border,o.thickness or 5)
 d.arc(integer(x),integer(y),integer(r),0,45,T.border,o.thickness or 5)
 local a=(135+270*v)*math.pi/180
 d.polyline({integer(x),integer(y),integer(x+math.cos(a)*(r-8)),integer(y+math.sin(a)*(r-8))},o.color or T.accent,false)
 d.arc(integer(x),integer(y),3,0,360,T.fg,3)
 text(x-r,y+10,value,T.fg,"title20",r*2,"center")
 if label then text(x-r,y+36,label,T.muted,"ui12",r*2,"center") end
end
function ui.battery(x,y,value,w,h)
 w=w or 35; h=h or 16; d.round_rect(integer(x),integer(y),w,h,2,T.muted,false)
 panel(x+w,y+h/3,3,max(1,integer(h/3)),T.muted,0)
 local fill=integer((w-6)*clamp(value,0,1)); if fill>0 then panel(x+3,y+3,fill,h-6,value<0.2 and T.bad or T.good,0) end
end
function ui.signal(x,y,value)
 for i=1,4 do panel(x+(i-1)*5,y+16-i*4,3,i*4,i/4<=value and T.accent or T.border,0) end
end
function ui.line_chart(x,y,w,h,values,minimum,maximum,options)
 local o=options or {}; local count=min(#values,64); if count<2 then return end
 panel(x,y,w,h,o.background)
 for i=1,count do
  scratch[i*2-1]=integer(x+4+(i-1)*(w-8)/(count-1))
  scratch[i*2]=integer(y+h-5-ratio(values[i],minimum,maximum)*(h-10))
 end
 for i=count*2+1,#scratch do scratch[i]=nil end
 d.polyline(scratch,o.color or T.accent,false)
end
function ui.bar_chart(x,y,w,h,values,maximum,options)
 local o=options or {}; local count=min(#values,16); if count==0 then return end
 panel(x,y,w,h,o.background); local span=floor((w-8)/count)
 for i=1,count do
  local bh=integer((h-10)*ratio(values[i],0,maximum))
  if bh>0 then panel(x+4+(i-1)*span,y+h-5-bh,max(1,span-3),bh,o.color or T.accent,2) end
 end
end
function ui.clock(x,y,hour,minute,second,options)
 local o=options or {}; local s=pad(hour)..":"..pad(minute)
 if second then s=s..":"..pad(second) end
 text(x,y,s,o.color or T.fg,o.font or "digits28",o.width or 280,o.align)
end
function ui.timer(x,y,milliseconds,options)
 local seconds=floor(max(0,milliseconds)/1000)
 ui.clock(x,y,floor(seconds/3600),floor(seconds/60)%60,seconds%60,options)
end
function ui.hud(score,lives,level)
 panel(0,0,320,29,T.panel,0)
 text(8,5,"POENG "..tostring(score),T.fg,"ui12b",150)
 if lives then text(155,5,"LIV "..tostring(lives),T.accent,"ui12b",83) end
 if level then text(241,5,"N "..tostring(level),T.muted,"ui12",70) end
end
function ui.game_menu(title,subtitle,selected)
 ui.screen(title,subtitle); ui.menu({"Start","Innstillinger","Tilbake"},selected,40,79,240,3)
 ui.buttons("Forrige","Velg","Neste","B")
end
function ui.pause() ui.dialog("Pause","Klar nar du er","Fortsett","Avslutt") end
function ui.game_over(score,best)
 ui.screen("GAME OVER"); ui.card(32,63,256,102,"POENG",score,{font="digits28",detail=best and "REKORD "..tostring(best) or nil})
 ui.buttons("Tilbake","Igjen",nil,"B")
end
local animations={
 ["alien.walk"]={"pixel-platformer.024","pixel-platformer.025"},
 ["coin.spin"]={"pixel-platformer.202","pixel-platformer.203"},
 ["flag.wave"]={"pixel-platformer.162","pixel-platformer.163"}
}
function ui.sprite(x,y,id,milliseconds,options)
 local o=options or {}; local frames=animations[id]
 if frames then id=frames[floor(max(0,milliseconds or 0)*(o.fps or 6)/1000)%#frames+1] end
 d.asset(integer(x),integer(y),id,o.scale or 1,o.tint,o.flip_x or false,o.flip_y or false)
end
function ui.collides(ax,ay,aw,ah,bx,by,bw,bh) return ax<bx+bw and bx<ax+aw and ay<by+bh and by<ay+ah end
function ui.lerp(a,b,t) return a+(b-a)*clamp(t,0,1) end
function ui.ease_out(t) t=1-clamp(t,0,1); return 1-t*t*t end
function ui.animate(elapsed,duration,a,b) return ui.lerp(a,b,ui.ease_out(elapsed/max(1,duration))) end
function ui.burst(particles,x,y,color,count,seed)
 seed=seed or 7
 for i=1,min(16,count or 8) do
  if #particles>=16 then break end
  seed=(seed*109+89)%16381; local angle=seed/16381*math.pi*2
  particles[#particles+1]={x=x,y=y,vx=math.cos(angle)*32,vy=math.sin(angle)*32,age=0,color=color or T.accent}
 end
end
function ui.particles(particles,dt)
 local write=1
 for i=1,min(#particles,16) do
  local p=particles[i]; p.age=p.age+max(0,min(dt,100))
  if p.age<500 then
   p.x=p.x+p.vx*dt/1000; p.y=p.y+p.vy*dt/1000
   if p.x>=0 and p.x<320 and p.y>=0 and p.y<240 then d.fill_circle(floor(p.x),floor(p.y),p.age<200 and 2 or 1,p.color) end
   particles[write]=p; write=write+1
  end
 end
 for i=write,#particles do particles[i]=nil end
end
function ui.layout(name,index)
 index=max(1,floor(index or 1))
 if name=="dashboard" or name=="sensor_monitor" or name=="control_panel" then
  local i=(index-1)%4; return 10+(i%2)*155,48+floor(i/2)*80,145,73
 elseif name=="instrument" then return 160,112,65,65
 elseif name=="graph" then return 10,52,300,146
 elseif name=="clock" then return 20,86,280,90
 elseif name=="calculator" then return 10,46,300,155
 elseif name=="list" or name=="settings" then return 10,48,300,150
 elseif name=="racing" then return 70,30,180,178
 elseif name=="puzzle" then return 64,32,192,176
 else return 8,32,304,176 end
end
function ui.table(x,y,w,rows,columns,selected)
 local count=min(#rows,5); columns=min(3,max(1,columns or 2)); local span=floor(w/columns)
 for r=1,count do
  panel(x,y+(r-1)*28,w,25,r==selected and T.border or T.panel,3)
  for c=1,columns do text(x+6+(c-1)*span,y+4+(r-1)*28,rows[r][c] or "",c==1 and T.fg or T.muted,"ui12",span-12) end
 end
end
function ui.empty(title,message,icon)
 if icon then ui.icon(148,74,icon,T.muted) end
 text(24,107,title,T.fg,"ui16",272,"center")
 if message then text(24,134,message,T.muted,"ui12",272,"center") end
end
function ui.error(message) ui.dialog("Kunne ikke fullfore",message,"Prov igjen","Tilbake") end
function ui.compass(x,y,r,heading)
 d.arc(integer(x),integer(y),integer(r),0,360,T.border,2)
 local angle=(heading-90)*math.pi/180
 local tipx,tipy=integer(x+math.cos(angle)*(r-9)),integer(y+math.sin(angle)*(r-9))
 local sidex,sidey=math.cos(angle+math.pi/2)*6,math.sin(angle+math.pi/2)*6
 d.triangle(tipx,tipy,integer(x+sidex),integer(y+sidey),integer(x-sidex),integer(y-sidey),T.accent,true)
 text(x-8,y-r-16,"N",T.fg,"ui12b",16,"center")
 text(x-r,y+10,tostring(integer(heading%360)).."°",T.muted,"ui12",r*2,"center")
end
function ui.radar(x,y,r,targets,milliseconds)
 for i=1,3 do d.arc(integer(x),integer(y),integer(r*i/3),0,360,T.border,1) end
 local angle=((milliseconds or 0)%3000)/3000*math.pi*2
 d.polyline({integer(x),integer(y),integer(x+math.cos(angle)*r),integer(y+math.sin(angle)*r)},T.accent,false)
 for i=1,min(#targets,8) do
  local point=targets[i]; local px=x+clamp(point[1],-1,1)*r; local py=y+clamp(point[2],-1,1)*r
  if px>=0 and px<320 and py>=0 and py<240 then d.fill_circle(floor(px),floor(py),2,T.good) end
 end
end
function ui.navigate(index,button,count)
 if count<1 then return 1,false end
 if button=="A" then index=(index-2)%count+1 elseif button=="C" then index=index%count+1 end
 return index,button=="B"
end
function ui.countdown(value,x,y)
 text(x or 20,y or 81,value,T.accent,"digits28",280,"center")
end
return ui
