#include "fire_backend_client.h"

#include <base64.h>
#include <esp_system.h>
#include "fire_lua_runtime.h"
#include "fire_json_guard.h"
#include "fire_ws_handshake.h"
#include <mbedtls/sha1.h>

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

String jsonStringField(const String& json, const char* key) {
  const String marker = String("\"") + key + "\"";
  const int keyAt = json.indexOf(marker);
  if (keyAt < 0) return "";
  const int colon = json.indexOf(':', keyAt + marker.length());
  const int quote = json.indexOf('"', colon + 1);
  if (colon < 0 || quote < 0) return "";
  String value;
  bool escaped = false;
  for (int index = quote + 1; index < json.length(); ++index) {
    const char c = json[index];
    if (escaped) {
      value += c == 'n' ? '\n' : c == 'r' ? '\r' : c;
      escaped = false;
    } else if (c == '\\') {
      escaped = true;
    } else if (c == '"') {
      break;
    } else {
      value += c;
    }
  }
  return value;
}

uint32_t jsonUintField(const String& json, const char* key) {
  const String marker = String("\"") + key + "\"";
  const int keyAt = json.indexOf(marker);
  if (keyAt < 0) return 0;
  const int colon = json.indexOf(':', keyAt + marker.length());
  if (colon < 0) return 0;
  int start = colon + 1;
  while (start < json.length() && (json[start] == ' ' || json[start] == '\t')) ++start;
  return static_cast<uint32_t>(json.substring(start).toInt());
}
}  // namespace

void FireBackendClient::configure(const String& host, uint16_t port,
                                  const String& token, const String& deviceId,
                                  const String& firmwareVersion) {
  disconnect();
  secureEndpoint_ = fireNetworkTls(host, port);
  host_ = fireNetworkEndpointValid(host) ? fireNetworkHost(host) : String();
  client_.secure(secureEndpoint_);
  audioClient_.secure(secureEndpoint_);
  port_ = port == 0 ? (secureEndpoint_ ? 443 : 8765) : port;
  token_ = token;
  if (deviceId.length() > 0) deviceId_ = deviceId;
  if (firmwareVersion.length() > 0) firmwareVersion_ = firmwareVersion;
  resumeSessionId_ = "";
  conversationMode_ = "";
  pendingAppMode_ = "";
  pendingBasePackageId_ = "";
  lastServerSeq_ = 0;
  bootId_ = "boot-" + String(static_cast<uint32_t>(esp_random()), HEX) +
            String(millis(), HEX);
  status_ = configured() ? "Backend disconnected" : "Backend not configured";
}

void FireBackendClient::setConversationMode(const String& mode) {
  if (mode != "chat" && mode != "develop") return;
  conversationMode_ = mode;
  if (mode == "chat") {
    pendingAppMode_ = "";
    pendingBasePackageId_ = "";
  }
  if (sessionReady())
    sendEvent("mode_select", ",\"conversation_mode\":\"" + jsonEscape(mode) + "\"");
}

void FireBackendClient::setAppMode(const String& mode,
                                   const String& basePackageId) {
  if (mode != "new" && mode != "update") return;
  pendingAppMode_ = mode;
  pendingBasePackageId_ = basePackageId;
  if (sessionReady()) {
    String fields = ",\"app_mode\":\"" + jsonEscape(mode) + "\"";
    if (mode == "update" && projectId_.length() > 0)
      fields += ",\"project_id\":\"" + jsonEscape(projectId_) + "\"";
    if (mode == "update" && basePackageId.length() > 0)
      fields += ",\"base_package_id\":\"" + jsonEscape(basePackageId) + "\"";
    if (sendEvent("app_select", fields)) {
      pendingAppMode_ = "";
      pendingBasePackageId_ = "";
    }
  }
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
  cancelAudioTransfer();
  // Cancellation includes DNS/TCP/TLS that has not connected yet.
  client_.stop();
  audioClient_.stop();
  // Audio worker owns its connection until cancellation completes.
  if (transportClient_ && reverseTransport_) {
    reverseTransport_->release(transportClient_);
    transportClient_ = nullptr;
  }
  usingReverseTransport_ = false;
  if (!audioTransferRunning_ && audioTransportClient_ && reverseTransport_) {
    reverseTransport_->release(audioTransportClient_);
    audioTransportClient_ = nullptr;
  }
  handshakeBuffer_ = "";
  frameBuffer_ = "";
  fragmentOpcode_ = 0;
  fragmentBuffer_ = "";
  resetReceiveFrame();
  if (sessionId_.length() > 0) resumeSessionId_ = sessionId_;
  sessionId_ = "";
  sessionStarted_ = false;
  setState(configured() ? State::Offline : State::Offline,
           configured() ? "Backend disconnected" : "Backend not configured");
}

