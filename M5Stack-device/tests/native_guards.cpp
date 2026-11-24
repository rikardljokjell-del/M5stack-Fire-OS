// Host tests include production headers directly. The JSON guard is a bounded
// preflight, not a complete JSON parser; grammar validation remains with cJSON.
#include "fire_byte_queue.h"
#include "fire_json_guard.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdio>
#include <deque>
#include <limits>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

static void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

static void queueBoundaries() {
  FireByteQueue empty;
  uint8_t scratch[64] = {};
  require(!empty.initialized() && !empty.size() && !empty.free(), "uninitialized state");
  require(!empty.read(scratch, 1) && !empty.write(scratch, 1), "uninitialized operations");
  uint8_t ring[16] = {}, source[32];
  for (unsigned i = 0; i < sizeof(source); ++i) source[i] = static_cast<uint8_t>(i);
  FireByteQueue queue; queue.initialize(ring, sizeof(ring));
  require(queue.initialized() && queue.free() == 16, "initialized capacity");
  require(!queue.write(nullptr, 1) && !queue.read(nullptr, 1), "null buffers");
  require(!queue.write(source, 0) && !queue.read(scratch, 0), "zero byte operations");
  require(!queue.write(source, std::numeric_limits<size_t>::max()), "oversized write bounded");
  require(queue.write(source, 16) == 16 && queue.free() == 0, "full capacity usable");
  require(!queue.write(source, 1) && queue.size() == 16, "full rejection is atomic");
  require(queue.read(scratch, sizeof(scratch)) == 16 && !memcmp(scratch, source, 16), "read bounded by available");
  require(queue.read(scratch, 1) == 0 && queue.free() == 16, "empty after drain");
  require(queue.write(source, 12) == 12 && queue.read(scratch, 10) == 10, "wrap setup");
  require(queue.write(source + 12, 14) == 14 && queue.size() == 16, "split wrap write");
  require(queue.read(scratch, 16) == 16 && !memcmp(scratch, source + 10, 16), "split wrap order");
  puts("PASS queue boundaries and wrap");
}

static void queueModel() {
  uint8_t ring[32], source[64], target[64];
  FireByteQueue queue; queue.initialize(ring, sizeof(ring));
  std::deque<uint8_t> model;
  uint32_t random = 0x413c029u; unsigned serial = 0;
  for (unsigned iteration = 0; iteration < 25000; ++iteration) {
    random = random * 1664525u + 1013904223u;
    const size_t amount = (random >> 8) % 40;
    if (random & 1) {
      for (size_t i = 0; i < amount; ++i) source[i] = static_cast<uint8_t>((serial + i) % 251);
      const size_t expected = amount <= 32 - model.size() ? amount : 0;
      require(queue.write(source, amount) == expected, "model write amount");
      for (size_t i = 0; i < expected; ++i) model.push_back(source[i]);
      serial += static_cast<unsigned>(expected);
    } else {
      const size_t expected = std::min(amount, model.size());
      require(queue.read(target, amount) == expected, "model read amount");
      for (size_t i = 0; i < expected; ++i) {
        require(target[i] == model.front(), "model byte order"); model.pop_front();
      }
    }
    require(queue.size() == model.size() && queue.free() == 32 - model.size(), "model occupancy");
  }
  puts("PASS queue random model");
}

static void queueResetAfterWorkerStops() {
  uint8_t ring[16], oldBytes[] = {7, 8, 9}, freshBytes[] = {1, 2, 3, 4}, target[16];
  FireByteQueue queue; queue.initialize(ring, sizeof(ring));
  // Only reset after the previous producer has stopped and joined, matching
  // the client's ownership requirement; concurrent reset is not supported.
  std::thread previousWorker([&]() { queue.write(oldBytes, sizeof(oldBytes)); });
  previousWorker.join();
  require(queue.size() == sizeof(oldBytes), "previous worker buffered data");
  queue.reset();
  require(!queue.size() && queue.free() == sizeof(ring), "quiescent reset");
  std::thread newWorker([&]() { queue.write(freshBytes, sizeof(freshBytes)); });
  newWorker.join();
  require(queue.read(target, sizeof(target)) == sizeof(freshBytes) &&
          !memcmp(target, freshBytes, sizeof(freshBytes)), "reset excludes previous connection bytes");
  puts("PASS queue quiescent stop/reset ownership");
}

static void queueCounterOverflow() {
  // Pass more than 2^32 bytes through the real counters, without exposing
  // private internals or replacing the production implementation.
  constexpr uint32_t capacity = 32768;
  std::vector<uint8_t> ring(capacity), source(capacity), target(capacity);
  for (size_t i = 0; i < source.size(); ++i) source[i] = static_cast<uint8_t>(i % 251);
  FireByteQueue queue; queue.initialize(ring.data(), capacity);
  for (uint32_t i = 0; i <= 131072; ++i) {
    require(queue.write(source.data(), source.size()) == capacity, "counter rollover write");
    require(queue.size() == capacity && queue.free() == 0, "counter rollover full");
    require(queue.read(target.data(), target.size()) == capacity, "counter rollover read");
    require(!memcmp(source.data(), target.data(), capacity), "counter rollover content");
    require(queue.size() == 0 && queue.free() == capacity, "counter rollover empty");
  }
  puts("PASS queue counter overflow");
}

