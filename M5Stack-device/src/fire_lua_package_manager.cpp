#include "fire_lua_package_manager.h"
#include "fire_lua_runtime.h"

#include <esp_system.h>
#include <WiFi.h>
#include <time.h>
#include <esp_heap_caps.h>
#include "fire_worker_diagnostics.h"

namespace {
constexpr uint32_t kHeaderTimeoutMs = 5000;
constexpr uint32_t kDataTimeoutMs = 15000;
constexpr size_t kChunkSize = 4096;
struct PackageHash {
  mbedtls_sha256_context* context;
  int update(const uint8_t* bytes,size_t length) {return mbedtls_sha256_update_ret(context,bytes,length);}
};

uint32_t crc32Update(uint32_t crc, const uint8_t* data, size_t length) {
  while (length-- > 0) {
    crc ^= *data++;
    for (uint8_t bit = 0; bit < 8; ++bit)
      crc = (crc >> 1) ^ (0xEDB88320UL & (-(crc & 1)));
  }
  return crc;
}

String manifestField(const String& json, const char* key) {
  const String marker = String("\"") + key + "\"";
  const int at = json.indexOf(marker);
  if (at < 0) return "";
  const int colon = json.indexOf(':', at + marker.length());
  const int quote = json.indexOf('"', colon + 1);
  const int end = json.indexOf('"', quote + 1);
  return quote >= 0 && end > quote ? json.substring(quote + 1, end) : "";
}

int manifestIntField(const String& json, const char* key, int fallback) {
  const String marker = String("\"") + key + "\"";
  const int keyAt = json.indexOf(marker);
  if (keyAt < 0) return fallback;
  const int colon = json.indexOf(':', keyAt + marker.length());
  if (colon < 0) return fallback;
  int start = colon + 1;
  while (start < json.length() &&
         (json[start] == ' ' || json[start] == '\t' || json[start] == '\r' ||
          json[start] == '\n')) {
    ++start;
  }
  return json.substring(start).toInt();
}

bool removeTree(const String& path) {
  File entry = SD.open(path);
  if (!entry) return true;
  if (!entry.isDirectory()) {
    entry.close();
    return SD.remove(path);
  }
  File child = entry.openNextFile();
  while (child) {
    String childPath = child.name();
    if (!childPath.startsWith("/")) childPath = path + "/" + childPath;
    child.close();
    if (!removeTree(childPath)) {
      entry.close();
      return false;
    }
    child = entry.openNextFile();
  }
  entry.close();
  return SD.rmdir(path);
}
}

void FireLuaPackageManager::setCallbacks(void* context, StatusCallback status,
                                          ResultCallback result) {
  callbackContext_ = context;
  statusCallback_ = status;
  resultCallback_ = result;
}

void FireLuaPackageManager::emitStatus(const String& value) {
  io_.status(value);
}

