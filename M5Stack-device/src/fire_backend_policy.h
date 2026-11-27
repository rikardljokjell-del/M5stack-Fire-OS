#pragma once
#include <stdint.h>

// Small, portable operations used by the existing client and settings path.
namespace fire_backend_policy {
// UI-owned send result, not a delivery ACK. Once writing starts, a false
// return cannot prove that nothing reached the peer.
enum class SendDisposition:uint8_t {NotQueued,Queued,Uncertain};
// Arduino String's empty assignment retains its allocation. A fresh move
// constructor steals that allocation and resets the source; destruction frees
// it even when its logical length was already zero. Never use move-assignment.
template<class Text> void releaseTextBuffer(Text& value) {
  Text released(static_cast<Text&&>(value));
  (void)released;
}

enum class Progress:uint8_t {Waiting,Failed,Ready};
inline Progress progress(bool ready,bool connecting,bool stopping,bool cleanup=false) {
  return ready?Progress::Ready:(connecting || stopping || cleanup)?Progress::Waiting:Progress::Failed;
}
template<class Store> bool saveMode(Store& store,uint8_t& current,uint8_t next) {
  if (next>2 || store.putUChar("backend_mode",next)!=1 || store.getUChar("backend_mode",255)!=next) return false;
  current=next;return true;
}
inline bool failureReadable(bool active,bool stopped,bool failed) {return !active && !stopped && failed;}
struct ConnectFailure {
  uint32_t phase; // upper byte: fixed worker phase; lower byte: TLS state
  int32_t error;
  uint32_t elapsedMs,attempt;
  constexpr ConnectFailure() : phase(0),error(0),elapsedMs(0),attempt(0) {}
  constexpr ConnectFailure(uint32_t phaseValue,int32_t errorValue,uint32_t elapsedValue,uint32_t attemptValue)
      : phase(phaseValue),error(errorValue),elapsedMs(elapsedValue),attempt(attemptValue) {}
  bool matches(uint32_t current) const {return attempt && attempt==current;}
};
struct TlsFailure {
  bool captured=false,socket=false;
  int state=0,error=0;
  void beforeStop(bool open,int phase,int code) {
    if (captured || code>=0) return;
    captured=true;socket=open;state=phase;error=code;
  }
};
} // namespace fire_backend_policy
