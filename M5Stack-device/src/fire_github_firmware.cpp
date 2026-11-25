#include "fire_github_firmware.h"
#include <WiFi.h>
#include <errno.h>
#include <esp_system.h>
#include <esp_heap_caps.h>
#include "fire_firmware_http.h"
#include "fire_sd_transaction.h"

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
    "6mcY1Yl9PMWLSn/pvtsrF9+wX3N3KjITOYFnQoQj8kVnNeyIv/iPsGEMNKSuIEyExt\n"
    "v4NeF22d+mQrvHRAiGfzZ0JFrabA0UWTW98kndth/Jsw1HKj2ZL7tcu7XUIOGZX1\n"
    "NGFdtom/DzMNU+MeKNhJ7jitralj41E6Vf8PlwUHBHQRFXGU7Aj64GxJUTFy8bJZ9\n"
    "18rGOmaFvE7FBcf6IKshPECBV1/MUReXgRPTqh5Uykw7+U0b6LJ3/iyK5S9kJRaTe\n"
    "pLiaWN0bfVKfjllDiIGknibVb63dDcY3fe0Dkhvld1927jyNxF1WW6LZZm6zNTfl\n"
    "MrY=\n"
    "-----END CERTIFICATE-----\n"
    "-----BEGIN CERTIFICATE-----\n"
    "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\n"
    "m+kXQ99b21/+jh5Xos1AnX5iItreGCc=\n"
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
  io_.status(value);
}

void FireGithubFirmwareManager::emitResult(bool manifest, bool ok,
                                            const String& message) {
  io_.result(manifest, ok, "", "", message);
}

bool FireGithubFirmwareManager::startManifest() {
  if (busy()) return false;
  errorCode_ = errorMessage_ = "";
  tempPath_ = catalogStage_ = globalStage_ = ""; ownsStage_ = ownsCatalogStage_ = ownsGlobalStage_ = false;
  manifestMode_ = true;
  overwriteExisting_ = false;
  requestPath_ = kGithubManifestPath;
  headerBuffer_ = "";
  manifestBody_ = "";
  startedAt_ = millis();
  lastDataAt_ = startedAt_;
  clockSyncStartedAt_ = startedAt_;
  clockSyncRequested_ = false;
  state_ = State::Connecting;
  emitStatus("GitHub: connecting");
  return launch();
}

bool FireGithubFirmwareManager::selection(uint8_t index, FireRelease& release,
                                                  String& envelope) const {
  if (busy() || index >= entryCount_) return false;
  release = catalog_.files[index];
  envelope = verifiedManifest_;
  return envelope.length() == verifiedManifest_.length() && release.name.length();
}

bool FireGithubFirmwareManager::startDownload(uint8_t index, bool overwrite) {
  FireRelease release; String envelope;
  return selection(index, release, envelope) && startDownload(release, envelope, overwrite);
}

bool FireGithubFirmwareManager::startDownload(const FireRelease& release,
                                              const String& envelope, bool overwrite) {
  if (busy() || !validFilename(release.name) || !validSha256(release.hash) ||
      !release.size || release.size > kMaxBytes || !envelope.length() || envelope.length() > kManifestLimit)
    return false;
  selectedRelease_ = release;
  downloadCatalog_ = envelope;
  if (downloadCatalog_ != envelope || selectedRelease_.name != release.name) return false;
  manifestMode_ = false; overwriteExisting_ = overwrite; selectionVerified_ = false;
  errorCode_ = errorMessage_ = "";
  tempPath_ = catalogStage_ = globalStage_ = ""; ownsStage_ = ownsCatalogStage_ = ownsGlobalStage_ = false;
  expectedHash_ = release.hash; expectedSize_ = release.size;
  requestPath_ = String(kGithubFirmwarePrefix) + release.name;
  headerBuffer_ = manifestBody_ = "";
  startedAt_ = lastDataAt_ = clockSyncStartedAt_ = millis();
  clockSyncRequested_ = false; state_ = State::Connecting;
  emitStatus("GitHub: henter til arbeidsminne");
  return launch();
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
  FireReleaseCatalog catalog;
  entryCount_ = 0;
  if (!fireVerifyCatalog(manifestBody_, catalog)) return false;
  verifiedManifest_ = manifestBody_;
  catalog_ = catalog;
  entryCount_ = catalog.count;
  return true;
}

