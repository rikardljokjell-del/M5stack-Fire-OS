#include "fire_app_graphics.h"
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <array>
using namespace fire_app_graphics;
struct Surface {
  std::array<uint16_t,kWidth*kHeight> pixels{};
  unsigned calls=0;
  void fillRect(int x,int y,int w,int h,uint16_t c) {
    ++calls;auto r=clippedRect(x,y,w,h);
    for(int row=r.y;row<r.y+r.h;++row)
      for(int col=r.x;col<r.x+r.w;++col) pixels[row*kWidth+col]=c;
  }
};
int main() {
  auto r=clippedRect(-4,-2,8,5);assert(r.x==0 && r.y==0 && r.w==4 && r.h==3);
  r=clippedRect(INT_MAX,0,INT_MAX,1);assert(r.w==0);
  r=clippedRect(INT_MIN,INT_MIN,INT_MAX,INT_MAX);assert(r.w==0 && r.h==0);
  assert(mix565(0,65535,0,4)==0 && mix565(0,65535,4,4)==65535);
  static Surface full,crop;
  gradient(full,0,0,10,10,0,65535,false);
  gradient(crop,-5,0,10,10,0,65535,false);
  for(int y=0;y<10;++y)for(int x=0;x<5;++x)assert(crop.pixels[y*kWidth+x]==full.pixels[y*kWidth+x+5]);
  static Surface filled;const Point box[]={{-2,-2},{4,-2},{4,3},{-2,3}};
  assert(polygon(filled,box,4,9));
  for(int y=0;y<kHeight;++y)for(int x=0;x<kWidth;++x)assert(filled.pixels[y*kWidth+x]==((x<4 && y<3)?9:0));
  static Surface reversed;const Point reverse[]={{-2,3},{4,3},{4,-2},{-2,-2}};
  assert(polygon(reversed,reverse,4,9) && reversed.pixels==filled.pixels);
  assert(!polygon(filled,box,2,1) && !polygon(filled,nullptr,4,1));
  static Surface rounded,outline,ring;
  roundRect(rounded,10,10,12,8,3,4,true);
  roundRect(outline,10,10,12,8,3,4,false);
  assert(rounded.pixels[10*kWidth+10]==0 && rounded.pixels[14*kWidth+14]==4);
  assert(outline.pixels[14*kWidth+14]==0);
  for (size_t i=0;i<outline.pixels.size();++i) if(outline.pixels[i]) assert(rounded.pixels[i]==4);
  arc(ring,50,50,20,0,360,7,4);
  assert(ring.pixels[50*kWidth+50]==0 && ring.pixels[50*kWidth+68]==7);
  const auto before=ring.pixels;arc(ring,50,50,20,40,40,9,4);assert(before==ring.pixels);
  uint32_t random=1337;
  for(int pass=0;pass<40;++pass) {
    static Surface expected,actual;expected=Surface{};actual=Surface{};
    uint8_t cells[384];const uint16_t palette[]={0,0x1234,0x1234,0xffff};
    for(auto& c:cells) {random=random*1664525u+1013904223u;c=uint8_t((random>>16)%5);}
    const int columns=24,rows=16,cw=3,ch=4;
    for(size_t i=0;i<384;++i)if(cells[i]<4)expected.fillRect(7+int(i%columns)*cw,9+int(i/columns)*ch,cw,ch,palette[cells[i]]);
    indexedGrid(actual,7,9,cw,ch,columns,rows,cells,384,palette,4);
    assert(expected.pixels==actual.pixels && actual.calls<=expected.calls);
  }
  static Surface batched;const uint8_t cells[]={0,1,0,1,0,1};const uint16_t same[]={7,7};
  indexedGrid(batched,0,0,2,2,3,2,cells,6,same,2);assert(batched.calls==2);
  puts("PASS native graphics clipping, gradients, polygons and legacy grid equivalence");
}
