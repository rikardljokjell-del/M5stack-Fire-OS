#include "fire_app_graphics.h"
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <array>
#include <vector>
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
// Independent pixel-center circle predicate, not the row-span renderer.
static bool roundedContains(int px,int py,int x,int y,int w,int h,int radius) {
  if(w<=0 || h<=0 || px<x || py<y || px>=x+w || py>=y+h) return false;
  const int xx=2*(px-x)+1,yy=2*(py-y)+1;
  int dx=0,dy=0;
  if(xx<2*radius) dx=2*radius-xx;else if(xx>2*(w-radius)) dx=xx-2*(w-radius);
  if(yy<2*radius) dy=2*radius-yy;else if(yy>2*(h-radius)) dy=yy-2*(h-radius);
  return dx*dx+dy*dy<=4*radius*radius;
}

// Frozen pre-reuse arc algorithm. Its four independently calculated polar
// points are the oracle for both pixels and the exact ordered fill operations.
static Point oldPolar(int x,int y,int radius,int degrees) {
  const double radians=degrees*0.017453292519943295;
  return {int16_t(x+int(lround(cos(radians)*radius))),int16_t(y+int(lround(sin(radians)*radius)))};
}
template<class Target>
static void oldArc(Target& surface,int x,int y,int radius,int start,int end,uint16_t color,int thickness) {
  if(radius<1 || radius>160 || start<0 || end>360 || end<start || thickness<1 || thickness>radius) return;
  for(int angle=start;angle<end;angle+=3) {
    const int next=angle+3<end?angle+3:end;
    const Point quad[]={oldPolar(x,y,radius,angle),oldPolar(x,y,radius,next),
                        oldPolar(x,y,radius-thickness,next),oldPolar(x,y,radius-thickness,angle)};
    polygon(surface,quad,4,color);
  }
}
struct ArcSurface:Surface {
  std::vector<std::array<int,5>> operations;
  void fillRect(int x,int y,int w,int h,uint16_t color) {
    operations.push_back({x,y,w,h,color});Surface::fillRect(x,y,w,h,color);
  }
};
static void arcEquivalence() {
  const auto check=[](int x,int y,int radius,int start,int end,int thickness,uint16_t color) {
    static ArcSurface expected,actual;expected=ArcSurface{};actual=ArcSurface{};
    expected.pixels.fill(0xa55a);actual.pixels.fill(0xa55a);
    oldArc(expected,x,y,radius,start,end,color,thickness);
    arc(actual,x,y,radius,start,end,color,thickness);
    assert(expected.operations==actual.operations && expected.pixels==actual.pixels);
  };
  const int centers[][2]={{-1024,-1024},{0,0},{160,120},{319,239},{1024,1024}};
  const int angles[][2]={{0,360},{0,1},{1,2},{1,4},{2,5},{89,94},{90,180},{179,182},{270,359},{359,360},{3,3}};
  unsigned index=0;
  for(int radius:{1,2,7,20,40,56,160}) for(int thickness:{1,radius/2+1,radius}) for(const auto& range:angles) {
    const auto& center=centers[index%5];
    check(center[0],center[1],radius,range[0],range[1],thickness,index&1?0:0xf81f);++index;
  }
  const int invalid[][4]={{0,0,360,1},{161,0,360,1},{20,-1,360,1},{20,0,361,1},
                         {20,180,90,1},{20,0,360,0},{20,0,360,21}};
  for(const auto& args:invalid) check(160,120,args[0],args[1],args[2],args[3],7);
  puts("PASS arc previous-algorithm exact ordered operations and pixel equivalence");
}
int main() {
  arcEquivalence();
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
  static Surface panel;
  roundRect(panel,10,50,145,72,6,5,true);
  assert(panel.calls<20); // Full panel used72 LGFX fills before row coalescing.
  for(int pass=0;pass<40;++pass) {
    const int x=pass%3==0?-7:pass%3==1?310:23,y=pass%2?-4:229;
    const int w=2+pass*3,h=2+pass*2,r=(w<h?w:h)/2<6?(w<h?w:h)/2:6;
    static Surface shape;shape=Surface{};
    const bool fill=pass%2==0;roundRect(shape,x,y,w,h,r,11,fill);
    for(int py=0;py<kHeight;++py)for(int px=0;px<kWidth;++px) {
      const bool outer=roundedContains(px,py,x,y,w,h,r);
      const bool inner=roundedContains(px,py,x+1,y+1,w-2,h-2,r?r-1:0);
      assert(shape.pixels[py*kWidth+px]==((outer && (fill || !inner))?11:0));
    }
  }
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
