#pragma once

#include <Arduino.h>
#include <WiFiClient.h>

class FireBackendClient {
 public:
  using MessageCallback = void (*)(void*, const String&);
  using StateCallback = void (*)(void*, bool, const String&);

  void configure(const String& host, uint16_t port, const String& token,
                 const String& deviceId, const String& firmwareVersion);
  void setCallbacks(void* context, MessageCallback message,
                    StateCallback state);
  void service(bool wifiConnected);
  void disconnect();
  bool uploadAudio(const String& turnId, const uint8_t* wavData,
                  size_t wavLength);

  bool configured() const { return host_.length() > 0 && token_.length() >= 24; }
  bool connected() const { return state_ == State::Connected; }
  const String& status() const { return status_; }

  bool listenStart(const String& turnId);
  bool listenStop(const String& turnId);
  bool cancelTurn();
  bool confirmBuild(const String& proposalId);
  bool confirmRun(const String& packageId);
  bool appStop();
  bool deviceInstallResult(const String& installId, const String& packageId,
                           bool ok, const String& archiveHash,
                           const String& message);
  bool appStarted(const String& runId, const String& packageId);
  bool appHealthy(const String& runId, const String& packageId);
  bool appFailed(const String& runId, const String& packageId,
                 const String& errorCode, const String& message);
  bool ping();

 private:
  enum class State : uint8_t { Offline, Connecting, Handshake, Connected };
  WiFiClient client_;
  WiFiClient audioClient_;
  State state_ = State::Offline;
  String host_;
  uint16_t port_ = 8765;
  String token_;
  String deviceId_ = "m5stack-fire-01";
  String firmwareVersion_ = "fire-os-device";
  String bootId_;
  String sessionId_;
  String handshakeBuffer_;
  String frameBuffer_;
  String status_ = "Backend not configured";
  uint32_t reconnectAt_ = 0;
  uint32_t eventCounter_ = 0;
  void* callbackContext_ = nullptr;
  MessageCallback messageCallback_ = nullptr;
  StateCallback stateCallback_ = nullptr;

  String eventId(const char* prefix);
  bool sendEvent(const String& event, const String& fields = String());
  bool sendFrame(uint8_t opcode, const uint8_t* data, size_t length);
  void setState(State state, const String& status);
  void handleHandshake();
  void readFrames();
  void handleFrame(uint8_t opcode, const uint8_t* data, size_t length);
};
