#pragma once
#include <stdint.h>
#include <cstring>
namespace fire_app_updates {
inline bool active(uint8_t phase,bool quickSettings) {return phase && !quickSettings;}
enum class Action:uint8_t {Wait,Download,Installed,Suppress,Minimize,RunVerified};
inline Action confirm(uint8_t phase,uint8_t choice,bool verified) {
  if(phase==2) return Action::Minimize;
  if(phase==3) return verified?Action::RunVerified:Action::Wait;
  if(phase!=1 || choice>2) return Action::Wait;
  return choice==0?Action::Download:choice==1?Action::Installed:Action::Suppress;
}
inline uint8_t completed(uint8_t phase,bool ok) {return phase==2?(ok?3:1):phase;}

inline bool version(const char* value,uint32_t (&parts)[3]) {
  if (!value) return false;
  for (unsigned n=0;n<3;++n) {
    parts[n]=0;unsigned digits=0;
    while (*value>='0' && *value<='9') {
      if (++digits>6) return false;
      parts[n]=parts[n]*10+unsigned(*value++-'0');
    }
    if (!digits || (n<2 && *value++!='.')) return false;
  }
  return !*value; // unknown prerelease/suffix never guessed newer
}
inline bool newer(const char* installed,const char* latest) {
  uint32_t a[3],b[3];if(!version(installed,a) || !version(latest,b)) return false;
  for(unsigned i=0;i<3;++i) {if(a[i]!=b[i]) return b[i]>a[i];}
  return false;
}
inline bool eligible(bool online,bool suppressed,bool downloadable,uint32_t epoch,uint32_t cachedEpoch,
    uint32_t now,uint32_t cachedAt,const char* localApp,const char* remoteApp,const char* project,
    const char* installedPackage,const char* latestPackage,const char* installedVersion,const char* latestVersion) {
  return online && !suppressed && downloadable && epoch && epoch==cachedEpoch && uint32_t(now-cachedAt)<=60000 &&
      localApp && *localApp && remoteApp && !strcmp(localApp,remoteApp) && project && *project &&
      installedPackage && *installedPackage && latestPackage && *latestPackage && strcmp(installedPackage,latestPackage) &&
      newer(installedVersion,latestVersion);
}
} // namespace fire_app_updates
