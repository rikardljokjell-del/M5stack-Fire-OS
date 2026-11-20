#include <Arduino.h>
#include <M5Unified.h>
#include <esp_ota_ops.h>

// FIRE OS recovery contract:
// keep this OTA image pending so the ESP32 bootloader rolls back to the
// previous FIRE OS image on the next reset or power-cycle. A production
// external app may provide the same hook when it supports this contract.
extern "C" bool verifyRollbackLater() { return true; }

namespace {
constexpr uint8_t kButtonPins[] = {39, 38, 37};

bool allButtonsHeld() {
  return digitalRead(kButtonPins[0]) == LOW &&
         digitalRead(kButtonPins[1]) == LOW &&
         digitalRead(kButtonPins[2]) == LOW;
}

void returnToFactoryLoader() {
  const esp_partition_t* factory = esp_partition_find_first(
      ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_APP_FACTORY, nullptr);
  if (factory && esp_ota_set_boot_partition(factory) == ESP_OK) {
    delay(100);
    ESP.restart();
  }
}
}  // namespace

void setup() {
  auto config = M5.config();
  config.output_power = true;
  M5.begin(config);
  Serial.begin(115200);
  for (uint8_t pin : kButtonPins) pinMode(pin, INPUT);
  if (allButtonsHeld()) returnToFactoryLoader();
  M5.Display.fillScreen(TFT_DARKGREEN);
  M5.Display.setTextColor(TFT_WHITE, TFT_DARKGREEN);
  M5.Display.drawString("External app test", 24, 70, 2);
  M5.Display.drawString("Hold A+B+C for recovery", 24, 110, 1);
  Serial.println("External app test running");
}

void loop() {
  M5.update();
  if (allButtonsHeld()) returnToFactoryLoader();
  delay(25);
}
