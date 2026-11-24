#include "fire_reverse_transport.h"

namespace {
constexpr uint32_t kAuthTimeoutMs = 4000;
constexpr size_t kMaxAuthBytes = 1024;
constexpr size_t kAuthWorkBytesPerService = 128;
}

FireReverseTransport::FireReverseTransport() : server_(kPort) {}

void FireReverseTransport::configure(const String& deviceId,
                                     const String& token) {
  if (deviceId_ == deviceId && token_ == token) return;
  stop();
  deviceId_ = deviceId;
  token_ = token;
}

void FireReverseTransport::stop() {
  accepting_ = false; ++generation_;
  if (listening_) server_.stop();
  listening_ = false;
  for (uint8_t index = 0; index < kMaxConnections; ++index)
    resetSlot(index);
}

void FireReverseTransport::resetSlot(uint8_t index) {
  if (index >= kMaxConnections) return;
  Slot& slot = slots_[index];
  slot.cancelled = true;
  SlotState before = slot.state;
  if (before == SlotState::InUse || before == SlotState::Maintenance ||
      !slot.state.compare_exchange_strong(before, SlotState::Maintenance)) return;
  slot.client.stop(); slot.authLine = ""; slot.acceptedAt = 0;
  slot.state = SlotState::Empty;
}

void FireReverseTransport::service(bool wifiConnected) {
  if (!wifiConnected || deviceId_.length() == 0 || token_.length() < 24) {
    if (listening_) stop();
    return;
  }

  if (!listening_) {
    server_.begin();
    listening_ = true;
    accepting_ = true;
  }

  for (uint8_t index = 0; index < kMaxConnections; ++index) {
    const SlotState state = slots_[index].state;
    if (state == SlotState::Empty || state == SlotState::InUse || state == SlotState::Maintenance) continue;
    if (state == SlotState::Authenticating) {
      if (!slots_[index].client.connected()) { resetSlot(index); continue; }
      serviceAuthentication(index);
    } else {
      SlotState ready = SlotState::Ready;
      if (slots_[index].state.compare_exchange_strong(ready, SlotState::Maintenance)) {
        if (slots_[index].client.connected()) slots_[index].state = SlotState::Ready;
        else { slots_[index].client.stop(); slots_[index].state = SlotState::Empty; }
      }
    }
  }

  WiFiClient incoming = server_.available();
  if (!incoming) return;
  for (uint8_t index = 0; index < kMaxConnections; ++index) {
    SlotState empty = SlotState::Empty;
    if (!slots_[index].state.compare_exchange_strong(empty, SlotState::Maintenance)) continue;
    slots_[index].client = incoming;
    slots_[index].client.setNoDelay(true);
    slots_[index].authLine = "";
    slots_[index].acceptedAt = millis();
    slots_[index].cancelled = false;
    slots_[index].state = SlotState::Authenticating;
    return;
  }
  // The fixed pool is full. Do not keep an unauthenticated excess socket.
  incoming.stop();
}

void FireReverseTransport::serviceAuthentication(uint8_t index) {
  Slot& slot = slots_[index];
  if (millis() - slot.acceptedAt > kAuthTimeoutMs) {
    resetSlot(index);
    return;
  }

  size_t processed = 0;
  while (slot.client.available() && processed < kAuthWorkBytesPerService) {
    const int value = slot.client.read();
    if (value < 0) return;
    ++processed;
    if (value == '\n') {
      if (authenticate(slot.authLine)) {
        const String response =
            "{\"type\":\"reverse_ready\",\"version\":1,\"device_id\":\"" +
            deviceId_ + "\"}\n";
        if (slot.client.print(response) != response.length()) { resetSlot(index); return; }
        slot.authLine = "";
        slot.state = SlotState::Ready;
      } else {
        resetSlot(index);
      }
      return;
    }
    if (slot.authLine.length() >= kMaxAuthBytes) {
      resetSlot(index);
      return;
    }
    slot.authLine += static_cast<char>(value);
  }
}

WiFiClient* FireReverseTransport::acquire(uint32_t expectedGeneration) {
  const uint32_t generation = generation_;
  if (!accepting_ || (expectedGeneration && expectedGeneration != generation)) return nullptr;
  for (uint8_t index = 0; index < kMaxConnections; ++index) {
    SlotState ready = SlotState::Ready;
    if (slots_[index].state.compare_exchange_strong(ready, SlotState::InUse)) {
      auto* client = &slots_[index].client;
      if (!accepting_ || generation != generation_ || slots_[index].cancelled || !client->connected()) { release(client); continue; }
      return client;
    }
  }
  return nullptr;
}

void FireReverseTransport::release(WiFiClient* client) {
  if (!client) return;
  for (uint8_t index = 0; index < kMaxConnections; ++index) {
    if (&slots_[index].client == client) {
      // The borrower alone closes and clears an InUse socket. UI stop only
      // marks it cancelled, so no object is reassigned beneath an I/O worker.
      if (slots_[index].state != SlotState::InUse) return;
      slots_[index].client.stop(); slots_[index].authLine = ""; slots_[index].acceptedAt = 0;
      slots_[index].cancelled = false; slots_[index].state = SlotState::Empty;
      return;
    }
  }
}

bool FireReverseTransport::hasReadyConnection() {
  for (Slot& slot : slots_) {
    if (accepting_ && slot.state == SlotState::Ready) return true;
  }
  return false;
}
bool FireReverseTransport::cancelled(WiFiClient* client) const {
  for (const Slot& slot : slots_) if (&slot.client == client) return slot.cancelled;
  return true;
}

bool FireReverseTransport::authenticate(const String& line) const {
  if (line.length() == 0 || line.length() > kMaxAuthBytes) return false;
  if (jsonStringField(line, "type") != "reverse_open" ||
      jsonIntField(line, "version", -1) != 1)
    return false;
  const String suppliedDevice = jsonStringField(line, "device_id");
  const String suppliedToken = jsonStringField(line, "token");
  return constantEquals(suppliedDevice, deviceId_) &&
         constantEquals(suppliedToken, token_);
}

bool FireReverseTransport::constantEquals(const String& left,
                                           const String& right) {
  if (left.length() != right.length()) return false;
  uint8_t difference = 0;
  for (size_t index = 0; index < left.length(); ++index)
    difference |= static_cast<uint8_t>(left[index] ^ right[index]);
  return difference == 0;
}

String FireReverseTransport::jsonStringField(const String& json,
                                             const char* key) {
  const String marker = String("\"") + key + "\"";
  const int keyAt = json.indexOf(marker);
  if (keyAt < 0) return "";
  const int colon = json.indexOf(':', keyAt + marker.length());
  const int start = json.indexOf('"', colon + 1);
  if (colon < 0 || start < 0) return "";
  String value;
  bool escaped = false;
  for (int index = start + 1; index < json.length(); ++index) {
    const char character = json[index];
    if (escaped) {
      value += character;
      escaped = false;
    } else if (character == '\\') {
      escaped = true;
    } else if (character == '"') {
      break;
    } else {
      value += character;
    }
  }
  return value;
}

int FireReverseTransport::jsonIntField(const String& json, const char* key,
                                        int fallback) {
  const String marker = String("\"") + key + "\"";
  const int keyAt = json.indexOf(marker);
  if (keyAt < 0) return fallback;
  const int colon = json.indexOf(':', keyAt + marker.length());
  if (colon < 0) return fallback;
  int start = colon + 1;
  while (start < json.length() &&
         (json[start] == ' ' || json[start] == '\t'))
    ++start;
  return json.substring(start).toInt();
}
