#include "fire_buttons.h"
#include "fire_ui_cadence.h"
#include <array>
#include <cassert>
#include <cstdio>
#include <vector>
using namespace fire_buttons;
struct Sample {unsigned button;Event event;};
struct Ui {
  Button buttons[3];Ring ring;std::vector<Sample> events;
  explicit Ui(uint32_t start=0) {for(auto& b:buttons) {b.resync(false,start);b.advance(start+kDebounceUs);}}
  void advance(uint32_t at) {
    for(unsigned i=0;i<3;++i) for(unsigned n=0;n<2;++n) {auto e=buttons[i].advance(at);if(e.kind==Kind::None) break;events.push_back({i,e});}
  }
  void drain(uint32_t now) {
    Edge edge;
    while(ring.pop(edge)) {advance(edge.at);for(unsigned i=0;i<3;++i) buttons[i].edge(edge.mask&(1u<<i),edge.at,edge.sleeping,edge.context);}
    advance(now);
  }
  unsigned count(Kind kind) const {unsigned n=0;for(auto x:events)n+=x.event.kind==kind;return n;}
};
int main() {
  static_assert(sizeof(Ring)<=416,"fixed internal edge ring; no raw key log or allocation");
  Ui blackout;assert(blackout.ring.push(2,25000,false,42));assert(blackout.ring.push(0,65000,false,42));
  blackout.drain(125000);assert(blackout.count(Kind::Click)==1 && blackout.count(Kind::Hold)==0);
  auto click=blackout.events.back().event;assert(click.at==65000 && click.context==42);
  blackout.drain(200000);assert(blackout.count(Kind::Click)==1);
  Ui repeated;
  for(unsigned n=0;n<10;++n) {assert(repeated.ring.push(1,25000+n*80000,false));assert(repeated.ring.push(0,65000+n*80000,false));}
  repeated.drain(900000);assert(repeated.count(Kind::Click)==10 && repeated.count(Kind::Hold)==0);
  Ui bounce;for(unsigned n=0;n<6;++n) assert(bounce.ring.push(n&1?0:2,25000+n*2000,false));
  bounce.drain(60000);assert(bounce.count(Kind::Click)==0 && bounce.count(Kind::Press)==0);
  Ui held;held.ring.push(4,25000,false);held.ring.push(0,900000,false);held.drain(1000000);
  assert(held.count(Kind::Hold)==1 && held.count(Kind::Click)==0);held.drain(2000000);assert(held.count(Kind::Hold)==1);
  Ui wake;wake.ring.push(2,25000,true);wake.ring.push(0,900000,false);wake.drain(1000000);
  assert(wake.count(Kind::Wake)==1 && wake.count(Kind::Click)==0 && wake.count(Kind::Hold)==0);
  wake.ring.push(2,1100000,false);wake.ring.push(0,1150000,false);wake.drain(1200000);assert(wake.count(Kind::Click)==1);
  const uint32_t wrap=UINT32_MAX-40000;Ui wrapped(wrap);
  wrapped.ring.push(2,wrap+25000,false);wrapped.ring.push(0,wrap+65000,false);wrapped.drain(wrap+125000);
  assert(wrapped.count(Kind::Click)==1 && wrapped.count(Kind::Hold)==0);
  assert(afterOrEqual(wrap+65000,wrap+25000) && !afterOrEqual(wrap+25000,wrap+65000));
  assert(afterOrEqual(1234,1234)); // simultaneous GPIO edges are not lost
  uint32_t floor=0;for (uint64_t t=1000000;t<9000000000ULL;t+=1000000) {assert(afterOrEqual(uint32_t(t),floor));floor=uint32_t(t);} // long uptime refresh and multiple wraps
  Ui overflow;
  for(unsigned i=0;i<Ring::capacity;++i) assert(overflow.ring.push(i&1?0:2,25000+i*1000,false));
  assert(!overflow.ring.push(0,90000,false) && overflow.ring.dropped()==1 && overflow.ring.takeOverflow());
  overflow.ring.discard();for(auto& b:overflow.buttons) {b.resync(true,100000);}
  overflow.advance(2000000);
  for(auto& b:overflow.buttons) {b.edge(false,2100000,false);}
  overflow.advance(2200000);
  assert(overflow.events.empty());overflow.ring.push(2,2300000,false);overflow.ring.push(0,2350000,false);overflow.drain(2400000);
  assert(overflow.count(Kind::Click)==1);
  assert(visibleClick(click,42,1,1,true));
  assert(!visibleClick(click,42,2,1,true)); // B opened a new logical page, not shown yet
  assert(!visibleClick(click,43,2,2,true)); // old down/release queued before new proposal was presented
  assert(!visibleClick(click,42,1,1,false)); // exact shown proposal identity changed
  click.context=43;assert(visibleClick(click,43,2,2,true));
  const uint64_t shownRow=uint64_t(11)|(uint64_t(0)<<40),unseenRow=uint64_t(11)|(uint64_t(1)<<40);
  assert(!visibleClick(click,43,unseenRow,shownRow,true)); // C moved the row before the next frame
  assert(!visibleClick(click,44,unseenRow,unseenRow,true)); // old B down cannot approve the newly painted row
  click.context=44;assert(visibleClick(click,44,unseenRow,unseenRow,true));
  puts("PASS actual button edge replay blackout rapid taps bounce hold wake wrap overflow and unseen confirmation guard");
  using namespace fire_ui_cadence;
  assert(!due(50,0,false,View::Static) && due(1000,0,false,View::Static));
  assert(due(1,0,true,View::Static));assert(!due(32,0,false,View::Developer) && due(33,0,false,View::Developer));
  assert(due(14,UINT32_MAX-10,false,View::Lua));
  enum class Screen {Main,Developer,Quick};
  assert(contentScreen(Screen::Quick,Screen::Developer,Screen::Quick)==Screen::Developer);
  assert(contentScreen(Screen::Quick,Screen::Main,Screen::Quick)==Screen::Main);
  assert(contentScreen(Screen::Developer,Screen::Main,Screen::Quick)==Screen::Developer);
  assert(networkAllowed(false,false) && !networkAllowed(true,false) && !networkAllowed(false,true) && !networkAllowed(true,true));
  assert(!repairViewDemand(true,true)); // plain local app never creates network demand
  assert(repairViewDemand(true,false)); // existing APP ERROR repair view retains metadata/status
  assert(!repairViewDemand(false,false));
  puts("PASS dirty static redraw and unchanged Developer Lua animation cadence");
}
