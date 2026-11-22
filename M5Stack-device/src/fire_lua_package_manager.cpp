#include "fire_lua_package_manager.h"

#include <esp_system.h>

namespace {
constexpr uint32_t kHeaderTimeoutMs = 5000;
constexpr uint32_t kDataTimeoutMs = 15000;
constexpr size_t kChunkSize = 4096;

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
  status_ = value;
  if (statusCallback_) statusCallback_(callbackContext_, status_);
}

bool FireLuaPackageManager::startDownload(const String& host, uint16_t port,
                                          const String& token, const String& url,
                                          const String& packageId,
                                          const String& installId,
                                          const String& expectedHash,
                                          uint32_t expectedSize) {
  if (busy() || host.length() == 0 || token.length() < 24 || url.length() == 0 ||
      packageId.length() == 0 || expectedHash.length() != 64 || expectedSize == 0)
    return false;
  host_ = host;
  port_ = port == 0 ? 8765 : port;
  token_ = token;
  url_ = url;
  packageId_ = packageId;
  installId_ = installId;
  expectedHash_ = expectedHash;
  expectedSize_ = expectedSize;
  installedPath_ = "";
  received_ = 0;
  contentLength_ = 0;
  headerBuffer_ = "";
  lastDataAt_ = millis();
  mbedtls_sha256_init(&sha256_);
  mbedtls_sha256_starts_ret(&sha256_, 0);
  state_ = State::Connecting;
  emitStatus("Connecting for download");
  return true;
}

void FireLuaPackageManager::service(bool wifiConnected) {
  if (!busy()) return;
  if (!wifiConnected) {
    fail("Wi-Fi disconnected during download");
    return;
  }
  if (state_ == State::Connecting) {
    if (reverseTransport_) reverseClient_ = reverseTransport_->acquire();
    WiFiClient* client = activeClient();
    if (!reverseClient_) {
      if (!client_.connect(host_.c_str(), port_)) {
        fail("Backend download connection failed");
        return;
      }
    }
    client->print("GET " + url_ + " HTTP/1.1\r\nHost: " + host_ + ":" +
                  String(port_) + "\r\nAuthorization: Bearer " + token_ +
                  "\r\nConnection: close\r\n\r\n");
    state_ = State::Headers;
    lastDataAt_ = millis();
    emitStatus("Waiting for package");
    return;
  }
  if (state_ == State::Headers) {
    WiFiClient* client = activeClient();
    while (client->available() && headerBuffer_.length() < 8192)
      headerBuffer_ += static_cast<char>(client->read());
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
    if (!SD.exists("/apps")) SD.mkdir("/apps");
    const String temp = "/apps/.download-" + packageId_ + ".zip";
    if (SD.exists(temp)) SD.remove(temp);
    archive_ = SD.open(temp, FILE_WRITE);
    if (!archive_) {
      fail("Cannot stage package on SD");
      return;
    }
    const String body = headerBuffer_.substring(end + 4);
    for (uint16_t index = 0; index < body.length(); ++index) {
      const uint8_t value = static_cast<uint8_t>(body[index]);
      archive_.write(&value, 1);
      mbedtls_sha256_update_ret(&sha256_, &value, 1);
      ++received_;
    }
    headerBuffer_ = "";
    state_ = State::Downloading;
    emitStatus("Downloading " + String(received_) + "/" + String(contentLength_));
  }
  if (state_ == State::Downloading) {
    WiFiClient* client = activeClient();
    uint8_t buffer[kChunkSize];
    while (client->available() && received_ < contentLength_) {
      const size_t amount = client->read(buffer, min<size_t>(sizeof(buffer), contentLength_ - received_));
      if (amount == 0) break;
      if (archive_.write(buffer, amount) != amount) {
        fail("SD write failed");
        return;
      }
      mbedtls_sha256_update_ret(&sha256_, buffer, amount);
      received_ += amount;
      lastDataAt_ = millis();
    }
    emitStatus("Downloading " + String(received_) + "/" + String(contentLength_));
    if (received_ == contentLength_) {
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
    } else if (millis() - lastDataAt_ > kDataTimeoutMs) {
      fail("Package download timeout");
    }
  }
  if (state_ == State::Verify) finishDownload();
}

void FireLuaPackageManager::finishDownload() {
  state_ = State::Idle;
  uint8_t digest[32] = {};
  mbedtls_sha256_finish_ret(&sha256_, digest);
  const String archiveHash = hexDigest(digest, sizeof(digest));
  const String path = "/apps/.download-" + packageId_ + ".zip";
  String reason;
  bool ok = archiveHash.equalsIgnoreCase(expectedHash_);
  if (ok) {
    File archive = SD.open(path, FILE_READ);
    ok = archive && installArchive(archive, const_cast<String&>(archiveHash), reason);
    if (archive) archive.close();
  } else {
    reason = "Archive SHA256 mismatch";
  }
  if (SD.exists(path)) SD.remove(path);
  mbedtls_sha256_free(&sha256_);
  if (resultCallback_) {
    resultCallback_(callbackContext_, ok, packageId_, archiveHash,
                    ok ? String("installed") : reason);
  }
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
  if (SD.exists(path)) SD.remove(path);
  mbedtls_sha256_free(&sha256_);
  state_ = State::Idle;
  status_ = reason;
  if (resultCallback_) resultCallback_(callbackContext_, false, packageId_, "", reason);
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

bool FireLuaPackageManager::installArchive(File& archive, String& archiveHash,
                                            String& reason) {
  (void)archiveHash;
  String appId;
  if (!extractStoredZip(archive, appId, reason)) return false;
  return appId.length() > 0;
}

bool FireLuaPackageManager::extractStoredZip(File& archive, String& appId,
                                             String& reason) {
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
  while (archive.available()) {
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
    String name;
    for (uint16_t index = 0; index < nameLength; ++index) name += static_cast<char>(archive.read());
    archive.seek(archive.position() + extraLength);
    if (!validZipPath(name) || (flags & 0x08) || method != 0 || compressed != uncompressed || compressed > 100000) {
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
    if (appId.length() == 0) appId = id;
    if (id != appId) {
      reason = "Multiple app IDs in package";
      return false;
    }
    const String relative = name.substring(secondSlash + 1);
    String destination;
    if (relative == "main.lua") {
      destination = staging + "/main.lua";
      mainFound = true;
    } else if (relative == "manifest.json") {
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
  if (manifestField(manifest, "id") != appId ||
      manifestField(manifest, "api_version") != "fire-lua-0.1" ||
      !manifestField(manifest, "checksum").equalsIgnoreCase(
          hexDigest(payloadDigest, sizeof(payloadDigest)))) {
    reason = "Manifest or Lua checksum mismatch";
    return false;
  }
  const String finalPath = "/apps/" + appId;
  const String previousPath = "/apps/.previous-" + appId;
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
        reason = "Cannot prepare appdata";
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
  if (!SD.rename(staging, finalPath)) {
    if (oldAppDataMoved) SD.rename(staging + "/appdata", previousPath + "/appdata");
    if (oldVersionMoved) SD.rename(previousPath, finalPath);
    reason = "Cannot activate staged app";
    return false;
  }
  installedPath_ = finalPath + "/main.lua";
  return true;
}
