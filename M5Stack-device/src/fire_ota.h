#pragma once
#include <Arduino.h>
#include <atomic>
#include "fire_async_client.h"

class FireOta {
 public:
  bool start(const String& path);
  // Inputs are copied before the worker starts. No SD access in this mode.
  bool startGithub(const String& signedCatalog, const String& filename);
  // False once boot selection has entered its non-cancellable commit step.
  bool cancel();
  bool busy() const { return busy_; }
  bool finished() const { return finished_; }
  bool succeeded() const { return finished_ && ok_; }
  void acknowledge() { if (!busy_) finished_ = false; }
  uint8_t progress() const { return progress_; }
  String message() const;
 private:
  std::atomic<bool> busy_{false}, finished_{false}, ok_{false};
  std::atomic<uint8_t> progress_{0}, phase_{0};
  std::atomic<bool> cancelRequested_{false};
  std::atomic<uint8_t> decision_{0};  // 0 active, 1 cancelled, 2 committing
  String path_;
  String signedCatalog_, filename_;
  bool github_ = false;
  // stop() is asynchronous; this client must outlive its socket worker.
  FireAsyncClient network_;
  const char* error_ = "";
  bool claim();
  bool launch();
  bool startFailed(const char* message);
  static void task(void* context);
  void run();
};
