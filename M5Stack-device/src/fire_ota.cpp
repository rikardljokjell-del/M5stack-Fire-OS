#include "fire_ota.h"
#include "fire_release.h"
#include <esp_ota_ops.h>
#include <esp_image_format.h>
#include <mbedtls/sha256.h>

bool FireOta::start(const String& path) {
  if (busy_ || !path.startsWith("/firmware/fire-") || path.indexOf("..") >= 0 ||
      path.indexOf('\\') >= 0 || !path.endsWith(".bin") || path.length() > 80) return false;
  path_ = path; error_ = ""; finished_ = ok_ = false; busy_ = true; progress_ = 0; phase_ = 1;
  if (xTaskCreate(task, "fire-ota", 12288, this, 1, nullptr) != pdPASS) {
    busy_ = false; finished_ = true; error_ = "Ikke nok minne"; return false;
  }
  return true;
}
void FireOta::task(void* context) { static_cast<FireOta*>(context)->run(); vTaskDelete(nullptr); }
void FireOta::run() {
  bool success = false;
  do {
    if (!fireRecoveryLayout()) { error_ = "Krever engangs USB-migrering"; break; }
    auto* factory = esp_partition_find_first(ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_APP_FACTORY, "recovery");
    esp_partition_pos_t location = {factory->address, factory->size};
    esp_image_metadata_t image = {};
    if (esp_image_verify(ESP_IMAGE_VERIFY_SILENT, &location, &image) != ESP_OK) { error_ = "Redningsappen er ikke gyldig"; break; }
    File catalogFile = SD.open("/firmware/catalog-v2.json", FILE_READ);
    if (!catalogFile || catalogFile.size() > 32768) { if (catalogFile) catalogFile.close(); error_ = "Signert katalog mangler"; break; }
    String envelope; envelope.reserve(catalogFile.size());
    uint8_t buffer[2048];
    while (catalogFile.available()) {
      const size_t count = catalogFile.read(buffer, sizeof(buffer)); if (!count) break;
      envelope.concat(reinterpret_cast<char*>(buffer), count); delay(1);
    }
    catalogFile.close();
    FireReleaseCatalog catalog;
    if (!fireVerifyCatalog(envelope, catalog)) { error_ = "Katalogsignaturen er ugyldig"; break; }
    FireRelease* release = nullptr;
    for (uint8_t i = 0; i < catalog.count; ++i) if (path_ == "/firmware/" + catalog.files[i].name) release = &catalog.files[i];
    if (!release || !fireVerifyReleaseFile(path_, *release)) { error_ = "Filen matcher ikke signert utgave"; break; }
    const auto* target = esp_ota_get_next_update_partition(nullptr);
    const auto* running = esp_ota_get_running_partition();
    if (!target || target == running || target->subtype == ESP_PARTITION_SUBTYPE_APP_FACTORY || release->size > target->size) { error_ = "Ingen trygg OTA-plass"; break; }
    File binary = SD.open(path_, FILE_READ); esp_ota_handle_t ota = 0;
    if (!binary || esp_ota_begin(target, release->size, &ota) != ESP_OK) { if (binary) binary.close(); error_ = "Kunne ikke starte OTA"; break; }
    phase_ = 2; uint32_t written = 0; bool ok = true;
    mbedtls_sha256_context sha; mbedtls_sha256_init(&sha);
    ok = mbedtls_sha256_starts_ret(&sha, 0) == 0;
    while (ok && written < release->size) {
      const size_t n = binary.read(buffer, min<size_t>(sizeof(buffer), release->size - written));
      if (!n || esp_ota_write(ota, buffer, n) != ESP_OK || mbedtls_sha256_update_ret(&sha, buffer, n)) { ok = false; break; }
      written += n; progress_ = written * 100ULL / release->size; delay(1);
    }
    binary.close();
    uint8_t digest[32]; char hash[65];
    if (mbedtls_sha256_finish_ret(&sha, digest)) ok = false;
    mbedtls_sha256_free(&sha);
    for (size_t i = 0; i < 32; ++i) snprintf(hash + i * 2, 3, "%02x", digest[i]);
    if (written != release->size || release->hash != hash) ok = false;
    if (!ok) { esp_ota_abort(ota); error_ = "Skriving feilet. Gjeldende OS beholdt"; break; }
    if (esp_ota_end(ota) != ESP_OK) { error_ = "Image-kontroll feilet"; break; }
    if (esp_ota_set_boot_partition(target) != ESP_OK) { error_ = "Kunne ikke velge ny firmware"; break; }
    success = true;
  } while (false);
  ok_ = success; finished_ = true; busy_ = false;
}
String FireOta::message() const {
  if (busy_) return phase_ == 1 ? "Kontrollerer signatur og redning" : "Installerer " + String(progress_.load()) + "%";
  if (finished_) return ok_ ? "Installert. Starter på nytt" : String(error_);
  return "";
}
