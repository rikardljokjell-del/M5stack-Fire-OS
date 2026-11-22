#include "fire_firmware_storage.h"

namespace {
bool isHex(char value) {
  return (value >= '0' && value <= '9') ||
         (value >= 'a' && value <= 'f') ||
         (value >= 'A' && value <= 'F');
}

bool isSafeIdentifier(const String& value) {
  if (value.length() == 0 || value.length() > 64) return false;
  for (size_t index = 0; index < value.length(); ++index) {
    const char character = value[index];
    const bool safe = (character >= 'a' && character <= 'z') ||
                      (character >= 'A' && character <= 'Z') ||
                      (character >= '0' && character <= '9') ||
                      character == '-' || character == '_' || character == '.';
    if (!safe) return false;
  }
  return value[0] != '.';
}
}  // namespace

void FireFirmwareStorage::setCallbacks(void* context, StatusCallback status,
                                        ResultCallback result) {
  callbackContext_ = context;
  statusCallback_ = status;
  resultCallback_ = result;
}

void FireFirmwareStorage::emitStatus(const String& value) {
  status_ = value;
  if (statusCallback_) statusCallback_(callbackContext_, status_);
}

void FireFirmwareStorage::emitResult(bool ok, const String& hash,
                                     const String& errorCode,
                                     const String& message) {
  if (resultCallback_) {
    resultCallback_(callbackContext_, transferId_, firmwareId_, ok, hash,
                    errorCode, message.substring(0, 240));
  }
}

bool FireFirmwareStorage::validFilename(const String& filename) const {
  // Backend-generated names are fire-<16 hex characters>.bin.  Requiring this
  // shape prevents path traversal and keeps the SD directory predictable.
  if (filename.length() != 25 || !filename.startsWith("fire-") ||
      !filename.endsWith(".bin"))
    return false;
  for (uint8_t index = 5; index < 21; ++index) {
    if (!isHex(filename[index])) return false;
  }
  return true;
}

bool FireFirmwareStorage::validDownloadUrl(const String& url) const {
  // The host is always taken from saved backend configuration.  Only the
  // backend's firmware route is accepted from the incoming command.
  return url.length() > 0 && url.length() <= 192 && url.startsWith("/firmware/") &&
         url.indexOf("..") < 0 && url.indexOf("\\") < 0 &&
         url.indexOf("://") < 0 && url.indexOf('\n') < 0 &&
         url.indexOf('\r') < 0;
}

bool FireFirmwareStorage::validateRequest(
    const String& url, const String& transferId, const String& firmwareId,
    const String& filename, const String& sdPath, const String& expectedHash,
    uint32_t expectedSize) const {
  return isSafeIdentifier(transferId) && isSafeIdentifier(firmwareId) &&
         validFilename(filename) && sdPath == "/firmware/" + filename &&
         validDownloadUrl(url) && expectedHash.length() == 64 &&
         expectedSize > 0 && expectedSize <= kMaxBytes &&
         [&]() {
           for (size_t index = 0; index < expectedHash.length(); ++index) {
             if (!isHex(expectedHash[index])) return false;
           }
           return true;
         }();
}

