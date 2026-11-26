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
// Known metadata is only a read-only suggestion; app_download remains the grant.
inline bool knownEpoch(uint32_t epoch,uint32_t cachedEpoch) {return epoch && epoch==cachedEpoch;}
inline bool catalogDue(uint32_t now,bool loading,bool requested,uint32_t completedAt,uint32_t attemptedAt,uint8_t failures) {
  if (loading) return false;
  const uint32_t cooldown=failures>=2?45000:failures?3000:0;
  if (attemptedAt && uint32_t(now-attemptedAt)<cooldown) return false;
  return !requested || uint32_t(now-completedAt)>=45000;
}
inline bool catalogTimeout(uint32_t now,bool loading,uint32_t requestedAt) {return loading && uint32_t(now-requestedAt)>=5000;}
inline bool catalogReply(uint32_t epoch,uint32_t requestedEpoch,int32_t offset,int32_t requestedOffset,
    const char* request,const char* received) {
  return knownEpoch(epoch,requestedEpoch) && offset==requestedOffset && request && *request && received && !strcmp(request,received);
}
inline bool seen(uint32_t mask,uint8_t index) {return index<32 && (mask & (uint32_t(1)<<index));}

inline bool eligible(bool online,bool suppressed,bool downloadable,uint32_t epoch,uint32_t cachedEpoch,
    uint32_t now,uint32_t cachedAt,const char* localApp,const char* remoteApp,const char* project,
    const char* installedPackage,const char* latestPackage,const char* installedVersion,const char* latestVersion) {
  (void)now;(void)cachedAt;
  return online && !suppressed && downloadable && knownEpoch(epoch,cachedEpoch) &&
      localApp && *localApp && remoteApp && !strcmp(localApp,remoteApp) && project && *project &&
      installedPackage && *installedPackage && latestPackage && *latestPackage && strcmp(installedPackage,latestPackage) &&
      newer(installedVersion,latestVersion);
}
} // namespace fire_app_updates
