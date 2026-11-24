#pragma once
#include <atomic>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

// Single producer / single consumer. Storage is caller-owned; size must be a
// power of two below 2^31. Each publish commits all bytes atomically. No RTOS
// waits, IRQ disabling or heap operations occur while moving socket bytes.
class FireByteQueue {
 public:
  void initialize(uint8_t* storage, uint32_t capacity) {
    data_ = storage; capacity_ = capacity; reset();
  }
  void reset() { head_ = 0; tail_ = 0; }
  size_t size() const { return head_.load(std::memory_order_acquire) - tail_.load(std::memory_order_acquire); }
  size_t free() const { return capacity_ - size(); }
  bool initialized() const { return data_ != nullptr; }
  size_t write(const uint8_t* source, size_t length) {
    if (!data_ || !source || length > free()) return 0;
    const uint32_t head = head_.load(std::memory_order_relaxed);
    const size_t first = length < capacity_ - (head & (capacity_ - 1)) ? length : capacity_ - (head & (capacity_ - 1));
    memcpy(data_ + (head & (capacity_ - 1)), source, first);
    memcpy(data_, source + first, length - first);
    head_.store(head + length, std::memory_order_release);
    return length;
  }
  size_t read(uint8_t* target, size_t maximum) {
    if (!data_ || !target || !maximum) return 0;
    const size_t available = size();
    const size_t length = maximum < available ? maximum : available;
    const uint32_t tail = tail_.load(std::memory_order_relaxed);
    const size_t first = length < capacity_ - (tail & (capacity_ - 1)) ? length : capacity_ - (tail & (capacity_ - 1));
    memcpy(target, data_ + (tail & (capacity_ - 1)), first);
    memcpy(target + first, data_, length - first);
    tail_.store(tail + length, std::memory_order_release);
    return length;
  }
 private:
  uint8_t* data_ = nullptr;
  uint32_t capacity_ = 0;
  std::atomic<uint32_t> head_{0};
  std::atomic<uint32_t> tail_{0};
};
