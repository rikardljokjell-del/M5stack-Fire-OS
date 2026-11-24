#pragma once
#include <stddef.h>
#include <stdint.h>

// String-aware preflight before cJSON allocation/recursion. Validates UTF-8,
// bounded structural depth/token count and bracket matching without a heap.
inline bool fireJsonSafe(const char* json, size_t length, size_t maximum,
                         unsigned maxDepth = 12, unsigned maxTokens = 1024) {
  if (!json || !length || length > maximum || maxDepth > 16) return false;
  char stack[16]; unsigned depth = 0, tokens = 0; bool quoted = false, escape = false;
  for (size_t i = 0; i < length; ++i) {
    const uint8_t c = static_cast<uint8_t>(json[i]);
    if (!c) return false;
    if (c >= 128) {
      unsigned n = c >= 0xc2 && c <= 0xdf ? 1 : c >= 0xe0 && c <= 0xef ? 2 : c >= 0xf0 && c <= 0xf4 ? 3 : 9;
      if (n == 9 || i + n >= length) return false;
      const uint8_t second = static_cast<uint8_t>(json[i + 1]);
      if ((c == 0xe0 && second < 0xa0) || (c == 0xed && second >= 0xa0) ||
          (c == 0xf0 && second < 0x90) || (c == 0xf4 && second >= 0x90)) return false;
      for (unsigned k = 1; k <= n; ++k) if ((static_cast<uint8_t>(json[i + k]) & 0xc0) != 0x80) return false;
      if (!quoted || escape) return false;
      i += n; continue;
    }
    if (quoted) {
      if (c < 32) return false;
      if (escape) { escape = false; continue; }
      if (c == '\\') escape = true; else if (c == '"') quoted = false;
      continue;
    }
    if (c == '"') { quoted = true; if (++tokens > maxTokens) return false; }
    else if (c == '{' || c == '[') {
      if (depth >= maxDepth || ++tokens > maxTokens) return false;
      stack[depth++] = c;
    } else if (c == '}' || c == ']') {
      if (!depth || stack[--depth] != (c == '}' ? '{' : '[')) return false;
    } else if (c == ',' || c == ':') { if (++tokens > maxTokens) return false; }
    else if (c < 32 && c != '\r' && c != '\n' && c != '\t') return false;
  }
  return !quoted && !escape && !depth;
}
