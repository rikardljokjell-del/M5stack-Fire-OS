#pragma once

#include <Arduino.h>
#include <WiFi.h>
#include <atomic>

// Small, authenticated reverse-TCP pool used when the PC can reach FIRE but
// FIRE cannot open a connection back to the PC.  The bytes after the
// reverse_open newline remain in the WiFiClient receive buffer and are handed
// to the normal WebSocket/HTTP client unchanged.
class FireReverseTransport {
 public:
  static constexpr uint8_t kMaxConnections = 4;
  static constexpr uint16_t kPort = 8766;

  FireReverseTransport();

  void configure(const String& deviceId, const String& token);
  void service(bool wifiConnected);
  void stop();

  WiFiClient* acquire(uint32_t generation = 0);
  void release(WiFiClient* client);
  bool cancelled(WiFiClient* client) const;
  uint32_t generation() const { return generation_; }
  bool hasReadyConnection();
  bool listening() const { return listening_; }

 private:
  enum class SlotState : uint8_t { Empty, Authenticating, Ready, InUse, Maintenance };
  struct Slot {
    WiFiClient client;
    std::atomic<SlotState> state{SlotState::Empty};
    std::atomic<bool> cancelled{false};
    String authLine;
    uint32_t acceptedAt = 0;
  };

  WiFiServer server_;
  Slot slots_[kMaxConnections];
  String deviceId_;
  String token_;
  bool listening_ = false;
  std::atomic<bool> accepting_{false};
  std::atomic<uint32_t> generation_{1};

  void resetSlot(uint8_t index);
  void serviceAuthentication(uint8_t index);
  bool authenticate(const String& line) const;
  static String jsonStringField(const String& json, const char* key);
  static int jsonIntField(const String& json, const char* key, int fallback);
  static bool constantEquals(const String& left, const String& right);
};
