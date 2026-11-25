#include "fire_lua_runtime.h"
#include "fire_app_sdk_data.h"
#include "fire_app_bitmap.h"
#include "fire_app_frame.h"
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
static void slow(void*,int elapsedUs) {fireTestClockUs+=elapsedUs;}
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
  uint16_t current=0;
  uint32_t spans=0,painted=0;
  void setColor(uint16_t c) {current=c;}
  void fillSprite(uint16_t c) {setColor(c);fillRect(0,0,320,240,c);}
  void fillRect(int x,int y,int w,int h,uint16_t color) {
    current=color;
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
static fire_app_frame::State renderedFrame;
static unsigned framePaintCalls=0,frameClearCalls=0,frameElisions=0;
static void renderedPaint(void*) {++framePaintCalls;renderedFrame.paint();}
static void renderedClear(void*,int c) {
  ++frameClearCalls;const auto spans=canvas.spans;
  renderedFrame.clear(canvas,uint16_t(c),true,true);
  if(canvas.spans==spans) ++frameElisions;
}
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
  auto h=host();h.displayPaint=renderedPaint;h.displayClear=renderedClear;h.displayTextStyle=renderedText;
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
    renderedFrame.invalidate();canvas.fillSprite(runtime.frameBackground());
    renderedFrame.acknowledgePrefill(runtime.frameBackground()); // ONLY after actual OS fill.
    canvas.spans=canvas.painted=0; // App paints only; OS clear is excluded.
    const bool ok=runtime.update(dt);renderedFrame.invalidate();
    fixtureCheck(ok,filename,runtime);++frames;
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

static void prepareFrame(FireLuaRuntime& runtime) {
  renderedFrame.invalidate();canvas.fillSprite(runtime.frameBackground());
  renderedFrame.acknowledgePrefill(runtime.frameBackground());
  framePaintCalls=frameClearCalls=frameElisions=0;
}
static void backgroundTests() {
  FireLuaRuntime runtime;runtime.setHardwareApi(true);runtime.setAppSdk(true);runtime.setServiceMask(3);
  assert(runtime.begin(renderHost()) && runtime.frameBackground()==0);
  const char* source="function init() fire.display.set_background(2113) end "
    "function update(dt) fire.display.set_background(7);fire.buttons.pressed('A');fire.display.measure_text('x');fire.display.clear(2113) end "
    "function on_button(b,a) fire.display.set_background(65535) end";
  assert(runtime.loadSource(reinterpret_cast<const uint8_t*>(source),strlen(source)) && runtime.frameBackground()==2113);
  prepareFrame(runtime);assert(runtime.update(16));renderedFrame.invalidate();
  assert(runtime.frameBackground()==7 && framePaintCalls==0 && frameClearCalls==1 && frameElisions==1);
  assert(canvas.current==2113);for(auto pixel:canvas.pixels) assert(pixel==2113);
  // New preference cannot retroactively acknowledge a different current frame.
  prepareFrame(runtime);assert(runtime.update(16));renderedFrame.invalidate();assert(frameElisions==0);
  assert(runtime.button("B","pressed") && runtime.frameBackground()==65535);
  const char* empty="function init() end function update(dt) end";
  assert(runtime.loadSource(reinterpret_cast<const uint8_t*>(empty),strlen(empty)) && runtime.frameBackground()==0);
  const char* bad="function init() fire.display.set_background(99);fire.display.clear(-1) end function update(dt) end";
  assert(!runtime.loadSource(reinterpret_cast<const uint8_t*>(bad),strlen(bad)) && runtime.frameBackground()==0);
  runtime.stop();assert(runtime.frameBackground()==0);
  runtime.setAppSdk(false);assert(runtime.begin(host()));
  assert(runtime.loadSource(reinterpret_cast<const uint8_t*>(empty),strlen(empty)) && runtime.frameBackground()==0);
  runtime.stop();
  runtime.setAppSdk(true);runtime.setServiceMask(2);assert(runtime.begin(host()));
  const char* denied="function init() end function update(dt) if fire.display~=nil or fire.ui~=nil then fire.display.clear(-1) end end";
  assert(runtime.loadSource(reinterpret_cast<const uint8_t*>(denied),strlen(denied)) && runtime.update(16));
  runtime.stop();runtime.setServiceMask(3);
  assert(run("if fire.display.set_background~=nil then fire.display.clear(-1) end",false));
  assert(!run("fire.display.set_background(0)",false));
  assert(run("fire.display.set_background(65535.0)"));
  for(const char* value:{"'7'","-1","65536","0.5","nil"}) assert(!run(std::string("fire.display.set_background(")+value+")"));
  std::string error;assert(!run("for i=1,65 do fire.display.set_background(0) end",true,&error));assert(error.find("budget")!=std::string::npos);

  const std::string paint[]={"circle(10,10,2,1)","rect(10,10,2,2,1)","line(1,1,2,2,1)","text(0,0,'x',1)",
    "fill_rect(0,0,1,1,1)","fill_circle(10,10,1,1)","pixel(0,0,1)","grid(0,0,1,1,1,1,{0},{1})",
    "text_style(0,0,'',1)",std::string("asset(-1024,-1024,'")+FireSdkData::kAssets[0].id+"')",
    "round_rect(0,0,2,2,0,1,true)","triangle(0,0,1,0,0,1,1,true)","polyline({0,0,1,1},1)",
    "polygon({0,0,1,0,0,1},1,true)","gradient_rect(-1024,-1024,1,1,0,1)","arc(0,0,1,0,0,1,1)"};
  for(const auto& command:paint) {
    runtime.setAppSdk(true);assert(runtime.begin(renderHost()));
    const std::string app="function init() end function update(dt) fire.display."+command+";fire.display.clear(0) end";
    assert(runtime.loadSource(reinterpret_cast<const uint8_t*>(app.data()),app.size()));prepareFrame(runtime);
    assert(runtime.update(16));renderedFrame.invalidate();
    assert(framePaintCalls==1 && frameClearCalls==1 && frameElisions==0);
    for(auto pixel:canvas.pixels) assert(pixel==0);
    runtime.stop();
  }
  runtime.setAppSdk(true);assert(runtime.begin(renderHost()));
  const char* many="function init() end function update(dt) for i=1,65 do fire.display.clear(0) end end";
  assert(runtime.loadSource(reinterpret_cast<const uint8_t*>(many),strlen(many)));prepareFrame(runtime);
  assert(!runtime.update(16));renderedFrame.invalidate();
  assert(frameClearCalls==64 && frameElisions==1 && strstr(runtime.lastError().c_str(),"budget"));runtime.stop();
  puts("PASS SDK background next-frame preference lifecycle,16paint invalidators and unchanged IO quotas");
}

static void instructionResetTest(bool oldSemantics) {
  FireLuaRuntime runtime;runtime.setHardwareApi(true);runtime.setAppSdk(false);
  assert(runtime.begin(host()));
  const char* app="function init() local s=0 for i=1,1024 do s=s+i end end "
    "function update(dt) local s=0 for i=1,1024 do s=s+i end end function on_button(b,a) end";
  assert(runtime.loadSource(reinterpret_cast<const uint8_t*>(app),strlen(app)));
  const auto initInstructions=runtime.instructionCount();assert(initInstructions>=1000);
  assert(runtime.button("B","pressed"));const auto afterInitButton=runtime.instructionCount();
  assert(runtime.update(16));const auto updateInstructions=runtime.instructionCount();assert(updateInstructions>=1000);
  assert(runtime.button("B","pressed"));const auto afterUpdateButton=runtime.instructionCount();
  if(oldSemantics) assert(afterInitButton>=1000 && afterUpdateButton>=updateInstructions);
  else assert(afterInitButton==0 && afterUpdateButton==0);
  printf("PASS %s instruction counter init=%u button_after_init=%u update=%u button_after_update=%u (actual Lua32 fakeclock)\n",
    oldSemantics?"OLD-SEMANTICS reproduced carry":"per-callback reset",initInstructions,afterInitButton,updateInstructions,afterUpdateButton);
  runtime.stop();
}

static void callbackTimingTest(bool sdk,const char* phase,int elapsedUs,bool expected) {
  FireLuaRuntime runtime;runtime.setHardwareApi(true);runtime.setAppSdk(sdk);
  auto h=host();h.displayClear=slow;assert(runtime.begin(h));
  std::string delay;
  for(int remaining=elapsedUs;remaining>0;) {
    const int part=remaining>65535?65535:remaining;
    delay+="fire.display.clear("+std::to_string(part)+");";remaining-=part;
  }
  const std::string source="function init() "+std::string(!strcmp(phase,"init")?delay:"")+" end "
    "function update(dt) "+std::string(!strcmp(phase,"update")?delay:"")+" end "
    "function on_button(b,a) "+std::string(!strcmp(phase,"on_button")?delay:"")+" end";
  const bool loaded=runtime.loadSource(reinterpret_cast<const uint8_t*>(source.data()),source.size());
  bool result=loaded;
  if(strcmp(phase,"init")) {
    assert(loaded);result=!strcmp(phase,"update")?runtime.update(16):runtime.button("B","pressed");
  }
  assert(result==expected && runtime.lastCallbackUs()==uint32_t(elapsedUs));
  if(!expected) assert(strstr(runtime.lastError().c_str(),"time budget") && !strcmp(runtime.lastPhase(),phase));
  runtime.stop();assert(runtime.memoryUsed()==0);
}

static void callbackTimingTests() {
  static_assert(FireLuaRuntime::kMaxCallbackMs==12 && FireSdkData::kUpdateCallbackMs==24,"coordinated timing contract");
  callbackTimingTest(true,"update",18000,true);
  callbackTimingTest(true,"update",24000,true);
  callbackTimingTest(true,"update",24001,false);
  callbackTimingTest(false,"update",12000,true);
  callbackTimingTest(false,"update",12001,false);
  callbackTimingTest(false,"update",18000,false);
  for(bool sdk:{false,true}) {
    callbackTimingTest(sdk,"on_button",12000,true);
    callbackTimingTest(sdk,"on_button",12001,false);
    callbackTimingTest(sdk,"init",250000,true);
    callbackTimingTest(sdk,"init",250001,false);
  }
  std::string error;assert(!run("while true do end",true,&error));
  assert(error.find("instruction budget")!=std::string::npos);
  puts("PASS SDK update24ms legacy update/button12ms preserved init250ms exact native elapsed and runaway guard");
}

static void manifestApiTests() {
  const auto accepted=[](const char* version,const char* contract) {
    return FireLuaRuntime::supportsManifestApi(version,version?strlen(version):0,
                                               contract,contract?strlen(contract):0);
  };
  const char* hardware=FireLuaRuntime::hardwareApiContract();
  const char* sdk=FireLuaRuntime::appSdkContract();
  assert(accepted("fire-lua-0.1",nullptr));
  assert(accepted("fire-lua-0.1","") && accepted("fire-lua-0.1","legacy ignored contract"));
  assert(accepted(FireLuaRuntime::hardwareApiVersion(),hardware));
  assert(accepted(FireLuaRuntime::appSdkVersion(),sdk));
  assert(!accepted(FireLuaRuntime::hardwareApiVersion(),sdk));
  assert(!accepted(FireLuaRuntime::appSdkVersion(),hardware));
  for(const char* version:{FireLuaRuntime::hardwareApiVersion(),FireLuaRuntime::appSdkVersion()}) {
    assert(!accepted(version,nullptr) && !accepted(version,""));
    assert(!accepted(version,"0") && !accepted(version,(std::string(sdk)+"0").c_str()));
    std::string wrong=sdk;wrong[0]=wrong[0]=='0'?'1':'0';assert(!accepted(version,wrong.c_str()));
    assert(!accepted(version,"64d1f826d3ac1af5fa041a7aaf1a82a8af6dd1f57ea30ae1020421db34f67857"));
  }
  assert(!accepted(nullptr,sdk) && !accepted("",sdk));
  assert(!accepted("fire-lua-0.3",hardware) && !accepted("fire-app-sdk-2.0",sdk));
  assert(!accepted("fire-app-sdk-1.0 ",sdk) && !accepted("FIRE-APP-SDK-1.0",sdk));
  const std::string nulSuffix("\0suffix",7);
  for(const char* version:{"fire-lua-0.1",FireLuaRuntime::hardwareApiVersion(),FireLuaRuntime::appSdkVersion()}) {
    const std::string badVersion=std::string(version)+nulSuffix;
    assert(!FireLuaRuntime::supportsManifestApi(badVersion.data(),badVersion.size(),sdk,strlen(sdk)));
  }
  for(const char* version:{FireLuaRuntime::hardwareApiVersion(),FireLuaRuntime::appSdkVersion()}) {
    const char* correct=!strcmp(version,FireLuaRuntime::hardwareApiVersion())?hardware:sdk;
    const std::string badContract=std::string(correct)+nulSuffix;
    assert(!FireLuaRuntime::supportsManifestApi(version,strlen(version),badContract.data(),badContract.size()));
    assert(!FireLuaRuntime::supportsManifestApi(version,strlen(version),badContract.data(),strlen(correct)+1));
  }
  puts("PASS installer manifest API gate exact SDK/current contract, legacy preservation and invalid/stale/cross-profile rejection");
}

int main(int argc,char** argv) {
  if(argc==2 && !strcmp(argv[1],"--old-instruction-counter")) {instructionResetTest(true);return 0;}
  static_assert(sizeof(lua_Integer)==4 && sizeof(lua_Number)==4,"match ESP32 Lua numeric profile");
  assert(!strcmp(FireLuaRuntime::hardwareApiContract(),"0b29618a077256268c1dc78512ccf2700517e6c162cbe72f2f4a171dcfc3cd40"));
  assert(!strcmp(FireLuaRuntime::appSdkContract(),FireSdkData::kContract));
  manifestApiTests();
  instructionResetTest(false);backgroundTests();
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
  callbackTimingTests();
  assert(argc==2);
  fixture(argv[1],"gallery.lua","CCCCCCAAAAAA");
  fixture(argv[1],"stopwatch.lua","BCBABC");
  fixture(argv[1],"racing.lua","BBCBBCACACBCAB");
  puts("PASS production Lua32 SDK gating UI load validation budgets and native elapsed guard");
  puts("PASS canonical SDK gallery six pages, stopwatch and racing fixture interactions");
}
