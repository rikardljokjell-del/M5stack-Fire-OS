#include "fire_github_firmware.h"

namespace {
constexpr char kGithubHost[] = "raw.githubusercontent.com";
constexpr char kGithubManifestPath[] =
    "/rikardljokjell-del/M5stack-Fire-OS/main/firmware/index.json";
constexpr char kGithubFirmwarePrefix[] =
    "/rikardljokjell-del/M5stack-Fire-OS/main/firmware/";

// GitHub currently chains through one of these long-lived public roots. Keep
// certificate verification enabled; never use setInsecure() for firmware.
constexpr char kGithubRootCertificates[] =
    "-----BEGIN CERTIFICATE-----\n"
    "MIIDjjCCAnagAwIBAgIQAzrx5qcRqaC7KGSxHQn65TANBgkqhkiG9w0BAQsFADBh\n"
    "MQswCQYDVQQGEwJVUzEVMBMGA1UEChMMRGlnaUNlcnQgSW5jMRkwFwYDVQQLExB3\n"
    "d3cuZGlnaWNlcnQuY29tMSAwHgYDVQQDExdEaWdpQ2VydCBHbG9iYWwgUm9vdCBH\n"
    "MjAeFw0xMzA4MDExMjAwMDBaFw0zODAxMTUxMjAwMDBaMGExCzAJBgNVBAYTAlVT\n"
    "MRUwEwYDVQQKEwxEaWdpQ2VydCBJbmMxGTAXBgNVBAsTEHd3dy5kaWdpY2VydC5j\n"
    "b20xIDAeBgNVBAMTF0RpZ2lDZXJ0IEdsb2JhbCBSb290IEcyMIIBIjANBgkqhkiG\n"
    "9w0BAQEFAAOCAQ8AMIIBCgKCAQEAuzfNNNx7a8myaJCtSnX/RrohCgiN9RlUyfu\n"
    "I2/Ou8jqJkTx65qsGGmvPrC3oXgkkRLpimn7Wo6h+4FR1IAWsULecYxpsMNzaHxmx\n"
    "1x7e/dfgy5SDN67sH0NO3Xss0r0upS/kqbitOtSZpLYl6ZtrAGCSYP9PIUkY92eQ\n"
    "q2EGnI/yuum06ZIya7XzV+hdG82MHauVBJVJ8zUtluNJbd134/tJS7SsVQepj5Wz\n"
    "tCO7TG1F8PapspUwtP1MVYwnSlcUfIKdzXOS0xZKBgyMUNGPHgm+F6HmIcr9g+UQ\n"
    "vIOlCsRnKPZzFBQ9RnbDhxSJITRNrw9FDKZJobq7nMWxM4MphQIDAQABo0IwQD\n"
    "APBgNVHRMBAf8EBTADAQH/MA4GA1UdDwEB/wQEAwIBhjAdBgNVHQ4EFgQUTiJUI\n"
    "BiV5uNu5g/6+rkS7QYXjzkwDQYJKoZIhvcNAQELBQADggEBAGBnKJRvDkhj6zHd\n"
    "6mcY1l9PMWLSn/pvtsrF9+wX3N3KjITOYFnQoQj1VvNeyIv/iPsGEMNKSuIEyExt\n"
    "v4NeF22d+mQrvHRAiGfzZ0JFrabA0UWTW98kndth/Jsw1HKj2ZL7tcu7XUIOGZX1\n"
    "NGFdtom/DzMNU+MeKNhJ7jitralj41E6Vf8PlwUHBHQRFXGU7Aj64GxJUTFy8bJZ9\n"
    "18rGOmaFvE7FBcf6IKshPECBV1/MUReXgRPTqh5Uykw7+U0b6LJ/iyK5S9kJRaTe\n"
    "pLiaWN0bfVKfjllDiIGknibVb63dDcY3fe0Dkhvld1927jyNxF1WW6LZZm6zNTfl\n"
    "MrY=\n"
    "-----END CERTIFICATE-----\n";

bool isHex(char value) {
  return (value >= '0' && value <= '9') ||
         (value >= 'a' && value <= 'f') ||
         (value >= 'A' && value <= 'F');
}
}  // namespace

void FireGithubFirmwareManager::setCallbacks(void* context,
                                               StatusCallback status,
                                               ResultCallback result) {
  callbackContext_ = context;
  statusCallback_ = status;
  resultCallback_ = result;
}

void FireGithubFirmwareManager::emitStatus(const String& value) {
  status_ = value;
  if (statusCallback_) statusCallback_(callbackContext_, status_);
}

