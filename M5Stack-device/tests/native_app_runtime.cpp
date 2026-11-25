#include "fire_lua_runtime.h"
#include "fire_app_sdk_data.h"
#include "fire_app_bitmap.h"
#include "fire_app_frame.h"
#include "fire_runtime_ai_contract.h"
#include "fire_data_engine_contract.h"
#include "fire_io_mailbox.h"
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

static unsigned aiRequests=0,aiCloses=0,aiCancels=0;static uint8_t aiState=0;
static std::string aiResponse;static int64_t aiDelay=0;
static uint16_t aiHost(void*,const char* instructions,size_t ni,const char* data,size_t nd,
    const char* schema,size_t ns,uint32_t timeout,const char**) {
  assert(ni && nd && ns && ni<=512 && nd<=768 && ns<=512 && ni+nd+ns<=1536);
  assert(instructions && data && schema && timeout>=1000 && timeout<=60000);
  ++aiRequests;fireTestClockUs+=aiDelay;return 7;
}
static bool aiPoll(void*,uint16_t id,FireLuaRuntime::JobSnapshot* snapshot) {
  if(id!=7) return false;snapshot->state=aiState;return true;
}
static bool aiResult(void*,uint16_t id,FireLuaRuntime::JobSnapshot* snapshot) {
  if(!aiPoll(nullptr,id,snapshot)) return false;
  snapshot->resultKind=FireLuaRuntime::JobSnapshot::RuntimeAi;snapshot->text=String(aiResponse);return true;
}
static void runtimeAiTests() {
  // The restricted production VM deliberately has no global assert(). Keep
  // checks fixture-local, using the existing rejected-color error on failure.
  const auto load=[](FireLuaRuntime& vm,const char* source) {
    const std::string fixture=std::string("local function assert(v) if not v then fire.display.clear(-1) end return v end ")+source;
    return vm.loadSource(reinterpret_cast<const uint8_t*>(fixture.data()),fixture.size());
  };
  const auto aiHostCallbacks=[]() {
    auto h=host();h.aiRequest=aiHost;h.jobPoll=aiPoll;h.jobResult=aiResult;
    h.jobClose=[](void*,uint16_t id) {++aiCloses;return id==7;};
    h.jobCancel=[](void*,uint16_t id) {if(id!=7 || aiState!=0) return false;++aiCancels;aiState=3;return true;};return h;
  };
  for(bool sdk:{false,true}) for(uint32_t mask:{3u,33u,1048577u}) {
    FireLuaRuntime r;r.setHardwareApi(true);r.setAppSdk(sdk);r.setServiceMask(mask);assert(r.begin(aiHostCallbacks()));
    const char* source="function init() end function update(dt) assert(fire.ai==nil) end";
    const bool updated=load(r,source) && r.update(16);
    if(!updated) fprintf(stderr,"AI dependency gate SDK=%d mask=%u: %s\n",sdk,mask,r.lastError().c_str());
    assert(updated);r.stop();
  }
  {
    FireLuaRuntime initVm;initVm.setHardwareApi(true);initVm.setAppSdk(true);initVm.setServiceMask(1u|32u|(1u<<20));assert(initVm.begin(aiHostCallbacks()));
    const char* initDenied="function init() local id,e=fire.ai.request('a','{}','{}');assert(id==nil and e=='stale_run') end function update(dt) end";
    assert(load(initVm,initDenied) && aiRequests==0);initVm.stop();
  }
  FireLuaRuntime r;r.setHardwareApi(true);r.setAppSdk(true);r.setServiceMask(1u|32u|(1u<<20));assert(r.begin(aiHostCallbacks()));
  const char* source=R"AI(local step,id=0,nil
function init() end
function update(dt)
 if step==0 then
  id=fire.ai.request('Analyse',[[{"samples":[1,2,3]}]],[[{"type":"object","properties":{"value":{"type":"number"}},"required":["value"],"additionalProperties":false}]],30000)
  assert(id==7 and fire.jobs.poll(id).state=='pending' and fire.jobs.result(id).error_code=='not_ready')
 else
  local result=fire.jobs.result(id);assert(result.ok and result.data.v[16].d==4)
  assert(not fire.jobs.cancel(id) and fire.jobs.close(id))
 end
 step=step+1
end)AI";
  aiState=0;aiDelay=0;assert(load(r,source) && r.update(16));
  aiResponse="{\"v\":[";for(unsigned i=0;i<16;++i) {if(i) aiResponse+=",";aiResponse+="{\"a\":1,\"b\":2,\"c\":3,\"d\":4}";}aiResponse+="]}";
  aiState=1;assert(aiResponse.size()<=512 && r.update(16));assert(aiRequests==1 && aiCloses==1 && aiCancels==0);r.stop();
  const auto check=[&](const char* body,const std::string& response,bool expected) {
    FireLuaRuntime vm;vm.setHardwareApi(true);vm.setAppSdk(true);vm.setServiceMask(1u|32u|(1u<<20));
    assert(vm.begin(aiHostCallbacks()));aiResponse=response;aiState=1;
    const std::string app=std::string("function init() end function update(dt) ")+body+" end";
    assert(load(vm,app.c_str()));
    assert(vm.update(16)==expected);vm.stop();assert(vm.memoryUsed()==0);
  };
  check("assert(fire.jobs.result(7).error_code=='invalid_result')","{\"x\":1,\"x\":2}",true);
  check("assert(fire.jobs.result(7).error_code=='invalid_result')","{\"x\":1e100}",true);
  check("local r=fire.jobs.result(7);assert(r.ok and r.data.value>0)","{\"value\":9223372036854775808}",true);
  check("local r=fire.jobs.result(7);assert(r.ok and r.data.value<0)","{\"value\":-9223372036854775809}",true);
  check("local r=fire.jobs.result(7);assert(r.ok and r.data.value>0)","{\"value\":2147483648}",true);
  check("local r=fire.jobs.result(7);assert(r.ok and r.data.value<0)","{\"value\":-2147483648}",true);
  check("local id,e=fire.ai.request('a','[]','{}');assert(id==nil and e=='invalid_json')","{}",true);
  check("local id,e=fire.ai.request('a','{}','[]');assert(id==nil and e=='invalid_schema')","{}",true);
  check("local id,e=fire.ai.request('a','{}','{}',999);assert(id==nil and e=='invalid_json')","{}",true);
  aiDelay=25000;check("fire.ai.request('a','{}','{}')","{}",false);aiDelay=0;
  puts("PASS actual Lua Runtime AI permission gating async request/jobs bounded decoded result and unchanged24ms wall guard");
}

