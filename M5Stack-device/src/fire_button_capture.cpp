#include "fire_button_capture.h"
#include <Arduino.h>
#include <driver/gpio.h>
#include <esp_intr_alloc.h>
#include <esp_timer.h>
#include <soc/gpio_struct.h>
namespace {
DRAM_ATTR fire_buttons::Ring edges;
DRAM_ATTR std::atomic<uint32_t> asleep{0},context{1};
bool installed=false,enabled=false;
// GPIO39/38/37 are the three inspected, permanently OS-owned FIRE buttons.
__attribute__((always_inline)) inline uint8_t rawMask() {
  const uint32_t value=GPIO.in1.val;
  return (value&(1u<<7)?0:1)|(value&(1u<<6)?0:2)|(value&(1u<<5)?0:4);
}
void IRAM_ATTR capture(void*) {
  // esp_timer_get_time is IRAM in the pinned ESP-IDF; uint32 microseconds
  // avoids division, millis(), flash lookup data and all UI/driver calls.
  edges.push(rawMask(),static_cast<uint32_t>(esp_timer_get_time()),asleep.load(std::memory_order_relaxed)!=0,context.load(std::memory_order_relaxed));
}
}
namespace fire_button_capture {
bool begin() {
  if (enabled) return true;
  if (!installed) {
    // Never replace another owner's ISR service or assume its IRAM flags.
    if (gpio_install_isr_service(ESP_INTR_FLAG_IRAM)!=ESP_OK) return false;
    installed=true;
  }
  const gpio_num_t pins[]={GPIO_NUM_39,GPIO_NUM_38,GPIO_NUM_37};
  unsigned added=0;
  for (gpio_num_t pin:pins) {
    if (gpio_set_intr_type(pin,GPIO_INTR_ANYEDGE)!=ESP_OK || gpio_isr_handler_add(pin,capture,nullptr)!=ESP_OK) {
      for(unsigned i=0;i<added;++i) gpio_isr_handler_remove(pins[i]);
      return false;
    }
    ++added;
  }
  enabled=true;return true;
}
void pause() {
  if (!enabled) return;
  for(gpio_num_t pin:{GPIO_NUM_39,GPIO_NUM_38,GPIO_NUM_37}) gpio_isr_handler_remove(pin);
  enabled=false;
}
bool active() {return enabled;}
uint8_t mask() {return rawMask();}
void sleeping(bool value) {asleep.store(value?1u:0u,std::memory_order_relaxed);}
void shown(uint32_t value) {context.store(value,std::memory_order_relaxed);}
bool pop(fire_buttons::Edge& edge) {return edges.pop(edge);}
bool pending() {return edges.pending();}
bool takeOverflow() {return edges.takeOverflow();}
void discard() {edges.discard();}
uint32_t dropped() {return edges.dropped();}
}
