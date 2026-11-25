#pragma once
#include "fire_app_graphics.h"
#include <string.h>

// Portable flash-data reader. Font/Asset shapes are supplied by the canonical
// SDK generator. No mutable font state, decoded atlas, heap or SD access.
namespace fire_app_bitmap {
template<class Entry>
const Entry* find(const Entry* entries,size_t count,const char* id) {
  if (!id || !entries) return nullptr;
  // Canonical assets/fonts are ID-sorted. Retain a linear fallback for portable
  // callers with unsorted tables, and preserve unknown-ID rejection.
  size_t low=0,high=count;
  while (low<high) {
    const size_t middle=low+(high-low)/2;
    if (strcmp(entries[middle].id,id)<0) low=middle+1;else high=middle;
  }
  if (low<count && !strcmp(entries[low].id,id)) return entries+low;
  for (size_t i=0;i<count;++i) if (!strcmp(entries[i].id,id)) return entries+i;
  return nullptr;
}

inline bool codepoint(const char* text,size_t length,size_t& offset,uint32_t& out) {
  if (offset>=length) return false;
  const auto first=uint8_t(text[offset++]);
  if (first<128) {out=first;return first!=0;}
  unsigned extra=0;uint32_t minimum=0;
  if (first>=0xc2 && first<=0xdf) {extra=1;out=first&31;minimum=0x80;}
  else if (first>=0xe0 && first<=0xef) {extra=2;out=first&15;minimum=0x800;}
  else if (first>=0xf0 && first<=0xf4) {extra=3;out=first&7;minimum=0x10000;}
  else return false;
  if (extra>length-offset) return false;
  for (unsigned i=0;i<extra;++i) {
    const auto byte=uint8_t(text[offset++]);
    if ((byte&0xc0)!=0x80) return false;
    out=(out<<6)|(byte&63);
  }
  return out>=minimum && out<=0x10ffff && !(out>=0xd800 && out<=0xdfff);
}

template<class Font>
auto glyph(const Font& font,uint32_t cp) -> decltype(font.glyphs) {
  // Canonical glyphs are sorted by codepoint. Probe in logarithmic time, then
  // retain linear fallback for other/test fonts without imposing a new format.
  size_t low=0,high=font.glyphCount;
  while (low<high) {
    const size_t middle=low+(high-low)/2;
    if (font.glyphs[middle].codepoint<cp) low=middle+1;else high=middle;
  }
  if (low<font.glyphCount && font.glyphs[low].codepoint==cp) return font.glyphs+low;
  decltype(font.glyphs) fallback=nullptr;
  for (size_t i=0;i<font.glyphCount;++i) {
    if (font.glyphs[i].codepoint==cp) return font.glyphs+i;
    if (font.glyphs[i].codepoint==63) fallback=font.glyphs+i;
  }
  return fallback;
}

template<class Font>
bool measure(const Font& font,const char* text,size_t length,int& width,int& height) {
  width=0;height=font.lineHeight;
  if (!text || length>80) return false;
  size_t offset=0;
  while (offset<length) {
    uint32_t cp=0;if (!codepoint(text,length,offset,cp)) return false;
    const auto* g=glyph(font,cp);
    if (!g || g->width>32 || (g->height && !g->rows)) return false;
    width+=g->advance;
  }
  return true;
}

template<class Surface,class Font>
bool text(Surface& surface,const Font& font,int x,int y,const char* value,
          size_t length,uint16_t color,int align,int maxWidth) {
  int width=0,height=0;
  if (align<0 || align>2 || maxWidth<1 || maxWidth>1024 ||
      !measure(font,value,length,width,height)) return false;
  const auto clip=fire_app_graphics::clippedRect(x,y,maxWidth,height);
  size_t offset=0;int pen=x+(align==1?(maxWidth-width)/2:align==2?maxWidth-width:0);
  while (offset<length) {
    uint32_t cp=0;codepoint(value,length,offset,cp);
    const auto* g=glyph(font,cp);
    for (int row=0;row<g->height;++row) {
      const int py=y+g->yOffset+row;
      if (py<clip.y || py>=clip.y+clip.h) continue;
      int col=0;
      while (col<g->width) {
        if (!(g->rows[row] & (uint32_t(1)<<(g->width-1-col)))) {++col;continue;}
        const int start=col++;
        while (col<g->width && (g->rows[row] & (uint32_t(1)<<(g->width-1-col)))) ++col;
        int a=pen+g->xOffset+start,b=pen+g->xOffset+col;
        if (a<clip.x) a=clip.x;
        if (b>clip.x+clip.w) b=clip.x+clip.w;
        if (b>a) surface.fillRect(a,py,b-a,1,color);
      }
    }
    pen+=g->advance;
  }
  return true;
}

template<class Asset>
bool validAsset(const Asset& asset) {
  if (!asset.width || !asset.height || asset.width>320 || asset.height>240 ||
      !asset.palette || !asset.paletteSize || asset.paletteSize>256 || !asset.runs ||
      (asset.runBytes&1) || asset.runBytes>uint32_t(asset.width)*asset.height*2) return false;
  uint32_t pixels=0;
  for (uint32_t i=0;i<asset.runBytes;i+=2) {
    if (!asset.runs[i] || asset.runs[i+1]>=asset.paletteSize) return false;
    pixels+=asset.runs[i];
    if (pixels>uint32_t(asset.width)*asset.height) return false;
  }
  return pixels==uint32_t(asset.width)*asset.height;
}

template<class Surface,class Asset>
bool asset(Surface& surface,const Asset& entry,int x,int y,int scale,int tint,
           bool flipX,bool flipY) {
  if (scale<1 || scale>4 || tint < -1 || tint>65535 || !validAsset(entry)) return false;
  uint32_t pixel=0;
  for (uint32_t i=0;i<entry.runBytes;i+=2) {
    unsigned remaining=entry.runs[i];const auto index=entry.runs[i+1];
    while (remaining) {
      const int row=int(pixel/entry.width),col=int(pixel%entry.width);
      const unsigned span=remaining<unsigned(entry.width-col)?remaining:unsigned(entry.width-col);
      if (index) {
        const int px=x+(flipX?entry.width-col-int(span):col)*scale;
        const int py=y+(flipY?entry.height-1-row:row)*scale;
        const auto r=fire_app_graphics::clippedRect(px,py,int(span)*scale,scale);
        if (r.w && r.h) surface.fillRect(r.x,r.y,r.w,r.h,
            entry.tintable && tint>=0?uint16_t(tint):entry.palette[index]);
      }
      pixel+=span;remaining-=span;
    }
  }
  return true;
}
} // namespace fire_app_bitmap