bool FireLuaPackageManager::startDownload(const String& host, uint16_t port,
                                          const String& token, const String& url,
                                          const String& packageId,
                                          const String& installId,
                                          const String& expectedHash,
                                          uint32_t expectedSize,const String& projectId,const String& sessionId,const String& bootId,uint32_t expiresAt) {
  if (busy() || !fireNetworkEndpointValid(host) || token.length() < 24 || !fireRelativePath(url) ||
      packageId.length() == 0 || packageId.length() > 96 || expectedHash.length() != 64 || expectedSize == 0 || expectedSize > 1048576)
    return false;
  if(!fire_lua_install::id(projectId.c_str(),true) || !fire_package_delivery::wireId(sessionId.c_str()) ||
      !fire_package_delivery::wireId(bootId.c_str()) || !fire_package_delivery::wireId(installId.c_str())) return false;
  if (matchesInstall(packageId,installId,expectedHash,expectedSize)) return true; // already executed; never replay bytes

  for (size_t i = 0; i < packageId.length(); ++i)
    if (!(isalnum(static_cast<unsigned char>(packageId[i])) || packageId[i] == '-' || packageId[i] == '_')) return false;
  for (size_t i = 0; i < expectedHash.length(); ++i) if (!isxdigit(static_cast<unsigned char>(expectedHash[i]))) return false;
  sessionId_=sessionId;bootId_=bootId;expiresAt_=expiresAt;
  receiptEvent_="ir-"+String(esp_random(),HEX)+"-"+String(esp_random(),HEX);
  receiptFrozen_=false;preconnectedTls_=false;cancelled_=false;io_.completed=false;
  host_ = fireNetworkHost(host);
  secureEndpoint_ = fireNetworkTls(host, port);buffered_=secureEndpoint_;streamVerified_=storageStarted_=ownsArchive_=false;
  client_.secure(secureEndpoint_);
  port_ = port == 0 ? (secureEndpoint_ ? 443 : 8765) : port;
  token_ = token;
  url_ = url;
  packageId_ = packageId;
  installId_ = installId;
  projectId_ = projectId;
  expectedHash_ = expectedHash;
  expectedSize_ = expectedSize;
  reverseGeneration_ = reverseTransport_ ? reverseTransport_->generation() : 0;
  installedPath_ = "";
  received_ = 0;
  progress_=0;
  contentLength_ = 0;
  headerBuffer_ = "";
  lastDataAt_ = millis();
  delivery_.begin(millis(),secureEndpoint_);
  emitStatus("Waiting for download resources");
  return true;
}

void FireLuaPackageManager::freeHash() {if (shaInitialized_) {mbedtls_sha256_free(&sha256_);shaInitialized_=false;}}
void FireLuaPackageManager::freeStaging() {
  staging_.attach(nullptr,0);if(stagedBytes_) {heap_caps_free(stagedBytes_);stagedBytes_=nullptr;}
}
bool FireLuaPackageManager::prepareStaging() {
  const uint32_t caps=MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT;
  if (!FireFirmwareStaging::fits(expectedSize_,1048576,heap_caps_get_free_size(caps),heap_caps_get_largest_free_block(caps),512u*1024u)) return false;
  stagedBytes_=static_cast<uint8_t*>(heap_caps_malloc(expectedSize_,caps));if(!stagedBytes_) return false;
  staging_.attach(stagedBytes_,expectedSize_);mbedtls_sha256_init(&sha256_);shaInitialized_=true;
  if(mbedtls_sha256_starts_ret(&sha256_,0)) {freeHash();freeStaging();return false;}
  state_=State::Connecting;return true;
}
bool FireLuaPackageManager::cancelled() const {return cancelled_ || time(nullptr)>=expiresAt_;}
void FireLuaPackageManager::queuedFailure(const String& reason) {
  client_.stop();freeHash();freeStaging(); // No worker owns these on a queued failure.
  state_=State::Idle;
  io_.result(false,false,packageId_,String(),reason,installId_);
  delivery_.phase=fire_package_delivery::Phase::Cleanup;
  emitStatus(reason);
}
String FireLuaPackageManager::connectionFailure() const {
  fire_backend_policy::ConnectFailure failure;
  String reason="Backend download connection failed";
  if (client_.lastConnectFailure(failure)) reason+=" (phase="+String(failure.phase>>8)+",tls="+String(failure.phase&255)+
      ",err="+String(failure.error)+",ms="+String(failure.elapsedMs)+")";
  return reason;
}
void FireLuaPackageManager::preconnect() {
  // This call only creates/polls the existing Async worker; UI never does TLS.
  client_.setTimeout(1200);
  if (!client_.connect(host_.c_str(),port_,1200) &&
      fire_backend_policy::progress(false,client_.connecting(),client_.stopping(),client_.running())==fire_backend_policy::Progress::Failed)
    queuedFailure(connectionFailure());
}
void FireLuaPackageManager::startWorker() {
  if(buffered_) {
    if (!staging_.readyForSd(client_.running()) || !streamVerified_) {queuedFailure("Verified download staging unavailable");return;}
    state_=State::Verify;
  } else {
    mbedtls_sha256_init(&sha256_);shaInitialized_=true;mbedtls_sha256_starts_ret(&sha256_,0);
    lastDataAt_=millis();state_=State::Connecting;
  }
  storageStarted_=true;io_.running=true;
  if (xTaskCreate(task,"fire-package",16384,this,1,nullptr)!=pdPASS) {
    io_.running=false;queuedFailure("Package worker allocation failed");
  }
}