void FireBackendClient::resetReceiveFrame() {
  receiveStage_ = ReceiveStage::Header;
  receiveHeaderBytes_ = 0;
  receiveOpcode_ = 0;
  receiveFin_ = false;
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
  if (audioTransferCancel_ || audioSession_.length() == 0 || !wavData || wavLength == 0 ||
      wavLength > 524288) {
    return false;
  }
  WiFiClient* audio = nullptr;
  if (!audioSecure_ && audioReverse_) audioTransportClient_ = audioReverse_->acquire(audioReverseGeneration_);
  if (audioTransportClient_) {
    audio = audioTransportClient_;
  } else {
    audioClient_.stop();
    audioClient_.secure(audioSecure_);
    if (!audioClient_.connectBlocking(audioHost_.c_str(), audioPort_, 15000, &audioTransferCancel_)) return false;
    audio = &audioClient_;
  }
  auto closeAudio = [&]() {
    if (audioTransportClient_ && audioReverse_) {
      audioReverse_->release(audioTransportClient_);
      audioTransportClient_ = nullptr;
    } else {
      audioClient_.stop();
    }
  };
  const String path = "/sessions/" + audioSession_ + "/audio/" + turnId;
  const String request = "POST " + path + " HTTP/1.1\r\nHost: " + audioHost_ + ":" +
               String(audioPort_) + "\r\nAuthorization: Bearer " + audioToken_ +
               "\r\nContent-Type: audio/wav\r\nContent-Length: " +
               String(wavLength) + "\r\nConnection: close\r\n\r\n";
  if (audioTransferCancel_ || audio->print(request) != request.length()) { closeAudio(); return false; }
  size_t offset = 0;
  while (offset < wavLength) {
    if (audioTransferCancel_ || (audioTransportClient_ && audioReverse_ && audioReverse_->cancelled(audioTransportClient_))) {
      closeAudio();
      return false;
    }
    const size_t amount = min<size_t>(2048, wavLength - offset);
    const uint32_t writeStarted = millis();
    size_t written = 0;
    while (written < amount && !audioTransferCancel_ && audio->connected() &&
           millis() - writeStarted < 5000) {
      const size_t count = audio->write(wavData + offset + written, amount - written);
      written += count;
      if (!count) delay(2);
    }
    if (written != amount) {
      closeAudio();
      return false;
    }
    offset += amount;
  }
  const uint32_t deadline = millis() + 5000;
  String response;
  while (millis() < deadline && audio->connected() &&
         response.indexOf("\r\n\r\n") < 0) {
    if (audioTransferCancel_ || (audioTransportClient_ && audioReverse_ && audioReverse_->cancelled(audioTransportClient_))) {
      closeAudio();
      return false;
    }
    while (audio->available() && response.length() < 512)
      response += static_cast<char>(audio->read());
    if (response.indexOf("\r\n\r\n") < 0) delay(1);
  }
  closeAudio();
  return response.startsWith("HTTP/1.1 2") || response.startsWith("HTTP/1.0 2");
}