void FireGithubFirmwareManager::emitResult(bool manifest, bool ok,
                                            const String& message) {
  if (resultCallback_) resultCallback_(callbackContext_, manifest, ok, message);
}

bool FireGithubFirmwareManager::startManifest() {
  if (busy()) return false;
  manifestMode_ = true;
  requestPath_ = kGithubManifestPath;
  headerBuffer_ = "";
  manifestBody_ = "";
  startedAt_ = millis();
  lastDataAt_ = startedAt_;
  state_ = State::Connecting;
  emitStatus("GitHub: connecting");
  return true;
}

bool FireGithubFirmwareManager::startDownload(uint8_t index) {
  if (busy() || index >= entryCount_ || !validFilename(names_[index]) ||
      !validSha256(hashes_[index]) || sizes_[index] == 0 ||
      sizes_[index] > kMaxBytes)
    return false;
  manifestMode_ = false;
  selectedIndex_ = index;
  requestPath_ = String(kGithubFirmwarePrefix) + names_[index];
  headerBuffer_ = "";
  manifestBody_ = "";
  startedAt_ = millis();
  lastDataAt_ = startedAt_;
  state_ = State::Connecting;
  emitStatus("GitHub: downloading " + names_[index]);
  return true;
}

void FireGithubFirmwareManager::releaseClient() {
  client_.stop();
}

bool FireGithubFirmwareManager::validFilename(const String& name) {
  if (name.length() == 0 || name.length() > 64 || name.indexOf("..") >= 0 ||
      name.indexOf('/') >= 0 || name.indexOf('\\') >= 0 ||
      !name.endsWith(".bin"))
    return false;
  for (size_t index = 0; index < name.length(); ++index) {
    const char value = name[index];
    const bool safe = (value >= 'a' && value <= 'z') ||
                      (value >= 'A' && value <= 'Z') ||
                      (value >= '0' && value <= '9') || value == '-' ||
                      value == '_' || value == '.';
    if (!safe) return false;
  }
  return true;
}

bool FireGithubFirmwareManager::validSha256(const String& value) {
  if (value.length() != 64) return false;
  for (size_t index = 0; index < value.length(); ++index) {
    if (!isHex(value[index])) return false;
  }
  return true;
}

String FireGithubFirmwareManager::jsonStringField(const String& json,
                                                  const char* key) {
  const String marker = String("\"") + key + "\"";
  const int keyAt = json.indexOf(marker);
  if (keyAt < 0) return "";
  const int colon = json.indexOf(':', keyAt + marker.length());
  const int start = json.indexOf('"', colon + 1);
  if (colon < 0 || start < 0) return "";
  const int end = json.indexOf('"', start + 1);
  return end > start ? json.substring(start + 1, end) : String();
}

uint32_t FireGithubFirmwareManager::jsonUintField(const String& json,
                                                  const char* key) {
  const String marker = String("\"") + key + "\"";
  const int keyAt = json.indexOf(marker);
  if (keyAt < 0) return 0;
  const int colon = json.indexOf(':', keyAt + marker.length());
  if (colon < 0) return 0;
  int start = colon + 1;
  while (start < json.length() &&
         (json[start] == ' ' || json[start] == '\t' || json[start] == '\n'))
    ++start;
  return static_cast<uint32_t>(json.substring(start).toInt());
}

bool FireGithubFirmwareManager::parseManifest() {
  const int filesAt = manifestBody_.indexOf("\"files\"");
  if (filesAt < 0) return false;
  uint8_t parsed = 0;
  int cursor = manifestBody_.indexOf('{', filesAt);
  while (cursor >= 0 && parsed < kMaxEntries) {
    const int end = manifestBody_.indexOf('}', cursor);
    if (end < 0) break;
    const String object = manifestBody_.substring(cursor, end + 1);
    const String name = jsonStringField(object, "name");
    const String hash = jsonStringField(object, "sha256");
    const uint32_t size = jsonUintField(object, "size_bytes");
    if (validFilename(name) && validSha256(hash) && size > 0 &&
        size <= kMaxBytes) {
      names_[parsed] = name;
      versions_[parsed] = jsonStringField(object, "version");
      hashes_[parsed] = hash;
      sizes_[parsed] = size;
      ++parsed;
    }
    cursor = manifestBody_.indexOf('{', end + 1);
  }
  entryCount_ = parsed;
  return entryCount_ > 0;
}

