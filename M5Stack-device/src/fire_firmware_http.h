#pragma once

#include <cstddef>
#include <cstdint>

// Portable, bounded validation of the complete HTTP header block, without body
// bytes. Callers must still enforce the declared length while reading the body.
namespace fire_firmware_http {
namespace detail {

inline bool tokenCharacter(unsigned char c) {
  if ((c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') ||
      (c >= 'a' && c <= 'z')) return true;
  switch (c) {
    case '!': case '#': case '$': case '%': case '&': case '\'':
    case '*': case '+': case '-': case '.': case '^': case '_':
    case '`': case '|': case '~': return true;
    default: return false;
  }
}

inline bool nameEquals(const char* name, size_t length, const char* expected) {
  size_t i = 0;
  for (; i < length && expected[i] != '\0'; ++i) {
    unsigned char c = static_cast<unsigned char>(name[i]);
    if (c >= 'A' && c <= 'Z') c = static_cast<unsigned char>(c + ('a' - 'A'));
    if (c != static_cast<unsigned char>(expected[i])) return false;
  }
  return i == length && expected[i] == '\0';
}

inline bool whitespace(char c) { return c == ' ' || c == '\t'; }

}  // namespace detail

inline bool validResponse(const char* header, size_t length,
                          uint32_t expectedLength) {
  constexpr size_t kMaximumHeader = 8192;
  constexpr uint32_t kMaximumFirmware = 4194304;
  if (header == nullptr || length < 4 || length > kMaximumHeader ||
      expectedLength == 0 || expectedLength > kMaximumFirmware) return false;

  // Validate framing and ASCII before parsing individual lines. HTAB is allowed
  // only as HTTP whitespace; line parsing below excludes it from field names.
  for (size_t i = 0; i < length; ++i) {
    const unsigned char c = static_cast<unsigned char>(header[i]);
    if (c == '\r') {
      if (i + 1 >= length || header[i + 1] != '\n') return false;
      ++i;
    } else if (c == '\n' || (c < 0x20 && c != '\t') || c > 0x7e) {
      return false;
    }
  }

  size_t lineEnd = 0;
  while (lineEnd < length && header[lineEnd] != '\r') ++lineEnd;
  // A separating space after exactly three status digits is mandatory.
  constexpr char kStatus[] = "HTTP/1.1 200 ";
  constexpr size_t kStatusLength = sizeof(kStatus) - 1;
  if (lineEnd < kStatusLength || lineEnd + 1 >= length) return false;
  for (size_t i = 0; i < kStatusLength; ++i) {
    if (i == 7) {
      if (header[i] != '0' && header[i] != '1') return false;
    } else if (header[i] != kStatus[i]) {
      return false;
    }
  }

  bool foundLength = false;
  size_t position = lineEnd + 2;
  while (position < length) {
    lineEnd = position;
    while (lineEnd < length && header[lineEnd] != '\r') ++lineEnd;
    if (lineEnd + 1 >= length) return false;
    if (lineEnd == position) {
      // Reject any second header block or body after the first terminator.
      return foundLength && lineEnd + 2 == length;
    }
    if (detail::whitespace(header[position])) return false;  // No obs-fold.

    size_t colon = position;
    while (colon < lineEnd && header[colon] != ':') {
      if (!detail::tokenCharacter(static_cast<unsigned char>(header[colon])))
        return false;
      ++colon;
    }
    if (colon == position || colon == lineEnd) return false;
    const size_t nameLength = colon - position;
    if (detail::nameEquals(header + position, nameLength, "transfer-encoding") ||
        detail::nameEquals(header + position, nameLength, "content-encoding"))
      return false;

    if (detail::nameEquals(header + position, nameLength, "content-length")) {
      if (foundLength) return false;
      foundLength = true;
      size_t first = colon + 1;
      size_t last = lineEnd;
      while (first < last && detail::whitespace(header[first])) ++first;
      while (first < last && detail::whitespace(header[last - 1])) --last;
      if (first == last) return false;
      uint32_t value = 0;
      for (size_t i = first; i < last; ++i) {
        if (header[i] < '0' || header[i] > '9') return false;
        const uint32_t digit = static_cast<uint32_t>(header[i] - '0');
        if (value > (UINT32_MAX - digit) / 10) return false;
        value = value * 10 + digit;
      }
      if (value != expectedLength) return false;
    }
    position = lineEnd + 2;
  }
  return false;
}

}  // namespace fire_firmware_http