bool FireBackendClient::downloadAudio(const String& url, uint8_t* buffer,
                                      size_t capacity, size_t& length) {
  length = 0;
  if (audioTransferCancel_ || !audioSession_.length() || !fireRelativePath(url) || !buffer || capacity == 0)
    return false;
  WiFiClient* audio = nullptr;
  if (!audioSecure_ && audioReverse_) audioTransportClient_ = audioReverse_->acquire(audioReverseGeneration_);
  if (audioTransportClient_) {
    audio = audioTransportClient_;
  } else {
    audioClient_.stop();
    audioClient_.secure(audioSecure_);
    if (!audioClient_.connectBlocking(audioHost_.c_str(), audioPort_, 15000, &audioTransferCancel_)) return false;
    audio = &audioClient_;
  }
  auto closeAudio = [&]() {
    if (audioTransportClient_ && audioReverse_) {
      audioReverse_->release(audioTransportClient_);
      audioTransportClient_ = nullptr;
    } else {
      audioClient_.stop();
    }
  };

  const String request = "GET " + url + " HTTP/1.1\r\nHost: " + audioHost_ + ":" +
               String(audioPort_) + "\r\nAuthorization: Bearer " + audioToken_ +
               "\r\nConnection: close\r\n\r\n";
  if (audioTransferCancel_ || audio->print(request) != request.length()) { closeAudio(); return false; }
  String headers;
  const uint32_t headerDeadline = millis() + 5000;
  while (millis() < headerDeadline && audio->connected() &&
         headers.length() < 8192 && headers.indexOf("\r\n\r\n") < 0) {
    if (audioTransferCancel_ || (audioTransportClient_ && audioReverse_ && audioReverse_->cancelled(audioTransportClient_))) {
      closeAudio();
      return false;
    }
    while (audio->available() && headers.length() < 8192) {
      headers += static_cast<char>(audio->read());
      if (headers.endsWith("\r\n\r\n")) break;
    }
    if (headers.indexOf("\r\n\r\n") < 0) delay(1);
  }
  const int headerEnd = headers.indexOf("\r\n\r\n");
  if (headerEnd < 0 ||
      (!headers.startsWith("HTTP/1.1 200") &&
       !headers.startsWith("HTTP/1.0 200"))) {
    closeAudio();
    return false;
  }
  String lowerHeaders = headers.substring(0, headerEnd);
  lowerHeaders.toLowerCase();
  const int lengthAt = lowerHeaders.indexOf("content-length:");
  if (lengthAt < 0) {
    closeAudio();
    return false;
  }
  const size_t contentLength =
      headers.substring(lengthAt + 15, headerEnd).toInt();
  if (contentLength == 0 || contentLength > capacity ||
      (contentLength & 1U) != 0) {
    closeAudio();
    return false;
  }
  const String body = headers.substring(headerEnd + 4);
  const size_t initial = min(contentLength, body.length());
  memcpy(buffer, body.c_str(), initial);
  length = initial;
  const uint32_t bodyDeadline = millis() + 20000;
  while (length < contentLength && millis() < bodyDeadline) {
    if (audioTransferCancel_ || (audioTransportClient_ && audioReverse_ && audioReverse_->cancelled(audioTransportClient_))) {
      closeAudio();
      return false;
    }
    if (!audio->available()) {
      delay(1);
      continue;
    }
    const size_t amount = audio->read(buffer + length, contentLength - length);
    if (amount == 0) break;
    length += amount;
  }
  closeAudio();
  return length == contentLength;
}

bool FireBackendClient::beginAudioUpload(const String& turnId,
                                         const uint8_t* wavData,
                                         size_t wavLength) {
  if (audioTransferRunning_ || !wavData || wavLength == 0 ||
      wavLength > 524288 || !sessionReady())
    return false;
  snapshotAudioEndpoint();
  audioTransfer_ = AudioTransfer::Upload;
  audioTransferTurnId_ = turnId;
  audioTransferUrl_ = "";
  audioTransferUploadData_ = wavData;
  audioTransferDownloadBuffer_ = nullptr;
  audioTransferBytes_ = wavLength;
  audioTransferLength_ = 0;
  audioTransferCancel_ = false;
  audioTransferFinished_ = false;
  audioTransferOk_ = false;
  audioTransferRunning_ = true;
  if (xTaskCreatePinnedToCore(audioTaskEntry, "fire-audio-http", 6144, this, 2,
                              &audioTask_, 0) != pdPASS) {
    audioTransferRunning_ = false;
    audioTransfer_ = AudioTransfer::None;
    return false;
  }
  return true;
}

bool FireBackendClient::beginAudioDownload(const String& url, uint8_t* buffer,
                                           size_t capacity) {
  if (audioTransferRunning_ || !buffer || capacity == 0 || !sessionReady() ||
      url.length() == 0)
    return false;
  snapshotAudioEndpoint();
  audioTransfer_ = AudioTransfer::Download;
  audioTransferTurnId_ = "";
  audioTransferUrl_ = url;
  audioTransferUploadData_ = nullptr;
  audioTransferDownloadBuffer_ = buffer;
  audioTransferBytes_ = capacity;
  audioTransferLength_ = 0;
  audioTransferCancel_ = false;
  audioTransferFinished_ = false;
  audioTransferOk_ = false;
  audioTransferRunning_ = true;
  if (xTaskCreatePinnedToCore(audioTaskEntry, "fire-audio-http", 6144, this, 2,
                              &audioTask_, 0) != pdPASS) {
    audioTransferRunning_ = false;
    audioTransfer_ = AudioTransfer::None;
    return false;
  }
  return true;
}

void FireBackendClient::cancelAudioTransfer() {
  if (!audioTransferRunning_) return;
  audioTransferCancel_ = true;
}
void FireBackendClient::snapshotAudioEndpoint() {
  audioHost_ = host_; audioPort_ = port_; audioToken_ = token_;
  audioSession_ = sessionId_; audioSecure_ = secureEndpoint_; audioReverse_ = reverseTransport_;
  audioReverseGeneration_ = audioReverse_ ? audioReverse_->generation() : 0;
}

void FireBackendClient::audioTaskEntry(void* context) {
  auto* client = static_cast<FireBackendClient*>(context);
  if (client) client->runAudioTransfer();
  vTaskDelete(nullptr);
}

