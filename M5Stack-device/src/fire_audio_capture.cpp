#include "fire_audio_capture.h"

#include <M5Unified.h>
#include <driver/adc.h>
#include <driver/i2s.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace {
constexpr size_t kDmaReadSamples = 512;

bool i2sInstalled = false;
i2s_port_t i2sPort = I2S_NUM_0;
bool adcI2sActive = false;

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
  uint16_t raw[kDmaReadSamples] = {};

  while (!capture.stopRequested &&
         capture.capturedSamples < capture.maxSamples) {
    const size_t remaining = capture.maxSamples - capture.capturedSamples;
    const size_t requested = min(kDmaReadSamples, remaining);
    size_t bytesRead = 0;
    const esp_err_t result = i2s_read(
        i2sPort, raw, requested * sizeof(uint16_t), &bytesRead,
        pdMS_TO_TICKS(100));
    if (result != ESP_OK || bytesRead != requested * sizeof(uint16_t)) {
      if (!capture.stopRequested) capture.failed = true;
      break;
    }

    uint32_t sum = 0;
    for (size_t index = 0; index < requested; ++index)
      sum += static_cast<uint32_t>(raw[index] >> 4);
    const int32_t average = static_cast<int32_t>(sum / requested);

    const size_t offset = capture.capturedSamples;
    for (size_t index = 0; index < requested; ++index) {
      const int32_t centered = static_cast<int32_t>(raw[index] >> 4) - average;
      const int32_t amplified = centered * 32;
      capture.target[offset + index] = static_cast<int16_t>(constrain(
          amplified, static_cast<int32_t>(INT16_MIN),
          static_cast<int32_t>(INT16_MAX)));
    }
    capture.capturedSamples += requested;
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

  // FIRE speaker and ADC microphone share I2S0. Stop the speaker task and
  // release its driver before installing the input DMA stream.
  M5.Speaker.end();
  if (adc1_config_width(ADC_WIDTH_BIT_12) != ESP_OK ||
      adc1_config_channel_atten(ADC1_CHANNEL_6, ADC_ATTEN_DB_11) !=
          ESP_OK) {
    M5.Speaker.begin();
    return false;
  }

  i2sPort = I2S_NUM_0;
  i2s_config_t i2sConfig = {};
  i2sConfig.mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX |
                                           I2S_MODE_ADC_BUILT_IN);
  i2sConfig.sample_rate = static_cast<int>(sampleRate);
  i2sConfig.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  i2sConfig.channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT;
#if defined(I2S_COMM_FORMAT_STAND_I2S)
  i2sConfig.communication_format = I2S_COMM_FORMAT_STAND_I2S;
#else
  i2sConfig.communication_format = I2S_COMM_FORMAT_I2S;
#endif
  i2sConfig.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  i2sConfig.dma_buf_count = 8;
  i2sConfig.dma_buf_len = 512;
  i2sConfig.use_apll = false;
  i2sConfig.tx_desc_auto_clear = false;
  i2sConfig.fixed_mclk = 0;

  const esp_err_t installResult =
      i2s_driver_install(i2sPort, &i2sConfig, 0, nullptr);
  if (installResult != ESP_OK) {
    Serial.printf("FIRE mic prepare: i2s install=%d\n",
                  static_cast<int>(installResult));
    M5.Speaker.begin();
    return false;
  }
  const esp_err_t adcModeResult =
      i2s_set_adc_mode(ADC_UNIT_1, ADC1_CHANNEL_6);
  const esp_err_t adcEnableResult =
      adcModeResult == ESP_OK ? i2s_adc_enable(i2sPort) : adcModeResult;
  if (adcEnableResult != ESP_OK) {
    Serial.printf("FIRE mic prepare: adc mode=%d enable=%d\n",
                  static_cast<int>(adcModeResult),
                  static_cast<int>(adcEnableResult));
    i2s_driver_uninstall(i2sPort);
    M5.Speaker.begin();
    return false;
  }

  i2s_zero_dma_buffer(i2sPort);
  i2sInstalled = true;
  adcI2sActive = true;
  capture.target = target;
  capture.maxSamples = maxSamples;
  capture.sampleRate = sampleRate;
  capture.capturedSamples = 0;
  capture.stopRequested = false;
  capture.failed = false;
  capture.running = true;

  const BaseType_t taskResult = xTaskCreate(
      micCaptureTask, "fire-mic", 4096, nullptr, 3, &capture.task);
  if (taskResult != pdPASS) {
    capture.running = false;
    fireReleaseMicCapture();
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

  if (capture.running) return;
  if (adcI2sActive) {
    i2s_adc_disable(i2sPort);
    adcI2sActive = false;
  }
  if (i2sInstalled) {
    i2s_driver_uninstall(i2sPort);
    i2sInstalled = false;
  }
  M5.Speaker.begin();
}
