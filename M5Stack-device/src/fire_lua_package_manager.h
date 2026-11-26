#pragma once

#include <Arduino.h>
#include <SD.h>
#include <WiFiClient.h>
#include <mbedtls/sha256.h>
#include "fire_reverse_transport.h"
#include "fire_async_client.h"
#include "fire_io_mailbox.h"
#include "fire_package_delivery.h"
#include "fire_firmware_staging.h"
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
                     uint32_t expectedSize,const String& projectId,const String& sessionId,const String& bootId,uint32_t expiresAt);
  void service(bool wifiConnected,bool allowed,bool busyNetwork,bool socketsQuiet,bool unexpired);
  void cancel() {cancelled_.store(true,std::memory_order_release);}
  bool busy() const { return delivery_.active() || io_.busy(); }
  bool networkPaused() const {return delivery_.paused();}
  bool receiptReady() const {return delivery_.phase==fire_package_delivery::Phase::Receipt && receiptFrozen_ && io_.completed;}
  bool receiptDue(uint32_t now) const {return receiptReady() && delivery_.receiptDue(now);}
  void receiptSent(uint32_t now) {delivery_.receiptSent(now);}
  const String& receiptEvent() const {return receiptEvent_;}
  const String& installSession() const {return sessionId_;}
  const String& installBoot() const {return bootId_;}
  uint32_t installExpiry() const {return expiresAt_;}
  const String& installId() const {return installId_;}
  const String& packageId() const {return packageId_;}
  const String& outcomeHash() const {return io_.second;}
  const String& outcomeMessage() const {return io_.message;}
  bool outcomeOk() const {return io_.ok;}
  void amendOutcome(bool ok,const String& message) {if (!receiptFrozen_) {io_.ok=ok;io_.message=message;}}
  void finishReceipt() {io_.completed=false;delivery_.clear();}

  bool matchesInstall(const String& packageId, const String& installId,
                      const String& hash, uint32_t size) const {
    return packageId_ == packageId && installId_ == installId &&
           expectedHash_.equalsIgnoreCase(hash) && expectedSize_ == size;
  }
  const String& status() const { return status_; }
  const String& installedPath() const { return installedPath_; }
  uint8_t progress() const { return progress_.load(std::memory_order_relaxed); }

 private:
  enum class State : uint8_t { Idle, Connecting, Headers, Downloading, Verify };
  State state_ = State::Idle;
  fire_package_delivery::Gate delivery_;
  String sessionId_,bootId_,receiptEvent_;
  uint32_t expiresAt_=0;
  bool receiptFrozen_=false,preconnectedTls_=false;
  bool buffered_=false,shaInitialized_=false,streamVerified_=false,storageStarted_=false,ownsArchive_=false;
  uint8_t* stagedBytes_=nullptr;
  FireFirmwareStaging staging_;
  bool prepareStaging();
  void freeStaging();
  void freeHash();
  void readDownloadBody();
  void readLegacyBody();
  void finishSecureStream();
  bool writeStagedArchive(String& reason);
  std::atomic<bool> cancelled_{false};
  void startWorker();
  void preconnect();
  String connectionFailure() const;
  bool cancelled() const;
  void queuedFailure(const String& reason);
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
