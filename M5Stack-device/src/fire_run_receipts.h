#pragma once
#include "fire_lua_install_identity.h"
#include "fire_backend_policy.h"

namespace fire_run_receipts {
enum class State:uint8_t {Starting,Started,Healthy,Failed};
enum class Admission {New,Duplicate,Busy,Invalid};
struct Entry {
  char id[97]={},package[97]={},source[65]={},archive[65]={};
  uint32_t expires=0;State state=State::Starting;
};
class Ring {
 public:
  static constexpr size_t kCapacity=8;
  Admission admit(const char* run,const char* package,const char* source,const char* archive,
                  uint32_t expires,uint32_t now,bool currentBoot,Entry*& result) {
    result=nullptr;
    if(!currentBoot || !now || expires<=now || !fire_lua_install::id(run) ||
       !fire_lua_install::id(package) || !fire_lua_install::hash(source) || !fire_lua_install::hash(archive)) return Admission::Invalid;
    for(auto& e:entries_) if(e.expires>now && !strcmp(e.id,run)) {
      if(e.expires!=expires || strcmp(e.package,package) || strcmp(e.source,source) || strcmp(e.archive,archive)) return Admission::Invalid;
      result=&e;return Admission::Duplicate;
    }
    for(auto& e:entries_) if(e.expires<=now) {
      strcpy(e.id,run);strcpy(e.package,package);strcpy(e.source,source);strcpy(e.archive,archive);
      e.expires=expires;e.state=State::Starting;result=&e;return Admission::New;
    }
    return Admission::Busy; // Never evict an unexpired replay marker.
  }
 private:
  Entry entries_[kCapacity];
};

// One local sending state for the current, already authorized VM. The Ring
// remains the replay/physical-state authority; this never launches a VM.
struct Delivery {
  Entry* entry=nullptr;
  char session[65]={},boot[65]={};
  enum : uint8_t {Started=1,HealthySeen=2,Healthy=4,StartPending=8,Uncertain=16,Attempted=32};
  uint8_t flags=0;
  uint32_t epoch=0,attemptAt=0;
  static bool wireId(const char* id,size_t maximum=64) {
    if(!id) return false;
    const size_t n=strlen(id);if(!n || n>maximum) return false;
    for(size_t i=0;i<n;++i) if(!((id[i]>='a' && id[i]<='z') || (id[i]>='0' && id[i]<='9') ||
      (i && (id[i]=='-' || id[i]=='_')))) return false;
    return true;
  }
  static bool canBind(const Entry* value,const char* sid,const char* bootId) {
    // Prefix plus the ENTIRE run ID must fit the existing 64-byte wire ID.
    // Reject longer IDs explicitly, never truncate or weaken the identity.
    return value && wireId(value->id,61) && wireId(value->package) &&
      fire_lua_install::hash(value->source) && fire_lua_install::hash(value->archive) && wireId(sid) && wireId(bootId);
  }
  void clear() {*this=Delivery();}
  bool arm(Entry* value,const char* sid,const char* bootId,uint32_t currentEpoch) {
    clear();if(!canBind(value,sid,bootId)) return false;
    entry=value;strcpy(session,sid);strcpy(boot,bootId);epoch=currentEpoch;flags=StartPending;return true;
  }
  bool scope(const char* sid,const char* bootId) const {
    return entry && sid && bootId && !strcmp(session,sid) && !strcmp(boot,bootId);
  }
  bool pending() const {return entry && !(flags&Uncertain) && ((flags&StartPending) || !(flags&Healthy));}
  bool uncertain() const {return flags&Uncertain;}
  bool started() const {return flags&Started;}
  bool healthy() const {return flags&Healthy;}
  void sawUpdate() {if(entry) flags|=HealthySeen;}
  // Only an ACTUALLY received duplicate command asks for another canonical
  // receipt. It preserves observed health and never rearms/restarts the VM.
  void duplicate() {if(entry) {flags|=StartPending;flags&=uint8_t(~(Uncertain|Attempted));}}
  bool due(uint32_t now) const {return !(flags&Attempted) || uint32_t(now-attemptAt)>=250;}
  void attempt(uint32_t now) {attemptAt=now;flags|=Attempted;}
  void unknown() {flags|=Uncertain;flags&=uint8_t(~StartPending);}
  bool epochSafe(uint32_t current) const {
    return !(flags&Started) || (flags&Healthy) || (flags&StartPending) || epoch==current;
  }
  bool wantHealthy() const {return (flags&Started) && (flags&HealthySeen) && !(flags&Healthy);}
  bool eventId(bool health,char (&out)[65]) const {
    if(!entry || !wireId(entry->id,61)) return false;
    out[0]='r';out[1]=health?'h':'s';out[2]='-';strcpy(out+3,entry->id);return true;
  }
  void sent(bool health,fire_backend_policy::SendDisposition disposition,uint32_t currentEpoch) {
    if(disposition==fire_backend_policy::SendDisposition::Uncertain) {unknown();return;}
    if(disposition!=fire_backend_policy::SendDisposition::Queued) return;
    if(health) flags|=Healthy;
    else {flags|=Started;flags&=uint8_t(~(StartPending|Attempted));epoch=currentEpoch;}
  }
};
inline bool legacyKey(const char* key) {
  if(!key || strncmp(key,"rr_",3)) return false;
  const size_t n=strlen(key+3);if(!n || n>8 || (n>1 && key[3]=='0')) return false;
  for(size_t i=3;key[i];++i) if(!((key[i]>='0' && key[i]<='9') || (key[i]>='a' && key[i]<='f'))) return false;
  return true;
}
inline bool legacyValue(const char* value) {
  return value && (!strcmp(value,"starting") || !strcmp(value,"started") ||
    !strcmp(value,"healthy") || !strcmp(value,"failed"));
}
} // namespace fire_run_receipts