void FireBackendClient::runAudioTransfer() {
  bool ok = false;
  size_t length = 0;
  if (audioTransfer_ == AudioTransfer::Upload) {
    ok = uploadAudio(audioTransferTurnId_, audioTransferUploadData_,
                     audioTransferBytes_);
  } else if (audioTransfer_ == AudioTransfer::Download) {
    ok = downloadAudio(audioTransferUrl_, audioTransferDownloadBuffer_,
                       audioTransferBytes_, length);
  }
  audioTransferLength_ = length;
  audioTransferOk_ = ok && !audioTransferCancel_;
  audioTask_ = nullptr;
  audioTransfer_ = AudioTransfer::None;
  audioTransferFinished_ = true;
  // Publish idle only after every old-task write. A new task may start at once.
  audioTransferRunning_.store(false, std::memory_order_release);
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
  if (length > 8192) return false;
  // Reserve the entire frame before queueing even the header. There is only
  // one producer for this stream, so the worker can only increase free space.
  if (!usingReverseTransport_ && !client_.canWrite(headerLength + length))
    return false;
  if (client->write(header, headerLength) != headerLength) { disconnect(); return false; }
  uint8_t chunk[256];
  size_t offset = 0;
  while (offset < length) {
    const size_t amount = min(sizeof(chunk), length - offset);
    for (size_t index = 0; index < amount; ++index)
      chunk[index] = data[offset + index] ^ mask[(offset + index) & 3];
    if (client->write(chunk, amount) != amount) { disconnect(); return false; }
    offset += amount;
  }
  return true;
}