bool FireFirmwareStorage::startRequest(
    const String& host, uint16_t port, const String& token, const String& url,
    const String& transferId, const String& firmwareId, const String& filename,
    const String& sdPath, const String& expectedHash, uint32_t expectedSize,
    uint32_t expiresAt) {
  errorCode_ = "";
  errorMessage_ = "";
  filePrepared_ = false;
  if (busy()) {
    if (transferId_ == transferId && firmwareId_ == firmwareId) return true;
    errorCode_ = "busy";
    errorMessage_ = "Another firmware transfer is active";
    return false;
  }
  if (completedTransferId_ == transferId && completedFirmwareId_ == firmwareId) {
    transferId_ = transferId;
    firmwareId_ = firmwareId;
    emitResult(completedOk_, completedHash_, completedErrorCode_,
               completedMessage_);
    return true;
  }
  if (host.length() == 0 || token.length() < 24 || expiresAt == 0 ||
      !validateRequest(url, transferId, firmwareId, filename, sdPath,
                       expectedHash, expectedSize)) {
    errorCode_ = "invalid_request";
    errorMessage_ = "Firmware request rejected";
    return false;
  }

  host_ = host;
  port_ = port == 0 ? 8765 : port;
  token_ = token;
  url_ = url;
  transferId_ = transferId;
  firmwareId_ = firmwareId;
  filename_ = filename;
  sdPath_ = sdPath;
  tempPath_ = sdPath_ + ".part";
  finalPath_ = sdPath_;
  expectedHash_ = expectedHash;
  expectedSize_ = expectedSize;
  expiresAt_ = expiresAt;
  contentLength_ = 0;
  received_ = 0;
  startedAt_ = millis();
  connectAttemptAt_ = 0;
  lastDataAt_ = startedAt_;
  headerBuffer_ = "";
  if (shaInitialized_) {
    mbedtls_sha256_free(&sha256_);
    shaInitialized_ = false;
  }
  state_ = State::Connecting;
  emitStatus("Firmware: waiting for SD");
  return true;
}

void FireFirmwareStorage::releaseTransport() {
  if (reverseClient_ && reverseTransport_) {
    reverseTransport_->release(reverseClient_);
    reverseClient_ = nullptr;
  } else {
    client_.stop();
  }
}

bool FireFirmwareStorage::prepareSdFile() {
  if (!SD.exists("/firmware") && !SD.mkdir("/firmware")) return false;
  if (SD.exists(finalPath_)) {
    // Never overwrite a completed firmware candidate. The backend filename is
    // hash-derived, so an existing same-hash file can be acknowledged safely.
    File existing = SD.open(finalPath_, FILE_READ);
    const bool sameSize = existing && !existing.isDirectory() &&
                          existing.size() == expectedSize_;
    if (existing) existing.close();
    if (sameSize && sha256File(finalPath_).equalsIgnoreCase(expectedHash_)) {
      completedTransferId_ = transferId_;
      completedFirmwareId_ = firmwareId_;
      completedOk_ = true;
      completedHash_ = expectedHash_;
      completedErrorCode_ = "";
      completedMessage_ = "already stored";
      state_ = State::Idle;
      emitStatus("Firmware already stored");
      emitResult(true, expectedHash_, "", "already stored");
      return false;
    }
    errorCode_ = "final_exists";
    errorMessage_ = "Firmware file already exists";
    return false;
  }
  if (SD.exists(tempPath_)) SD.remove(tempPath_);
  const uint32_t total = static_cast<uint32_t>(SD.totalBytes());
  const uint32_t used = static_cast<uint32_t>(SD.usedBytes());
  if (total > 0 && (used >= total || total - used < expectedSize_ + 4096UL)) {
    errorCode_ = "sd_full";
    errorMessage_ = "Not enough SD space";
    return false;
  }
  stagedFile_ = SD.open(tempPath_, FILE_WRITE);
  if (!stagedFile_) {
    errorCode_ = "sd_write";
    errorMessage_ = "Cannot open firmware staging file";
    return false;
  }
  mbedtls_sha256_init(&sha256_);
  if (mbedtls_sha256_starts_ret(&sha256_, 0) != 0) {
    stagedFile_.close();
    SD.remove(tempPath_);
    errorCode_ = "hash_init";
    errorMessage_ = "Checksum initialization failed";
    return false;
  }
  shaInitialized_ = true;
  filePrepared_ = true;
  return true;
}

