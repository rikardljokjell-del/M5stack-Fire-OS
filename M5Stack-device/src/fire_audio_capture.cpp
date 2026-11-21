#include "fire_audio_capture.h"

#include <M5Unified.h>

bool fireRecordMic(int16_t* samples, size_t sampleCount, uint32_t sampleRate) {
  return M5.Mic.record(samples, sampleCount, sampleRate, false);
}