bool FireBackendClient::sendEvent(const String& event, const String& fields,
                                  const String& stableEventId) {
  // Protocol 0.2 requires session_id on every event after session_start.
  // Do not emit a malformed listen/build event while the server's
  // session_started message is still in flight.
  if (!sessionReady()) return false;
  String payload = "{\"type\":\"device_event\",\"protocol_version\":\"0.2\",\"event_id\":\"" +
                   (stableEventId.length() ? jsonEscape(stableEventId) : eventId("evt")) + "\",\"device_id\":\"" +
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

bool FireBackendClient::cancelTurn(const String& turnId) {
  return sendEvent("cancel_turn", turnId.length() > 0
                                    ? ",\"turn_id\":\"" + jsonEscape(turnId) + "\""
                                    : String());
}

bool FireBackendClient::appDeleted(const String& appId) {
  return sendEvent("app_deleted", ",\"app_id\":\"" + jsonEscape(appId) + "\"");
}

bool FireBackendClient::appInventory(const String& appsJson, bool storageReady,
                                     bool complete) {
  return sendEvent("app_inventory", ",\"storage_ready\":" +
                                  String(storageReady ? "true" : "false") +
                                  ",\"complete\":" +
                                  String(complete ? "true" : "false") +
                                  ",\"apps\":" + appsJson);
}

bool FireBackendClient::appList(uint32_t offset) {
  return sendEvent("app_list", ",\"offset\":" + String(offset));
}

bool FireBackendClient::appVersions(const String& projectId,
                                    const String& appId, uint32_t offset) {
  String fields = ",\"offset\":" + String(offset);
  if (projectId.length() > 0)
    fields += ",\"project_id\":\"" + jsonEscape(projectId) + "\"";
  else if (appId.length() > 0)
    fields += ",\"app_id\":\"" + jsonEscape(appId) + "\"";
  else
    return false;
  return sendEvent("app_versions", fields);
}

bool FireBackendClient::appDownload(const String& projectId,
                                    const String& packageId,
                                    const String& appId) {
  if (packageId.length() == 0) return false;
  String fields = ",\"package_id\":\"" + jsonEscape(packageId) + "\"";
  if (projectId.length() > 0)
    fields += ",\"project_id\":\"" + jsonEscape(projectId) + "\"";
  if (appId.length() > 0)
    fields += ",\"app_id\":\"" + jsonEscape(appId) + "\"";
  return sendEvent("app_download", fields);
}

bool FireBackendClient::appBackendDeletePrepare(
    const String& projectId, const String& appId, const String& scope,
    const String& packageId) {
  if ((projectId.length() == 0 && appId.length() == 0) ||
      (scope != "all" && scope != "version") ||
      (scope == "version" && packageId.length() == 0))
    return false;
  String fields = ",\"delete_scope\":\"" + jsonEscape(scope) + "\"";
  if (projectId.length() > 0)
    fields += ",\"project_id\":\"" + jsonEscape(projectId) + "\"";
  if (appId.length() > 0)
    fields += ",\"app_id\":\"" + jsonEscape(appId) + "\"";
  if (packageId.length() > 0)
    fields += ",\"package_id\":\"" + jsonEscape(packageId) + "\"";
  return sendEvent("app_backend_delete_prepare", fields);
}

bool FireBackendClient::appBackendDeleteConfirm(const String& deleteId) {
  if (deleteId.length() == 0) return false;
  return sendEvent("app_backend_delete_confirm", ",\"delete_id\":\"" +
                                                   jsonEscape(deleteId) + "\"");
}

bool FireBackendClient::confirmBuild(const String& proposalId,
                                     const String& repairId) {
  String fields = ",\"proposal_id\":\"" + jsonEscape(proposalId) + "\"";
  if (repairId.length() > 0)
    fields += ",\"repair_id\":\"" + jsonEscape(repairId) + "\"";
  return sendEvent("build_confirm", fields);
}

bool FireBackendClient::confirmRun(const String& packageId) {
  return sendEvent("run_confirm", ",\"package_id\":\"" +
                   jsonEscape(packageId) + "\"");
}

bool FireBackendClient::appRepairPrepare(
    const String& appId, const String& packageId, const String& appVersion,
    const String& sha256, const String& errorCode, const String& message,
    const String& diagnostics, const String& runId) {
  if (appId.length() == 0) return false;
  String fields = ",\"app_id\":\"" + jsonEscape(appId) + "\"";
  if (packageId.length() > 0)
    fields += ",\"package_id\":\"" + jsonEscape(packageId) + "\"";
  if (appVersion.length() > 0)
    fields += ",\"app_version\":\"" + jsonEscape(appVersion) + "\"";
  if (sha256.length() == 64)
    fields += ",\"sha256\":\"" + jsonEscape(sha256) + "\"";
  if (errorCode.length() > 0)
    fields += ",\"error_code\":\"" + jsonEscape(errorCode) + "\"";
  if (message.length() > 0)
    fields += ",\"message\":\"" + jsonEscape(message.substring(0, 240)) +
              "\"";
  if (diagnostics.length() > 0) fields += ",\"diagnostics\":" + diagnostics;
  if (runId.length() > 0)
    fields += ",\"run_id\":\"" + jsonEscape(runId) + "\"";
  return sendEvent("app_repair_prepare", fields);
}

bool FireBackendClient::appRepairStatus(const String& repairId,
                                        const String& appId) {
  if (repairId.length() == 0 && appId.length() == 0) return false;
  String fields;
  if (repairId.length() > 0)
    fields += ",\"repair_id\":\"" + jsonEscape(repairId) + "\"";
  if (appId.length() > 0) {
    fields += ",\"app_id\":\"" + jsonEscape(appId) + "\"";
  }
  return sendEvent("app_repair_status", fields);
}

bool FireBackendClient::appRepairCancel(const String& repairId) {
  if (repairId.length() == 0) return false;
  return sendEvent("app_repair_cancel", ",\"repair_id\":\"" +
                   jsonEscape(repairId) + "\"");
}

bool FireBackendClient::buildBackground(const String& buildId) {
  if (buildId.length() == 0) return false;
  return sendEvent("build_background", ",\"build_id\":\"" +
                   jsonEscape(buildId) + "\"");
}

bool FireBackendClient::buildJobs(uint32_t offset) {
  return sendEvent("build_jobs", ",\"offset\":" + String(offset));
}

bool FireBackendClient::buildResume(const String& buildId) {
  if (buildId.length() == 0) return false;
  return sendEvent("build_resume", ",\"build_id\":\"" +
                   jsonEscape(buildId) + "\"");
}

bool FireBackendClient::buildCancel(const String& buildId) {
  if (buildId.length() == 0) return false;
  return sendEvent("build_cancel", ",\"build_id\":\"" +
                   jsonEscape(buildId) + "\"");
}

bool FireBackendClient::buildNoticeAck(const String& buildId,
                                       const String& action,
                                       const String& stableEventId) {
  if (buildId.length() == 0 || (action != "open" && action != "dismiss"))
    return false;
  return sendEvent("build_notice_ack", ",\"build_id\":\"" +
                   jsonEscape(buildId) + "\",\"notification_action\":\"" +
                   jsonEscape(action) + "\"", stableEventId);
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

bool FireBackendClient::appStarted(const String& runId, const String& packageId,
                                   const String& diagnostics) {
  String fields = ",\"run_id\":\"" + jsonEscape(runId) +
                  "\",\"package_id\":\"" + jsonEscape(packageId) + "\"";
  if (diagnostics.length() > 0) fields += ",\"diagnostics\":" + diagnostics;
  return sendEvent("app_started", fields);
}

bool FireBackendClient::appHealthy(const String& runId, const String& packageId,
                                   const String& diagnostics) {
  String fields = ",\"run_id\":\"" + jsonEscape(runId) +
                  "\",\"package_id\":\"" + jsonEscape(packageId) + "\"";
  if (diagnostics.length() > 0) fields += ",\"diagnostics\":" + diagnostics;
  return sendEvent("app_healthy", fields);
}

bool FireBackendClient::appFailed(const String& runId, const String& packageId,
                                  const String& errorCode,
                                  const String& message,
                                  const String& diagnostics) {
  String fields = ",\"run_id\":\"" + jsonEscape(runId) +
                  "\",\"package_id\":\"" + jsonEscape(packageId) +
                  "\",\"error_code\":\"" + jsonEscape(errorCode) +
                  "\",\"message\":\"" + jsonEscape(message.substring(0, 240)) +
                  "\"";
  if (diagnostics.length() > 0) fields += ",\"diagnostics\":" + diagnostics;
  return sendEvent("app_failed", fields);
}

bool FireBackendClient::appDiagnostic(const String& appId,
                                      const String& packageId,
                                      const String& errorCode,
                                      const String& message,
                                      const String& diagnostics) {
  String fields = ",\"app_id\":\"" + jsonEscape(appId) +
                  "\",\"package_id\":\"" + jsonEscape(packageId) +
                  "\",\"error_code\":\"" + jsonEscape(errorCode) +
                  "\",\"message\":\"" + jsonEscape(message.substring(0, 240)) +
                  "\"";
  if (diagnostics.length() > 0) fields += ",\"diagnostics\":" + diagnostics;
  return sendEvent("app_diagnostic", fields);
}

bool FireBackendClient::appStopped(const String& runId,
                                   const String& packageId,
                                   const String& stopId,
                                   const String& reason,
                                   const String& diagnostics) {
  String fields = ",\"run_id\":\"" + jsonEscape(runId) +
                  "\",\"package_id\":\"" + jsonEscape(packageId);
  if (stopId.length() > 0)
    fields += "\",\"stop_id\":\"" + jsonEscape(stopId);
  fields += "\",\"reason\":\"" + jsonEscape(reason) + "\"";
  if (diagnostics.length() > 0) fields += ",\"diagnostics\":" + diagnostics;
  return sendEvent("app_stopped", fields);
}

bool FireBackendClient::rollbackResult(const String& rollbackId,
                                       const String& packageId, bool ok,
                                       const String& message) {
  return sendEvent("rollback_result", ",\"rollback_id\":\"" +
                   jsonEscape(rollbackId) + "\",\"package_id\":\"" +
                   jsonEscape(packageId) + "\",\"status\":\"" +
                   (ok ? "ok" : "failed") + "\",\"message\":\"" +
                   jsonEscape(message.substring(0, 240)) + "\"");
}

bool FireBackendClient::firmwareStoreResult(
    const String& transferId, const String& firmwareId, bool ok,
    const String& sha256, const String& errorCode, const String& message) {
  String fields = ",\"transfer_id\":\"" + jsonEscape(transferId) +
                  "\",\"firmware_id\":\"" + jsonEscape(firmwareId) +
                  "\",\"status\":\"" + (ok ? "ok" : "failed") + "\"";
  if (ok) {
    fields += ",\"sha256\":\"" + jsonEscape(sha256) + "\"";
  } else {
    fields += ",\"error_code\":\"" + jsonEscape(errorCode) +
              "\",\"message\":\"" +
              jsonEscape(message.substring(0, 240)) + "\"";
  }
  return sendEvent("firmware_store_result", fields);
}

bool FireBackendClient::audioPlaybackStarted(const String& audioId,
                                             const String& turnId) {
  return sendEvent("audio_playback_started", ",\"audio_id\":\"" +
                   jsonEscape(audioId) + "\",\"turn_id\":\"" +
                   jsonEscape(turnId) + "\"");
}

bool FireBackendClient::audioPlaybackFinished(const String& audioId,
                                              const String& turnId) {
  return sendEvent("audio_playback_finished", ",\"audio_id\":\"" +
                   jsonEscape(audioId) + "\",\"turn_id\":\"" +
                   jsonEscape(turnId) + "\"");
}

bool FireBackendClient::audioPlaybackFailed(const String& audioId,
                                            const String& turnId,
                                            const String& errorCode,
                                            const String& message,
                                            const String& diagnostics) {
  String fields = ",\"audio_id\":\"" + jsonEscape(audioId) +
                  "\",\"turn_id\":\"" + jsonEscape(turnId) +
                  "\",\"error_code\":\"" + jsonEscape(errorCode) +
                  "\",\"message\":\"" + jsonEscape(message.substring(0, 240)) +
                  "\"";
  if (diagnostics.length() > 0) fields += ",\"diagnostics\":" + diagnostics;
  return sendEvent("audio_playback_failed", fields);
}

bool FireBackendClient::ping() { return sendEvent("ping"); }

void FireBackendClient::service(bool wifiConnected) {
  if (transportClient_ && reverseTransport_ && reverseTransport_->cancelled(transportClient_)) disconnect();
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
    if (!secureEndpoint_ && reverseTransport_) transportClient_ = reverseTransport_->acquire();
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
      if (client_.connecting() || client_.stopping()) { state_ = State::Offline; reconnectAt_ = 0; return; }
      transportClient_ = nullptr;
      setState(State::Offline, "Backend connection failed");
      return;
    }
    uint8_t randomKey[16];
    for (uint8_t& value : randomKey) value = static_cast<uint8_t>(esp_random());
    const String key = base64::encode(randomKey, sizeof(randomKey));
    const String proof = key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
    uint8_t digest[20]; mbedtls_sha1_ret(reinterpret_cast<const uint8_t*>(proof.c_str()), proof.length(), digest);
    expectedAccept_ = base64::encode(digest, sizeof(digest));
    const String request = "GET /ws/device HTTP/1.1\r\nHost: " + host_ + ":" +
                  String(port_) + "\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: " +
                  key + "\r\nSec-WebSocket-Version: 13\r\nAuthorization: Bearer " +
                  token_ + "\r\n\r\n";
    if (client->print(request) != request.length()) { disconnect(); return; }
    handshakeBuffer_ = "";
    handshakeStartedAt_ = millis();
    setState(State::Handshake, "Authenticating backend");
  }
  if (state_ == State::Handshake) {
    if (millis() - handshakeStartedAt_ > 5000) {
      disconnect();
      setState(State::Offline, "Backend handshake timeout");
      return;
    }
    handleHandshake();
    return;
  }
  if (state_ == State::Connected) {
    readFrames();
    const uint32_t now = millis();
    if (now - lastPingAt_ >= 20000) {
      sendFrame(0x9, nullptr, 0);
      lastPingAt_ = now;
    }
    if (lastPongAt_ != 0 && now - lastPongAt_ >= 45000) {
      disconnect();
      setState(State::Offline, "Backend heartbeat timeout");
    }
  }
}

