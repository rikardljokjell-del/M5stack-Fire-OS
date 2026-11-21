#include "fire_backend_client.h"

#include <base64.h>
#include <esp_system.h>

namespace {
constexpr size_t kMaxFrameBytes = 8192;

String jsonEscape(const String& input) {
  String output;
  output.reserve(input.length() + 8);
  for (size_t index = 0; index < input.length(); ++index) {
    const char value = input[index];
    if (value == '\\' || value == '"') output += '\\';
    if (value == '\n') {
      output += "\\n";
    } else if (value == '\r') {
      output += "\\r";
    } else {
      output += value;
    }
  }
  return output;
}
}  // namespace

void FireBackendClient::configure(const String& host, uint16_t port,
                                  const String& token, const String& deviceId,
                                  const String& firmwareVersion) {
  disconnect();
  host_ = host;
  port_ = port == 0 ? 8765 : port;
  token_ = token;
  if (deviceId.length() > 0) deviceId_ = deviceId;
  if (firmwareVersion.length() > 0) firmwareVersion_ = firmwareVersion;
  bootId_ = "boot-" + String(static_cast<uint32_t>(esp_random()), HEX) +
            String(millis(), HEX);
  status_ = configured() ? "Backend disconnected" : "Backend not configured";
}

void FireBackendClient::setCallbacks(void* context, MessageCallback message,
                                     StateCallback state) {
  callbackContext_ = context;
  messageCallback_ = message;
  stateCallback_ = state;
}

void FireBackendClient::setState(State state, const String& status) {
  if (state_ == state && status_ == status) return;
  state_ = state;
  status_ = status;
  if (stateCallback_) stateCallback_(callbackContext_, connected(), status_);
}

void FireBackendClient::disconnect() {
  if (transportClient_ && reverseTransport_) {
    reverseTransport_->release(transportClient_);
    transportClient_ = nullptr;
  } else if (client_.connected()) {
    client_.stop();
  }
  usingReverseTransport_ = false;
  if (audioTransportClient_ && reverseTransport_) {
    reverseTransport_->release(audioTransportClient_);
    audioTransportClient_ = nullptr;
  } else if (audioClient_.connected()) {
    audioClient_.stop();
  }
  handshakeBuffer_ = "";
  frameBuffer_ = "";
  resetReceiveFrame();
  sessionId_ = "";
  setState(configured() ? State::Offline : State::Offline,
           configured() ? "Backend disconnected" : "Backend not configured");
}

void FireBackendClient::resetReceiveFrame() {
  receiveStage_ = ReceiveStage::Header;
  receiveHeaderBytes_ = 0;
  receiveOpcode_ = 0;
  receiveMasked_ = false;
  receiveExtendedNeeded_ = 0;
  receiveExtendedBytes_ = 0;
  receiveMaskBytes_ = 0;
  receiveLength_ = 0;
  receivePayloadBytes_ = 0;
  frameBuffer_ = "";
}

bool FireBackendClient::uploadAudio(const String& turnId,
                                    const uint8_t* wavData,
                                    size_t wavLength) {
  if (!connected() || sessionId_.length() == 0 || !wavData || wavLength == 0 ||
      wavLength > 524288) {
    return false;
  }
  WiFiClient* audio = nullptr;
  if (reverseTransport_) audioTransportClient_ = reverseTransport_->acquire();
  if (audioTransportClient_) {
    audio = audioTransportClient_;
  } else {
    audioClient_.stop();
    if (!audioClient_.connect(host_.c_str(), port_)) return false;
    audio = &audioClient_;
  }
  auto closeAudio = [&]() {
    if (audioTransportClient_ && reverseTransport_) {
      reverseTransport_->release(audioTransportClient_);
      audioTransportClient_ = nullptr;
    } else {
      audioClient_.stop();
    }
  };
  const String path = "/sessions/" + sessionId_ + "/audio/" + turnId;
  audio->print("POST " + path + " HTTP/1.1\r\nHost: " + host_ + ":" +
               String(port_) + "\r\nAuthorization: Bearer " + token_ +
               "\r\nContent-Type: audio/wav\r\nContent-Length: " +
               String(wavLength) + "\r\nConnection: close\r\n\r\n");
  size_t offset = 0;
  while (offset < wavLength) {
    const size_t amount = min<size_t>(2048, wavLength - offset);
    if (audio->write(wavData + offset, amount) != amount) {
      closeAudio();
      return false;
    }
    offset += amount;
  }
  const uint32_t deadline = millis() + 5000;
  String response;
  while (millis() < deadline && audio->connected() &&
         response.indexOf("\r\n\r\n") < 0) {
    while (audio->available() && response.length() < 512)
      response += static_cast<char>(audio->read());
    if (response.indexOf("\r\n\r\n") < 0) delay(1);
  }
  closeAudio();
  return response.startsWith("HTTP/1.1 2") || response.startsWith("HTTP/1.0 2");
}

