#include <Arduino.h>
#include <M5Unified.h>
#include <NimBLEDevice.h>
#include <WiFi.h>

namespace {
constexpr char kServiceUuid[] = "7d3f0001-5b9a-4f2a-9c61-6f8d7c110001";
constexpr char kCharacteristicUuid[] = "7d3f0002-5b9a-4f2a-9c61-6f8d7c110001";
NimBLEScan* scan = nullptr;

class CharacteristicCallbacks final : public NimBLECharacteristicCallbacks {
 public:
  void onWrite(NimBLECharacteristic* characteristic, NimBLEConnInfo&) override {
    Serial.printf("BLE RX: %s\n", characteristic->getValue().c_str());
  }
};

void setupBle() {
  NimBLEDevice::init("M5Stack-FIRE");
  NimBLEDevice::setPower(ESP_PWR_LVL_N0);
  NimBLEServer* server = NimBLEDevice::createServer();
  NimBLEService* service = server->createService(kServiceUuid);
  NimBLECharacteristic* characteristic = service->createCharacteristic(
      kCharacteristicUuid,
      NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::NOTIFY);
  characteristic->setCallbacks(new CharacteristicCallbacks());
  characteristic->setValue("FIRE OS BLE");
  server->start();
  NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();
  advertising->addServiceUUID(kServiceUuid);
  advertising->start();
  scan = NimBLEDevice::getScan();
  scan->setActiveScan(true);
  scan->setMaxResults(8);
}
}  // namespace

void setup() {
  Serial.begin(115200);
  auto config = M5.config();
  M5.begin(config);
  WiFi.setHostname("M5Stack-FIRE");
  WiFi.mode(WIFI_STA);
  setupBle();
}

void loop() {
  static uint32_t lastScan = 0;
  if (millis() - lastScan >= 10000) {
    lastScan = millis();
    NimBLEScanResults results = scan->getResults(1200, false);
    Serial.printf("BLE scan results: %d, Wi-Fi mode: %d\n",
                  results.getCount(), static_cast<int>(WiFi.getMode()));
  }
  delay(20);
}