void FireBackendClient::handleHandshake() {
  WiFiClient* client = activeClient();
  if (!client) return;
  while (client->available() && handshakeBuffer_.length() < 4096) {
    handshakeBuffer_ += static_cast<char>(client->read());
    if (handshakeBuffer_.endsWith("\r\n\r\n")) break;
  }
  if (handshakeBuffer_.indexOf("\r\n\r\n") < 0) return;
  if (!fireWsAccepted(handshakeBuffer_.c_str(), handshakeBuffer_.length(), expectedAccept_.c_str())) {
    disconnect();
    setState(State::Offline, "Backend handshake rejected");
    return;
  }
  sessionStarted_ = false;
  lastReceiveAt_ = millis();
  lastPongAt_ = millis();
  setState(State::Connected, "Waiting for backend session");
  const String fields = ",\"target\":\"device\",\"boot_id\":\"" +
                        jsonEscape(bootId_) +
                        "\",\"capabilities\":{\"api_version\":\"fire-lua-0.2\",\"api_contract\":\"" +
                        FireLuaRuntime::hardwareApiContract() +
                        "\",\"services\":[\"display\",\"buttons\",\"rgb\",\"imu\",\"time\",\"jobs\",\"gpio\",\"pwm\",\"i2c\",\"uart\",\"adc\",\"dac\",\"spi\",\"sd\",\"rtc\",\"speaker\"],\"hardware\":{\"gpio_read\":[26,35,36],\"gpio_write\":[26],\"adc\":[36],\"dac\":[26],\"pwm\":[26],\"i2c\":[0],\"i2c_write_addresses\":[64],\"uart\":[2],\"spi\":[2]},\"max_memory\":131072,\"max_runtime_ms\":0,\"audio_input\":true,\"audio_output\":true,\"firmware_storage\":false,\"firmware_max_bytes\":4194304,\"firmware_version\":\"" +
                        jsonEscape(firmwareVersion_) + "\"}";
  String payload = "{\"type\":\"device_event\",\"protocol_version\":\"0.2\",\"event_id\":\"" +
                   eventId("evt") + "\",\"device_id\":\"" +
                   jsonEscape(deviceId_) + "\",\"event\":\"session_start\"" +
                   (resumeSessionId_.length() > 0
                        ? ",\"resume_session_id\":\"" + jsonEscape(resumeSessionId_) + "\""
                        : String()) +
                   (projectId_.length() > 0
                        ? ",\"project_id\":\"" + jsonEscape(projectId_) + "\""
                        : String()) +
                   (conversationMode_.length() > 0
                        ? ",\"conversation_mode\":\"" + jsonEscape(conversationMode_) + "\""
                        : String()) +
                   (pendingAppMode_.length() > 0
                        ? ",\"app_mode\":\"" + jsonEscape(pendingAppMode_) + "\"" +
                              (pendingAppMode_ == "update" && pendingBasePackageId_.length() > 0
                                   ? ",\"base_package_id\":\"" + jsonEscape(pendingBasePackageId_) + "\""
                                   : String())
                        : String()) +
                   fields + "}";
  if (sendFrame(0x1, reinterpret_cast<const uint8_t*>(payload.c_str()),
                payload.length())) {
    // Explicit app selection is one-shot. Reconnect must resume, not select a
    // new app again.
    pendingAppMode_ = "";
    pendingBasePackageId_ = "";
  }
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
          const uint8_t header = static_cast<uint8_t>(value);
          receiveFin_ = (header & 0x80) != 0;
          if (header & 0x70) {
            disconnect();
            setState(State::Offline, "Invalid WebSocket flags");
            return;
          }
          receiveOpcode_ = header & 0x0F;
          if (receiveOpcode_ == 0x0 && fragmentOpcode_ == 0) {
            disconnect();
            setState(State::Offline, "Unexpected WebSocket continuation");
            return;
          }
        } else {
          receiveMasked_ = (static_cast<uint8_t>(value) & 0x80) != 0;
          const uint8_t lengthCode = static_cast<uint8_t>(value) & 0x7F;
          if (lengthCode <= 125) {
            receiveLength_ = lengthCode;
            if (receiveOpcode_ >= 0x8 &&
                (!receiveFin_ || receiveLength_ > 125)) {
              disconnect();
              setState(State::Offline, "Invalid WebSocket control frame");
              return;
            }
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
      if (receiveOpcode_ == 0x0) {
        fragmentBuffer_ += frameBuffer_;
        if (fragmentBuffer_.length() > kMaxFrameBytes) {
          disconnect();
          setState(State::Offline, "Fragmented WebSocket frame too large");
          return;
        }
        if (receiveFin_) {
          handleFrame(fragmentOpcode_,
                      reinterpret_cast<const uint8_t*>(fragmentBuffer_.c_str()),
                      fragmentBuffer_.length());
          fragmentOpcode_ = 0;
          fragmentBuffer_ = "";
        }
      } else if (receiveOpcode_ == 0x1 && fragmentOpcode_ == 0 &&
                 !receiveFin_) {
        fragmentOpcode_ = receiveOpcode_;
        fragmentBuffer_ = frameBuffer_;
      } else if (receiveOpcode_ == 0x1 && fragmentOpcode_ != 0) {
        disconnect();
        setState(State::Offline, "Overlapping WebSocket fragments");
        return;
      } else {
        handleFrame(receiveOpcode_,
                    reinterpret_cast<const uint8_t*>(frameBuffer_.c_str()),
                    frameBuffer_.length());
      }
      resetReceiveFrame();
    }
  }
}

