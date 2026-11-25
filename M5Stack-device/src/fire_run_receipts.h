#pragma once
#include "fire_lua_install_identity.h"

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
