#pragma once

#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <atomic>
#include "fire_byte_queue.h"
#include "fire_backend_policy.h"

// Socket/TLS ownership stays on one worker. UI-facing operations only move
// bounded bytes through single-reader/single-writer queues and never wait.
class FireAsyncClient : public WiFiClient {
 public:
  FireAsyncClient() = default;
  FireAsyncClient(const FireAsyncClient&) = delete;
  FireAsyncClient& operator=(const FireAsyncClient&) = delete;
  int connect(const char* host, uint16_t port) override;
  int connect(const char* host, uint16_t port, int32_t timeout);
  int connect(IPAddress ip, uint16_t port) override;
  bool connectBlocking(const char* host, uint16_t port, uint32_t timeoutMs,
                       const std::atomic<bool>* cancelled = nullptr);
  bool connecting() const { return state_.load() == State::Connecting; }
  bool stopping() const { return active_.load() && stop_.load(); }
  bool running() const { return active_.load(); }
  bool pendingWrites() const {
    // Queue first: a consumer publishes in-flight before removing its bytes.
    return active_ && !stop_ && (tx_.size() != 0 || txWriting_.load());
  }
  bool canWrite(size_t length) const {
    return tx_.initialized() && active_ && !stop_ && state_ == State::Ready &&
           tx_.free() >= length;
  }
  bool lastConnectFailure(fire_backend_policy::ConnectFailure& result) const {
    // active_ is released only after socket destruction. No payload is read
    // while a worker can write it; a new attempt belongs to this client owner.
    if (!fire_backend_policy::failureReadable(active_.load(std::memory_order_acquire),stop_.load(),state_.load()==State::Failed)) return false;
    result=lastFailure_;return result.matches(attempt_);
  }
  void secure(bool enabled) { secure_.store(enabled); }
  int available() override;
  int read() override;
  int read(uint8_t* data, size_t length) override;
  int peek() override;
  size_t write(uint8_t byte) override;
  size_t write(const uint8_t* data, size_t length) override;
  uint8_t connected() override;
  void stop() override;
  void flush() override {}
  using Print::write;
 private:
  enum class State : uint8_t { Idle, Connecting, Ready, Failed };
  std::atomic<State> state_{State::Idle};
  std::atomic<bool> active_{false};
  std::atomic<bool> stop_{false};
  std::atomic<bool> failureReported_{false};
  std::atomic<bool> secure_{true};
  std::atomic<bool> txWriting_{false};
  bool workerSecure_ = true;
  uint32_t measuredAt_ = 0,attempt_=0;
  fire_backend_policy::ConnectFailure lastFailure_;
  char host_[128] = {};
  uint16_t port_ = 443;
  FireByteQueue rx_;
  FireByteQueue tx_;
  uint8_t* rxStorage_ = nullptr;
  uint8_t* txStorage_ = nullptr;
  int peeked_ = -1;
  static void task(void* context);
  void run();
};

// Explicit HTTP is limited to private IPv4/localhost for legacy local/reverse
// mode. DNS/public endpoints default to verified TLS, including bare names.
String fireNetworkHost(const String& endpoint);
bool fireNetworkTls(const String& endpoint, uint16_t port);
bool fireNetworkEndpointValid(const String& endpoint);
bool fireRelativePath(const String& path);
// Call once from setup before starting network workers. The shared immutable
// certificate index must never be replaced while another TLS handshake runs.
void fireInitTrust();
