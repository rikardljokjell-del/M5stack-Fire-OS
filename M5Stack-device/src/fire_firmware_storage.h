#pragma once

#include <Arduino.h>
#include <SD.h>
#include <WiFiClient.h>
#include <mbedtls/sha256.h>

#include "fire_reverse_transport.h"

// Receives candidate ESP32 firmware files from the trusted FIRE backend and
// stores them on SD. Flashing is handled separately by FireOS after an
// explicit user confirmation and inactive-slot validation.
class FireFirmwareStorage {
 public:
  static constexpr uint32_t kMaxBytes = 4UL * 1024UL * 1024UL;

  using StatusCallback = void (*)(void*, const String&);
  using ResultCallback = void (*)(void*, const String&, const String&, bool,
                                  const String&, const String&, const String&);

  void setCallbacks(void* context, StatusCallback status,
                    ResultCallback result);
  void setReverseTransport(FireReverseTransport* transport) {
    reverseTransport_ = transport;
  }

  // Returns false when the request is rejected before any network or SD work.
  // The caller can retrieve errorCode() and errorMessage() and send the
  // protocol failure receipt.  Duplicate requests already completed in this
  // boot are acknowledged through the result callback without downloading a
  // second time.
  bool startRequest(const String& host, uint16_t port, const String& token,
                    const String& url, const String& transferId,
                    const String& firmwareId, const String& filename,
                    const String& sdPath, const String& expectedHash,
                    uint32_t expectedSize, uint32_t expiresAt);
  void service(bool wifiConnected, bool sdReady);

  bool busy() const { return state_ != State::Idle; }
  const String& status() const { return status_; }
  const String& errorCode() const { return errorCode_; }
  const String& errorMessage() const { return errorMessage_; }
  uint32_t receivedBytes() const { return received_; }
  uint32_t expectedBytes() const { return expectedSize_; }

 private:
  enum class State : uint8_t { Idle, Connecting, Headers, Downloading, Verify };

  static constexpr size_t kChunkSize = 2048;
  static constexpr size_t kHeaderLimit = 8192;
  static constexpr uint32_t kHeaderTimeoutMs = 6000;
  static constexpr uint32_t kDataTimeoutMs = 15000;
  static constexpr uint32_t kTransferTimeoutMs = 300000;

  State state_ = State::Idle;
  WiFiClient client_;
  WiFiClient* reverseClient_ = nullptr;
  FireReverseTransport* reverseTransport_ = nullptr;
  File stagedFile_;

  String host_;
  uint16_t port_ = 8765;
  String token_;
  String url_;
  String transferId_;
  String firmwareId_;
  String filename_;
  String sdPath_;
  String tempPath_;
  String finalPath_;
  String expectedHash_;
  uint32_t expectedSize_ = 0;
  uint32_t expiresAt_ = 0;
  uint32_t contentLength_ = 0;
  uint32_t received_ = 0;
  uint32_t startedAt_ = 0;
  uint32_t connectAttemptAt_ = 0;
  uint32_t lastDataAt_ = 0;
  String headerBuffer_;
  String status_;
  String errorCode_;
  String errorMessage_;

  String completedTransferId_;
  String completedFirmwareId_;
  bool completedOk_ = false;
  String completedHash_;
  String completedErrorCode_;
  String completedMessage_;
  bool filePrepared_ = false;

  void* callbackContext_ = nullptr;
  StatusCallback statusCallback_ = nullptr;
  ResultCallback resultCallback_ = nullptr;
  mbedtls_sha256_context sha256_;
  bool shaInitialized_ = false;

  void emitStatus(const String& value);
  void emitResult(bool ok, const String& hash, const String& errorCode,
                  const String& message);
  void fail(const String& code, const String& message);
  void releaseTransport();
  bool validateRequest(const String& url, const String& transferId,
                      const String& firmwareId, const String& filename,
                      const String& sdPath, const String& expectedHash,
                      uint32_t expectedSize) const;
  bool validFilename(const String& filename) const;
  bool validDownloadUrl(const String& url) const;
  bool prepareSdFile();
  bool writeBytes(const uint8_t* data, size_t length);
  void finishDownload();
  String sha256File(const String& path) const;
  static String hexDigest(const uint8_t* digest, size_t length);

  WiFiClient* activeClient() {
    return reverseClient_ ? reverseClient_ : &client_;
  }
};
