#include "fire_home.h"
#include "fire_async_client.h"
#include "fire_json_guard.h"
#include <WiFi.h>
#include <cJSON.h>
#include <esp_heap_caps.h>
#include <math.h>
#include <time.h>
#include <nvs_flash.h>
#include "fire_worker_diagnostics.h"
#include "fire_config_store.h"

extern "C" esp_err_t arduino_esp_crt_bundle_attach(void* config);
namespace {
constexpr uint16_t bg = 0x0862, panel = 0x10E3, ink = 0xEF7E, muted = 0x94F4;
constexpr uint16_t accent = 0x4F5A, amber = 0xFDA8;
const char* operations[] = {"on", "off", "brightness", "temperature", "heat_mode", "run"};
const cJSON* field(const cJSON* obj, const char* key) { return cJSON_GetObjectItemCaseSensitive(obj, key); }
String str(const cJSON* obj, const char* key) { const auto* v = field(obj, key); return cJSON_IsString(v) ? String(v->valuestring) : String(); }
bool identifier(const String& id) {
  if (!id.length() || id.length() > 32) return false;
  for (size_t i = 0; i < id.length(); ++i)
    if (!((id[i] >= 'a' && id[i] <= 'z') || (id[i] >= '0' && id[i] <= '9') ||
          (i && (id[i] == '_' || id[i] == '-')))) return false;
  return true;
}
bool hex(const String& s, size_t minimum, size_t maximum) {
  if (s.length() < minimum || s.length() > maximum) return false;
  for (size_t i = 0; i < s.length(); ++i)
    if (!((s[i] >= '0' && s[i] <= '9') || (s[i] >= 'a' && s[i] <= 'f'))) return false;
  return true;
}
bool keys(const cJSON* obj, const char* allowed) {
  if (!cJSON_IsObject(obj)) return false;
  for (auto* item = obj->child; item; item = item->next) {
    String needle = String(",") + item->string + ",";
    if (String(allowed).indexOf(needle) < 0) return false;
    for (auto* other = item->next; other; other = other->next)
      if (!strcmp(item->string, other->string)) return false;
  }
  return true;
}
bool integer(const cJSON* obj, const char* key, double lo, double hi) {
  const auto* v = field(obj, key);
  return cJSON_IsNumber(v) && isfinite(v->valuedouble) && v->valuedouble >= lo &&
         v->valuedouble <= hi && floor(v->valuedouble) == v->valuedouble;
}
bool fresh(const cJSON* obj) {
  if (!integer(obj, "issued", 1700000000, 4102444800.0) || !integer(obj, "ttl", 1, 90)) return false;
  const double now = time(nullptr), issued = field(obj, "issued")->valuedouble;
  return now >= 1700000000 && issued <= now + 2 && now <= issued + field(obj, "ttl")->valuedouble;
}
String rid() { char value[17]; snprintf(value, sizeof(value), "%08lx%08lx", (unsigned long)esp_random(), (unsigned long)esp_random()); return value; }
uint8_t operation(const String& name) { for (uint8_t i = 0; i < 6; ++i) if (name == operations[i]) return 1 << i; return 0; }
void label(M5Canvas& c, int x, int y, const String& text, uint16_t color = ink, uint8_t scale = 1) {
  c.setTextDatum(TL_DATUM); c.setTextColor(color, bg); c.setTextSize(scale); c.drawString(text, x, y);
}
}