String FireBackendClient::eventId(const char* prefix) {
  ++eventCounter_;
  return String(prefix) + "-" + String(millis(), HEX) + "-" +
         String(eventCounter_, HEX);
}

bool FireBackendClient::sendFrame(uint8_t opcode, const uint8_t* data,
                                  size_t length) {
  WiFiClient* client = activeClient();
  if (!client || !client->connected() || length > kMaxFrameBytes) return false;
  uint8_t header[10] = {};
  size_t headerLength = 2;
  header[0] = 0x80 | (opcode & 0x0F);
  if (length < 126) {
    header[1] = 0x80 | static_cast<uint8_t>(length);
  } else if (length <= 0xFFFF) {
    header[1] = 0x80 | 126;
    header[2] = static_cast<uint8_t>(length >> 8);
    header[3] = static_cast<uint8_t>(length);
    headerLength = 4;
  } else {
    return false;
  }
  uint8_t mask[4] = {static_cast<uint8_t>(esp_random()),
                     static_cast<uint8_t>(esp_random()),
                     static_cast<uint8_t>(esp_random()),
                     static_cast<uint8_t>(esp_random())};
  memcpy(header + headerLength, mask, sizeof(mask));
  headerLength += sizeof(mask);
  if (client->write(header, headerLength) != headerLength) return false;
  uint8_t chunk[256];
  size_t offset = 0;
  while (offset < length) {
    const size_t amount = min(sizeof(chunk), length - offset);
    for (size_t index = 0; index < amount; ++index)
      chunk[index] = data[offset + index] ^ mask[(offset + index) & 3];
    if (client->write(chunk, amount) != amount) return false;
    offset += amount;
  }
  return true;
}

bool FireBackendClient::sendEvent(const String& event, const String& fields) {
  if (!connected()) return false;
  String payload = "{\"type\":\"device_event\",\"protocol_version\":\"0.2\",\"event_id\":\"" +
                   eventId("evt") + "\",\"device_id\":\"" +
                   jsonEscape(deviceId_) + "\",\"event\":\"" + event +
                   "\",\"boot_id\":\"" + jsonEscape(bootId_) + "\"";
  if (sessionId_.length() > 0)
    payload += ",\"session_id\":\"" + jsonEscape(sessionId_) + "\"";
  payload += fields + "}";
  return sendFrame(0x1, reinterpret_cast<const uint8_t*>(payload.c_str()),
                   payload.length());
}

bool FireBackendClient::listenStart(const String& turnId) {
  return sendEvent("listen_start", ",\"turn_id\":\"" + jsonEscape(turnId) + "\"");
}

bool FireBackendClient::listenStop(const String& turnId) {
  return sendEvent("listen_stop", ",\"turn_id\":\"" + jsonEscape(turnId) + "\"");
}

bool FireBackendClient::cancelTurn() { return sendEvent("cancel_turn"); }

bool FireBackendClient::confirmBuild(const String& proposalId) {
  return sendEvent("build_confirm", ",\"proposal_id\":\"" +
                   jsonEscape(proposalId) + "\"");
}

bool FireBackendClient::confirmRun(const String& packageId) {
  return sendEvent("run_confirm", ",\"package_id\":\"" +
                   jsonEscape(packageId) + "\"");
}

bool FireBackendClient::appStop() { return sendEvent("app_stop"); }

bool FireBackendClient::deviceInstallResult(const String& installId,
                                             const String& packageId, bool ok,
                                             const String& archiveHash,
                                             const String& message) {
  return sendEvent("device_install_result", ",\"install_id\":\"" +
                   jsonEscape(installId) + "\",\"package_id\":\"" +
                   jsonEscape(packageId) + "\",\"status\":\"" +
                   (ok ? "ok" : "failed") + "\",\"archive_sha256\":\"" +
                   jsonEscape(archiveHash) + "\",\"message\":\"" +
                   jsonEscape(message.substring(0, 240)) + "\"");
}

bool FireBackendClient::appStarted(const String& runId, const String& packageId) {
  return sendEvent("app_started", ",\"run_id\":\"" + jsonEscape(runId) +
                   "\",\"package_id\":\"" + jsonEscape(packageId) + "\"");
}

bool FireBackendClient::appHealthy(const String& runId, const String& packageId) {
  return sendEvent("app_healthy", ",\"run_id\":\"" + jsonEscape(runId) +
                   "\",\"package_id\":\"" + jsonEscape(packageId) + "\"");
}

