#include "fire_async_client.h"
#include <esp_heap_caps.h>
#include <time.h>
#include "fire_worker_diagnostics.h"

extern const uint8_t fireCaBundle[] asm("_binary_certs_roots_bundle_start");
extern "C" void arduino_esp_crt_bundle_set(const uint8_t* bundle);
namespace {
class SharedBundleTls : public WiFiClientSecure {
 public:
  void useSharedBundle() { _use_ca_bundle = true; }
};
constexpr size_t kRxBytes = 8192;
constexpr size_t kTxBytes = 16384;
bool privateHost(const String& host) {
  IPAddress ip;
  return host == "localhost" || (ip.fromString(host) &&
      (ip[0] == 10 || ip[0] == 127 ||
       (ip[0] == 192 && ip[1] == 168) ||
       (ip[0] == 172 && ip[1] >= 16 && ip[1] <= 31)));
}
}
void fireInitTrust() { arduino_esp_crt_bundle_set(fireCaBundle); }
String fireNetworkHost(const String& endpoint) {
  String host = endpoint;
  if (host.startsWith("https://")) host.remove(0, 8);
  else if (host.startsWith("http://")) host.remove(0, 7);
  if (host.endsWith("/")) host.remove(host.length() - 1);
  return host;
}
bool fireNetworkEndpointValid(const String& endpoint) {
  const String h = fireNetworkHost(endpoint);
  if (!h.length() || h.length() > 127) return false;
  for (size_t i = 0; i < h.length(); ++i)
    if (!(isalnum(static_cast<unsigned char>(h[i])) || h[i] == '.' || h[i] == '-'))
      return false;
  return !endpoint.startsWith("http://") || privateHost(h);
}
bool fireNetworkTls(const String& endpoint, uint16_t port) {
  if (endpoint.startsWith("https://") || port == 443) return true;
  return !privateHost(fireNetworkHost(endpoint));
}
bool fireRelativePath(const String& path) {
  if (!path.startsWith("/") || path.startsWith("//") || path.length() > 1024 ||
      path.indexOf("..") >= 0 || path.indexOf('\\') >= 0 ||
      path.indexOf("://") >= 0) return false;
  for (size_t i = 0; i < path.length(); ++i)
    if (static_cast<uint8_t>(path[i]) < 32 || path[i] == 127) return false;
  return true;
}
int FireAsyncClient::connect(IPAddress ip, uint16_t port) {
  return connect(ip.toString().c_str(), port);
}
int FireAsyncClient::connect(const char* host, uint16_t port, int32_t) {
  return connect(host, port);
}
int FireAsyncClient::connect(const char* host, uint16_t port) {
  if (!host || !fireNetworkEndpointValid(host)) return 0;
  if (active_) {
    const bool same = fireNetworkHost(host) == host_ && port == port_ && secure_ == workerSecure_;
    if (!same) stop();
    return same && state_ == State::Ready && !stop_ ? 1 : 0;
  }
  if (state_ == State::Failed && !stop_ && !failureReported_) {
    failureReported_ = true;
    return 0;
  }
  if (!rxStorage_) {
    rxStorage_ = static_cast<uint8_t*>(heap_caps_malloc(kRxBytes + 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    txStorage_ = static_cast<uint8_t*>(heap_caps_malloc(kTxBytes + 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!rxStorage_ || !txStorage_) {
      if (rxStorage_) heap_caps_free(rxStorage_);
      if (txStorage_) heap_caps_free(txStorage_);
      rxStorage_ = txStorage_ = nullptr;
      state_ = State::Failed;
      return 0;
    }
    rx_.initialize(rxStorage_, kRxBytes);
    tx_.initialize(txStorage_, kTxBytes);
  }
  rx_.reset();
  tx_.reset();
  peeked_ = -1;
  strlcpy(host_, fireNetworkHost(host).c_str(), sizeof(host_));
  port_ = port;
  workerSecure_ = secure_.load();
  stop_ = false;
  failureReported_ = false;
  state_ = State::Connecting;
  active_ = true;
  if (xTaskCreate(task, "fire-net", 8192, this, 1, nullptr) != pdPASS) {
    state_ = State::Failed;
    active_ = false;
  }
  return 0;
}
bool FireAsyncClient::connectBlocking(const char* host, uint16_t port,
                                     uint32_t timeoutMs, const std::atomic<bool>* cancelled) {
  const uint32_t started = millis();
  while (active_ && stop_ && millis() - started < timeoutMs &&
         (!cancelled || !*cancelled)) delay(5);
  if (cancelled && *cancelled) return false;
  connect(host, port);
  while (millis() - started < timeoutMs && (!cancelled || !*cancelled)) {
    if (connected()) return true;
    if (!active_) break;
    delay(5);
  }
  stop();
  return false;
}
void FireAsyncClient::task(void* context) {
  static_cast<FireAsyncClient*>(context)->run();
  vTaskDelete(nullptr);
}
void FireAsyncClient::run() {
  WiFiClient plain;
  SharedBundleTls tls;
  WiFiClient* socket = workerSecure_ ? static_cast<WiFiClient*>(&tls) : &plain;
  bool ok = false;
  if (workerSecure_) {
    if (time(nullptr) < 1700000000) {
      configTime(0, 0, "pool.ntp.org", "time.google.com");
      const uint32_t started = millis();
      while (!stop_ && time(nullptr) < 1700000000 && millis() - started < 8000) delay(20);
    }
    tls.useSharedBundle();
    tls.setHandshakeTimeout(5);
    tls.setTimeout(1);
    if (!stop_ && time(nullptr) >= 1700000000) ok = tls.connect(host_, port_, 5000);
  } else {
    plain.setTimeout(1);
    if (!stop_) ok = plain.connect(host_, port_, 1200);
  }
  if (ok && !stop_) {
    state_ = State::Ready;
    uint8_t data[1024];
    while (!stop_) {
      const size_t space = rx_.free();
      const int availableBytes = socket->available();
      if (space && availableBytes > 0) {
        const int n = socket->read(data, min<size_t>(sizeof(data), min<size_t>(space, availableBytes)));
        if (n > 0) rx_.write(data, n);
      }
      txWriting_ = true;
      const size_t sent = tx_.read(data, sizeof(data));
      size_t offset = 0;
      const uint32_t writeStarted = millis();
      while (!stop_ && offset < sent && millis() - writeStarted < 2000) {
        const size_t n = socket->write(data + offset, sent - offset);
        if (!n) break;
        offset += n;
      }
      txWriting_ = false;
      if (offset != sent || (!socket->connected() && !socket->available())) break;
      delay(2);
    }
  }
  socket->stop();
  txWriting_ = false;
  fireMeasureWorker("net", measuredAt_);
  state_ = stop_ ? State::Idle : State::Failed;
  active_ = false;
}
int FireAsyncClient::available() { return rx_.size() + (peeked_ >= 0); }
int FireAsyncClient::read() {
  if (peeked_ >= 0) { const int value = peeked_; peeked_ = -1; return value; }
  uint8_t value;
  return rx_.read(&value, 1) ? value : -1;
}
int FireAsyncClient::read(uint8_t* data, size_t length) {
  if (!data || !length) return 0;
  size_t count = 0;
  if (peeked_ >= 0) { data[count++] = peeked_; peeked_ = -1; }
  count += rx_.read(data + count, length - count);
  return count;
}
int FireAsyncClient::peek() { if (peeked_ < 0) peeked_ = read(); return peeked_; }
size_t FireAsyncClient::write(uint8_t byte) { return write(&byte, 1); }
size_t FireAsyncClient::write(const uint8_t* data, size_t length) {
  if (!canWrite(length)) return 0;
  return tx_.write(data, length);
}
uint8_t FireAsyncClient::connected() { return !stop_ && (state_ == State::Ready || available() > 0); }
void FireAsyncClient::stop() {
  stop_ = true;
  if (!active_) { state_ = State::Idle; failureReported_ = false; }
}
