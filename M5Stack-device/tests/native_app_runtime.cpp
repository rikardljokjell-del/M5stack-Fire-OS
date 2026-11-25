#include "fire_lua_runtime.h"
#include "fire_app_sdk_data.h"
#include "fire_app_bitmap.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <string>
#include <array>
#include <fstream>
#include <iterator>
int64_t fireTestClockUs=1000000;
static unsigned calls=0;
static void clear(void*,int) {++calls;}
static void polyline(void*,const int16_t*,size_t,int,bool,bool) {++calls;}
static void grid(void*,int,int,int,int,int,int,const uint8_t*,size_t,const uint16_t*,size_t) {++calls;}
struct Surface {void fillRect(int,int,int,int,uint16_t) {++calls;}};
static bool text(void*,int x,int y,const char* value,size_t length,int color,const char* id,int align,int width) {
  Surface surface;const auto* f=fire_app_bitmap::find(FireSdkData::kFonts,FireSdkData::kFontCount,id);
  return f && fire_app_bitmap::text(surface,*f,x,y,value,length,uint16_t(color),align,width);
}
static bool measure(void*,const char* value,size_t length,const char* id,int* w,int* h) {
  const auto* f=fire_app_bitmap::find(FireSdkData::kFonts,FireSdkData::kFontCount,id);
  return f && fire_app_bitmap::measure(*f,value,length,*w,*h);
}
static bool asset(void*,int,int,const char* id,int,int,bool,bool) {
  ++calls;return fire_app_bitmap::find(FireSdkData::kAssets,FireSdkData::kAssetCount,id)!=nullptr;
}
static void rounded(void*,int,int,int,int,int,int,bool) {++calls;}
static void slow(void*,int) {fireTestClockUs+=13000;}
static FireLuaRuntime::Host host() {
  FireLuaRuntime::Host h;h.appSdkUiSource=FireSdkData::kUiSource;h.appSdkUiBytes=sizeof(FireSdkData::kUiSource)-1;
  h.displayClear=clear;h.displayPolyline=polyline;h.displayTextStyle=text;
  h.displayGrid=grid;
  h.displayMeasureText=measure;h.displayAsset=asset;h.displayRoundRect=rounded;
  return h;
}
static bool run(const std::string& update,bool sdk=true,std::string* error=nullptr) {
  FireLuaRuntime runtime;runtime.setHardwareApi(true);runtime.setAppSdk(sdk);runtime.setServiceMask(31);
  assert(runtime.begin(host()));
  const std::string source="function init() end function update(dt) "+update+" end";
  const bool loaded=runtime.loadSource(reinterpret_cast<const uint8_t*>(source.data()),source.size());
  const bool result=loaded && runtime.update(16);
  if(error) *error=runtime.lastError().c_str();
  assert(runtime.memoryUsed()<=runtime.peakMemoryUsed() && runtime.peakMemoryUsed()<=FireLuaRuntime::kMaxMemoryBytes);
  runtime.stop();assert(runtime.memoryUsed()==0 && runtime.peakMemoryUsed()==0);
  return result;
}

