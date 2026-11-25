-- Trusted SDK validation adapter. No Python objects or general loader enters app env.
return function(display, fonts, assets, emit, charge)
 local floor,min,max,ceil=math.floor,math.min,math.max,math.ceil
 local function whole(v,lo,hi)
  if type(v)~="number" or v~=v or v%1~=0 or v<lo or v>hi then error("SDK integer outside bounds") end
  return v
 end
 local function xy(x,y) whole(x,-1024,1024);whole(y,-1024,1024) end
 local function color(c) return whole(c,0,65535) end
 local function boolean(v,default) if v==nil then return default end;if type(v)~="boolean" then error("SDK boolean required") end;return v end
 local function area(x,y,w,h) return max(0,min(320,x+w)-max(0,x))*max(0,min(240,y+h)-max(0,y)) end
 local function rectangle(x,y,w,h)
  xy(x,y);whole(w,1,1024);whole(h,1,1024)
  return area(x,y,w,h)
 end
 local function font(name)
  name=name or "ui16";if type(name)~="string" or not fonts[name] then error("Unknown SDK font") end
  return name,fonts[name]
 end
 local function text_ok(s)
  if type(s)~="string" or #s>80 or string.find(s,"%z") or not utf8.len(s) then error("SDK text must be bounded valid UTF8") end
 end
 local function measure(s,f)
  local width=0
  for _,cp in utf8.codes(s) do width=width+(f.advances[cp] or f.advances[63]) end
  return width,f.line_height
 end
 display.measure_text=function(s,name)
  text_ok(s);local _,f=font(name);charge("measure_text",#s);return measure(s,f)
 end
 display.text_style=function(x,y,s,c,name,align,width)
  xy(x,y);text_ok(s);color(c);local id,f=font(name)
  align=align or "left";width=width or 320;whole(width,1,1024)
  if align~="left" and align~="center" and align~="right" then error("Unknown SDK text alignment") end
  charge("text_style",#s)
  local tw,th=measure(s,f)
  emit("text_style",rectangle(x,y,width,th),#s>0 and c or nil,x,y,s,c,id,align,width)
 end
 display.asset=function(x,y,id,scale,tint,flipx,flipy)
  xy(x,y)
  if type(id)~="string" or not assets[id] then error("Unknown canonical SDK asset ID") end
  scale=scale or 1;whole(scale,1,4)
  local spec=assets[id];local w=spec%256;local h=(spec//256)%256
  if tint~=nil then color(tint);if spec<65536 then tint=nil end end
  flipx=boolean(flipx,false);flipy=boolean(flipy,false)
  charge("asset",#id)
  -- Nil is represented as -1 only in the trusted capture format, never the API.
  emit("asset",rectangle(x,y,w*scale,h*scale),tint or 65535,x,y,id,scale,tint or -1,flipx,flipy)
 end
 display.round_rect=function(x,y,w,h,r,c,filled)
  local work=rectangle(x,y,w,h);whole(r,0,160)
  if r>floor(min(w,h)/2) then error("SDK rounded radius exceeds rectangle") end
  color(c);filled=boolean(filled,false);charge("round_rect",1)
  emit("round_rect",filled and work or min(work,2*(w+h)),c,x,y,w,h,r,c,filled)
 end
 display.triangle=function(x1,y1,x2,y2,x3,y3,c,filled)
  xy(x1,y1);xy(x2,y2);xy(x3,y3);color(c);filled=boolean(filled,false)
  local w,h=max(x1,x2,x3)-min(x1,x2,x3)+1,max(y1,y2,y3)-min(y1,y2,y3)+1
  local work=area(min(x1,x2,x3),min(y1,y2,y3),w,h)
  charge("triangle",1);emit("triangle",filled and work or min(work,2*(w+h)),c,x1,y1,x2,y2,x3,y3,c,filled)
 end
 local function points(values,lo,hi)
  if type(values)~="table" or #values%2~=0 or #values<lo*2 or #values>hi*2 then error("SDK point count outside bounds") end
  local count=0;local minx,miny,maxx,maxy=1024,1024,-1024,-1024
  for k,v in pairs(values) do whole(k,1,#values);whole(v,-1024,1024);count=count+1 end
  if count~=#values then error("SDK points must be dense") end
  for i=1,#values,2 do minx=min(minx,values[i]);maxx=max(maxx,values[i]);miny=min(miny,values[i+1]);maxy=max(maxy,values[i+1]) end
  return area(minx,miny,maxx-minx+1,maxy-miny+1)
 end
 display.polyline=function(values,c,closed)
  local work=points(values,2,64);color(c);closed=boolean(closed,false)
  charge("polyline",#values*2);emit("polyline",min(work,#values*320),c,values,c,closed)
 end
 display.polygon=function(values,c,filled)
  local work=points(values,3,16);color(c);filled=boolean(filled,false)
  charge("polygon",#values*2);emit("polygon",filled and work or min(work,#values*320),c,values,c,filled)
 end
 display.gradient_rect=function(x,y,w,h,c1,c2,vertical)
  local work=rectangle(x,y,w,h);color(c1);color(c2);vertical=boolean(vertical,true)
  charge("gradient_rect",1);emit("gradient_rect",work,c1~=0 and c1 or c2,x,y,w,h,c1,c2,vertical)
 end
 display.arc=function(x,y,r,start,finish,c,thickness)
  xy(x,y);whole(r,1,160);whole(start,0,360);whole(finish,0,360);color(c)
  thickness=thickness or 1;whole(thickness,1,r)
  if finish<start then error("SDK arc end precedes start") end
  charge("arc",1)
  emit("arc",ceil(2*math.pi*r*thickness*(finish-start)/360),finish>start and c or nil,x,y,r,start,finish,c,thickness)
 end
end
