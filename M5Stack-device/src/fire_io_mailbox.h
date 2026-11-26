#pragma once
#include <Arduino.h>
#include <atomic>

// One worker publishes; the UI copies only if it can acquire immediately.
// Completion strings are published by running=false, after all worker writes.
struct FireIoMailbox {
  std::atomic<bool> running{false}, completed{false}, wifi{false}, sd{false};
  std::atomic_flag lock = ATOMIC_FLAG_INIT;
  bool dirty = false;
  char text[128] = {};
  bool kind = false, ok = false;
  String first, second, message, completionId;
  void status(const String& value) {
    while (lock.test_and_set(std::memory_order_acquire)) delay(1);
    if(strncmp(text,value.c_str(),sizeof(text)-1)!=0) {strlcpy(text, value.c_str(), sizeof(text));dirty=true;}
    lock.clear(std::memory_order_release);
  }
  bool poll(String& value) {
    if (lock.test_and_set(std::memory_order_acquire)) return false;
    const bool changed = dirty;
    if (changed) { value = text; dirty = false; }
    lock.clear(std::memory_order_release); return changed;
  }
  void result(bool type, bool success, const String& a, const String& b, const String& detail,
              const String& identity=String()) {
    kind = type; ok = success; first = a; second = b; message = detail;completionId=identity;
    completed = true;
  }
  bool busy() const { return running || completed; }
};
