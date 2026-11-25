#pragma once
#include <stdint.h>
namespace fire_hardware_policy {
// Grove A shares the internal I2C bus. Keep board-owned devices read-only;
// allow external devices by address, never by a product-specific driver list.
constexpr bool externalI2cWrite(uint8_t address) {
  return address >= 0x08 && address <= 0x77 && address != 0x10 &&
         address != 0x68 && address != 0x75;
}
constexpr bool externalSpi(int bus,int clock,int miso,int mosi,int cs) {
  return bus==2 && clock==18 && miso==19 && mosi==23 && cs==26;
}
} // namespace fire_hardware_policy