// This canvas and approximate legacy line/circle adapter are HOST TEST ONLY.
// SDK bitmap/geometry paths below use the actual production portable renderer.
// They do not establish physical rendering speed or M5GFX pixel parity.
struct Canvas {
  std::array<uint16_t,320*240> pixels{};
  uint32_t spans=0,painted=0;
  void fillRect(int x,int y,int w,int h,uint16_t color) {
    const auto r=fire_app_graphics::clippedRect(x,y,w,h);
    if(r.w && r.h) {++spans;painted+=uint32_t(r.w)*uint32_t(r.h);}
    for (int py=r.y;py<r.y+r.h;++py)
      for (int px=r.x;px<r.x+r.w;++px) pixels[py*320+px]=color;
  }
  void line(int x,int y,int endX,int endY,uint16_t color) {
    const int dx=abs(endX-x),sx=x<endX?1:-1,dy=-abs(endY-y),sy=y<endY?1:-1;
    int error=dx+dy;
    for (;;) {
      fillRect(x,y,1,1,color);if(x==endX && y==endY) break;
      const int twice=2*error;
      if(twice>=dy) {error+=dy;x+=sx;}
      if(twice<=dx) {error+=dx;y+=sy;}
    }
  }
};
static Canvas canvas;
static void renderedClear(void*,int c) {canvas.fillRect(0,0,320,240,uint16_t(c));}
static bool renderedText(void*,int x,int y,const char* value,size_t length,int color,const char* id,int align,int width) {
  const auto* f=fire_app_bitmap::find(FireSdkData::kFonts,FireSdkData::kFontCount,id);
  return f && fire_app_bitmap::text(canvas,*f,x,y,value,length,uint16_t(color),align,width);
}
static bool renderedAsset(void*,int x,int y,const char* id,int scale,int tint,bool flipX,bool flipY) {
  const auto* a=fire_app_bitmap::find(FireSdkData::kAssets,FireSdkData::kAssetCount,id);
  return a && fire_app_bitmap::asset(canvas,*a,x,y,scale,tint,flipX,flipY);
}
static void renderedRounded(void*,int x,int y,int w,int h,int r,int c,bool filled) {
  fire_app_graphics::roundRect(canvas,x,y,w,h,r,uint16_t(c),filled);
}
static void renderedPoints(void*,const int16_t* values,size_t count,int c,bool closed,bool filled) {
  if(filled) {
    assert(count<=16);fire_app_graphics::Point points[16];
    for(size_t i=0;i<count;++i) points[i]={values[i*2],values[i*2+1]};
    assert(fire_app_graphics::polygon(canvas,points,count,uint16_t(c)));
  } else {
    for(size_t i=1;i<count;++i) canvas.line(values[(i-1)*2],values[(i-1)*2+1],values[i*2],values[i*2+1],uint16_t(c));
    if(closed) canvas.line(values[(count-1)*2],values[(count-1)*2+1],values[0],values[1],uint16_t(c));
  }
}
static void renderedTriangle(void* ctx,int x,int y,int x2,int y2,int x3,int y3,int c,bool filled) {
  const int16_t p[]={int16_t(x),int16_t(y),int16_t(x2),int16_t(y2),int16_t(x3),int16_t(y3)};
  renderedPoints(ctx,p,3,c,true,filled);
}
static void renderedArc(void*,int x,int y,int r,int from,int to,int c,int thickness) {
  fire_app_graphics::arc(canvas,x,y,r,from,to,uint16_t(c),thickness);
}
static void renderedGradient(void*,int x,int y,int w,int h,int a,int b,bool vertical) {
  fire_app_graphics::gradient(canvas,x,y,w,h,uint16_t(a),uint16_t(b),vertical);
}
static void renderedLine(void*,int x,int y,int x2,int y2,int c) {canvas.line(x,y,x2,y2,uint16_t(c));}
static void renderedFillRect(void*,int x,int y,int w,int h,int c) {canvas.fillRect(x,y,w,h,uint16_t(c));}
static void renderedFillCircle(void*,int x,int y,int r,int c) {
  for(int row=-r;row<=r;++row)for(int col=-r;col<=r;++col)
    if(row*row+col*col<=r*r) canvas.fillRect(x+col,y+row,1,1,uint16_t(c));
}
static FireLuaRuntime::Host renderHost() {
  auto h=host();h.displayClear=renderedClear;h.displayTextStyle=renderedText;
  h.displayAsset=renderedAsset;h.displayRoundRect=renderedRounded;
  h.displayPolyline=renderedPoints;h.displayTriangle=renderedTriangle;
  h.displayArc=renderedArc;h.displayGradient=renderedGradient;
  h.displayLine=renderedLine;h.displayFillRect=renderedFillRect;h.displayFillCircle=renderedFillCircle;
  return h;
}
static void fixtureCheck(bool ok,const char* filename,FireLuaRuntime& runtime) {
  if(!ok) fprintf(stderr,"fixture %s phase %s: %s\n",filename,runtime.lastPhase(),runtime.lastError().c_str());
  assert(ok);
}
static void fixture(const char* directory,const char* filename,const char* buttons) {
  const std::string path=std::string(directory)+"/"+filename;
  std::ifstream file(path,std::ios::binary);assert(file.good());
  const std::string source((std::istreambuf_iterator<char>(file)),std::istreambuf_iterator<char>());
  FireLuaRuntime runtime;runtime.setHardwareApi(true);runtime.setAppSdk(true);runtime.setServiceMask(3);
  assert(runtime.begin(renderHost()));
  const size_t registeredBytes=runtime.memoryUsed();
  fixtureCheck(runtime.loadSource(reinterpret_cast<const uint8_t*>(source.data()),source.size()),filename,runtime);
  const size_t loadedBytes=runtime.memoryUsed();
  size_t sampledBytes=loadedBytes;unsigned frames=0;uint32_t maxSpans=0,maxPainted=0;
  const auto update=[&](unsigned dt) {
    canvas.pixels.fill(0); // Same clear-before-every-update lifecycle as FIRE OS.
    canvas.spans=canvas.painted=0; // App paints only; OS clear is excluded.
    fixtureCheck(runtime.update(dt),filename,runtime);++frames;
    sampledBytes=max(sampledBytes,runtime.memoryUsed());
    maxSpans=max(maxSpans,canvas.spans);maxPainted=max(maxPainted,canvas.painted);
    unsigned contrasting=0;for(auto pixel:canvas.pixels) if(pixel!=canvas.pixels[0]) ++contrasting;
    assert(contrasting>32 && sampledBytes<=FireLuaRuntime::kMaxMemoryBytes);
    if(frames%2==1 && !strcmp(filename,"gallery.lua"))
      printf("HOST GALLERY frame=%u native_fill_spans=%u painted_pixels=%u\n",frames,canvas.spans,canvas.painted);
  };
  update(16);
  for(const char* p=buttons;*p;++p) {
    char name[]={*p,0};fixtureCheck(runtime.button(name,"pressed"),filename,runtime);
    update(16);update(100); // Exercise cache fill and a repeated frame.
  }
  assert(runtime.peakMemoryUsed()>=sampledBytes && runtime.peakMemoryUsed()<=FireLuaRuntime::kMaxMemoryBytes);
  printf("HOST FIXTURE %s frames=%u registered_vm_bytes=%zu ui_and_app_loaded_vm_bytes=%zu sampled_vm_bytes=%zu peak_vm_bytes=%zu max_native_fill_spans=%u max_painted_pixels=%u (fake clock; not physical timing)\n",
         filename,frames,registeredBytes,loadedBytes,sampledBytes,runtime.peakMemoryUsed(),maxSpans,maxPainted);
  runtime.stop();assert(runtime.memoryUsed()==0);
}