bool FireGithubFirmwareManager::prepareDownload(bool sdReady) {
  if (!staging_.readyForSd(client_.running())) {
    errorCode_ = "phase_guard"; errorMessage_ = "Nedlastingen er ikke klar for SD"; return false;
  }
  if (!sdReady) { errorCode_ = "no_sd"; errorMessage_ = "SD-kort er ikke tilgjengelig"; return false; }
  if (!SD.exists("/firmware") && !SD.mkdir("/firmware")) {
    errorCode_ = "sd_directory"; errorMessage_ = "Kan ikke opprette firmwaremappe"; return false;
  }
  const uint64_t total = SD.totalBytes(), used = SD.usedBytes();
  const uint64_t required = uint64_t(expectedSize_) + downloadCatalog_.length() + 131072ULL;
  Serial.printf("FIRE SD space total=%llu used=%llu required=%llu\n", total, used, required);
  if (!total || used > total) { errorCode_ = "sd_stats"; errorMessage_ = "Kan ikke lese SD-kapasitet"; return false; }
  if (required > total - used) { errorCode_ = "sd_full"; errorMessage_ = "Ikke nok ledig plass pa SD"; return false; }
  finalPath_ = "/firmware/" + selectedRelease_.name;
  catalogFinal_ = finalPath_ + ".catalog-v2.json";
  if (SD.exists(finalPath_) && !overwriteExisting_) {
    errorCode_ = "file_exists"; errorMessage_ = "Filen finnes. Bekreft erstatning"; return false;
  }
  // Fresh owned staging paths never truncate an earlier user/staging file.
  for (uint8_t attempt = 0; attempt < 4; ++attempt) {
    char nonce[9]; snprintf(nonce, sizeof(nonce), "%08lx", (unsigned long)esp_random());
    const String stem = "/firmware/.fw-" + String(nonce);
    tempPath_ = stem + ".part"; catalogStage_ = stem + ".json.part";
    binaryBackup_ = stem + ".bin.bak"; catalogBackup_ = stem + ".json.bak";
    globalStage_ = stem + ".global.part"; globalBackup_ = stem + ".global.bak";
    if (!SD.exists(tempPath_) && !SD.exists(catalogStage_) &&
        !SD.exists(binaryBackup_) && !SD.exists(catalogBackup_) &&
        !SD.exists(globalStage_) && !SD.exists(globalBackup_)) break;
    tempPath_ = "";
  }
  if (!tempPath_.length()) { errorCode_ = "sd_staging"; errorMessage_ = "Kan ikke velge midlertidig fil"; return false; }
  errno = 0;
  stagedFile_ = SD.open(tempPath_, FILE_WRITE);
  const int openError = errno;
  if (!stagedFile_) {
    Serial.printf("FIRE SD open errno=%d\n", openError);
    errorCode_ = "sd_open"; errorMessage_ = "Kan ikke opprette SD-fil"; return false;
  }
  ownsStage_ = true;
  if (!stagedFile_.setBufferSize(512)) {
    errorCode_ = "sd_buffer"; errorMessage_ = "Ikke nok minne til SD-buffer"; return false;
  }
  return true;
}

bool FireGithubFirmwareManager::prepareStaging() {
  const uint32_t caps = MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT;
  const size_t free = heap_caps_get_free_size(caps), largest = heap_caps_get_largest_free_block(caps);
  Serial.printf("FIRE GitHub staging bytes=%lu psram_total=%u free=%u largest=%u\n",
      (unsigned long)expectedSize_, unsigned(heap_caps_get_total_size(caps)), unsigned(free), unsigned(largest));
  if (!FireFirmwareStaging::fits(expectedSize_, kMaxBytes, free, largest, 512UL * 1024UL)) {
    errorCode_ = "staging_memory"; errorMessage_ = "Ikke nok arbeidsminne. Bruk direkte installering"; return false;
  }
  downloadBuffer_ = static_cast<uint8_t*>(heap_caps_malloc(expectedSize_, caps));
  if (!downloadBuffer_) {
    errorCode_ = "staging_memory"; errorMessage_ = "Kan ikke reservere arbeidsminne. SD er urort"; return false;
  }
  staging_.attach(downloadBuffer_, expectedSize_); received_ = sdWritten_ = 0;
  mbedtls_sha256_init(&sha256_);
  shaInitialized_ = true;
  if (mbedtls_sha256_starts_ret(&sha256_, 0)) {
    errorCode_ = "hash_init"; errorMessage_ = "Kan ikke starte hashkontroll"; return false;
  }
  return true;
}

void FireGithubFirmwareManager::freeStaging() {
  staging_.attach(nullptr, 0);
  if (downloadBuffer_) heap_caps_free(downloadBuffer_);
  downloadBuffer_ = nullptr;
}

