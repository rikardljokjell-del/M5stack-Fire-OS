#include "fire_ui.h"
#include <array>
#include <cassert>
#include <cstdio>

struct Canvas {
  std::array<uint16_t, 320*240> pixels{};
  unsigned reads=0, writes=0;
  uint16_t readPixel(int x,int y) {
    assert(x>=0 && x<320 && y>=0 && y<240); ++reads; return pixels[y*320+x];
  }
  void fillRect(int x,int y,int w,int h,uint16_t ink) {
    assert(x>=0 && x+w<=320 && y>=0 && y+h<=240 && w>=0 && h>=0); ++writes;
    for(int py=y;py<y+h;++py) for(int px=x;px<x+w;++px) pixels[py*320+px]=ink;
  }
};

int main() {
  using namespace fire_ui_aa;
  assert(blend(0xf800,0x001f,0)==0x001f);
  assert(blend(0xf800,0x001f,15)==0xf800);
  assert(blend(0xf800,0x001f,7)==uint16_t((14<<11)|17));
  static Canvas c;
  c.pixels.fill(0x001f);
  const uint8_t runs[]={0x00,0x07,0x0f,0x00};
  FireUiAaData::Mask m{4,1,runs,4};
  assert(mask(c,m,20,20,0xf800,{0,0,320,240}));
  assert(c.pixels[20*320+20]==0x001f && c.pixels[20*320+23]==0x001f);
  assert(c.pixels[20*320+21]==blend(0xf800,0x001f,7));
  assert(c.pixels[20*320+22]==0xf800);
  c.pixels.fill(0x07e0);
  assert(mask(c,m,-2,0,0xf800,{0,0,320,240}));
  assert(c.pixels[0]==0xf800 && c.pixels[1]==0x07e0);
  const uint8_t bad[]={0xff};
  assert(!mask(c,{4,1,bad,1},0,0,0xffff,{0,0,320,240}));
  for(int r=1;r<=16;++r) for(int y=0;y<r;++y) for(int x=0;x<r;++x)
    assert(corner(r,x,y)>=corner(r-1,x-1,y-1));
  c.pixels.fill(0x001f);
  rounded(c,20,20,60,40,10,0x07e0,0xf800,true,true);
  assert(c.pixels[20*320+20]==0x001f && c.pixels[40*320+50]==0x07e0);
  for(int y=0;y<40;++y) for(int x=0;x<60;++x) {
    assert(c.pixels[(20+y)*320+20+x]==c.pixels[(20+y)*320+79-x]);
    assert(c.pixels[(20+y)*320+20+x]==c.pixels[(59-y)*320+20+x]);
  }
  // Fill, border and background are composited once at a partially covered edge.
  for(int y=0;y<10;++y) for(int x=0;x<10;++x) {
    unsigned outer=corner(10,x,y), inner=corner(9,x-1,y-1);
    assert(c.pixels[(20+y)*320+20+x]==composite(0x07e0,0xf800,0x001f,inner,outer-inner));
  }
  rounded(c,-10,-8,30,28,10,0xffff,0,false,true);
  for(const auto& f:FireUiAaData::kFonts) for(unsigned j=0;j<f.glyphCount;++j)
    assert(mask(c,f.glyphs[j].mask,100,100,0xffff,{0,0,320,240}));
  for(const auto& i:FireUiAaData::kIcons) assert(mask(c,i.mask,100,100,0xffff,{0,0,320,240}));
  const unsigned before=c.writes;
  FireUI::text(c,310,230,"Æøå / Home",0xffff,"ui12",10);
  FireUI::icon(c,"icon.house",300,225,0xffff,24);
  assert(c.writes>before);
  assert(FireUI::width("Home","pixel8")<FireUI::width("Home","ui16"));
  std::puts("PASS coverage blend, background, clipping, corners, fonts and icons");
}