void FireBackendClient::handleFrame(uint8_t opcode, const uint8_t* data,
                                    size_t length) {
  lastReceiveAt_ = millis();
  if (opcode == 0x8) {
    disconnect();
    setState(State::Offline, "Backend closed connection");
  } else if (opcode == 0x9) {
    sendFrame(0xA, data, length);
  } else if (opcode == 0xA) {
    lastPongAt_ = millis();
  } else if (opcode == 0x1 && messageCallback_) {
    if (!fireJsonSafe(reinterpret_cast<const char*>(data), length, kMaxFrameBytes)) {
      disconnect(); setState(State::Offline, "Invalid backend message"); return;
    }
    String message;
    message.reserve(length);
    for (size_t index = 0; index < length; ++index) message += static_cast<char>(data[index]);
    const String type = jsonStringField(message, "type");
    const uint32_t seq = jsonUintField(message, "seq");
    if (seq > 0 && lastServerSeq_ > 0 && seq <= lastServerSeq_) return;
    if (seq > 0) lastServerSeq_ = seq;
    if (type == "session_started") {
      const String newSession = jsonStringField(message, "session_id");
      if (newSession.length() > 0) {
        sessionId_ = newSession;
        resumeSessionId_ = "";
        sessionStarted_ = true;
        setState(State::Connected, usingReverseTransport_
                                      ? "Backend connected (Reverse TCP)"
                                      : "Backend connected (Direct)");
      }
    } else if ((type == "session_snapshot" || type == "pong") &&
               sessionId_.length() == 0) {
      const String snapshotSession = jsonStringField(message, "session_id");
      if (snapshotSession.length() > 0) {
        sessionId_ = snapshotSession;
        sessionStarted_ = true;
        setState(State::Connected, usingReverseTransport_
                                      ? "Backend connected (Reverse TCP)"
                                      : "Backend connected (Direct)");
      }
    }
    messageCallback_(callbackContext_, message);
  }
}
