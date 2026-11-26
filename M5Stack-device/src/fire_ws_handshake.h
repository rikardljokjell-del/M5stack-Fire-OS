#pragma once
#include <stddef.h>
#include <string.h>

inline bool fireWsEqual(const char* a, size_t n, const char* b, bool fold = false) {
  if (strlen(b) != n) return false;
  for (size_t i = 0; i < n; ++i) {
    char left = a[i], right = b[i];
    if (fold) { if (left >= 'A' && left <= 'Z') left += 32; if (right >= 'A' && right <= 'Z') right += 32; }
    if (left != right) return false;
  }
  return true;
}
// Bounded HTTP upgrade validation, including the exact nonce-derived proof.
inline bool fireWsAccepted(const char* headers, size_t length, const char* expected) {
  if (!headers || !expected || strlen(expected) != 28 || length < 16 || length > 4096 || memcmp(headers, "HTTP/1.1 101 ", 13)) return false;
  if (memcmp(headers + length - 4, "\r\n\r\n", 4)) return false;
  for (size_t i = 0; i < length; ++i) if (!headers[i] || (static_cast<unsigned char>(headers[i]) < 32 && headers[i] != '\r' && headers[i] != '\n' && headers[i] != '\t')) return false;
  size_t at = 0; while (at + 1 < length && !(headers[at] == '\r' && headers[at + 1] == '\n')) ++at;
  at += 2; unsigned upgrade = 0, connection = 0, accept = 0;
  while (at + 2 < length) {
    size_t end = at; while (end + 1 < length && !(headers[end] == '\r' && headers[end + 1] == '\n')) ++end;
    size_t colon = at; while (colon < end && headers[colon] != ':') ++colon;
    if (colon == at || colon == end) return false;
    size_t value = colon + 1, tail = end;
    while (value < tail && (headers[value] == ' ' || headers[value] == '\t')) ++value;
    while (tail > value && (headers[tail - 1] == ' ' || headers[tail - 1] == '\t')) --tail;
    if (fireWsEqual(headers + at, colon - at, "upgrade", true)) {
      if (++upgrade != 1 || !fireWsEqual(headers + value, tail - value, "websocket", true)) return false;
    } else if (fireWsEqual(headers + at, colon - at, "connection", true)) {
      if (++connection != 1) return false;
      bool found = false;
      while (value < tail) {
        size_t next = value; while (next < tail && headers[next] != ',') ++next;
        size_t tokenEnd = next; while (tokenEnd > value && (headers[tokenEnd - 1] == ' ' || headers[tokenEnd - 1] == '\t')) --tokenEnd;
        if (fireWsEqual(headers + value, tokenEnd - value, "upgrade", true)) found = true;
        value = next + 1; while (value < tail && (headers[value] == ' ' || headers[value] == '\t')) ++value;
      }
      if (!found) return false;
    } else if (fireWsEqual(headers + at, colon - at, "sec-websocket-accept", true)) {
      if (++accept != 1 || !fireWsEqual(headers + value, tail - value, expected)) return false;
    }
    at = end + 2;
  }
  return upgrade == 1 && connection == 1 && accept == 1;
}

// Sequence numbers belong to one authenticated backend session. Resume keeps
// its watermark; a genuinely new session starts its own sequence at one.
inline bool fireWsNewSession(const char* incoming,const char* current,const char* resume) {
  return incoming && *incoming && (!current || strcmp(incoming,current)) && (!resume || strcmp(incoming,resume));
}
