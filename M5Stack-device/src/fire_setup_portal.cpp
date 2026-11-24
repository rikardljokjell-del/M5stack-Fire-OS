#include "fire_setup_portal.h"
#include "fire_worker_diagnostics.h"
#include <WebServer.h>

bool FireSetupPortal::open(bool backend, const String& token, const char* page) {
  if (lock_.test_and_set(std::memory_order_acquire)) return false;
  backend_ = backend; token_ = token; homePage_ = page; ++generation_;
  lock_.clear(std::memory_order_release); wanted_ = true;
  if (started_) return true;
  if (xTaskCreate(task, "fire-setup", 8192, this, 1, nullptr) != pdPASS) { wanted_ = false; return false; }
  started_ = true; return true;
}
FireSetupPortal::Request* FireSetupPortal::take() {
  Phase pending = Phase::Pending;
  return phase_.compare_exchange_strong(pending, Phase::Claimed) ? &request_ : nullptr;
}
void FireSetupPortal::complete(bool ok, const String& message) {
  ok_ = ok; message_ = message; phase_ = Phase::Done;
}
void FireSetupPortal::task(void* context) {
  static_cast<FireSetupPortal*>(context)->run(); vTaskDelete(nullptr);
}
void FireSetupPortal::run() {
  WebServer web(80); String token; bool backend = false;
  const char* homePage = nullptr; uint32_t active = 0, measuredAt = 0;
  auto submit = [&](Operation operation, bool optionalToken = false) {
    const String supplied = web.arg("token");
    if (!wanted_ || active != generation_ || ((!optionalToken || supplied.length()) && supplied != token)) { web.send(403, "text/plain", "Ugyldig oppsettsokt"); return; }
    Request next; next.operation = operation; next.token = supplied; next.generation = active;
    next.host = web.arg("host"); next.port = web.arg("port"); next.device = web.arg("device");
    if (!next.device.length()) next.device = web.arg("device_id");
    next.secret = web.arg("backend_token"); next.ssid = web.arg("ssid"); next.password = web.arg("password"); next.config = web.arg("config");
    if (next.host.length() > 150 || next.port.length() > 5 || next.device.length() > 64 || next.secret.length() > 128 || next.ssid.length() > 32 || next.password.length() > 64 || next.config.length() > 8192) { web.send(400, "text/plain", "For store oppsettsfelt"); return; }
    // Persistent storage + phase CAS avoids pointers to a timed-out stack frame.
    request_ = next; replied_ = false; phase_.store(Phase::Pending, std::memory_order_release);
    const uint32_t waiting = millis();
    while (phase_ != Phase::Done) {
      if (millis() - waiting > 5000) {
        Phase pending = Phase::Pending;
        if (phase_.compare_exchange_strong(pending, Phase::Abandoned)) { web.send(503, "text/plain", "OS svarte ikke. Oppsettet ble ikke brukt."); return; }
      }
      delay(2);
    }
    web.sendHeader("Cache-Control", "no-store");
    web.send(ok_ ? 200 : 400, "text/plain; charset=utf-8", message_);
    replied_ = true;
    phase_ = Phase::Idle;
  };
  web.on("/", HTTP_GET, [&]() {
    if (!wanted_ || active != generation_ || web.arg("token") != token) { web.send(403, "text/plain", "Ugyldig oppsettsokt"); return; }
    String fields = backend
        ? "<label>Backend-domene eller lokal IP<input name=host maxlength=150></label><label>Port (offentlig: 443)<input name=port inputmode=numeric maxlength=5></label><label>Enhetstoken<input type=password name=backend_token maxlength=128></label><label>Device-ID<input name=device maxlength=64></label>"
        : "<label>Wi-Fi-nettverk<input name=ssid maxlength=32></label><label>Wi-Fi-passord<input type=password name=password maxlength=64></label>";
    String page = "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>FIRE oppsett</title><style>body{font:17px system-ui;max-width:500px;margin:24px auto;padding:16px}label{display:block}input,button{box-sizing:border-box;width:100%;padding:12px;margin:8px 0 18px}</style><h1>FIRE oppsett</h1><p>Tomme felt beholder gjeldende verdi.</p><form method=post action=/save>" + fields + "<input type=hidden name=token value='" + token + "'><button>Lagre</button></form><p><a href=/home>Home-oppsett</a></p>";
    web.sendHeader("Cache-Control", "no-store"); web.send(200, "text/html; charset=utf-8", page);
  });
  web.on("/save", HTTP_POST, [&]() { submit(backend ? Operation::Backend : Operation::Wifi); });
  web.on("/provision", HTTP_GET, [&]() {
    if (!backend) { web.send(403, "text/plain", "Backend-oppsett er ikke aktivt"); return; }
    submit(Operation::Provision, true);
  });
  web.on("/home", HTTP_GET, [&]() {
    if (!wanted_ || active != generation_ || !homePage) { web.send(403, "text/plain", "Oppsett er lukket"); return; }
    String page = homePage; page.replace("%TOKEN%", token);
    web.sendHeader("Cache-Control", "no-store"); web.sendHeader("X-Content-Type-Options", "nosniff");
    web.send(200, "text/html; charset=utf-8", page);
  });
  web.on("/home/save", HTTP_POST, [&]() { submit(Operation::Home); });
  for (;;) {
    if (wanted_) {
      if (active != generation_) {
        if (lock_.test_and_set(std::memory_order_acquire)) { delay(2); continue; }
        token = token_; backend = backend_; homePage = homePage_; active = generation_;
        lock_.clear(std::memory_order_release); web.stop(); web.begin();
      }
      web.handleClient(); fireMeasureWorker("setup", measuredAt);
    } else if (active) { web.stop(); active = 0; }
    delay(5);
  }
}
