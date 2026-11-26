#pragma once
#include <stdint.h>

// Small, portable operations used by the existing client and settings path.
namespace fire_backend_policy {
enum class Progress:uint8_t {Waiting,Failed,Ready};
inline Progress progress(bool ready,bool connecting,bool stopping) {
  return ready?Progress::Ready:(connecting || stopping)?Progress::Waiting:Progress::Failed;
}
template<class Store> bool saveMode(Store& store,uint8_t& current,uint8_t next) {
  if (next>2 || store.putUChar("backend_mode",next)!=1 || store.getUChar("backend_mode",255)!=next) return false;
  current=next;return true;
}
struct TlsFailure {
  bool captured=false,socket=false;
  int state=0,error=0;
  void beforeStop(bool open,int phase,int code) {
    if (captured || code>=0) return;
    captured=true;socket=open;state=phase;error=code;
  }
};
} // namespace fire_backend_policy
