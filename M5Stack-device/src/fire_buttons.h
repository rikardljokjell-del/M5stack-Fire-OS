#pragma once
#include <atomic>
#include <stdint.h>
#if defined(__GNUC__)
#define FIRE_INPUT_INLINE __attribute__((always_inline)) inline
#else
#define FIRE_INPUT_INLINE inline
#endif
namespace fire_buttons {
constexpr uint32_t kDebounceUs=18000,kHoldUs=650000;
enum class Kind:uint8_t {None,Press,Click,Hold,Wake};
struct Event {Kind kind=Kind::None;uint32_t at=0,context=0;};
struct Edge {uint32_t at=0;uint32_t context=0;uint8_t mask=0;bool sleeping=false;};
// One GPIO ISR producer, one UI consumer. Never allocate or dispatch in ISR.
class Ring {
 public:
  static constexpr uint32_t capacity=32;
  FIRE_INPUT_INLINE bool push(uint8_t mask,uint32_t at,bool sleeping,uint32_t context=0) {
    const uint32_t head=head_.load(std::memory_order_relaxed);
    if (head-tail_.load(std::memory_order_acquire)>=capacity) {
      const uint32_t lost=dropped_.load(std::memory_order_relaxed);
      if (lost!=UINT32_MAX) dropped_.store(lost+1,std::memory_order_relaxed);
      overflow_.store(1,std::memory_order_release);return false;
    }
    edges_[head&(capacity-1)]={at,context,mask,sleeping};head_.store(head+1,std::memory_order_release);return true;
  }
  bool pop(Edge& edge) {
    const uint32_t tail=tail_.load(std::memory_order_relaxed);
    if (head_.load(std::memory_order_acquire)==tail) return false;
    edge=edges_[tail&(capacity-1)];tail_.store(tail+1,std::memory_order_release);return true;
  }
  void discard() {tail_.store(head_.load(std::memory_order_acquire),std::memory_order_release);}
  bool pending() const {return head_.load(std::memory_order_acquire)!=tail_.load(std::memory_order_acquire);}
  bool takeOverflow() {return overflow_.exchange(0,std::memory_order_acq_rel);}
  uint32_t dropped() const {return dropped_.load(std::memory_order_relaxed);}
 private:
  Edge edges_[capacity];
  std::atomic<uint32_t> head_{0},tail_{0},dropped_{0};
  std::atomic<uint32_t> overflow_{0};
};
class Button {
 public:
  bool down() const {return down_;}
  void resync(bool raw,uint32_t at) {raw_=raw;down_=false;changed_=at;blocked_=true;held_=wake_=false;}
  void edge(bool raw,uint32_t at,bool sleeping,uint32_t context=0) {
    if (raw_==raw) return;
    raw_=raw;changed_=at;if(raw) {rawWake_=sleeping;context_=context;}
  }
  Event advance(uint32_t at) {
    if (blocked_) {
      if (!raw_ && uint32_t(at-changed_)>=kDebounceUs) blocked_=false;
      return {};
    }
    if (raw_!=down_ && uint32_t(at-changed_)>=kDebounceUs) {
      down_=raw_;
      if (down_) {started_=changed_+kDebounceUs;held_=false;wake_=rawWake_;return {wake_?Kind::Wake:Kind::Press,started_,context_};}
      else {const bool click=!held_ && !wake_;wake_=false;if(click) return {Kind::Click,changed_,context_};}
    }
    if (down_ && !wake_ && !held_ && uint32_t(at-started_)>=kHoldUs) {held_=true;return {Kind::Hold,started_+kHoldUs,context_};}
    return {};
  }
 private:
  bool raw_=false,down_=false,held_=false,wake_=false,rawWake_=false,blocked_=true;
  uint32_t changed_=0,started_=0,context_=0;
};
inline bool afterOrEqual(uint32_t at,uint32_t floor) {return static_cast<int32_t>(at-floor)>=0;}
inline bool visibleClick(const Event& event,uint32_t shownContext,uint64_t logicalView,uint64_t shownView,bool sameIdentity) {
  return event.context==shownContext && logicalView==shownView && sameIdentity;
}
} // namespace fire_buttons

#undef FIRE_INPUT_INLINE