static void generationalGuiTests(const char* directory) {
  // Actual unchanged failing scene, normal UI allocation and no B/AI request.
  const std::string path=std::string(directory)+"/../../../examples/runtime_ai_quest.lua";
  std::ifstream file(path,std::ios::binary);assert(file.good());
  const std::string source((std::istreambuf_iterator<char>(file)),std::istreambuf_iterator<char>());
  FireLuaRuntime runtime;runtime.setHardwareApi(true);runtime.setAppSdk(true);runtime.setServiceMask(3u|32u|(1u<<20));
  auto h=renderHost();h.aiRequest=aiHost;assert(runtime.begin(h));
  const unsigned requestsBefore=aiRequests;
  fixtureCheck(runtime.loadSource(reinterpret_cast<const uint8_t*>(source.data()),source.size()),"runtime_ai_quest.lua",runtime);
  size_t previous=runtime.memoryUsed(),low=previous,high=previous;unsigned collections=0;
  for(unsigned frame=0;frame<600;++frame) {
    prepareFrame(runtime);fixtureCheck(runtime.update(75),"runtime_ai_quest.lua",runtime);renderedFrame.invalidate();
    const size_t used=runtime.memoryUsed();if(used<previous) ++collections;
    low=min(low,used);high=max(high,used);previous=used;
    assert(used<=FireLuaRuntime::kMaxMemoryBytes);
  }
  assert(collections>2 && runtime.peakMemoryUsed()<=FireLuaRuntime::kMaxMemoryBytes && aiRequests==requestsBefore);
  printf("HOST SDK quest600 frames collections_observed=%u bytes_min=%zu bytes_max=%zu peak=%zu (fake clock; not ESP32 timing)\n",
    collections,low,high,runtime.peakMemoryUsed());
  runtime.stop();assert(runtime.memoryUsed()==0);
  // Preserve old reachable state while repeatedly creating/discarding young
  // objects. Run both profiles; the legacy mode-setting path is untouched.
  const char* churn="local keep={} function init() for i=1,16 do keep[i]={v=i} end end "
    "function update(dt) local t={} for i=1,5 do t[i]={i} end keep[1]={v=keep[1].v+1} "
    "if keep[16].v~=16 then fire.display.clear(-1) end end";
  for(bool sdk:{false,true}) {
    FireLuaRuntime vm;vm.setHardwareApi(true);vm.setAppSdk(sdk);vm.setServiceMask(3);assert(vm.begin(host()));
    assert(vm.loadSource(reinterpret_cast<const uint8_t*>(churn),strlen(churn)));
    for(unsigned i=0;i<400;++i) assert(vm.update(16));
    assert(vm.peakMemoryUsed()<=FireLuaRuntime::kMaxMemoryBytes);vm.stop();assert(vm.memoryUsed()==0);
  }
  std::string error;
  assert(!run("local held={} for i=1,20000 do held[i]={i,i,i,i} end",true,&error));
  assert(error.find("memory")!=std::string::npos);
  puts("PASS SDK generational GUI allocation cycles, retained state,128KiB hard limit and legacy allocation regression");
}

