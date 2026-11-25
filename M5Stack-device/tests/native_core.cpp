#include "fire_byte_queue.h"
#include "fire_json_guard.h"
#include "fire_runtime_ai_json.h"
#include "fire_ai_workflow.h"
#include <assert.h>
#include <string>
#include <thread>
#include <vector>
#include <stdio.h>

int main() {
  for(uint8_t phase=0;phase<=6;++phase) for(uint8_t speech:{uint8_t(0),uint8_t(1),uint8_t(2)})
    assert(fireConversationState(phase,speech)==(phase>=3?phase:speech));
  puts("PASS assistant/TTS lifecycle preserves ready/build/install/run confirmation phases");
  const auto aiJson=[](const std::string& s) {return fire_runtime_ai_json::validObject(s.c_str(),s.size(),512);};
  assert(aiJson("{\"value\":12.5,\"nested\":{\"a\":[1,2,3]},\"text\":\"\\u00e6\\ud83d\\ude80\",\"null\":null}"));
  assert(!aiJson("{\"x\":1,\"x\":2}") && !aiJson("{\"x\":1,\"\\u0078\":2}"));
  assert(!aiJson("{\"x\":NaN}") && !aiJson("{\"x\":1e999}") && !aiJson("{\"x\":01}"));
  assert(!aiJson("{\"x\":\"\\q\"}") && !aiJson("{\"x\":\"\\ud800\"}"));
  assert(!aiJson("{} garbage") && !aiJson("[]") && !aiJson("{\"a\":{\"b\":{\"c\":{\"d\":1}}}}"));
  assert(aiJson("{\"x\":\""+std::string(256,'a')+"\"}"));
  assert(!aiJson("{\"x\":\""+std::string(257,'a')+"\"}"));
  std::string worst="{\"v\":[";
  for(unsigned i=0;i<16;++i) {if(i) worst+=",";worst+="{\"a\":1,\"b\":2,\"c\":3,\"d\":4}";}
  worst+="]}";assert(worst.size()<=512 && aiJson(worst));
  worst.insert(worst.size()-2,",0");assert(!aiJson(worst));
  puts("PASS Runtime AI strict JSON finite/UTF8/duplicates/depth4/array16/string256 and bounded worst-case result");
  auto safe = [](const std::string& s) { return fireJsonSafe(s.data(), s.size(), 32768); };
  assert(safe("{\"navn\":\"æøå\",\"quoted\":\"[\\\"}\"}"));
  assert(!safe(std::string(500, '[') + std::string(500, ']')));
  assert(!safe("{\"a\": [1,2}"));
  assert(!safe(std::string("{\"a\":\"\xc0\xaf\"}")));
  assert(!safe(std::string("{\"a\":\"\xed\xa0\x80\"}")));
  assert(!safe(std::string("{\"a\":\"\xf4\x90\x80\x80\"}")));
  assert(!safe(std::string("{\"a\":\"a\0b\"}", 11)));
  assert(!safe("{\"a\":\"unterminated}"));
  std::string many = "[";
  for (int i = 0; i < 1200; ++i) many += "0,";
  many += "0]"; assert(!safe(many));
  uint8_t storage[16], out[32] = {}; FireByteQueue queue; queue.initialize(storage, 16);
  const uint8_t first[] = {1,2,3,4,5,6,7,8,9,10,11,12};
  assert(queue.write(first, 12) == 12);
  assert(queue.write(first, 5) == 0); assert(queue.size() == 12);
  assert(queue.read(out, 8) == 8);
  assert(queue.write(first, 12) == 12); assert(queue.free() == 0);
  assert(queue.read(out, 16) == 16);
  for (int i = 0; i < 4; ++i) assert(out[i] == first[i + 8]);
  for (int i = 0; i < 12; ++i) assert(out[i + 4] == first[i]);
  // Exercise the actual SPSC implementation concurrently through many wraps.
  uint8_t ring[1024]; FireByteQueue concurrent; concurrent.initialize(ring, 1024);
  constexpr unsigned count = 1000000;
  std::thread writer([&]() {
    for (unsigned i = 0; i < count; ++i) { uint8_t b = i % 251; while (!concurrent.write(&b, 1)) std::this_thread::yield(); }
  });
  for (unsigned i = 0; i < count; ++i) {
    uint8_t b = 0; while (!concurrent.read(&b, 1)) std::this_thread::yield(); assert(b == i % 251);
  }
  writer.join(); assert(concurrent.size() == 0);
  puts("PASS native UTF-8/depth/token guard and atomic queue/backpressure/wrap/concurrency");
}
