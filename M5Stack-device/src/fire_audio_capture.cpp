#include "fire_audio_capture.h"

#include <M5Unified.h>
#include <driver/adc.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace {
struct CaptureState {
  int16_t* target = nullptr;
  size_t maxSamples = 0;
  uint32_t sampleRate = 0;
  volatile size_t capturedSamples = 0;
  volatile bool running = false;
  volatile bool stopRequested = false;
  volatile bool failed = false;
  TaskHandle_t task = nullptr;
};

CaptureState capture;

void micCaptureTask(void*) {
  const uint32_t intervalUs = max<uint32_t>(1, 1000000UL / capture.sampleRate);
  int32_t baseline = 2048;
  int64_t nextSampleUs = esp_timer_get_time();

  while (!capture.stopRequested &&
         capture.capturedSamples < capture.maxSamples) {
    for (;;) {
      const int64_t waitUs = nextSampleUs - esp_timer_get_time();
      if (waitUs <= 0) break;
      if (waitUs > 1000) {
        vTaskDelay(1);
      } else {
        taskYIELD();
      }
    }

    const int raw = adc1_get_raw(ADC1_CHANNEL_6);
    baseline += (raw - baseline) >> 8;
    const int32_t centered = raw - baseline;
    const int32_t amplified = centered * 32;
    capture.target[capture.capturedSamples++] = static_cast<int16_t>(constrain(
        amplified, static_cast<int32_t>(INT16_MIN),
        static_cast<int32_t>(INT16_MAX)));
    nextSampleUs += intervalUs;

    // If Wi-Fi/BLE temporarily preempted the sampler, restart the clock
    // instead of trying to catch up with a burst of late samples.
    const int64_t nowUs = esp_timer_get_time();
    if (nextSampleUs + 100000 < nowUs) nextSampleUs = nowUs;
  }

  capture.running = false;
  capture.task = nullptr;
  vTaskDelete(nullptr);
}
}  // namespace

bool fireStartMicCapture(int16_t* target, size_t maxSamples,
                         uint32_t sampleRate) {
  const auto cfg = M5.Mic.config();
  if (!target || maxSamples == 0 || sampleRate == 0 ||
      !M5.Mic.isEnabled() || cfg.pin_data_in != GPIO_NUM_34 ||
      !cfg.use_adc || capture.running)
    return false;

  if (adc1_config_width(ADC_WIDTH_BIT_12) != ESP_OK ||
      adc1_config_channel_atten(ADC1_CHANNEL_6, ADC_ATTEN_DB_11) !=
          ESP_OK)
    return false;

  capture.target = target;
  capture.maxSamples = maxSamples;
  capture.sampleRate = sampleRate;
  capture.capturedSamples = 0;
  capture.stopRequested = false;
  capture.failed = false;
  capture.running = true;

  const BaseType_t taskResult = xTaskCreatePinnedToCore(
      micCaptureTask, "fire-mic", 4096, nullptr, 2, &capture.task, 0);
  if (taskResult != pdPASS) {
    capture.running = false;
    capture.task = nullptr;
    return false;
  }
  return true;
}

bool fireMicCaptureRunning() { return capture.running; }

size_t fireMicCapturedSamples() {
  const size_t captured = capture.capturedSamples;
  return min(captured, capture.maxSamples);
}

bool fireMicCaptureFailed() { return capture.failed; }

void fireStopMicCapture() { capture.stopRequested = true; }

void fireReleaseMicCapture() {
  capture.stopRequested = true;
  const uint32_t deadline = millis() + 250;
  while (capture.running && static_cast<int32_t>(millis() - deadline) < 0)
    vTaskDelay(1);
}
