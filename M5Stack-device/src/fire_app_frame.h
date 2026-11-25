#pragma once
#include <stdint.h>

// UI-owner state only. Lua cannot acknowledge a prefill. Preparation is a real
// OS fill, not a queued app command or callback timer credit.
namespace fire_app_frame {
class State {
 public:
  void invalidate() {active_=pristine_=false;applied_=0;}
  // Call ONLY after the OS has actually filled the complete supported canvas.
  void acknowledgePrefill(uint16_t color) {applied_=color;active_=pristine_=true;}
  void paint() {pristine_=false;}
  bool consumeClear(uint16_t color,bool sdk,bool fullCanvas) {
    const bool reuse=active_ && pristine_ && sdk && fullCanvas && color==applied_;
    pristine_=false; // Only the FIRST clear may consume the completed OS fill.
    return reuse;
  }
  template<class Canvas>
  void clear(Canvas& canvas,uint16_t color,bool sdk,bool fullCanvas) {
    if(consumeClear(color,sdk,fullCanvas)) canvas.setColor(color);
    else canvas.fillSprite(color);
  }
 private:
  uint16_t applied_=0;
  bool active_=false,pristine_=false;
};
} // namespace fire_app_frame
