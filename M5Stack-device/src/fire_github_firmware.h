#pragma once

#include <Arduino.h>
#include <SD.h>
#include <time.h>
#include <WiFiClientSecure.h>
#include <mbedtls/sha256.h>
#include "fire_async_client.h"
#include "fire_release.h"
#include "fire_io_mailbox.h"
#include "fire_firmware_staging.h"

// Reads the public, device-compatible firmware catalog from the FIRE OS
// repository and downloads a selected image to /firmware. The URL and host
// are fixed in the implementation; the manifest cannot redirect the device
// to an arbitrary server.
class FireGithubFirmwareManager {
 public:
  static constexpr uint32_t kMaxBytes = 4UL * 1024UL * 1024UL;
  static constexpr uint8_t kMaxEntries = 8;

  using StatusCallback = void (*)(void*, const String&);
  using ResultCallback = void (*)(void*, bool, bool, const String&);

  void setCallbacks(void* context, StatusCallback status,
                    ResultCallback result);
  bool startManifest();
  bool startDownload(uint8_t index, bool overwriteExisting = false);
  bool selection(uint8_t index, FireRelease& release, String& signedCatalog) const;
  bool startDownload(const FireRelease& release, const String& signedCatalog,
                     bool overwriteExisting = false);
  void service(bool wifiConnected, bool sdReady);

  bool busy() const { return io_.busy() || client_.running(); }
  const String& status() const { return status_; }
  uint8_t entryCount() const { return io_.running ? 0 : entryCount_; }
  const String& entryName(uint8_t index) const { return catalog_.files[index].name; }
  const String& entryVersion(uint8_t index) const { return catalog_.files[index].version; }
  const String& entryNotes(uint8_t index) const { return catalog_.files[index].notes; }
  uint32_t entrySize(uint8_t index) const { return catalog_.files[index].size; }

 private:
  enum class State : uint8_t {
    Idle,
    Connecting,
    Headers,
    ManifestBody,
    DownloadBody,
    Verify,
    StoppingNetwork,
    WriteSd,
  };

  static constexpr size_t kChunkSize = 2048;
  static constexpr size_t kHeaderLimit = 8192;
  static constexpr size_t kManifestLimit = 32768;
  static constexpr uint32_t kHeaderTimeoutMs = 10000;
  static constexpr uint32_t kDataTimeoutMs = 20000;
  static constexpr uint32_t kTransferTimeoutMs = 300000;

  State state_ = State::Idle;
  FireIoMailbox io_;
  bool launch();
  static void task(void* context);
  void serviceWorker(bool wifiConnected, bool sdReady);
  FireAsyncClient client_;
  File stagedFile_;
  uint8_t* downloadBuffer_ = nullptr;
  const char* stagedCatalog_ = nullptr;
  size_t stagedCatalogLength_ = 0;
  FireFirmwareStaging staging_;
  uint32_t sdWritten_ = 0, phaseStartedAt_ = 0;
  bool manifestMode_ = false;
  bool overwriteExisting_ = false;
  uint8_t entryCount_ = 0;
  FireReleaseCatalog catalog_;
  FireRelease selectedRelease_;
  String verifiedManifest_;
  String downloadCatalog_;
  bool selectionVerified_ = false, ownsStage_ = false, ownsCatalogStage_ = false, ownsGlobalStage_ = false;
  String catalogStage_, catalogFinal_, binaryBackup_, catalogBackup_;
  String globalStage_, globalBackup_;

  String requestPath_;
  String headerBuffer_;
  String manifestBody_;
  String tempPath_;
  String finalPath_;
  String expectedHash_;
  uint32_t expectedSize_ = 0;
  uint32_t contentLength_ = 0;
  uint32_t received_ = 0;
  uint32_t startedAt_ = 0;
  uint32_t lastDataAt_ = 0;
  uint32_t clockSyncStartedAt_ = 0;
  bool clockSyncRequested_ = false;
  bool connectionMeasured_ = false;
  String status_;
  String errorCode_;
  String errorMessage_;
  mbedtls_sha256_context sha256_;
  bool shaInitialized_ = false;

  void* callbackContext_ = nullptr;
  StatusCallback statusCallback_ = nullptr;
  ResultCallback resultCallback_ = nullptr;

  void emitStatus(const String& value);
  void emitResult(bool manifest, bool ok, const String& message);
  void fail(const String& code, const String& message);
  void releaseClient();
  bool writeBytes(const uint8_t* data, size_t length);
  bool prepareStaging();
  void freeStaging();
  void writeSd();
  bool parseManifest();
  bool prepareDownload(bool sdReady);
  void finishManifest();
  void finishDownload();
  String sha256File(const String& path, uint32_t expectedSize) const;
  bool writeCatalog();
  bool writeCatalogFile(const String& path, bool& owned);
  static String jsonStringField(const String& json, const char* key);
  static uint32_t jsonUintField(const String& json, const char* key);
  static bool validFilename(const String& name);
  static bool validSha256(const String& value);
  static String hexDigest(const uint8_t* digest, size_t length);
};