void FireLuaPackageManager::service(bool wifiConnected,bool allowed,bool busyNetwork,bool socketsQuiet,bool unexpired) {
  io_.wifi=wifiConnected;
  if (io_.poll(status_) && statusCallback_) statusCallback_(callbackContext_,status_);
  const auto action=delivery_.poll(millis(),allowed && wifiConnected && unexpired && !cancelled_.load(),busyNetwork,socketsQuiet,
      io_.running,client_.running(),io_.completed,client_.ready(),streamVerified_);
  if (action==fire_package_delivery::Action::Connect) {
    if (!prepareStaging()) queuedFailure("Not enough PSRAM for download staging");
    else {emitStatus("Connecting for download");preconnect();}
  }
  else if (action==fire_package_delivery::Action::Stream) {preconnectedTls_=true;lastDataAt_=millis();serviceWorker(wifiConnected);}
  else if (action==fire_package_delivery::Action::Start) startWorker();
  else if (action==fire_package_delivery::Action::Cancel || action==fire_package_delivery::Action::Busy || action==fire_package_delivery::Action::Timeout) {
    cancelled_=true;client_.stop();
    if (!io_.running && !io_.completed) queuedFailure(action==fire_package_delivery::Action::Busy?"Installer network busy":action==fire_package_delivery::Action::Timeout?"Backend download connection timeout":"Download cancelled or expired");
  } else if (action==fire_package_delivery::Action::Notify) {
    // Callback can validate/amend this sole result before its immutable receipt.
    if (resultCallback_) resultCallback_(callbackContext_,io_.ok,io_.first,io_.completionId,io_.second,io_.message);
    receiptFrozen_=true;
  } else if (delivery_.phase==fire_package_delivery::Phase::Connecting) preconnect();
  else if (delivery_.phase==fire_package_delivery::Phase::Streaming) serviceWorker(wifiConnected);
}
void FireLuaPackageManager::task(void* context) {
  auto* self = static_cast<FireLuaPackageManager*>(context);uint32_t began=0;
  while (self->state_ != State::Idle) { self->serviceWorker(WiFi.isConnected()); delay(2); }
  fireMeasureWorker("package",began);
  self->io_.running.store(false, std::memory_order_release); vTaskDelete(nullptr);
}
void FireLuaPackageManager::serviceWorker(bool wifiConnected) {
  if (state_ == State::Idle) return;
  if (cancelled()) {fail("Download cancelled or expired");return;}
  if (reverseClient_ && reverseTransport_ && reverseTransport_->cancelled(reverseClient_)) { fail("Reverse connection cancelled"); return; }
  if (!wifiConnected) {
    fail("Wi-Fi disconnected during download");
    return;
  }
  if (state_ == State::Connecting) {
    if (millis() - lastDataAt_ > 18000) {
      fail("Backend download connection timeout");
      return;
    }
    if (!secureEndpoint_ && reverseTransport_ && !reverseClient_) reverseClient_ = reverseTransport_->acquire(reverseGeneration_);
    WiFiClient* client = activeClient();
    if (preconnectedTls_) {
      // Never restart TLS with the 16KiB package stack resident. A drop is a
      // controlled failed command, not another connection attempt.
      if (!fire_package_delivery::handoffReady(preconnectedTls_,client_.ready())) {fail("Download connection lost before request");return;}
    } else if (!reverseClient_) {
      client_.setTimeout(1200);
      if (!client_.connect(host_.c_str(),port_,1200)) {
        if (fire_backend_policy::progress(false,client_.connecting(),client_.stopping(),client_.running())==fire_backend_policy::Progress::Waiting) return;
        fail(connectionFailure());return;
      }
    }
    const String request = "GET " + url_ + " HTTP/1.1\r\nHost: " + host_ + ":" +
                  String(port_) + "\r\nAuthorization: Bearer " + token_ +
                  "\r\nConnection: close\r\n\r\n";
    if (client->print(request) != request.length()) { fail("Cannot send complete package request"); return; }
    state_ = State::Headers;
    lastDataAt_ = millis();
    emitStatus("Waiting for package");
    return;
  }
  if (state_ == State::Headers) {
    WiFiClient* client = activeClient();
    size_t headerBudget = 2048;
    const int64_t headerAt=esp_timer_get_time();
    while (client->available() && headerBuffer_.length() < 8192 && headerBudget-- && esp_timer_get_time()-headerAt<2000) {
      headerBuffer_ += static_cast<char>(client->read());
      if (headerBuffer_.endsWith("\r\n\r\n")) break; // Body remains in the binary receive queue.
    }
    const int end = headerBuffer_.indexOf("\r\n\r\n");
    if (end < 0) {
      if (millis() - lastDataAt_ > kHeaderTimeoutMs) fail("Download headers timeout");
      return;
    }
    const String headers = headerBuffer_.substring(0, end);
    if (!headers.startsWith("HTTP/1.1 200") && !headers.startsWith("HTTP/1.1 206")) {
      fail("Backend rejected package download");
      return;
    }
    String lowerHeaders = headers;
    lowerHeaders.toLowerCase();
    const int lengthAt = lowerHeaders.indexOf("content-length:");
    if (lengthAt >= 0)
      contentLength_ = headers.substring(lengthAt + 15).toInt();
    if (contentLength_ == 0 || contentLength_ > expectedSize_ ||
        (expectedSize_ > 0 && contentLength_ != expectedSize_)) {
      fail("Package size mismatch");
      return;
    }
    if (!buffered_) {
    if (!SD.exists("/apps")) SD.mkdir("/apps");
    const String temp = "/apps/.download-" + packageId_ + ".zip";
    if (SD.exists(temp)) SD.remove(temp);
    archive_ = SD.open(temp, FILE_WRITE);
    if (!archive_) {
      fail("Cannot stage package on SD");
      return;
    }
      ownsArchive_=true;
    }
    const String body = headerBuffer_.substring(end + 4);
    if (buffered_) {
      PackageHash hash{&sha256_};
      if(body.length() && !staging_.append(hash,reinterpret_cast<const uint8_t*>(body.c_str()),body.length())) {fail("Package staging bounds/hash failure");return;}
      received_=staging_.received();
    } else {
    for (uint16_t index = 0; index < body.length(); ++index) {
      const uint8_t value = static_cast<uint8_t>(body[index]);
      if (archive_.write(&value, 1) != 1) {
        fail("SD write failed");
        return;
      }
      mbedtls_sha256_update_ret(&sha256_, &value, 1);
      ++received_;
    }
    }
    headerBuffer_ = "";
    state_ = State::Downloading;
    progress_=contentLength_?min<uint32_t>(100,uint64_t(received_)*100/contentLength_):0;
    emitStatus("Downloading " + String(received_) + "/" + String(contentLength_));
  }
  if (state_ == State::Downloading) {
    readDownloadBody();if(state_==State::Idle) return;
    progress_=contentLength_?min<uint32_t>(100,uint64_t(received_)*100/contentLength_):0;
    emitStatus("Downloading " + String(received_) + "/" + String(contentLength_));
    if (received_ == contentLength_) {
      if(buffered_) finishSecureStream();
      else {
      archive_.flush();
      archive_.close();
      if (reverseClient_ && reverseTransport_) {
        reverseTransport_->release(reverseClient_);
        reverseClient_ = nullptr;
      } else {
        client_.stop();
      }
      state_ = State::Verify;
      emitStatus("Verifying package");
      }
    } else if (millis() - lastDataAt_ > kDataTimeoutMs) {
      fail("Package download timeout");
    }
  }
  if (state_ == State::Verify && (!buffered_ || storageStarted_)) finishDownload();
}

