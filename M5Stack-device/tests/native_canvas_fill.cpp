#include "fire_canvas_fill.h"
#include "fire_app_bitmap.h"
#include "fire_app_sdk_data.h"
#include <array>
#include <algorithm>
#include <assert.h>
#include <limits.h>
#include <stdio.h>
namespace {
constexpr size_t guard=32,bytes=320*240*2;
struct Canvas {
  alignas(4) std::array<uint8_t,guard+bytes+guard+4> memory{};
  int offset=0,w=320,h=240,depth=16,rotation=0;
  int clipX=0,clipY=0,clipW=320,clipH=240;
  size_t storage=bytes;bool nullBuffer=false,swap=true;
  uint16_t current=0;unsigned fallbackCalls=0;
  unsigned colorCalls=0;mutable unsigned rawReads=0;
  int last[4]={};uint16_t lastColor=0;
  Canvas() {memory.fill(0xa5);}
  uint8_t* pixels() {return memory.data()+guard+offset;}
  void* getBuffer() {return nullBuffer?nullptr:pixels();}
  size_t bufferLength() const {return storage;}
  int width() const {return w;} int height() const {return h;}
  int getColorDepth() const {return depth;} int getRotation() const {return rotation;}
  void getClipRect(int* x,int* y,int* cw,int* ch) {*x=clipX;*y=clipY;*cw=clipW;*ch=clipH;}
  void setColor(uint16_t color) {++colorCalls;current=swap?uint16_t((color<<8)|(color>>8)):color;}
  uint32_t getRawColor() const {++rawReads;return current;}
  // Independent scalar pixel oracle. Does not use clipping/span helpers under test.
  void fillRect(int x,int y,int rw,int rh,uint16_t color) {
    ++fallbackCalls;last[0]=x;last[1]=y;last[2]=rw;last[3]=rh;lastColor=color;
    setColor(color);if(nullBuffer) return;
    int64_t ax=x,ay=y,aw=rw,ah=rh;
    if(aw<0) {ax+=aw;aw=-aw;}if(ah<0) {ay+=ah;ah=-ah;}
    const int64_t loX=std::max<int64_t>(0,std::max<int64_t>(clipX,ax));
    const int64_t loY=std::max<int64_t>(0,std::max<int64_t>(clipY,ay));
    const int64_t hiX=std::min<int64_t>(320,std::min<int64_t>(int64_t(clipX)+clipW,ax+aw));
    const int64_t hiY=std::min<int64_t>(240,std::min<int64_t>(int64_t(clipY)+clipH,ay+ah));
    const uint8_t* raw=reinterpret_cast<const uint8_t*>(&current);
    for(int64_t py=loY;py<hiY;++py) for(int64_t px=loX;px<hiX;++px) {
      const auto p=size_t(py*320+px)*2;pixels()[p]=raw[0];pixels()[p+1]=raw[1];
    }
  }
};
static Canvas expected,actual;
void equal() {assert(expected.memory==actual.memory);assert(expected.current==actual.current);}
void reset(int offset=0,bool swap=true) {
  expected=Canvas{};actual=Canvas{};expected.offset=actual.offset=offset;expected.swap=actual.swap=swap;
}
void rectangle(int x,int y,int w,int h,uint16_t color) {
  const unsigned fallbackBefore=actual.fallbackCalls;
  expected.fillRect(x,y,w,h,color);fire_canvas_fill::Surface<Canvas> surface(actual);
  surface.fillRect(x,y,w,h,color);equal();
  const bool delegated=w<=0 || h!=1;
  assert(actual.fallbackCalls==fallbackBefore+(delegated?1:0));
  if(delegated) {
    assert(actual.last[0]==x && actual.last[1]==y && actual.last[2]==w && actual.last[3]==h && actual.lastColor==color);
  }
}
void allColors() {
  alignas(4) std::array<uint8_t,96> want{},got{};
  fire_canvas_fill::raw16Span(nullptr,0,0);
  for(uint32_t color=0;color<65536;++color) for(unsigned offset:{0u,2u}) for(size_t count=0;count<10;++count) {
    want.fill(0xa5);got.fill(0xa5);const uint16_t raw=uint16_t(color);
    const auto* value=reinterpret_cast<const uint8_t*>(&raw);
    for(size_t i=0;i<count;++i) {want[guard+offset+i*2]=value[0];want[guard+offset+i*2+1]=value[1];}
    fire_canvas_fill::raw16Span(got.data()+guard+offset,count,raw);assert(want==got);
  }
}
void rectangles() {
  const int regions[][4]={{0,0,320,240},{1,1,317,237},{319,239,1,1},{-8,-7,15,13},
    {-1024,12,1024,1},{318,20,1024,5},{12,238,5,100},{INT_MIN,0,INT_MAX,1},{INT_MAX,INT_MAX,INT_MAX,INT_MAX},
    {2,3,1,19},{3,3,2,19},{0,239,319,1},{319,0,1,240},{500,500,1,1},
    {500,500,3,2},{1,239,3,4},{0,0,0,0},{9,10,-7,-5}};
  const uint16_t colors[]={0,65535,2113,0x1234,0x0801,0xf800,0x07e0,0x001f,0x00ff,0xff00};
  for(int offset:{0,2}) for(bool swap:{false,true}) for(auto color:colors) for(const auto& region:regions) {
    reset(offset,swap);rectangle(region[0],region[1],region[2],region[3],color);
    reset(offset,swap);expected.clipX=actual.clipX=3;expected.clipY=actual.clipY=7;
    expected.clipW=actual.clipW=313;expected.clipH=actual.clipH=229;
    rectangle(region[0],region[1],region[2],region[3],color);
  }
  uint32_t seed=1337;
  for(int pass=0;pass<500;++pass) {
    auto next=[&]() {seed=seed*1664525u+1013904223u;return seed;};
    reset(pass&1?2:0,pass&2);
    const int x=int(next()%1800)-900,y=int(next()%1000)-500,w=int(next()%1100)+1,h=int(next()%1100)+1;
    rectangle(x,y,w,h,uint16_t(next()));
  }
}
void fallback() {
  for(int height:{1,13}) for(int mode=0;mode<12;++mode) {
    reset();
    for(auto* canvas:{&expected,&actual}) switch(mode) {
      case 0:canvas->rotation=1;break;case 1:canvas->depth=8;break;
      case 2:canvas->storage=bytes-2;break;case 3:canvas->storage=bytes+2;break;
      case 4:canvas->w=319;break;case 5:canvas->h=239;break;
      case 6:canvas->offset=1;break;case 7:canvas->nullBuffer=true;break;
      case 8:canvas->clipX=-1;break;case 9:canvas->clipW=321;break;
      case 10:canvas->clipH=0;break;case 11:canvas->clipY=INT_MAX;break;
    }
    expected.fillRect(-3,5,11,height,0x0812);fire_canvas_fill::Surface<Canvas> surface(actual);
    surface.fillRect(-3,5,11,height,0x0812);equal();assert(actual.fallbackCalls==1);
    assert(actual.last[0]==-3 && actual.last[1]==5 && actual.last[2]==11 && actual.last[3]==height && actual.lastColor==0x0812);
  }
}
void repeatedSpanColors() {
  for(int offset:{0,2}) for(bool swap:{false,true}) {
    reset(offset,swap);fire_canvas_fill::Surface<Canvas> surface(actual);
    const auto draw=[&](int x,int y,int w,int h,uint16_t color) {
      expected.fillRect(x,y,w,h,color);surface.fillRect(x,y,w,h,color);equal();
    };
    // First use is clipped away, but must still set current-color correctly.
    draw(-20,4,3,1,0x1234);
    for(int row=0;row<100;++row) draw(row%13,row,19,1,0x1234);
    assert(actual.colorCalls==1 && actual.rawReads==1 && !actual.fallbackCalls);
    draw(319,239,3,1,0xabcd);draw(400,400,3,1,0xabcd);
    assert(actual.colorCalls==2 && actual.rawReads==2);
    // Native multi-row fallback changes the canvas color and invalidates even
    // when the next raw span uses the previously cached RGB565 value.
    draw(2,3,7,4,0x4567);
    assert(actual.fallbackCalls==1 && actual.colorCalls==3 && actual.rawReads==2);
    draw(5,7,9,1,0xabcd);draw(8,9,2,1,0xabcd);
    assert(actual.colorCalls==4 && actual.rawReads==3);
  }
  puts("PASS Surface repeated-span color conversion reuse and fallback invalidation");
}
void sharedAssetsAndFonts() {
  size_t index=0;
  for(const auto& asset:FireSdkData::kAssets) {
    reset(index&1?2:0,index&2);
    if(index%5==0) {
      expected.clipX=actual.clipX=3;expected.clipY=actual.clipY=7;
      expected.clipW=actual.clipW=313;expected.clipH=actual.clipH=229;
    }
    fire_canvas_fill::Surface<Canvas> fast(actual);
    const int scale=int(index%4)+1,x=index%3==0?-7:285,y=index%2?-3:219;
    const bool flipX=index&1,flipY=index&2;const int tint=index%3==0?0x1234:-1;
    assert(fire_app_bitmap::asset(expected,asset,x,y,scale,tint,flipX,flipY));
    assert(fire_app_bitmap::asset(fast,asset,x,y,scale,tint,flipX,flipY));equal();++index;
  }
  const uint16_t palette[]={0xffff,0,0x3412};const uint8_t runs[]={1,0,1,1,2,2};
  const FireSdkData::Asset black={"test",2,2,palette,3,runs,6,true};
  for(int tint:{-1,0,0x1234}) for(bool flipX:{false,true}) for(bool flipY:{false,true}) {
    reset();fire_canvas_fill::Surface<Canvas> fast(actual);
    assert(fire_app_bitmap::asset(expected,black,-1,-1,3,tint,flipX,flipY));
    assert(fire_app_bitmap::asset(fast,black,-1,-1,3,tint,flipX,flipY));equal();
  }
  for(const auto& font:FireSdkData::kFonts) {
    for(int align=0;align<3;++align) for(int x:{-7,8,315}) {
      reset(align&1?2:0,align&2);fire_canvas_fill::Surface<Canvas> fast(actual);
      const char text[]="FIRE 12 \xc3\xa6\xc3\xb8\xc3\xa5 \xc3\x86\xc3\x98\xc3\x85 \xc2\xb0\xc3\x97\xe2\x88\x92";
      assert(fire_app_bitmap::text(expected,font,x,3,text,sizeof(text)-1,0x1234,align,117));
      assert(fire_app_bitmap::text(fast,font,x,3,text,sizeof(text)-1,0x1234,align,117));equal();
    }
  }
}
void shapes() {
  using namespace fire_app_graphics;
  for(int pass=0;pass<24;++pass) {
    reset(pass&1?2:0,pass&2);fire_canvas_fill::Surface<Canvas> fast(actual);
    const int x=pass%3==0?-9:pass%3==1?309:15,y=pass%4==0?-5:pass%4==1?220:70;
    const bool filled=pass&1;const uint16_t color=uint16_t(2113+pass*321);
    roundRect(expected,x,y,101,75,6,color,filled);roundRect(fast,x,y,101,75,6,color,filled);equal();
    const Point points[]={{int16_t(x),int16_t(y)},{int16_t(x+79),int16_t(y-13)},{int16_t(x+20),int16_t(y+41)}};
    assert(polygon(expected,points,3,color));assert(polygon(fast,points,3,color));equal();
    gradient(expected,x,y,99,17,0,0xffff,pass&1);gradient(fast,x,y,99,17,0,0xffff,pass&1);equal();
    arc(expected,x+40,y,31,pass%3==0?0:87,pass%3==0?360:359,color,pass%7+1);
    arc(fast,x+40,y,31,pass%3==0?0:87,pass%3==0?360:359,color,pass%7+1);equal();
  }
}
} // namespace
int main() {
  allColors();rectangles();fallback();repeatedSpanColors();sharedAssetsAndFonts();shapes();
  puts("PASS canvas raw16 all65536 colors alignment canaries clipping fallback color-state and shared SDK raster parity");
}