bool FireGithubFirmwareManager::prepareDownload(bool sdReady) {
  if (!sdReady) return false;
  if (!SD.exists("/firmware") && !SD.mkdir("/firmware")) return false;
  finalPath_ = "/firmware/" + names_[selectedIndex_];
  tempPath_ = finalPath_ + ".part";
  expectedHash_ = hashes_[selectedIndex_];
  expectedSize_ = sizes_[selectedIndex_];
  if (SD.exists(finalPath_)) return false;
  if (SD.exists(tempPath_)) SD.remove(tempPath_);
  stagedFile_ = SD.open(tempPath_, FILE_WRITE);
  if (!stagedFile_) return false;
  mbedtls_sha256_init(&sha256_);
  if (mbedtls_sha256_starts_ret(&sha256_, 0) != 0) {
    stagedFile_.close();
    SD.remove(tempPath_);
    return false;
  }
  shaInitialized_ = true;
  received_ = 0;
  return true;
}

bool FireGithubFirmwareManager::writeBytes(const uint8_t* data, size_t length) {
  while (length > 0) {
    const size_t amount = min<size_t>(kChunkSize, length);
    if (stagedFile_.write(data, amount) != amount ||
        mbedtls_sha256_update_ret(&sha256_, data, amount) != 0)
      return false;
    received_ += static_cast<uint32_t>(amount);
    data += amount;
    length -= amount;
  }
  return true;
}

void FireGithubFirmwareManager::fail(const String& code,
                                     const String& message) {
  if (stagedFile_) stagedFile_.close();
  if (shaInitialized_) {
    mbedtls_sha256_free(&sha256_);
    shaInitialized_ = false;
  }
  releaseClient();
  if (tempPath_.length() > 0 && SD.exists(tempPath_)) SD.remove(tempPath_);
  state_ = State::Idle;
  errorCode_ = code;
  errorMessage_ = message;
  emitStatus("GitHub failed: " + code);
  emitResult(manifestMode_, false, message);
}

void FireGithubFirmwareManager::finishManifest() {
  releaseClient();
  const bool ok = parseManifest();
  state_ = State::Idle;
  emitStatus(ok ? "GitHub firmware list ready" : "GitHub catalog invalid");
  emitResult(true, ok, ok ? "ready" : "Invalid firmware catalog");
}

String FireGithubFirmwareManager::sha256File(const String& path) const {
  File file = SD.open(path, FILE_READ);
  if (!file || file.isDirectory()) {
    if (file) file.close();
    return "";
  }
  mbedtls_sha256_context sha;
  mbedtls_sha256_init(&sha);
  mbedtls_sha256_starts_ret(&sha, 0);
  uint8_t buffer[512] = {};
  while (file.available()) {
    const size_t amount = file.read(buffer, sizeof(buffer));
    if (amount == 0 || mbedtls_sha256_update_ret(&sha, buffer, amount) != 0) {
      file.close();
      mbedtls_sha256_free(&sha);
      return "";
    }
  }
  file.close();
  uint8_t digest[32] = {};
  mbedtls_sha256_finish_ret(&sha, digest);
  mbedtls_sha256_free(&sha);
  return hexDigest(digest, sizeof(digest));
}

void FireGithubFirmwareManager::finishDownload() {
  uint8_t digest[32] = {};
  if (mbedtls_sha256_finish_ret(&sha256_, digest) != 0) {
    mbedtls_sha256_free(&sha256_);
    shaInitialized_ = false;
    fail("hash_failed", "Checksum calculation failed");
    return;
  }
  mbedtls_sha256_free(&sha256_);
  shaInitialized_ = false;
  const String actual = hexDigest(digest, sizeof(digest));
  if (received_ != expectedSize_ || contentLength_ != expectedSize_ ||
      !actual.equalsIgnoreCase(expectedHash_)) {
    fail("hash_mismatch", "GitHub firmware checksum mismatch");
    return;
  }
  stagedFile_.flush();
  stagedFile_.close();
  if (!SD.rename(tempPath_, finalPath_)) {
    fail("rename_failed", "Cannot activate GitHub firmware file");
    return;
  }
  releaseClient();
  state_ = State::Idle;
  emitStatus("GitHub firmware stored on SD");
  emitResult(false, true, "stored on SD");
}

