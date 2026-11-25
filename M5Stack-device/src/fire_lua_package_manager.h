#pragma once

#include <Arduino.h>
#include <SD.h>
#include <WiFiClient.h>
#include <mbedtls/sha256.h>
#include "fire_reverse_transport.h"
#include "fire_async_client.h"
#include "fire_io_mailbox.h"
#include "fire_lua_install_identity.h"

class FireLuaPackageManager {
 public:
  using StatusCallback = void (*)(void*, const String&);
  using ResultCallback = void (*)(void*, bool, const String&, const String&,
                                  const String&, const String&);

  void setCallbacks(void* context, StatusCallback status, ResultCallback result);
  void setReverseTransport(FireReverseTransport* transport) {
    reverseTransport_ = transport;
  }
  bool startDownload(const String& host, uint16_t port, const String& token,
                     const String& url, const String& packageId,
                     const String& installId, const String& expectedHash,
                     uint32_t expectedSize,const String& projectId=String());
  void service(bool wifiConnected);
  bool busy() const { return io_.busy(); }
  bool matchesInstall(const String& packageId, const String& installId,
                      const String& hash, uint32_t size) const {
    return busy() && packageId_ == packageId && installId_ == installId &&
           expectedHash_.equalsIgnoreCase(hash) && expectedSize_ == size;
  }
  const String& status() const { return status_; }
  const String& installedPath() const { return installedPath_; }
  uint8_t progress() const { return progress_.load(std::memory_order_relaxed); }

 private:
  enum class State : uint8_t { Idle, Connecting, Headers, Downloading, Verify };
  State state_ = State::Idle;
  FireIoMailbox io_;
  static void task(void* context);
  void serviceWorker(bool wifiConnected);
  FireAsyncClient client_;
  bool secureEndpoint_ = true;
  FireReverseTransport* reverseTransport_ = nullptr;
  WiFiClient* reverseClient_ = nullptr;
  uint32_t reverseGeneration_ = 0;
  File archive_;
  String host_;
  uint16_t port_ = 8765;
  String token_;
  String url_;
  String packageId_;
  String installId_;
  String projectId_;
  String expectedHash_;
  uint32_t expectedSize_ = 0;
  uint32_t contentLength_ = 0;
  uint32_t received_ = 0;
  std::atomic<uint8_t> progress_{0};
  uint32_t lastDataAt_ = 0;
  String headerBuffer_;
  String status_;
  String installedPath_;
  void* callbackContext_ = nullptr;
  StatusCallback statusCallback_ = nullptr;
  ResultCallback resultCallback_ = nullptr;
  mbedtls_sha256_context sha256_;

  void fail(const String& reason);
  void finishDownload();
  void emitStatus(const String& value);
  bool installArchive(File& archive, const String& archiveHash, String& reason);
  bool extractStoredZip(File& archive, String& appId,const String& archiveHash,String& reason);
  static uint16_t read16(File& file);
  static uint32_t read32(File& file);
  static bool validZipPath(const String& path);
  static String hexDigest(const uint8_t* digest, size_t length);
  WiFiClient* activeClient() {
    return reverseClient_ ? reverseClient_ : &client_;
  }
};