bool FireGithubFirmwareManager::writeBytes(const uint8_t* data, size_t length) {
  struct Hash {
    mbedtls_sha256_context* context;
    int update(const unsigned char* bytes, size_t count) {
      return mbedtls_sha256_update_ret(context, bytes, count);
    }
  } hash{&sha256_};
  if (!staging_.append(hash, data, length)) {
    errorCode_ = "staging_write"; errorMessage_ = "Nedlasting/hash feilet. SD er urort"; return false;
  }
  received_ = staging_.received();
  return true;
}

void FireGithubFirmwareManager::writeSd() {
  if (!staging_.readyForSd(client_.running()) || !stagedFile_) {
    fail("phase_guard", "SD-fasen kunne ikke starte"); return;
  }
  struct Hash { int update(const unsigned char*, size_t) { return 0; } } hash;
  const size_t amount = min<size_t>(kChunkSize, expectedSize_ - sdWritten_);
  if (amount) {
    const auto result = fireWriteSdBlock(stagedFile_, hash, downloadBuffer_ + sdWritten_, amount);
    if (!result.ok(amount)) {
      Serial.printf("FIRE SD short_write requested=%u written=%u errno=%d received=%lu position=%lu open=%u\n",
          unsigned(amount), unsigned(result.written), result.writeError, (unsigned long)sdWritten_,
          (unsigned long)stagedFile_.position(), bool(stagedFile_));
      fail("sd_short_write", "SD-skriving feilet. Gjeldende OS beholdt"); return;
    }
    sdWritten_ += amount;
  }
  emitStatus("Skriver til SD: " + String(sdWritten_ * 100ULL / expectedSize_) + "%");
  if (sdWritten_ == expectedSize_) { stagedFile_.close(); finishDownload(); }
}