bool FireBackendClient::appFailed(const String& runId, const String& packageId,
                                  const String& errorCode,
                                  const String& message) {
  return sendEvent("app_failed", ",\"run_id\":\"" + jsonEscape(runId) +
                   "\",\"package_id\":\"" + jsonEscape(packageId) +
                   "\",\"error_code\":\"" + jsonEscape(errorCode) +
                   "\",\"message\":\"" + jsonEscape(message.substring(0, 240)) +
                   "\"");
}

bool FireBackendClient::ping() { return sendEvent("ping"); }

void FireBackendClient::service(bool wifiConnected) {
  if (!configured()) {
    if (state_ != State::Offline || status_ != "Backend not configured")
      setState(State::Offline, "Backend not configured");
    return;
  }
  if (!wifiConnected) {
    if (state_ != State::Offline) disconnect();
    setState(State::Offline, "Waiting for Wi-Fi");
    return;
  }
  if (state_ == State::Offline) {
    if (millis() < reconnectAt_) return;
    reconnectAt_ = millis() + 3000;
    WiFiClient* client = nullptr;
    if (reverseTransport_) transportClient_ = reverseTransport_->acquire();
    if (transportClient_) {
      client = transportClient_;
      usingReverseTransport_ = true;
    } else {
      client = &client_;
    }
    setState(State::Connecting,
             usingReverseTransport_ ? "Connecting via Reverse TCP"
                                     : "Connecting to backend");
    // A failed backend must never stall the UI for the platform TCP default
    // timeout.  Retry is deliberately throttled by reconnectAt_.
    if (!usingReverseTransport_) {
      client->setTimeout(1200);
    }
    if (!usingReverseTransport_ && !client->connect(host_.c_str(), port_, 1200)) {
      transportClient_ = nullptr;
      setState(State::Offline, "Backend connection failed");
      return;
    }
    uint8_t randomKey[16];
    for (uint8_t& value : randomKey) value = static_cast<uint8_t>(esp_random());
    const String key = base64::encode(randomKey, sizeof(randomKey));
    client->print("GET /ws/device HTTP/1.1\r\nHost: " + host_ + ":" +
                  String(port_) + "\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: " +
                  key + "\r\nSec-WebSocket-Version: 13\r\nAuthorization: Bearer " +
                  token_ + "\r\n\r\n");
    handshakeBuffer_ = "";
    setState(State::Handshake, "Authenticating backend");
  }
  if (state_ == State::Handshake) {
    handleHandshake();
    return;
  }
  if (state_ == State::Connected) readFrames();
}

void FireBackendClient::handleHandshake() {
  WiFiClient* client = activeClient();
  if (!client) return;
  while (client->available() && handshakeBuffer_.length() < 4096)
    handshakeBuffer_ += static_cast<char>(client->read());
  if (handshakeBuffer_.indexOf("\r\n\r\n") < 0) return;
  if (!handshakeBuffer_.startsWith("HTTP/1.1 101")) {
    disconnect();
    setState(State::Offline, "Backend handshake rejected");
    return;
  }
  setState(State::Connected, usingReverseTransport_
                                ? "Backend connected (Reverse TCP)"
                                : "Backend connected (Direct)");
  const String fields = ",\"target\":\"device\",\"boot_id\":\"" +
                        jsonEscape(bootId_) +
                        "\",\"capabilities\":{\"api_version\":\"fire-lua-0.1\",\"services\":[\"display\",\"buttons\",\"rgb\",\"imu\",\"time\"],\"max_memory\":131072,\"max_runtime_ms\":10000,\"audio_input\":true,\"audio_output\":false,\"firmware_version\":\"" +
                        jsonEscape(firmwareVersion_) + "\"}";
  String payload = "{\"type\":\"device_event\",\"protocol_version\":\"0.2\",\"event_id\":\"" +
                   eventId("evt") + "\",\"device_id\":\"" +
                   jsonEscape(deviceId_) + "\",\"event\":\"session_start\"" +
                   fields + "}";
  sendFrame(0x1, reinterpret_cast<const uint8_t*>(payload.c_str()),
            payload.length());
}

