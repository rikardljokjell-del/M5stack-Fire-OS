// Factory recovery has no dependency on FireOS, Lua, BLE or the AI backend.
#include <M5Unified.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <nvs_flash.h>
#include <esp_ota_ops.h>
#include <esp_image_format.h>
#include <esp_heap_caps.h>
#include <mbedtls/sha256.h>
#include "fire_async_client.h"
#include "fire_release.h"
#include "fire_ota.h"
#include "fire_config_store.h"

extern "C" bool verifyRollbackLater() { return true; }
namespace {
const char* host = "raw.githubusercontent.com";
const char* prefix = "/rikardljokjell-del/M5stack-Fire-OS/main/";
Preferences prefs;
FireAsyncClient network;
FireOta sdOta;
FireReleaseCatalog releases;
std::atomic<bool> busy{false}, startPortal{false}, portalActive{false};
std::atomic<uint8_t> phase{0}, progress{0};
std::atomic<bool> restartReady{false};
String ssid, password, apPassword, csrf, result = "Klar for gjenoppretting";
uint8_t selected = 0;
bool sdReady = false;
bool preferencesReady = false;
bool choosingSlot = false, catalogOnSd = false;
struct ExistingSlot { bool valid = false; String version; } existing[2];
uint8_t selectedSlot = 0;
uint32_t restartAt = 0;

bool bytes(uint8_t* out, size_t length) {
  uint32_t last = millis();
  size_t at = 0;
  while (at < length && millis() - last < 15000) {
    const int count = network.read(out + at, min<size_t>(2048, length - at));
    if (count > 0) { at += count; last = millis(); }
    else { if (!network.connected() && !network.available()) return false; delay(2); }
  }
  return at == length;
}
bool request(const String& path, size_t maximum, size_t& length) {
  network.stop(); network.secure(true);
  if (!network.connectBlocking(host, 443, 20000)) return false;
  String query = "GET " + path + " HTTP/1.1\r\nHost: " + host +
      "\r\nUser-Agent: FIRE-Recovery/1\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n";
  if (network.print(query) != query.length()) return false;
  String headers; const uint32_t started = millis();
  while (!headers.endsWith("\r\n\r\n") && headers.length() < 8192 && millis() - started < 15000) {
    int ch = network.read();
    if (ch >= 0) headers += static_cast<char>(ch);
    else { if (!network.connected()) return false; delay(2); }
  }
  if (!headers.endsWith("\r\n\r\n") || !(headers.startsWith("HTTP/1.1 200 ") || headers.startsWith("HTTP/1.0 200 "))) return false;
  headers.toLowerCase();
  // No redirects, transfer coding or decompression. Exactly one length header.
  const int at = headers.indexOf("\r\ncontent-length:");
  if (at < 0 || headers.indexOf("\r\ncontent-length:", at + 2) >= 0 || headers.indexOf("\r\ntransfer-encoding:") >= 0 || headers.indexOf("\r\ncontent-encoding:") >= 0) return false;
  String size = headers.substring(at + 17, headers.indexOf("\r\n", at + 2)); size.trim();
  if (!size.length() || size.length() > 8) return false;
  for (size_t i = 0; i < size.length(); ++i) if (!isdigit(size[i])) return false;
  length = strtoul(size.c_str(), nullptr, 10);
  return length > 0 && length <= maximum;
}
bool loadCatalog() {
  size_t length = 0;
  if (!request(String(prefix) + "firmware/index.json", 32768, length)) return false;
  char* body = static_cast<char*>(heap_caps_malloc(length + 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (!body) return false;
  const bool read = bytes(reinterpret_cast<uint8_t*>(body), length); body[length] = 0;
  const bool valid = read && strlen(body) == length && fireVerifyCatalog(String(body), releases);
  heap_caps_free(body); network.stop(); return valid;
}
bool installNetwork(const FireRelease& release) {
  if (!fireRecoveryLayout()) { result = "Ukjent partisjonsoppsett"; return false; }
  const auto* target = esp_partition_find_first(ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_APP_OTA_0, nullptr);
  if (!target || target == esp_ota_get_running_partition() || release.size > target->size) return false;
  size_t length = 0;
  if (!request(String(prefix) + release.path, release.size, length) || length != release.size) return false;
  esp_ota_handle_t handle = 0;
  if (esp_ota_begin(target, length, &handle) != ESP_OK) return false;
  mbedtls_sha256_context sha; mbedtls_sha256_init(&sha);
  bool ok = !mbedtls_sha256_starts_ret(&sha, 0);
  uint8_t block[2048], digest[32] = {}; uint32_t done = 0;
  phase = 3;
  while (ok && done < length) {
    const size_t count = min<size_t>(sizeof(block), length - done);
    ok = bytes(block, count) && !esp_ota_write(handle, block, count) && !mbedtls_sha256_update_ret(&sha, block, count);
    if (ok) { done += count; progress = done * 100ULL / length; }
    delay(1);
  }
  if (mbedtls_sha256_finish_ret(&sha, digest)) ok = false;
  mbedtls_sha256_free(&sha); network.stop();
  char hash[65]; for (size_t i = 0; i < 32; ++i) snprintf(hash + 2 * i, 3, "%02x", digest[i]);
  if (!ok || done != length || release.hash != hash) { esp_ota_abort(handle); result = "Hash/signalfeil. Redning beholdt"; return false; }
  if (esp_ota_end(handle) != ESP_OK || esp_ota_set_boot_partition(target) != ESP_OK) return false;
  return true;
}
bool inspectSlot(uint8_t slot, bool select);
void worker(void* action) {
  const uintptr_t command = reinterpret_cast<uintptr_t>(action);
  if (command == 3) {
    File file = SD.open("/firmware/catalog-v2.json", FILE_READ);
    String body; if (file && file.size() <= 32768) body = file.readString(); if (file) file.close();
    FireReleaseCatalog catalog;
    if (fireVerifyCatalog(body, catalog) && catalog.count) {
      releases = catalog; selected = 0; catalogOnSd = true;
      result = "SD-katalog kontrollert. Velg og trykk B";
    }
    else result = "Signert SD-katalog mangler";
    busy = false; vTaskDelete(nullptr); return;
  }
  if (command == 4) {
    inspectSlot(0, false); inspectSlot(1, false); selectedSlot = 0; choosingSlot = true;
    result = "Velg OS-slot. Driftstilstand ukjent";
    busy = false; vTaskDelete(nullptr); return;
  }
  if (command == 5) {
    if (inspectSlot(selectedSlot, true)) { result = "Starter valgt OS-slot"; restartReady = true; }
    else result = "Valgt slot har ikke gyldig image";
    busy = false; vTaskDelete(nullptr); return;
  }
  if (command == 2 && catalogOnSd) {
    if (selected < releases.count) sdOta.start("/firmware/" + releases.files[selected].name);
    busy = false; vTaskDelete(nullptr); return;
  }
  const bool install = command == 2;
  phase = 1;
  if (!WiFi.isConnected()) {
    WiFi.mode(WIFI_AP_STA); WiFi.begin(ssid.c_str(), password.c_str());
    const uint32_t started = millis();
    while (!WiFi.isConnected() && millis() - started < 15000) delay(25);
  }
  if (!WiFi.isConnected()) result = "Ingen Wi-Fi. Hold C for oppsett";
  else if (!install) {
    phase = 2;
    result = loadCatalog() ? "Katalog kontrollert. B installerer" : "Kunne ikke verifisere GitHub-katalog";
    catalogOnSd = false;
    selected = 0;
  } else {
    // The previously verified selection is immutable while busy is true.
    if (selected < releases.count && installNetwork(releases.files[selected])) {
      result = "Installert og kontrollert"; restartReady = true;
    } else if (result != "Hash/signalfeil. Redning beholdt") result = "Installering avbrutt. Redning beholdt";
  }
  network.stop(); phase = 0; busy.store(false, std::memory_order_release);
  vTaskDelete(nullptr);
}
void launch(uint8_t action) {
  if (busy.exchange(true)) return;
  if (xTaskCreate(worker, "recovery-fetch", 16384, reinterpret_cast<void*>(static_cast<uintptr_t>(action)), 1, nullptr) != pdPASS) {
    result = "Ikke nok minne"; busy = false;
  }
}
void portal(void*) {
  WebServer web(80);
  web.on("/", HTTP_GET, [&]() {
    web.sendHeader("Cache-Control", "no-store");
    web.send(200, "text/html; charset=utf-8", "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>FIRE redning</title><h1>Wi-Fi for redning</h1><form method=post action=/save><input name=csrf type=hidden value='" + csrf + "'><p>Nettverksnavn <input name=ssid maxlength=32 required></p><p>Passord <input name=password type=password maxlength=64></p><button>Lagre</button></form><p>Dette er separat fra vanlig FIRE OS. Ingen AI-konto trengs.</p>");
  });
  web.on("/save", HTTP_POST, [&]() {
    web.sendHeader("Cache-Control", "no-store");
    if (!portalActive || web.arg("csrf") != csrf) { web.send(403, "text/plain", "Avvist"); return; }
    if (busy || web.arg("ssid").length() < 1 || web.arg("ssid").length() > 32 || web.arg("password").length() > 64) { web.send(400, "text/plain", "Opptatt eller ugyldig oppsett"); return; }
    // Only this worker writes credentials; launch reads after portal is stopped.
    const String name = web.arg("ssid"), secret = web.arg("password");
    const bool stored = preferencesReady && prefs.putString("ssid", name) == name.length() &&
        prefs.putString("password", secret) == secret.length() && prefs.getString("ssid", "") == name && prefs.getString("password", "") == secret;
    if (!stored) { web.send(507, "text/plain; charset=utf-8", "Kunne ikke lagre. Kontroller rescuecfg; oppsettet er ikke bekreftet."); return; }
    web.send(200, "text/plain; charset=utf-8", "Lagret. Hold C på FIRE for å lukke oppsett, trykk B for å hente katalog.");
  });
  uint32_t opened = 0;
  while (true) {
    if (startPortal.exchange(false)) {
      WiFi.mode(WIFI_AP_STA); WiFi.softAP("FIRE-Recovery", apPassword.c_str());
      web.begin(); portalActive = true; opened = millis();
    }
    if (portalActive && millis() - opened > 600000) { web.stop(); WiFi.softAPdisconnect(true); portalActive = false; }
    if (portalActive) web.handleClient();
    delay(5);
  }
}
bool inspectSlot(uint8_t slot, bool select) {
  // CRC/image integrity is not proof of runtime health. The user picks A/B.
    const auto* part = esp_partition_find_first(ESP_PARTITION_TYPE_APP, static_cast<esp_partition_subtype_t>(ESP_PARTITION_SUBTYPE_APP_OTA_0 + slot), nullptr);
    if (!part) return false;
    esp_partition_pos_t pos = {part->address, part->size}; esp_image_metadata_t image = {};
    existing[slot].valid = esp_image_verify(ESP_IMAGE_VERIFY_SILENT, &pos, &image) == ESP_OK;
    esp_app_desc_t desc = {};
    existing[slot].version = esp_ota_get_partition_description(part, &desc) == ESP_OK ? String(desc.version) : String("Ukjent versjon");
    return existing[slot].valid && (!select || esp_ota_set_boot_partition(part) == ESP_OK);
}
}
void setup() {
  Serial.begin(115200); fireInitTrust();
  auto config = M5.config(); config.internal_mic = false; config.internal_spk = false;
  config.internal_imu = false; config.internal_rtc = false; M5.begin(config);
  M5.Display.setRotation(1); M5.Display.setFont(&fonts::efontJA_12);
  preferencesReady = fireOpenConfig(prefs, "recovery", "rescuecfg", 0xfb0000, 0x10000);
  if (preferencesReady) {
    ssid = prefs.getString("ssid", ""); password = prefs.getString("password", "");
  }
  else result = "Feil i separat recovery-lagring";
  char secret[33]; for (uint8_t i = 0; i < 4; ++i) snprintf(secret + i * 8, 9, "%08lx", (unsigned long)esp_random());
  csrf = secret; apPassword = String("fire-") + csrf.substring(0, 12);
  WiFi.persistent(false); WiFi.mode(WIFI_STA);
  sdReady = SD.begin(GPIO_NUM_4);
  xTaskCreate(portal, "recovery-setup", 6144, nullptr, 1, nullptr);
  enableLoopWDT();
}
void loop() {
  M5.update();
  if (!busy && !sdOta.busy()) {
    if (choosingSlot) {
      if (M5.BtnA.wasHold() || M5.BtnC.wasHold()) choosingSlot = false;
      else if (M5.BtnA.wasClicked() || M5.BtnC.wasClicked()) selectedSlot ^= 1;
      else if (M5.BtnB.wasClicked()) launch(5);
    } else if (M5.BtnC.wasHold()) {
      // A restart ends the portal cleanly and reloads stored rescue credentials.
      if (portalActive) ESP.restart(); else startPortal = true;
    } else if (!portalActive && M5.BtnA.wasHold()) launch(4);
    else if (!portalActive && M5.BtnB.wasHold() && sdReady) launch(3);
    else if (!portalActive && M5.BtnB.wasClicked()) launch(releases.count ? 2 : 1);
    else if (M5.BtnA.wasClicked() && releases.count) selected = (selected + releases.count - 1) % releases.count;
    else if (M5.BtnC.wasClicked() && releases.count) selected = (selected + 1) % releases.count;
  }
  if (sdOta.succeeded()) restartReady = true;
  if (restartReady && !restartAt) restartAt = millis();
  if (restartAt && millis() - restartAt > 1000) ESP.restart();
  static uint32_t drawn = 0;
  if (millis() - drawn > 150) {
    drawn = millis(); auto& d = M5.Display; d.fillScreen(0x0862); d.setTextColor(TFT_WHITE); d.setTextSize(2);
    d.drawString("FIRE redning", 12, 12); d.setTextSize(1);
    d.drawString("Uavhengig recovery v1", 12, 47);
    if (portalActive) {
      d.drawString("Wi-Fi: FIRE-Recovery", 12, 78); d.drawString("Passord: " + apPassword, 12, 101);
      d.drawString("Åpne 192.168.4.1", 12, 126); d.drawString("Hold C for å lukke og starte om", 12, 156);
    } else if (busy) d.drawString(String(phase == 1 ? "Kobler til Wi-Fi" : phase == 2 ? "Kontrollerer signert katalog" : "Installerer: ") + (phase == 3 ? String(progress.load()) + "%" : ""), 12, 92);
    else if (choosingSlot) {
      d.drawString(String("OS-slot ") + (selectedSlot ? "B / app1" : "A / app0"), 12, 78);
      d.drawString(existing[selectedSlot].version, 12, 103);
      d.drawString(existing[selectedSlot].valid ? "Image gyldig. Driftstilstand ukjent" : "Image ugyldig; kan ikke starte", 12, 130);
      d.drawString("A/C: bytt slot  B: start valgt", 12, 171);
      d.drawString("Hold A/C: tilbake", 12, 204);
    } else {
      if (releases.count) { d.drawString(releases.files[selected].version, 12, 77); d.drawString(releases.files[selected].name, 12, 100); }
      d.drawString(sdOta.busy() || sdOta.finished() ? sdOta.message() : result, 12, 135);
      d.drawString("B: hent katalog / installer valgt", 12, 161);
      d.drawString("Hold A: velg OS-slot  Hold B: SD", 12, 185);
      d.drawString("A/C: forrige/neste  Hold C: Wi-Fi", 12, 211);
    }
  }
  delay(5);
}
