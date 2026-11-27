#include "fire_backend_client.h"
#include "fire_backend_policy.h"

#include <base64.h>
#include <esp_system.h>
#include <esp_timer.h>
#include "fire_lua_runtime.h"
#include "fire_runtime_ai_contract.h"
#include "fire_data_engine_contract.h"
#include "fire_evolution_contract.h"
#include "fire_hardware_policy.h"
#include "fire_firmware_http.h"
#include "fire_json_guard.h"
#include "fire_session_json.h"
#include "fire_worker_diagnostics.h"
#include "fire_ws_handshake.h"
#include <mbedtls/sha1.h>
#include <cJSON.h>
#include <M5Unified.h>

namespace {
constexpr size_t kMaxFrameBytes = 8192;
String dataCapabilities() {
  String sources="[",limits="{";
  const auto add=[&](const char* source,const char* values) {
    if (sources.length()>1) {sources+=",";limits+=",";}
    sources+="\""+String(source)+"\"";limits+="\""+String(source)+"\":"+values;
  };
  if (M5.Imu.isEnabled() && M5.Imu.getType()==m5::imu_mpu6886)
    add("imu","{\"duration_ms_max\":60000,\"sample_rates_hz\":[50,100],\"max_records\":6000}");
#if defined(FIRE_AUDIO_CAPTURE_ENABLED) && FIRE_AUDIO_CAPTURE_ENABLED
  if (M5.Mic.isEnabled()) add("mic","{\"duration_ms_max\":10000,\"sample_rates_hz\":[8000,16000],\"max_records\":160000}");
#endif
#ifdef FIRE_OS_BLE
  add("ble.advertisements","{\"duration_ms_max\":60000,\"max_records\":6000}");
#endif
  return "{\"version\":\""+String(FireDataEngineContract::kVersion)+"\",\"contract\":\""+FireDataEngineContract::kContract+
      "\",\"capture_sources\":"+sources+"],\"capture_limits\":"+limits+"}}";
}
String i2cWriteResources() {
  String values="[";
  for (uint8_t address=8;address<=0x77;++address) {
    if (!fire_hardware_policy::externalI2cWrite(address) || (address==0x6c && M5.Imu.getType()==m5::imu_sh200q)) continue;
    if (values.length()>1) values+=",";
    values+=String(address);
  }
  return values+"]";
}
String hardwareServiceCapabilities() {
  String services="\"display\",\"buttons\",\"rgb\",\"imu\",\"time\",\"jobs\",\"gpio\",\"pwm\",\"i2c\",\"uart\",\"adc\",\"dac\",\"spi\",\"sd\",\"rtc\",\"speaker\",\"ai\",\"wifi\",\"data\"";
  String methods="\"wifi\":[\"status\",\"scan\"]",modes="{}";
#ifdef FIRE_OS_BLE
  services+=",\"bluetooth\"";
  methods+=",\"bluetooth\":[\"scan\",\"read_gatt\",\"write_gatt\",\"advertise\",\"advertise_raw\",\"close\"]";
  modes="{\"bluetooth.scan\":[\"ble\"]}";
#endif
#if defined(FIRE_AUDIO_CAPTURE_ENABLED) && FIRE_AUDIO_CAPTURE_ENABLED
  services+=",\"mic\"";methods+=",\"mic\":[\"level\",\"record\"]";
#endif
  return ",\"services\":["+services+"],\"service_methods\":{"+methods+"},\"service_modes\":"+modes;
}

String jsonEscape(const String& input) {return fire_session::escape(input);}

String jsonStringField(const String& json, const char* key) {
  const String marker = String("\"") + key + "\"";
  const int keyAt = json.indexOf(marker);
  if (keyAt < 0) return "";
  const int colon = json.indexOf(':', keyAt + marker.length());
  const int quote = json.indexOf('"', colon + 1);
  if (colon < 0 || quote < 0) return "";
  String value;
  bool escaped = false;
  for (int index = quote + 1; index < static_cast<int>(json.length()); ++index) {
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
  while (start < static_cast<int>(json.length()) && (json[start] == ' ' || json[start] == '\t')) ++start;
  return static_cast<uint32_t>(json.substring(start).toInt());
}
}  // namespace

void FireBackendClient::configure(const String& host, uint16_t port,
                                  const String& token, const String& deviceId,
                                  const String& firmwareVersion) {
  disconnect();
  retrySession();
  secureEndpoint_ = fireNetworkTls(host, port);
  host_ = fireNetworkEndpointValid(host) ? fireNetworkHost(host) : String();
  client_.secure(secureEndpoint_);
  audioClient_.secure(secureEndpoint_);
  port_ = port == 0 ? (secureEndpoint_ ? 443 : 8765) : port;
  token_ = token;
  if (deviceId.length() > 0) deviceId_ = deviceId;
  if (firmwareVersion.length() > 0) firmwareVersion_ = firmwareVersion;
  resumeSessionId_ = "";
  confirmedProject_=confirmedBase_=confirmedMode_=confirmedAppMode_=String();
  selection_.clear();selectionReply_=0;
  lastServerSeq_ = 0;
  bootId_ = "boot-" + String(static_cast<uint32_t>(esp_random()), HEX) +
            String(millis(), HEX);
  status_ = configured() ? "Backend disconnected" : "Backend not configured";
}

void FireBackendClient::setConversationMode(const String& mode) {
  if (mode!="chat" && mode!="develop") return;
  // Existing frozen Data Engine context applies its own mode/proposal on the
  // server. A later mode_select would cancel that just-restored proposal.
  if (developmentContext_.length() && mode=="develop") return;
  selection_.queueMode(mode,bootId_+"-"+eventId("mode"));
}

void FireBackendClient::setAppMode(const String& mode,const String& basePackageId) {
  if (mode!="new" && mode!="update") return;
  selection_.queueApp(mode,projectId_,basePackageId,bootId_+"-"+eventId("app"));
}

void FireBackendClient::serviceSelection() {
  if (!sessionReady() || developmentContext_.length()) return;
  if (selection_.sendApp()) {
    const String fields=fire_session::appFields(selection_.appMode,selection_.project,selection_.base);
    selection_.appSent=true;
    if (!sendEvent("app_select",fields,selection_.appEvent)) {selection_.lost();disconnect();}
  } else if (selection_.sendMode()) {
    selection_.modeSent=true;
    if (!sendEvent("mode_select",fire_session::modeFields(selection_.mode),selection_.modeEvent)) {selection_.lost();disconnect();}
  }
}

void FireBackendClient::observeSession(const String& type,const String& message) {
  selectionReply_=0;
  const bool bootstrap=type=="session_started" || type=="session_snapshot";
  if (!bootstrap && type!="app_selected" && type!="conversation_mode" && type!="event_ack" && type!="error") return;
  const fire_session_json::Document document(message.c_str(),message.length());
  if(!document.valid()) return;
  const auto root=document.root();
  const auto result=document.field(root,"result");
  const auto receipts=document.field(root,"selection_ack");
  // Complete validation before ANY acknowledged scope/selection mutation.
  // cJSON lookup semantics for missing/null/wrong-type and first duplicate
  // members are retained; oversized or NUL-containing selected text fails closed.
  for(const auto object:{root,result}) {
    for(const char* key:{"project_id","base_package_id","conversation_mode","app_mode"})
      if(!fire_session_json::Document::selected(document.field(object,key))) return;
  }
  if(!fire_session_json::Document::selected(document.field(root,"event_id")) ||
     !fire_session_json::Document::selected(document.field(receipts,"app_select")) ||
     !fire_session_json::Document::selected(document.field(receipts,"mode_select"))) return;
  const auto event=document.field(root,"event_id");
  const bool appEvent=selection_.appEvent.length() && fire_session_json::Document::equal(event,selection_.appEvent.c_str());
  const bool modeEvent=selection_.modeEvent.length() && fire_session_json::Document::equal(event,selection_.modeEvent.c_str());
  bool appAck=false,modeAck=false,rejected=false;
  if (bootstrap) {
    appAck=selection_.appSent && selection_.appEvent.length() &&
      fire_session_json::Document::equal(document.field(receipts,"app_select"),selection_.appEvent.c_str());
    modeAck=selection_.modeSent && selection_.modeEvent.length() &&
      fire_session_json::Document::equal(document.field(receipts,"mode_select"),selection_.modeEvent.c_str());
  } else if(type=="error" || (type=="event_ack" && document.field(result,"error").present())) {
    rejected=appEvent || modeEvent;
  } else {
    appAck=(type=="app_selected" || type=="event_ack") && appEvent && selection_.appSent;
    modeAck=(type=="conversation_mode" || type=="event_ack") && modeEvent && selection_.modeSent;
  }
  const auto scope=bootstrap || type=="app_selected" || type=="conversation_mode"?root:
    type=="event_ack" && !rejected && (appAck || modeAck)?result:fire_session_json::Span();
  const auto project=document.field(scope,"project_id"),base=document.field(scope,"base_package_id");
  String projectText,baseText,modeText,appText;
  if(!fire_session_json::Document::text(project,projectText) ||
     !fire_session_json::Document::text(base,baseText) ||
     !fire_session_json::Document::text(document.field(scope,"conversation_mode"),modeText) ||
     !fire_session_json::Document::text(document.field(scope,"app_mode"),appText)) return;
  // Commit only after EVERY needed decode/allocation succeeded. Pinned
  // WString::move copies only into sufficient capacity, otherwise steals the
  // staged allocation; neither branch allocates. IDs are matched as spans
  // against already owned pending IDs, so no receipt/event copy is needed.
  if(project.present()) confirmedProject_=static_cast<String&&>(projectText);
  if(base.present()) confirmedBase_=static_cast<String&&>(baseText);
  if(modeText=="chat" || modeText=="develop") confirmedMode_=static_cast<String&&>(modeText);
  if(appText=="new" || appText=="update") confirmedAppMode_=static_cast<String&&>(appText);
  if(rejected) {
    if(selection_.rejected(appEvent?selection_.appEvent:selection_.modeEvent)) selectionReply_|=4;
  } else {
    if(appAck && selection_.appAck(selection_.appEvent)) selectionReply_|=1;
    if(modeAck && selection_.modeAck(selection_.modeEvent)) selectionReply_|=2;
  }
}

void FireBackendClient::setRuntimeAiMode(const String& mode,bool publish) {
  if(mode!="auto" && mode!="off") return;runtimeAiMode_=mode;
  if(publish && sessionReady()) sendEvent("mode_select",",\"runtime_ai_mode\":\""+mode+"\"");
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
  selection_.lost();
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
  releaseReadBuffersPending_=true;releaseReadBuffers();
  if (sessionId_.length() > 0) resumeSessionId_ = sessionId_;
  sessionId_ = "";
  sessionStarted_ = false;
  setState(configured() ? State::Offline : State::Offline,
           configured() ? "Backend disconnected" : "Backend not configured");
}

void FireBackendClient::releaseReadBuffers() {
  if(receiveCallbackActive_ || !releaseReadBuffersPending_) return;
  fire_backend_policy::releaseTextBuffer(handshakeBuffer_);
  fire_backend_policy::releaseTextBuffer(frameBuffer_);
  fire_backend_policy::releaseTextBuffer(fragmentBuffer_);
  releaseReadBuffersPending_=false;
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
  const bool dataUpload=audioTransfer_==AudioTransfer::DataUpload;
  if (audioTransferCancel_ || audioSession_.length() == 0 || !wavData || (!dataUpload && wavLength == 0) ||
      wavLength > (dataUpload?FireDataEngineContract::kHttpChunkBytes:524288u)) {
    return false;
  }
  WiFiClient* audio = nullptr;
  if (!audioTransportClient_ && !audioSecure_ && audioReverse_) audioTransportClient_ = audioReverse_->acquire(audioReverseGeneration_);
  if (audioTransportClient_) {
    audio = audioTransportClient_;
  } else {
    if (!dataUpload || !audioClient_.connected()) {
      audioClient_.stop();audioClient_.secure(audioSecure_);
      if (!audioClient_.connectBlocking(audioHost_.c_str(), audioPort_, 15000, &audioTransferCancel_)) return false;
    }
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
  const String path = dataUpload
      ? "/sessions/"+audioSession_+"/data/"+turnId+"/"+dataUploadDataset_
      : "/sessions/" + audioSession_ + "/audio/" + turnId;
  const String request = "POST " + path + " HTTP/1.1\r\nHost: " + audioHost_ + ":" +
               String(audioPort_) + "\r\nAuthorization: Bearer " + audioToken_ +
               (dataUpload?"\r\nContent-Type: application/octet-stream\r\nX-Data-Offset: "+String(dataUploadOffset_)+
                   "\r\nX-Data-SHA256: "+dataUploadHash_+"\r\nX-Data-Part: "+dataUploadPart_:String("\r\nContent-Type: audio/wav")) + "\r\nContent-Length: " +
               String(wavLength) + (dataUpload?"\r\nConnection: keep-alive\r\n\r\n":"\r\nConnection: close\r\n\r\n");
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
    while (audio->available() && response.length() < 512) {
      response += static_cast<char>(audio->read());
      if (dataUpload && response.endsWith("\r\n\r\n")) break;
    }
    if (response.indexOf("\r\n\r\n") < 0) delay(1);
  }
  const bool accepted=response.startsWith("HTTP/1.1 2") || response.startsWith("HTTP/1.0 2");
  if (dataUpload && accepted) {
    const int headerEnd=response.indexOf("\r\n\r\n");
    String headers=response.substring(0,headerEnd);headers.toLowerCase();
    const int at=headers.indexOf("content-length:");
    if (headerEnd<0 || at<0 || headers.indexOf("transfer-encoding:")>=0 || headers.indexOf("content-encoding:")>=0) {closeAudio();return false;}
    const int bodyBytes=headers.substring(at+15).toInt();
    if (bodyBytes<=0 || bodyBytes>256 ||
        !fire_firmware_http::validResponse(response.c_str(),headerEnd+4,static_cast<uint32_t>(bodyBytes))) {closeAudio();return false;}
    String body=response.substring(headerEnd+4);
    while (body.length()<static_cast<size_t>(bodyBytes) && millis()<deadline && !audioTransferCancel_) {
      while (audio->available() && body.length()<static_cast<size_t>(bodyBytes)) body+=static_cast<char>(audio->read());
      if (body.length()<static_cast<size_t>(bodyBytes)) delay(1);
    }
    if (body.length()!=static_cast<size_t>(bodyBytes) || !fireJsonSafe(body.c_str(),body.length(),256,4,32)) {closeAudio();return false;}
    cJSON* obj=cJSON_Parse(body.c_str());
    const cJSON* offset=cJSON_GetObjectItemCaseSensitive(obj,"offset");
    const cJSON* complete=cJSON_GetObjectItemCaseSensitive(obj,"complete");
    const cJSON* next=cJSON_GetObjectItemCaseSensitive(obj,"next_upload");
    const bool valid=cJSON_IsNumber(offset) && offset->valuedouble==static_cast<double>(dataUploadOffset_+wavLength) && cJSON_IsBool(complete) &&
        (!next || cJSON_IsNull(next) || cJSON_IsObject(next));
    if (valid) {
      dataUploadResponseOffset_=static_cast<uint32_t>(offset->valuedouble);
      char* encoded=cJSON_IsObject(next)?cJSON_PrintUnformatted(next):nullptr;
      dataUploadNext_=encoded?String(encoded):String();cJSON_free(encoded);
    }
    cJSON_Delete(obj);
    if (!valid || headers.indexOf("connection: close")>=0) closeAudio();
    return valid;
  }
  closeAudio();return accepted;
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
bool FireBackendClient::beginDataUpload(const String& request,const String& dataset,const String& part,
    uint32_t offset,const String& chunkHash,const uint8_t* bytes,size_t length) {
  const auto safe=[](const String& id) {
    if (!id.length() || id.length()>128) return false;
    for (size_t i=0;i<id.length();++i) {const char c=id[i];if (!isalnum(static_cast<unsigned char>(c)) && c!='-' && c!='_') return false;}
    return true;
  };
  const bool reuse=audioTransferRunning_ && dataTransferActive_ && dataChunkDone_ && !audioTransferCancel_ && audioTransferTurnId_==request;
  if ((audioTransferRunning_ && !reuse) || !sessionReady() || !bytes || length>FireDataEngineContract::kHttpChunkBytes ||
      !safe(request) || !safe(dataset) || (part!="data" && part!="index" && part!="events") || chunkHash.length()!=64) return false;
  for (size_t i=0;i<chunkHash.length();++i) if (!isxdigit(static_cast<unsigned char>(chunkHash[i]))) return false;
  if (!reuse) {snapshotAudioEndpoint();audioTransfer_=AudioTransfer::DataUpload;}
  dataUploadDataset_=dataset;dataUploadPart_=part;dataUploadOffset_=offset;dataUploadHash_=chunkHash;dataUploadNext_=String();
  audioTransferTurnId_=request;audioTransferUploadData_=bytes;audioTransferDownloadBuffer_=nullptr;audioTransferBytes_=length;
  audioTransferLength_=0;audioTransferFinished_=false;audioTransferOk_=false;dataChunkDone_=false;
  dataChunkReady_.store(true,std::memory_order_release);
  if (reuse) return true;
  audioTransferCancel_=false;dataTransferActive_=true;audioTransferRunning_=true;
  if (xTaskCreatePinnedToCore(audioTaskEntry,"fire-data-http",6144,this,2,&audioTask_,0)!=pdPASS) {
    dataTransferActive_=false;audioTransferRunning_=false;audioTransfer_=AudioTransfer::None;return false;
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
  if (audioTransfer_==AudioTransfer::DataUpload) {
    const uint32_t started=millis();
    while (!audioTransferCancel_ && millis()-started<FireDataEngineContract::kNetworkJobTimeoutMs) {
      if (!dataChunkReady_.load(std::memory_order_acquire)) {delay(2);continue;}
      dataChunkReady_=false;
      ok=uploadAudio(audioTransferTurnId_,audioTransferUploadData_,audioTransferBytes_);
      audioTransferLength_=ok?dataUploadResponseOffset_:0;
      audioTransferOk_=ok && !audioTransferCancel_;
      dataChunkDone_.store(true,std::memory_order_release);
      if (!ok) break;
    }
    if (audioTransportClient_ && audioReverse_) {audioReverse_->release(audioTransportClient_);audioTransportClient_=nullptr;}
    else audioClient_.stop();
    dataTransferActive_=false;
  } else if (audioTransfer_ == AudioTransfer::Upload) {
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
  if (selection_.pending()) return false;
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

bool FireBackendClient::appList(uint32_t offset,const String& stableEventId) {
  return sendEvent("app_list", ",\"offset\":" + String(offset),stableEventId);
}

bool FireBackendClient::appVersions(const String& projectId,
                                    const String& appId, uint32_t offset,const String& stableEventId) {
  String fields = ",\"offset\":" + String(offset);
  if (projectId.length() > 0)
    fields += ",\"project_id\":\"" + jsonEscape(projectId) + "\"";
  else if (appId.length() > 0)
    fields += ",\"app_id\":\"" + jsonEscape(appId) + "\"";
  else
    return false;
  return sendEvent("app_versions", fields,stableEventId);
}

bool FireBackendClient::appDownload(const String& projectId,
                                    const String& packageId,
                                    const String& appId,const String& stableEventId) {
  if (packageId.length() == 0) return false;
  String fields = ",\"package_id\":\"" + jsonEscape(packageId) + "\"";
  if (projectId.length() > 0)
    fields += ",\"project_id\":\"" + jsonEscape(projectId) + "\"";
  if (appId.length() > 0)
    fields += ",\"app_id\":\"" + jsonEscape(appId) + "\"";
  return sendEvent("app_download",fields,stableEventId);
}

bool FireBackendClient::appBackendDeletePrepare(
    const String& projectId, const String& appId, const String& scope,
    const String& packageId,const String& stableEventId) {
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
  return sendEvent("app_backend_delete_prepare", fields,stableEventId);
}

bool FireBackendClient::appBackendDeleteConfirm(const String& deleteId,const String& stableEventId) {
  if (deleteId.length() == 0) return false;
  return sendEvent("app_backend_delete_confirm", ",\"delete_id\":\"" +
                                                   jsonEscape(deleteId) + "\"",stableEventId);
}

bool FireBackendClient::confirmBuild(const String& proposalId,
                                     const String& repairId) {
  if (selection_.pending()) return false;
  String fields = ",\"proposal_id\":\"" + jsonEscape(proposalId) + "\"";
  if (repairId.length() > 0)
    fields += ",\"repair_id\":\"" + jsonEscape(repairId) + "\"";
  return sendEvent("build_confirm", fields);
}

bool FireBackendClient::confirmRun(const String& packageId) {
  if (selection_.pending()) return false;
  return sendEvent("run_confirm", ",\"package_id\":\"" +
                   jsonEscape(packageId) + "\"");
}

static String evolutionIdentity(const String& request,const String& app) {
  return ",\"request_id\":\""+jsonEscape(request)+"\",\"app_id\":\""+jsonEscape(app)+"\"";
}
bool FireBackendClient::evolutionStatus(const String& request,const String& app,const String& view,uint32_t offset) {
  return sendEvent("evolution_status",evolutionIdentity(request,app)+",\"view\":\""+jsonEscape(view)+"\",\"offset\":"+String(offset),request);
}
bool FireBackendClient::evolutionPrepare(const String& request,const String& app,const String& operation,uint32_t revision,
    const String& json,const String& packageId,const String& source) {
  if (!fireJsonSafe(json.c_str(),json.length(),FireEvolutionContract::kControlJsonBytes)) return false;
  String fields=evolutionIdentity(request,app)+",\"operation\":\""+jsonEscape(operation)+
      "\",\"expected_revision\":"+String(revision)+",\"evolution_json\":\""+jsonEscape(json)+
      "\"";
  if (packageId.length()) fields+=",\"package_id\":\""+jsonEscape(packageId)+"\"";
  if (source.length()) fields+=",\"source_sha256\":\""+jsonEscape(source)+"\"";
  return sendEvent("evolution_prepare",fields,request);
}
bool FireBackendClient::evolutionConfirm(const String& request,const String& app,const String& proposal,uint32_t revision) {
  return sendEvent("evolution_confirm",evolutionIdentity(request,app)+",\"proposal_id\":\""+jsonEscape(proposal)+
      "\",\"expected_revision\":"+String(revision),request);
}
bool FireBackendClient::evolutionControl(const String& request,const String& app,const String& action,uint32_t revision,
    const String& job,const String& mandate) {
  if (action!="pause" && action!="resume" && action!="stop" && action!="revoke") return false;
  String fields=evolutionIdentity(request,app)+",\"evolution_action\":\""+action+"\",\"expected_revision\":"+String(revision);
  if (job.length()) fields+=",\"evolution_job_id\":\""+jsonEscape(job)+"\"";
  if (mandate.length()) fields+=",\"evolution_mandate_id\":\""+jsonEscape(mandate)+"\"";
  return sendEvent("evolution_control",fields,request);
}
bool FireBackendClient::evolutionTelemetry(const String& request,const String& app,const String& packageId,
    const String& source,const String& json) {
  if (!fireJsonSafe(json.c_str(),json.length(),FireEvolutionContract::kTelemetryJsonBytes)) return false;
  return sendEvent("evolution_telemetry",evolutionIdentity(request,app)+",\"package_id\":\""+jsonEscape(packageId)+
      "\",\"source_sha256\":\""+jsonEscape(source)+"\",\"telemetry_json\":\""+jsonEscape(json)+"\"",request);
}

static String runtimeIdentityFields(const String& requestId,const String& appId,const String& packageId,
                                    const String& sourceHash,const String& runId) {
  return ",\"request_id\":\""+jsonEscape(requestId)+"\",\"app_id\":\""+jsonEscape(appId)+
    "\",\"package_id\":\""+jsonEscape(packageId)+"\",\"source_sha256\":\""+jsonEscape(sourceHash)+
    "\",\"run_id\":\""+jsonEscape(runId)+"\"";
}
bool FireBackendClient::backendSettingsStatus(const String& request,const String& view,const String& role,uint32_t offset) {
  String fields=",\"request_id\":\""+jsonEscape(request)+"\",\"view\":\""+jsonEscape(view)+"\",\"offset\":"+String(offset);
  if (role.length()) fields+=",\"role\":\""+jsonEscape(role)+"\"";
  return sendEvent("backend_settings_status",fields,request);
}
bool FireBackendClient::backendSettingsPrepare(const String& request,uint32_t revision,const String& patch) {
  if (!fireJsonSafe(patch.c_str(),patch.length(),FireEvolutionContract::kControlJsonBytes)) return false;
  return sendEvent("backend_settings_prepare",",\"request_id\":\""+jsonEscape(request)+"\",\"expected_revision\":"+String(revision)+
      ",\"settings_json\":\""+jsonEscape(patch)+"\"",request);
}
bool FireBackendClient::backendSettingsConfirm(const String& request,const String& proposal,uint32_t revision) {
  return sendEvent("backend_settings_confirm",",\"request_id\":\""+jsonEscape(request)+"\",\"proposal_id\":\""+jsonEscape(proposal)+
      "\",\"expected_revision\":"+String(revision),request);
}
bool FireBackendClient::runtimeAiRequest(const String& requestId,const String& appId,const String& packageId,
                                       const String& sourceHash,const String& runId,const String& instructions,
                                       const String& data,const String& schema,uint32_t timeoutMs) {
  return sendEvent("runtime_ai_request",runtimeIdentityFields(requestId,appId,packageId,sourceHash,runId)+
    ",\"instructions\":\""+jsonEscape(instructions)+"\",\"data_json\":\""+jsonEscape(data)+
    "\",\"schema_json\":\""+jsonEscape(schema)+"\",\"timeout_ms\":"+String(timeoutMs));
}
bool FireBackendClient::runtimeAiCancel(const String& requestId,const String& appId,const String& packageId,
                                      const String& sourceHash,const String& runId) {
  return sendEvent("runtime_ai_cancel",runtimeIdentityFields(requestId,appId,packageId,sourceHash,runId));
}
bool FireBackendClient::dataRequest(const String& requestId,const String& appId,const String& packageId,
    const String& sourceHash,const String& runId,const String& operation,const String& datasetId,
    const String& options,const String& datasets) {
  return sendEvent("data_request",runtimeIdentityFields(requestId,appId,packageId,sourceHash,runId)+
      ",\"operation\":\""+jsonEscape(operation)+"\",\"dataset_id\":\""+jsonEscape(datasetId)+
      "\",\"options_json\":\""+jsonEscape(options)+"\",\"datasets\":"+datasets);
}
bool FireBackendClient::dataCancel(const String& requestId,const String& appId,const String& packageId,
    const String& sourceHash,const String& runId) {
  return sendEvent("data_cancel",runtimeIdentityFields(requestId,appId,packageId,sourceHash,runId));
}
bool FireBackendClient::appDevelop(const String& requestId,const String& appId,const String& packageId,
    const String& sourceHash,const String& runId,const String& mode,const String& instruction,
    const String& ids,const String& datasets) {
  return sendEvent("app_develop_request",runtimeIdentityFields(requestId,appId,packageId,sourceHash,runId)+
      ",\"mode\":\""+jsonEscape(mode)+"\",\"instruction\":\""+jsonEscape(instruction)+
      "\",\"dataset_ids\":"+ids+",\"datasets\":"+datasets);
}
bool FireBackendClient::confirmObservation(const String& context,const String& action,const String& id) {
  if (action!="confirm" && action!="reject") return false;
  return sendEvent("app_observation_confirm",",\"context_id\":\""+jsonEscape(context)+
      "\",\"observation_action\":\""+action+"\"",id);
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
                                        const String& appId,const String& stableEventId) {
  if (repairId.length() == 0 && appId.length() == 0) return false;
  String fields;
  if (repairId.length() > 0)
    fields += ",\"repair_id\":\"" + jsonEscape(repairId) + "\"";
  if (appId.length() > 0) {
    fields += ",\"app_id\":\"" + jsonEscape(appId) + "\"";
  }
  return sendEvent("app_repair_status", fields,stableEventId);
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

bool FireBackendClient::jobControl(const String& action,const String& build,const String& repair) {
  if ((build.length()>0)==(repair.length()>0) ||
      (action!="resume" && action!="pause" && action!="cancel" && action!="background" && action!="context" && action!="delete")) return false;
  return sendEvent("job_control",",\"job_action\":\""+action+"\",\""+(build.length()?String("build_id"):String("repair_id"))+"\":\""+jsonEscape(build.length()?build:repair)+"\"");
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
                                             const String& message,const String& stableEventId) {
  return sendEvent("device_install_result", ",\"install_id\":\"" +
                   jsonEscape(installId) + "\",\"package_id\":\"" +
                   jsonEscape(packageId) + "\",\"status\":\"" +
                   (ok ? "ok" : "failed") + "\",\"archive_sha256\":\"" +
                   jsonEscape(archiveHash) + "\",\"message\":\"" +
                   jsonEscape(message.substring(0, 240)) + "\"" +
                   (!ok && message=="metadata_error"?String(",\"error_code\":\"metadata_error\""):String()),stableEventId);
}

bool FireBackendClient::appStarted(const String& runId, const String& packageId,
                                   const String& sourceHash, const String& diagnostics) {
  String fields = ",\"run_id\":\"" + jsonEscape(runId) +
                  "\",\"package_id\":\"" + jsonEscape(packageId) +
                  "\",\"source_sha256\":\"" + jsonEscape(sourceHash) + "\"";
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
  if (!sessionAdmission_.allowed()) {
    setState(State::Offline,"Backend session rejected");
    return;
  }
  if (state_ == State::Offline) {
    if (millis() < reconnectAt_) return;
    reconnectAt_ = millis() + 3000;
    if (!secureEndpoint_ && reverseTransport_) transportClient_ = reverseTransport_->acquire();
    usingReverseTransport_=transportClient_!=nullptr;
    setState(State::Connecting,
             usingReverseTransport_ ? "Connecting via Reverse TCP"
                                     : "Connecting to backend");
  }
  if (state_ == State::Connecting) {
    WiFiClient* client=activeClient();
    // Keep this phase while the existing worker connects or finishes cancel.
    // Do not republish Connecting/dirty the UI on every asynchronous poll.
    const bool ready=usingReverseTransport_ || client->connect(host_.c_str(),port_,1200);
    const auto progress=fire_backend_policy::progress(ready,client_.connecting(),client_.stopping(),client_.running());
    if (progress==fire_backend_policy::Progress::Waiting) return;
    if (progress==fire_backend_policy::Progress::Failed) {
      transportClient_=nullptr;reconnectAt_=millis()+3000;
      setState(State::Offline,"Backend connection failed");return;
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
    handshakeStartedAt_ = millis();bootstrapStages_=0;
    bootstrapDiagnostic(0,usingReverseTransport_?1:0);
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
    if (state_!=State::Connected) return;
    serviceSelection();
    if (state_!=State::Connected) return;
    const uint32_t now = millis();
    if (fireWsSessionExpired(sessionStarted_,now,handshakeStartedAt_)) {
      bootstrapDiagnostic(6,receivePayloadBytes_,receiveLength_);
      disconnect();
      setState(State::Offline,"Backend session timeout");
      return;
    }
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
  bootstrapDiagnostic(1);
  fire_backend_policy::releaseTextBuffer(handshakeBuffer_);
  memoryKinds_=0;
  sessionStarted_ = false;
  lastReceiveAt_ = millis();
  handshakeStartedAt_=lastReceiveAt_; // fresh application-session stage; never refreshed by PONG
  lastPongAt_ = millis();
  setState(State::Connected, "Waiting for backend session");
  String payload;
  bool built=true;
  const auto append=[&](const char* value) {if(built && !payload.concat(value)) built=false;};
  append("{\"type\":\"device_event\",\"protocol_version\":\"0.2\",\"event_id\":\"");
  append(eventId("evt").c_str());
  append("\",\"device_id\":\"");
  append(jsonEscape(deviceId_).c_str());
  append("\",\"event\":\"session_start\"");
  append(fire_session::startFields(resumeSessionId_,developmentContext_).c_str());
  append(",\"target\":\"device\",\"boot_id\":\"");
  append(jsonEscape(bootId_).c_str());
  append("\",\"capabilities\":{\"api_version\":\"fire-lua-0.2\",\"api_contract\":\"");
  append(FireLuaRuntime::hardwareApiContract());
  append("\",\"app_sdk\":{\"version\":\"");
  append(FireLuaRuntime::appSdkVersion());
  append("\",\"contract\":\"");
  append(FireLuaRuntime::appSdkContract());
  append("\"},\"runtime_ai\":{\"version\":\"");
  append(FireRuntimeAiContract::kVersion);
  append("\",\"contract\":\"");
  append(FireRuntimeAiContract::kContract);
  append("\"},\"evolution\":{\"version\":\"");
  append(FireEvolutionContract::kVersion);
  append("\",\"contract\":\"");
  append(FireEvolutionContract::kContract);
  append("\"},\"data_engine\":");
  append(dataCapabilities().c_str());
  append(hardwareServiceCapabilities().c_str());
  append(",\"hardware\":{\"gpio_read\":[26,35,36],\"gpio_write\":[26],\"adc\":[36],\"dac\":[26],\"pwm\":[26],\"i2c\":[0],\"i2c_write_addresses\":");
  append(i2cWriteResources().c_str());
  append(",\"uart\":[2],\"spi\":[2]},\"max_memory\":131072,\"max_runtime_ms\":0,\"audio_input\":true,\"audio_output\":true,\"firmware_storage\":false,\"firmware_max_bytes\":4194304,\"firmware_version\":\"");
  append(jsonEscape(firmwareVersion_).c_str());
  append("\"}");
  append("}");
  if(!built) {disconnect();setState(State::Offline,"Backend start allocation failed");return;}
  // Pending choices are separate normal events, consumed only on server ACK.
  sendFrame(0x1,reinterpret_cast<const uint8_t*>(payload.c_str()),payload.length());
}

void FireBackendClient::bootstrapDiagnostic(uint8_t stage,uint32_t first,uint32_t second) {
  const uint8_t bit=static_cast<uint8_t>(1u<<stage);
  if (bootstrapStages_&bit) return;
  bootstrapStages_|=bit;
  // Numeric stage/elapsed/progress only: no identity, endpoint or payload.
  Serial.printf("FIRE bootstrap stage=%u elapsed_ms=%lu a=%lu b=%lu\n",
      unsigned(stage),static_cast<unsigned long>(millis()-handshakeStartedAt_),
      static_cast<unsigned long>(first),static_cast<unsigned long>(second));
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
  const int64_t readStartedUs = esp_timer_get_time();
  const auto withinBudget = [&]() {
    return processed < kMaxBytesPerService &&
           esp_timer_get_time() - readStartedUs < 10000;
  };
  // Cooperative I/O budget. A native message callback cannot be preempted;
  // its duration is measured separately below rather than hidden/reset.
  while (withinBudget() && client->available()) {
    if (receiveStage_ == ReceiveStage::Header) {
      while (receiveHeaderBytes_ < 2 && withinBudget() && client->available()) {
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
          if (!sessionStarted_) bootstrapDiagnostic(2,receiveOpcode_);
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
             withinBudget() && client->available()) {
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
      while (receiveMaskBytes_ < sizeof(receiveMask_) && withinBudget() && client->available()) {
        const int value = client->read();
        if (value < 0) return;
        receiveMask_[receiveMaskBytes_++] = static_cast<uint8_t>(value);
        ++processed;
      }
      if (receiveMaskBytes_ < sizeof(receiveMask_)) return;
      receiveStage_ = ReceiveStage::Payload;
    }

    if (receiveStage_ == ReceiveStage::Payload) {
      while (receivePayloadBytes_ < receiveLength_ && withinBudget()) {
        const int available = client->available();
        if (available <= 0) return;
        uint8_t block[256];
        const size_t amount = min<size_t>(sizeof(block), min<size_t>(available,
            min<size_t>(receiveLength_ - receivePayloadBytes_, kMaxBytesPerService - processed)));
        const int received = client->read(block, amount);
        if (received <= 0) return;
        if (receiveMasked_)
          for (int index = 0; index < received; ++index)
            block[index] ^= receiveMask_[(receivePayloadBytes_ + index) & 3];
        if (!frameBuffer_.concat(reinterpret_cast<const char*>(block), received)) {
          disconnect();
          setState(State::Offline, "Backend frame allocation failed");
          return;
        }
        receivePayloadBytes_ += received;
        processed += received;
      }
      if (receivePayloadBytes_ < receiveLength_) return;
      if (receiveOpcode_ == 0x0) {
        if (frameBuffer_.length()>kMaxFrameBytes-fragmentBuffer_.length() ||
            !fragmentBuffer_.concat(frameBuffer_.c_str(),frameBuffer_.length())) {
          disconnect();
          setState(State::Offline, "Fragmented WebSocket frame too large");
          return;
        }
        if (receiveFin_) {
          handleFrame(fragmentOpcode_,fragmentBuffer_);
          fragmentOpcode_ = 0;
          fragmentBuffer_ = "";
        }
      } else if (receiveOpcode_ == 0x1 && fragmentOpcode_ == 0 &&
                 !receiveFin_) {
        fragmentOpcode_ = receiveOpcode_;
        fire_backend_policy::releaseTextBuffer(fragmentBuffer_);
        fragmentBuffer_=static_cast<String&&>(frameBuffer_);
      } else if (receiveOpcode_ == 0x1 && fragmentOpcode_ != 0) {
        disconnect();
        setState(State::Offline, "Overlapping WebSocket fragments");
        return;
      } else {
        handleFrame(receiveOpcode_,frameBuffer_);
      }
      resetReceiveFrame();
    }
  }
}

void FireBackendClient::handleFrame(uint8_t opcode, String& payload) {
  receiveCallbackActive_=true;
  struct ReceiveLifetime {
    FireBackendClient* owner;
    ~ReceiveLifetime() {owner->receiveCallbackActive_=false;owner->releaseReadBuffers();}
  } lifetime{this}; // Declared first: all message copies/callbacks finish before release.
  const auto* data=reinterpret_cast<const uint8_t*>(payload.c_str());
  const size_t length=payload.length();
  lastReceiveAt_ = millis();
  if (!sessionStarted_) bootstrapDiagnostic(3,opcode,length);
  if (opcode == 0x8) {
    disconnect();
    setState(State::Offline, "Backend closed connection");
  } else if (opcode == 0x9) {
    sendFrame(0xA, data, length);
  } else if (opcode == 0xA) {
    lastPongAt_ = millis();
  } else if (opcode == 0x1 && messageCallback_) {
    if (!fireJsonSafe(reinterpret_cast<const char*>(data), length, kMaxFrameBytes)) {
      if (!sessionStarted_) bootstrapDiagnostic(7,length);
      Serial.printf("FIRE backend rejected_json bytes=%u max_bytes=%u max_tokens=1024\n",unsigned(length),unsigned(kMaxFrameBytes));
      disconnect(); setState(State::Offline, "Invalid backend message"); return;
    }
    // Own the existing allocation throughout callbacks, even if they disconnect
    // and clear the receive members. A fresh move constructor never reuses an
    // older destination allocation (unlike Arduino String move assignment).
    String message(static_cast<String&&>(payload));
    selectionReply_=0;
    const String type = jsonStringField(message, "type");
    const unsigned memoryKind=type=="session_started"?1:type=="session_snapshot"?2:type=="app_catalog"?3:type=="build_jobs"?4:0;
    const bool measure=memoryKind && !(memoryKinds_&(1u<<memoryKind));
    if(measure) {memoryKinds_|=1u<<memoryKind;fireNetMemory(3,memoryKind);}
    if (!sessionStarted_ && type=="error") {
      cJSON* envelope=cJSON_Parse(message.c_str());
      const cJSON* code=cJSON_GetObjectItemCaseSensitive(envelope,"code");
      const bool rejected=sessionAdmission_.reject(sessionStarted_,type.c_str(),
          cJSON_IsString(code)?code->valuestring:nullptr,
          cJSON_IsFalse(cJSON_GetObjectItemCaseSensitive(envelope,"retryable")));
      cJSON_Delete(envelope);
      if (rejected) {
        disconnect();setState(State::Offline,"Backend session rejected");
        messageCallback_(callbackContext_,message);
        return;
      }
    }
    const uint32_t seq = jsonUintField(message, "seq");
    const String startedSession=type=="session_started"?jsonStringField(message,"session_id"):String();
    if (type=="session_started" && fireWsNewSession(startedSession.c_str(),sessionId_.c_str(),resumeSessionId_.c_str())) lastServerSeq_=0;
    if (seq > 0 && lastServerSeq_ > 0 && seq <= lastServerSeq_) {
      if (!sessionStarted_) bootstrapDiagnostic(4,seq,lastServerSeq_);
      return;
    }
    if (seq > 0) lastServerSeq_ = seq;
    if (type == "session_started") {
      const String newSession = jsonStringField(message, "session_id");
      if (newSession.length() > 0) {
        bootstrapDiagnostic(5,seq,newSession!=resumeSessionId_?1:0);
        sessionId_ = newSession;
        resumeSessionId_ = "";
        sessionStarted_ = true;
        if (++connectionEpoch_==0) ++connectionEpoch_;
        developmentContext_=String();
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
        if (++connectionEpoch_==0) ++connectionEpoch_;
        setState(State::Connected, usingReverseTransport_
                                      ? "Backend connected (Reverse TCP)"
                                      : "Backend connected (Direct)");
      }
    }
    observeSession(type,message);
    if(measure) fireNetMemory(4,memoryKind);
    const int64_t callbackStartedUs = esp_timer_get_time();
    messageCallback_(callbackContext_, message);
    if(measure) fireNetMemory(5,memoryKind);
    const int64_t callbackUs = esp_timer_get_time() - callbackStartedUs;
    if (callbackUs >= 10000)
      Serial.printf("FIRE backend callback_us=%lu\n", static_cast<unsigned long>(callbackUs));
  }
}