static unsigned dataRequests=0,developRequests=0,rawAdvertisements=0;
static uint16_t dataHost(void*,const char* operation,const char* first,const char*,const char*,
    const uint8_t* payload,size_t length,uint32_t offset,uint16_t count,const char**) {
  ++dataRequests;
  if (!strcmp(operation,"append")) assert(!strcmp(first,"ds-a-b-c") && length==2 && payload[0]==0 && payload[1]==255);
  if (!strcmp(operation,"read")) assert(offset==2 && count==FireDataEngineContract::kReadBytes);
  return 41;
}
static bool developHost(void*,const char* mode,const char* instruction,const char**) {
  ++developRequests;assert(!strcmp(mode,"update") && !strcmp(instruction,"Improve graph"));return true;
}
static uint16_t rawAdvertisementHost(void*,const uint8_t* bytes,size_t length,uint32_t duration,const char**) {
  ++rawAdvertisements;assert(length==3 && bytes[0]==2 && bytes[2]==6 && duration==100);return 42;
}
static uint16_t bluetoothHost(void*,const char*,const char*,const char*,const char*,const uint8_t*,size_t,const char**) {return 43;}
static bool dataResultHost(void*,uint16_t id,FireLuaRuntime::JobSnapshot* snapshot) {
  assert(id==41);snapshot->state=1;snapshot->resultKind=FireLuaRuntime::JobSnapshot::DataRead;
  snapshot->byteCount=FireDataEngineContract::kReadBytes;memset(snapshot->bytes,255,snapshot->byteCount);
  snapshot->written=2;snapshot->connected=true;return true;
}
static void dataAdapterTests() {
  constexpr uint32_t mask=1u|2u|32u|(1u<<17)|(1u<<21)|(1u<<14);
  auto h=host();h.dataRequest=dataHost;h.dataDevelop=developHost;h.jobResult=dataResultHost;
  h.bluetoothAdvertiseRaw=rawAdvertisementHost;h.bluetoothRequest=bluetoothHost;
  auto check=[&](const std::string& body,bool enabled,uint32_t services,bool expected) {
    FireLuaRuntime r;r.setHardwareApi(true);r.setAppSdk(true);r.setDataEngine(enabled);r.setServiceMask(services);assert(r.begin(h));
    const std::string source="function init() end function update(dt) "+body+" end";
    const bool ok=r.loadSource(reinterpret_cast<const uint8_t*>(source.data()),source.size()) && r.update(16);
    assert(ok==expected);r.stop();assert(r.memoryUsed()==0);
  };
  check("local id=fire.data.append('ds-a-b-c',{0,255}) if id~=41 then fire.display.clear(-1) end "
      "local r=fire.jobs.result(fire.data.read('ds-a-b-c',2,"+std::to_string(FireDataEngineContract::kReadBytes)+")) "
      "if not r.ok or r.offset~=2 or not r.eof or #r.bytes~="+std::to_string(FireDataEngineContract::kReadBytes)+" or r.text~=nil or r.bytes[1]~=255 then fire.display.clear(-1) end",true,mask,true);
  const unsigned before=dataRequests;
  check("local id,e=fire.data.append('ds-a-b-c',{'0'})",true,mask,false);
  check("fire.data.read('ds-a-b-c',0,"+std::to_string(FireDataEngineContract::kReadBytes+1)+")",true,mask,false);
  check("fire.data.info('../another-app')",true,mask,false);
  check("fire.data.create('x','csv','{bad')",true,mask,false);
  assert(dataRequests==before);
  for (uint32_t services:{mask&~32u,mask&~(1u<<17),mask&~(1u<<21)})
    check("if fire.data~=nil then fire.display.clear(-1) end",true,services,true);
  check("if fire.data~=nil or fire.bluetooth.advertise_raw~=nil then fire.display.clear(-1) end",false,mask,true);
  check("local ok,e=fire.data.develop('update','Improve graph') if ok~=nil or e~='permission_denied' then fire.display.clear(-1) end",true,mask,true);
  assert(developRequests==0);
  FireLuaRuntime r;r.setHardwareApi(true);r.setAppSdk(true);r.setDataEngine(true);r.setServiceMask(mask);assert(r.begin(h));
  const char* source="function init() local ok=fire.data.develop('update','Improve graph') if ok~=nil then fire.display.clear(-1) end end "
      "function update(dt) end function on_button(b,a) fire.data.develop('update','Improve graph') end";
  assert(r.loadSource(reinterpret_cast<const uint8_t*>(source),strlen(source)));
  assert(r.button("B","released") && developRequests==0);
  assert(r.button("B","pressed") && developRequests==1);r.stop();
  check("if fire.bluetooth.advertise_raw({2,1,6},100)~=42 then fire.display.clear(-1) end",true,mask,true);
  assert(rawAdvertisements==1);
  check("fire.bluetooth.advertise_raw({2,1,6},99)",true,mask,false);assert(rawAdvertisements==1);
  puts("PASS Data Engine actual Lua adapter extension dependency quotas binary results and physical-button intent gate");
}