void FireHome::begin() {
  preferencesReady_ = fireOpenConfig(preferences_, "firehome", "homecfg", 0xf90000, 0x20000);
  if (!preferencesReady_) { status_ = "Home krever migrering / lagringskontroll"; return; }
  profile_ = min<uint8_t>(preferences_.getUChar("profile", 0), 1);
  routeMode_ = min<uint8_t>(preferences_.getUChar("route", 0), 2);
  layout_ = min<uint8_t>(preferences_.getUChar("layout", 0), 1);
  configMutex_ = xSemaphoreCreateMutex();
  inbox_ = xQueueCreate(4, sizeof(Message)); outgoing_ = xQueueCreate(2, sizeof(Outgoing));
  for (uint8_t i = 0; i < 2; ++i) {
    String saved = preferences_.getString(i ? "camper" : "home", "");
    if (saved.length()) { String error; configure(saved, error); }
  }
  if (configMutex_ && inbox_ && outgoing_) xTaskCreate(task, "fire-home", 8192, this, 1, nullptr);
}
bool FireHome::configured() const {
  const auto& p = profiles_[profile_];
  return identifier(p.site) && identifier(p.device) && (p.localHost.length() || p.remoteHost.length());
}
bool FireHome::configure(const String& body, String& error) {
  if (!preferencesReady_) { error = "Home-lagring er ikke klar"; return false; }
  if (!fireJsonSafe(body.c_str(), body.length(), 8192)) { error = "Ugyldig oppsett"; return false; }
  cJSON* root = cJSON_ParseWithOpts(body.c_str(), nullptr, true);
  bool ok = keys(root, ",profile,site,device,local_host,remote_host,local_user,local_password,remote_user,remote_password,ca,") && integer(root, "profile", 0, 1);
  uint8_t index = ok ? field(root, "profile")->valueint : 0;
  Profile p = profiles_[index];
  p.site = str(root, "site"); p.device = str(root, "device");
  p.localHost = str(root, "local_host"); p.remoteHost = str(root, "remote_host");
  p.localUser = str(root, "local_user"); p.remoteUser = str(root, "remote_user");
  if (str(root, "local_password").length()) p.localPassword = str(root, "local_password");
  if (str(root, "remote_password").length()) p.remotePassword = str(root, "remote_password");
  p.ca = str(root, "ca");
  ok = ok && identifier(p.site) && identifier(p.device) &&
      (p.localHost.length() || p.remoteHost.length()) &&
      (!p.localHost.length() || fireNetworkEndpointValid(p.localHost)) &&
      (!p.remoteHost.length() || fireNetworkEndpointValid(p.remoteHost)) &&
      p.localUser.length() <= 64 && p.remoteUser.length() <= 64 &&
      p.localPassword.length() <= 128 && p.remotePassword.length() <= 128 &&
      p.ca.length() <= 4096 && (!p.ca.length() || p.ca.startsWith("-----BEGIN CERTIFICATE-----")) &&
      (!p.localHost.length() || (p.localUser.length() && p.localPassword.length())) &&
      (!p.remoteHost.length() || (p.remoteUser.length() && p.remotePassword.length()));
  if (ok && configMutex_ && xSemaphoreTake(configMutex_, 0) == pdTRUE) {
    // Persist one complete validated document; credentials are never exported.
    cJSON_DeleteItemFromObjectCaseSensitive(root, "local_password");
    cJSON_DeleteItemFromObjectCaseSensitive(root, "remote_password");
    cJSON_AddStringToObject(root, "local_password", p.localPassword.c_str());
    cJSON_AddStringToObject(root, "remote_password", p.remotePassword.c_str());
    char* encoded = cJSON_PrintUnformatted(root);
    const char* key = index ? "camper" : "home";
    ok = encoded && preferences_.putString(key, encoded) == strlen(encoded) && preferences_.getString(key, "") == encoded;
    if (encoded) cJSON_free(encoded);
    if (ok) { profiles_[index] = p; ++generation_; invalidate(); status_ = "Oppsett lagret"; }
    else { error = "Kunne ikke lagre Home-oppsett"; status_ = error; }
    xSemaphoreGive(configMutex_);
  } else { ok = false; error = "Ugyldig oppsett eller opptatt"; }
  cJSON_Delete(root); return ok;
}
void FireHome::persist() {
  preferences_.putUChar("profile", profile_); preferences_.putUChar("route", routeMode_);
  preferences_.putUChar("layout", layout_); ++generation_;
}
void FireHome::invalidate() {
  catalogValid_ = false; stateAt_ = 0; confirm_ = false; pendingRid_ = ""; count_ = 0; focus_ = 0;
}
bool FireHome::current() const {
  return online_ && catalogValid_ && catalogAt_ && millis() - catalogAt_ <= catalogTtl_ * 1000 &&
      (!remote_ || remoteAllowed_) && time(nullptr) >= 1700000000;
}
bool FireHome::stateFresh() const {
  return current() && stateAt_ && millis() - stateAt_ <= stateTtl_ * 1000;
}
bool FireHome::queue(const String& body) {
  if (body.length() > 512 || !online_) return false;
  Outgoing out = {}; strlcpy(out.body, body.c_str(), sizeof(out.body));
  out.generation = generation_; out.connection = connection_;
  return xQueueSend(outgoing_, &out, 0) == pdTRUE;
}
void FireHome::task(void* context) { static_cast<FireHome*>(context)->run(); }
void FireHome::run() {
  uint32_t measuredAt = 0;
  uint32_t backoff = 1000;
  bool tryRemote = false;
  for (;;) {
    if (!wanted_) { delay(100); continue; }
    Profile p; uint8_t mode; uint32_t generation;
    xSemaphoreTake(configMutex_, portMAX_DELAY); p = profiles_[profile_]; mode = routeMode_; generation = generation_; xSemaphoreGive(configMutex_);
    const bool remote = mode == 2 || (mode == 0 && (tryRemote || !p.localHost.length()));
    const String host = fireNetworkHost(remote ? p.remoteHost : p.localHost);
    if (!host.length() || time(nullptr) < 1700000000) {
      if (time(nullptr) < 1700000000) configTime(0, 0, "pool.ntp.org", "time.google.com");
      delay(1000); tryRemote = !tryRemote; continue;
    }
    remote_ = remote;
    connectionGeneration_ = generation;
    ++connection_;
    topicPrefix_ = "fire/home/v1/" + p.site + "/" + p.device + (remote ? "/remote/" : "/local/");
    String uri = (remote ? "wss://" : "mqtts://") + host + (remote ? ":443/mqtt" : ":8883");
    esp_mqtt_client_config_t config = {};
    config.uri = uri.c_str(); config.username = (remote ? p.remoteUser : p.localUser).c_str();
    config.password = (remote ? p.remotePassword : p.localPassword).c_str();
    config.keepalive = 30; config.disable_clean_session = false; config.disable_auto_reconnect = true;
    config.buffer_size = 2048; config.out_buffer_size = 1024; config.task_stack = 8192;
    config.network_timeout_ms = 5000;
    // Application ACK expires after 10 s and tears this client down. The
    // MQTT outbox must not retransmit an uncertain action before that reset.
    config.message_retransmit_timeout = 60000;
    if (p.ca.length() && !remote) config.cert_pem = p.ca.c_str();
    else config.crt_bundle_attach = arduino_esp_crt_bundle_attach;
    auto client = esp_mqtt_client_init(&config);
    if (!client) { delay(1000); continue; }
    esp_mqtt_client_register_event(client, MQTT_EVENT_ANY, event, this);
    esp_mqtt_client_start(client);
    uint32_t started = millis(); bool connectedOnce = false;
    while (wanted_ && generation == generation_) {
      if (online_) { connectedOnce = true; backoff = 1000; }
      if ((connectedOnce && !online_) || (!connectedOnce && millis() - started > 10000) ||
          (mode == 0 && remote && millis() - started > 60000)) break;
      Outgoing out;
      if (online_ && xQueueReceive(outgoing_, &out, 0) == pdTRUE && out.generation == generation_ && out.connection == connection_)
        esp_mqtt_client_publish(client, (topicPrefix_ + "request").c_str(), out.body, 0, 1, false);
      fireMeasureWorker("home", measuredAt); delay(10);
    }
    online_ = false;
    esp_mqtt_client_stop(client); esp_mqtt_client_destroy(client);
    Outgoing discarded; while (xQueueReceive(outgoing_, &discarded, 0) == pdTRUE) {}
    if (assembly_) heap_caps_free(assembly_); assembly_ = nullptr;
    tryRemote = mode == 0 ? !remote : false;
    const uint32_t wait = millis();
    while (wanted_ && generation == generation_ && millis() - wait < backoff + esp_random() % 250) delay(20);
    backoff = min<uint32_t>(30000, backoff * 2);
  }
}
void FireHome::event(void* context, esp_event_base_t, int32_t, void* data) {
  static_cast<FireHome*>(context)->handleEvent(static_cast<esp_mqtt_event_handle_t>(data));
}
void FireHome::handleEvent(esp_mqtt_event_handle_t e) {
  if (e->event_id == MQTT_EVENT_CONNECTED) {
    uint32_t measure = 0; fireMeasureWorker("mqtt", measure);
    for (const char* topic : {"catalog", "state", "ack"})
      esp_mqtt_client_subscribe(e->client, (topicPrefix_ + topic).c_str(), 1);
    online_ = true; helloNeeded_ = true; return;
  }
  if (e->event_id == MQTT_EVENT_DISCONNECTED || e->event_id == MQTT_EVENT_ERROR) { online_ = false; return; }
  if (e->event_id != MQTT_EVENT_DATA) return;
  if (e->current_data_offset == 0) {
    if (assembly_) heap_caps_free(assembly_); assembly_ = nullptr;
    String topic; for (int i = 0; i < e->topic_len; ++i) topic += e->topic[i];
    assemblyKind_ = topic == topicPrefix_ + "catalog" ? 1 : topic == topicPrefix_ + "state" ? 2 : topic == topicPrefix_ + "ack" ? 3 : 0;
    const uint32_t limit = assemblyKind_ == 1 ? 8192 : assemblyKind_ == 2 ? 4096 : 512;
    if (!assemblyKind_ || e->total_data_len <= 0 || static_cast<uint32_t>(e->total_data_len) > limit) return;
    assemblyExpected_ = e->total_data_len; assemblyLength_ = 0;
    assembly_ = static_cast<char*>(heap_caps_malloc(assemblyExpected_ + 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  }
  if (!assembly_) return;
  if (e->current_data_offset != assemblyLength_ || e->data_len < 0 ||
      assemblyLength_ + e->data_len > assemblyExpected_) { heap_caps_free(assembly_); assembly_ = nullptr; return; }
  memcpy(assembly_ + assemblyLength_, e->data, e->data_len); assemblyLength_ += e->data_len;
  if (assemblyLength_ == assemblyExpected_) {
    assembly_[assemblyLength_] = 0;
    Message msg = {assemblyKind_, assemblyLength_, assembly_, connectionGeneration_, remote_.load(), connection_.load()};
    if (xQueueSend(inbox_, &msg, 0) != pdTRUE) heap_caps_free(assembly_);
    assembly_ = nullptr;
  }
}
void FireHome::service(bool wifiConnected, bool allowNetwork) {
  wanted_ = wifiConnected && allowNetwork && configured();
  if (helloNeeded_.exchange(false)) {
    catalogValid_ = false; stateAt_ = 0;
    if (pendingRid_.length()) { pendingRid_ = ""; status_ = "Ukjent resultat"; }
    queue("{\"v\":1,\"type\":\"hello\",\"rid\":\"" + rid() + "\"}");
    helloAt_ = millis(); helloAttempts_ = 0;
  }
  const uint32_t helloWait[] = {2000, 5000, 10000, 30000};
  if (online_ && (!catalogValid_ || millis() - catalogAt_ > catalogTtl_ * 1000) &&
      millis() - helloAt_ >= helloWait[helloAttempts_]) {
    queue("{\"v\":1,\"type\":\"hello\",\"rid\":\"" + rid() + "\"}");
    helloAt_ = millis(); helloAttempts_ = min<uint8_t>(3, helloAttempts_ + 1);
  }
  Message msg;
  if (inbox_ && xQueueReceive(inbox_, &msg, 0) == pdTRUE) {
    // MQTT payload must be one complete JSON text, never an embedded NUL prefix.
    if (msg.generation == generation_ && msg.remote == remote_ && msg.connection == connection_ &&
        fireJsonSafe(msg.body, msg.length, msg.kind == 1 ? 8192 : msg.kind == 2 ? 4096 : 512)) {
      if (msg.kind == 1) catalog(msg.body); else if (msg.kind == 2) state(msg.body); else acknowledge(msg.body);
    }
    heap_caps_free(msg.body);
  }
  if (pendingRid_.length() && (millis() - pendingAt_ >= 10000 || !online_)) {
    pendingRid_ = ""; status_ = "Ukjent resultat";
    catalogValid_ = false; stateAt_ = 0; ++generation_;
  }
}

bool FireHome::catalog(const char* body) {
  if (!fireJsonSafe(body, strlen(body), 8192)) return false;
  cJSON* root = cJSON_ParseWithOpts(body, nullptr, true);
  const auto& profile = profiles_[profile_];
  bool ok = keys(root, ",v,site,device,route,epoch,rev,issued,ttl,last_seq,remote_allowed,cards,") &&
      integer(root, "v", 1, 1) && fresh(root) &&
      str(root, "site") == profile.site && str(root, "device") == profile.device &&
      str(root, "route") == (remote_ ? "remote" : "local") &&
      hex(str(root, "epoch"), 16, 16) && hex(str(root, "rev"), 8, 32) &&
      integer(root, "last_seq", 0, 2147483647) && cJSON_IsBool(field(root, "remote_allowed"));
  const cJSON* list = field(root, "cards");
  ok = ok && cJSON_IsArray(list) && cJSON_GetArraySize(list) <= 12;
  Card next[12]; uint8_t count = 0;
  for (const auto* item = ok ? list->child : nullptr; item && ok; item = item->next) {
    Card& c = next[count++];
    c.id = str(item, "id"); c.name = str(item, "name"); c.kind = str(item, "kind"); c.unit = str(item, "unit");
    size_t characters = 0;
    for (size_t i = 0; i < c.name.length(); ++i) if ((static_cast<uint8_t>(c.name[i]) & 0xC0) != 0x80) ++characters;
    size_t unitCharacters = 0;
    for (size_t i = 0; i < c.unit.length(); ++i) if ((static_cast<uint8_t>(c.unit[i]) & 0xC0) != 0x80) ++unitCharacters;
    ok = keys(item, ",id,name,kind,unit,ops,min,max,step,modes,") && identifier(c.id) &&
        c.name.length() && c.name.length() <= 96 && characters <= 32 && c.unit.length() <= 24 && unitCharacters <= 12 &&
        (c.kind == "sensor" || c.kind == "binary_sensor" || c.kind == "light" || c.kind == "switch" ||
         c.kind == "climate" || c.kind == "script" || c.kind == "scene");
    for (uint8_t i = 0; i + 1 < count; ++i) if (next[i].id == c.id) ok = false;
    const cJSON* ops = field(item, "ops"); ok = ok && cJSON_IsArray(ops) && cJSON_GetArraySize(ops) <= 6;
    for (const auto* op = cJSON_IsArray(ops) ? ops->child : nullptr; op; op = op->next) {
      const uint8_t bit = cJSON_IsString(op) ? operation(op->valuestring) : 0;
      if (!bit || c.ops & bit) ok = false; c.ops |= bit;
    }
    const uint8_t permitted = c.kind == "light" ? 7 : c.kind == "switch" ? 3 :
        c.kind == "climate" ? 24 : c.kind == "script" || c.kind == "scene" ? 32 : 0;
    if (c.ops & ~permitted) ok = false;
    if (c.kind != "climate" && (field(item, "min") || field(item, "max") || field(item, "step") || field(item, "modes"))) ok = false;
    if (c.ops & 8) {
      const auto* lo = field(item, "min"), *hi = field(item, "max"), *step = field(item, "step");
      if (!cJSON_IsNumber(lo) || !cJSON_IsNumber(hi) || !cJSON_IsNumber(step) ||
          !isfinite(lo->valuedouble) || !isfinite(hi->valuedouble) || !isfinite(step->valuedouble) ||
          lo->valuedouble >= hi->valuedouble || step->valuedouble <= 0 || step->valuedouble > hi->valuedouble - lo->valuedouble) ok = false;
      else { c.minimum = lo->valuedouble; c.maximum = hi->valuedouble; c.step = step->valuedouble; }
    }
    const cJSON* modes = field(item, "modes");
    if (c.ops & 16) {
      if (!cJSON_IsArray(modes) || cJSON_GetArraySize(modes) < 1 || cJSON_GetArraySize(modes) > 3) ok = false;
      for (const auto* mode = cJSON_IsArray(modes) ? modes->child : nullptr; mode; mode = mode->next) {
        String m = cJSON_IsString(mode) ? String(mode->valuestring) : String();
        uint8_t bit = m == "off" ? 1 : m == "heat" ? 2 : m == "auto" ? 4 : 0;
        if (!bit || c.modes & bit) ok = false; c.modes |= bit;
      }
    }
  }
  if (ok) {
    const String epoch = str(root, "epoch"), rev = str(root, "rev");
    if (epoch != epoch_ || rev != revision_) { stateAt_ = 0; confirm_ = editing_ = false; }
    if (epoch != epoch_) {
      lastSeq_ = 0;
      if (pendingRid_.length()) { pendingRid_ = ""; status_ = "Ukjent resultat"; }
    }
    epoch_ = epoch; revision_ = rev;
    lastSeq_ = max<uint32_t>(lastSeq_, field(root, "last_seq")->valueint);
    stateAt_ = 0;
    count_ = count; for (uint8_t i = 0; i < count; ++i) cards_[i] = next[i];
    remoteAllowed_ = cJSON_IsTrue(field(root, "remote_allowed"));
    catalogTtl_ = max<int>(0, field(root, "issued")->valuedouble + field(root, "ttl")->valueint - time(nullptr));
    catalogAt_ = millis(); catalogValid_ = true; reorder();
    if (!pendingRid_.length()) status_ = remote_ && !remoteAllowed_ ? "Fjerntilgang sperret" : "Tilkoblet";
  } else { catalogValid_ = false; status_ = "Ugyldig katalog"; }
  cJSON_Delete(root); return ok;
}
bool FireHome::state(const char* body) {
  if (!fireJsonSafe(body, strlen(body), 4096)) return false;
  cJSON* root = cJSON_ParseWithOpts(body, nullptr, true);
  bool ok = keys(root, ",v,epoch,rev,issued,ttl,values,") && integer(root, "v", 1, 1) && fresh(root) &&
      catalogValid_ && str(root, "epoch") == epoch_ && str(root, "rev") == revision_ && cJSON_IsObject(field(root, "values"));
  Card next[12]; for (uint8_t i = 0; i < count_; ++i) { next[i] = cards_[i]; next[i].state = next[i].mode = "unknown"; next[i].hasValue = next[i].hasTarget = false; }
  const auto* values = field(root, "values");
  for (const auto* item = ok ? values->child : nullptr; item && ok; item = item->next) {
    for (const auto* other = item->next; other; other = other->next) if (!strcmp(item->string, other->string)) ok = false;
    int index = -1; for (uint8_t i = 0; i < count_; ++i) if (cards_[i].id == item->string) index = i;
    if (index < 0) continue;
    Card& c = next[index]; c.state = str(item, "state");
    ok = keys(item, c.kind == "climate" ? ",state,value,target,mode," : ",state,value,") &&
        (c.state == "on" || c.state == "off" || c.state == "ok" || c.state == "unavailable" || c.state == "unknown");
    const auto* v = field(item, "value");
    if (cJSON_IsBool(v)) { c.value = cJSON_IsTrue(v) ? 1 : 0; c.hasValue = true; }
    else if (cJSON_IsNumber(v) && isfinite(v->valuedouble)) { c.value = v->valuedouble; c.hasValue = true; }
    else if (!cJSON_IsNull(v)) ok = false;
    const auto* target = field(item, "target");
    if (target && !cJSON_IsNull(target)) {
      if (!cJSON_IsNumber(target) || !isfinite(target->valuedouble)) ok = false;
      else { c.target = target->valuedouble; c.hasTarget = true; }
    }
    if (field(item, "mode")) {
      c.mode = str(item, "mode");
      if (c.mode != "off" && c.mode != "heat" && c.mode != "auto" && c.mode != "unknown") ok = false;
    }
  }
  if (ok) {
    for (uint8_t i = 0; i < count_; ++i) cards_[i] = next[i];
    stateAt_ = millis(); stateTtl_ = max<int>(0, field(root, "issued")->valuedouble + field(root, "ttl")->valueint - time(nullptr));
  }
  cJSON_Delete(root); return ok;
}
void FireHome::acknowledge(const char* body) {
  if (!fireJsonSafe(body, strlen(body), 512)) return;
  cJSON* root = cJSON_ParseWithOpts(body, nullptr, true);
  if (keys(root, ",v,rid,seq,status,code,") && integer(root, "v", 1, 1) &&
      str(root, "rid") == pendingRid_ && pendingRid_.length() && integer(root, "seq", pendingSeq_, pendingSeq_)) {
    String s = str(root, "status");
    const String code = str(root, "code");
    const bool validCode = code == "ok" || code == "schema" || code == "expired" || code == "session" || code == "revision" || code == "sequence" || code == "denied" || code == "unavailable" || code == "action_failed";
    if (validCode && (s == "executed" || s == "rejected" || s == "unknown")) {
      pendingRid_ = "";
      status_ = s == "executed" ? "Sendt til HA" : s == "rejected" ? "Avvist av HA" : "Ukjent resultat";
    }
  }
  cJSON_Delete(root);
}
bool FireHome::sendCommand(const Card& card, const char* op, double value, bool number, const char* text) {
  if (!stateFresh() || card.state == "unavailable" || card.state == "unknown" || pendingRid_.length() || !(card.ops & operation(op)) || lastSeq_ >= 2147483647) return false;
  if (String(op) == "brightness" && (!isfinite(value) || value < 0 || value > 255 || floor(value) != value)) return false;
  if (String(op) == "temperature" && (!isfinite(value) || value < card.minimum || value > card.maximum ||
      fabs((value - card.minimum) / card.step - round((value - card.minimum) / card.step)) > 0.001)) return false;
  cJSON* request = cJSON_CreateObject(); if (!request) return false;
  const String id = rid(); const uint32_t seq = lastSeq_ + 1;
  cJSON_AddNumberToObject(request, "v", 1); cJSON_AddStringToObject(request, "type", "command");
  cJSON_AddStringToObject(request, "rid", id.c_str()); cJSON_AddStringToObject(request, "epoch", epoch_.c_str());
  cJSON_AddStringToObject(request, "rev", revision_.c_str()); cJSON_AddNumberToObject(request, "seq", seq);
  cJSON_AddNumberToObject(request, "issued", time(nullptr)); cJSON_AddNumberToObject(request, "ttl", 15);
  cJSON_AddStringToObject(request, "card", card.id.c_str()); cJSON_AddStringToObject(request, "op", op);
  if (number) cJSON_AddNumberToObject(request, "value", value);
  else if (text) cJSON_AddStringToObject(request, "value", text); else cJSON_AddNullToObject(request, "value");
  char* data = cJSON_PrintUnformatted(request); bool ok = data && queue(data); cJSON_free(data); cJSON_Delete(request);
  if (ok) { pendingRid_ = id; pendingSeq_ = lastSeq_ = seq; pendingAt_ = millis(); status_ = "Venter på HA"; }
  return ok;
}
String FireHome::favoriteKey(const String& id) const {
  uint32_t hash = 2166136261UL; for (size_t i = 0; i < id.length(); ++i) hash = (hash ^ id[i]) * 16777619UL;
  return "f" + String(profile_) + String(hash, HEX);
}
void FireHome::reorder() {
  const String order = preferences_.getString(profile_ ? "order1" : "order0", "");
  for (uint8_t i = 0; i < count_; ++i) cards_[i].favorite = preferences_.getBool(favoriteKey(cards_[i].id).c_str(), false);
  for (uint8_t i = 0; i < count_; ++i) for (uint8_t j = i + 1; j < count_; ++j) {
    const int a = order.indexOf("," + cards_[i].id + ","), b = order.indexOf("," + cards_[j].id + ",");
    if ((cards_[j].favorite && !cards_[i].favorite) || (cards_[j].favorite == cards_[i].favorite && b >= 0 && (a < 0 || b < a))) {
      Card temporary = cards_[i]; cards_[i] = cards_[j]; cards_[j] = temporary;
    }
  }
  focus_ = min<uint8_t>(focus_, count_);
}
uint8_t FireHome::visible(uint8_t* indices) const {
  uint8_t n = 0; for (uint8_t i = 0; i < count_; ++i) if (!favoritesOnly_ || cards_[i].favorite) indices[n++] = i; return n;
}
bool FireHome::back() {
  if (confirm_ || editing_) { confirm_ = editing_ = false; return true; }
  if (detail_ || settings_) { detail_ = settings_ = false; focus_ = 0; return true; }
  return false;
}
void FireHome::button(uint8_t index) {
  if (!preferencesReady_ || !configMutex_) { status_ = "Home-lagring er ikke klar"; return; }
  if (settings_) {
    constexpr uint8_t options = 6;
    if (index != 1) focus_ = (focus_ + options + (index == 0 ? -1 : 1)) % options;
    else if (focus_ == 0) {
      if (xSemaphoreTake(configMutex_, 0) != pdTRUE) return;
      profile_ ^= 1; invalidate(); persist(); xSemaphoreGive(configMutex_);
    } else if (focus_ == 1) {
      if (xSemaphoreTake(configMutex_, 0) != pdTRUE) return;
      routeMode_ = (routeMode_ + 1) % 3; invalidate(); persist(); focus_ = 1;
      xSemaphoreGive(configMutex_);
    }
    else if (focus_ == 2) { layout_ ^= 1; persist(); }
    else if (focus_ == 3) favoritesOnly_ = !favoritesOnly_;
    else if (focus_ == 4) setupRequested_ = true;
    else { settings_ = false; focus_ = 0; }
    return;
  }
  if (!detail_) {
    uint8_t indices[12]; const uint8_t n = visible(indices);
    if (index != 1) focus_ = (focus_ + n + 1 + (index == 0 ? -1 : 1)) % (n + 1);
    else if (focus_ >= n) settings();
    else { detail_ = true; detailCardId_ = cards_[indices[focus_]].id; detailAction_ = 0; editing_ = confirm_ = false; }
    return;
  }
  Card* card = nullptr; for (uint8_t i = 0; i < count_; ++i) if (cards_[i].id == detailCardId_) card = &cards_[i];
  if (!card) { detail_ = false; return; }
  uint8_t actions[9], n = 0;
  for (uint8_t i = 0; i < 6; ++i) if (card->ops & (1 << i)) actions[n++] = i;
  actions[n++] = 6; actions[n++] = 7; actions[n++] = 8;
  detailAction_ = min<uint8_t>(detailAction_, n - 1); uint8_t action = actions[detailAction_];
  if (confirm_) {
    if (index == 1 && action < 6) {
      const char* mode = editValue_ == 0 ? "off" : editValue_ == 1 ? "heat" : "auto";
      if (!sendCommand(*card, operations[action], editValue_, action == 2 || action == 3, action == 4 ? mode : nullptr)) status_ = "Ikke tilgjengelig";
    }
    confirm_ = editing_ = false; return;
  }
  if (editing_) {
    if (index == 1) { editing_ = false; confirm_ = true; }
    else if (action == 4) {
      int mode = static_cast<int>(editValue_);
      do { mode = (mode + 3 + (index == 0 ? -1 : 1)) % 3; } while (!(card->modes & (1 << mode)));
      editValue_ = mode;
    } else {
      double step = action == 2 ? 16 : card->step;
      editValue_ = max(action == 2 ? 0.0 : card->minimum,
          min(action == 2 ? 255.0 : card->maximum, editValue_ + (index == 0 ? -step : step)));
    }
    return;
  }
  if (index != 1) detailAction_ = (detailAction_ + n + (index == 0 ? -1 : 1)) % n;
  else if (action == 8) detail_ = false;
  else if (action == 6) { card->favorite = !card->favorite; preferences_.putBool(favoriteKey(card->id).c_str(), card->favorite); reorder(); }
  else if (action == 7) {
    String order = "," + card->id + ","; for (uint8_t i = 0; i < count_; ++i) if (cards_[i].id != card->id) order += cards_[i].id + ",";
    preferences_.putString(profile_ ? "order1" : "order0", order); reorder();
  } else if (stateFresh() && card->state != "unknown" && card->state != "unavailable" && !pendingRid_.length()) {
    editValue_ = action == 2 ? (card->hasValue ? round(card->value) : 128) :
                 action == 3 ? (card->hasTarget ? card->target : card->minimum) : 0;
    if (action == 3) editValue_ = max(card->minimum, min(card->maximum, card->minimum + round((editValue_ - card->minimum) / card->step) * card->step));
    if (action == 4) while (!(card->modes & (1 << static_cast<int>(editValue_)))) ++editValue_;
    editing_ = action >= 2 && action <= 4; confirm_ = !editing_;
  } else status_ = "Venter på ferske data";
}

void FireHome::draw(M5Canvas& c) {
  c.fillSprite(bg); c.setFont(&fonts::efontJA_12); c.setTextSize(1);
  label(c, 12, 8, profileName(), ink, 2);
  const String connection = !configured() ? "Oppsett" : !online_ ? "Frakoblet" : !current() ? "Utdatert" : remote_ ? "Internett" : "Lokalt";
  label(c, 218, 14, connection, current() ? accent : amber);
  c.drawFastHLine(12, 40, 296, panel);
  auto footer = [&](const char* a, const char* b, const char* d) {
    c.fillRect(0, 216, 320, 24, panel);
    label(c, 10, 221, a, muted); label(c, 127, 221, b); label(c, 257, 221, d, muted);
  };
  auto value = [](double number) {
    char text[32]; snprintf(text, sizeof(text), fabs(number) < 1000000 ? "%.1f" : "%.2g", number); return String(text);
  };
  auto crop = [&](String text, int width, uint8_t scale = 1) -> String {
    c.setTextSize(scale);
    if (c.textWidth(text) <= width) return text;
    while (text.length()) {
      size_t end = text.length() - 1;
      while (end && (static_cast<uint8_t>(text[end]) & 0xC0) == 0x80) --end;
      text.remove(end);
      if (c.textWidth(text + "…") <= width) return text + "…";
    }
    return String();
  };
  if (settings_) {
    const char* modes[] = {"Auto", "Lokalt", "Internett"};
    String rows[] = {"Profil: " + profileName(), "Forbindelse: " + String(modes[routeMode_]),
        String("Visning: ") + (layout_ ? "Stort kort" : "2 x 2 kort"),
        String("Favoritter: ") + (favoritesOnly_ ? "Bare favoritter" : "Alle kort"), "Oppsett på mobil", "Tilbake"};
    for (uint8_t i = 0; i < 6; ++i) {
      const int y = 49 + i * 24;
      if (focus_ == i) c.fillRoundRect(8, y - 2, 304, 23, 5, panel);
      label(c, 16, y, rows[i], focus_ == i ? accent : ink);
    }
    if (setupHint_.length()) { c.fillRect(0, 188, 320, 27, bg); label(c, 10, 188, setupHint_, amber); label(c, 10, 201, "192.168.4.1/home", muted); }
    footer("Forrige", "Endre", "Neste"); return;
  }
  if (detail_) {
    Card* card = nullptr; for (uint8_t i = 0; i < count_; ++i) if (cards_[i].id == detailCardId_) card = &cards_[i];
    if (!card) { detail_ = false; return; }
    label(c, 14, 50, crop(card->name, 292, 2), ink, 2);
    String reading = card->hasValue ? value(card->value) + " " + card->unit : "—";
    uint8_t scale = 3;
    c.setTextSize(scale); while (scale > 1 && c.textWidth(reading) > 288) c.setTextSize(--scale);
    label(c, 16, 84, crop(reading, 288, scale), stateFresh() ? ink : muted, scale);
    if (card->kind == "climate") label(c, 18, 125, String("Mål: ") + (card->hasTarget ? value(card->target) : "—") + "  " + card->mode, muted);
    else label(c, 18, 125, card->state, muted);
    if (!stateFresh()) label(c, 225, 138, "Utdatert", amber);
    uint8_t actions[9], n = 0; for (uint8_t i = 0; i < 6; ++i) if (card->ops & (1 << i)) actions[n++] = i;
    actions[n++] = 6; actions[n++] = 7; actions[n++] = 8;
    const char* names[] = {"Slå på", "Slå av", "Lysstyrke", "Måltemperatur", "Varmemodus", "Kjør", "Favoritt", "Flytt først", "Tilbake"};
    const uint8_t action = actions[min<uint8_t>(detailAction_, n - 1)];
    String choice = names[action];
    if (editing_ || confirm_) choice += String(": ") + (action == 4 ? (editValue_ == 0 ? "off" : editValue_ == 1 ? "heat" : "auto") : action == 2 || action == 3 ? value(editValue_) : "");
    c.fillRoundRect(10, 153, 300, 33, 7, panel); label(c, 20, 160, crop(choice, 278), confirm_ ? amber : accent);
    label(c, 15, 194, confirm_ ? "Bekreft handlingen" : crop(status_, 290), muted);
    if (confirm_) footer("Tilbake", "Bekreft", "Avbryt"); else if (editing_) footer("Mindre", "Velg", "Mer"); else footer("Forrige", "Velg", "Neste");
    return;
  }
  uint8_t indices[12]; const uint8_t n = visible(indices);
  if (!n) {
    label(c, 18, 70, configured() ? "Venter på Home Assistant" : "Velkommen til Home", ink, 2);
    label(c, 18, 107, "Direkte til ditt hjem. Ingen PC nødvendig.", muted);
    label(c, 18, 139, "B åpner innstillinger og mobiloppsett", muted);
  } else {
    const uint8_t perPage = layout_ ? 1 : 4;
    const uint8_t page = min<uint8_t>(focus_, n - 1) / perPage;
    for (uint8_t slot = 0; slot < perPage; ++slot) {
      uint8_t at = page * perPage + slot; if (at >= n) break;
      Card& card = cards_[indices[at]];
      const int x = layout_ ? 10 : 10 + (slot % 2) * 155;
      const int y = layout_ ? 50 : 50 + (slot / 2) * 76;
      const int w = layout_ ? 300 : 145, h = layout_ ? 139 : 68;
      c.fillRoundRect(x, y, w, h, 8, panel);
      c.drawRoundRect(x, y, w, h, 8, focus_ == at ? accent : panel);
      if (focus_ == at) c.drawRoundRect(x + 1, y + 1, w - 2, h - 2, 7, accent);
      // Cheap native symbols; no bitmap/font downloads or per-card sprites.
      if (card.kind == "light") { c.drawCircle(x + w - 17, y + 15, 6, accent); c.drawFastHLine(x + w - 21, y + 23, 8, accent); }
      else if (card.kind == "climate" || card.kind == "sensor") { c.drawRoundRect(x + w - 21, y + 8, 7, 15, 3, accent); c.fillCircle(x + w - 18, y + 23, 5, accent); }
      else if (card.kind == "script" || card.kind == "scene") c.fillTriangle(x + w - 22, y + 8, x + w - 22, y + 24, x + w - 10, y + 16, accent);
      c.setTextColor(ink, panel); c.setTextSize(1); c.drawString(crop(card.name, w - 42), x + 10, y + 9);
      const bool stale = !stateFresh();
      String reading = card.kind == "light" || card.kind == "switch" ? (card.state == "on" ? "PÅ" : card.state == "off" ? "AV" : "—") :
          card.kind == "script" || card.kind == "scene" ? "Kjør" : card.hasValue ? value(card.value) + " " + card.unit : "—";
      uint8_t scale = layout_ ? 3 : 2;
      c.setTextSize(scale); while (scale > 1 && c.textWidth(reading) > w - 20) c.setTextSize(--scale);
      c.setTextColor(stale ? muted : ink, panel); c.drawString(crop(reading, w - 20, scale), x + 10, y + (layout_ ? 47 : 31));
      if (!stale && card.kind == "climate" && card.hasTarget) { c.setTextSize(1); c.drawString(crop("Mål " + value(card.target), w - 20), x + 10, y + h - 16); }
      else if (stale) { c.setTextSize(1); c.drawString("Utdatert", x + 10, y + h - 15); }
    }
  }
  label(c, 12, 198, focus_ >= n ? "Innstillinger" : crop(status_, 296), focus_ >= n ? accent : muted);
  footer("Forrige", focus_ >= n ? "Oppsett" : "Åpne", "Neste");
}

const char* FireHome::setupPage() const {
  return R"HOME(<!doctype html><html lang="no"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FIRE Home</title>
<style>body{font:17px system-ui;max-width:560px;margin:30px auto;padding:16px;background:#0c1720;color:#e6f1f6}input,select,textarea,button{box-sizing:border-box;width:100%;margin:7px 0 16px;padding:12px;border-radius:8px;border:1px solid #516472;background:#142632;color:inherit}button{background:#277b73}label{display:block}</style>
<h1>Home på FIRE</h1><p>Direkte MQTT til Home Assistant. Bruk egne brokerbrukere med begrensede rettigheter.</p><label>Importer device-profile.json<input id="profilefile" type="file" accept=".json,application/json"></label><form id="f">
<label>Profil<select name="profile"><option value="0">Home</option><option value="1">Camper</option></select></label>
<label>Site-ID<input name="site" required pattern="[a-z0-9][a-z0-9_-]{0,31}"></label><label>Device-ID<input name="device" value="fire01" required></label>
<label>Lokal broker (vertsnavn, TLS port 8883)<input name="local_host"></label><label>Lokal brokerbruker<input name="local_user"></label><label>Lokalt passord<input type="password" name="local_password" autocomplete="new-password"></label>
<label>Ekstern broker (vertsnavn, WSS 443 /mqtt)<input name="remote_host"></label><label>Ekstern brokerbruker<input name="remote_user"></label><label>Eksternt passord<input type="password" name="remote_password" autocomplete="new-password"></label>
<label>Lokal CA, bare ved privat sertifikat<textarea name="ca" rows="4" placeholder="-----BEGIN CERTIFICATE-----"></textarea></label>
<p>Passord vises aldri tilbake. Tomt passord beholder tidligere lagret passord for valgt profil. HA-administratoren velger kort og handlinger.</p><button>Lagre sikkert på enheten</button></form><p id="result"></p>
<script>profilefile.onchange=async()=>{try{const file=profilefile.files[0];if(file.size>8192)throw Error();const config=JSON.parse(await file.text());for(const[k,v]of Object.entries(config)){const field=f.elements.namedItem(k);if(field)field.value=v}result.textContent='Profil lest. Kontroller feltene og trykk Lagre.'}catch(e){result.textContent='Ugyldig profilfil'}};f.onsubmit=async e=>{e.preventDefault();const config=Object.fromEntries(new FormData(f));config.profile=Number(config.profile);try{const r=await fetch('/home/save',{method:'POST',body:new URLSearchParams({token:'%TOKEN%',config:JSON.stringify(config)})});result.textContent=await r.text()}catch(e){result.textContent='Forbindelsen ble brutt. Koble til FIRE-Setup igjen.'}}</script></html>)HOME";
}