void FireBackendClient::readFrames() {
  WiFiClient* client = activeClient();
  if (!client || !client->connected()) {
    disconnect();
    setState(State::Offline, "Backend disconnected");
    return;
  }
  // Process a bounded amount per OS update.  The previous implementation
  // waited in a tight loop for the rest of a fragmented frame, which could
  // pause drawing and button handling for up to two seconds.
  constexpr size_t kMaxBytesPerService = 2048;
  size_t processed = 0;
  while (client->available() && processed < kMaxBytesPerService) {
    if (receiveStage_ == ReceiveStage::Header) {
      while (receiveHeaderBytes_ < 2 && client->available() &&
             processed < kMaxBytesPerService) {
        const int value = client->read();
        if (value < 0) return;
        if (receiveHeaderBytes_ == 0) {
          receiveOpcode_ = static_cast<uint8_t>(value) & 0x0F;
        } else {
          receiveMasked_ = (static_cast<uint8_t>(value) & 0x80) != 0;
          const uint8_t lengthCode = static_cast<uint8_t>(value) & 0x7F;
          if (lengthCode <= 125) {
            receiveLength_ = lengthCode;
            receiveStage_ = receiveMasked_ ? ReceiveStage::Mask
                                           : ReceiveStage::Payload;
            frameBuffer_ = "";
            frameBuffer_.reserve(static_cast<size_t>(receiveLength_));
          } else {
            receiveExtendedNeeded_ = lengthCode == 126 ? 2 : 8;
            receiveExtendedBytes_ = 0;
            receiveLength_ = 0;
            receiveStage_ = ReceiveStage::ExtendedLength;
          }
        }
        ++receiveHeaderBytes_;
        ++processed;
      }
      if (receiveStage_ == ReceiveStage::Header) return;
    }

    if (receiveStage_ == ReceiveStage::ExtendedLength) {
      while (receiveExtendedBytes_ < receiveExtendedNeeded_ &&
             client->available() && processed < kMaxBytesPerService) {
        const int value = client->read();
        if (value < 0) return;
        receiveExtended_[receiveExtendedBytes_++] = static_cast<uint8_t>(value);
        ++processed;
      }
      if (receiveExtendedBytes_ < receiveExtendedNeeded_) return;
      for (uint8_t index = 0; index < receiveExtendedNeeded_; ++index)
        receiveLength_ = (receiveLength_ << 8) | receiveExtended_[index];
      if (receiveLength_ > kMaxFrameBytes) {
        disconnect();
        resetReceiveFrame();
        setState(State::Offline, "Backend frame too large");
        return;
      }
      receiveStage_ = receiveMasked_ ? ReceiveStage::Mask
                                     : ReceiveStage::Payload;
      frameBuffer_ = "";
      frameBuffer_.reserve(static_cast<size_t>(receiveLength_));
    }

    if (receiveStage_ == ReceiveStage::Mask) {
      while (receiveMaskBytes_ < sizeof(receiveMask_) && client->available() &&
             processed < kMaxBytesPerService) {
        const int value = client->read();
        if (value < 0) return;
        receiveMask_[receiveMaskBytes_++] = static_cast<uint8_t>(value);
        ++processed;
      }
      if (receiveMaskBytes_ < sizeof(receiveMask_)) return;
      receiveStage_ = ReceiveStage::Payload;
    }

    if (receiveStage_ == ReceiveStage::Payload) {
      while (receivePayloadBytes_ < receiveLength_ && client->available() &&
             processed < kMaxBytesPerService) {
        const int value = client->read();
        if (value < 0) return;
        const uint8_t decoded = static_cast<uint8_t>(value) ^
                                (receiveMasked_
                                     ? receiveMask_[receivePayloadBytes_ & 3]
                                     : 0);
        frameBuffer_ += static_cast<char>(decoded);
        ++receivePayloadBytes_;
        ++processed;
      }
      if (receivePayloadBytes_ < receiveLength_) return;
      handleFrame(receiveOpcode_,
                  reinterpret_cast<const uint8_t*>(frameBuffer_.c_str()),
                  frameBuffer_.length());
      resetReceiveFrame();
    }
  }
}

void FireBackendClient::handleFrame(uint8_t opcode, const uint8_t* data,
                                    size_t length) {
  if (opcode == 0x8) {
    disconnect();
    setState(State::Offline, "Backend closed connection");
  } else if (opcode == 0x9) {
    sendFrame(0xA, data, length);
  } else if (opcode == 0x1 && messageCallback_) {
    String message;
    message.reserve(length);
    for (size_t index = 0; index < length; ++index) message += static_cast<char>(data[index]);
    const int sessionKey = message.indexOf("\"session_id\"");
    if (sessionKey >= 0) {
      const int colon = message.indexOf(':', sessionKey);
      const int quote = message.indexOf('"', colon + 1);
      const int end = message.indexOf('"', quote + 1);
      if (quote >= 0 && end > quote) sessionId_ = message.substring(quote + 1, end);
    }
    messageCallback_(callbackContext_, message);
  }
}
