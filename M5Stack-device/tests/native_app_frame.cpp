#include "fire_app_frame.h"
#include <array>
#include <assert.h>
#include <stdio.h>
struct Canvas {
  std::array<uint16_t,320*240> pixels{};
  uint16_t current=0;unsigned fills=0;
  void setColor(uint16_t color) {current=color;}
  void fillSprite(uint16_t color) {++fills;current=color;pixels.fill(color);}
};
int main() {
  static Canvas actual,reference;
  fire_app_frame::State state;
  // No acknowledgement: even matching black MUST execute a real clear.
  actual.fillSprite(0);state.clear(actual,0,true,true);assert(actual.fills==2);
  for(unsigned scenario=0;scenario<12;++scenario) for(uint16_t bg:{uint16_t(0),uint16_t(2113),uint16_t(65535)}) {
    actual=Canvas{};reference=Canvas{};state.invalidate();
    actual.fillSprite(bg);reference.fillSprite(bg);state.acknowledgePrefill(bg);
    const uint16_t requested=scenario==1?uint16_t(bg^0x1234):bg;
    if(scenario==2 || scenario==3) {actual.pixels[17]=reference.pixels[17]=9;state.paint();}
    if(scenario==4) state.paint(); // Conservative transparent/offscreen attempt.
    if(scenario==5) state.invalidate(); // Error/stop/overlay ownership transfer.
    if(scenario==6) {state.clear(actual,bg,true,true);reference.fillSprite(bg);} // Second clear is real.
    if(scenario==7) {state.invalidate();state.acknowledgePrefill(bg);state.invalidate();} // Stale acknowledgement.
    const bool sdk=scenario!=8,full=scenario!=9;
    // Measurement and next-frame configuration do not touch this UI-owned state.
    if(scenario==10 || scenario==11) actual.current=reference.current=0x1234;
    const unsigned before=actual.fills;
    state.clear(actual,requested,sdk,full);reference.fillSprite(requested);
    assert(actual.pixels==reference.pixels && actual.current==reference.current);
    const bool canReuse=(scenario==0 || scenario==10 || scenario==11);
    assert(actual.fills==before+(canReuse?0:1));
    state.clear(actual,requested,true,true);reference.fillSprite(requested);
    assert(actual.fills==before+(canReuse?1:2));
    assert(actual.pixels==reference.pixels && actual.current==reference.current);
  }
  // Each new preparation can acknowledge exactly one initial matching clear.
  for(unsigned frame=0;frame<20;++frame) {
    const uint16_t color=uint16_t(frame*2113);state.invalidate();actual.fillSprite(color);
    state.acknowledgePrefill(color);const auto fills=actual.fills;
    state.clear(actual,color,true,true);assert(actual.fills==fills);
    state.invalidate();state.clear(actual,color,true,true);assert(actual.fills==fills+1);
  }
  puts("PASS frame prefill one-shot real clear fallback pixel color-state and lifecycle isolation");
}