void FireLuaPackageManager::readLegacyBody() {
  WiFiClient* client=activeClient();
    uint8_t buffer[kChunkSize];
    size_t budget = 4096;
    while (client->available() && received_ < contentLength_ && budget > 0) {
      const size_t amount = client->read(buffer, min<size_t>(sizeof(buffer), contentLength_ - received_));
      if (amount == 0) break;
      if (archive_.write(buffer, amount) != amount) {
        fail("SD write failed");
        return;
      }
      mbedtls_sha256_update_ret(&sha256_, buffer, amount);
      received_ += amount;
      budget -= min<size_t>(budget, amount);
      lastDataAt_ = millis();
    }
 }
void FireLuaPackageManager::readDownloadBody() {
  if (!buffered_) {readLegacyBody();return;}
  uint8_t buffer[256];size_t budget=4096;const int64_t began=esp_timer_get_time();PackageHash hash{&sha256_};
  while(client_.available() && received_<contentLength_ && budget && esp_timer_get_time()-began<2000) {
    const size_t amount=client_.read(buffer,min<size_t>(sizeof(buffer),min<size_t>(budget,contentLength_-received_)));
    if(!amount) break;
    if(!staging_.append(hash,buffer,amount)) {fail("Package staging bounds/hash failure");return;}
    received_=staging_.received();budget-=amount;lastDataAt_=millis();
  }
}
void FireLuaPackageManager::finishSecureStream() {
  uint8_t digest[32]={};const bool hashed=mbedtls_sha256_finish_ret(&sha256_,digest)==0;freeHash();
  io_.second=hexDigest(digest,sizeof(digest));
  if(!staging_.verify(hashed && io_.second.equalsIgnoreCase(expectedHash_))) {fail("Archive SHA256 mismatch");return;}
  client_.stop();streamVerified_=true;state_=State::Verify;emitStatus("Preparing SD installation");
}

