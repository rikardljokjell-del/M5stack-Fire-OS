#include "fire_audio_capture.h"

#include <M5Unified.h>
#include <driver/i2s.h>

namespace {
bool installed = false;
i2s_port_t port = I2S_NUM_0;
}

bool fireRecordMic(int16_t* samples, size_t sampleCount, uint32_t sampleRate) {
  if (!samples || sampleCount == 0 || sampleRate == 0) return false;
  const auto cfg = M5.Mic.config();
  if (cfg.use_adc || cfg.pin_data_in < 0 || cfg.pin_bck < 0 || cfg.pin_ws < 0)
    return false;
  port = cfg.i2s_port;
  if (!installed) {
    i2s_config_t i2sConfig = {};
    i2sConfig.mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX);
    i2sConfig.sample_rate = static_cast<int>(sampleRate);
    i2sConfig.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
    i2sConfig.channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT;
#if defined(I2S_COMM_FORMAT_STAND_I2S)
    i2sConfig.communication_format = I2S_COMM_FORMAT_STAND_I2S;
#else
    i2sConfig.communication_format = I2S_COMM_FORMAT_I2S;
#endif
    i2sConfig.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
    i2sConfig.dma_buf_count = 4;
    i2sConfig.dma_buf_len = 256;
    i2sConfig.use_apll = false;
    i2sConfig.tx_desc_auto_clear = false;
    i2sConfig.fixed_mclk = 0;
    if (i2s_driver_install(port, &i2sConfig, 0, nullptr) != ESP_OK) return false;
    i2s_pin_config_t pins = {};
    pins.bck_io_num = cfg.pin_bck;
    pins.ws_io_num = cfg.pin_ws;
    pins.data_out_num = I2S_PIN_NO_CHANGE;
    pins.data_in_num = cfg.pin_data_in;
    if (i2s_set_pin(port, &pins) != ESP_OK) {
      i2s_driver_uninstall(port);
      return false;
    }
    i2s_zero_dma_buffer(port);
    installed = true;
  }
  int32_t raw[256] = {};
  size_t captured = 0;
  while (captured < sampleCount) {
    const size_t chunk = min<size_t>(256, sampleCount - captured);
    size_t bytesRead = 0;
    if (i2s_read(port, raw, chunk * sizeof(int32_t), &bytesRead,
                 pdMS_TO_TICKS(100)) != ESP_OK) return false;
    const size_t samplesRead = min(chunk, bytesRead / sizeof(int32_t));
    for (size_t index = 0; index < samplesRead; ++index)
      samples[captured + index] = static_cast<int16_t>(raw[index] >> 14);
    if (samplesRead == 0) return false;
    captured += samplesRead;
  }
  return true;
}
