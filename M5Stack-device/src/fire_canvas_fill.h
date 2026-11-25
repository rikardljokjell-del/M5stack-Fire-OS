#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

// UI-task-only writes to the existing canvas. The caller retains ownership and
// completes parent display/DMA presentation before rendering the next frame.
// No framebuffer, allocation, decoded cache or M5GFX implementation is owned here.
namespace fire_canvas_fill {
constexpr int kWidth=320,kHeight=240;
constexpr size_t kBytes=size_t(kWidth)*kHeight*2;

// Preconditions: two-byte-aligned writable storage for count native16 pixels.
// memcpy gives defined aliasing semantics; constant-size stores are inlined by
// Xtensa GCC. Unlike the sprite row-copy path, no destination data is read back.
inline void raw16Span(uint8_t* destination,size_t count,uint16_t raw) {
  if (!count) return;
  if (reinterpret_cast<uintptr_t>(destination)&2u) {
    memcpy(destination,&raw,2);destination+=2;--count;
  }
  const uint32_t repeated=uint32_t(raw)|(uint32_t(raw)<<16);
#if defined(__GNUC__) || defined(__clang__)
  auto* aligned=static_cast<uint8_t*>(__builtin_assume_aligned(destination,4));
#else
  auto* aligned=destination;
#endif
  while (count>=2) {
    memcpy(aligned,&repeated,4);aligned+=4;count-=2;
  }
  if (count) memcpy(aligned,&raw,2);
}

// Canvas exposes the existing public M5Canvas getters/color/fillRect interface.
// Snapshot only for the duration of one synchronous native display call; shape
// helpers cannot mutate the layout or clip. All unsupported states delegate.
template<class Canvas>
class Surface {
 public:
  explicit Surface(Canvas& canvas):canvas_(canvas) {
    buffer_=static_cast<uint8_t*>(canvas_.getBuffer());
    canvas_.getClipRect(&left_,&top_,&width_,&height_);
    supported_=buffer_ && !(reinterpret_cast<uintptr_t>(buffer_)&1u) &&
      canvas_.width()==kWidth && canvas_.height()==kHeight &&
      int(canvas_.getColorDepth())==16 && canvas_.getRotation()==0 &&
      canvas_.bufferLength()==kBytes && left_>=0 && top_>=0 &&
      width_>0 && height_>0 && int64_t(left_)+width_<=kWidth &&
      int64_t(top_)+height_<=kHeight;
  }

  void fillRect(int32_t x,int32_t y,int32_t w,int32_t h,uint16_t color) {
    // Let M5GFX reuse its source row for multi-row fills; raw writes are only
    // for single-row spans. Unsupported layouts/negative dimensions still delegate.
    if (!supported_ || w<=0 || h<=0 || h>1) {
      colorReady_=false;
      canvas_.fillRect(x,y,w,h,color);return;
    }
    // Preserve fillRect/fillSprite's current-color side effect even if clipped
    // away, and use M5GFX's native storage conversion instead of assuming swaps.
    // One synchronous Surface has no external color/layout mutations. Font
    // spans reuse one color; retain its native conversion until it changes.
    if (!colorReady_ || color_!=color) {
      canvas_.setColor(color);raw_=uint16_t(canvas_.getRawColor());
      color_=color;colorReady_=true;
    }
    const int64_t xEnd=int64_t(x)+w,yEnd=int64_t(y)+h;
    const int32_t a=x<left_?left_:x,b=y<top_?top_:y;
    const int32_t clipRight=left_+width_,clipBottom=top_+height_;
    const int64_t right=xEnd<clipRight?xEnd:clipRight;
    const int64_t bottom=yEnd<clipBottom?yEnd:clipBottom;
    if (right<=a || bottom<=b) return;
    const size_t count=size_t(right-a);
    auto* row=buffer_+(size_t(b)*kWidth+size_t(a))*2;
    for (int32_t py=b;py<bottom;++py,row+=kWidth*2) raw16Span(row,count,raw_);
  }

 private:
  Canvas& canvas_;
  uint8_t* buffer_=nullptr;
  int32_t left_=0,top_=0,width_=0,height_=0;
  bool supported_=false;
  uint16_t color_=0,raw_=0;
  bool colorReady_=false;
};
} // namespace fire_canvas_fill