bool FireFirmwareStorage::writeBytes(const uint8_t* data, size_t length) {
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

void FireFirmwareStorage::fail(const String& code, const String& message) {
  if (stagedFile_) {
    stagedFile_.close();
  }
  if (shaInitialized_) {
    mbedtls_sha256_free(&sha256_);
    shaInitialized_ = false;
  }
  releaseTransport();
  if (tempPath_.length() > 0 && SD.exists(tempPath_)) SD.remove(tempPath_);
  filePrepared_ = false;
  errorCode_ = code;
  errorMessage_ = message;
  completedTransferId_ = transferId_;
  completedFirmwareId_ = firmwareId_;
  completedOk_ = false;
  completedHash_ = "";
  completedErrorCode_ = code;
  completedMessage_ = message;
  state_ = State::Idle;
  emitStatus("Firmware failed: " + code);
  emitResult(false, "", code, message);
}

void FireFirmwareStorage::finishDownload() {
  uint8_t digest[32] = {};
  if (mbedtls_sha256_finish_ret(&sha256_, digest) != 0) {
    mbedtls_sha256_free(&sha256_);
    shaInitialized_ = false;
    fail("hash_failed", "Checksum calculation failed");
    return;
  }
  mbedtls_sha256_free(&sha256_);
  shaInitialized_ = false;
  const String actualHash = hexDigest(digest, sizeof(digest));
  if (received_ != expectedSize_ || contentLength_ != expectedSize_) {
    fail("size_mismatch", "Firmware size mismatch");
    return;
  }
  if (!actualHash.equalsIgnoreCase(expectedHash_)) {
    fail("hash_mismatch", "Firmware checksum mismatch");
    return;
  }
  if (SD.exists(finalPath_)) {
    fail("final_exists", "Firmware file already exists");
    return;
  }
  if (!SD.rename(tempPath_, finalPath_)) {
    fail("rename_failed", "Cannot activate firmware file");
    return;
  }
  filePrepared_ = false;
  completedTransferId_ = transferId_;
  completedFirmwareId_ = firmwareId_;
  completedOk_ = true;
  completedHash_ = actualHash;
  completedErrorCode_ = "";
  completedMessage_ = "stored on SD";
  state_ = State::Idle;
  emitStatus("Firmware stored on SD");
  emitResult(true, actualHash, "", "stored on SD");
}

void FireFirmwareStorage::service(bool wifiConnected, bool sdReady) {
  if (!busy()) return;
  if (millis() - startedAt_ > kTransferTimeoutMs) {
    fail("timeout", "Firmware transfer timed out");
    return;
  }
  if (!wifiConnected) {
    fail("wifi_disconnected", "Wi-Fi disconnected");
    return;
  }
  if (!sdReady) {
    fail("no_sd", "SD card not available");
    return;
  }

  if (state_ == State::Connecting) {
    if (!filePrepared_ && !prepareSdFile()) {
      // prepareSdFile can finish a duplicate request itself. Only emit a
      // failure when it populated an error code.
      if (errorCode_.length() > 0) fail(errorCode_, errorMessage_);
      return;
    }
    if (reverseTransport_) reverseClient_ = reverseTransport_->acquire();
    WiFiClient* client = activeClient();
    if (!reverseClient_) {
      if (millis() - connectAttemptAt_ < 1000) return;
      connectAttemptAt_ = millis();
      client_.setTimeout(1200);
      if (!client_.connect(host_.c_str(), port_, 1200)) {
        if (millis() - startedAt_ > kHeaderTimeoutMs)
          fail("connect_failed", "Backend firmware connection failed");
        return;
      }
    }
    client->print("GET " + url_ + " HTTP/1.1\r\nHost: " + host_ + ":" +
                  String(port_) + "\r\nAuthorization: Bearer " + token_ +
                  "\r\nConnection: close\r\n\r\n");
    state_ = State::Headers;
    lastDataAt_ = millis();
    emitStatus("Firmware: waiting for download");
    return;
  }

  WiFiClient* client = activeClient();
  if (!client || !client->connected()) {
    fail("connection_lost", "Backend firmware connection closed");
    return;
  }

  if (state_ == State::Headers) {
    size_t budget = 2048;
    while (client->available() && headerBuffer_.length() < kHeaderLimit &&
           budget-- > 0) {
      const int value = client->read();
      if (value < 0) break;
      headerBuffer_ += static_cast<char>(value);
      lastDataAt_ = millis();
    }
    const int end = headerBuffer_.indexOf("\r\n\r\n");
    if (end < 0) {
      if (millis() - lastDataAt_ > kHeaderTimeoutMs)
        fail("header_timeout", "Firmware response timeout");
      return;
    }
    const String headers = headerBuffer_.substring(0, end);
    if (!headers.startsWith("HTTP/1.1 200") &&
        !headers.startsWith("HTTP/1.0 200")) {
      fail("http_rejected", "Backend rejected firmware download");
      return;
    }
    String lowerHeaders = headers;
    lowerHeaders.toLowerCase();
    const int lengthAt = lowerHeaders.indexOf("content-length:");
    if (lengthAt < 0) {
      fail("missing_length", "Firmware response has no size");
      return;
    }
    contentLength_ = static_cast<uint32_t>(
        headers.substring(lengthAt + 15).toInt());
    if (contentLength_ == 0 || contentLength_ != expectedSize_ ||
        contentLength_ > kMaxBytes) {
      fail("size_mismatch", "Firmware response size mismatch");
      return;
    }
    const int bodyStart = end + 4;
    if (bodyStart < headerBuffer_.length() &&
        !writeBytes(reinterpret_cast<const uint8_t*>(headerBuffer_.c_str() +
                                                     bodyStart),
                    headerBuffer_.length() - bodyStart)) {
      fail("sd_write", "Firmware SD write failed");
      return;
    }
    headerBuffer_ = "";
    state_ = State::Downloading;
    emitStatus("Firmware: " + String(received_) + "/" +
               String(contentLength_));
  }

  if (state_ == State::Downloading) {
    uint8_t buffer[kChunkSize];
    size_t budget = 4096;
    while (client->available() && received_ < contentLength_ && budget > 0) {
      const size_t amount = client->read(
          buffer, min<size_t>(sizeof(buffer), contentLength_ - received_));
      if (amount == 0) break;
      if (!writeBytes(buffer, amount)) {
        fail("sd_write", "Firmware SD write failed");
        return;
      }
      budget -= min<size_t>(budget, amount);
      lastDataAt_ = millis();
    }
    emitStatus("Firmware: " + String(received_) + "/" +
               String(contentLength_));
    if (received_ == contentLength_) {
      stagedFile_.flush();
      stagedFile_.close();
      releaseTransport();
      state_ = State::Verify;
      emitStatus("Firmware: verifying");
    } else if (millis() - lastDataAt_ > kDataTimeoutMs) {
      fail("data_timeout", "Firmware download timed out");
    }
  }

  if (state_ == State::Verify) finishDownload();
}

String FireFirmwareStorage::sha256File(const String& path) const {
  File file = SD.open(path, FILE_READ);
  if (!file || file.isDirectory()) {
    if (file) file.close();
    return "";
  }
  mbedtls_sha256_context sha;
  mbedtls_sha256_init(&sha);
  if (mbedtls_sha256_starts_ret(&sha, 0) != 0) {
    file.close();
    mbedtls_sha256_free(&sha);
    return "";
  }
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
  if (mbedtls_sha256_finish_ret(&sha, digest) != 0) {
    mbedtls_sha256_free(&sha);
    return "";
  }
  mbedtls_sha256_free(&sha);
  return hexDigest(digest, sizeof(digest));
}

String FireFirmwareStorage::hexDigest(const uint8_t* digest, size_t length) {
  const char* digits = "0123456789abcdef";
  String result;
  result.reserve(length * 2);
  for (size_t index = 0; index < length; ++index) {
    result += digits[digest[index] >> 4];
    result += digits[digest[index] & 0x0F];
  }
  return result;
}