static unsigned micRequests = 0;
static uint16_t micRecordHost(void*,const char* path,int duration,int rate,const char**) {
  assert(!strcmp(path,"record.wav") && duration==10000 && rate==16000);
  ++micRequests;return 73;
}
static bool micLevelHost(void*,float* value,const char**) {*value=0.25f;return true;}
static bool micResultHost(void*,uint16_t id,FireLuaRuntime::JobSnapshot* snapshot) {
  assert(id==73);snapshot->state=1;snapshot->resultKind=FireLuaRuntime::JobSnapshot::Recording;
  snapshot->path="record.wav";snapshot->sizeBytes=320044;snapshot->sampleRate=16000;return true;
}
static void micAdapterTests() {
  auto h=host();h.micRecord=micRecordHost;h.micLevel=micLevelHost;h.jobResult=micResultHost;
  const uint32_t mask=1u|32u|(1u<<15)|(1u<<17);
  auto check=[&](const char* body,uint32_t services,bool expected) {
    FireLuaRuntime r;r.setHardwareApi(true);r.setAppSdk(true);r.setServiceMask(services);assert(r.begin(h));
    const std::string source=std::string("function init() end function update(dt) ")+body+" end";
    const bool ok=r.loadSource(reinterpret_cast<const uint8_t*>(source.data()),source.size()) && r.update(16);
    if (ok!=expected) fprintf(stderr,"mic adapter expected=%d actual=%d body=%s error=%s\n",expected,ok,body,r.lastError().c_str());
    assert(ok==expected);r.stop();assert(r.memoryUsed()==0);
  };
  micRequests=0;
  check("local id=fire.mic.record('record.wav',10000,16000) if id~=73 or fire.mic.level()~=0.25 then fire.display.clear(-1) end "
        "local t=fire.jobs.result(id) if not t.ok or t.path~='record.wav' or t.sample_rate~=16000 or t.size_bytes~=320044 then fire.display.clear(-1) end",mask,true);
  assert(micRequests==1);
  check("local id,e=fire.mic.record('../outside',10000,16000) if id~=nil or e~='permission_denied' then fire.display.clear(-1) end",mask,true);
  check("local id,e=fire.mic.record('DATASETS/DS-A-B-C/data',10000,16000) if id~=nil or e~='permission_denied' then fire.display.clear(-1) end",mask,true);
  assert(micRequests==1);
  check("fire.mic.record('record.wav',10001,16000)",mask,false);
  check("fire.mic.record('record.wav',100,12000)",mask,false);
  check("if fire.mic~=nil then fire.display.clear(-1) end",mask&~32u,true);
  check("if fire.mic~=nil then fire.display.clear(-1) end",mask&~(1u<<17),true);
  assert(micRequests==1);
  puts("PASS microphone existing-contract adapter permissions limits private paths and recording results");
}