void FireGithubFirmwareManager::fail(const String& code,
                                     const String& message) {
  if (stagedFile_) stagedFile_.close();
  if (shaInitialized_) {
    mbedtls_sha256_free(&sha256_);
    shaInitialized_ = false;
  }
  releaseClient();
  freeStaging();
  if (ownsStage_ && tempPath_.length()) SD.remove(tempPath_);
  if (ownsCatalogStage_ && catalogStage_.length()) SD.remove(catalogStage_);
  if (ownsGlobalStage_ && globalStage_.length()) SD.remove(globalStage_);
  ownsStage_ = ownsCatalogStage_ = ownsGlobalStage_ = false;
  Serial.printf("FIRE GitHub failure code=%s received=%lu expected=%lu\n", code.c_str(), (unsigned long)received_, (unsigned long)expectedSize_);
  state_ = State::Idle;
  overwriteExisting_ = false;
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

String FireGithubFirmwareManager::sha256File(const String& path, uint32_t expectedSize) const {
  File file = SD.open(path, FILE_READ);
  if (!file || !file.setBufferSize(512) || file.isDirectory() || file.size() != expectedSize) { file.close(); return ""; }
  mbedtls_sha256_context sha; mbedtls_sha256_init(&sha);
  bool ok = mbedtls_sha256_starts_ret(&sha, 0) == 0;
  uint8_t buffer[1024]; uint32_t count = 0;
  while (ok && count < expectedSize) {
    const size_t want = min<size_t>(sizeof(buffer), expectedSize - count);
    const size_t n = file.read(buffer, want);
    ok = n && n <= want && !mbedtls_sha256_update_ret(&sha, buffer, n);
    if (ok) count += n;
    delay(1);
  }
  file.close(); uint8_t digest[32] = {};
  if (mbedtls_sha256_finish_ret(&sha, digest)) ok = false;
  mbedtls_sha256_free(&sha);
  return ok && count == expectedSize ? hexDigest(digest, sizeof(digest)) : String();
}

bool FireGithubFirmwareManager::writeCatalog() {
  return writeCatalogFile(catalogStage_, ownsCatalogStage_) &&
      writeCatalogFile(globalStage_, ownsGlobalStage_);
}

bool FireGithubFirmwareManager::writeCatalogFile(const String& path, bool& owned) {
  File file = SD.open(path, FILE_WRITE);
  if (!file) return false;
  owned = true;
  if (!file.setBufferSize(512)) { file.close(); return false; }
  errno = 0;
  const size_t written = file.write(reinterpret_cast<const uint8_t*>(downloadCatalog_.c_str()), downloadCatalog_.length());
  const int error = errno;
  file.close();
  if (written != downloadCatalog_.length()) {
    Serial.printf("FIRE SD catalog_short_write requested=%u written=%u errno=%d\n",
        unsigned(downloadCatalog_.length()), unsigned(written), error);
    return false;
  }
  file = SD.open(path, FILE_READ);
  const size_t expected = downloadCatalog_.length();
  if (!file || !file.setBufferSize(512) || file.size() != expected) { file.close(); return false; }
  String actual; bool ok = actual.reserve(expected); uint8_t buffer[512];
  while (ok && actual.length() < expected) {
    const size_t want = min<size_t>(sizeof(buffer), expected - actual.length());
    const size_t n = file.read(buffer, want);
    ok = n && n <= want && actual.concat(reinterpret_cast<const char*>(buffer), n);
    delay(1);
  }
  file.close(); FireReleaseCatalog checked;
  return ok && actual == downloadCatalog_ && fireVerifyCatalog(actual, checked);
}

void FireGithubFirmwareManager::finishDownload() {
  if (!staging_.readyForSd(client_.running()) || sdWritten_ != expectedSize_) {
    fail("phase_guard", "SD-filen er ikke ferdig skrevet"); return;
  }
  emitStatus("Kontrollerer lagret SD-fil");
  const FireSdPublishPaths paths = {tempPath_.c_str(), finalPath_.c_str(), binaryBackup_.c_str(),
      catalogStage_.c_str(), catalogFinal_.c_str(), catalogBackup_.c_str()};
  const FireSdGlobalCatalogPaths global = {globalStage_.c_str(), "/firmware/catalog-v2.json", globalBackup_.c_str()};
  const auto result = fireFinalizeSdTriplet(SD, paths, global,
      [&]() { return sha256File(tempPath_, expectedSize_).equalsIgnoreCase(expectedHash_); },
      [&]() { return writeCatalog(); });
  if (result != FireSdPublishResult::Ok) {
    const char* code = result == FireSdPublishResult::BinaryReadback ? "sd_readback" :
        result == FireSdPublishResult::CatalogReadback ? "catalog_readback" :
        result == FireSdPublishResult::Restore ? "sd_restore" : "sd_activate";
    fail(code, "SD-kontroll/aktivering feilet. Tidligere kopier er beholdt"); return;
  }
  ownsStage_ = ownsCatalogStage_ = ownsGlobalStage_ = false;
  freeStaging();
  releaseClient(); state_ = State::Idle; overwriteExisting_ = false;
  Serial.printf("FIRE GitHub SD verified bytes=%lu\n", (unsigned long)received_);
  emitStatus("GitHub firmware kontrollert og lagret pa SD");
  emitResult(false, true, "Lagret og kontrollert pa SD. Ikke installert");
}

void FireGithubFirmwareManager::service(bool wifiConnected, bool sdReady) {
  io_.wifi = wifiConnected; io_.sd = sdReady;
  if (io_.poll(status_) && statusCallback_) statusCallback_(callbackContext_, status_);
  if (!io_.running && io_.completed.exchange(false) && resultCallback_)
    resultCallback_(callbackContext_, io_.kind, io_.ok, io_.message);
}
bool FireGithubFirmwareManager::launch() {
  io_.running = true;
  if (xTaskCreate(task, "fire-github", 16384, this, 1, nullptr) == pdPASS) return true;
  state_ = State::Idle; io_.running = false; emitStatus("Cannot start firmware worker"); return false;
}
void FireGithubFirmwareManager::task(void* context) {
  auto* self = static_cast<FireGithubFirmwareManager*>(context);
  // Initial wifi/sd values come from the last UI service tick.
  while (self->state_ != State::Idle) {
    self->serviceWorker(WiFi.isConnected(), self->io_.sd.load()); delay(2);
  }
  self->io_.running.store(false, std::memory_order_release);
  vTaskDelete(nullptr);
}
void FireGithubFirmwareManager::serviceWorker(bool wifiConnected, bool sdReady) {
  if (state_ == State::Idle) return;
  if (!manifestMode_ && !selectionVerified_) {
    FireReleaseCatalog checked; bool matched = false;
    if (fireVerifyCatalog(downloadCatalog_, checked)) {
      for (uint8_t i = 0; i < checked.count; ++i) {
        const auto& item = checked.files[i];
        if (item.name == selectedRelease_.name && item.hash == selectedRelease_.hash &&
            item.size == selectedRelease_.size && item.version == selectedRelease_.version &&
            item.path == selectedRelease_.path && item.commit == selectedRelease_.commit) matched = true;
      }
    }
    if (!matched) { fail("selection_invalid", "Utgaven matcher ikke signert katalog"); return; }
    selectionVerified_ = true;
    if (!prepareStaging()) { fail(errorCode_, errorMessage_); return; }
  }
  if (millis() - startedAt_ > kTransferTimeoutMs) {
    fail("timeout", "GitHub/SD transfer timed out"); return;
  }
  if (state_ == State::StoppingNetwork) {
    if (client_.running()) {
      if (millis() - phaseStartedAt_ >= 6000) fail("network_stop", "Nettverket ble ikke avsluttet. SD er urort");
      return;
    }
    if (!prepareDownload(sdReady)) { fail(errorCode_, errorMessage_); return; }
    Serial.printf("FIRE GitHub SD phase network_running=0 bytes=%lu internal_free=%u\n",
        (unsigned long)received_, unsigned(heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)));
    state_ = State::WriteSd; return;
  }
  if (state_ == State::WriteSd) {
    if (!sdReady) { fail("no_sd", "SD-kort er ikke tilgjengelig"); return; }
    writeSd(); return;
  }
  if (!wifiConnected && state_ == State::Connecting && millis() - startedAt_ < 15000) {
    emitStatus("GitHub: venter pa Wi-Fi"); return;
  }
  if (!wifiConnected) {
    fail("wifi_disconnected", "Wi-Fi disconnected");
    return;
  }
  if (state_ == State::Connecting) {
    if (time(nullptr) < 1700000000) {
      if (!clockSyncRequested_) {
        configTime(0, 0, "pool.ntp.org", "time.nist.gov");
        clockSyncRequested_ = true;
        clockSyncStartedAt_ = millis();
      }
      emitStatus("GitHub: syncing clock");
      if (millis() - clockSyncStartedAt_ < 12000) return;
      fail("clock_unset", "Device clock is not synchronized");
      return;
    }
    client_.secure(true);
    client_.setTimeout(5);
    if (!client_.connect(kGithubHost, 443, 5000)) {
      if (client_.connecting() || client_.stopping()) return;
      fail("connect_failed", "GitHub TLS connection failed");
      return;
    }
    const String request = "GET " + requestPath_ +
                  " HTTP/1.1\r\nHost: " + String(kGithubHost) +
                  "\r\nUser-Agent: FIRE-OS-Firmware\r\nAccept: */*\r\nAccept-Encoding: identity\r\n"
                  "Connection: close\r\n\r\n";
    if (client_.print(request) != request.length()) { fail("request_failed", "Cannot queue complete HTTP request"); return; }
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
    const String headers = headerBuffer_.substring(0, end + 4);
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
    if (!fire_firmware_http::validResponse(headers.c_str(), headers.length(), contentLength_)) {
      fail("http_invalid", "Ugyldig GitHub HTTP-svar"); return;
    }
    const int bodyStart = end + 4;
    const size_t availableBody = bodyStart < headerBuffer_.length()
                                     ? headerBuffer_.length() - bodyStart
                                     : 0;
    const size_t initial = min<size_t>(availableBody, contentLength_);
    if (availableBody > contentLength_) {
      fail("extra_bytes", "GitHub-svaret hadde ekstra data"); return;
    }
    if (manifestMode_) {
      manifestBody_ = initial > 0 ? headerBuffer_.substring(bodyStart) : "";
      state_ = State::ManifestBody;
      emitStatus("GitHub: reading catalog");
    } else {
      if (initial > 0 &&
          !writeBytes(reinterpret_cast<const uint8_t*>(headerBuffer_.c_str() +
                                                       bodyStart),
                      initial)) {
        fail(errorCode_, errorMessage_);
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
        fail(errorCode_, errorMessage_);
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
      phaseStartedAt_ = millis(); state_ = State::Verify;
    } else if (millis() - lastDataAt_ > kDataTimeoutMs) {
      fail("data_timeout", "GitHub firmware download timed out");
    }
  }
  if (state_ == State::Verify) {
    if (client_.available()) { fail("extra_bytes", "GitHub-svaret hadde ekstra data"); return; }
    if (client_.connected()) {
      if (millis() - phaseStartedAt_ >= 5000) fail("response_close", "GitHub-svaret ble ikke avsluttet");
      return;
    }
    uint8_t digest[32] = {};
    const int result = mbedtls_sha256_finish_ret(&sha256_, digest);
    mbedtls_sha256_free(&sha256_); shaInitialized_ = false;
    if (!staging_.verify(!result && contentLength_ == expectedSize_ &&
        hexDigest(digest, sizeof(digest)).equalsIgnoreCase(expectedHash_))) {
      fail("hash_mismatch", "GitHub-filen matcher ikke signert hash. SD er urort"); return;
    }
    releaseClient(); phaseStartedAt_ = millis(); state_ = State::StoppingNetwork;
    emitStatus("Nedlasting kontrollert. Avslutter nettverk");
  }
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