void FireGithubFirmwareManager::service(bool wifiConnected, bool sdReady) {
  if (!busy()) return;
  if (!wifiConnected) {
    fail("wifi_disconnected", "Wi-Fi disconnected");
    return;
  }
  if (millis() - startedAt_ > kTransferTimeoutMs) {
    fail("timeout", "GitHub transfer timed out");
    return;
  }
  if (state_ == State::Connecting) {
    client_.setCACert(kGithubRootCertificates);
    client_.setTimeout(5);
    if (!client_.connect(kGithubHost, 443, 5000)) {
      fail("connect_failed", "GitHub connection failed");
      return;
    }
    client_.print("GET " + requestPath_ +
                  " HTTP/1.1\r\nHost: " + String(kGithubHost) +
                  "\r\nUser-Agent: FIRE-OS-Firmware\r\nAccept: */*\r\n"
                  "Connection: close\r\n\r\n");
    state_ = State::Headers;
    lastDataAt_ = millis();
    return;
  }
  if (state_ == State::Headers) {
    size_t budget = 2048;
    while (client_.available() && headerBuffer_.length() < kHeaderLimit &&
           budget-- > 0) {
      const int value = client_.read();
      if (value < 0) break;
      headerBuffer_ += static_cast<char>(value);
      lastDataAt_ = millis();
    }
    const int end = headerBuffer_.indexOf("\r\n\r\n");
    if (end < 0) {
      if (millis() - lastDataAt_ > kHeaderTimeoutMs)
        fail("header_timeout", "GitHub response timeout");
      return;
    }
    const String headers = headerBuffer_.substring(0, end);
    if (!headers.startsWith("HTTP/1.1 200") &&
        !headers.startsWith("HTTP/1.0 200")) {
      fail("http_rejected", "GitHub rejected firmware request");
      return;
    }
    String lower = headers;
    lower.toLowerCase();
    const int lengthAt = lower.indexOf("content-length:");
    if (lengthAt < 0) {
      fail("missing_length", "GitHub response has no size");
      return;
    }
    contentLength_ = static_cast<uint32_t>(
        headers.substring(lengthAt + 15).toInt());
    if (contentLength_ == 0 ||
        (manifestMode_ ? contentLength_ > kManifestLimit
                       : contentLength_ != expectedSize_)) {
      fail("size_mismatch", "GitHub response size mismatch");
      return;
    }
    const int bodyStart = end + 4;
    const size_t initial = bodyStart < headerBuffer_.length()
                               ? headerBuffer_.length() - bodyStart
                               : 0;
    if (manifestMode_) {
      manifestBody_ = initial > 0 ? headerBuffer_.substring(bodyStart) : "";
      state_ = State::ManifestBody;
      emitStatus("GitHub: reading catalog");
    } else {
      if (!prepareDownload(sdReady)) {
        fail("sd_prepare", "Cannot prepare firmware on SD");
        return;
      }
      if (initial > 0 &&
          !writeBytes(reinterpret_cast<const uint8_t*>(headerBuffer_.c_str() +
                                                       bodyStart),
                      initial)) {
        fail("sd_write", "GitHub firmware SD write failed");
        return;
      }
      state_ = State::DownloadBody;
      emitStatus("GitHub: 0% downloaded");
    }
    headerBuffer_ = "";
  }
  if (state_ == State::ManifestBody) {
    while (client_.available() && manifestBody_.length() < contentLength_) {
      const int value = client_.read();
      if (value < 0) break;
      manifestBody_ += static_cast<char>(value);
      lastDataAt_ = millis();
      if (manifestBody_.length() >= contentLength_) break;
    }
    if (manifestBody_.length() == contentLength_) finishManifest();
    else if (millis() - lastDataAt_ > kDataTimeoutMs)
      fail("data_timeout", "GitHub catalog download timed out");
  }
  if (state_ == State::DownloadBody) {
    uint8_t buffer[kChunkSize];
    size_t budget = 4096;
    while (client_.available() && received_ < contentLength_ && budget > 0) {
      const size_t amount = client_.read(
          buffer, min<size_t>(sizeof(buffer), contentLength_ - received_));
      if (amount == 0) break;
      if (!writeBytes(buffer, amount)) {
        fail("sd_write", "GitHub firmware SD write failed");
        return;
      }
      budget -= min<size_t>(budget, amount);
      lastDataAt_ = millis();
    }
    const uint32_t percent = contentLength_ == 0
                                 ? 0
                                 : received_ * 100UL / contentLength_;
    emitStatus("GitHub: " + String(percent) + "% downloaded");
    if (received_ == contentLength_) {
      stagedFile_.flush();
      stagedFile_.close();
      releaseClient();
      state_ = State::Verify;
    } else if (millis() - lastDataAt_ > kDataTimeoutMs) {
      fail("data_timeout", "GitHub firmware download timed out");
    }
  }
  if (state_ == State::Verify) finishDownload();
}

String FireGithubFirmwareManager::hexDigest(const uint8_t* digest,
                                             size_t length) {
  const char* digits = "0123456789abcdef";
  String result;
  result.reserve(length * 2);
  for (size_t index = 0; index < length; ++index) {
    result += digits[digest[index] >> 4];
    result += digits[digest[index] & 0x0F];
  }
  return result;
}