bool FireLuaPackageManager::writeStagedArchive(String& reason) {
  if(!staging_.readyForSd(client_.running())) {reason="TLS cleanup not complete";return false;}
  if(!SD.exists("/apps") && !SD.mkdir("/apps")) {reason="Cannot create app folder";return false;}
  const String path="/apps/.download-"+packageId_+".zip";
  if(SD.exists(path) && !SD.remove(path)) {reason="Cannot clear staged archive";return false;}
  archive_=SD.open(path,FILE_WRITE);if(!archive_) {reason="Cannot stage package on SD";return false;}ownsArchive_=true;
  for(uint32_t at=0;at<expectedSize_;) {
    if(cancelled()) {reason="Download cancelled or expired";archive_.close();return false;}
    const size_t amount=min<uint32_t>(4096,expectedSize_-at);
    if(archive_.write(stagedBytes_+at,amount)!=amount) {reason="SD write failed";archive_.close();return false;}
    at+=amount;
  }
  archive_.flush();archive_.close();freeStaging();return true;
}

void FireLuaPackageManager::finishDownload() {
  state_ = State::Idle;
  uint8_t digest[32] = {};
  if(!buffered_) mbedtls_sha256_finish_ret(&sha256_, digest);
  const String archiveHash = buffered_?io_.second:hexDigest(digest, sizeof(digest));
  const String path = "/apps/.download-" + packageId_ + ".zip";
  String reason;
  bool ok = archiveHash.equalsIgnoreCase(expectedHash_);
  if (!ok) reason="Archive SHA256 mismatch";
  if(ok && buffered_) ok=writeStagedArchive(reason);
  if (ok) {
    File archive = SD.open(path, FILE_READ);
    ok = archive && archive.size()==expectedSize_ && installArchive(archive, archiveHash, reason);
    if (archive) archive.close();
  }
  if (!ok && !reason.length()) reason="Cannot read staged archive";
  if (SD.exists(path)) SD.remove(path);ownsArchive_=false;
  freeHash();freeStaging();
  io_.result(false, ok, packageId_, archiveHash, ok ? String("installed") : reason,installId_);
  emitStatus(ok ? "Package installed" : reason);
}

