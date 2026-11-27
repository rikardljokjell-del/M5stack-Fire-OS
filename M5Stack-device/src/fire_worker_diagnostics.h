#pragma once
#include <Arduino.h>
#include <esp_heap_caps.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

// Call from the measured task, never from an ISR. Names are fixed literals,
// never endpoints, credentials, request bodies or user content.
inline void fireNetMemory(unsigned phase,unsigned kind) {
  const uint32_t caps=MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT;
  Serial.printf("FIRE net_memory phase=%u kind=%u heap=%u min_heap=%u largest=%u\n",
      phase,kind,heap_caps_get_free_size(caps),heap_caps_get_minimum_free_size(caps),
      heap_caps_get_largest_free_block(caps)); // min_heap is lifetime, NOT a stage minimum.
}
inline void fireMeasureWorker(const char* name, uint32_t& measuredAt) {
  if (measuredAt && millis() - measuredAt < 30000) return;
  measuredAt = millis();
  const uint32_t caps = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
  Serial.printf("FIRE worker %s stack=%u heap=%u min_heap=%u largest=%u\n", name,
      uxTaskGetStackHighWaterMark(nullptr), heap_caps_get_free_size(caps),
      heap_caps_get_minimum_free_size(caps), heap_caps_get_largest_free_block(caps));
}
