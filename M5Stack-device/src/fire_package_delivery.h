#pragma once
#include <stdint.h>
#include <cstring>
namespace fire_package_delivery {
inline bool wireId(const char* s) {
  if (!s || !*s) return false;
  unsigned n=0;
  for (;s[n];++n) if (n>=64 || !((s[n]>='a' && s[n]<='z') || (s[n]>='0' && s[n]<='9') || (n && (s[n]=='_' || s[n]=='-')))) return false;
  return true;
}
inline bool sameScope(const char* sid,const char* boot,const char* actualSid,const char* actualBoot) {
  return wireId(sid) && wireId(boot) && actualSid && actualBoot && !strcmp(sid,actualSid) && !strcmp(boot,actualBoot);
}
inline bool admittedScope(bool connected,const char* sid,const char* boot,const char* actualSid,const char* actualBoot) {
  return !connected || sameScope(sid,boot,actualSid,actualBoot);
}
inline bool handoffReady(bool preconnected,bool ready) {return !preconnected || ready;}

enum class Phase:uint8_t {Idle,Waiting,Quiet,Connecting,Streaming,TlsCleanup,Worker,Cleanup,Receipt};
enum class Action:uint8_t {None,Connect,Stream,Start,Cancel,Busy,Timeout,Notify};
struct Gate {
  Phase phase=Phase::Idle;
  uint32_t startedAt=0,lastReceiptAt=0;
  bool exclusive=false,ownsQuiet=false,sent=false;
  void begin(uint32_t now,bool tls) {phase=Phase::Waiting;startedAt=now;lastReceiptAt=0;exclusive=tls;ownsQuiet=false;sent=false;}
  bool paused() const {return ownsQuiet && phase!=Phase::Receipt && phase!=Phase::Idle;}
  bool active() const {return phase!=Phase::Idle;}
  bool otherNetworksPaused() const {return ownsQuiet && phase!=Phase::Idle;} // Receipt reserves TLS for backend ACK only.
  Action poll(uint32_t now,bool allowed,bool busy,bool quiet,bool worker,bool network,bool completed,bool ready=false,bool staged=false) {
    if (phase==Phase::Waiting) {
      if (!allowed) return Action::Cancel;
      if (busy) return uint32_t(now-startedAt)>=12000?Action::Busy:Action::None;
      if (!exclusive) {phase=Phase::Worker;return Action::Start;}
      phase=Phase::Quiet;ownsQuiet=true;startedAt=now;
    }
    if (phase==Phase::Quiet) {
      if (!allowed) return Action::Cancel;
      if (quiet) {phase=Phase::Connecting;startedAt=now;return Action::Connect;}
      return uint32_t(now-startedAt)>=12000?Action::Busy:Action::None;
    }
    if (phase==Phase::Connecting) {
      if (!allowed) return Action::Cancel;
      if (uint32_t(now-startedAt)>=18000) return Action::Timeout;
      if (ready) {phase=Phase::Streaming;return Action::Stream;}
      return Action::None;
    }
    if (phase==Phase::Streaming) {
      if (!allowed) return Action::Cancel;
      if (staged) phase=Phase::TlsCleanup;
    }
    if (phase==Phase::TlsCleanup) {
      if (!allowed) return Action::Cancel;
      if (!network && staged) {phase=Phase::Worker;return Action::Start;}
    }
    if (phase==Phase::Worker) {
      if (!worker && completed) phase=Phase::Cleanup;
      else if (!allowed) return Action::Cancel;
    }
    if (phase==Phase::Cleanup && !worker && !network) {phase=Phase::Receipt;return Action::Notify;}
    return Action::None;
  }
  bool receiptDue(uint32_t now) const {return phase==Phase::Receipt && (!sent || uint32_t(now-lastReceiptAt)>=3000);}
  void receiptSent(uint32_t now) {sent=true;lastReceiptAt=now;}
  void clear() {phase=Phase::Idle;ownsQuiet=false;sent=false;}
};
inline const char* receiptLabel(bool installed,bool cancelled,bool connected) {
  if(cancelled) return installed?"Installert, start avbrutt":"Avbrutt, sender kvittering";
  if(installed) return connected?"Installert, sender kvittering":"Installert, kobler til";
  return connected?"Nedlasting feilet, sender kvittering":"Nedlasting feilet, kobler til";
}
inline bool recordedAck(const char* expectedEvent,const char* event,const char* status,const char* resultStatus,
                        const char* expectedPackage,const char* package,bool error) {
  return expectedEvent && event && !strcmp(expectedEvent,event) && status &&
      (!strcmp(status,"accepted") || !strcmp(status,"duplicate")) && resultStatus && !strcmp(resultStatus,"recorded") &&
      expectedPackage && package && !strcmp(expectedPackage,package) && !error;
}
} // namespace fire_package_delivery