void FireLuaPackageManager::fail(const String& reason) {
  if (archive_) archive_.close();
  if (reverseClient_ && reverseTransport_) {
    reverseTransport_->release(reverseClient_);
    reverseClient_ = nullptr;
  } else {
    client_.stop();
  }
  const String path = "/apps/.download-" + packageId_ + ".zip";
  if (ownsArchive_ && SD.exists(path)) SD.remove(path);ownsArchive_=false;
  freeHash();freeStaging();
  state_ = State::Idle;
  emitStatus(reason);
  io_.result(false, false, packageId_, "", reason,installId_);
  if(!io_.running) delivery_.phase=fire_package_delivery::Phase::Cleanup;
}

uint16_t FireLuaPackageManager::read16(File& file) {
  const uint16_t a = file.read();
  const uint16_t b = file.read();
  return a | (b << 8);
}

uint32_t FireLuaPackageManager::read32(File& file) {
  uint32_t value = 0;
  for (uint8_t index = 0; index < 4; ++index) value |= static_cast<uint32_t>(file.read()) << (index * 8);
  return value;
}

bool FireLuaPackageManager::validZipPath(const String& path) {
  return path.startsWith("apps/") && !path.startsWith("/") &&
         path.indexOf("..") < 0 && path.indexOf('\\') < 0;
}

String FireLuaPackageManager::hexDigest(const uint8_t* digest, size_t length) {
  const char* digits = "0123456789abcdef";
  String result;
  result.reserve(length * 2);
  for (size_t index = 0; index < length; ++index) {
    result += digits[digest[index] >> 4];
    result += digits[digest[index] & 0x0F];
  }
  return result;
}

bool FireLuaPackageManager::installArchive(File& archive, const String& archiveHash,
                                            String& reason) {
  String appId;
  if (!extractStoredZip(archive, appId,archiveHash,reason)) return false;
  return appId.length() > 0;
}

