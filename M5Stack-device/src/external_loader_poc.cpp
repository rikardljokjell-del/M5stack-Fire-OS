#include <Arduino.h>
#include <M5Unified.h>
#include <SD.h>
#include <esp_ota_ops.h>

namespace {
constexpr uint8_t kButtonPins[] = {39, 38, 37};
constexpr uint8_t kSdCsPin = 4;
constexpr uint8_t kMaxApps = 16;
constexpr size_t kCopyBufferSize = 4096;
constexpr size_t kMaxAppBytes = 0x500000;

String appPaths[kMaxApps];
String appNames[kMaxApps];
uint8_t appCount = 0;
uint8_t appSelection = 0;
bool safeBoot = false;
bool previousPressed[3] = {};

bool allButtonsHeld() {
  return digitalRead(kButtonPins[0]) == LOW &&
         digitalRead(kButtonPins[1]) == LOW &&
         digitalRead(kButtonPins[2]) == LOW;
}

String baseName(const String& path) {
  const int slash = path.lastIndexOf('/');
  return slash >= 0 ? path.substring(slash + 1) : path;
}

bool hasBinExtension(const String& name) {
  String lower = name;
  lower.toLowerCase();
  return lower.endsWith(".bin");
}

bool validateImage(File& file, const esp_partition_t* target) {
  if (!file || !target || file.size() == 0 ||
      static_cast<size_t>(file.size()) > target->size ||
      static_cast<size_t>(file.size()) > kMaxAppBytes) {
    return false;
  }
  uint8_t header[16] = {};
  if (file.read(header, sizeof(header)) != sizeof(header)) return false;
  file.seek(0);
  return header[0] == 0xE9 && header[12] == 0 && header[13] == 0;
}

void printPartitions() {
  Serial.println("External loader POC partitions:");
  const char* labels[] = {"factory", "ota_0", "ota_1"};
  for (const char* label : labels) {
    const esp_partition_t* part = esp_partition_find_first(
        ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_ANY, label);
    if (!part) continue;
    Serial.printf("  %-8s address=0x%06x size=%u\n", part->label,
                  part->address, part->size);
  }
}

void scanApps() {
  appCount = 0;
  File apps = SD.open("/apps");
  if (!apps || !apps.isDirectory()) return;
  File entry = apps.openNextFile();
  while (entry && appCount < kMaxApps) {
    if (!entry.isDirectory() && hasBinExtension(entry.name())) {
      appPaths[appCount] = entry.name();
      if (!appPaths[appCount].startsWith("/")) {
        appPaths[appCount] = "/apps/" + appPaths[appCount];
      }
      appNames[appCount] = baseName(entry.name());
      ++appCount;
    }
    entry.close();
    entry = apps.openNextFile();
  }
  apps.close();
}

void drawUi(const String& message = String()) {
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
  M5.Display.drawString("External App POC", 16, 12, 2);
  M5.Display.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  M5.Display.drawString(safeBoot ? "SAFE BOOT / FIRE OS" : "A/C select  B install",
                        16, 38, 1);
  if (appCount == 0) {
    M5.Display.setTextColor(TFT_ORANGE, TFT_BLACK);
    M5.Display.drawString("No .bin files in /apps", 16, 86, 1);
  } else {
    const uint8_t first = appSelection < 5 ? 0 : appSelection - 4;
    for (uint8_t row = 0; row < 5 && first + row < appCount; ++row) {
      const uint8_t index = first + row;
      const bool selected = index == appSelection;
      const int y = 70 + row * 25;
      if (selected) M5.Display.fillRect(10, y - 3, 300, 21, TFT_CYAN);
      M5.Display.setTextColor(selected ? TFT_BLACK : TFT_WHITE,
                              selected ? TFT_CYAN : TFT_BLACK);
      M5.Display.drawString(appNames[index], 20, y, 1);
    }
  }
  if (message.length() > 0) {
    M5.Display.setTextColor(TFT_ORANGE, TFT_BLACK);
    M5.Display.drawString(message, 16, 205, 1);
  }
}

bool installToInactiveSlot(const char* path) {
  const esp_partition_t* target = esp_ota_get_next_update_partition(nullptr);
  File source = SD.open(path, FILE_READ);
  if (!source || !target || !validateImage(source, target)) {
    source.close();
    return false;
  }
  esp_ota_handle_t handle = 0;
  if (esp_ota_begin(target, source.size(), &handle) != ESP_OK) {
    source.close();
    return false;
  }
  uint8_t buffer[kCopyBufferSize];
  bool ok = true;
  while (source.available()) {
    const size_t amount = source.read(buffer, sizeof(buffer));
    if (amount == 0 || esp_ota_write(handle, buffer, amount) != ESP_OK) {
      ok = false;
      break;
    }
  }
  source.close();
  if (esp_ota_end(handle) != ESP_OK) ok = false;
  if (ok && esp_ota_set_boot_partition(target) != ESP_OK) ok = false;
  return ok;
}

void handleButtons() {
  const bool pressed[] = {digitalRead(kButtonPins[0]) == LOW,
                          digitalRead(kButtonPins[1]) == LOW,
                          digitalRead(kButtonPins[2]) == LOW};
  for (uint8_t index = 0; index < 3; ++index) {
    if (pressed[index] && !previousPressed[index]) {
      if (index == 0 && appCount > 0) {
        appSelection = (appSelection + appCount - 1) % appCount;
        drawUi();
      } else if (index == 2 && appCount > 0) {
        appSelection = (appSelection + 1) % appCount;
        drawUi();
      } else if (index == 1 && !safeBoot && appCount > 0) {
        const bool ok = installToInactiveSlot(appPaths[appSelection].c_str());
        drawUi(ok ? "Installed - rebooting" : "Rejected / install failed");
        delay(1500);
        if (ok) ESP.restart();
      }
    }
    previousPressed[index] = pressed[index];
  }
}
}  // namespace

void setup() {
  auto config = M5.config();
  config.output_power = true;
  M5.begin(config);
  Serial.begin(115200);
  for (uint8_t pin : kButtonPins) pinMode(pin, INPUT);
  safeBoot = allButtonsHeld();
  printPartitions();
  if (SD.begin(kSdCsPin)) scanApps();
  drawUi();
  Serial.println("POC ready; stable FIRE OS is unchanged");
}

void loop() {
  M5.update();
  handleButtons();
  delay(25);
}