static void queueConcurrency() {
  uint8_t ring[1024]; FireByteQueue queue; queue.initialize(ring, sizeof(ring));
  constexpr unsigned total = 2000000;
  std::atomic<bool> failed{false}, producerFinished{false};
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(30);
  std::thread producer([&]() {
    uint8_t bytes[257]; unsigned sent = 0;
    while (sent < total && !failed) {
      const unsigned count = std::min<unsigned>(17 + sent % 241, total - sent);
      for (unsigned i = 0; i < count; ++i) bytes[i] = static_cast<uint8_t>((sent + i) % 251);
      if (queue.write(bytes, count) == count) sent += count;
      else {
        if (std::chrono::steady_clock::now() > deadline) { failed = true; break; }
        std::this_thread::yield();
      }
    }
    producerFinished = true;
  });
  uint8_t bytes[509]; unsigned received = 0;
  while (received < total && !failed) {
    const size_t count = queue.read(bytes, 1 + received % sizeof(bytes));
    for (size_t i = 0; i < count; ++i)
      if (bytes[i] != static_cast<uint8_t>((received + i) % 251)) failed = true;
    received += static_cast<unsigned>(count);
    if (!count) {
      if ((producerFinished && !queue.size()) || std::chrono::steady_clock::now() > deadline) {
        failed = true; break;
      }
      std::this_thread::yield();
    }
  }
  producer.join();
  require(!failed && received == total && !queue.size(), "concurrent stream order and progress");
  puts("PASS queue SPSC concurrency");
}

static bool safe(const std::string& text, size_t maximum = 32768,
                 unsigned depth = 12, unsigned tokens = 1024) {
  return fireJsonSafe(text.data(), text.size(), maximum, depth, tokens);
}

static void jsonPreflight() {
  require(safe("{\"name\":\"Home\",\"cards\":[{\"id\":\"lamp\"}]}"), "normal JSON shape");
  require(safe("{\"quoted\":\"[{}]\\\"\\\\\"}"), "escaped quotes and brackets");
  require(safe(std::string(12, '[') + "0" + std::string(12, ']')), "depth boundary accepted");
  require(!safe(std::string(13, '[') + "0" + std::string(13, ']')), "depth boundary rejected");
  require(!safe(std::string(1000, '[') + std::string(1000, ']')), "deep recursion prevented");
  require(safe(std::string(16, '[') + std::string(16, ']'), 32768, 16), "preflight stack boundary");
  require(!safe("[]", 32768, 17) && !safe("[]", 32768, 0), "invalid depth configuration");
  require(!safe("{[}]") && !safe("{\"a\":[1,2}"), "mismatched brackets");
  require(!safe("{\"a\":\"unterminated}") && !safe("\"unfinished\\"), "unterminated strings");
  require(!safe(std::string("\"a\0b\"", 5)), "embedded NUL rejected");
  require(!safe(std::string("\"a\nb\"")), "literal string control rejected");
  require(!safe("") && !fireJsonSafe(nullptr, 1, 32768), "empty and null rejected");
  require(safe("[]", 2) && !safe("[]", 1), "byte size boundary");
  require(safe("[0,0]", 32768, 12, 2) && !safe("[0,0,0]", 32768, 12, 2), "token boundary");
  std::string tokens = "[\"x\"";
  for (unsigned i = 1; i < 512; ++i) tokens += ",\"x\"";
  tokens += "]"; require(safe(tokens), "default token boundary accepted");
  tokens.insert(tokens.size() - 1, ",\"x\""); require(!safe(tokens), "token flood bounded");
  // Valid UTF-8 range edges, including Nordic characters and supplementary code points.
  for (const std::string& bytes : std::vector<std::string>{"\xc2\x80", "\xc3\xa6\xc3\xb8\xc3\xa5", "\xe0\xa0\x80",
       "\xed\x9f\xbf", "\xef\xbf\xbf", "\xf0\x90\x80\x80", "\xf4\x8f\xbf\xbf"})
    require(safe("\"" + bytes + "\""), "valid UTF-8 rejected");
  for (const std::string& bytes : std::vector<std::string>{"\x80", "\xc0\xaf", "\xc1\xbf", "\xc2", "\xe0\x9f\xbf",
       "\xed\xa0\x80", "\xe2\x28\xa1", "\xf0\x8f\xbf\xbf", "\xf4\x90\x80\x80", "\xf5\x80\x80\x80", "\xff"})
    require(!safe("\"" + bytes + "\""), "malformed UTF-8 accepted");
  require(!safe("\xc3\xa6") && !safe("\"\\\xc3\xa6\""), "UTF-8 outside string or after escape");
  require(safe("\"\\u00e6\\u005b\""), "JSON Unicode escapes survive preflight");
  puts("PASS JSON preflight");
}

int main() {
  try {
    queueBoundaries(); queueModel(); queueResetAfterWorkerStops();
    queueCounterOverflow(); queueConcurrency(); jsonPreflight();
  } catch (const std::exception& error) {
    fprintf(stderr, "FAIL: %s\n", error.what()); return 1;
  }
  return 0;
}
