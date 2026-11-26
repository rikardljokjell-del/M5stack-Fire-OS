#include "fire_ws_handshake.h"
#include <cassert>
#include <string>
#include <cstdio>
int main() {
  const char* accept = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=";
  const std::string valid = std::string("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: keep-alive, Upgrade\r\nSec-WebSocket-Accept: ") + accept + "\r\n\r\n";
  assert(fireWsAccepted(valid.data(), valid.size(), accept));
  assert(!fireWsAccepted(valid.data(), valid.size(), "AAAAAAAAAAAAAAAAAAAAAAAAAAA="));
  for (const char* field : {"Upgrade: websocket", "Sec-WebSocket-Accept: ", "HTTP/1.1 101 ", "Connection: keep-alive, Upgrade"}) {
    std::string wrong = valid; const size_t at = wrong.find(field); wrong[at] = '!';
    assert(!fireWsAccepted(wrong.data(), wrong.size(), accept));
  }
  std::string duplicate = valid.substr(0, valid.size() - 2) + "Sec-WebSocket-Accept: " + accept + "\r\n\r\n";
  assert(!fireWsAccepted(duplicate.data(), duplicate.size(), accept));
  assert(!fireWsAccepted(valid.data(), valid.size() - 1, accept));
  std::string nul = valid; nul[22] = 0; assert(!fireWsAccepted(nul.data(), nul.size(), accept));
  assert(fireWsNewSession("new","old","old"));
  assert(!fireWsNewSession("old","old",""));
  assert(!fireWsNewSession("old","","old"));
  assert(!fireWsNewSession("","old","old"));
  assert(fireWsNewSession("new","",""));
  assert(!fireWsSessionExpired(false,5999,1000));
  assert(fireWsSessionExpired(false,6000,1000));
  assert(fireWsSessionExpired(false,65000,1000)); // healthy transport PONG cannot admit a session
  assert(!fireWsSessionExpired(true,65000,1000));
  const uint32_t nearWrap=UINT32_MAX-2500;
  assert(!fireWsSessionExpired(false,nearWrap+4999,nearWrap));
  assert(fireWsSessionExpired(false,nearWrap+5000,nearWrap));
  assert(fireWsSessionRejected(false,"error","session_start_rejected",true));
  assert(!fireWsSessionRejected(true,"error","session_start_rejected",true));
  assert(!fireWsSessionRejected(false,"error","session_start_rejected",false));
  assert(!fireWsSessionRejected(false,"error","event_rejected",true));
  assert(!fireWsSessionRejected(false,"app_failed","session_start_rejected",true));
  assert(!fireWsSessionRejected(false,nullptr,nullptr,true));
  FireWsSessionAdmission admission;
  assert(admission.allowed());
  assert(!admission.reject(true,"error","session_start_rejected",true) && admission.allowed());
  assert(admission.reject(false,"error","session_start_rejected",true) && !admission.allowed());
  assert(!admission.reject(false,"error","event_rejected",true) && !admission.allowed()); // no implicit unblock/replay
  admission.retry(); // the same production operation used by explicit OFF-to-ON/configuration
  assert(admission.allowed());
  assert(!admission.reject(false,"session_started",nullptr,false) && admission.allowed()); // safe backend expired/stopped recovery
  assert(admission.reject(false,"error","session_start_rejected",true) && !admission.allowed()); // mismatch remains terminal
  std::puts("PASS bounded session deadline typed rejection and explicit policy retry");
  std::puts("PASS strict WebSocket nonce/header validation");
}
