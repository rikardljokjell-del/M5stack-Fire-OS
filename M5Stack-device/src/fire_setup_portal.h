#pragma once
#include <Arduino.h>
#include <atomic>

class FireSetupPortal {
 public:
  enum class Operation { Wifi, Backend, Provision, Home };
  struct Request {
    Operation operation;
    uint32_t generation = 0;
    String token, host, port, device, secret, ssid, password, config;
  };
  bool open(bool backend, const String& token, const char* homePage);
  void close() { wanted_ = false; }
  Request* take();
  void complete(bool ok, const String& message);
  bool current(const Request& request) const { return wanted_ && request.generation == generation_; }
  bool replied() const { return replied_; }
 private:
  enum class Phase { Idle, Pending, Claimed, Done, Abandoned };
  std::atomic<Phase> phase_{Phase::Idle};
  std::atomic<bool> wanted_{false};
  std::atomic<bool> replied_{false};
  std::atomic<uint32_t> generation_{0};
  std::atomic_flag lock_ = ATOMIC_FLAG_INIT;
  bool started_ = false, backend_ = false, ok_ = false;
  String token_, message_;
  const char* homePage_ = nullptr;
  Request request_;
  static void task(void* context);
  void run();
};