static void uiLoadMeasurement(bool sdk) {
  FireLuaRuntime runtime;runtime.setHardwareApi(true);runtime.setAppSdk(sdk);runtime.setServiceMask(3);
  assert(runtime.begin(host()));const size_t registered=runtime.memoryUsed();
  const char* empty="function init() end function update(dt) end";
  assert(runtime.loadSource(reinterpret_cast<const uint8_t*>(empty),strlen(empty)));
  printf("HOST UI LOAD sdk=%d pointer_bytes=%zu registered_vm_bytes=%zu ui_and_empty_app_loaded_vm_bytes=%zu peak_vm_bytes=%zu\n",
         int(sdk),sizeof(void*),registered,runtime.memoryUsed(),runtime.peakMemoryUsed());
  runtime.stop();assert(runtime.memoryUsed()==0);
}

int main(int argc,char** argv) {
  static_assert(sizeof(lua_Integer)==4 && sizeof(lua_Number)==4,"match ESP32 Lua numeric profile");
  assert(!strcmp(FireLuaRuntime::hardwareApiContract(),"0b29618a077256268c1dc78512ccf2700517e6c162cbe72f2f4a171dcfc3cd40"));
  assert(!strcmp(FireLuaRuntime::appSdkContract(),FireSdkData::kContract));
  uiLoadMeasurement(false);uiLoadMeasurement(true);
  assert(run("fire.ui.screen('FIRE');fire.ui.card(10,60,300,100,'Status',42)"));
  assert(run("fire.display.polyline({math.floor(1.2),2,3,4},65535)"));
  assert(!run("fire.display.polyline({'1',2,3,4},65535)"));
  assert(!run("fire.display.text_style(0,0,'text',65535,'missing')"));
  assert(!run("fire.display.text_style(0,0,'\\255',65535)"));
  assert(!run("fire.display.text_style(0,0,'x',65535,nil,'bad')"));
  assert(!run("fire.display.asset(0,0,'missing')"));
  assert(!run("fire.display.round_rect(0,0,5,5,3,0,true)"));
  assert(!run("fire.display.polygon({0,0,1,1},0,true)"));
  assert(!run("fire.display.polyline({0,0,1,1},0,1)"));
  assert(!run("fire.display.text_style(0,0,'x',0)",false));
  assert(run("if fire.ui~=nil or fire.display.asset~=nil then fire.display.clear(-1) end",false));
  assert(run("if require or load or package or io or os or debug then fire.display.clear(-1) end"));
  std::string error;calls=0;
  assert(!run("for i=1,65 do fire.display.asset(0,0,'"+std::string(FireSdkData::kAssets[0].id)+"') end",true,&error));
  assert(error.find("budget")!=std::string::npos && calls==64);
  const std::string longText(80,'A');
  assert(!run("for i=1,4 do fire.display.measure_text('"+longText+"') end",true,&error));
  assert(error.find("budget")!=std::string::npos);
  const std::string board="local c={} for i=1,200 do c[i]=0 end fire.display.grid(10,20,8,8,10,20,c,{0}) ";
  assert(run(board));
  assert(!run(board+"fire.display.grid(10,20,8,8,10,20,c,{0})",true,&error));
  assert(error.find("grid callback budget")!=std::string::npos);
  assert(run(board+"fire.display.grid(10,20,8,8,10,20,c,{0})",false));
  assert(!run("local c={} for i=1,200 do c[i]=0 end fire.display.grid(10,20,16,16,10,20,c,{0})",true,&error));
  FireLuaRuntime timed;timed.setHardwareApi(true);timed.setAppSdk(true);auto h=host();h.displayClear=slow;
  assert(timed.begin(h));const char* app="function init() end function update(dt) fire.display.clear(0) end";
  assert(timed.loadSource(reinterpret_cast<const uint8_t*>(app),strlen(app)));
  assert(!timed.update(16) && strstr(timed.lastError().c_str(),"time budget"));timed.stop();
  assert(argc==2);
  fixture(argv[1],"gallery.lua","CCCCCCAAAAAA");
  fixture(argv[1],"stopwatch.lua","BCBABC");
  fixture(argv[1],"racing.lua","BBCBBCACACBCAB");
  puts("PASS production Lua32 SDK gating UI load validation budgets and native elapsed guard");
  puts("PASS canonical SDK gallery six pages, stopwatch and racing fixture interactions");
}
