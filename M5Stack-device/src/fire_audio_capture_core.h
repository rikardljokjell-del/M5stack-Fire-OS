#pragma once
#include <atomic>
#include <stdint.h>
#include <stddef.h>
namespace fire_audio_capture_core {
inline int16_t rawPcm(int32_t averagedAdc12) {return static_cast<int16_t>((averagedAdc12-2048)*16);}
inline void publish(int16_t* target,size_t index,int16_t sample,std::atomic<size_t>& count) {
  target[index]=sample;
  count.store(index+1,std::memory_order_release);
}
} // namespace fire_audio_capture_core