static void installCompletionTest() {
  FireIoMailbox mailbox;mailbox.running=true;
  mailbox.result(false,true,"package-a","hash-a","installed","install-a");
  assert(mailbox.busy());mailbox.running=false;
  // UI can receive a different command before it drains this completion. The
  // completed installation identity belongs to the worker receipt, not that UI.
  String currentUiInstall="install-b";
  assert(mailbox.busy() && mailbox.completed.exchange(false));
  assert(!strcmp(mailbox.completionId.c_str(),"install-a") && strcmp(mailbox.completionId.c_str(),currentUiInstall.c_str()));
  assert(mailbox.ok && !strcmp(mailbox.first.c_str(),"package-a") && !mailbox.busy());
  mailbox.result(false,false,"package-c","","failed","install-c");
  assert(!mailbox.ok && !strcmp(mailbox.completionId.c_str(),"install-c"));
  puts("PASS install completion retains exact worker package/install identity across unrelated UI command");
}

int main(int argc,char** argv) {
  if(argc==2 && !strcmp(argv[1],"--old-instruction-counter")) {instructionResetTest(true);return 0;}
  static_assert(sizeof(lua_Integer)==4 && sizeof(lua_Number)==4,"match ESP32 Lua numeric profile");
  assert(!strcmp(FireLuaRuntime::hardwareApiContract(),"0b29618a077256268c1dc78512ccf2700517e6c162cbe72f2f4a171dcfc3cd40"));
  assert(!strcmp(FireLuaRuntime::appSdkContract(),FireSdkData::kContract));
  manifestApiTests();
  runtimeAiTests();
  installCompletionTest();
  micAdapterTests();
  dataAdapterTests();
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
  generationalGuiTests(argv[1]);
  fixture(argv[1],"gallery.lua","CCCCCCAAAAAA");
  fixture(argv[1],"stopwatch.lua","BCBABC");
  fixture(argv[1],"racing.lua","BBCBBCACACBCAB");
  puts("PASS production Lua32 SDK gating UI load validation budgets and native elapsed guard");
  puts("PASS canonical SDK gallery six pages, stopwatch and racing fixture interactions");
}
