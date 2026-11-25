#include "fire_app_bitmap.h"
#include "fire_app_sdk_data.h"
#include <array>
#include <assert.h>
#include <stdio.h>
struct Glyph {uint32_t codepoint;uint8_t width,height,advance;int8_t xOffset,yOffset;const uint32_t* rows;};
struct Font {const char* id;uint8_t lineHeight,ascent,descent;const Glyph* glyphs;uint16_t glyphCount;};
struct Asset {const char* id;uint16_t width,height;const uint16_t* palette;uint16_t paletteSize;const uint8_t* runs;uint32_t runBytes;bool tintable;};
struct Surface {
  std::array<uint16_t,320*240> pixels{};
  void fillRect(int x,int y,int w,int h,uint16_t c) {
    const auto r=fire_app_graphics::clippedRect(x,y,w,h);
    for(int py=r.y;py<r.y+r.h;++py)for(int px=r.x;px<r.x+r.w;++px)pixels[py*320+px]=c;
  }
};
int main() {
  const uint32_t mask[]={5,7,5},question[]={7,1,2};
  const Glyph glyphs[]={{65,3,3,4,0,1,mask},{63,3,3,4,0,1,question},{0xe6,3,3,5,0,1,mask}};
  const Font fonts[]={{"test",5,4,1,glyphs,3}};
  const auto& font=fonts[0];int w=0,h=0;
  assert(fire_app_bitmap::find(fonts,1,"test")==fonts && !fire_app_bitmap::find(fonts,1,"bad"));
  assert(fire_app_bitmap::measure(font,"A\xc3\xa6",3,w,h) && w==9 && h==5);
  assert(fire_app_bitmap::measure(font,"\xf0\x9f\x98\x80",4,w,h) && w==4);
  assert(!fire_app_bitmap::measure(font,"\xc0\xaf",2,w,h));
  assert(!fire_app_bitmap::measure(font,"\xed\xa0\x80",3,w,h));
  assert(!fire_app_bitmap::measure(font,"\xf4\x90\x80\x80",4,w,h));
  assert(!fire_app_bitmap::measure(font,"A\0B",3,w,h));
  assert(!fire_app_bitmap::measure(font,"\xc3",1,w,h));
  static Surface left,center,right,clipped;
  left.pixels.fill(9);
  assert(fire_app_bitmap::text(left,font,0,0,"A",1,2,0,12));
  assert(left.pixels[0]==9 && left.pixels[320]==2 && left.pixels[321]==9 && left.pixels[322]==2);
  assert(fire_app_bitmap::text(center,font,0,0,"A",1,2,1,12));
  assert(fire_app_bitmap::text(right,font,0,0,"A",1,2,2,12));
  assert(center.pixels[324]==2 && right.pixels[328]==2);
  assert(fire_app_bitmap::text(clipped,font,-2,0,"AA",2,2,0,3));
  assert(clipped.pixels[320]==2 && clipped.pixels[321]==0);
  const uint16_t palette[]={0x1111,0,0x7777};
  const uint8_t runs[]={1,0,1,1,2,2};
  const Asset sprite={"sprite",2,2,palette,3,runs,4,false};
  assert(!fire_app_bitmap::validAsset(sprite));
  const Asset valid={"sprite",2,2,palette,3,runs,6,false};
  assert(fire_app_bitmap::validAsset(valid));
  static Surface normal,flipped,tinted;
  normal.pixels.fill(9);
  assert(fire_app_bitmap::asset(normal,valid,0,0,1,0xffff,false,false));
  assert(normal.pixels[0]==9 && normal.pixels[1]==0 && normal.pixels[320]==0x7777);
  assert(fire_app_bitmap::asset(flipped,valid,0,0,2,-1,true,true));
  assert(flipped.pixels[0]==0x7777 && flipped.pixels[1]==0x7777 && flipped.pixels[640]==0);
  const Asset icon={"icon",2,2,palette,3,runs,6,true};
  assert(fire_app_bitmap::asset(tinted,icon,-1,-1,1,0x1234,false,false));
  assert(tinted.pixels[0]==0x1234);
  for (const auto& entry:FireSdkData::kAssets) {
    assert(fire_app_bitmap::validAsset(entry));
    assert(fire_app_bitmap::asset(tinted,entry,-4,-3,2,-1,true,false));
  }
  for (const auto& entry:FireSdkData::kFonts) {
    assert(fire_app_bitmap::measure(entry,"FIRE 123",8,w,h) && h==entry.lineHeight);
    assert(fire_app_bitmap::text(tinted,entry,0,0,"FIRE 123",8,0xffff,0,320));
    assert(fire_app_bitmap::measure(entry," ",1,w,h));
  }
  puts("PASS bitmap font UTF-8 metrics alignment clipping and palette RLE transparency flips tint");
}
