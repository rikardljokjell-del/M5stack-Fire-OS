#include "fire_audio_capture.h"
#include "fire_audio_capture_core.h"

#include <M5Unified.h>
#include <driver/adc.h>
#include <driver/i2s.h>
#include <atomic>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace {

// M5Stack FIRE has an analog microphone on GPIO34 / ADC1 channel 6. The
// ESP32 I2S ADC peripheral samples it continuously into DMA. Four hardware
// samples are averaged into one 16 kHz PCM sample, matching M5Unified's FIRE
// profile without its larger Mic_Class wrapper.
constexpr uint32_t kOversampling = 4;
constexpr size_t kRawReadSamples = 512;
constexpr int32_t kSpeechGain = 4;

struct CaptureState {
  int16_t* target = nullptr;
  size_t maxSamples = 0;
  uint32_t sampleRate = 0;
  bool rawMeasurement = false;
  std::atomic<size_t> capturedSamples{0};
  std::atomic<bool> running{false};
  std::atomic<bool> stopRequested{false};
  std::atomic<bool> failed{false};
  TaskHandle_t task = nullptr;
  bool speakerWasEnabled = false;
  bool driverInstalled = false;
};

CaptureState capture;

int16_t processSpeechSample(int32_t rawAverage, int64_t& baselineQ16) {
  // Track the ADC midpoint slowly so speech energy is not mistaken for DC.
  baselineQ16 +=
      ((static_cast<int64_t>(rawAverage) << 16) - baselineQ16) >> 11;
  const int32_t centered =
      rawAverage - static_cast<int32_t>(baselineQ16 >> 16);
  int32_t value = centered * kSpeechGain;
  const int32_t magnitude = value < 0 ? -value : value;
  if (magnitude > 28000) {
    value = (value < 0 ? -1 : 1) *
            min<int32_t>(28000 + (magnitude - 28000) / 4, INT16_MAX);
  }
  return static_cast<int16_t>(constrain(value, static_cast<int32_t>(INT16_MIN),
                                        static_cast<int32_t>(INT16_MAX)));
}

void micCaptureTask(void*) {
  uint16_t raw[kRawReadSamples] = {};
  int64_t baselineQ16 = 2048LL << 16;
  int32_t rawSum = 0;
  uint32_t rawInAverage = 0;

  // Discard the first DMA frames. This clears stale samples left in the I2S
  // FIFO while the speaker peripheral was being released.
  size_t bytesRead = 0;
  i2s_read(I2S_NUM_0, raw, sizeof(raw), &bytesRead, pdMS_TO_TICKS(20));
  i2s_read(I2S_NUM_0, raw, sizeof(raw), &bytesRead, pdMS_TO_TICKS(20));

  while (!capture.stopRequested.load(std::memory_order_acquire) &&
         capture.capturedSamples.load(std::memory_order_acquire) <
             capture.maxSamples) {
    bytesRead = 0;
    const esp_err_t result =
        i2s_read(I2S_NUM_0, raw, sizeof(raw), &bytesRead, pdMS_TO_TICKS(100));
    if (result != ESP_OK || bytesRead == 0) {
      if (capture.stopRequested.load(std::memory_order_acquire)) break;
      capture.failed.store(true, std::memory_order_release);
      break;
    }

    const size_t sampleCount = min(bytesRead / sizeof(uint16_t),
                                   static_cast<size_t>(kRawReadSamples));
    for (size_t index = 0; index < sampleCount; ++index) {
      // ESP32 built-in I2S ADC samples contain a 4-bit channel tag and a
      // 12-bit ADC value. Keep only the value bits.
      rawSum += static_cast<int32_t>(raw[index] & 0x0FFFu);
      if (++rawInAverage < kOversampling) continue;
      rawInAverage = 0;

      const size_t outputIndex=capture.capturedSamples.load(std::memory_order_relaxed);
      if (outputIndex >= capture.maxSamples) break;
      const int32_t average=(rawSum+(kOversampling/2))/static_cast<int32_t>(kOversampling);
      const int16_t sample=capture.rawMeasurement?fire_audio_capture_core::rawPcm(average):processSpeechSample(average,baselineQ16);
      fire_audio_capture_core::publish(capture.target,outputIndex,sample,capture.capturedSamples);
      rawSum = 0;
    }
  }

  capture.running.store(false, std::memory_order_release);
  capture.task = nullptr;
  vTaskDelete(nullptr);
}

