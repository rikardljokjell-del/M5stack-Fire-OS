#pragma once
#include <Arduino.h>
#include <atomic>

class FireOta {
 public:
  bool start(const String& path);
  bool busy() const { return busy_; }
  bool finished() const { return finished_; }
  bool succeeded() const { return finished_ && ok_; }
  void acknowledge() { if (!busy_) finished_ = false; }
  uint8_t progress() const { return progress_; }
  String message() const;
 private:
  std::atomic<bool> busy_{false}, finished_{false}, ok_{false};
  std::atomic<uint8_t> progress_{0}, phase_{0};
  String path_;
  const char* error_ = "";
  static void task(void* context);
  void run();
};
