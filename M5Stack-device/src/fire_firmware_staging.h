#pragma once
#include <stddef.h>
#include <string.h>

// Storage belongs to the firmware worker; this guard never allocates internally.
// A verified complete image and a stopped socket worker are required before SD.
class FireFirmwareStaging {
 public:
  static bool fits(size_t bytes, size_t limit, size_t free, size_t largest, size_t reserve) {
    return bytes && bytes <= limit && bytes <= largest && bytes <= free && reserve <= free - bytes;
  }
  void attach(unsigned char* bytes, size_t size) {
    bytes_ = bytes; expected_ = bytes ? size : 0; received_ = 0; verified_ = false;
  }
  template<class Hash>
  bool append(Hash& hash, const unsigned char* bytes, size_t size) {
    if (!bytes_ || !bytes || !size || verified_ || size > expected_ - received_) return false;
    memcpy(bytes_ + received_, bytes, size);
    if (hash.update(bytes, size)) return false;
    received_ += size;
    return true;
  }
  bool verify(bool hashMatches) {
    verified_ = bytes_ && expected_ && received_ == expected_ && hashMatches;
    return verified_;
  }
  bool readyForSd(bool networkRunning) const { return verified_ && !networkRunning; }
  size_t received() const { return received_; }
 private:
  unsigned char* bytes_ = nullptr;
  size_t expected_ = 0, received_ = 0;
  bool verified_ = false;
};
