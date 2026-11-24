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
  std::puts("PASS strict WebSocket nonce/header validation");
}
