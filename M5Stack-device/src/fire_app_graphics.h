#pragma once
#include <stddef.h>
#include <stdint.h>
#include <math.h>

// Allocation-free raster helpers. Surfaces implement fillRect(x,y,w,h,rgb565).
// Coordinates and rectangles use a half-open 320x240 surface; no OS state lives here.
namespace fire_app_graphics {
constexpr int kWidth = 320;
constexpr int kHeight = 240;
constexpr size_t kMaxPolygonPoints = 16;
struct Point { int16_t x, y; };
struct Rect { int32_t x, y, w, h; };

inline Rect clippedRect(int32_t x, int32_t y, int32_t w, int32_t h) {
  if (w <= 0 || h <= 0) return {0,0,0,0};
  const int64_t right = int64_t(x) + w, bottom = int64_t(y) + h;
  const int32_t left = x < 0 ? 0 : x > kWidth ? kWidth : x;
  const int32_t top = y < 0 ? 0 : y > kHeight ? kHeight : y;
  const int32_t r = right < 0 ? 0 : right > kWidth ? kWidth : int32_t(right);
  const int32_t b = bottom < 0 ? 0 : bottom > kHeight ? kHeight : int32_t(bottom);
  return {left, top, r > left ? r-left : 0, b > top ? b-top : 0};
}

inline uint16_t mix565(uint16_t from, uint16_t to, uint32_t at, uint32_t span) {
  if (!span) return from;
  if (at >= span) return to;
  const uint64_t inverse = span-at;
  const auto channel = [&](unsigned shift, unsigned mask) {
    return uint16_t((((from >> shift) & mask)*inverse +
        uint64_t((to >> shift) & mask)*at + span/2) / span);
  };
  return uint16_t((channel(11,31)<<11) | (channel(5,63)<<5) | channel(0,31));
}

template<class Surface>
void gradient(Surface& surface, int32_t x, int32_t y, int32_t w, int32_t h,
              uint16_t from, uint16_t to, bool vertical) {
  const auto r = clippedRect(x,y,w,h);
  if (!r.w || !r.h) return;
  const uint32_t span = uint32_t((vertical ? h : w)-1);
  const int32_t count = vertical ? r.h : r.w;
  for (int32_t i=0; i<count; ++i) {
    const uint32_t at = uint32_t(vertical ? int64_t(r.y)+i-y : int64_t(r.x)+i-x);
    const auto color = mix565(from,to,at,span);
    surface.fillRect(r.x+(vertical?0:i),r.y+(vertical?i:0),vertical?r.w:1,vertical?1:r.h,color);
  }
}

// Pixel-center sampling, half-open non-horizontal edges and even/odd fill.
// Q16 intersections use 64-bit intermediates; at most16 stack intersections.
inline int32_t ceilFixed(int64_t value) {
  const int64_t quotient=value/65536, remainder=value%65536;
  return int32_t(quotient+(remainder>0));
}
template<class Surface>
bool polygon(Surface& surface,const Point* points,size_t count,uint16_t color) {
  if (!points || count<3 || count>kMaxPolygonPoints) return false;
  int32_t low=points[0].y,high=low;
  for (size_t i=1;i<count;++i) {
    if (points[i].y<low) low=points[i].y;
    if (points[i].y>high) high=points[i].y;
  }
  if (low<0) low=0;
  if (high>kHeight) high=kHeight;
  for (int32_t y=low;y<high;++y) {
    int64_t intersections[kMaxPolygonPoints];size_t used=0;
    for (size_t i=0;i<count;++i) {
      Point a=points[i],b=points[(i+1)%count];
      if (a.y>b.y) {const Point t=a;a=b;b=t;}
      if (a.y==b.y || y<a.y || y>=b.y) continue;
      const int64_t value=int64_t(a.x)*65536+
          (int64_t(2*y+1)-2*int64_t(a.y))*(int64_t(b.x)-a.x)*32768/(int64_t(b.y)-a.y);
      size_t j=used;
      while (j && intersections[j-1]>value) {intersections[j]=intersections[j-1];--j;}
      intersections[j]=value;++used;
    }
    for (size_t i=0;i+1<used;i+=2) {
      int32_t left=ceilFixed(intersections[i]-32768),right=ceilFixed(intersections[i+1]-32768);
      if (left<0) left=0;
      if (right>kWidth) right=kWidth;
      if (right>left) surface.fillRect(left,y,right-left,1,color);
    }
  }
  return true;
}

template<class Surface>
void span(Surface& surface,int x,int y,int w,int h,uint16_t color) {
  const auto r=clippedRect(x,y,w,h);
  if (r.w && r.h) surface.fillRect(r.x,r.y,r.w,r.h,color);
}

// Integer circle inclusion at pixel centers. A binary search avoids a floating
// square root for each row, and has at most10 iterations for contract sizes.
inline int roundInset(int row,int height,int radius) {
  if (!radius) return 0;
  const int edge=row<height/2?row:height-1-row;
  if (edge>=radius) return 0;
  const int dy=2*edge+1-2*radius;
  int low=0,high=radius;
  while (low<high) {
    const int middle=(low+high)/2,dx=2*middle+1-2*radius;
    if (dx*dx+dy*dy<=4*radius*radius) high=middle;
    else low=middle+1;
  }
  return low;
}

template<class Surface>
void roundRect(Surface& surface,int x,int y,int w,int h,int radius,uint16_t color,bool filled) {
  const auto clip=clippedRect(x,y,w,h);
  if (radius<0 || radius>160 || radius>w/2 || radius>h/2) return;
  if (filled) {
    // Identical adjacent row spans form one rectangle. In particular the
    // straight middle of a panel is one fill, not one LGFX call per row.
    int py=clip.y;
    while (py<clip.y+clip.h) {
      const int inset=roundInset(py-y,h,radius);int end=py+1;
      while (end<clip.y+clip.h && roundInset(end-y,h,radius)==inset) ++end;
      span(surface,x+inset,py,w-2*inset,end-py,color);py=end;
    }
    return;
  }
  for (int py=clip.y;py<clip.y+clip.h;++py) {
    const int row=py-y,inset=roundInset(row,h,radius);
    const int left=x+inset,right=x+w-inset;
    if (row==0 || row==h-1 || w<=2 || h<=2) span(surface,left,py,right-left,1,color);
    else {
      const int inner=roundInset(row-1,h-2,radius>0?radius-1:0);
      const int a=x+1+inner,b=x+w-1-inner;
      span(surface,left,py,a-left,1,color);span(surface,b,py,right-b,1,color);
    }
  }
}

inline Point polar(int x,int y,int radius,int degrees) {
  const double radians=degrees*0.017453292519943295;
  return {int16_t(x+int(lround(cos(radians)*radius))),int16_t(y+int(lround(sin(radians)*radius)))};
}

template<class Surface>
void arc(Surface& surface,int x,int y,int radius,int start,int end,uint16_t color,int thickness) {
  if (radius<1 || radius>160 || start<0 || end>360 || end<start || thickness<1 || thickness>radius) return;
  for (int angle=start;angle<end;angle+=3) {
    const int next=angle+3<end?angle+3:end;
    const Point quad[]={polar(x,y,radius,angle),polar(x,y,radius,next),
                        polar(x,y,radius-thickness,next),polar(x,y,radius-thickness,angle)};
    polygon(surface,quad,4,color);
  }
}

// Preserve legacy grid pixels while reducing calls for adjacent equal colors.
template<class Surface>
void indexedGrid(Surface& surface,int x,int y,int cellWidth,int cellHeight,int columns,int rows,
                 const uint8_t* cells,size_t cellCount,const uint16_t* palette,size_t paletteCount) {
  if (!cells || !palette || columns<=0 || rows<=0 || cellWidth<=0 || cellHeight<=0) return;
  for (int row=0;row<rows;++row) {
    const size_t first=size_t(row)*size_t(columns);
    if (first>=cellCount) break;
    size_t available=cellCount-first;
    if (available>size_t(columns)) available=size_t(columns);
    size_t column=0;
    while (column<available) {
      const auto index=cells[first+column];
      if (index>=paletteCount) {++column;continue;}
      size_t end=column+1;
      while (end<available && cells[first+end]<paletteCount && palette[cells[first+end]]==palette[index]) ++end;
      surface.fillRect(x+int(column)*cellWidth,y+row*cellHeight,int(end-column)*cellWidth,cellHeight,palette[index]);
      column=end;
    }
  }
}
} // namespace fire_app_graphics
