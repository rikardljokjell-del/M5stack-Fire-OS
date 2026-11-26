#pragma once

#include <Arduino.h>
#include <WiFiClient.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include "fire_reverse_transport.h"
#include "fire_async_client.h"
#include "fire_ws_handshake.h"
#include "fire_session_selection.h"

class FireBackendClient {
 public:
  using MessageCallback = void (*)(void*, const String&);
  using StateCallback = void (*)(void*, bool, const String&);

  void configure(const String& host, uint16_t port, const String& token,
                 const String& deviceId, const String& firmwareVersion);
  void setProjectId(const String& projectId) { projectId_ = projectId; }
  bool beginSelection() { selectionReply_=0;return selection_.begin(); }
  bool selectionPending() const { return selection_.pending(); }
  bool selectionUnclear() const { return selection_.unclear(); }
  bool selectionAppAck() const { return selectionReply_&1; }
  bool selectionModeAck() const { return selectionReply_&2; }
  bool selectionFailed() const { return selectionReply_&4; }
  const String& confirmedProject() const { return confirmedProject_; }
  const String& confirmedBase() const { return confirmedBase_; }
  const String& confirmedMode() const { return confirmedMode_; }
  const String& confirmedAppMode() const { return confirmedAppMode_; }
  void setConversationMode(const String& mode);
  void setRuntimeAiMode(const String& mode,bool publish=true);
  void setAppMode(const String& mode, const String& basePackageId = String());
  void setDevelopmentContext(const String& context) {
    developmentContext_=context;selection_.clear();projectId_=String();
  }
  void setCallbacks(void* context, MessageCallback message,
                    StateCallback state);
  void setReverseTransport(FireReverseTransport* transport) {
    reverseTransport_ = transport;
  }
  void service(bool wifiConnected);
  void disconnect();
  // A deliberate policy/configuration retry, never an automatic app action.
  void retrySession() { sessionAdmission_.retry();reconnectAt_=0; }
  bool uploadAudio(const String& turnId, const uint8_t* wavData,
                  size_t wavLength);
  bool downloadAudio(const String& url, uint8_t* buffer, size_t capacity,
                     size_t& length);
  bool beginAudioUpload(const String& turnId, const uint8_t* wavData,
                        size_t wavLength);
  bool beginAudioDownload(const String& url, uint8_t* buffer, size_t capacity);
  bool beginDataUpload(const String& request,const String& dataset,const String& part,
                       uint32_t offset,const String& chunkHash,const uint8_t* bytes,size_t length);
  const String& dataUploadNext() const {return dataUploadNext_;}
  void cancelAudioTransfer();
  bool audioTransferActive() const { return audioTransferRunning_; }
  bool audioTransferFinished() const { return (dataTransferActive_ && dataChunkDone_) || (!audioTransferRunning_ && audioTransferFinished_); }
  bool dataTransferActive() const {return dataTransferActive_;}
  bool audioTransferOk() const { return audioTransferOk_; }
  size_t audioTransferLength() const { return audioTransferLength_; }