bool installAdcDma(uint32_t sampleRate) {
  i2s_config_t config = {};
  config.mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX |
                                        I2S_MODE_ADC_BUILT_IN);
  config.sample_rate = sampleRate * kOversampling;
  config.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  config.channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT;
  config.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  config.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  config.dma_buf_count = 8;
  config.dma_buf_len = 256;
  config.use_apll = false;
  config.tx_desc_auto_clear = false;
  config.fixed_mclk = 0;

  if (i2s_driver_install(I2S_NUM_0, &config, 0, nullptr) != ESP_OK)
    return false;
  capture.driverInstalled = true;
  if (i2s_set_adc_mode(ADC_UNIT_1, ADC1_CHANNEL_6) != ESP_OK ||
      adc1_config_width(ADC_WIDTH_BIT_12) != ESP_OK ||
      adc1_config_channel_atten(ADC1_CHANNEL_6, ADC_ATTEN_DB_11) != ESP_OK ||
      i2s_adc_enable(I2S_NUM_0) != ESP_OK) {
    i2s_driver_uninstall(I2S_NUM_0);
    capture.driverInstalled = false;
    return false;
  }
  return true;
}

}  // namespace

bool fireStartMicCapture(int16_t* target, size_t maxSamples,
                         uint32_t sampleRate,bool rawMeasurement) {
  if (!target || maxSamples == 0 || sampleRate == 0 ||
      !M5.Mic.isEnabled() || capture.running.load(std::memory_order_acquire) ||
      capture.driverInstalled) {
    return false;
  }

  // FIRE uses I2S0 for both the speaker and the analog microphone. Follow
  // the supported M5Unified lifecycle: speaker off while recording, then
  // restore it after the ADC driver has been uninstalled.
  capture.speakerWasEnabled = M5.Speaker.isEnabled();
  if (capture.speakerWasEnabled) M5.Speaker.end();

  capture.target = target;
  capture.maxSamples = maxSamples;
  capture.sampleRate = sampleRate;
  capture.rawMeasurement = rawMeasurement;
  capture.capturedSamples.store(0, std::memory_order_release);
  capture.stopRequested.store(false, std::memory_order_release);
  capture.failed.store(false, std::memory_order_release);
  capture.task = nullptr;

  if (!installAdcDma(sampleRate)) {
    if (capture.speakerWasEnabled) M5.Speaker.begin();
    capture.speakerWasEnabled = false;
    capture.target = nullptr;
    capture.maxSamples = 0;
    return false;
  }

  capture.running.store(true, std::memory_order_release);
  if (xTaskCreatePinnedToCore(micCaptureTask, "fire-mic", 4096, nullptr, 3,
                              &capture.task, 0) != pdPASS) {
    capture.running.store(false, std::memory_order_release);
    i2s_adc_disable(I2S_NUM_0);
    i2s_driver_uninstall(I2S_NUM_0);
    capture.driverInstalled = false;
    if (capture.speakerWasEnabled) M5.Speaker.begin();
    capture.speakerWasEnabled = false;
    capture.target = nullptr;
    capture.maxSamples = 0;
    return false;
  }
  return true;
}

bool fireMicCaptureRunning() {
  return capture.running.load(std::memory_order_acquire);
}

size_t fireMicCapturedSamples() {
  return min(capture.capturedSamples.load(std::memory_order_acquire),
             capture.maxSamples);
}

bool fireMicCaptureFailed() {
  return capture.failed.load(std::memory_order_acquire);
}

void fireStopMicCapture() {
  capture.stopRequested.store(true, std::memory_order_release);
}

bool fireReleaseMicCapture() {
  if (!capture.driverInstalled && !capture.running.load(std::memory_order_acquire))
    return true;

  fireStopMicCapture();
  const uint32_t deadline = millis() + 1000;
  while (capture.running.load(std::memory_order_acquire) &&
         static_cast<int32_t>(millis() - deadline) < 0) {
    vTaskDelay(1);
  }

  if (capture.running.load(std::memory_order_acquire)) {
    i2s_stop(I2S_NUM_0);
    return false; // only the producer may acknowledge exit; retain its buffer
  }
  return fireTryReleaseMicCapture();
}

bool fireTryReleaseMicCapture() {
  fireStopMicCapture();
  if (capture.running.load(std::memory_order_acquire)) return false;
  if (!capture.driverInstalled) return true;
  i2s_stop(I2S_NUM_0);
  if (capture.driverInstalled) {
    i2s_adc_disable(I2S_NUM_0);
    i2s_driver_uninstall(I2S_NUM_0);
    capture.driverInstalled = false;
  }

  if (capture.speakerWasEnabled) M5.Speaker.begin();
  capture.speakerWasEnabled = false;
  capture.target = nullptr;
  capture.maxSamples = 0;
  return !capture.running.load(std::memory_order_acquire);
}
