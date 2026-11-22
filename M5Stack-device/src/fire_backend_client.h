#pragma once

#include <Arduino.h>
#include <WiFiClient.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include "fire_reverse_transport.h"

class FireBackendClient {
 public:
  using MessageCallback = void (*)(void*, const String&);
  using StateCallback = void (*)(void*, bool, const String&);

  void configure(const String& host, uint16_t port, const String& token,
                 const String& deviceId, const String& firmwareVersion);
  void setProjectId(const String& projectId) { projectId_ = projectId; }
  void setConversationMode(const String& mode);
  void setAppMode(const String& mode, const String& basePackageId = String());
  void setCallbacks(void* context, MessageCallback message,
                    StateCallback state);
  void setReverseTransport(FireReverseTransport* transport) {
    reverseTransport_ = transport;
  }
  void service(bool wifiConnected);
  void disconnect();
  bool uploadAudio(const String& turnId, const uint8_t* wavData,
                  size_t wavLength);
  bool downloadAudio(const String& url, uint8_t* buffer, size_t capacity,
                     size_t& length);
  bool beginAudioUpload(const String& turnId, const uint8_t* wavData,
                        size_t wavLength);
  bool beginAudioDownload(const String& url, uint8_t* buffer, size_t capacity);
  void cancelAudioTransfer();
  bool audioTransferActive() const { return audioTransferRunning_; }
  bool audioTransferFinished() const { return audioTransferFinished_; }
  bool audioTransferOk() const { return audioTransferOk_; }
  size_t audioTransferLength() const { return audioTransferLength_; }

  bool configured() const { return host_.length() > 0 && token_.length() >= 24; }
  bool connected() const { return state_ == State::Connected && sessionStarted_; }
  bool sessionReady() const { return connected() && sessionId_.length() > 0; }
  bool active() const { return state_ != State::Offline; }
  const String& bootId() const { return bootId_; }
  const String& status() const { return status_; }

  bool listenStart(const String& turnId);
  bool listenStop(const String& turnId);
  bool cancelTurn(const String& turnId = String());
  bool appDeleted(const String& appId);
  bool appInventory(const String& appsJson, bool storageReady, bool complete);
  bool appList(uint32_t offset = 0);
  bool appVersions(const String& projectId, const String& appId = String(),
                  uint32_t offset = 0);
  bool appDownload(const String& projectId, const String& packageId,
                  const String& appId = String());
  bool appBackendDeletePrepare(const String& projectId, const String& appId,
                               const String& scope,
                               const String& packageId = String());
  bool appBackendDeleteConfirm(const String& deleteId);
  bool confirmBuild(const String& proposalId);
  bool confirmRun(const String& packageId);
  bool appStop();
  bool deviceInstallResult(const String& installId, const String& packageId,
                           bool ok, const String& archiveHash,
                           const String& message);
  bool appStarted(const String& runId, const String& packageId,
                  const String& diagnostics = String());
  bool appHealthy(const String& runId, const String& packageId,
                  const String& diagnostics = String());
  bool appFailed(const String& runId, const String& packageId,
                 const String& errorCode, const String& message,
                 const String& diagnostics = String());
  bool appDiagnostic(const String& appId, const String& packageId,
                    const String& errorCode, const String& message,
                    const String& diagnostics = String());
  bool appStopped(const String& runId, const String& packageId,
                  const String& stopId, const String& reason,
                  const String& diagnostics = String());
  bool rollbackResult(const String& rollbackId, const String& packageId,
                      bool ok, const String& message);
  bool firmwareStoreResult(const String& transferId, const String& firmwareId,
                           bool ok, const String& sha256,
                           const String& errorCode, const String& message);
  bool audioPlaybackStarted(const String& audioId, const String& turnId);
  bool audioPlaybackFinished(const String& audioId, const String& turnId);
  bool audioPlaybackFailed(const String& audioId, const String& turnId,
                           const String& errorCode, const String& message,
                           const String& diagnostics = String());
  bool ping();

 private:
  enum class State : uint8_t { Offline, Connecting, Handshake, Connected };
  WiFiClient client_;
  WiFiClient audioClient_;
  FireReverseTransport* reverseTransport_ = nullptr;
  WiFiClient* transportClient_ = nullptr;
  WiFiClient* audioTransportClient_ = nullptr;
  bool usingReverseTransport_ = false;
  State state_ = State::Offline;
  String host_;
  uint16_t port_ = 8765;
  String token_;
  String deviceId_ = "m5stack-fire-01";
  String projectId_;
  String firmwareVersion_ = "fire-os-device";
  String bootId_;
  String sessionId_;
  String resumeSessionId_;
  String conversationMode_;
  String pendingAppMode_;
  String pendingBasePackageId_;
  bool sessionStarted_ = false;
  uint32_t lastServerSeq_ = 0;
  uint32_t handshakeStartedAt_ = 0;
  uint32_t lastReceiveAt_ = 0;
  uint32_t lastPingAt_ = 0;
  uint32_t lastPongAt_ = 0;
  enum class AudioTransfer : uint8_t { None, Upload, Download };
  AudioTransfer audioTransfer_ = AudioTransfer::None;
  TaskHandle_t audioTask_ = nullptr;
  volatile bool audioTransferRunning_ = false;
  volatile bool audioTransferFinished_ = false;
  volatile bool audioTransferOk_ = false;
  volatile bool audioTransferCancel_ = false;
  volatile size_t audioTransferLength_ = 0;
  String audioTransferTurnId_;
  String audioTransferUrl_;
  const uint8_t* audioTransferUploadData_ = nullptr;
  uint8_t* audioTransferDownloadBuffer_ = nullptr;
  size_t audioTransferBytes_ = 0;
  static void audioTaskEntry(void* context);
  void runAudioTransfer();
  String handshakeBuffer_;
  String frameBuffer_;
  enum class ReceiveStage : uint8_t { Header, ExtendedLength, Mask, Payload };
  ReceiveStage receiveStage_ = ReceiveStage::Header;
  uint8_t receiveHeaderBytes_ = 0;
  uint8_t receiveOpcode_ = 0;
  bool receiveFin_ = false;
  bool receiveMasked_ = false;
  uint8_t receiveExtended_[8] = {};
  uint8_t receiveExtendedNeeded_ = 0;
  uint8_t receiveExtendedBytes_ = 0;
  uint8_t receiveMask_[4] = {};
  uint8_t receiveMaskBytes_ = 0;
  uint64_t receiveLength_ = 0;
  size_t receivePayloadBytes_ = 0;
  uint8_t fragmentOpcode_ = 0;
  String fragmentBuffer_;
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
  void resetReceiveFrame();
  void handleHandshake();
  void readFrames();
  void handleFrame(uint8_t opcode, const uint8_t* data, size_t length);
  WiFiClient* activeClient() {
    return transportClient_ ? transportClient_ : &client_;
  }
};
