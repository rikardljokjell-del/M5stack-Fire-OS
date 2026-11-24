#include "fire_release.h"
#include "fire_json_guard.h"
#include <cJSON.h>
#include <esp_partition.h>
#include <esp_heap_caps.h>
#include <mbedtls/base64.h>
#include <mbedtls/pk.h>
#include <mbedtls/sha256.h>
#include <math.h>

extern const uint8_t fireReleaseKey[] asm("_binary_certs_release_public_pem_start");
namespace {
String text(const cJSON* o, const char* key) { auto* v = cJSON_GetObjectItemCaseSensitive(o, key); return cJSON_IsString(v) ? String(v->valuestring) : String(); }
bool number(const cJSON* o, const char* key, uint32_t expected) {
  auto* n = cJSON_GetObjectItemCaseSensitive(o, key); return cJSON_IsNumber(n) && n->valuedouble == expected;
}
bool keys(const cJSON* o, const char* allowed, unsigned count) {
  if (!cJSON_IsObject(o) || cJSON_GetArraySize(o) != count) return false;
  for (const auto* item = o->child; item; item = item->next) {
    if (String(allowed).indexOf(String(",") + item->string + ",") < 0) return false;
    for (const auto* other = item->next; other; other = other->next)
      if (!strcmp(item->string, other->string)) return false;
  }
  return true;
}
bool timestamp(const String& s) {
  if (s.length() != 20 || s[4] != '-' || s[7] != '-' || s[10] != 'T' || s[13] != ':' || s[16] != ':' || s[19] != 'Z') return false;
  for (size_t i = 0; i < 19; ++i)
    if (i != 4 && i != 7 && i != 10 && i != 13 && i != 16 && (s[i] < '0' || s[i] > '9')) return false;
  const int month = s.substring(5, 7).toInt(), day = s.substring(8, 10).toInt();
  const int year = s.substring(0, 4).toInt();
  if (month < 1 || month > 12 || !year) return false;
  const uint8_t days[] = {31,28,31,30,31,30,31,31,30,31,30,31};
  const int maximum = days[month - 1] + (month == 2 && (!(year % 400) || (!(year % 4) && year % 100)));
  return day >= 1 && day <= maximum && s.substring(11, 13).toInt() <= 23 &&
      s.substring(14, 16).toInt() <= 59 && s.substring(17, 19).toInt() <= 59;
}
bool hex(const String& s, size_t size) {
  if (s.length() != size) return false;
  for (size_t i = 0; i < size; ++i) if (!((s[i] >= '0' && s[i] <= '9') || (s[i] >= 'a' && s[i] <= 'f'))) return false;
  return true;
}
bool base64(const String& s) {
  if (!s.length() || s.length() % 4) return false;
  for (size_t i = 0; i < s.length(); ++i)
    if (!(isalnum(static_cast<unsigned char>(s[i])) || s[i] == '+' || s[i] == '/' || (s[i] == '=' && i >= s.length() - 2))) return false;
  return true;
}
String digest(const uint8_t* d) {
  char h[65]; for (size_t i = 0; i < 32; ++i) snprintf(h + i * 2, 3, "%02x", d[i]); h[64] = 0; return h;
}
}
bool fireVerifyCatalog(const String& envelope, FireReleaseCatalog& result) {
  if (!fireJsonSafe(envelope.c_str(), envelope.length(), 32768)) return false;
  cJSON* e = cJSON_ParseWithOpts(envelope.c_str(), nullptr, true);
  bool ok = keys(e, ",schema,algorithm,key_id,payload,signature,", 5) && number(e, "schema", 2) &&
      text(e, "algorithm") == "ecdsa-p256-sha256" && text(e, "key_id") == "fire-release-2026";
  const String body = text(e, "payload"), sig = text(e, "signature");
  ok = ok && base64(body) && base64(sig) && body.length() <= 21848 && sig.length() <= 112;
  size_t length = 0, signatureLength = 0;
  uint8_t signature[84] = {}, hash[32] = {};
  auto* raw = static_cast<uint8_t*>(heap_caps_malloc(16385, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  ok = ok && raw && !mbedtls_base64_decode(raw, 16384, &length,
      reinterpret_cast<const uint8_t*>(body.c_str()), body.length()) &&
      !mbedtls_base64_decode(signature, sizeof(signature), &signatureLength,
      reinterpret_cast<const uint8_t*>(sig.c_str()), sig.length());
  mbedtls_pk_context pk; mbedtls_pk_init(&pk);
  if (ok) {
    mbedtls_sha256_ret(raw, length, hash, 0);
    ok = !mbedtls_pk_parse_public_key(&pk, fireReleaseKey, strlen(reinterpret_cast<const char*>(fireReleaseKey)) + 1) &&
         mbedtls_pk_can_do(&pk, MBEDTLS_PK_ECDSA) &&
         !mbedtls_pk_verify(&pk, MBEDTLS_MD_SHA256, hash, sizeof(hash), signature, signatureLength);
  }
  mbedtls_pk_free(&pk); cJSON_Delete(e);
  cJSON* payload = nullptr;
  if (ok) { raw[length] = 0; ok = fireJsonSafe(reinterpret_cast<char*>(raw), length, 16384); if (ok) payload = cJSON_ParseWithOpts(reinterpret_cast<char*>(raw), nullptr, true); }
  if (raw) heap_caps_free(raw);
  ok = ok && keys(payload, ",schema,repository,target,layout,min_recovery,channel,files,", 7) && number(payload, "schema", 2) &&
      text(payload, "repository") == "rikardljokjell-del/M5stack-Fire-OS" &&
      text(payload, "target") == "m5stack-fire" && text(payload, "layout") == "fire-ab-recovery-v1" &&
      text(payload, "channel") == "stable" && number(payload, "min_recovery", 1);
  auto* files = cJSON_GetObjectItemCaseSensitive(payload, "files");
  ok = ok && cJSON_IsArray(files) && cJSON_GetArraySize(files) >= 1 && cJSON_GetArraySize(files) <= 8;
  FireReleaseCatalog candidate;
  for (auto* item = ok ? files->child : nullptr; item && ok; item = item->next) {
    FireRelease& f = candidate.files[candidate.count++];
    f.name = text(item, "name"); f.version = text(item, "version"); f.notes = text(item, "notes");
    f.hash = text(item, "sha256"); f.path = text(item, "path"); f.commit = text(item, "source_commit");
    const auto* size = cJSON_GetObjectItemCaseSensitive(item, "size_bytes");
    ok = keys(item, ",name,version,notes,path,published_at,sha256,size_bytes,source_commit,", 8) &&
        timestamp(text(item, "published_at")) && cJSON_IsString(cJSON_GetObjectItemCaseSensitive(item, "notes")) &&
        f.name.startsWith("fire-") && f.name.endsWith(".bin") &&
        f.name.length() <= 64 && f.name.indexOf("..") < 0 && f.path == "firmware/" + f.name &&
        hex(f.hash, 64) && hex(f.commit, 40) && f.version.length() && f.version.length() <= 40 &&
        f.notes.length() <= 240 && cJSON_IsNumber(size) && size->valuedouble >= 1 &&
        size->valuedouble <= 4194304 && floor(size->valuedouble) == size->valuedouble;
    for (size_t i = 0; i < f.name.length(); ++i) if (!(isalnum(static_cast<unsigned char>(f.name[i])) || f.name[i] == '.' || f.name[i] == '-' || f.name[i] == '_')) ok = false;
    for (size_t i = 0; i < f.version.length(); ++i) if (static_cast<uint8_t>(f.version[i]) < 32 || static_cast<uint8_t>(f.version[i]) > 126) ok = false;
    if (ok) f.size = static_cast<uint32_t>(size->valuedouble);
    for (uint8_t i = 0; i + 1 < candidate.count; ++i) if (candidate.files[i].name == f.name) ok = false;
  }
  if (ok) result = candidate;
  cJSON_Delete(payload); return ok;
}
bool fireVerifyReleaseFile(const String& path, FireRelease& release) {
  if (path != "/firmware/" + release.name) return false;
  File file = SD.open(path, FILE_READ);
  if (!file || file.size() != release.size) { if (file) file.close(); return false; }
  mbedtls_sha256_context sha; mbedtls_sha256_init(&sha); mbedtls_sha256_starts_ret(&sha, 0);
  uint8_t buffer[1024], hash[32]; uint32_t count = 0;
  while (file.available()) {
    size_t n = file.read(buffer, sizeof(buffer)); if (!n) break;
    mbedtls_sha256_update_ret(&sha, buffer, n); count += n; delay(1);
  }
  file.close(); mbedtls_sha256_finish_ret(&sha, hash); mbedtls_sha256_free(&sha);
  return count == release.size && digest(hash) == release.hash;
}
bool fireRecoveryLayout() {
  const auto* a = esp_partition_find_first(ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_APP_OTA_0, nullptr);
  const auto* b = esp_partition_find_first(ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_APP_OTA_1, nullptr);
  const auto* factory = esp_partition_find_first(ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_APP_FACTORY, "recovery");
  return a && b && factory && a->address == 0x10000 && b->address == 0x650000 &&
      a->size == 0x640000 && b->size == 0x640000 && factory->address == 0xc90000 && factory->size == 0x300000;
}
