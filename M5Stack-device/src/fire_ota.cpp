#include "fire_ota.h"
#include "fire_release.h"
#include "fire_firmware_http.h"
#include <esp_ota_ops.h>
#include <esp_image_format.h>
#include <mbedtls/sha256.h>

namespace {
constexpr char kHost[] = "raw.githubusercontent.com";
constexpr char kPrefix[] = "/rikardljokjell-del/M5stack-Fire-OS/main/";
constexpr uint32_t kTransferMs = 300000;
constexpr uint32_t kIdleMs = 15000;
// Covers every FireOta instance in this image, including recovery's SD path.
// A successful commit retains the lease until reboot.
std::atomic<bool> otaInFlight{false};

bool digestMatches(mbedtls_sha256_context& sha, const String& expected) {
  uint8_t digest[32] = {};
  if (mbedtls_sha256_finish_ret(&sha, digest) != 0) return false;
  char text[65] = {};
  for (size_t i = 0; i < sizeof(digest); ++i)
    snprintf(text + i * 2, 3, "%02x", digest[i]);
  return expected == text;
}
bool imageValid(const esp_partition_t* partition) {
  if (!partition) return false;
  esp_partition_pos_t location = {partition->address, partition->size};
  esp_image_metadata_t image = {};
  return esp_image_verify(ESP_IMAGE_VERIFY_SILENT, &location, &image) == ESP_OK;
}
bool filenameValid(const String& name) {
  if (!name.startsWith("fire-") || !name.endsWith(".bin") || name.length() > 64 ||
      name.indexOf("..") >= 0) return false;
  for (size_t i = 0; i < name.length(); ++i) {
    const char c = name[i];
    if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
          (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.')) return false;
  }
  return true;
}
}

bool FireOta::claim() {
  // A stopped asynchronous network worker may still hold this client's queues.
  if (network_.running() || ok_.load()) return false;
  bool expected = false;
  if (!busy_.compare_exchange_strong(expected, true)) return false;
  expected = false;
  if (!otaInFlight.compare_exchange_strong(expected, true)) {
    busy_ = false;
    return false;
  }
  error_ = ""; finished_ = false; ok_ = false; progress_ = 0; phase_ = 1;
  cancelRequested_ = false; decision_ = 0;
  return true;
}
bool FireOta::startFailed(const char* message) {
  error_ = message; finished_ = true; busy_ = false; otaInFlight = false;
  return false;
}
bool FireOta::launch() {
  if (xTaskCreate(task, "fire-ota", 12288, this, 1, nullptr) == pdPASS) return true;
  return startFailed("Ikke nok minne");
}
bool FireOta::start(const String& path) {
  if (!path.startsWith("/firmware/fire-") || path.indexOf("..") >= 0 ||
      path.indexOf('\\') >= 0 || !path.endsWith(".bin") || path.length() > 80 || !claim()) return false;
  github_ = false; path_ = path; signedCatalog_ = ""; filename_ = "";
  if (path_ != path) return startFailed("Ikke nok minne til firmwarevalg");
  return launch();
}
bool FireOta::startGithub(const String& signedCatalog, const String& filename) {
  if (!signedCatalog.length() || signedCatalog.length() > 32768 || !filenameValid(filename) || !claim()) return false;
  github_ = true; path_ = ""; signedCatalog_ = signedCatalog; filename_ = filename;
  if (signedCatalog_ != signedCatalog || filename_ != filename)
    return startFailed("Ikke nok minne til signert utgave");
  return launch();
}
bool FireOta::cancel() {
  if (!busy_) return false;
  uint8_t active = 0;
  if (!decision_.compare_exchange_strong(active, 1)) return false;
  cancelRequested_ = true;
  return true;
}
void FireOta::task(void* context) {
  static_cast<FireOta*>(context)->run();
  vTaskDelete(nullptr);
}

void FireOta::run() {
  bool success = false, otaOpen = false;
  esp_ota_handle_t ota = 0;
  File binary;
  const uint32_t started = millis();
  uint8_t buffer[2048];
  const auto interrupted = [&]() {
    if (decision_.load() == 1) { error_ = "Installering avbrutt. Gjeldende OS beholdt"; return true; }
    if (millis() - started > kTransferMs) { error_ = "Tidsavbrudd. Gjeldende OS beholdt"; return true; }
    return false;
  };
  do {
    FireReleaseCatalog catalog;
    String envelope;
    if (!github_) {
      // Each downloaded binary keeps its original signed catalog snapshot.
      // Prefer it strictly; an invalid sidecar must never fall back to a newer
      // global catalog and hide corruption. Legacy SD folders still work.
      const String sidecar = path_ + ".catalog-v2.json";
      File file = SD.open(SD.exists(sidecar) ? sidecar : String("/firmware/catalog-v2.json"), FILE_READ);
      if (!file || !file.size() || file.size() > 32768) {
        if (file) file.close(); error_ = "Signert katalog mangler"; break;
      }
      const size_t length = file.size();
      bool read = envelope.reserve(length);
      size_t total = 0;
      while (read && total < length && !interrupted()) {
        const size_t want = min<size_t>(sizeof(buffer), length - total);
        const size_t count = file.read(buffer, want);
        read = count && count <= want && envelope.concat(reinterpret_cast<const char*>(buffer), count);
        if (read) total += count;
        delay(1);
      }
      file.close();
      if (interrupted()) break;
      if (!read || total != length || envelope.length() != length) { error_ = "Kunne ikke lese signert katalog"; break; }
    }
    if (!fireVerifyCatalog(github_ ? signedCatalog_ : envelope, catalog)) { error_ = "Katalogsignaturen er ugyldig"; break; }
    FireRelease release;
    for (uint8_t i = 0; i < catalog.count; ++i) {
      const auto& candidate = catalog.files[i];
      if ((github_ && filename_ == candidate.name) || (!github_ && path_ == "/firmware/" + candidate.name)) {
        release = candidate; break;
      }
    }
    if (!release.size || !filenameValid(release.name)) { error_ = "Utgaven finnes ikke i signert katalog"; break; }
    if (!fireRecoveryLayout()) { error_ = "Krever engangs USB-migrering"; break; }
    const auto* factory = esp_partition_find_first(ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_APP_FACTORY, "recovery");
    if (!imageValid(factory)) { error_ = "Redningsappen er ikke gyldig"; break; }
    const auto* running = esp_ota_get_running_partition();
    if (!running) { error_ = "Ukjent OS-slot"; break; }
    if (running->subtype != ESP_PARTITION_SUBTYPE_APP_FACTORY) {
      esp_ota_img_states_t state = ESP_OTA_IMG_UNDEFINED;
      if (esp_ota_get_state_partition(running, &state) != ESP_OK ||
          (state != ESP_OTA_IMG_VALID && state != ESP_OTA_IMG_UNDEFINED)) {
        error_ = "Vent til gjeldende OS er helsegodkjent"; break;
      }
      const auto* selected = esp_ota_get_boot_partition();
      if (!selected || selected->address != running->address) { error_ = "Ny firmware venter allerede på omstart"; break; }
    }
    const auto* target = esp_ota_get_next_update_partition(nullptr);
    if (!target || target->type != ESP_PARTITION_TYPE_APP ||
        (target->subtype != ESP_PARTITION_SUBTYPE_APP_OTA_0 && target->subtype != ESP_PARTITION_SUBTYPE_APP_OTA_1) ||
        target->address == running->address || target->address == factory->address || release.size > target->size) {
      error_ = "Ingen trygg OTA-plass"; break;
    }

    if (github_) {
      phase_ = 2;
      network_.secure(true);
      if (!network_.connectBlocking(kHost, 443, 20000, &cancelRequested_)) {
        if (!interrupted()) error_ = "Kunne ikke koble sikkert til GitHub";
        break;
      }
      const String request = "GET " + String(kPrefix) + release.path +
          " HTTP/1.1\r\nHost: " + kHost +
          "\r\nUser-Agent: FIRE-OS-OTA/1\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n";
      if (network_.print(request) != request.length()) { error_ = "Kunne ikke sende GitHub-forespørsel"; break; }
      String headers;
      bool headerOk = headers.reserve(1024);
      const uint32_t headerStarted = millis();
      while (headerOk && !headers.endsWith("\r\n\r\n") && headers.length() < 8192 &&
             millis() - headerStarted < kIdleMs && !interrupted()) {
        const int value = network_.read();
        if (value < 0) {
          if (!network_.connected() && !network_.available()) break;
          delay(2); continue;
        }
        headerOk = value != 0 && headers.concat(static_cast<char>(value));
        if ((headers.length() & 255) == 0) delay(1);
      }
      if (interrupted()) break;
      if (!headerOk || !fire_firmware_http::validResponse(headers.c_str(), headers.length(), release.size)) {
        error_ = "GitHub svarte med ugyldig status eller størrelse"; break;
      }
    } else {
      // Retain pre-erase SD validation. The second streamed hash also catches
      // source changes between this check and writing to the inactive slot.
      if (!fireVerifyReleaseFile(path_, release)) { error_ = "Filen matcher ikke signert utgave"; break; }
      binary = SD.open(path_, FILE_READ);
      if (!binary || binary.size() != release.size) { error_ = "Kunne ikke åpne signert firmware"; break; }
    }
    if (interrupted()) break;
    // SDK 4.4 supports incremental sector erasure during sequential writes.
    // Its sentinel is not a size bound: every read/write is bounded below by
    // the independently signed release.size and the validated target size.
    if (esp_ota_begin(target, OTA_WITH_SEQUENTIAL_WRITES, &ota) != ESP_OK) { error_ = "Kunne ikke starte OTA"; break; }
    otaOpen = true;
    phase_ = 3;
    uint32_t written = 0, lastData = millis();
    mbedtls_sha256_context sha;
    mbedtls_sha256_init(&sha);
    bool ok = mbedtls_sha256_starts_ret(&sha, 0) == 0;
    while (ok && written < release.size && !interrupted()) {
      const size_t want = min<size_t>(sizeof(buffer), release.size - written);
      const int count = github_ ? network_.read(buffer, want) : static_cast<int>(binary.read(buffer, want));
      if (count <= 0) {
        if (!github_ || (!network_.connected() && !network_.available()) || millis() - lastData > kIdleMs) { ok = false; break; }
        delay(2); continue;
      }
      const size_t length = static_cast<size_t>(count);
      if (length > want || esp_ota_write(ota, buffer, length) != ESP_OK ||
          mbedtls_sha256_update_ret(&sha, buffer, length) != 0) { ok = false; break; }
      written += length; lastData = millis();
      progress_ = written * 100ULL / release.size;
      delay(1);
    }
    ok = ok && written == release.size && digestMatches(sha, release.hash);
    mbedtls_sha256_free(&sha);
    if (!github_ && binary && binary.size() != release.size) ok = false;
    if (binary) binary.close();
    if (interrupted()) break;
    if (!ok) { error_ = "Nedlasting eller skriving feilet. Gjeldende OS beholdt"; break; }
    if (github_) {
      // Connection: close was requested. Reject extra bytes as well as a
      // sender that refuses to finish its declared single response.
      const uint32_t closing = millis();
      while (!network_.available() && network_.connected() && millis() - closing < 5000 && !interrupted()) delay(2);
      if (interrupted()) break;
      if (network_.available() || network_.connected()) { error_ = "GitHub-svaret hadde uventet lengde"; break; }
      network_.stop();
    }
    const esp_err_t ended = esp_ota_end(ota);
    otaOpen = false;  // SDK frees the handle regardless of esp_ota_end result.
    if (ended != ESP_OK || !imageValid(target)) { error_ = "ESP32 image-kontroll feilet"; break; }

    phase_ = 4; progress_ = 0;
    mbedtls_sha256_init(&sha);
    ok = mbedtls_sha256_starts_ret(&sha, 0) == 0;
    uint32_t checked = 0;
    while (ok && checked < release.size && !interrupted()) {
      const size_t length = min<size_t>(sizeof(buffer), release.size - checked);
      if (esp_partition_read(target, checked, buffer, length) != ESP_OK ||
          mbedtls_sha256_update_ret(&sha, buffer, length) != 0) { ok = false; break; }
      checked += length; progress_ = checked * 100ULL / release.size;
      delay(1);
    }
    ok = ok && checked == release.size && digestMatches(sha, release.hash);
    mbedtls_sha256_free(&sha);
    if (interrupted()) break;
    if (!ok) { error_ = "Flash-kontrollen feilet. Gjeldende OS beholdt"; break; }

    // cancel() and the activation step race on one atomic decision. A cancel
    // accepted before this point cannot be followed by boot selection.
    uint8_t active = 0;
    if (!decision_.compare_exchange_strong(active, 2)) { interrupted(); break; }
    phase_ = 5;
    if (esp_ota_set_boot_partition(target) != ESP_OK) { error_ = "Kunne ikke velge ny firmware"; break; }
    success = true;
  } while (false);
  if (binary) binary.close();
  if (otaOpen) esp_ota_abort(ota);
  network_.stop();
  const uint32_t closing = millis();
  while (network_.running() && millis() - closing < 6000) delay(2);
  // Persistent network_ remains alive even if a slow TLS worker is stopping.
  // claim() refuses reuse until that worker has really exited.
  if (!success) otaInFlight = false;
  ok_ = success; finished_ = true; busy_ = false;
}

String FireOta::message() const {
  if (busy_) {
    if (phase_ == 1) return "Kontrollerer signatur og redning";
    if (phase_ == 2) return "Kobler sikkert til GitHub";
    if (phase_ == 4) return "Kontrollerer flash " + String(progress_.load()) + "%";
    if (phase_ == 5) return "Velger kontrollert firmware";
    return String(github_ ? "Henter og installerer " : "Installerer ") + String(progress_.load()) + "%";
  }
  if (finished_) return ok_ ? "Installert. Starter på nytt" : String(error_);
  return "";
}