  bool sessionRejected() const { return !sessionAdmission_.allowed(); }
  bool configured() const { return host_.length() > 0 && token_.length() >= 24; }
  bool connected() const { return state_ == State::Connected && sessionStarted_; }
  bool sessionReady() const { return connected() && sessionId_.length() > 0; }
  bool active() const { return state_ != State::Offline; }
  bool pendingWrites() const { return !usingReverseTransport_ && client_.pendingWrites(); }
  bool networkIdle() const {
    return !client_.running() && !audioClient_.running() && !audioTransferRunning_;
  }
  uint32_t connectionEpoch() const {return connectionEpoch_;}
  const String& bootId() const { return bootId_; }
  const String& sessionId() const {return sessionId_;}
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
                  const String& appId = String(),const String& stableEventId=String());
  bool appBackendDeletePrepare(const String& projectId, const String& appId,
                               const String& scope,
                               const String& packageId = String());
  bool appBackendDeleteConfirm(const String& deleteId);
  bool confirmBuild(const String& proposalId,
                    const String& repairId = String());
  bool confirmRun(const String& packageId);
  bool evolutionStatus(const String& request,const String& app,const String& view,uint32_t offset);
  bool evolutionPrepare(const String& request,const String& app,const String& operation,uint32_t revision,
                        const String& json,const String& packageId,const String& source);
  bool evolutionConfirm(const String& request,const String& app,const String& proposal,uint32_t revision);
  bool evolutionControl(const String& request,const String& app,const String& action,uint32_t revision,
                        const String& job,const String& mandate);
  bool evolutionTelemetry(const String& request,const String& app,const String& packageId,
                          const String& source,const String& json);
  bool backendSettingsStatus(const String& request,const String& view,const String& role,uint32_t offset);
  bool backendSettingsPrepare(const String& request,uint32_t revision,const String& patch);
  bool backendSettingsConfirm(const String& request,const String& proposal,uint32_t revision);
  bool runtimeAiRequest(const String& requestId,const String& appId,const String& packageId,
                        const String& sourceHash,const String& runId,const String& instructions,
                        const String& data,const String& schema,uint32_t timeoutMs);
  bool runtimeAiCancel(const String& requestId,const String& appId,const String& packageId,
                       const String& sourceHash,const String& runId);
  bool dataRequest(const String& requestId,const String& appId,const String& packageId,
                   const String& sourceHash,const String& runId,const String& operation,
                   const String& datasetId,const String& options,const String& datasets);
  bool dataCancel(const String& requestId,const String& appId,const String& packageId,
                  const String& sourceHash,const String& runId);
  bool appDevelop(const String& requestId,const String& appId,const String& packageId,
                  const String& sourceHash,const String& runId,const String& mode,
                  const String& instruction,const String& ids,const String& datasets);
  bool confirmObservation(const String& context,const String& action,const String& eventId);
  bool appRepairPrepare(const String& appId, const String& packageId,
                        const String& appVersion, const String& sha256,
                        const String& errorCode, const String& message,
                        const String& diagnostics, const String& runId = String());
  bool appRepairStatus(const String& repairId, const String& appId = String());
  bool appRepairCancel(const String& repairId);
  bool buildBackground(const String& buildId);
  bool buildJobs(uint32_t offset = 0);
  bool jobControl(const String& action,const String& build,const String& repair);
  bool buildResume(const String& buildId);
  bool buildCancel(const String& buildId);
  bool buildNoticeAck(const String& buildId, const String& action,
                      const String& stableEventId = String());
  bool appStop();
  bool deviceInstallResult(const String& installId, const String& packageId,
                           bool ok, const String& archiveHash,
                           const String& message,const String& stableEventId=String());
  bool appStarted(const String& runId, const String& packageId,
                  const String& sourceHash, const String& diagnostics = String());
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
  FireAsyncClient client_;
  FireAsyncClient audioClient_;
  bool secureEndpoint_ = true;
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
  String confirmedProject_,confirmedBase_,confirmedMode_,confirmedAppMode_;
  fire_session::Selection<String> selection_;
  uint8_t selectionReply_=0;
  String runtimeAiMode_ = "auto";
  String developmentContext_;
  bool sessionStarted_ = false;
  FireWsSessionAdmission sessionAdmission_;
  uint32_t lastServerSeq_ = 0,connectionEpoch_=0;
  uint32_t handshakeStartedAt_ = 0;
  uint8_t bootstrapStages_=0; // at most eight fixed numeric lines per attempt
  uint32_t lastReceiveAt_ = 0;
  uint32_t lastPingAt_ = 0;
  uint32_t lastPongAt_ = 0;
  enum class AudioTransfer : uint8_t { None, Upload, Download, DataUpload };
  AudioTransfer audioTransfer_ = AudioTransfer::None;
  TaskHandle_t audioTask_ = nullptr;
  std::atomic<bool> audioTransferRunning_{false};
  std::atomic<bool> audioTransferFinished_{false};
  std::atomic<bool> audioTransferOk_{false};
  std::atomic<bool> audioTransferCancel_{false};
  std::atomic<size_t> audioTransferLength_{0};
  String audioTransferTurnId_;
  String audioTransferUrl_;
  const uint8_t* audioTransferUploadData_ = nullptr;
  uint8_t* audioTransferDownloadBuffer_ = nullptr;
  size_t audioTransferBytes_ = 0;
  String dataUploadDataset_,dataUploadPart_,dataUploadHash_,dataUploadNext_;
  uint32_t dataUploadOffset_=0,dataUploadResponseOffset_=0;
  std::atomic<bool> dataTransferActive_{false},dataChunkReady_{false},dataChunkDone_{false};
  // Immutable for the lifetime of one audio task, including config changes.
  String audioHost_, audioToken_, audioSession_;
  uint16_t audioPort_ = 0;
  bool audioSecure_ = true;
  FireReverseTransport* audioReverse_ = nullptr;
  uint32_t audioReverseGeneration_ = 0;
  void snapshotAudioEndpoint();
  static void audioTaskEntry(void* context);
  void runAudioTransfer();
  String handshakeBuffer_;
  String expectedAccept_;
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
  bool sendEvent(const String& event, const String& fields = String(),
                 const String& stableEventId = String());
  bool sendFrame(uint8_t opcode, const uint8_t* data, size_t length);
  void setState(State state, const String& status);
  void resetReceiveFrame();
  void handleHandshake();
  void serviceSelection();
  void observeSession(const String& type,const String& message);
  void bootstrapDiagnostic(uint8_t stage,uint32_t first=0,uint32_t second=0);
  void readFrames();
  void handleFrame(uint8_t opcode, const uint8_t* data, size_t length);
  WiFiClient* activeClient() {
    return transportClient_ ? transportClient_ : &client_;
  }
};