bool FireLuaPackageManager::extractStoredZip(File& archive, String& appId,
                                             const String& archiveHash,String& reason) {
  const String staging = "/apps/.staging-" + packageId_;
  if (SD.exists(staging)) {
    if (!removeTree(staging)) {
      reason = "Cannot clear stale staging folder";
      return false;
    }
  }
  if (!SD.mkdir(staging)) {
    reason = "Cannot create staging folder";
    return false;
  }
  bool mainFound = false;
  bool manifestFound = false;
  uint8_t entryCount = 0;
  while (archive.available()) {
    if (++entryCount > 24) {
      reason = "Too many ZIP entries";
      return false;
    }
    const uint32_t signature = read32(archive);
    if (signature != 0x04034b50) break;
    archive.seek(archive.position() + 2);  // version needed
    const uint16_t flags = read16(archive);
    const uint16_t method = read16(archive);
    archive.seek(archive.position() + 4);  // modification time/date
    const uint32_t storedCrc = read32(archive);
    const uint32_t compressed = read32(archive);
    const uint32_t uncompressed = read32(archive);
    const uint16_t nameLength = read16(archive);
    const uint16_t extraLength = read16(archive);
    if (!nameLength || nameLength > 160 || static_cast<uint64_t>(archive.position()) + nameLength + extraLength + compressed > archive.size()) {
      reason = "Invalid ZIP entry bounds"; return false;
    }
    String name;
    for (uint16_t index = 0; index < nameLength; ++index) name += static_cast<char>(archive.read());
    archive.seek(archive.position() + extraLength);
    if (!validZipPath(name) || (flags & ~0x0800u) || method != 0 ||
        compressed != uncompressed || compressed > 100000) {
      reason = "Unsupported or unsafe ZIP entry";
      return false;
    }
    const int firstSlash = name.indexOf('/');
    const int secondSlash = name.indexOf('/', firstSlash + 1);
    if (firstSlash < 0 || secondSlash < 0) {
      reason = "Invalid app package path";
      return false;
    }
    const String id = name.substring(firstSlash + 1, secondSlash);
    if(!fire_lua_install::id(id.c_str())) {reason="Invalid app ID";return false;}
    if (appId.length() == 0) appId = id;
    if (id != appId) {
      reason = "Multiple app IDs in package";
      return false;
    }
    const String relative = name.substring(secondSlash + 1);
    String destination;
    if (relative == "main.lua") {
      if (mainFound) {
        reason = "Duplicate main.lua entry";
        return false;
      }
      destination = staging + "/main.lua";
      mainFound = true;
    } else if (relative == "manifest.json") {
      if (manifestFound) {
        reason = "Duplicate manifest.json entry";
        return false;
      }
      destination = staging + "/manifest.json";
      manifestFound = true;
    } else if (relative == "assets/") {
      SD.mkdir(staging + "/assets");
    } else if (relative == "appdata/") {
      SD.mkdir(staging + "/appdata");
    } else {
      reason = "Unexpected package entry";
      return false;
    }
    uint32_t entryCrc = 0xFFFFFFFFUL;
    if (destination.length() > 0) {
      File output = SD.open(destination, FILE_WRITE);
      if (!output) {
        reason = "Cannot create staged file";
        return false;
      }
      uint8_t buffer[256];
      uint32_t remaining = compressed;
      while (remaining > 0) {
        if (cancelled()) {output.close();reason="Download cancelled or expired";return false;}
        const size_t amount = archive.read(buffer, min<uint32_t>(sizeof(buffer), remaining));
        if (amount == 0 || output.write(buffer, amount) != amount) {
          output.close();
          reason = "Cannot extract package";
          return false;
        }
        entryCrc = crc32Update(entryCrc, buffer, amount);
        remaining -= amount;
      }
      output.close();
    } else {
      archive.seek(archive.position() + compressed);
    }
    if ((entryCrc ^ 0xFFFFFFFFUL) != storedCrc) {
      reason = "ZIP CRC mismatch";
      return false;
    }
  }
  if (!mainFound || !manifestFound || appId.length() == 0) {
    reason = "Package missing manifest or main.lua";
    return false;
  }
  File manifestFile = SD.open(staging + "/manifest.json", FILE_READ);
  File mainFile = SD.open(staging + "/main.lua", FILE_READ);
  if (!manifestFile || !mainFile || manifestFile.size() > 8192 ||
      mainFile.size() > 100000) {
    reason = "Invalid staged app files";
    if (manifestFile) manifestFile.close();
    if (mainFile) mainFile.close();
    return false;
  }
  String manifest;
  while (manifestFile.available()) manifest += static_cast<char>(manifestFile.read());
  manifestFile.close();
  mbedtls_sha256_context payloadSha;
  mbedtls_sha256_init(&payloadSha);
  mbedtls_sha256_starts_ret(&payloadSha, 0);
  uint8_t buffer[256];
  while (mainFile.available()) {
    const size_t amount = mainFile.read(buffer, sizeof(buffer));
    if (amount == 0) break;
    mbedtls_sha256_update_ret(&payloadSha, buffer, amount);
  }
  mainFile.close();
  uint8_t payloadDigest[32] = {};
  mbedtls_sha256_finish_ret(&payloadSha, payloadDigest);
  mbedtls_sha256_free(&payloadSha);
  const int maxMemory =
      manifestIntField(manifest, "max_memory", FireLuaRuntime::kMaxMemoryBytes);
  const int maxRuntime = manifestIntField(
      manifest, "max_runtime_ms", FireLuaRuntime::kDefaultRuntimeMs);
  const String manifestApi = manifestField(manifest, "api_version");
  const String manifestContract = manifestField(manifest, "api_contract");
  if (manifestField(manifest, "id") != appId ||
      !FireLuaRuntime::supportsManifestApi(manifestApi.c_str(), manifestApi.length(),
                                          manifestContract.c_str(), manifestContract.length()) ||
      !manifestField(manifest, "checksum").equalsIgnoreCase(
          hexDigest(payloadDigest, sizeof(payloadDigest)))) {
    reason = "Manifest or Lua checksum mismatch";
    return false;
  }
  if (maxMemory < 65536 ||
      maxMemory > static_cast<int>(FireLuaRuntime::kMaxMemoryBytes) ||
      maxRuntime < 0 ||
      maxRuntime > static_cast<int>(FireLuaRuntime::kMaxRuntimeMs)) {
    reason = "Manifest resource limits invalid";
    return false;
  }
  const String finalPath = "/apps/" + appId;
  const String previousPath = "/apps/.previous-" + appId;
  fire_lua_install::Identity identity;
  strlcpy(identity.app,appId.c_str(),sizeof(identity.app));
  strlcpy(identity.package,packageId_.c_str(),sizeof(identity.package));
  strlcpy(identity.project,projectId_.c_str(),sizeof(identity.project));
  const String sourceHash=hexDigest(payloadDigest,sizeof(payloadDigest));
  strlcpy(identity.source,sourceHash.c_str(),sizeof(identity.source));
  strlcpy(identity.archive,archiveHash.c_str(),sizeof(identity.archive));
  // A failed write/readback leaves the current and previous app untouched.
  if(!fire_lua_install::writeVerified(SD,(staging+"/"+fire_lua_install::kFilename).c_str(),identity)) {
    reason="metadata_error";return false;
  }
  if (cancelled()) {reason="Download cancelled or expired";return false;}
  bool oldVersionMoved = false;
  bool oldAppDataMoved = false;
  if (SD.exists(previousPath) && !removeTree(previousPath)) {
    reason = "Cannot clear previous app version";
    return false;
  }
  if (SD.exists(finalPath)) {
    if (!SD.rename(finalPath, previousPath)) {
      reason = "Cannot preserve previous app version";
      return false;
    }
    oldVersionMoved = true;
    const String oldAppData = previousPath + "/appdata";
    const String newAppData = staging + "/appdata";
    if (SD.exists(oldAppData)) {
      if (SD.exists(newAppData) && !removeTree(newAppData)) {
        // The old version is the recovery copy. Never delete it because a
        // failure while preparing new appdata is being handled.
        const bool restored=SD.rename(previousPath,finalPath);
        reason = restored?"Cannot prepare appdata":"Cannot prepare appdata; previous version retained";
        return false;
      }
      if (!SD.rename(oldAppData, newAppData)) {
        SD.rename(previousPath, finalPath);
        reason = "Cannot preserve appdata";
        return false;
      }
      oldAppDataMoved = true;
    }
  }
  if (cancelled() || !SD.rename(staging, finalPath)) {
    if (oldAppDataMoved) SD.rename(staging + "/appdata", previousPath + "/appdata");
    if (oldVersionMoved) SD.rename(previousPath, finalPath);
    reason = "Cannot activate staged app";
    return false;
  }
  installedPath_ = finalPath + "/main.lua";
  return true;
}
