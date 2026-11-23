#include "fire_os.h"
#include "fire_audio_capture.h"

#include <M5Unified.h>
#ifdef FIRE_OS_BLE
#include <driver/rmt.h>
#endif
#include <utility/led/LED_Strip_Class.hpp>
#include <Preferences.h>
#include <SD.h>
#include <WiFi.h>
#include <Wire.h>
#include <WebServer.h>
#include <driver/gpio.h>
#include <esp_system.h>
#include <esp_sleep.h>
#include <esp_ota_ops.h>
#include <sys/time.h>
#include <time.h>
#include <esp_sntp.h>
#include <math.h>
#include <string.h>
#include <mbedtls/sha256.h>
#ifdef FIRE_OS_BLE
#include <NimBLEDevice.h>
#endif

namespace {
constexpr uint8_t kSdCsPin = 4;
constexpr char kSdNameCharset[] =
    " ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-.";
constexpr uint8_t kButtonPins[] = {39, 38, 37};
constexpr uint16_t kBg = 0x1082;
constexpr uint16_t kPanel = 0x18E3;
constexpr uint16_t kText = 0xE73C;
constexpr uint16_t kMuted = 0x7BEF;
constexpr uint16_t kCyan = 0x05FF;
constexpr uint16_t kOrange = 0xFD20;
constexpr uint16_t kGreen = 0x07E0;
constexpr uint16_t kRed = 0xF800;
constexpr uint16_t kPurple = 0xC81F;
constexpr uint16_t kDurationMinutes[] = {
    0,  1,  2,  3,  4,  5,  6,  7,  8,  9,  10,
    11, 12, 13, 14, 15, 16, 17, 18, 19, 20};
constexpr uint8_t kBrightnessValues[] = {24, 42, 60, 90, 120,
                                         150, 180, 210, 235, 255};
constexpr uint8_t kBrightnessStepCount = 10;
constexpr uint8_t kVolumeStepCount = 10;
constexpr uint8_t kTimezoneCount = DateTimeService::kTimezoneCount;
constexpr char kFirmwareVersion[] = "fire-os-1.1";
constexpr uint32_t kFirmwareBootGuardMs = 15000;
constexpr uint32_t kLuaServiceDisplay = 1u << 0;
constexpr uint32_t kLuaServiceButtons = 1u << 1;
constexpr uint32_t kLuaServiceRgb = 1u << 2;
constexpr uint32_t kLuaServiceImu = 1u << 3;
constexpr uint32_t kLuaServiceTime = 1u << 4;
constexpr uint32_t kLuaServiceJobs = 1u << 5;
constexpr uint32_t kLuaServiceGpio = 1u << 6;
constexpr uint32_t kLuaServicePwm = 1u << 7;
constexpr uint32_t kLuaServiceI2c = 1u << 8;
constexpr uint32_t kLuaServiceUart = 1u << 9;
constexpr uint32_t kLuaServiceAdc = 1u << 10;
constexpr uint32_t kLuaServiceDac = 1u << 11;
constexpr uint32_t kLuaServiceSpi = 1u << 12;
constexpr uint32_t kLuaServiceWifi = 1u << 13;
constexpr uint32_t kLuaServiceBluetooth = 1u << 14;
constexpr uint32_t kLuaServiceMic = 1u << 15;
constexpr uint32_t kLuaServiceSpeaker = 1u << 16;
constexpr uint32_t kLuaServiceSd = 1u << 17;
constexpr uint32_t kLuaServicePower = 1u << 18;
constexpr uint32_t kLuaServiceRtc = 1u << 19;
constexpr uint32_t kBootMelodySampleRate = 8000;
constexpr size_t kBootMelodySampleCount = 3160;  // 395 ms at 8 kHz
int8_t kBootMelodyPcm[kBootMelodySampleCount] = {};
bool kBootMelodyPcmReady = false;

String firmwareVersionLabel() {
  String label = kFirmwareVersion;
  if (label.startsWith("fire-os-"))
    return "FIRE OS v" + label.substring(8);
  return label;
}

void prepareBootMelody() {
  if (kBootMelodyPcmReady) return;
  struct Note {
    float frequency;
    uint16_t startMs;
    uint16_t durationMs;
  };
  constexpr Note notes[] = {{523.251f, 0, 105},
                            {659.255f, 130, 105},
                            {783.991f, 260, 135}};
  constexpr float kTwoPi = 6.28318530718f;
  for (const Note& note : notes) {
    const size_t start = note.startMs * kBootMelodySampleRate / 1000;
    const size_t count = note.durationMs * kBootMelodySampleRate / 1000;
    for (size_t sample = 0; sample < count; ++sample) {
      const size_t position = start + sample;
      if (position >= kBootMelodySampleCount) break;
      float envelope = 1.0f;
      const size_t edge = kBootMelodySampleRate / 100;  // 10 ms
      if (sample < edge) envelope = static_cast<float>(sample) / edge;
      if (count - sample <= edge)
        envelope = min(envelope, static_cast<float>(count - sample) / edge);
      const float phase = kTwoPi * note.frequency * sample /
                          kBootMelodySampleRate;
      kBootMelodyPcm[position] = static_cast<int8_t>(
          sinf(phase) * 108.0f * envelope);
    }
  }
  kBootMelodyPcmReady = true;
}

struct TimezoneInfo {
  const char* label;
  const char* daylight;
  const char* standard;
};

// POSIX TZ rules keep automatic summer time local and deterministic without
// requiring a network connection. The labels are intentionally short enough
// for the 320x240 settings page.
constexpr TimezoneInfo kTimezones[kTimezoneCount] = {
    {"UTC", "UTC0", "UTC0"},
    {"Europe/Oslo", "CET-1CEST,M3.5.0,M10.5.0/3", "CET-1"},
    {"Europe/London", "GMT0BST,M3.5.0/1,M10.5.0/2", "GMT0"},
    {"Europe/Berlin", "CET-1CEST,M3.5.0,M10.5.0/3", "CET-1"},
    {"America/New_York", "EST5EDT,M3.2.0/2,M11.1.0/2", "EST5"},
    {"America/Los_Angeles", "PST8PDT,M3.2.0/2,M11.1.0/2", "PST8"},
    {"Asia/Tokyo", "JST-9", "JST-9"},
};

Preferences* firePreferences = nullptr;
#define preferences (*firePreferences)
M5Canvas* uiCanvas = nullptr;
#define ui (*uiCanvas)
WebServer* fireWifiSetupServer = nullptr;
#define wifiSetupServer (*fireWifiSetupServer)
FireOS* activeFireOs = nullptr;
bool bluetoothRadioReady = false;

void configureFireRgbStrip() {
#ifdef FIRE_OS_BLE
  pinMode(15, OUTPUT_OPEN_DRAIN);
  rmt_config_t config = {};
  config.rmt_mode = RMT_MODE_TX;
  config.channel = RMT_CHANNEL_0;
  config.gpio_num = GPIO_NUM_15;
  config.clk_div = 2;
  config.mem_block_num = 1;
  config.tx_config.loop_en = false;
  config.tx_config.carrier_en = false;
  config.tx_config.idle_output_en = true;
  config.tx_config.idle_level = RMT_IDLE_LEVEL_LOW;
  rmt_config(&config);
  rmt_driver_install(config.channel, 0, 0);
#else
  auto bus = std::make_shared<m5::LedBus_RMT>();
  auto busConfig = bus->getConfig();
  busConfig.pin_data = 15;
  bus->setConfig(busConfig);

  auto strip = std::make_shared<m5::LED_Strip_Class>();
  auto stripConfig = strip->getConfig();
  stripConfig.led_count = 10;
  strip->setConfig(stripConfig);
  strip->setBus(bus);
  M5.Led.setLedInstance(strip);
  M5.Led.setAutoDisplay(false);
  pinMode(15, OUTPUT_OPEN_DRAIN);
  M5.Led.begin();
#endif
}

#ifdef FIRE_OS_BLE
void writeFireRgbArray(const uint8_t values[10][3], uint8_t brightness) {
  static rmt_item32_t items[10 * 24 + 1];
  uint16_t item = 0;
  for (uint8_t pixel = 0; pixel < 10; ++pixel) {
    const uint8_t bytes[] = {
        static_cast<uint8_t>(static_cast<uint16_t>(values[pixel][1]) * brightness / 255),
        static_cast<uint8_t>(static_cast<uint16_t>(values[pixel][0]) * brightness / 255),
        static_cast<uint8_t>(static_cast<uint16_t>(values[pixel][2]) * brightness / 255)};
    for (uint8_t byte : bytes) {
      for (int8_t bit = 7; bit >= 0; --bit) {
        const bool one = (byte >> bit) & 1;
        items[item].level0 = 1;
        items[item].duration0 = one ? 28 : 14;
        items[item].level1 = 0;
        items[item].duration1 = one ? 24 : 32;
        ++item;
      }
    }
  }
  items[item].level0 = 0;
  items[item].duration0 = 2000;
  items[item].level1 = 0;
  items[item].duration1 = 0;
  rmt_write_items(RMT_CHANNEL_0, items, item + 1, true);
}

void writeFireRgbRaw(uint8_t red, uint8_t green, uint8_t blue,
                     uint8_t brightness) {
  uint8_t values[10][3] = {};
  for (uint8_t pixel = 0; pixel < 10; ++pixel) {
    values[pixel][0] = red;
    values[pixel][1] = green;
    values[pixel][2] = blue;
  }
  writeFireRgbArray(values, brightness);
}
#endif

void writeRgbForDebug(uint8_t red, uint8_t green, uint8_t blue,
                      uint8_t brightness) {
#ifdef FIRE_OS_BLE
  writeFireRgbRaw(red, green, blue, brightness);
#else
  M5.Led.setBrightness(brightness);
  M5.Led.setAllColor(red, green, blue);
  M5.Led.display();
#endif
}


#ifdef FIRE_OS_BLE
constexpr char kBluetoothServiceUuid[] =
    "7d3f0001-5b9a-4f2a-9c61-6f8d7c110001";
constexpr char kBluetoothCharacteristicUuid[] =
    "7d3f0002-5b9a-4f2a-9c61-6f8d7c110001";
NimBLEServer* bluetoothServer = nullptr;
NimBLECharacteristic* bluetoothCharacteristic = nullptr;
NimBLEScan* bluetoothScan = nullptr;
NimBLEClient* bluetoothClient = nullptr;
bool bluetoothPeripheralConnected = false;
String* bluetoothPeripheralAddressPtr = nullptr;
#define bluetoothPeripheralAddress (*bluetoothPeripheralAddressPtr)
uint8_t bluetoothPeripheralAddressType = 0;
portMUX_TYPE bluetoothStateMux = portMUX_INITIALIZER_UNLOCKED;
volatile bool bluetoothPendingConnected = false;
volatile bool bluetoothPendingUpdate = false;
char bluetoothPendingAddress[32] = {};
uint8_t bluetoothPendingAddressType = 0;

class FireBluetoothServerCallbacks final : public NimBLEServerCallbacks {
 public:
  void onConnect(NimBLEServer*, NimBLEConnInfo& connInfo) override {
    bluetoothPeripheralConnected = true;
    const String address = connInfo.getAddress().toString().c_str();
    portENTER_CRITICAL(&bluetoothStateMux);
    strncpy(bluetoothPendingAddress, address.c_str(),
            sizeof(bluetoothPendingAddress) - 1);
    bluetoothPendingAddress[sizeof(bluetoothPendingAddress) - 1] = '\0';
    bluetoothPendingAddressType = connInfo.getAddress().getType();
    bluetoothPendingConnected = true;
    bluetoothPendingUpdate = true;
    portEXIT_CRITICAL(&bluetoothStateMux);
  }

  void onDisconnect(NimBLEServer*, NimBLEConnInfo&, int) override {
    bluetoothPeripheralConnected = false;
    portENTER_CRITICAL(&bluetoothStateMux);
    bluetoothPendingAddress[0] = '\0';
    bluetoothPendingConnected = false;
    bluetoothPendingUpdate = true;
    portEXIT_CRITICAL(&bluetoothStateMux);
  }
};

class FireBluetoothCallbacks final : public NimBLECharacteristicCallbacks {
 public:
  void onWrite(NimBLECharacteristic* characteristic, NimBLEConnInfo&) override {
    Serial.printf("FIRE BLE RX: %s\n", characteristic->getValue().c_str());
  }
};
#endif

String twoDigits(uint8_t value) {
  return value < 10 ? String("0") + String(value) : String(value);
}

uint8_t daysInMonth(uint16_t year, uint8_t month) {
  static constexpr uint8_t days[] = {31, 28, 31, 30, 31, 30,
                                     31, 31, 30, 31, 30, 31};
  if (month == 2 && ((year % 4 == 0 && year % 100 != 0) || year % 400 == 0)) {
    return 29;
  }
  return days[month - 1];
}

String formatBytes(uint32_t bytes) {
  if (bytes >= 1024UL * 1024UL) {
    return String(bytes / (1024UL * 1024UL)) + " MB";
  }
  return String(bytes / 1024UL) + " KB";
}

String sha256File(const String& path) {
  File file = SD.open(path, FILE_READ);
  if (!file || file.isDirectory()) {
    if (file) file.close();
    return "";
  }
  mbedtls_sha256_context sha;
  mbedtls_sha256_init(&sha);
  mbedtls_sha256_starts_ret(&sha, 0);
  uint8_t buffer[512] = {};
  while (file.available()) {
    const size_t amount = file.read(buffer, sizeof(buffer));
    if (amount == 0) {
      file.close();
      mbedtls_sha256_free(&sha);
      return "";
    }
    mbedtls_sha256_update_ret(&sha, buffer, amount);
  }
  file.close();
  uint8_t digest[32] = {};
  mbedtls_sha256_finish_ret(&sha, digest);
  mbedtls_sha256_free(&sha);
  const char* digits = "0123456789abcdef";
  String result;
  result.reserve(64);
  for (uint8_t value : digest) {
    result += digits[value >> 4];
    result += digits[value & 0x0F];
  }
  return result;
}

String compactPreferenceKey(const char* prefix, const String& value) {
  // ESP32 Preferences/NVS keys are limited to 15 characters. Keep the full
  // package/run ID in the value and use a stable short FNV-1a key.
  uint32_t hash = 2166136261UL;
  for (size_t index = 0; index < value.length(); ++index) {
    hash ^= static_cast<uint8_t>(value[index]);
    hash *= 16777619UL;
  }
  return String(prefix) + String(hash, HEX);
}

String jsonStringField(const String& json, const char* key) {
  const String marker = String("\"") + key + "\"";
  const int keyAt = json.indexOf(marker);
  if (keyAt < 0) return "";
  const int colon = json.indexOf(':', keyAt + marker.length());
  if (colon < 0) return "";
  const int start = json.indexOf('"', colon + 1);
  if (start < 0) return "";
  String value;
  bool escaped = false;
  for (int index = start + 1; index < json.length(); ++index) {
    const char character = json[index];
    if (escaped) {
      value += character == 'n' ? '\n' : character == 'r' ? '\r' : character;
      escaped = false;
    } else if (character == '\\') {
      escaped = true;
    } else if (character == '"') {
      break;
    } else {
      value += character;
    }
  }
  return value;
}

String jsonEscapeField(const String& input) {
  String output;
  output.reserve(input.length() + 4);
  for (size_t index = 0; index < input.length(); ++index) {
    const char c = input[index];
    if (c == '\\' || c == '"') output += '\\';
    if (c == '\n') output += "\\n";
    else if (c == '\r') output += "\\r";
    else output += c;
  }
  return output;
}

bool removeSdTree(const String& path) {
  File entry = SD.open(path);
  if (!entry) return true;
  if (!entry.isDirectory()) {
    entry.close();
    return SD.remove(path);
  }
  File child = entry.openNextFile();
  while (child) {
    String childPath = child.name();
    if (!childPath.startsWith("/")) childPath = path + "/" + childPath;
    child.close();
    if (!removeSdTree(childPath)) {
      entry.close();
      return false;
    }
    child = entry.openNextFile();
  }
  entry.close();
  return SD.rmdir(path);
}

bool validSha256Hex(const String& value) {
  if (value.length() != 64) return false;
  for (size_t index = 0; index < value.length(); ++index) {
    const char c = value[index];
    const bool digit = c >= '0' && c <= '9';
    const bool lower = c >= 'a' && c <= 'f';
    const bool upper = c >= 'A' && c <= 'F';
    if (!digit && !lower && !upper) return false;
  }
  return true;
}

int jsonIntField(const String& json, const char* key, int fallback = 0) {
  const String marker = String("\"") + key + "\"";
  const int keyAt = json.indexOf(marker);
  if (keyAt < 0) return fallback;
  const int colon = json.indexOf(':', keyAt + marker.length());
  if (colon < 0) return fallback;
  int end = colon + 1;
  while (end < json.length() && (json[end] == ' ' || json[end] == '\t')) ++end;
  return json.substring(end).toInt();
}

bool jsonBoolField(const String& json, const char* key, bool fallback = false) {
  const String marker = String("\"") + key + "\"";
  const int keyAt = json.indexOf(marker);
  if (keyAt < 0) return fallback;
  const int colon = json.indexOf(':', keyAt + marker.length());
  if (colon < 0) return fallback;
  int start = colon + 1;
  while (start < json.length() &&
         (json[start] == ' ' || json[start] == '\t' || json[start] == '\r' ||
          json[start] == '\n'))
    ++start;
  if (json.startsWith("true", start)) return true;
  if (json.startsWith("false", start)) return false;
  return fallback;
}

bool luaManifestServiceMask(const String& manifest, uint32_t& mask) {
  const int at = manifest.indexOf("\"required_services\"");
  if (at < 0) return false;
  const int start = manifest.indexOf('[', at);
  const int end = start < 0 ? -1 : manifest.indexOf(']', start);
  if (start < 0 || end < 0) return false;
  mask = 0;
  int cursor = start + 1;
  while (cursor < end) {
    while (cursor < end && (manifest[cursor] == ' ' ||
                            manifest[cursor] == '\t' ||
                            manifest[cursor] == '\r' ||
                            manifest[cursor] == '\n' ||
                            manifest[cursor] == ',')) {
      ++cursor;
    }
    if (cursor >= end) break;
    if (manifest[cursor] != '"') return false;
    const int valueStart = cursor + 1;
    const int valueEnd = manifest.indexOf('"', valueStart);
    if (valueEnd < 0 || valueEnd > end) return false;
    const String service = manifest.substring(valueStart, valueEnd);
    uint32_t bit = 0;
    if (service == "display") bit = kLuaServiceDisplay;
    else if (service == "buttons") bit = kLuaServiceButtons;
    else if (service == "rgb") bit = kLuaServiceRgb;
    else if (service == "imu") bit = kLuaServiceImu;
    else if (service == "time") bit = kLuaServiceTime;
    else if (service == "jobs") bit = kLuaServiceJobs;
    else if (service == "gpio") bit = kLuaServiceGpio;
    else if (service == "pwm") bit = kLuaServicePwm;
    else if (service == "i2c") bit = kLuaServiceI2c;
    else if (service == "uart") bit = kLuaServiceUart;
    else if (service == "adc") bit = kLuaServiceAdc;
    else if (service == "dac") bit = kLuaServiceDac;
    else if (service == "spi") bit = kLuaServiceSpi;
    else if (service == "sd") bit = kLuaServiceSd;
    else if (service == "rtc") bit = kLuaServiceRtc;
    else if (service == "speaker") bit = kLuaServiceSpeaker;
    else return false;
    if ((mask & bit) != 0) return false;
    mask |= bit;
    cursor = valueEnd + 1;
  }
  return true;
}

const char* luaFailureCode(const String& error) {
  if (error == "vm_not_initialized") return "vm_not_initialized";
  if (error == "source_empty") return "source_empty";
  if (error == "source_size") return "source_size";
  if (error == "source_hash" || error.startsWith("App source checksum"))
    return "source_hash";
  if (error.startsWith("Lua syntax")) return "source_syntax";
  if (error.startsWith("Lua init")) return "init_error";
  if (error.startsWith("Lua on_button") || error.startsWith("Lua update"))
    return "runtime_error";
  if (error.startsWith("Lua memory") || error == "memory_error")
    return "memory_error";
  if (error == "runtime_limit") return "runtime_limit";
  return "load_error";
}

String durationLabel(uint8_t option) {
  const uint16_t minutes = kDurationMinutes[min<uint8_t>(option, 20)];
  return minutes == 0 ? "Always on" : String(minutes) + " min";
}

const char* doubleClickActionLabel(uint8_t action) {
  switch (action) {
    case 1:
      return "Apps";
    case 2:
      return "Power";
    case 3:
      return "All settings";
    case 4:
      return "Display & Sound";
    case 5:
      return "Wi-Fi";
    case 6:
      return "Bluetooth";
    case 7:
      return "Menu Layout";
    case 8:
      return "System Info";
    default:
      return "Disabled";
  }
}

uint8_t nearestBrightnessStep(uint8_t brightness) {
  uint8_t best = 0;
  uint8_t distance = 255;
  for (uint8_t index = 0; index < kBrightnessStepCount; ++index) {
    const uint8_t current = kBrightnessValues[index];
    const uint8_t currentDistance = current > brightness ? current - brightness
                                                         : brightness - current;
    if (currentDistance < distance) {
      distance = currentDistance;
      best = index;
    }
  }
  return best;
}

uint8_t volumeValue(uint8_t step) {
  return static_cast<uint8_t>(step * 100 / (kVolumeStepCount - 1));
}

// FIRE OS presents volume as 0..100 in the UI, while M5Unified expects the
// speaker master volume in its full 0..255 range. Keep mute exact and map the
// remaining UI levels to the complete hardware range.
uint8_t speakerVolumeValue(uint8_t uiVolume) {
  if (uiVolume == 0) return 0;
  return static_cast<uint8_t>(min<uint16_t>(255, uiVolume * 255U / 100U));
}

uint8_t nearestVolumeStep(uint8_t volume) {
  uint8_t best = 0;
  uint8_t distance = 255;
  for (uint8_t index = 0; index < kVolumeStepCount; ++index) {
    const uint8_t current = volumeValue(index);
    const uint8_t currentDistance = current > volume ? current - volume
                                                     : volume - current;
    if (currentDistance < distance) {
      distance = currentDistance;
      best = index;
    }
  }
  return best;
}

String cleanFooterLabel(const char* raw) {
  String text(raw);
  if (text.startsWith("A/C  ")) return text.substring(5);
  if (text.startsWith("A  ") || text.startsWith("B  ") ||
      text.startsWith("C  ")) {
    text = text.substring(3);
  }
  if (text.endsWith("  A") || text.endsWith("  B") ||
      text.endsWith("  C")) {
    text.remove(text.length() - 3);
  }
  return text;
}

String wifiFailureReason(wl_status_t status) {
  switch (status) {
    case WL_NO_SSID_AVAIL:
      return "network not found";
    case WL_CONNECT_FAILED:
      return "password rejected or connection failed";
    case WL_CONNECTION_LOST:
      return "connection lost";
    case WL_DISCONNECTED:
      return "disconnected";
    default:
      return "status " + String(static_cast<int>(status));
  }
}

void handleWifiSetupRoot() {
  const String token = wifiSetupServer.arg("token");
  if (activeFireOs == nullptr || !activeFireOs->wifiSetupTokenValid(token)) {
    wifiSetupServer.send(403, "text/plain", "Invalid or missing setup token");
    return;
  }
  const bool backendSetup = activeFireOs->aiApiSetupActive();
  const String html = backendSetup
      ? "<!doctype html><html><meta name='viewport' content='width=device-width'><title>FIRE OS backend</title><style>body{font-family:sans-serif;max-width:480px;margin:24px auto;padding:0 16px}input{width:100%;padding:10px;margin:6px 0 16px;box-sizing:border-box}button{padding:12px 18px}</style><body><h2>FIRE OS AI backend</h2><p>Empty fields keep their current value. Use the PC IP address and its device token.</p><form method='post' action='/save'><label>Backend host/IP</label><input name='host' autocomplete='off'><label>Backend port</label><input name='port' inputmode='numeric' autocomplete='off'><label>Device token</label><input name='backend_token' type='password' autocomplete='off'><label>Device ID</label><input name='device' autocomplete='off'><input type='hidden' name='token' value='" + token + "'><button type='submit'>Save backend</button></form></body></html>"
      :
      "<!doctype html><html><meta name='viewport' content='width=device-width'>"
      "<title>FIRE OS setup</title><style>body{font-family:sans-serif;max-width:480px;"
      "margin:24px auto;padding:0 16px}input{width:100%;padding:10px;margin:6px 0 16px;"
      "box-sizing:border-box}button{padding:12px 18px}</style><body>"
      "<h2>FIRE OS setup</h2><p>Leave a field empty to keep its current value.</p>"
      "<form method='post' action='/save'><label>Wi-Fi SSID</label>"
      "<input name='ssid' autocomplete='off'><label>Wi-Fi password</label>"
      "<input name='password' type='password' autocomplete='off'>"
      "<input type='hidden' name='token' value='" +
      token + "'><button type='submit'>Save</button></form></body></html>";
  wifiSetupServer.send(200, "text/html", html);
}

void handleWifiSetupSave() {
  if (activeFireOs == nullptr) {
    wifiSetupServer.send(500, "text/plain", "OS unavailable");
    return;
  }
  if (!activeFireOs->wifiSetupTokenValid(wifiSetupServer.arg("token"))) {
    wifiSetupServer.send(403, "text/plain", "Invalid setup token");
    return;
  }
  if (activeFireOs->aiApiSetupActive()) {
    const bool saved = activeFireOs->saveBackendSetupFields(
        wifiSetupServer.arg("host"), wifiSetupServer.arg("port"),
        wifiSetupServer.arg("backend_token"), wifiSetupServer.arg("device"));
    if (!saved) {
      wifiSetupServer.send(400, "text/plain", "Invalid backend configuration");
      return;
    }
  } else {
    const String ssid = wifiSetupServer.arg("ssid");
    const String password = wifiSetupServer.arg("password");
    const String apiKey = wifiSetupServer.arg("api");
    activeFireOs->saveMobileSetupFields(ssid, password, apiKey);
  }
  wifiSetupServer.send(200, "text/html",
                       "<html><body><h2>Saved</h2><p>FIRE OS kept empty fields "
                       "unchanged. You can close this page.</p></body></html>");
  if (activeFireOs->aiApiSetupActive()) activeFireOs->finishBackendSetup();
}

void handleWifiBackendProvision() {
  if (activeFireOs == nullptr) {
    wifiSetupServer.send(500, "text/plain", "OS unavailable");
    return;
  }
  if (!activeFireOs->aiApiSetupActive()) {
    wifiSetupServer.send(403, "text/plain",
                         "Backend provisioning is not active");
    return;
  }

  // The provisioning URL is only accepted while the temporary, password-
  // protected FIRE-Setup network is active.  An optional setup token is
  // accepted as an additional check when a QR generator includes it, but the
  // backend token itself is never logged or rendered back in the response.
  const String setupToken = wifiSetupServer.arg("token");
  if (setupToken.length() > 0 &&
      !activeFireOs->wifiSetupTokenValid(setupToken)) {
    wifiSetupServer.send(403, "text/plain", "Invalid setup token");
    return;
  }

  const String host = wifiSetupServer.arg("host");
  const String port = wifiSetupServer.arg("port");
  const String deviceId = wifiSetupServer.arg("device").length() > 0
                              ? wifiSetupServer.arg("device")
                              : wifiSetupServer.arg("device_id");
  const String backendToken = wifiSetupServer.arg("backend_token");
  const long parsedPort = port.toInt();

  if (host.length() == 0 || parsedPort < 1 || parsedPort > 65535 ||
      deviceId.length() == 0 || backendToken.length() < 24) {
    wifiSetupServer.send(
        400, "text/html",
        "<html><meta name='viewport' content='width=device-width'>"
        "<body><h2>Invalid backend setup</h2>"
        "<p>The QR code must contain PC address, port, device ID and a valid "
        "device token.</p><p>Return to the FIRE OS screen and scan a new "
        "backend QR code.</p></body></html>");
    return;
  }

  // Send the acknowledgement before stopping the temporary AP.  This gives
  // the phone a useful result page even though saving the settings closes the
  // setup network immediately afterwards.
  wifiSetupServer.send(
      200, "text/html",
      "<html><meta name='viewport' content='width=device-width'>"
      "<body><h2>Backend saved</h2>"
      "<p>FIRE OS saved the PC address, port, device ID and token.</p>"
      "<p>You can return to FIRE OS. It will connect to the backend when Wi-Fi "
      "is available.</p></body></html>");
  if (!activeFireOs->saveBackendSetupFields(host, port, backendToken, deviceId)) {
    wifiSetupServer.send(400, "text/plain", "Invalid backend configuration");
    return;
  }
  activeFireOs->finishBackendSetup();
}

void writeWavHeader(uint8_t* data, uint32_t payloadBytes,
                    uint32_t sampleRate) {
  const uint32_t riffSize = 36 + payloadBytes;
  const uint32_t byteRate = sampleRate * 2;
  const uint16_t blockAlign = 2;
  const uint16_t bitsPerSample = 16;
  memcpy(data, "RIFF", 4);
  memcpy(data + 4, &riffSize, 4);
  memcpy(data + 8, "WAVEfmt ", 8);
  const uint32_t fmtSize = 16;
  const uint16_t format = 1;
  const uint16_t channels = 1;
  memcpy(data + 16, &fmtSize, 4);
  memcpy(data + 20, &format, 2);
  memcpy(data + 22, &channels, 2);
  memcpy(data + 24, &sampleRate, 4);
  memcpy(data + 28, &byteRate, 4);
  memcpy(data + 32, &blockAlign, 2);
  memcpy(data + 34, &bitsPerSample, 2);
  memcpy(data + 36, "data", 4);
  memcpy(data + 40, &payloadBytes, 4);
}

// Keep a defensive duration check for a future capture backend, but do not
// resample a correctly timed DMA stream. Resampling even a small amount adds
// avoidable interpolation to speech.
size_t normalizePcmDuration(int16_t* pcm, size_t inputSamples,
                            uint32_t elapsedMs, uint32_t sampleRate,
                            size_t maxSamples) {
  if (!pcm || inputSamples == 0 || elapsedMs == 0) return inputSamples;
  const uint64_t expected64 =
      (static_cast<uint64_t>(elapsedMs) * sampleRate + 500) / 1000;
  const size_t outputSamples = static_cast<size_t>(min<uint64_t>(
      maxSamples, max<uint64_t>(1, expected64)));
  const uint64_t sampleDelta = outputSamples > inputSamples
                                   ? outputSamples - inputSamples
                                   : inputSamples - outputSamples;
  if (sampleDelta * 100ULL <= inputSamples * 2ULL)
    return inputSamples;
  if (outputSamples == inputSamples || inputSamples == 1) return inputSamples;

  const uint64_t inputSpan = inputSamples - 1;
  const uint64_t outputSpan = outputSamples - 1;
  if (outputSamples > inputSamples) {
    for (size_t output = outputSamples; output-- > 0;) {
      const uint64_t scaled = static_cast<uint64_t>(output) * inputSpan;
      const size_t left = static_cast<size_t>(scaled / outputSpan);
      const uint64_t fraction = scaled % outputSpan;
      const int64_t a = pcm[left];
      const int64_t b = pcm[min(left + 1, inputSamples - 1)];
      pcm[output] = static_cast<int16_t>(
          a + ((b - a) * static_cast<int64_t>(fraction)) /
                  static_cast<int64_t>(outputSpan));
    }
  } else {
    for (size_t output = 0; output < outputSamples; ++output) {
      const uint64_t scaled = static_cast<uint64_t>(output) * inputSpan;
      const size_t left = static_cast<size_t>(scaled / outputSpan);
      const uint64_t fraction = scaled % outputSpan;
      const int64_t a = pcm[left];
      const int64_t b = pcm[min(left + 1, inputSamples - 1)];
      pcm[output] = static_cast<int16_t>(
          a + ((b - a) * static_cast<int64_t>(fraction)) /
                  static_cast<int64_t>(outputSpan));
    }
  }
  return outputSamples;
}
}  // namespace

void DateTimeService::begin() {
  preferences.begin("fire_os", false);
  timezoneIndex_ = min<uint8_t>(preferences.getUChar("tz", 1), kTimezoneCount - 1);
  dstAuto_ = preferences.getBool("dst", true);
  applyTimezone();

  // Prefer the hardware RTC so time survives a normal reboot and does not
  // depend on Wi-Fi. M5Unified reports false when this FIRE revision has no
  // usable RTC, in which case the persisted epoch is used below.
  if (M5.Rtc.isEnabled()) {
    const auto rtc = M5.Rtc.getDateTime();
    if (rtc.date.year >= 2020 && rtc.date.year <= 2099 &&
        rtc.date.month >= 1 && rtc.date.month <= 12 && rtc.date.date >= 1 &&
        rtc.date.date <= 31 && rtc.time.hours >= 0 && rtc.time.hours <= 23 &&
        rtc.time.minutes >= 0 && rtc.time.minutes <= 59 &&
        rtc.time.seconds >= 0 && rtc.time.seconds <= 59) {
      tm local{};
      local.tm_year = rtc.date.year - 1900;
      local.tm_mon = rtc.date.month - 1;
      local.tm_mday = rtc.date.date;
      local.tm_hour = rtc.time.hours;
      local.tm_min = rtc.time.minutes;
      local.tm_sec = rtc.time.seconds;
      local.tm_isdst = -1;
      const time_t epoch = mktime(&local);
      timeval tv{};
      tv.tv_sec = epoch;
      settimeofday(&tv, nullptr);
      configured_ = epoch > 1000000000UL;
      if (configured_) {
        preferences.putULong("epoch", static_cast<uint32_t>(epoch));
        return;
      }
    }
  }

  const uint32_t savedEpoch = preferences.getULong("epoch", 0);
  configured_ = savedEpoch > 1000000000UL;
  if (configured_) {
    timeval tv{};
    tv.tv_sec = savedEpoch;
    settimeofday(&tv, nullptr);
  }
}

void DateTimeService::applyTimezone() const {
  const TimezoneInfo& zone = kTimezones[timezoneIndex_];
  setenv("TZ", dstAuto_ ? zone.daylight : zone.standard, 1);
  tzset();
}

bool DateTimeService::setLocalDateTime(uint16_t year, uint8_t month,
                                       uint8_t day, uint8_t hour,
                                       uint8_t minute) {
  if (year < 2020 || year > 2099 || month < 1 || month > 12 || day < 1 ||
      day > daysInMonth(year, month) || hour > 23 || minute > 59) {
    return false;
  }
  applyTimezone();
  tm local{};
  local.tm_year = year - 1900;
  local.tm_mon = month - 1;
  local.tm_mday = day;
  local.tm_hour = hour;
  local.tm_min = minute;
  local.tm_sec = 0;
  local.tm_isdst = -1;
  const time_t epoch = mktime(&local);
  if (epoch <= 0) return false;
  timeval tv{};
  tv.tv_sec = epoch;
  settimeofday(&tv, nullptr);
  if (M5.Rtc.isEnabled()) M5.Rtc.setDateTime(&local);
  configured_ = true;
  return true;
}

bool DateTimeService::setSystemLocalDateTime(const tm& localTime) {
  tm normalized = localTime;
  normalized.tm_isdst = -1;
  const time_t epoch = mktime(&normalized);
  if (epoch <= 0) return false;
  timeval tv{};
  tv.tv_sec = epoch;
  settimeofday(&tv, nullptr);
  if (M5.Rtc.isEnabled()) M5.Rtc.setDateTime(&normalized);
  configured_ = true;
  save();
  return true;
}

void DateTimeService::setTimezone(uint8_t index) {
  timezoneIndex_ = min<uint8_t>(index, kTimezoneCount - 1);
  applyTimezone();
}

void DateTimeService::setDstAuto(bool enabled) {
  dstAuto_ = enabled;
  applyTimezone();
}

void DateTimeService::reset() {
  timezoneIndex_ = 1;
  dstAuto_ = true;
  applyTimezone();
  setLocalDateTime(2026, 1, 1, 0, 0);
  save();
}

void DateTimeService::save() {
  preferences.putUChar("tz", timezoneIndex_);
  preferences.putBool("dst", dstAuto_);
  preferences.putULong("epoch", static_cast<uint32_t>(time(nullptr)));
}

String DateTimeService::localDateTime() const {
  tm local{};
  const time_t now = time(nullptr);
  localtime_r(&now, &local);
  return String(local.tm_year + 1900) + "-" + twoDigits(local.tm_mon + 1) +
         "-" + twoDigits(local.tm_mday) + " " + twoDigits(local.tm_hour) +
         ":" + twoDigits(local.tm_min);
}

String DateTimeService::statusDateTime() const {
  static const char* const months[] = {"jan", "feb", "mar", "apr", "may",
                                       "jun", "jul", "aug", "sep", "oct",
                                       "nov", "dec"};
  tm local{};
  const time_t now = time(nullptr);
  localtime_r(&now, &local);
  return twoDigits(local.tm_hour) + ":" + twoDigits(local.tm_min) +
         "   " + twoDigits(local.tm_mday) + "/" +
         months[constrain(local.tm_mon, 0, 11)] + "/" +
         String(local.tm_year + 1900);
}

String DateTimeService::localTime() const {
  tm local{};
  const time_t now = time(nullptr);
  localtime_r(&now, &local);
  return twoDigits(local.tm_hour) + ":" + twoDigits(local.tm_min);
}

String DateTimeService::timezoneLabel() const {
  return kTimezones[timezoneIndex_].label;
}

String DateTimeService::timezoneLabel(uint8_t index) const {
  return kTimezones[min<uint8_t>(index, kTimezoneCount - 1)].label;
}

const char* DateTimeService::timezoneRule() const {
  const TimezoneInfo& zone = kTimezones[timezoneIndex_];
  return dstAuto_ ? zone.daylight : zone.standard;
}

void FireOS::begin() {
  activeFireOs = this;
  Serial.begin(115200);
  auto config = M5.config();
  config.output_power = true;
  config.internal_imu = true;
  config.internal_rtc = true;
  config.internal_spk = true;
  // M5Unified's official FIRE profile owns the analog mic through I2S ADC DMA;
  // it is started lazily by the capture service after the speaker is stopped.
  config.internal_mic = false;
  config.led_brightness = 80;
  M5.begin(config);
  Serial.println("FIRE boot: M5.begin OK");
  auto micConfig = M5.Mic.config();
  micConfig.pin_data_in = GPIO_NUM_34;
  micConfig.use_adc = true;
  micConfig.i2s_port = I2S_NUM_0;
  // Match M5Unified's documented M5Stack/FIRE analog-mic profile. Four ADC
  // samples are averaged into each 16 kHz output sample. Keep the filter off
  // here: the audio is sent to speech recognition and should retain the
  // consonant/high-frequency detail needed for intelligible speech.
  micConfig.over_sampling = 4;
  micConfig.magnification = 16;
  micConfig.noise_filter_level = 0;
  M5.Mic.config(micConfig);
  firePreferences = new Preferences();
  fireWifiSetupServer = new WebServer(80);
#ifdef FIRE_OS_BLE
  bluetoothPeripheralAddressPtr = new String();
#endif
  uiCanvas = new M5Canvas(&M5.Display);
  if (!uiCanvas) {
    Serial.println("FIRE boot: canvas allocation failed");
    return;
  }
  backendClient_ = new FireBackendClient();
  firmwareStorage_ = new FireFirmwareStorage();
  githubFirmware_ = new FireGithubFirmwareManager();
  luaRuntime_ = new FireLuaRuntime();
  packageManager_ = new FireLuaPackageManager();
  configureFireRgbStrip();
  Serial.println("FIRE boot: RGB OK");
  initSdCard();
  Serial.println("FIRE boot: SD OK");

  pinMode(kButtonPins[0], INPUT);
  pinMode(kButtonPins[1], INPUT);
  pinMode(kButtonPins[2], INPUT);

  delay(100);
  safeMode_ = allButtonsHeldAtBoot();
  Serial.println("FIRE boot: buttons OK");
  dateTime_.begin();
  Serial.println("FIRE boot: DateTime OK");
  loadSettings();
  Serial.println("FIRE boot: settings OK");
  if (handlePendingFirmwareBoot()) return;
  if (backendClient_) {
    backendClient_->setReverseTransport(&reverseTransport_);
    backendClient_->setCallbacks(this, backendMessage, backendState);
    backendClient_->configure(backendHost_, backendPort_, backendToken_,
                              backendDeviceId_, kFirmwareVersion);
    backendStatus_ = backendClient_->status();
  }
  reverseTransport_.configure(backendDeviceId_, backendToken_);
  if (firmwareStorage_) {
    firmwareStorage_->setReverseTransport(&reverseTransport_);
    firmwareStorage_->setCallbacks(this, firmwareStatus, firmwareResult);
  }
  if (githubFirmware_)
    githubFirmware_->setCallbacks(this, githubFirmwareStatus,
                                  githubFirmwareResult);
  packageManager_->setReverseTransport(&reverseTransport_);
  packageManager_->setCallbacks(this, packageStatus, packageResult);
  if (mainIndex_ < kSystemMainCount && !mainVisible_[mainIndex_])
    mainIndex_ = mainItemAtPosition(0);
  const esp_partition_t* runningPartition = esp_ota_get_running_partition();
  const bool runningFactory = runningPartition &&
                              runningPartition->subtype ==
                                  ESP_PARTITION_SUBTYPE_APP_FACTORY;
  const bool bootAttemptPending = preferences.getBool("boot_pending", false);
  if (safeMode_ || bootAttemptPending) {
    // Safe boot and a failed previous external-app attempt both return to
    // FIRE OS. The pending marker prevents a crashing .bin from trapping the
    // device in an endless boot loop.
    selectedBootAppPath_ = "";
    preferences.putBool("boot_pending", false);
    saveSettings();
  } else if (!safeMode_ && runningFactory &&
             selectedBootAppPath_.length() > 0) {
    preferences.putBool("boot_pending", true);
    saveSettings();
    // External .bin boot returns after selecting the OTA partition and
    // rebooting. Lua boot apps stay in this firmware and must continue the
    // normal display/audio/backend initialization below.
    if (launchSelectedBootApp() && screen_ != Screen::LuaApp) return;
    preferences.putBool("boot_pending", false);
    selectedBootAppPath_ = "";
    saveSettings();
  }
  // Do not let optional BLE initialization block the first FIRE OS frame.
  // The UI, audio and recovery path must be usable even if the radio stack
  // is damaged or unavailable after an external firmware attempt.
  bluetoothEnabled_ = false;
  bluetoothBootInitPending_ = false;
  if (wifiMode_ == 1) {
    wifiEnabled_ = true;
    WiFi.setHostname("M5Stack-FIRE");
    WiFi.mode(WIFI_STA);
    if (wifiSsid_.length() > 0) beginWifiConnection();
  }
  if (wifiTimeSync_) {
    startTimeSync();
  }

  M5.Display.setRotation(0);
  M5.Display.setBrightness(brightness_);
  M5.Speaker.setVolume(speakerVolumeValue(volume_));
  M5.Speaker.setBufferReleaseCallback(this, luaSpeakerBufferReleaseCallback);
  // Keep boot non-blocking. The previous synchronous LED animation could
  // stall before the first FIRE OS frame on some M5Unified/RMT combinations.
  // Boot feedback is handled after the UI is alive.
  ui.setColorDepth(16);
  ui.createSprite(320, 240);
  lastActivity_ = millis();
  bootFeedbackActive_ = bootRgbPulse_ || bootMelody_;
  bootFeedbackStarted_ = millis();
  bootFeedbackLastFrame_ = 0;
  bootMelodyStarted_ = false;

  if (safeMode_) {
    Serial.println("FIRE OS safe mode: all three buttons held at boot");
  } else {
    Serial.println("FIRE OS started");
  }
  draw();
}

void FireOS::update() {
  M5.update();
#ifdef FIRE_OS_BLE
  bool bluetoothUpdate = false;
  bool bluetoothConnectedSnapshot = false;
  uint8_t bluetoothTypeSnapshot = 0;
  char bluetoothAddressSnapshot[32] = {};
  portENTER_CRITICAL(&bluetoothStateMux);
  if (bluetoothPendingUpdate) {
    bluetoothUpdate = true;
    bluetoothConnectedSnapshot = bluetoothPendingConnected;
    bluetoothTypeSnapshot = bluetoothPendingAddressType;
    strncpy(bluetoothAddressSnapshot, bluetoothPendingAddress,
            sizeof(bluetoothAddressSnapshot) - 1);
    bluetoothPendingUpdate = false;
  }
  portEXIT_CRITICAL(&bluetoothStateMux);
  if (bluetoothUpdate) {
    bluetoothPeripheralAddress = bluetoothConnectedSnapshot
                                     ? String(bluetoothAddressSnapshot)
                                     : String();
    bluetoothPeripheralAddressType = bluetoothTypeSnapshot;
  }
#endif
  updateBootFeedback();
  updateFirmwareBootGuard();
  if (screen_ == Screen::AiDeveloper &&
      (!backendClient_ || !backendClient_->configured()))
    updateAiDeveloperMock();
#ifdef FIRE_OS_BLE
  if (bluetoothPeripheralConnected && bluetoothPeripheralAddress.length() > 0) {
    bool saved = false;
    for (uint8_t index = 0; index < bluetoothSavedCount_; ++index) {
      if (bluetoothSavedAddresses_[index] == bluetoothPeripheralAddress) {
        saved = true;
        break;
      }
    }
    if (!saved) {
      const uint8_t index = bluetoothSavedCount_ < kMaxBluetoothSavedDevices
                                ? bluetoothSavedCount_++
                                : kMaxBluetoothSavedDevices - 1;
      bluetoothSavedNames_[index] = bluetoothPeripheralAddress;
      bluetoothSavedAddresses_[index] = bluetoothPeripheralAddress;
      bluetoothSavedAddressTypes_[index] = bluetoothPeripheralAddressType;
      bluetoothSavedName_ = bluetoothPeripheralAddress;
      bluetoothSavedAddress_ = bluetoothPeripheralAddress;
      saveSettings();
    }
  }
#endif
  pollButtons();
  // Render the result of a button event before optional background work.
  if (redrawRequested_) draw();
  if (appScanPending_) {
    appScanPending_ = false;
    if (screen_ == Screen::Apps || screen_ == Screen::AppsSettings) {
      scanExternalApps();
      if (screen_ == Screen::AppsSettings) rebuildAppManagerItems();
      redrawRequested_ = true;
    }
  }
  if (fileExplorerScanPending_) {
    fileExplorerScanPending_ = false;
    if (screen_ == Screen::FileExplorer) {
      initSdCard();
      refreshSdDirectory();
      redrawRequested_ = true;
    }
  }
  if (firmwareScanPending_) {
    firmwareScanPending_ = false;
    if (screen_ == Screen::Firmware) {
      scanFirmwareFiles();
      redrawRequested_ = true;
    }
  }
  if (firmwareInstallPending_) {
    firmwareInstallPending_ = false;
    String path;
    if (firmwareSelection_ < firmwareCount_)
      path = firmwarePaths_[firmwareSelection_];
    if (path.length() == 0 || !installFirmwareFile(path)) redrawRequested_ = true;
  }
  if (wifiSetupActive_) wifiSetupServer.handleClient();
  updateWifiState();
  updateBluetoothScan();
  serviceLuaHardwareJobs();
  updateDebugTests();
  reverseTransport_.service(WiFi.status() == WL_CONNECTED &&
                            backendClient_ && backendClient_->configured());
  updateBackend();
  updateAiAudio();
  updateAiAudioOutput();
  if (packageManager_) packageManager_->service(WiFi.status() == WL_CONNECTED);
  if (firmwareStorage_)
    firmwareStorage_->service(WiFi.status() == WL_CONNECTED, sdReady_);
  if (githubFirmware_)
    githubFirmware_->service(WiFi.status() == WL_CONNECTED, sdReady_);
  updateTimeSync();
  manageDisplayPower();
  if (carouselAnimating_) {
    const uint32_t now = millis();
    const uint32_t elapsed = now - carouselLastStepAt_;
    // Keep the same visual speed when the input loop runs faster than before.
    // 48 px per 25 ms was the previous animation rate.
    const int16_t step = static_cast<int16_t>(max<uint32_t>(1, elapsed * 48 / 25));
    if (elapsed > 0) carouselLastStepAt_ = now;
    carouselOffset_ += step;
    if (carouselOffset_ >= kCarouselDistance) {
      carouselOffset_ = kCarouselDistance;
      carouselAnimating_ = false;
      if (carouselQueuedDirection_ != 0) {
        const int8_t queuedDirection = carouselQueuedDirection_;
        carouselQueuedDirection_ = 0;
        startMainSlide(nextVisibleMain(mainIndex_, queuedDirection),
                       queuedDirection);
      }
    }
  }
  const bool animatedScreen = screen_ == Screen::AiDeveloper ||
                              screen_ == Screen::LuaApp ||
                              carouselAnimating_;
  const uint32_t drawInterval = screen_ == Screen::AiDeveloper
                                    ? 33
                                    : animatedScreen ? 25 : 50;
  if (redrawRequested_ || millis() - lastDrawAt_ >= drawInterval) draw();
  // Initialize BLE after the first Bluetooth settings frame is visible. BLE
  // setup can take a noticeable amount of time and must not delay the menu
  // transition itself.
  if (bluetoothBootInitPending_ && screen_ == Screen::Bluetooth) {
    bluetoothBootInitPending_ = false;
    bluetoothEnabled_ = initBluetooth();
    setBluetoothVisibility(bluetoothEnabled_);
    redrawRequested_ = true;
  }
  // Keep button sampling responsive while still yielding to Wi-Fi/BLE tasks.
  delay(5);
}

void FireOS::updateBootFeedback() {
  if (!bootFeedbackActive_) return;
  const uint32_t elapsed = millis() - bootFeedbackStarted_;
  constexpr uint32_t kDurationMs = 2400;
  if (elapsed >= kDurationMs) {
    // Keep the startup melody at the pre-volume-scaling level. Speech uses
    // the full M5Unified 0..255 range, but the existing boot sound level was
    // intentionally softer and should not change with that correction.
    if (bootMelodyStarted_) {
      M5.Speaker.setVolume(speakerVolumeValue(volume_));
    }
    if (bootRgbPulse_) {
#ifdef FIRE_OS_BLE
      writeFireRgbRaw(0, 0, 0, 0);
#else
      M5.Led.setBrightness(0);
      M5.Led.setAllColor(0, 0, 0);
      M5.Led.display();
#endif
    }
    bootFeedbackActive_ = false;
    return;
  }

  if (bootMelody_ && M5.Speaker.isEnabled()) {
    if (!bootMelodyStarted_) {
      prepareBootMelody();
      M5.Speaker.setVolume(volume_);
      bootMelodyStarted_ = M5.Speaker.playRaw(
          kBootMelodyPcm, kBootMelodySampleCount, kBootMelodySampleRate,
          false, 1, 0, true);
    }
  }

  if (bootRgbPulse_ && elapsed - bootFeedbackLastFrame_ >= 45) {
    bootFeedbackLastFrame_ = elapsed;
    static const uint8_t colors[][3] = {
        {255, 0, 0}, {0, 90, 255}, {0, 255, 40}, {255, 80, 0}};
    const uint32_t colorElapsed = elapsed % 600;
    const uint8_t color = (elapsed / 600) % 4;
    const uint8_t brightness = colorElapsed < 300
                                   ? static_cast<uint8_t>(colorElapsed * 255 / 300)
                                   : static_cast<uint8_t>((600 - colorElapsed) *
                                                          255 / 300);
#ifdef FIRE_OS_BLE
    writeFireRgbRaw(colors[color][0], colors[color][1], colors[color][2],
                    brightness);
#else
    M5.Led.setBrightness(brightness);
    M5.Led.setAllColor(colors[color][0], colors[color][1], colors[color][2]);
    M5.Led.display();
#endif
  }
}

void FireOS::updateAiDeveloperMock() {
  const uint32_t elapsed = millis() - aiWorkflowStarted_;
  if (aiWorkflowState_ == 2 && elapsed >= 1300) {
    aiWorkflowState_ = 3;
    aiDeveloperMode_ = 2;
    aiWorkflowStarted_ = millis();
  } else if (aiWorkflowState_ == 4) {
    aiBuildProgress_ = min<uint8_t>(100, elapsed / 55);
    if (aiBuildProgress_ >= 100) {
      aiWorkflowState_ = 5;
      aiDeveloperMode_ = 3;
      aiWorkflowStarted_ = millis();
    }
  } else if (aiWorkflowState_ == 6 && elapsed >= 2200) {
    aiWorkflowState_ = 5;
    aiDeveloperMode_ = 3;
    aiWorkflowStarted_ = millis();
  }
}

void FireOS::loadSettings() {
  const uint8_t storedBrightness = preferences.getUChar("brightness", 180);
  const uint8_t storedVolume = preferences.getUChar("volume", 90);
  brightnessStep_ = min<uint8_t>(preferences.getUChar("brightness_step",
                                                       nearestBrightnessStep(storedBrightness)),
                                 kBrightnessStepCount - 1);
  volumeStep_ = min<uint8_t>(preferences.getUChar("volume_step",
                                                   nearestVolumeStep(storedVolume)),
                            kVolumeStepCount - 1);
  brightness_ = kBrightnessValues[brightnessStep_];
  volume_ = volumeValue(volumeStep_);
  const bool legacyWifi = preferences.getBool("wifi", false);
  wifiMode_ = preferences.isKey("wifi_mode")
                  ? min<uint8_t>(preferences.getUChar("wifi_mode", 0), 2)
                  : (legacyWifi ? 1 : 0);
  wifiTimeSync_ = preferences.getBool("wifi_time_sync", false);
  timeSyncLast_ = preferences.getString("wifi_time_last", "");
  wifiEnabled_ = false;
  wifiSsid_ = preferences.getString("wifi_ssid", "");
  wifiPassword_ = preferences.getString("wifi_pass", "");
  // OpenAI credentials belong exclusively on the PC backend. Remove any key
  // written by older firmware versions during settings migration.
  aiApiKey_ = "";
  if (preferences.isKey("openai_key")) preferences.remove("openai_key");
  backendHost_ = preferences.getString("backend_host", "");
  backendPort_ = preferences.getUShort("backend_port", 8765);
  backendToken_ = preferences.getString("backend_token", "");
  backendDeviceId_ = preferences.getString("backend_device", "m5stack-fire-01");
  pendingDiagnosticAppId_ = preferences.isKey("diag_app")
                                ? preferences.getString("diag_app", "")
                                : String();
  pendingDiagnosticPackageId_ = preferences.isKey("diag_pkg")
                                    ? preferences.getString("diag_pkg", "")
                                    : String();
  pendingDiagnosticErrorCode_ = preferences.isKey("diag_code")
                                    ? preferences.getString("diag_code", "")
                                    : String();
  pendingDiagnosticMessage_ = preferences.isKey("diag_msg")
                                  ? preferences.getString("diag_msg", "")
                                  : String();
  pendingDiagnosticJson_ = preferences.isKey("diag_meta")
                               ? preferences.getString("diag_meta", "")
                               : String();
  loadSavedWifiNetworks();
  bluetoothEnabled_ = false;
  bluetoothMode_ = 0;
  bluetoothMode_ = min<uint8_t>(preferences.getUChar("bt_mode", 0), 2);
  bluetoothSavedName_ = preferences.getString("bt_saved_name", "");
  bluetoothSavedAddress_ = preferences.getString("bt_saved_addr", "");
  loadSavedBluetoothDevices();
  buttonSoundsEnabled_ = preferences.getBool("button_sounds", true);
  bootRgbPulse_ = preferences.getBool("boot_rgb", true);
  bootMelody_ = preferences.getBool("boot_melody", true);
  selectedBootAppPath_ = preferences.getString("boot_app", "");
  mainVisible_[0] = preferences.getBool("menu_apps", true);
  mainVisible_[1] = preferences.getBool("menu_settings", true);
  mainVisible_[2] = preferences.getBool("menu_power", true);
  mainVisible_[3] = preferences.getBool("menu_files", true);
  mainVisible_[4] = preferences.getBool("menu_ai", true);
  if (!mainVisible_[0] && !mainVisible_[1] && !mainVisible_[2] &&
      !mainVisible_[3] && !mainVisible_[4]) {
    mainVisible_[1] = true;
  }
  const bool durationV2 = preferences.getBool("duration_v2", false);
  if (durationV2) {
    sleepOption_ = min<uint8_t>(preferences.getUChar("sleep", 0),
                                kDurationCount - 1);
    dimOption_ = min<uint8_t>(preferences.getUChar("dim", 5),
                              kDurationCount - 1);
    screenOffOption_ = min<uint8_t>(preferences.getUChar("screenoff", 10),
                                    kDurationCount - 1);
  } else {
    // Convert the previous 0/1/5/10/15/30/60-minute index format once.
    const uint8_t legacyMinutes[] = {0, 1, 5, 10, 15, 20, 20};
    sleepOption_ = legacyMinutes[min<uint8_t>(preferences.getUChar("sleep", 0), 6)];
    dimOption_ = legacyMinutes[min<uint8_t>(preferences.getUChar("dim", 2), 6)];
    screenOffOption_ = legacyMinutes[min<uint8_t>(preferences.getUChar("screenoff", 3), 6)];
    preferences.putBool("duration_v2", true);
  }
  for (uint8_t index = 0; index < kButtonCount; ++index) {
    doubleClickAction_[index] = min<uint8_t>(
        preferences.getUChar(("dbl_" + String(index)).c_str(), 0),
        kDoubleClickActionCount - 1);
    doubleClickLuaAppId_[index] =
        preferences.getString(("dbl_app_" + String(index)).c_str(), "");
  }
  WiFi.setHostname("M5Stack-FIRE");
  if (wifiMode_ != 1) WiFi.mode(WIFI_OFF);
}

void FireOS::saveSettings() {
  preferences.putUChar("brightness", brightness_);
  preferences.putUChar("volume", volume_);
  preferences.putUChar("brightness_step", brightnessStep_);
  preferences.putUChar("volume_step", volumeStep_);
  preferences.putBool("wifi", wifiEnabled_);
  preferences.putUChar("wifi_mode", wifiMode_);
  preferences.putBool("wifi_time_sync", wifiTimeSync_);
  preferences.putString("wifi_time_last", timeSyncLast_);
  preferences.putString("wifi_ssid", wifiSsid_);
  preferences.putString("wifi_pass", wifiPassword_);
  preferences.putString("backend_host", backendHost_);
  preferences.putUShort("backend_port", backendPort_);
  preferences.putString("backend_token", backendToken_);
  preferences.putString("backend_device", backendDeviceId_);
  saveSavedWifiNetworks();
  preferences.putBool("bluetooth", bluetoothEnabled_);
  preferences.putUChar("bt_mode", bluetoothMode_);
  preferences.putString("bt_saved_name", bluetoothSavedName_);
  preferences.putString("bt_saved_addr", bluetoothSavedAddress_);
  saveSavedBluetoothDevices();
  preferences.putBool("button_sounds", buttonSoundsEnabled_);
  preferences.putBool("boot_rgb", bootRgbPulse_);
  preferences.putBool("boot_melody", bootMelody_);
  preferences.putString("boot_app", selectedBootAppPath_);
  preferences.putBool("menu_apps", mainVisible_[0]);
  preferences.putBool("menu_settings", mainVisible_[1]);
  preferences.putBool("menu_power", mainVisible_[2]);
  preferences.putBool("menu_files", mainVisible_[3]);
  preferences.putBool("menu_ai", mainVisible_[4]);
  preferences.putUChar("sleep", sleepOption_);
  preferences.putUChar("dim", dimOption_);
  preferences.putUChar("screenoff", screenOffOption_);
  preferences.putBool("duration_v2", true);
  for (uint8_t index = 0; index < kButtonCount; ++index) {
    preferences.putUChar(("dbl_" + String(index)).c_str(), doubleClickAction_[index]);
    preferences.putString(("dbl_app_" + String(index)).c_str(),
                          doubleClickLuaAppId_[index]);
  }
  saveLuaAppSelections();
}

void FireOS::loadSavedWifiNetworks() {
  wifiSavedCount_ = 0;
  for (uint8_t index = 0; index < 5; ++index) {
    const String ssid = preferences.getString(("wifi_ssid_" + String(index)).c_str(), "");
    if (ssid.length() == 0) continue;
    wifiSavedSsid_[wifiSavedCount_] = ssid;
    wifiSavedPassword_[wifiSavedCount_] =
        preferences.getString(("wifi_pass_" + String(index)).c_str(), "");
    ++wifiSavedCount_;
  }
  if (wifiSavedCount_ == 0 && wifiSsid_.length() > 0) {
    wifiSavedSsid_[0] = wifiSsid_;
    wifiSavedPassword_[0] = wifiPassword_;
    wifiSavedCount_ = 1;
  }
  if (wifiSavedCount_ > 0) {
    wifiSsid_ = wifiSavedSsid_[0];
    wifiPassword_ = wifiSavedPassword_[0];
  }
}

void FireOS::loadSavedBluetoothDevices() {
  bluetoothSavedCount_ = min<uint8_t>(
      preferences.getUChar("bt_saved_count", 0), kMaxBluetoothSavedDevices);
  for (uint8_t index = 0; index < kMaxBluetoothSavedDevices; ++index) {
    bluetoothSavedNames_[index] = preferences.getString(
        ("bt_name_" + String(index)).c_str(), "");
    bluetoothSavedAddresses_[index] = preferences.getString(
        ("bt_addr_" + String(index)).c_str(), "");
    bluetoothSavedAddressTypes_[index] = preferences.getUChar(
        ("bt_type_" + String(index)).c_str(), 0);
  }
  if (bluetoothSavedCount_ == 0 && bluetoothSavedAddress_.length() > 0) {
    bluetoothSavedCount_ = 1;
    bluetoothSavedNames_[0] = bluetoothSavedName_;
    bluetoothSavedAddresses_[0] = bluetoothSavedAddress_;
  }
}

void FireOS::saveSavedBluetoothDevices() {
  preferences.putUChar("bt_saved_count", bluetoothSavedCount_);
  for (uint8_t index = 0; index < kMaxBluetoothSavedDevices; ++index) {
    preferences.putString(("bt_name_" + String(index)).c_str(),
                          bluetoothSavedNames_[index]);
    preferences.putString(("bt_addr_" + String(index)).c_str(),
                          bluetoothSavedAddresses_[index]);
    preferences.putUChar(("bt_type_" + String(index)).c_str(),
                         bluetoothSavedAddressTypes_[index]);
  }
}

bool FireOS::initSdCard() {
  sdLastProbe_ = millis();
  // SD.begin() initializes the default VSPI bus (18/19/23 on FIRE).
  sdReady_ = SD.begin(kSdCsPin);
  if (!sdReady_) sdMessage_ = "SD card not detected";
  return sdReady_;
}

void FireOS::scanFirmwareFiles() {
  firmwareCount_ = 0;
  if (!sdReady_ && !initSdCard()) {
    firmwareMessage_ = "SD card not detected";
    firmwareSelection_ = 0;
    firmwareOffset_ = 0;
    return;
  }
  File directory = SD.open("/firmware");
  if (!directory || !directory.isDirectory()) {
    if (directory) directory.close();
    firmwareMessage_ = "No /firmware folder yet";
    firmwareSelection_ = 0;
    firmwareOffset_ = 0;
    return;
  }
  File entry = directory.openNextFile();
  while (entry && firmwareCount_ < kMaxFirmwareFiles) {
    if (!entry.isDirectory()) {
      String rawName = entry.name();
      while (rawName.endsWith("/") && rawName.length() > 1)
        rawName.remove(rawName.length() - 1);
      String name = sdBaseName(rawName);
      String lower = name;
      lower.toLowerCase();
      if (lower.endsWith(".bin") && !lower.endsWith(".part")) {
        const uint8_t index = firmwareCount_++;
        firmwareNames_[index] = name;
        firmwarePaths_[index] = "/firmware/" + name;
        firmwareSizes_[index] = entry.size();
      }
    }
    entry.close();
    entry = directory.openNextFile();
  }
  directory.close();
  for (uint8_t i = 0; i < firmwareCount_; ++i) {
    for (uint8_t j = i + 1; j < firmwareCount_; ++j) {
      if (firmwareNames_[j].compareTo(firmwareNames_[i]) >= 0) continue;
      String name = firmwareNames_[i];
      firmwareNames_[i] = firmwareNames_[j];
      firmwareNames_[j] = name;
      String path = firmwarePaths_[i];
      firmwarePaths_[i] = firmwarePaths_[j];
      firmwarePaths_[j] = path;
      const uint32_t size = firmwareSizes_[i];
      firmwareSizes_[i] = firmwareSizes_[j];
      firmwareSizes_[j] = size;
    }
  }
  const uint8_t itemCount = firmwareCount_ + 3;  // Refresh + GitHub + Back.
  if (firmwareSelection_ >= itemCount) firmwareSelection_ = itemCount - 1;
  if (firmwareSelection_ < firmwareOffset_) firmwareOffset_ = firmwareSelection_;
  if (firmwareSelection_ >= firmwareOffset_ + 5)
    firmwareOffset_ = firmwareSelection_ - 4;
  if (firmwareCount_ > 0)
    firmwareMessage_ = String(firmwareCount_) + " firmware file" +
                       (firmwareCount_ == 1 ? "" : "s") + " on SD";
  else
    firmwareMessage_ = "No firmware files on SD";
}

bool FireOS::handlePendingFirmwareBoot() {
  if (!preferences.getBool("fw_pending", false)) return false;
  if (safeMode_) {
    preferences.putBool("fw_pending", false);
    preferences.remove("fw_attempts");
    preferences.remove("fw_target");
    saveSettings();
    return false;
  }

  const esp_partition_t* running = esp_ota_get_running_partition();
  const String target = preferences.getString("fw_target", "");
  if (!running || target.length() == 0 || target != running->label) {
    // A normal USB flash or an unrelated boot invalidates the pending marker.
    preferences.putBool("fw_pending", false);
    preferences.remove("fw_attempts");
    preferences.remove("fw_target");
    saveSettings();
    return false;
  }

  const uint8_t attempts = preferences.getUChar("fw_attempts", 0);
  if (attempts >= 1) {
    const esp_partition_t* previous =
        esp_ota_get_next_update_partition(nullptr);
    if (previous && previous != running &&
        esp_ota_set_boot_partition(previous) == ESP_OK) {
      preferences.putBool("fw_pending", false);
      preferences.remove("fw_attempts");
      preferences.remove("fw_target");
      saveSettings();
      Serial.println("FIRE firmware boot guard: reverting to previous slot");
      delay(250);
      ESP.restart();
      return true;
    }
    // Do not trap the device in a rollback loop if the partition table cannot
    // provide a previous slot. Continue with the image and clear the marker.
    preferences.putBool("fw_pending", false);
    preferences.remove("fw_attempts");
    preferences.remove("fw_target");
    saveSettings();
    return false;
  }

  preferences.putUChar("fw_attempts", 1);
  saveSettings();
  firmwareBootGuardActive_ = true;
  firmwareBootGuardStarted_ = millis();
  Serial.println("FIRE firmware boot guard: validation window started");
  return false;
}

void FireOS::updateFirmwareBootGuard() {
  if (!firmwareBootGuardActive_ ||
      millis() - firmwareBootGuardStarted_ < kFirmwareBootGuardMs)
    return;
  preferences.putBool("fw_pending", false);
  preferences.remove("fw_attempts");
  preferences.remove("fw_target");
  saveSettings();
  firmwareBootGuardActive_ = false;
  Serial.println("FIRE firmware boot guard: image accepted");
}

bool FireOS::installFirmwareFile(const String& path) {
  if (!sdReady_ && !initSdCard()) {
    firmwareMessage_ = "SD card not detected";
    return false;
  }
  if (!path.startsWith("/firmware/") || path.indexOf("..") >= 0 ||
      path.indexOf('\\') >= 0 || path.length() > 80 ||
      (firmwareStorage_ && firmwareStorage_->busy())) {
    firmwareMessage_ = "Firmware install unavailable";
    return false;
  }

  const esp_partition_t* target = esp_ota_get_next_update_partition(nullptr);
  File source = SD.open(path, FILE_READ);
  uint32_t imageOffset = 0;
  uint32_t imageSize = 0;
  const bool validImage = source &&
                          inspectExternalImage(source, imageOffset, imageSize,
                                               true);
  if (!source || !target || !validImage || imageSize > target->size) {
    source.close();
    firmwareMessage_ = !target ? "No OTA slot available"
                               : validImage ? "Firmware is too large"
                                            : "Invalid FIRE firmware image";
    return false;
  }
  if (!source.seek(imageOffset)) {
    source.close();
    firmwareMessage_ = "Cannot read firmware image";
    return false;
  }

  esp_ota_handle_t handle = 0;
  if (esp_ota_begin(target, imageSize, &handle) != ESP_OK) {
    source.close();
    firmwareMessage_ = "OTA install could not start";
    return false;
  }
  uint8_t buffer[4096];
  uint32_t remaining = imageSize;
  bool ok = true;
  while (remaining > 0) {
    const size_t request = min<size_t>(sizeof(buffer), remaining);
    const size_t amount = source.read(buffer, request);
    if (amount == 0 || esp_ota_write(handle, buffer, amount) != ESP_OK) {
      ok = false;
      break;
    }
    remaining -= amount;
    if ((remaining & 0xFFFFU) == 0) {
      firmwareMessage_ = "Flashing " +
                         String((imageSize - remaining) * 100UL / imageSize) +
                         "%";
      redrawRequested_ = true;
      delay(1);
    }
  }
  source.close();
  if (!ok) {
    esp_ota_abort(handle);
    firmwareMessage_ = "Flash failed; current OS retained";
    return false;
  }
  if (esp_ota_end(handle) != ESP_OK || remaining != 0) {
    firmwareMessage_ = "Firmware verification failed";
    return false;
  }
  if (esp_ota_set_boot_partition(target) != ESP_OK) {
    firmwareMessage_ = "Could not select new firmware";
    return false;
  }

  preferences.putBool("fw_pending", true);
  preferences.putUChar("fw_attempts", 0);
  preferences.putString("fw_target", target->label);
  saveSettings();
  firmwareMessage_ = "Firmware installed; restarting";
  delay(350);
  ESP.restart();
  return true;
}

String FireOS::sdParentPath(const String& path) const {
  if (path == "/" || path.length() == 0) return "/";
  const int slash = path.lastIndexOf('/');
  if (slash <= 0) return "/";
  return path.substring(0, slash);
}

String FireOS::sdJoinPath(const String& base, const String& name) const {
  if (base == "/" || base.length() == 0) return "/" + name;
  return base + "/" + name;
}

String FireOS::sdBaseName(const String& path) const {
  const int slash = path.lastIndexOf('/');
  return slash >= 0 ? path.substring(slash + 1) : path;
}

String FireOS::sdStorageLabel() const {
  if (!sdReady_) return "SD: not present";
  const uint32_t total = static_cast<uint32_t>(SD.totalBytes());
  const uint32_t used = static_cast<uint32_t>(SD.usedBytes());
  const uint32_t free = total > used ? total - used : 0;
  return "Free " + formatBytes(free) + " / " + formatBytes(total);
}

bool FireOS::sdIsTextFile(const String& name) const {
  String lower = name;
  lower.toLowerCase();
  return lower.endsWith(".txt") || lower.endsWith(".log") ||
         lower.endsWith(".csv") || lower.endsWith(".json") ||
         lower.endsWith(".ini") || lower.endsWith(".md") ||
         lower.endsWith(".xml") || lower.endsWith(".cpp") ||
         lower.endsWith(".h");
}

bool FireOS::sdIsImageFile(const String& name) const {
  String lower = name;
  lower.toLowerCase();
  return lower.endsWith(".jpg") || lower.endsWith(".jpeg") ||
         lower.endsWith(".png") || lower.endsWith(".bmp");
}

void FireOS::refreshSdDirectory() {
  if (!sdReady_ && !initSdCard()) return;
  File directory = SD.open(sdPath_);
  if (!directory || !directory.isDirectory()) {
    sdMessage_ = "Cannot open folder";
    sdPath_ = "/";
    return;
  }
  sdEntryCount_ = 0;
  File entry = directory.openNextFile();
  while (entry && sdEntryCount_ < kMaxFileEntries) {
    const uint8_t index = sdEntryCount_++;
    String rawName = entry.name();
    while (rawName.endsWith("/") && rawName.length() > 1) {
      rawName.remove(rawName.length() - 1);
    }
    const String entryName = sdBaseName(rawName);
    // Normalize the path against the currently open directory. Some Arduino
    // SD/FAT implementations return only a basename from File::name().
    sdEntryNames_[index] = entryName;
    sdEntryPaths_[index] = sdJoinPath(sdPath_, entryName);
    sdEntrySizes_[index] = entry.isDirectory() ? 0 : entry.size();
    sdEntryDirectories_[index] = entry.isDirectory();
    entry.close();
    entry = directory.openNextFile();
  }
  directory.close();
  for (uint8_t i = 0; i < sdEntryCount_; ++i) {
    for (uint8_t j = i + 1; j < sdEntryCount_; ++j) {
      bool swap = false;
      if (sdSortMode_ == 0) {
        swap = sdEntryNames_[j].compareTo(sdEntryNames_[i]) < 0;
      } else {
        swap = sdEntrySizes_[j] < sdEntrySizes_[i];
      }
      if (swap) {
        const String name = sdEntryNames_[i];
        sdEntryNames_[i] = sdEntryNames_[j];
        sdEntryNames_[j] = name;
        const String path = sdEntryPaths_[i];
        sdEntryPaths_[i] = sdEntryPaths_[j];
        sdEntryPaths_[j] = path;
        const uint32_t size = sdEntrySizes_[i];
        sdEntrySizes_[i] = sdEntrySizes_[j];
        sdEntrySizes_[j] = size;
        const bool dir = sdEntryDirectories_[i];
        sdEntryDirectories_[i] = sdEntryDirectories_[j];
        sdEntryDirectories_[j] = dir;
      }
    }
  }
  const uint8_t itemCount = sdEntryCount_ + 1;
  if (sdSelection_ >= itemCount) sdSelection_ = itemCount - 1;
  if (sdSelection_ < sdOffset_) sdOffset_ = sdSelection_;
  if (sdSelection_ >= sdOffset_ + kFileVisibleRows) {
    sdOffset_ = sdSelection_ - kFileVisibleRows + 1;
  }
}

void FireOS::openSelectedSdEntry() {
  if (sdSelection_ >= sdEntryCount_) {
    if (sdPath_ == "/") {
      back();
    } else {
      sdPath_ = sdParentPath(sdPath_);
      sdSelection_ = 0;
      sdOffset_ = 0;
      refreshSdDirectory();
    }
    return;
  }
  if (sdEntryDirectories_[sdSelection_]) {
    sdPath_ = sdEntryPaths_[sdSelection_];
    sdSelection_ = 0;
    sdOffset_ = 0;
    refreshSdDirectory();
  } else if (sdIsTextFile(sdEntryNames_[sdSelection_])) {
    previewSelectedSdFile();
  } else if (sdIsImageFile(sdEntryNames_[sdSelection_])) {
    previewSelectedSdImage();
  } else {
    sdMessage_ = "Preview not supported";
  }
}

void FireOS::previewSelectedSdImage() {
  releaseSdImageBuffer();
  File file = SD.open(sdEntryPaths_[sdSelection_], FILE_READ);
  if (!file) {
    sdMessage_ = "Cannot open image";
    return;
  }
  const size_t fileSize = file.size();
  constexpr size_t kMaxPreviewBytes = 768 * 1024;
  if (fileSize == 0 || fileSize > kMaxPreviewBytes) {
    file.close();
    sdMessage_ = fileSize > kMaxPreviewBytes ? "Image too large" : "Empty image";
    return;
  }
  sdImageBuffer_ = static_cast<uint8_t*>(
      ESP.getPsramSize() > 0 ? ps_malloc(fileSize) : malloc(fileSize));
  if (!sdImageBuffer_) {
    file.close();
    sdMessage_ = "Not enough memory";
    return;
  }
  const size_t readBytes = file.read(sdImageBuffer_, fileSize);
  file.close();
  if (readBytes != fileSize) {
    releaseSdImageBuffer();
    sdMessage_ = "Cannot read image";
    return;
  }
  String lower = sdEntryNames_[sdSelection_];
  lower.toLowerCase();
  sdImagePreviewType_ = lower.endsWith(".png") ? 2 : lower.endsWith(".bmp") ? 3 : 1;
  sdImagePreviewPath_ = sdEntryPaths_[sdSelection_];
  sdImageBufferSize_ = fileSize;
  sdImageRendered_ = false;
  sdImagePreview_ = true;
}

void FireOS::releaseSdImageBuffer() {
  if (sdImageBuffer_) {
    free(sdImageBuffer_);
    sdImageBuffer_ = nullptr;
  }
  sdImageBufferSize_ = 0;
}

void FireOS::previewSelectedSdFile() {
  File file = SD.open(sdEntryPaths_[sdSelection_], FILE_READ);
  if (!file) {
    sdMessage_ = "Cannot open file";
    return;
  }
  sdPreviewLineCount_ = 0;
  while (file.available() && sdPreviewLineCount_ < 8) {
    String line = file.readStringUntil('\n');
    line.replace("\r", "");
    if (line.length() > 48) line = line.substring(0, 48);
    sdPreviewLines_[sdPreviewLineCount_++] = line;
  }
  file.close();
  sdPreview_ = true;
}

void FireOS::deleteSelectedSdEntry() {
  bool ok = false;
  if (sdSelection_ < sdEntryCount_) {
    ok = sdEntryDirectories_[sdSelection_]
             ? SD.rmdir(sdEntryPaths_[sdSelection_])
             : SD.remove(sdEntryPaths_[sdSelection_]);
  }
  sdDeleteConfirm_ = false;
  sdMessage_ = ok ? "Deleted" : "Delete failed (folder empty?)";
  refreshSdDirectory();
}

void FireOS::copySelectedSdEntry() {
  if (sdSelection_ >= sdEntryCount_ || sdEntryDirectories_[sdSelection_]) {
    sdMessage_ = "Copy folders not supported";
    return;
  }
  String base = "copy_" + sdEntryNames_[sdSelection_];
  String destination = sdJoinPath(sdPath_, base);
  uint8_t suffix = 1;
  while (SD.exists(destination) && suffix < 100) {
    destination = sdJoinPath(sdPath_, "copy" + String(suffix++) + "_" +
                                         sdEntryNames_[sdSelection_]);
  }
  File source = SD.open(sdEntryPaths_[sdSelection_], FILE_READ);
  File target = SD.open(destination, FILE_WRITE);
  if (!source || !target) {
    sdMessage_ = "Copy failed";
  } else {
    uint8_t buffer[256];
    while (source.available()) {
      const size_t amount = source.read(buffer, sizeof(buffer));
      if (amount == 0 || target.write(buffer, amount) != amount) break;
    }
    sdMessage_ = "Copied";
  }
  source.close();
  target.close();
  refreshSdDirectory();
}

void FireOS::moveSelectedSdEntry() {
  if (sdSelection_ >= sdEntryCount_ || sdPath_ == "/") {
    sdMessage_ = "Already at root";
    return;
  }
  const String destination = sdJoinPath(sdParentPath(sdPath_),
                                        sdEntryNames_[sdSelection_]);
  sdMessage_ = SD.rename(sdEntryPaths_[sdSelection_], destination)
                   ? "Moved to parent folder"
                   : "Move failed";
  refreshSdDirectory();
}

void FireOS::commitSdNameEditor() {
  sdNameBuffer_.trim();
  if (sdNameBuffer_.length() == 0) {
    sdMessage_ = "Name cannot be empty";
    sdNameEditor_ = false;
    return;
  }
  bool ok = false;
  if (sdNameIsNewFolder_) {
    ok = SD.mkdir(sdJoinPath(sdPath_, sdNameBuffer_));
  } else if (sdSelection_ < sdEntryCount_) {
    ok = SD.rename(sdEntryPaths_[sdSelection_],
                   sdJoinPath(sdPath_, sdNameBuffer_));
  }
  sdMessage_ = ok ? "Saved" : "Name already exists or invalid";
  sdNameEditor_ = false;
  refreshSdDirectory();
}

void FireOS::handleFileExplorerAction(uint8_t index) {
  if (index == 0) {
    sdActionMenu_ = false;
    openSelectedSdEntry();
  } else if (index == 1) {
    sdActionMenu_ = false;
    copySelectedSdEntry();
  } else if (index == 2) {
    sdActionMenu_ = false;
    moveSelectedSdEntry();
  } else if (index == 3) {
    if (sdSelection_ < sdEntryCount_) {
      sdNameBuffer_ = sdEntryNames_[sdSelection_].substring(0, 20);
      sdNameCursor_ = 0;
      sdNameIsNewFolder_ = false;
      sdNameEditor_ = true;
      sdActionMenu_ = false;
    }
  } else if (index == 4) {
    sdDeleteConfirm_ = true;
    sdActionMenu_ = false;
  } else if (index == 5) {
    sdNameBuffer_ = "NewFolder";
    sdNameCursor_ = 0;
    sdNameIsNewFolder_ = true;
    sdNameEditor_ = true;
    sdActionMenu_ = false;
  } else if (index == 6) {
    sdSortMode_ = (sdSortMode_ + 1) % 2;
    sdMessage_ = sdSortMode_ == 0 ? "Sorted by name" : "Sorted by size";
    sdActionMenu_ = false;
    refreshSdDirectory();
  } else {
    sdActionMenu_ = false;
  }
}

void FireOS::handleFileExplorerButton(uint8_t index) {
  if (sdImagePreview_) {
    if (index == 1 || index == 2) {
      sdImagePreview_ = false;
      sdImageRendered_ = false;
      releaseSdImageBuffer();
    }
    return;
  }
  if (sdPreview_) {
    if (index == 1 || index == 2) sdPreview_ = false;
    return;
  }
  if (sdNameEditor_) {
    if (index == 0 || index == 2) {
      const int length = strlen(kSdNameCharset);
      int position = strchr(kSdNameCharset, sdNameBuffer_[sdNameCursor_]) -
                     kSdNameCharset;
      position = (position + (index == 0 ? length - 1 : 1)) % length;
      sdNameBuffer_[sdNameCursor_] = kSdNameCharset[position];
    } else {
      if (sdNameCursor_ + 1 < sdNameBuffer_.length()) {
        ++sdNameCursor_;
      } else {
        commitSdNameEditor();
      }
    }
    return;
  }
  if (sdDeleteConfirm_) {
    if (index == 1) deleteSelectedSdEntry();
    else if (index == 0 || index == 2) sdDeleteConfirm_ = false;
    return;
  }
  if (sdActionMenu_) {
    if (index == 0) {
      sdActionIndex_ = (sdActionIndex_ + 7) % 8;
    } else if (index == 2) {
      sdActionIndex_ = (sdActionIndex_ + 1) % 8;
    } else {
      handleFileExplorerAction(sdActionIndex_);
    }
    return;
  }
  const uint8_t itemCount = sdEntryCount_ + 1;
  if (index == 0 && sdSelection_ > 0) --sdSelection_;
  if (index == 2 && sdSelection_ + 1 < itemCount) ++sdSelection_;
  if (index == 0 || index == 2) {
    if (sdSelection_ < sdOffset_) sdOffset_ = sdSelection_;
    if (sdSelection_ >= sdOffset_ + kFileVisibleRows)
      sdOffset_ = sdSelection_ - kFileVisibleRows + 1;
  } else {
    openSelectedSdEntry();
  }
}

String FireOS::externalAppBaseName(const String& path) const {
  return sdBaseName(path);
}

void FireOS::scanExternalApps() {
  externalAppCount_ = 0;
  luaAppCount_ = 0;
  if (!sdReady_ && !initSdCard()) return;
  File apps = SD.open("/apps");
  if (!apps || !apps.isDirectory()) return;
  File entry = apps.openNextFile();
  while (entry && externalAppCount_ < kMaxExternalApps) {
    String name = entry.name();
    if (!name.startsWith("/")) name = "/apps/" + name;
    String lowerName = name;
    lowerName.toLowerCase();
    if (!entry.isDirectory() && lowerName.endsWith(".bin")) {
      const uint8_t index = externalAppCount_++;
      externalAppPaths_[index] = name;
      externalAppNames_[index] = externalAppBaseName(name);
      externalAppOffsets_[index] = 0;
      externalAppSizes_[index] = entry.size();
      externalAppCompatible_[index] =
          inspectExternalImage(entry, externalAppOffsets_[index],
                               externalAppSizes_[index], false);
    }
    entry.close();
    entry = apps.openNextFile();
  }
  apps.close();
  for (uint8_t i = 0; i < externalAppCount_; ++i) {
    for (uint8_t j = i + 1; j < externalAppCount_; ++j) {
      if (externalAppNames_[j].compareTo(externalAppNames_[i]) < 0) {
        const String name = externalAppNames_[i];
        externalAppNames_[i] = externalAppNames_[j];
        externalAppNames_[j] = name;
        const String path = externalAppPaths_[i];
        externalAppPaths_[i] = externalAppPaths_[j];
        externalAppPaths_[j] = path;
        const uint32_t size = externalAppSizes_[i];
        externalAppSizes_[i] = externalAppSizes_[j];
        externalAppSizes_[j] = size;
        const uint32_t offset = externalAppOffsets_[i];
        externalAppOffsets_[i] = externalAppOffsets_[j];
        externalAppOffsets_[j] = offset;
        const bool compatible = externalAppCompatible_[i];
        externalAppCompatible_[i] = externalAppCompatible_[j];
        externalAppCompatible_[j] = compatible;
      }
    }
  }
  if (externalAppSelection_ >= externalAppCount_) {
    externalAppSelection_ = externalAppCount_ == 0 ? 0 : externalAppCount_ - 1;
  }
  scanLuaApps();
}

void FireOS::scanLuaApps() {
  luaAppCount_ = 0;
  if (!sdReady_ && !initSdCard()) return;
  File apps = SD.open("/apps");
  if (!apps || !apps.isDirectory()) return;
  File entry = apps.openNextFile();
  while (entry && luaAppCount_ < kMaxLuaApps) {
    if (entry.isDirectory()) {
      String raw = entry.name();
      if (!raw.startsWith("/")) raw = "/apps/" + raw;
      if (sdBaseName(raw).startsWith(".")) {
        entry.close();
        entry = apps.openNextFile();
        continue;
      }
      const String manifest = sdJoinPath(raw, "manifest.json");
      const String source = sdJoinPath(raw, "main.lua");
      if (SD.exists(manifest) && SD.exists(source)) {
        luaAppPaths_[luaAppCount_] = source;
        luaAppNames_[luaAppCount_] = sdBaseName(raw);
        luaAppIds_[luaAppCount_] = jsonStringField(
            [&]() {
              File manifestFile = SD.open(manifest, FILE_READ);
              String body;
              if (manifestFile && manifestFile.size() <= 8192) {
                while (manifestFile.available()) body += static_cast<char>(manifestFile.read());
              }
              if (manifestFile) manifestFile.close();
              return body;
            }(),
            "id");
        if (luaAppIds_[luaAppCount_].length() == 0)
          luaAppIds_[luaAppCount_] = luaAppNames_[luaAppCount_];
        luaAppDisplayNames_[luaAppCount_] = jsonStringField(
            [&]() {
              File manifestFile = SD.open(manifest, FILE_READ);
              String body;
              if (manifestFile && manifestFile.size() <= 8192) {
                while (manifestFile.available()) body += static_cast<char>(manifestFile.read());
              }
              if (manifestFile) manifestFile.close();
              return body;
            }(),
            "name");
        if (luaAppDisplayNames_[luaAppCount_].length() == 0)
          luaAppDisplayNames_[luaAppCount_] = luaAppNames_[luaAppCount_];
        ++luaAppCount_;
      }
    }
    entry.close();
    entry = apps.openNextFile();
  }
  apps.close();
  for (uint8_t i = 0; i < luaAppCount_; ++i) {
    for (uint8_t j = i + 1; j < luaAppCount_; ++j) {
      if (luaAppNames_[j].compareTo(luaAppNames_[i]) < 0) {
        String path = luaAppPaths_[i];
        luaAppPaths_[i] = luaAppPaths_[j];
        luaAppPaths_[j] = path;
        String name = luaAppNames_[i];
        luaAppNames_[i] = luaAppNames_[j];
        luaAppNames_[j] = name;
        String id = luaAppIds_[i];
        luaAppIds_[i] = luaAppIds_[j];
        luaAppIds_[j] = id;
        String displayName = luaAppDisplayNames_[i];
        luaAppDisplayNames_[i] = luaAppDisplayNames_[j];
        luaAppDisplayNames_[j] = displayName;
      }
    }
  }
  syncLuaAppSelections();
}

void FireOS::syncLuaAppSelections() {
  const String saved = preferences.getString("lua_menu", "");
  for (uint8_t index = 0; index < kMaxLuaApps; ++index)
    luaMenuSelected_[index] = false;
  for (uint8_t index = 0; index < luaAppCount_; ++index) {
    luaMenuSelected_[index] = saved.indexOf("|" + luaAppIds_[index] + "|") >= 0;
  }
  for (uint8_t button = 0; button < kButtonCount; ++button) {
    if (doubleClickAction_[button] < kBaseDoubleClickActionCount) continue;
    if (doubleClickLuaAppId_[button].length() == 0) {
      const uint8_t oldIndex = doubleClickAction_[button] -
                               kBaseDoubleClickActionCount;
      if (oldIndex < luaAppCount_)
        doubleClickLuaAppId_[button] = luaAppIds_[oldIndex];
    }
    uint8_t found = 0xFF;
    for (uint8_t index = 0; index < luaAppCount_; ++index) {
      if (luaAppIds_[index] == doubleClickLuaAppId_[button]) {
        found = index;
        break;
      }
    }
    if (found == 0xFF) {
      doubleClickAction_[button] = 0;
      doubleClickLuaAppId_[button] = "";
    } else {
      doubleClickAction_[button] = kBaseDoubleClickActionCount + found;
    }
  }
}

void FireOS::saveLuaAppSelections() {
  String saved = "|";
  for (uint8_t index = 0; index < luaAppCount_; ++index) {
    if (luaMenuSelected_[index]) saved += luaAppIds_[index] + "|";
  }
  preferences.putString("lua_menu", saved);
}

uint8_t FireOS::shortcutActionCount() const {
  uint8_t count = kBaseDoubleClickActionCount;
  for (uint8_t index = 0; index < luaAppCount_; ++index)
    if (luaMenuSelected_[index]) ++count;
  return count;
}

uint8_t FireOS::shortcutActionAtPosition(uint8_t position) const {
  if (position < kBaseDoubleClickActionCount) return position;
  uint8_t visible = kBaseDoubleClickActionCount;
  for (uint8_t index = 0; index < luaAppCount_; ++index) {
    if (!luaMenuSelected_[index]) continue;
    if (visible++ == position) return kBaseDoubleClickActionCount + index;
  }
  return 0;
}

uint8_t FireOS::shortcutPositionForAction(uint8_t action) const {
  if (action < kBaseDoubleClickActionCount) return action;
  uint8_t position = kBaseDoubleClickActionCount;
  const uint8_t target = action - kBaseDoubleClickActionCount;
  for (uint8_t index = 0; index < luaAppCount_; ++index) {
    if (!luaMenuSelected_[index]) continue;
    if (index == target) return position;
    ++position;
  }
  return 0;
}

String FireOS::shortcutActionLabel(uint8_t action) const {
  if (action < kBaseDoubleClickActionCount)
    return String(doubleClickActionLabel(action));
  const uint8_t index = action - kBaseDoubleClickActionCount;
  if (index < luaAppCount_) return luaAppDisplayNames_[index];
  return "Disabled";
}

void FireOS::setLuaError(const char** error, const char* value) {
  if (error) *error = value;
}

FireOS::LuaHardwareJob* FireOS::findLuaJob(uint16_t id) {
  for (LuaHardwareJob& job : luaJobs_)
    if (job.id == id) return &job;
  return nullptr;
}

const FireOS::LuaHardwareJob* FireOS::findLuaJob(uint16_t id) const {
  for (const LuaHardwareJob& job : luaJobs_)
    if (job.id == id) return &job;
  return nullptr;
}

uint16_t FireOS::createLuaJob(LuaJobKind kind, const char** error) {
  for (LuaHardwareJob& job : luaJobs_) {
    if (job.id != 0) continue;
    job = LuaHardwareJob();
    // IDs are app-scoped but must not collide with a still-live slot after
    // the 16-bit counter wraps.  Four slots make this bounded and cheap.
    for (uint32_t attempt = 0; attempt < 65535; ++attempt) {
      const uint16_t candidate = nextLuaJobId_++;
      if (nextLuaJobId_ == 0) nextLuaJobId_ = 1;
      if (candidate != 0 && !findLuaJob(candidate)) {
        job.id = candidate;
        break;
      }
    }
    if (job.id == 0) {
      setLuaError(error, "busy");
      return 0;
    }
    job.kind = kind;
    job.startedAt = millis();
    job.lastProgressAt = job.startedAt;
    return job.id;
  }
  setLuaError(error, "busy");
  return 0;
}

bool FireOS::luaGpioAllowed(int pin, bool write) const {
  if (pin == 26) return true;
  if (!write && (pin == 35 || pin == 36)) return true;
  return false;
}

bool FireOS::luaPwmAllowed(int pin) const { return pin == 26; }

bool FireOS::luaI2cAllowed(uint8_t bus, uint8_t address, bool write) const {
  if (bus != 0) return false;
  return !write || address == 0x40;
}

void FireOS::releaseLuaHardware() {
  // Lua currently has no microphone service, but keeping this reset here
  // makes the exit boundary safe if an audio adapter or an interrupted app
  // owns the capture path in a future build.
  fireStopMicCapture();
  fireReleaseMicCapture();
  if (M5.Speaker.isEnabled()) M5.Speaker.stop(kLuaSpeakerChannel);
  luaSpeakerFile_.close();
  if (luaSpeakerBuffer_ && (!luaSpeakerPlaying_ ||
                            luaSpeakerBufferReleased_)) {
    free(luaSpeakerBuffer_);
    luaSpeakerBuffer_ = nullptr;
    luaSpeakerBufferSize_ = 0;
    luaSpeakerBufferReleased_ = false;
    luaSpeakerPlaying_ = false;
  }
  luaSpeakerJobId_ = 0;
  for (LuaHardwareJob& job : luaJobs_) job = LuaHardwareJob();
  for (uint8_t pin = 0; pin < 40; ++pin) {
    if (!luaGpioClaimed_[pin]) continue;
    pinMode(pin, INPUT);
    luaGpioClaimed_[pin] = false;
    luaGpioMode_[pin] = 0;
  }
  if (luaPwmPin_ >= 0) {
    ledcWrite(luaPwmChannel_, 0);
    ledcDetachPin(luaPwmPin_);
    luaPwmPin_ = -1;
  }
  if (luaDacPin_ >= 0) {
    dacWrite(luaDacPin_, 0);
    pinMode(luaDacPin_, INPUT);
    luaDacPin_ = -1;
  }
  if (luaSpi_) {
    luaSpi_->end();
    delete luaSpi_;
    luaSpi_ = nullptr;
    luaSpiBus_ = -1;
    luaSpiFrequency_ = 1000000;
    luaSpiMode_ = 0;
  }
  if (luaUartOpen_) {
    Serial2.end();
    luaUartOpen_ = false;
    luaUartRxPin_ = luaUartTxPin_ = -1;
  }
}

bool FireOS::luaGpioModeCallback(void* context, int pin, const char* mode,
                                 const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !mode || !os->luaGpioAllowed(pin, false)) {
    setLuaError(error, "unavailable");
    return false;
  }
  if (os->luaGpioClaimed_[pin] ||
      (os->luaUartOpen_ &&
       (pin == os->luaUartRxPin_ || pin == os->luaUartTxPin_)) ||
      (pin == 26 && (os->luaPwmPin_ >= 0 || os->luaDacPin_ >= 0))) {
    setLuaError(error, "busy");
    return false;
  }
  uint8_t modeValue = 0;
  uint8_t arduinoMode = INPUT;
  if (!strcmp(mode, "input")) {
    modeValue = 1;
    arduinoMode = INPUT;
  } else if (!strcmp(mode, "input_pullup") && pin == 26) {
    modeValue = 2;
    arduinoMode = INPUT_PULLUP;
  } else if (!strcmp(mode, "input_pulldown") && pin == 26) {
    modeValue = 3;
    arduinoMode = INPUT_PULLDOWN;
  } else if (!strcmp(mode, "output") && pin == 26) {
    modeValue = 4;
    arduinoMode = OUTPUT;
  } else if (!strcmp(mode, "open_drain") && pin == 26) {
    modeValue = 5;
    arduinoMode = OUTPUT_OPEN_DRAIN;
  } else {
    setLuaError(error, "invalid_mode");
    return false;
  }
  pinMode(pin, arduinoMode);
  os->luaGpioClaimed_[pin] = true;
  os->luaGpioMode_[pin] = modeValue;
  return true;
}

bool FireOS::luaGpioReadCallback(void* context, int pin, int* value,
                                 const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !value || !os->luaGpioAllowed(pin, false) ||
      !os->luaGpioClaimed_[pin] ||
      (os->luaGpioMode_[pin] != 1 && os->luaGpioMode_[pin] != 2 &&
       os->luaGpioMode_[pin] != 3)) {
    setLuaError(error, "not_configured");
    return false;
  }
  *value = digitalRead(pin) ? 1 : 0;
  return true;
}

bool FireOS::luaGpioWriteCallback(void* context, int pin, int value,
                                  const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !os->luaGpioAllowed(pin, true) || !os->luaGpioClaimed_[pin] ||
      (os->luaGpioMode_[pin] != 4 && os->luaGpioMode_[pin] != 5)) {
    setLuaError(error, "not_configured");
    return false;
  }
  digitalWrite(pin, value ? HIGH : LOW);
  return true;
}

bool FireOS::luaGpioReleaseCallback(void* context, int pin, const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || pin < 0 || pin >= 40 || !os->luaGpioClaimed_[pin] ||
      (os->luaUartOpen_ &&
       (pin == os->luaUartRxPin_ || pin == os->luaUartTxPin_))) {
    setLuaError(error, "invalid_handle");
    return false;
  }
  pinMode(pin, INPUT);
  os->luaGpioClaimed_[pin] = false;
  os->luaGpioMode_[pin] = 0;
  return true;
}

bool FireOS::luaPwmConfigureCallback(void* context, int pin, int frequency,
                                    int resolution, const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !os->luaPwmAllowed(pin)) {
    setLuaError(error, "unavailable");
    return false;
  }
  if (os->luaGpioClaimed_[pin] || os->luaUartOpen_ ||
      os->luaDacPin_ >= 0 ||
      (os->luaPwmPin_ >= 0 && os->luaPwmPin_ != pin)) {
    setLuaError(error, "busy");
    return false;
  }
  if (os->luaPwmPin_ >= 0) {
    ledcDetachPin(os->luaPwmPin_);
    os->luaPwmPin_ = -1;
  }
  if (!ledcSetup(os->luaPwmChannel_, frequency, resolution)) {
    setLuaError(error, "pwm_failed");
    return false;
  }
  ledcAttachPin(pin, os->luaPwmChannel_);
  os->luaPwmPin_ = pin;
  return true;
}

bool FireOS::luaPwmWriteCallback(void* context, int pin, int duty,
                                 const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || os->luaPwmPin_ != pin) {
    setLuaError(error, "not_configured");
    return false;
  }
  ledcWrite(os->luaPwmChannel_, duty);
  return true;
}

bool FireOS::luaPwmStopCallback(void* context, int pin, const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || os->luaPwmPin_ != pin) {
    setLuaError(error, "invalid_handle");
    return false;
  }
  ledcWrite(os->luaPwmChannel_, 0);
  ledcDetachPin(pin);
  os->luaPwmPin_ = -1;
  return true;
}

bool FireOS::luaUartOpenCallback(void* context, int port, int baud, int rxPin,
                                 int txPin, const char* format,
                                 const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || port != 2 || rxPin != 36 || txPin != 26 || !format) {
    setLuaError(error, "unavailable");
    return false;
  }
  if (os->luaUartOpen_ || os->luaGpioClaimed_[rxPin] ||
      os->luaGpioClaimed_[txPin] || os->luaPwmPin_ >= 0) {
    setLuaError(error, "busy");
    return false;
  }
  uint32_t config = SERIAL_8N1;
  if (!strcmp(format, "8E1")) config = SERIAL_8E1;
  else if (!strcmp(format, "8O1")) config = SERIAL_8O1;
  else if (!strcmp(format, "7E1")) config = SERIAL_7E1;
  else if (!strcmp(format, "7O1")) config = SERIAL_7O1;
  else if (!strcmp(format, "8N2")) config = SERIAL_8N2;
  else if (strcmp(format, "8N1")) {
    setLuaError(error, "invalid_format");
    return false;
  }
  Serial2.begin(baud, config, rxPin, txPin);
  os->luaUartOpen_ = true;
  os->luaUartRxPin_ = rxPin;
  os->luaUartTxPin_ = txPin;
  return true;
}

uint16_t FireOS::luaUartReadCallback(void* context, int port, int maxBytes,
                                     const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || port != 2 || !os->luaUartOpen_) {
    setLuaError(error, "not_configured");
    return 0;
  }
  const uint16_t jobId = os->createLuaJob(LuaJobKind::UartRead, error);
  if (!jobId) return 0;
  LuaHardwareJob* job = os->findLuaJob(jobId);
  job->count = static_cast<uint16_t>(maxBytes);
  return jobId;
}

uint16_t FireOS::luaUartWriteCallback(void* context, int port,
                                      const char* text, size_t length,
                                      const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || port != 2 || !os->luaUartOpen_) {
    setLuaError(error, "not_configured");
    return 0;
  }
  const uint16_t jobId = os->createLuaJob(LuaJobKind::UartWrite, error);
  if (!jobId) return 0;
  LuaHardwareJob* job = os->findLuaJob(jobId);
  job->payloadCount = static_cast<uint16_t>(min<size_t>(length, sizeof(job->payload)));
  memcpy(job->payload, text, job->payloadCount);
  return jobId;
}

bool FireOS::luaUartCloseCallback(void* context, int port, const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || port != 2 || !os->luaUartOpen_) {
    setLuaError(error, "invalid_handle");
    return false;
  }
  Serial2.end();
  for (LuaHardwareJob& job : os->luaJobs_) {
    if (job.kind == LuaJobKind::UartRead || job.kind == LuaJobKind::UartWrite) {
      job.state = 2;
      job.errorCode = "uart_closed";
    }
  }
  os->luaUartOpen_ = false;
  os->luaUartRxPin_ = os->luaUartTxPin_ = -1;
  return true;
}

uint16_t FireOS::luaI2cScanCallback(void* context, int bus,
                                    const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || bus != 0 || !os->luaI2cAllowed(bus, 0, false)) {
    setLuaError(error, "unavailable");
    return 0;
  }
  if (!os->luaI2cStarted_) {
    Wire.begin(21, 22, 400000);
    os->luaI2cStarted_ = true;
  }
  const uint16_t jobId = os->createLuaJob(LuaJobKind::I2cScan, error);
  if (jobId) {
    if (LuaHardwareJob* job = os->findLuaJob(jobId)) job->step = 1;
  }
  return jobId;
}

uint16_t FireOS::luaI2cReadCallback(void* context, int bus, int address,
                                    int reg, int count, const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !os->luaI2cAllowed(bus, address, false)) {
    setLuaError(error, "unavailable");
    return 0;
  }
  if (!os->luaI2cStarted_) {
    Wire.begin(21, 22, 400000);
    os->luaI2cStarted_ = true;
  }
  const uint16_t jobId = os->createLuaJob(LuaJobKind::I2cRead, error);
  if (!jobId) return 0;
  LuaHardwareJob* job = os->findLuaJob(jobId);
  job->address = address;
  job->reg = reg;
  job->count = count;
  return jobId;
}

uint16_t FireOS::luaI2cWriteCallback(void* context, int bus, int address,
                                     const uint8_t* bytes, size_t length,
                                     const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !os->luaI2cAllowed(bus, address, true)) {
    setLuaError(error, "write_not_allowed");
    return 0;
  }
  if (!os->luaI2cStarted_) {
    Wire.begin(21, 22, 400000);
    os->luaI2cStarted_ = true;
  }
  const uint16_t jobId = os->createLuaJob(LuaJobKind::I2cWrite, error);
  if (!jobId) return 0;
  LuaHardwareJob* job = os->findLuaJob(jobId);
  job->address = address;
  job->payloadCount = static_cast<uint16_t>(min<size_t>(length, sizeof(job->payload)));
  memcpy(job->payload, bytes, job->payloadCount);
  return jobId;
}

bool FireOS::luaAdcReadCallback(void* context, int pin, int* value,
                                const char** error) {
  auto* os = static_cast<FireOS*>(context);
  // GPIO36 is ADC1 and is the only ADC resource exposed by the FIRE profile.
  // It is also the fixed UART2 RX pin, so never sample it while UART owns it.
  if (!os || !value || pin != 36 || os->luaUartOpen_ ||
      os->luaGpioClaimed_[pin] || os->aiAudioCaptureActive_) {
    setLuaError(error, os && os->aiAudioCaptureActive_ ? "busy" : "unavailable");
    return false;
  }
  analogReadResolution(12);
  *value = analogRead(pin);
  return *value >= 0;
}

bool FireOS::luaDacWriteCallback(void* context, int pin, int value,
                                 const char** error) {
  auto* os = static_cast<FireOS*>(context);
  // GPIO25 drives the FIRE speaker and is never handed to an app. GPIO26 is
  // the safe Grove-B output and the only DAC resource in the device profile.
  if (!os || pin != 26 || os->luaGpioClaimed_[pin] || os->luaUartOpen_ ||
      os->luaPwmPin_ >= 0 || (os->luaDacPin_ >= 0 && os->luaDacPin_ != pin)) {
    setLuaError(error, "busy");
    return false;
  }
  dacWrite(pin, static_cast<uint8_t>(value));
  os->luaDacPin_ = pin;
  return true;
}

bool FireOS::luaDacStopCallback(void* context, int pin, const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || os->luaDacPin_ != pin) {
    setLuaError(error, "invalid_handle");
    return false;
  }
  dacWrite(pin, 0);
  pinMode(pin, INPUT);
  os->luaDacPin_ = -1;
  return true;
}

bool FireOS::luaSpiOpenCallback(void* context, int bus, int sclk, int miso,
                                int mosi, int cs, int frequency, int mode,
                                const char** error) {
  auto* os = static_cast<FireOS*>(context);
  // FIRE's SD card owns VSPI (18/19/23). The SPI adapter is therefore only
  // available when SD is absent, with a fixed, validated CS on GPIO27. This
  // prevents an app from corrupting SD traffic or selecting flash/PSRAM pins.
  if (!os || bus != 2 || sclk != 18 || miso != 19 || mosi != 23 || cs != 27) {
    setLuaError(error, "unavailable");
    return false;
  }
  if (os->sdReady_ || os->luaSpi_ || os->luaUartOpen_ ||
      os->luaGpioClaimed_[cs] || os->luaPwmPin_ >= 0 || os->luaDacPin_ >= 0) {
    setLuaError(error, "busy");
    return false;
  }
  auto* spi = new SPIClass(VSPI);
  if (!spi) {
    setLuaError(error, "memory");
    return false;
  }
  spi->begin(sclk, miso, mosi, cs);
  os->luaSpi_ = spi;
  os->luaSpiBus_ = bus;
  os->luaSpiFrequency_ = static_cast<uint32_t>(frequency);
  os->luaSpiMode_ = static_cast<uint8_t>(mode);
  return true;
}

uint16_t FireOS::luaSpiTransferCallback(void* context, int bus,
                                        const uint8_t* bytes, size_t length,
                                        const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !os->luaSpi_ || os->luaSpiBus_ != bus || !bytes || length == 0 ||
      length > 512) {
    setLuaError(error, "not_configured");
    return 0;
  }
  const uint16_t jobId = os->createLuaJob(LuaJobKind::SpiTransfer, error);
  if (!jobId) return 0;
  LuaHardwareJob* job = os->findLuaJob(jobId);
  job->bus = static_cast<uint8_t>(bus);
  job->payloadCount = static_cast<uint16_t>(length);
  memcpy(job->payload, bytes, length);
  return jobId;
}

bool FireOS::luaSpiCloseCallback(void* context, int bus, const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !os->luaSpi_ || os->luaSpiBus_ != bus) {
    setLuaError(error, "invalid_handle");
    return false;
  }
  os->luaSpi_->end();
  delete os->luaSpi_;
  os->luaSpi_ = nullptr;
  os->luaSpiBus_ = -1;
  os->luaSpiFrequency_ = 1000000;
  os->luaSpiMode_ = 0;
  return true;
}

bool FireOS::luaPrivateAppPath(const char* relative, String& result,
                               const char** error) const {
  if (!relative || luaAppId_.length() == 0) {
    setLuaError(error, "unavailable");
    return false;
  }
  const String path(relative);
  if (path.length() > 96 || path.startsWith("/") || path.indexOf('\\') >= 0 ||
      path.indexOf(':') >= 0 || path.indexOf('\0') >= 0 ||
      path.indexOf("..") >= 0) {
    setLuaError(error, "invalid_path");
    return false;
  }
  result = "/apps/" + luaAppId_ + "/appdata";
  if (path.length() > 0) result += "/" + path;
  return true;
}

uint16_t FireOS::luaSdListCallback(void* context, const char* path,
                                   const char** error) {
  auto* os = static_cast<FireOS*>(context);
  String resolved;
  if (!os || !os->luaPrivateAppPath(path, resolved, error)) return 0;
  if (!os->sdReady_) {
    setLuaError(error, "unavailable");
    return 0;
  }
  const uint16_t jobId = os->createLuaJob(LuaJobKind::SdList, error);
  if (!jobId) return 0;
  os->findLuaJob(jobId)->path = resolved;
  return jobId;
}

uint16_t FireOS::luaSdReadCallback(void* context, const char* path,
                                   uint32_t offset, uint16_t count,
                                   const char** error) {
  auto* os = static_cast<FireOS*>(context);
  String resolved;
  if (!os || !os->luaPrivateAppPath(path, resolved, error)) return 0;
  if (!os->sdReady_) {
    setLuaError(error, "unavailable");
    return 0;
  }
  const uint16_t jobId = os->createLuaJob(LuaJobKind::SdRead, error);
  if (!jobId) return 0;
  LuaHardwareJob* job = os->findLuaJob(jobId);
  job->path = resolved;
  job->offset = offset;
  job->count = count;
  return jobId;
}

uint16_t FireOS::luaSdWriteCallback(void* context, const char* path,
                                    const char* text, size_t length, bool append,
                                    const char** error) {
  auto* os = static_cast<FireOS*>(context);
  String resolved;
  if (!os || !os->luaPrivateAppPath(path, resolved, error)) return 0;
  if (!text || length > 512) {
    setLuaError(error, "payload_too_large");
    return 0;
  }
  if (!os->sdReady_) {
    setLuaError(error, "unavailable");
    return 0;
  }
  const uint16_t jobId = os->createLuaJob(LuaJobKind::SdWrite, error);
  if (!jobId) return 0;
  LuaHardwareJob* job = os->findLuaJob(jobId);
  job->path = resolved;
  job->append = append;
  job->payloadCount = static_cast<uint16_t>(length);
  memcpy(job->payload, text, length);
  return jobId;
}

uint16_t FireOS::luaSdRemoveCallback(void* context, const char* path,
                                     const char** error) {
  auto* os = static_cast<FireOS*>(context);
  String resolved;
  if (!os || !os->luaPrivateAppPath(path, resolved, error)) return 0;
  if (!os->sdReady_) {
    setLuaError(error, "unavailable");
    return 0;
  }
  const uint16_t jobId = os->createLuaJob(LuaJobKind::SdRemove, error);
  if (!jobId) return 0;
  os->findLuaJob(jobId)->path = resolved;
  return jobId;
}

bool FireOS::luaSdMkdirCallback(void* context, const char* path,
                                const char** error) {
  auto* os = static_cast<FireOS*>(context);
  String resolved;
  if (!os || !os->luaPrivateAppPath(path, resolved, error)) return false;
  if (!os->sdReady_) {
    setLuaError(error, "unavailable");
    return false;
  }
  if (SD.exists(resolved)) {
    setLuaError(error, "already_exists");
    return false;
  }
  if (!SD.mkdir(resolved)) {
    setLuaError(error, "mkdir_failed");
    return false;
  }
  return true;
}

bool FireOS::luaPowerStatusCallback(void* context, float* battery,
                                    float* voltage, bool* charging, bool* usb) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !battery || !voltage || !charging || !usb) return false;
  os->refreshBatteryStatus();
  *battery = static_cast<float>(os->batteryLevel());
  *voltage = max<int16_t>(0, M5.Power.getBatteryVoltage()) / 1000.0f;
  *charging = os->batteryCharging();
  *usb = *charging || M5.Power.getVBUSVoltage() > 0;
  return true;
}

bool FireOS::luaPowerBrightnessCallback(void* context, int brightness,
                                        const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os) {
    setLuaError(error, "unavailable");
    return false;
  }
  M5.Display.setBrightness(static_cast<uint8_t>(brightness));
  os->brightness_ = static_cast<uint8_t>(brightness);
  os->brightnessStep_ = nearestBrightnessStep(os->brightness_);
  os->saveSettings();
  return true;
}

uint16_t FireOS::luaPowerSleepCallback(void* context, uint32_t duration,
                                       const char** error) {
  // Deep/light sleep changes the boot lifecycle and cannot be safely invoked
  // by a Lua callback without a dedicated OS wake/resume state machine.
  // Keep the method unavailable until that state machine exists rather than
  // pretending that a queued job is a sleep operation.
  (void)context;
  (void)duration;
  setLuaError(error, "unavailable");
  return 0;
}

bool FireOS::luaRtcNowCallback(void* context, uint32_t* epoch, int* year,
                               int* month, int* day, int* hour, int* minute,
                               int* second, const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !epoch || !year || !month || !day || !hour || !minute || !second) {
    setLuaError(error, "unavailable");
    return false;
  }
  const time_t now = time(nullptr);
  tm utc{};
  if (gmtime_r(&now, &utc) == nullptr) {
    setLuaError(error, "clock_unavailable");
    return false;
  }
  *epoch = static_cast<uint32_t>(now);
  *year = utc.tm_year + 1900;
  *month = utc.tm_mon + 1;
  *day = utc.tm_mday;
  *hour = utc.tm_hour;
  *minute = utc.tm_min;
  *second = utc.tm_sec;
  return true;
}

bool FireOS::luaRtcSetCallback(void* context, uint32_t epoch,
                               const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os) {
    setLuaError(error, "unavailable");
    return false;
  }
  timeval tv{};
  tv.tv_sec = static_cast<time_t>(epoch);
  if (settimeofday(&tv, nullptr) != 0) {
    setLuaError(error, "clock_set_failed");
    return false;
  }
  os->dateTime_.save();
  return true;
}

bool FireOS::validateLuaWav(const uint8_t* data, size_t length,
                            uint32_t& sampleRate, uint32_t& dataBytes) const {
  if (!data || length < 44 || length > kMaxLuaWavBytes ||
      memcmp(data, "RIFF", 4) != 0 || memcmp(data + 8, "WAVE", 4) != 0)
    return false;
  bool formatFound = false;
  bool dataFound = false;
  uint16_t audioFormat = 0;
  uint16_t channels = 0;
  uint16_t bits = 0;
  sampleRate = 0;
  dataBytes = 0;
  size_t cursor = 12;
  while (cursor + 8 <= length) {
    const uint32_t chunkSize = static_cast<uint32_t>(data[cursor + 4]) |
                               (static_cast<uint32_t>(data[cursor + 5]) << 8) |
                               (static_cast<uint32_t>(data[cursor + 6]) << 16) |
                               (static_cast<uint32_t>(data[cursor + 7]) << 24);
    const size_t payload = cursor + 8;
    if (chunkSize > length - payload) return false;
    if (memcmp(data + cursor, "fmt ", 4) == 0 && chunkSize >= 16) {
      audioFormat = static_cast<uint16_t>(data[payload]) |
                    (static_cast<uint16_t>(data[payload + 1]) << 8);
      channels = static_cast<uint16_t>(data[payload + 2]) |
                 (static_cast<uint16_t>(data[payload + 3]) << 8);
      sampleRate = static_cast<uint32_t>(data[payload + 4]) |
                   (static_cast<uint32_t>(data[payload + 5]) << 8) |
                   (static_cast<uint32_t>(data[payload + 6]) << 16) |
                   (static_cast<uint32_t>(data[payload + 7]) << 24);
      bits = static_cast<uint16_t>(data[payload + 14]) |
             (static_cast<uint16_t>(data[payload + 15]) << 8);
      formatFound = true;
    } else if (memcmp(data + cursor, "data", 4) == 0) {
      dataBytes = chunkSize;
      dataFound = true;
    }
    cursor = payload + chunkSize + (chunkSize & 1u);
  }
  return formatFound && dataFound && audioFormat == 1 && channels == 1 &&
         bits == 16 && (sampleRate == 8000 || sampleRate == 16000 ||
                        sampleRate == 24000) && dataBytes > 0;
}

void FireOS::releaseLuaSpeakerBufferIfReady() {
  if (!luaSpeakerBuffer_ || !luaSpeakerBufferReleased_) return;
  free(luaSpeakerBuffer_);
  luaSpeakerBuffer_ = nullptr;
  luaSpeakerBufferSize_ = 0;
  luaSpeakerBufferReleased_ = false;
  luaSpeakerPlaying_ = false;
}

void FireOS::luaSpeakerBufferReleaseCallback(void* context, const void* data,
                                              uint8_t) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !os->luaSpeakerBuffer_ || !data) return;
  const uintptr_t start = reinterpret_cast<uintptr_t>(os->luaSpeakerBuffer_);
  const uintptr_t end = start + os->luaSpeakerBufferSize_;
  const uintptr_t released = reinterpret_cast<uintptr_t>(data);
  if (released >= start && released < end)
    os->luaSpeakerBufferReleased_ = true;
}

uint16_t FireOS::luaSpeakerToneCallback(void* context, int frequency,
                                        int duration, int volume,
                                        const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !M5.Speaker.isEnabled()) {
    setLuaError(error, "unavailable");
    return 0;
  }
  if (os->aiAudioCaptureActive_ || os->aiAudioOutputActive_) {
    setLuaError(error, "busy");
    return 0;
  }
  if (os->luaSpeakerJobId_ != 0 || os->luaSpeakerPlaying_) {
    setLuaError(error, "busy");
    return 0;
  }
  const uint16_t jobId = os->createLuaJob(LuaJobKind::SpeakerTone, error);
  if (!jobId) return 0;
  LuaHardwareJob* job = os->findLuaJob(jobId);
  job->frequency = static_cast<uint32_t>(frequency);
  job->durationMs = static_cast<uint32_t>(duration);
  job->appVolume = static_cast<uint8_t>(volume);
  os->luaSpeakerJobId_ = jobId;
  return jobId;
}

uint16_t FireOS::luaSpeakerPlayCallback(void* context, const char* path,
                                        int volume, const char** error) {
  auto* os = static_cast<FireOS*>(context);
  String resolved;
  if (!os || !os->luaPrivateAppPath(path, resolved, error)) return 0;
  if (!os->sdReady_) {
    setLuaError(error, "unavailable");
    return 0;
  }
  if (!M5.Speaker.isEnabled()) {
    setLuaError(error, "unavailable");
    return 0;
  }
  if (os->aiAudioCaptureActive_ || os->aiAudioOutputActive_ ||
      os->luaSpeakerJobId_ != 0 || os->luaSpeakerPlaying_) {
    setLuaError(error, "busy");
    return 0;
  }
  const uint16_t jobId = os->createLuaJob(LuaJobKind::SpeakerPlay, error);
  if (!jobId) return 0;
  LuaHardwareJob* job = os->findLuaJob(jobId);
  job->path = resolved;
  job->appVolume = static_cast<uint8_t>(volume);
  os->luaSpeakerJobId_ = jobId;
  return jobId;
}

bool FireOS::luaSpeakerStopCallback(void* context, const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !M5.Speaker.isEnabled()) {
    setLuaError(error, "unavailable");
    return false;
  }
  M5.Speaker.stop(kLuaSpeakerChannel);
  for (LuaHardwareJob& job : os->luaJobs_) {
    if (job.kind == LuaJobKind::SpeakerTone ||
        job.kind == LuaJobKind::SpeakerPlay) {
      job.state = 3;
      job.errorCode = "cancelled";
    }
  }
  os->luaSpeakerJobId_ = 0;
  os->luaSpeakerFile_.close();
  if (!os->luaSpeakerPlaying_ && os->luaSpeakerBuffer_) {
    free(os->luaSpeakerBuffer_);
    os->luaSpeakerBuffer_ = nullptr;
    os->luaSpeakerBufferSize_ = 0;
    os->luaSpeakerBufferReleased_ = false;
  } else {
    os->releaseLuaSpeakerBufferIfReady();
  }
  return true;
}

bool FireOS::luaJobPollCallback(void* context, uint16_t id,
                                FireLuaRuntime::JobSnapshot* snapshot) {
  auto* os = static_cast<FireOS*>(context);
  const LuaHardwareJob* job = os ? os->findLuaJob(id) : nullptr;
  if (!job || !snapshot) return false;
  snapshot->state = job->state;
  snapshot->errorCode = job->errorCode;
  return true;
}

bool FireOS::luaJobResultCallback(void* context, uint16_t id,
                                  FireLuaRuntime::JobSnapshot* snapshot) {
  auto* os = static_cast<FireOS*>(context);
  const LuaHardwareJob* job = os ? os->findLuaJob(id) : nullptr;
  if (!job || !snapshot) return false;
  snapshot->state = job->state;
  snapshot->errorCode = job->state == 0 ? "not_ready" : job->errorCode;
  snapshot->addressCount = job->addressCount;
  memcpy(snapshot->addresses, job->addresses,
         sizeof(uint16_t) * job->addressCount);
  snapshot->byteCount = job->byteCount;
  memcpy(snapshot->bytes, job->bytes, job->byteCount);
  snapshot->text = job->text;
  snapshot->written = job->written;
  snapshot->entryCount = job->entryCount;
  for (uint16_t index = 0; index < job->entryCount && index < 32; ++index) {
    snapshot->entries[index].name = job->entryNames[index];
    snapshot->entries[index].sizeBytes = job->entrySizes[index];
    snapshot->entries[index].directory = job->entryDirectories[index];
  }
  snapshot->path = job->path;
  snapshot->resultKind = job->kind == LuaJobKind::I2cScan
                             ? FireLuaRuntime::JobSnapshot::I2cScan
                         : job->kind == LuaJobKind::UartRead
                             ? FireLuaRuntime::JobSnapshot::Uart
                         : job->kind == LuaJobKind::I2cRead
                             ? FireLuaRuntime::JobSnapshot::Bytes
                         : job->kind == LuaJobKind::SpiTransfer ||
                                   job->kind == LuaJobKind::SdRead
                             ? FireLuaRuntime::JobSnapshot::Bytes
                         : job->kind == LuaJobKind::SdList
                             ? FireLuaRuntime::JobSnapshot::Files
                         : FireLuaRuntime::JobSnapshot::Write;
  return true;
}

bool FireOS::luaJobCloseCallback(void* context, uint16_t id) {
  auto* os = static_cast<FireOS*>(context);
  LuaHardwareJob* job = os ? os->findLuaJob(id) : nullptr;
  if (!job) return false;
  if (os && id == os->luaSpeakerJobId_) {
    if (M5.Speaker.isEnabled()) M5.Speaker.stop(kLuaSpeakerChannel);
    os->luaSpeakerFile_.close();
    os->luaSpeakerJobId_ = 0;
    if (!os->luaSpeakerPlaying_)
      os->releaseLuaSpeakerBufferIfReady();
  }
  *job = LuaHardwareJob();
  return true;
}

bool FireOS::luaJobCancelCallback(void* context, uint16_t id) {
  auto* os = static_cast<FireOS*>(context);
  LuaHardwareJob* job = os ? os->findLuaJob(id) : nullptr;
  if (!job || job->state != 0) return false;
  job->state = 3;
  job->errorCode = "cancelled";
  if (os && id == os->luaSpeakerJobId_) {
    if (M5.Speaker.isEnabled()) M5.Speaker.stop(kLuaSpeakerChannel);
    os->luaSpeakerFile_.close();
    os->luaSpeakerJobId_ = 0;
    if (!os->luaSpeakerPlaying_)
      os->releaseLuaSpeakerBufferIfReady();
  }
  return true;
}

void FireOS::serviceLuaHardwareJobs() {
  if (luaSpeakerJobId_ == 0) releaseLuaSpeakerBufferIfReady();
  if (luaSpeakerPlaying_ && volume_ == 0 && M5.Speaker.isEnabled())
    M5.Speaker.stop(kLuaSpeakerChannel);
  for (LuaHardwareJob& job : luaJobs_) {
    if (job.id == 0 || job.state != 0) continue;
    const uint32_t now = millis();
    if (now - job.startedAt > job.timeoutMs) {
      job.state = 2;
      job.errorCode = "timeout";
      continue;
    }
    if (job.kind == LuaJobKind::I2cScan) {
      uint8_t processed = 0;
      while (job.step < 127 && processed++ < 4) {
        const uint8_t address = static_cast<uint8_t>(job.step++);
        Wire.beginTransmission(address);
        if (Wire.endTransmission() == 0 && job.addressCount < 126)
          job.addresses[job.addressCount++] = address;
      }
      if (job.step >= 127) job.state = 1;
    } else if (job.kind == LuaJobKind::I2cRead) {
      if (job.reg >= 0) {
        Wire.beginTransmission(job.address);
        Wire.write(static_cast<uint8_t>(job.reg));
        if (Wire.endTransmission(false) != 0) {
          job.state = 2;
          job.errorCode = "i2c_nack";
          continue;
        }
      }
      const uint8_t received = Wire.requestFrom(static_cast<int>(job.address),
                                                static_cast<int>(job.count));
      if (received == 0) {
        job.state = 2;
        job.errorCode = "i2c_read_failed";
        continue;
      }
      while (Wire.available() && job.byteCount < sizeof(job.bytes))
        job.bytes[job.byteCount++] = static_cast<uint8_t>(Wire.read());
      job.state = 1;
    } else if (job.kind == LuaJobKind::I2cWrite) {
      Wire.beginTransmission(job.address);
      Wire.write(job.payload, job.payloadCount);
      const uint8_t result = Wire.endTransmission();
      job.state = result == 0 ? 1 : 2;
      if (result != 0) job.errorCode = "i2c_nack";
      else job.written = job.payloadCount;
    } else if (job.kind == LuaJobKind::UartWrite) {
      const size_t written = Serial2.write(job.payload, job.payloadCount);
      job.written = written;
      job.state = written == job.payloadCount ? 1 : 2;
      if (job.state == 2) job.errorCode = "uart_write_failed";
    } else if (job.kind == LuaJobKind::UartRead) {
      while (Serial2.available() && job.byteCount < job.count &&
             job.byteCount < sizeof(job.bytes)) {
        job.bytes[job.byteCount++] = static_cast<uint8_t>(Serial2.read());
        job.lastProgressAt = now;
      }
      if (job.byteCount >= job.count ||
          (job.byteCount > 0 && now - job.lastProgressAt > 40) ||
          now - job.startedAt > 250) {
        for (uint16_t index = 0; index < job.byteCount; ++index)
          if (job.bytes[index] >= 32 && job.bytes[index] < 127)
            job.text += static_cast<char>(job.bytes[index]);
        job.state = 1;
      }
    } else if (job.kind == LuaJobKind::SpiTransfer) {
      if (!luaSpi_ || luaSpiBus_ != job.bus) {
        job.state = 2;
        job.errorCode = "spi_closed";
        continue;
      }
      const uint16_t remaining = job.payloadCount - job.step;
      const uint16_t chunk = min<uint16_t>(remaining, 64);
      luaSpi_->beginTransaction(
          SPISettings(luaSpiFrequency_, MSBFIRST, luaSpiMode_));
      for (uint16_t index = 0; index < chunk; ++index) {
        job.bytes[job.step + index] =
            luaSpi_->transfer(job.payload[job.step + index]);
      }
      luaSpi_->endTransaction();
      job.step = static_cast<uint16_t>(job.step + chunk);
      job.byteCount = job.step;
      if (job.step >= job.payloadCount) {
        job.written = job.payloadCount;
        job.state = 1;
      }
    } else if (job.kind == LuaJobKind::SdList) {
      File directory = SD.open(job.path, FILE_READ);
      if (!directory || !directory.isDirectory()) {
        if (directory) directory.close();
        job.state = 2;
        job.errorCode = "not_found";
        continue;
      }
      File entry = directory.openNextFile();
      while (entry && job.entryCount < 32) {
        String name = entry.name();
        const int slash = name.lastIndexOf('/');
        if (slash >= 0) name = name.substring(slash + 1);
        job.entryNames[job.entryCount] = name;
        job.entrySizes[job.entryCount] = entry.isDirectory() ? 0 : entry.size();
        job.entryDirectories[job.entryCount] = entry.isDirectory();
        ++job.entryCount;
        entry.close();
        entry = directory.openNextFile();
      }
      if (entry) entry.close();
      directory.close();
      job.state = 1;
    } else if (job.kind == LuaJobKind::SdRead) {
      File file = SD.open(job.path, FILE_READ);
      if (!file || file.isDirectory() || !file.seek(job.offset)) {
        if (file) file.close();
        job.state = 2;
        job.errorCode = "read_failed";
        continue;
      }
      const size_t amount = file.read(job.bytes, job.count);
      file.close();
      if (amount == 0 && job.count > 0) {
        job.state = 2;
        job.errorCode = "read_failed";
        continue;
      }
      job.byteCount = static_cast<uint16_t>(amount);
      job.state = 1;
    } else if (job.kind == LuaJobKind::SdWrite) {
      File file = SD.open(job.path, job.append ? FILE_APPEND : FILE_WRITE);
      if (!file) {
        job.state = 2;
        job.errorCode = "open_failed";
        continue;
      }
      const size_t amount = file.write(job.payload, job.payloadCount);
      file.close();
      job.written = static_cast<uint32_t>(amount);
      job.state = amount == job.payloadCount ? 1 : 2;
      if (job.state == 2) job.errorCode = "write_failed";
    } else if (job.kind == LuaJobKind::SdRemove) {
      if (!SD.exists(job.path)) {
        job.state = 2;
        job.errorCode = "not_found";
        continue;
      }
      const bool ok = SD.remove(job.path) || SD.rmdir(job.path);
      job.state = ok ? 1 : 2;
      if (!ok) job.errorCode = "remove_failed";
    } else if (job.kind == LuaJobKind::SpeakerTone) {
      if (!job.started) {
        if (aiAudioCaptureActive_ || aiAudioOutputActive_) {
          job.state = 2;
          job.errorCode = "busy";
          luaSpeakerJobId_ = 0;
          continue;
        }
        if (job.appVolume == 0 || volume_ == 0) {
          job.state = 1;
          job.written = 0;
          luaSpeakerJobId_ = 0;
          continue;
        }
        M5.Speaker.setChannelVolume(kLuaSpeakerChannel, job.appVolume);
        if (!M5.Speaker.tone(static_cast<float>(job.frequency),
                             job.durationMs, kLuaSpeakerChannel, true)) {
          job.state = 2;
          job.errorCode = "speaker_rejected";
          luaSpeakerJobId_ = 0;
          continue;
        }
        job.started = true;
        luaSpeakerPlaying_ = true;
        job.timeoutMs = job.durationMs + 3000;
      } else if (!M5.Speaker.isPlaying(kLuaSpeakerChannel)) {
        job.state = 1;
        job.written = 0;
        luaSpeakerPlaying_ = false;
        luaSpeakerJobId_ = 0;
      }
    } else if (job.kind == LuaJobKind::SpeakerPlay) {
      if (!job.started && job.mediaSize == 0) {
        if (!sdReady_ || !SD.exists(job.path)) {
          job.state = 2;
          job.errorCode = "not_found";
          luaSpeakerJobId_ = 0;
          continue;
        }
        luaSpeakerFile_ = SD.open(job.path, FILE_READ);
        if (!luaSpeakerFile_ || luaSpeakerFile_.isDirectory()) {
          luaSpeakerFile_.close();
          job.state = 2;
          job.errorCode = "open_failed";
          luaSpeakerJobId_ = 0;
          continue;
        }
        const size_t size = luaSpeakerFile_.size();
        if (size == 0 || size > kMaxLuaWavBytes) {
          luaSpeakerFile_.close();
          job.state = 2;
          job.errorCode = "audio_too_large";
          luaSpeakerJobId_ = 0;
          continue;
        }
        luaSpeakerBuffer_ = static_cast<uint8_t*>(
            ESP.getPsramSize() > 0 ? ps_malloc(size) : malloc(size));
        if (!luaSpeakerBuffer_) {
          luaSpeakerFile_.close();
          job.state = 2;
          job.errorCode = "memory";
          luaSpeakerJobId_ = 0;
          continue;
        }
        luaSpeakerBufferSize_ = size;
        luaSpeakerBufferReleased_ = false;
        luaSpeakerPlaying_ = false;
        job.mediaSize = static_cast<uint32_t>(size);
        job.mediaRead = 0;
      }
      if (!job.started && job.mediaRead < job.mediaSize) {
        const size_t remaining = job.mediaSize - job.mediaRead;
        const size_t amount = luaSpeakerFile_.read(
            luaSpeakerBuffer_ + job.mediaRead, min<size_t>(remaining, 2048));
        if (amount == 0) {
          luaSpeakerFile_.close();
          free(luaSpeakerBuffer_);
          luaSpeakerBuffer_ = nullptr;
          luaSpeakerBufferSize_ = 0;
          job.state = 2;
          job.errorCode = "read_failed";
          luaSpeakerJobId_ = 0;
          continue;
        }
        job.mediaRead += amount;
        if (job.mediaRead < job.mediaSize) continue;
        luaSpeakerFile_.close();
      }
      if (!job.started && job.mediaRead >= job.mediaSize) {
        uint32_t sampleRate = 0;
        uint32_t dataBytes = 0;
        if (!validateLuaWav(luaSpeakerBuffer_, luaSpeakerBufferSize_,
                            sampleRate, dataBytes)) {
          free(luaSpeakerBuffer_);
          luaSpeakerBuffer_ = nullptr;
          luaSpeakerBufferSize_ = 0;
          job.state = 2;
          job.errorCode = "invalid_wav";
          luaSpeakerJobId_ = 0;
          continue;
        }
        if (aiAudioCaptureActive_ || aiAudioOutputActive_) {
          free(luaSpeakerBuffer_);
          luaSpeakerBuffer_ = nullptr;
          luaSpeakerBufferSize_ = 0;
          job.state = 2;
          job.errorCode = "busy";
          luaSpeakerJobId_ = 0;
          continue;
        }
        if (job.appVolume == 0 || volume_ == 0) {
          free(luaSpeakerBuffer_);
          luaSpeakerBuffer_ = nullptr;
          luaSpeakerBufferSize_ = 0;
          job.state = 1;
          job.written = 0;
          luaSpeakerJobId_ = 0;
          continue;
        }
        M5.Speaker.setChannelVolume(kLuaSpeakerChannel, job.appVolume);
        if (!M5.Speaker.playWav(luaSpeakerBuffer_, luaSpeakerBufferSize_, 1,
                                kLuaSpeakerChannel, true)) {
          free(luaSpeakerBuffer_);
          luaSpeakerBuffer_ = nullptr;
          luaSpeakerBufferSize_ = 0;
          job.state = 2;
          job.errorCode = "speaker_rejected";
          luaSpeakerJobId_ = 0;
          continue;
        }
        job.started = true;
        luaSpeakerPlaying_ = true;
        const uint32_t duration =
            static_cast<uint32_t>((static_cast<uint64_t>(dataBytes) * 1000) /
                                  (sampleRate * 2));
        job.timeoutMs = duration + 3000;
      } else if (job.started && !M5.Speaker.isPlaying(kLuaSpeakerChannel) &&
                 luaSpeakerBufferReleased_) {
        job.state = 1;
        job.written = 0;
        luaSpeakerPlaying_ = false;
        luaSpeakerJobId_ = 0;
        releaseLuaSpeakerBufferIfReady();
      }
    }
  }
}

int8_t FireOS::managerItemForAppId(const String& appId) const {
  if (appId.length() == 0) return -1;
  for (uint8_t index = 0; index < managerItemCount_; ++index) {
    if (managerItems_[index].appId == appId) return index;
  }
  return -1;
}

void FireOS::rebuildAppManagerItems() {
  managerItemCount_ = 0;
  for (uint8_t index = 0;
       index < externalAppCount_ && managerItemCount_ < kMaxManagerItems;
       ++index) {
    ManagerItem& item = managerItems_[managerItemCount_++];
    item = ManagerItem();
    item.kind = 0;
    item.local = true;
    item.name = externalAppNames_[index];
    item.localPath = externalAppPaths_[index];
  }
  for (uint8_t index = 0;
       index < luaAppCount_ && managerItemCount_ < kMaxManagerItems;
       ++index) {
    const String source = luaAppPaths_[index];
    const int slash = source.lastIndexOf('/');
    const String folder = slash > 0 ? source.substring(0, slash) : source;
    const String appId = sdBaseName(folder);
    ManagerItem& item = managerItems_[managerItemCount_++];
    item = ManagerItem();
    item.kind = 1;
    item.local = true;
    item.appId = appId;
    item.name = luaAppNames_[index];
    item.localPath = source;
    item.localPackageId = preferences.getString(
        compactPreferenceKey("ap_", appId).c_str(), "");
    File manifest = SD.open(sdJoinPath(folder, "manifest.json"), FILE_READ);
    if (manifest && manifest.size() <= 8192) {
      String body;
      while (manifest.available()) body += static_cast<char>(manifest.read());
      item.localVersion = jsonStringField(body, "version");
    }
    if (manifest) manifest.close();
  }

  for (uint8_t backendIndex = 0; backendIndex < backendAppCount_; ++backendIndex) {
    const BackendAppInfo& backend = backendApps_[backendIndex];
    int8_t found = managerItemForAppId(backend.appId);
    if (found < 0) {
      if (managerItemCount_ >= kMaxManagerItems) continue;
      found = managerItemCount_++;
      managerItems_[found] = ManagerItem();
      managerItems_[found].kind = 2;
    }
    ManagerItem& item = managerItems_[found];
    item.backend = true;
    item.appId = backend.appId;
    item.projectId = backend.projectId;
    if (item.name.length() == 0) item.name = backend.name;
    item.packageId = backend.latestPackageId;
    item.version = backend.latestVersion;
    item.versionCount = backend.versionCount;
    item.downloadable = backend.downloadable;
    item.canDeleteBackend = backend.canDelete;
    item.backendBlockReason = backend.downloadable ? backend.deleteReason
                                                   : backend.deleteReason;
  }

  for (uint8_t i = 0; i < managerItemCount_; ++i) {
    for (uint8_t j = i + 1; j < managerItemCount_; ++j) {
      if (managerItems_[j].name.compareTo(managerItems_[i].name) >= 0) continue;
      ManagerItem swap = managerItems_[i];
      managerItems_[i] = managerItems_[j];
      managerItems_[j] = swap;
    }
  }
  const uint8_t itemCount = managerItemCount_ + 1;
  if (managerSelection_ >= itemCount) managerSelection_ = itemCount - 1;
  if (managerSelection_ < managerOffset_) managerOffset_ = managerSelection_;
  if (managerSelection_ >= managerOffset_ + 6)
    managerOffset_ = managerSelection_ - 5;
}

void FireOS::updateAppManagerBackend() {
  if (screen_ != Screen::AppsSettings || !backendClient_ ||
      !backendClient_->sessionReady())
    return;
  if (!backendCatalogRequested_ && !backendCatalogLoading_) {
    backendCatalogRequested_ = backendClient_->appList(0);
    backendCatalogLoading_ = backendCatalogRequested_;
    if (backendCatalogRequested_) {
      backendCatalogNextOffset_ = 0;
      backendCatalogStatus_ = "Loading backend apps...";
      managerStatus_ = backendCatalogStatus_;
      redrawRequested_ = true;
    }
  }
}

void FireOS::parseBackendAppCatalog(const String& message) {
  const int appsAt = message.indexOf("\"apps\"");
  int cursor = appsAt >= 0 ? message.indexOf('{', appsAt) : -1;
  while (cursor >= 0 && backendAppCount_ < kMaxBackendApps) {
    const int end = message.indexOf('}', cursor);
    if (end < 0) break;
    const String object = message.substring(cursor, end + 1);
    const String appId = jsonStringField(object, "app_id");
    if (appId.length() > 0) {
      int8_t existing = -1;
      for (uint8_t index = 0; index < backendAppCount_; ++index) {
        if (backendApps_[index].appId == appId) {
          existing = index;
          break;
        }
      }
      const uint8_t index = existing >= 0
                                 ? static_cast<uint8_t>(existing)
                                 : backendAppCount_++;
      BackendAppInfo& item = backendApps_[index];
      item.appId = appId;
      item.projectId = jsonStringField(object, "project_id");
      item.name = jsonStringField(object, "name");
      item.latestPackageId = jsonStringField(object, "latest_package_id");
      item.latestVersion = jsonStringField(object, "latest_version");
      item.versionCount = static_cast<uint8_t>(
          constrain(jsonIntField(object, "version_count"), 0, 255));
      item.downloadable = jsonBoolField(object, "downloadable");
      item.canDelete = jsonBoolField(object, "can_delete_from_device");
      item.deleteReason = jsonStringField(object, "download_block_reason");
      if (item.deleteReason.length() == 0)
        item.deleteReason = jsonStringField(object, "device_delete_block_reason");
    }
    cursor = message.indexOf('{', end + 1);
  }
  rebuildAppManagerItems();
  const bool complete = message.indexOf("\"next_offset\":null") >= 0;
  if (!complete) {
    const int next = jsonIntField(message, "next_offset", -1);
    if (next >= 0 && next != backendCatalogNextOffset_ &&
        backendClient_ && backendClient_->sessionReady()) {
      backendCatalogNextOffset_ = next;
      backendCatalogLoading_ = backendClient_->appList(next);
      return;
    }
  }
  backendCatalogLoading_ = false;
  backendCatalogRequested_ = true;
  backendCatalogStatus_ = "Backend apps: " + String(backendAppCount_);
  managerStatus_ = backendCatalogStatus_;
  redrawRequested_ = true;
}

void FireOS::parseBackendAppVersions(const String& message) {
  appManagerVersionCount_ = 0;
  appManagerVersionProjectId_ = jsonStringField(message, "project_id");
  const int versionsAt = message.indexOf("\"versions\"");
  int cursor = versionsAt >= 0 ? message.indexOf('{', versionsAt) : -1;
  while (cursor >= 0 && appManagerVersionCount_ < kMaxBackendVersions) {
    const int end = message.indexOf('}', cursor);
    if (end < 0) break;
    const String object = message.substring(cursor, end + 1);
    const uint8_t index = appManagerVersionCount_++;
    appManagerVersionPackageIds_[index] = jsonStringField(object, "package_id");
    appManagerVersionLabels_[index] = jsonStringField(object, "version");
    appManagerVersionReasons_[index] = jsonStringField(object, "download_block_reason");
    appManagerVersionDownloadable_[index] =
        jsonBoolField(object, "downloadable");
    cursor = message.indexOf('{', end + 1);
  }
  appManagerVersionSelection_ = 0;
  appManagerVersionOffset_ = 0;
  appManagerVersionDialog_ = appManagerVersionCount_ > 0;
  managerStatus_ = appManagerVersionDialog_ ? "Choose version" : "No versions";
  redrawRequested_ = true;
}

void FireOS::prepareAppManagerActions() {
  appManagerActionCount_ = 0;
  if (managerSelection_ >= managerItemCount_) return;
  const ManagerItem& item = managerItems_[managerSelection_];
  auto add = [&](uint8_t code, const char* label) {
    if (appManagerActionCount_ >= 6) return;
    appManagerActionCodes_[appManagerActionCount_] = code;
    appManagerActionLabels_[appManagerActionCount_++] = label;
  };
  if (item.local) add(1, "Launch");
  if (item.backend && item.packageId.length() > 0) add(2, "Download/update");
  if (item.local) add(3, "Delete local");
  if (item.backend && item.canDeleteBackend) add(4, "Delete backend");
  add(5, "Back");
  appManagerActionIndex_ = 0;
}

void FireOS::requestSelectedAppVersions() {
  if (managerSelection_ >= managerItemCount_ || !backendClient_) return;
  const ManagerItem& item = managerItems_[managerSelection_];
  if (!item.backend) return;
  appManagerVersionProjectId_ = item.projectId;
  appManagerVersionAppId_ = item.appId;
  appManagerVersionDialog_ = false;
  managerStatus_ = "Loading versions...";
  if (!backendClient_->appVersions(item.projectId, item.appId, 0))
    managerStatus_ = "Backend unavailable";
}

void FireOS::sendAppInventory() {
  if (!backendClient_ || !backendClient_->sessionReady()) return;
  if (!sdReady_) {
    backendClient_->appInventory("[]", false, false);
    return;
  }
  String appsJson = "[";
  for (uint8_t index = 0; index < luaAppCount_; ++index) {
    const String source = luaAppPaths_[index];
    const int slash = source.lastIndexOf('/');
    const String folder = slash > 0 ? source.substring(0, slash) : source;
    const String appId = sdBaseName(folder);
    String version;
    String checksum;
    File manifest = SD.open(sdJoinPath(folder, "manifest.json"), FILE_READ);
    if (manifest && manifest.size() <= 8192) {
      String body;
      while (manifest.available()) body += static_cast<char>(manifest.read());
      version = jsonStringField(body, "version");
      checksum = jsonStringField(body, "checksum");
    }
    if (manifest) manifest.close();
    const String packageId = preferences.getString(
        compactPreferenceKey("ap_", appId).c_str(), "");
    if (index > 0) appsJson += ',';
    appsJson += "{\"app_id\":\"" + jsonEscapeField(appId);
    if (packageId.length() > 0)
      appsJson += "\",\"package_id\":\"" + jsonEscapeField(packageId);
    appsJson += "\",\"version\":\"" + jsonEscapeField(version) +
                "\",\"checksum\":\"" + jsonEscapeField(checksum) + "\"}";
  }
  appsJson += ']';
  backendClient_->appInventory(appsJson, true, true);
}

bool FireOS::deleteExternalApp(const String& path) {
  if (path.length() == 0 || (!sdReady_ && !initSdCard())) return false;
  const bool deleted = SD.remove(path);
  if (deleted && selectedBootAppPath_ == path) {
    selectedBootAppPath_ = "";
    saveSettings();
  }
  return deleted;
}

bool FireOS::deleteLuaApp(const String& path) {
  if (path.length() == 0 || (!sdReady_ && !initSdCard())) return false;
  String folder = path;
  const int slash = folder.lastIndexOf('/');
  if (slash <= 0) return false;
  folder = folder.substring(0, slash);
  const bool ok = removeSdTree(folder);
  if (ok) {
    const String appId = sdBaseName(folder);
    preferences.remove(compactPreferenceKey("ap_", appId).c_str());
    if (backendClient_ && backendClient_->sessionReady())
      backendClient_->appDeleted(appId);
    scanLuaApps();
    rebuildAppManagerItems();
    sendAppInventory();
  }
  return ok;
}

bool FireOS::inspectExternalImage(File& file, uint32_t& imageOffset,
                                  uint32_t& imageSize,
                                  bool verifyChecksum) const {
  imageOffset = 0;
  imageSize = 0;
  if (!file || file.size() < 32) return false;

  uint32_t candidateOffsets[2] = {0, 0x10000};
  for (uint8_t candidate = 0; candidate < 2; ++candidate) {
    const uint32_t offset = candidateOffsets[candidate];
    if (offset + 24 > file.size()) continue;
    uint8_t header[24] = {};
    if (!file.seek(offset) || file.read(header, sizeof(header)) !=
                                  sizeof(header)) {
      continue;
    }
    if (header[0] != 0xE9 || header[1] == 0 || header[1] > 16 ||
        header[12] != 0 || header[13] != 0) {
      continue;
    }

    uint32_t cursor = offset + sizeof(header);
    uint8_t checksum = 0xEF;
    bool valid = true;
    for (uint8_t segment = 0; segment < header[1]; ++segment) {
      if (cursor + 8 > file.size()) {
        valid = false;
        break;
      }
      uint8_t segmentHeader[8] = {};
      if (!file.seek(cursor) ||
          file.read(segmentHeader, sizeof(segmentHeader)) !=
              sizeof(segmentHeader)) {
        valid = false;
        break;
      }
      const uint32_t length =
          static_cast<uint32_t>(segmentHeader[4]) |
          (static_cast<uint32_t>(segmentHeader[5]) << 8) |
          (static_cast<uint32_t>(segmentHeader[6]) << 16) |
          (static_cast<uint32_t>(segmentHeader[7]) << 24);
      if (length > file.size() - cursor - 8) {
        valid = false;
        break;
      }
      const uint32_t dataStart = cursor + 8;
      if (verifyChecksum) {
        if (!file.seek(dataStart)) {
          valid = false;
          break;
        }
        uint32_t remaining = length;
        uint8_t checksumBuffer[256] = {};
        while (remaining > 0) {
          const size_t request = min<size_t>(sizeof(checksumBuffer), remaining);
          const size_t amount = file.read(checksumBuffer, request);
          if (amount == 0) {
            valid = false;
            break;
          }
          for (size_t byte = 0; byte < amount; ++byte)
            checksum ^= checksumBuffer[byte];
          remaining -= amount;
        }
      }
      if (!valid) break;
      cursor = dataStart + length;
      cursor = (cursor + 15u) & ~15u;
    }
    if (!valid || cursor >= file.size()) continue;

    if (verifyChecksum) {
      uint8_t storedChecksum = 0;
      if (!file.seek(cursor) || file.read(&storedChecksum, 1) != 1 ||
          storedChecksum != checksum) {
        continue;
      }
    }

    // One checksum byte follows the aligned segment data. Newer images may
    // also contain a 32-byte validation hash; include it when present.
    uint32_t totalSize = cursor - offset + 1;
    if (offset + totalSize + 32 <= file.size()) {
      uint8_t nextByte = 0xFF;
      if (file.seek(offset + totalSize) && file.read(&nextByte, 1) == 1 &&
          nextByte != 0xFF) {
        totalSize += 32;
      }
    }
    imageOffset = offset;
    imageSize = totalSize;
    return true;
  }
  return false;
}

bool FireOS::installExternalApp(const String& path, bool rebootAfterInstall,
                                bool makeBootApp) {
  const esp_partition_t* target = esp_ota_get_next_update_partition(nullptr);
  File source = SD.open(path, FILE_READ);
  uint32_t imageOffset = 0;
  uint32_t imageSize = 0;
  const bool validImage = source &&
                          inspectExternalImage(source, imageOffset, imageSize,
                                               true);
  if (!source || !target || !validImage || imageSize > target->size) {
    source.close();
    externalAppMessage_ = validImage ? "Rejected: app too large"
                                     : "Rejected: incompatible .bin";
    return false;
  }
  if (!source.seek(imageOffset)) {
    source.close();
    externalAppMessage_ = "Cannot read app image";
    return false;
  }
  esp_ota_handle_t handle = 0;
  if (esp_ota_begin(target, imageSize, &handle) != ESP_OK) {
    source.close();
    externalAppMessage_ = "Install could not start";
    return false;
  }
  uint8_t buffer[4096];
  bool ok = true;
  uint32_t remaining = imageSize;
  while (remaining > 0) {
    const size_t request = min<size_t>(sizeof(buffer), remaining);
    const size_t amount = source.read(buffer, request);
    if (amount == 0 || esp_ota_write(handle, buffer, amount) != ESP_OK) {
      ok = false;
      break;
    }
    remaining -= amount;
  }
  source.close();
  if (esp_ota_end(handle) != ESP_OK) ok = false;
  if (ok && esp_ota_set_boot_partition(target) != ESP_OK) ok = false;
  if (!ok) {
    externalAppMessage_ = "Install failed; FIRE OS retained";
    return false;
  }
  if (rebootAfterInstall) {
    if (makeBootApp) {
      selectedBootAppPath_ = path;
      saveSettings();
    }
    ESP.restart();
  }
  externalAppMessage_ = "Installed to inactive slot";
  return true;
}

bool FireOS::launchSelectedBootApp() {
  if (selectedBootAppPath_.length() == 0) return false;
  if (!sdReady_ && !initSdCard()) return false;
  if (selectedBootAppPath_.endsWith("/main.lua")) {
    scanLuaApps();
    for (uint8_t index = 0; index < luaAppCount_; ++index) {
      if (luaAppPaths_[index] == selectedBootAppPath_)
        return startLuaApp(luaAppPaths_[index], luaAppDisplayNames_[index]);
    }
    return false;
  }
  return installExternalApp(selectedBootAppPath_, true, true);
}

void FireOS::saveSavedWifiNetworks() {
  for (uint8_t index = 0; index < 5; ++index) {
    preferences.remove(("wifi_ssid_" + String(index)).c_str());
    preferences.remove(("wifi_pass_" + String(index)).c_str());
  }
  for (uint8_t index = 0; index < wifiSavedCount_ && index < 5; ++index) {
    preferences.putString(("wifi_ssid_" + String(index)).c_str(),
                          wifiSavedSsid_[index]);
    preferences.putString(("wifi_pass_" + String(index)).c_str(),
                          wifiSavedPassword_[index]);
  }
}

bool FireOS::allButtonsHeldAtBoot() const {
  return digitalRead(kButtonPins[0]) == LOW &&
         digitalRead(kButtonPins[1]) == LOW && digitalRead(kButtonPins[2]) == LOW;
}

bool FireOS::backendCommandUnexpired(uint32_t expiresAt) const {
  if (expiresAt == 0) return false;
  uint32_t now = 0;
  if (backendServerTime_ > 0) {
    now = backendServerTime_ + (millis() - backendServerSeenAt_) / 1000UL;
  } else {
    const time_t localNow = time(nullptr);
    if (localNow < 1577836800) return false;
    now = static_cast<uint32_t>(localNow);
  }
  return expiresAt > now;
}

void FireOS::pollButtons() {
  const uint32_t now = millis();
  for (uint8_t index = 0; index < kButtonCount; ++index) {
    if (buttons_[index].clickPending &&
        now - buttons_[index].lastClickAt > kDoubleClickWindowMs) {
      buttons_[index].clickPending = false;
      onButton(index, false);
    }
    const bool pressed = digitalRead(kButtonPins[index]) == LOW;
    if (pressed != buttons_[index].rawPressed) {
      buttons_[index].rawPressed = pressed;
      buttons_[index].rawChangedAt = now;
    }
    if (buttons_[index].rawPressed != buttons_[index].down &&
        now - buttons_[index].rawChangedAt >= kButtonDebounceMs) {
      buttons_[index].down = buttons_[index].rawPressed;
      if (buttons_[index].down) {
        buttons_[index].longTriggered = false;
        buttons_[index].started = now;
        buttons_[index].wakeOnly = displayPowerState_ != 0;
        if (displayPowerState_ != 0) {
          wakeDisplay();
        } else {
          lastActivity_ = now;
        }
      } else {
        const bool shortPress = !buttons_[index].longTriggered &&
                                !buttons_[index].wakeOnly;
        buttons_[index].wakeOnly = false;
        if (shortPress) {
          if (doubleClickAction_[index] == 0) {
            onButton(index, false);
          } else if (buttons_[index].clickPending &&
                     now - buttons_[index].lastClickAt <=
                         kDoubleClickWindowMs) {
            buttons_[index].clickPending = false;
            onDoubleClick(index);
          } else {
            buttons_[index].clickPending = true;
            buttons_[index].lastClickAt = now;
          }
        }
      }
    }
    if (buttons_[index].down &&
        !buttons_[index].wakeOnly && !buttons_[index].longTriggered &&
        now - buttons_[index].started >= kLongPressMs) {
      buttons_[index].longTriggered = true;
      buttons_[index].clickPending = false;
      lastActivity_ = now;
      onButton(index, true);
    }
  }
}

void FireOS::onButton(uint8_t index, bool longPress) {
  redrawRequested_ = true;
  const bool conversationAudio = screen_ == Screen::AiDeveloper && index == 1;
  const bool debugAudio = screen_ == Screen::Debug && detailIndex_ == 4;
  if (!conversationAudio && !debugAudio && !aiAudioOutputActive_)
    playButtonSound(index, longPress);
  if (longPress) {
    if (screen_ == Screen::FileExplorer && index == 1 && !sdPreview_ &&
        !sdNameEditor_ && !sdDeleteConfirm_) {
      sdActionMenu_ = true;
      sdActionIndex_ = 0;
      return;
    }
    if (screen_ == Screen::Bluetooth && bluetoothScanDialog_) {
#ifdef FIRE_OS_BLE
      if (bluetoothScanInProgress_ && bluetoothScan) bluetoothScan->stop();
#endif
      bluetoothScanInProgress_ = false;
      bluetoothScanDialog_ = false;
      bluetoothUnknownDialog_ = false;
      return;
    }
    if (index == 0) {
      home();
    } else if (index == 1 && screen_ != Screen::QuickSettings) {
      openQuickSettings();
    } else if (index == 2) {
      if (screen_ == Screen::Settings) {
        goToBootApp();
      } else {
        back();
      }
    }
    return;
  }

  if (screen_ == Screen::DateTime) {
    handleDateTimeButton(index);
    return;
  }
  if (screen_ == Screen::DisplaySound) {
    handleDisplaySoundButton(index);
    return;
  }
  if (screen_ == Screen::Boot) {
    handleBootButton(index);
    return;
  }
  if (screen_ == Screen::Help) {
    handleHelpButton(index);
    return;
  }
  if (screen_ == Screen::AppsSettings) {
    handleAppsSettingsButton(index);
    return;
  }
  if (screen_ == Screen::AiDeveloper) {
    handleAiDeveloperButton(index);
    return;
  }
  if (screen_ == Screen::LuaApp) {
    const char* buttonName = index == 0 ? "A" : index == 1 ? "B" : "C";
    if (luaAppActive_ && luaRuntime_ && !luaRuntime_->button(buttonName, "pressed")) {
      const String error = luaRuntime_->lastError();
      stopLuaApp(error);
    }
    return;
  }
  if (screen_ == Screen::AiApi) {
    handleAiApiButton(index);
    return;
  }
  if (screen_ == Screen::Wifi) {
    handleWifiButton(index);
    return;
  }
  if (screen_ == Screen::Bluetooth) {
    if (bluetoothScanDialog_) {
      handleBluetoothScanDialogButton(index);
      return;
    }
    if (bluetoothSavedDialog_) {
      handleBluetoothSavedDialogButton(index);
      return;
    }
    handleBluetoothButton(index);
    return;
  }
  if (screen_ == Screen::FileExplorer) {
    handleFileExplorerButton(index);
    return;
  }
  if (screen_ == Screen::Firmware) {
    handleFirmwareButton(index);
    return;
  }
  if (screen_ == Screen::MainMenuSettings || screen_ == Screen::Shortcuts) {
    handleAppsSettingsButton(index);
    return;
  }
  if (screen_ == Screen::QuickSettings) {
    handleQuickButton(index);
    return;
  }
  if (screen_ == Screen::FactoryReset) {
    handleFactoryResetButton(index);
    return;
  }
  if (screen_ == Screen::Power) {
    handlePowerButton(index);
    return;
  }
  if (screen_ == Screen::PowerActions) {
    handlePowerActionsButton(index);
    return;
  }
  if (screen_ == Screen::Debug) {
    // Debug is a five-page overview/test area. A/C browse pages, while B is
    // reserved for the active test on the current test page.
    constexpr uint8_t kDebugPageCount = 5;
    if (index == 0) {
      detailIndex_ = (detailIndex_ + kDebugPageCount - 1) % kDebugPageCount;
    } else if (index == 2) {
      detailIndex_ = (detailIndex_ + 1) % kDebugPageCount;
    } else if (index == 1 && detailIndex_ == 3) {
      debugRgbIndex_ = (debugRgbIndex_ + 1) % 7;
      const uint8_t colors[7][3] = {{0, 0, 0},       {255, 0, 0},
                                    {0, 180, 0},      {0, 80, 255},
                                    {255, 160, 0},   {180, 0, 255},
                                    {255, 255, 255}};
      const uint8_t* color = colors[debugRgbIndex_];
      writeRgbForDebug(color[0], color[1], color[2], debugRgbBrightness_);
    } else if (index == 1 && detailIndex_ == 4) {
      if (debugMicRecording_) {
        stopDebugMicTest();
      } else if (debugMicPlaying_) {
        M5.Speaker.stop();
        debugMicPlaying_ = false;
        debugMicStatus_ = "Playback stopped";
      } else {
        startDebugMicTest();
      }
    }
    return;
  }

  if (index == 0) {
    if (screen_ == Screen::Main) {
      const uint8_t nextIndex = nextVisibleMain(mainIndex_, -1);
      startMainSlide(nextIndex, 1);
    } else if (screen_ == Screen::Apps) {
      handleAppsButton(index);
    } else if (screen_ == Screen::Placeholder || screen_ == Screen::Debug ||
               screen_ == Screen::SystemInfo) {
      // Short left press never means Home. Home is long left only.
    } else if (screen_ == Screen::Settings) {
      settingsIndex_ = (settingsIndex_ + kSettingsCount - 1) % kSettingsCount;
    }
  } else if (index == 2) {
    if (screen_ == Screen::Main) {
      const uint8_t nextIndex = nextVisibleMain(mainIndex_, 1);
      startMainSlide(nextIndex, -1);
    } else if (screen_ == Screen::Apps) {
      handleAppsButton(index);
    } else if (screen_ == Screen::Placeholder || screen_ == Screen::Debug ||
               screen_ == Screen::SystemInfo) {
      back();
    } else if (screen_ == Screen::Settings) {
      settingsIndex_ = (settingsIndex_ + 1) % kSettingsCount;
    }
  } else if (index == 1) {
    if (screen_ == Screen::Main) {
      if (mainIndex_ == 0) {
        open(Screen::Apps);
      } else if (mainIndex_ == 1) {
        open(Screen::Settings);
      } else if (mainIndex_ == 2) {
        powerIndex_ = 1;
        powerEditing_ = false;
        open(Screen::Power);
      } else if (mainIndex_ == 3) {
        open(Screen::FileExplorer);
      } else if (mainIndex_ >= kSystemMainCount) {
        const uint8_t appIndex = mainIndex_ - kSystemMainCount;
        if (appIndex < luaAppCount_)
          startLuaApp(luaAppPaths_[appIndex], luaAppDisplayNames_[appIndex]);
      } else {
        open(Screen::AiDeveloper);
      }
    } else if (screen_ == Screen::Apps) {
      handleAppsButton(index);
    } else if (screen_ == Screen::Settings) {
      if (settingsIndex_ == 0) {
        openDateTimeEditor();
      } else if (settingsIndex_ == 1) {
        detailIndex_ = 0;
        detailEditing_ = false;
        open(Screen::DisplaySound);
      } else if (settingsIndex_ == 2) {
        detailIndex_ = 0;
        open(Screen::Wifi);
      } else if (settingsIndex_ == 3) {
        detailIndex_ = 0;
        open(Screen::Bluetooth);
      } else if (settingsIndex_ == 4) {
        open(Screen::FileExplorer);
      } else if (settingsIndex_ == 5) {
        detailIndex_ = 0;
        detailEditing_ = false;
        open(Screen::Boot);
      } else if (settingsIndex_ == 6) {
        firmwareSelection_ = 0;
        firmwareOffset_ = 0;
        firmwareMessage_ = "Scanning /firmware...";
        firmwareScanPending_ = true;
        open(Screen::Firmware);
      } else if (settingsIndex_ == 7) {
        detailIndex_ = 0;
        open(Screen::MainMenuSettings);
      } else if (settingsIndex_ == 8) {
        detailIndex_ = 0;
        open(Screen::Shortcuts);
      } else if (settingsIndex_ == 9) {
        detailIndex_ = 0;
        open(Screen::AppsSettings);
      } else if (settingsIndex_ == 10) {
        detailIndex_ = 0;
        open(Screen::Debug);
      } else if (settingsIndex_ == 11) {
        open(Screen::SystemInfo);
      } else if (settingsIndex_ == 12) {
        helpPage_ = 0;
        open(Screen::Help);
      } else if (settingsIndex_ == 14) {
        open(Screen::AiApi);
      } else if (settingsIndex_ == 15) {
        powerIndex_ = 0;
        powerEditing_ = false;
        open(Screen::Power);
      } else if (settingsIndex_ == 16) {
        back();
      } else if (settingsIndex_ == 13) {
        factoryResetArmed_ = false;
        open(Screen::FactoryReset);
      } else {
        placeholderIndex_ = settingsIndex_;
        open(Screen::Placeholder);
      }
    } else if (screen_ == Screen::Placeholder || screen_ == Screen::Debug ||
               screen_ == Screen::SystemInfo) {
      // B is reserved for select/action. Back is always long A.
    }
  }
}

void FireOS::onDoubleClick(uint8_t index) {
  redrawRequested_ = true;
  if (screen_ == Screen::Debug && index == 1 && detailIndex_ == 3) {
    static constexpr uint8_t kBrightness[] = {40, 80, 120, 180, 255};
    uint8_t current = 0;
    while (current + 1 < sizeof(kBrightness) / sizeof(kBrightness[0]) &&
           kBrightness[current] != debugRgbBrightness_)
      ++current;
    debugRgbBrightness_ =
        kBrightness[(current + 1) % (sizeof(kBrightness) / sizeof(kBrightness[0]))];
    const uint8_t colors[7][3] = {{0, 0, 0},       {255, 0, 0},
                                  {0, 180, 0},      {0, 80, 255},
                                  {255, 160, 0},   {180, 0, 255},
                                  {255, 255, 255}};
    const uint8_t* color = colors[debugRgbIndex_];
    writeRgbForDebug(color[0], color[1], color[2], debugRgbBrightness_);
    return;
  }
  if (screen_ == Screen::Debug && index == 1 && detailIndex_ == 4) {
    if (debugMicRecording_)
      stopDebugMicTest();
    else if (debugMicPlaying_) {
      M5.Speaker.stop();
      debugMicPlaying_ = false;
      debugMicStatus_ = "Playback stopped";
    } else
      startDebugMicTest();
    return;
  }
  playButtonSound(index, false);
  if (doubleClickAction_[index] >= kBaseDoubleClickActionCount) {
    const uint8_t appIndex = doubleClickAction_[index] -
                             kBaseDoubleClickActionCount;
    if (appIndex < luaAppCount_ && luaMenuSelected_[appIndex]) {
      startLuaApp(luaAppPaths_[appIndex], luaAppDisplayNames_[appIndex]);
    } else {
      doubleClickAction_[index] = 0;
      doubleClickLuaAppId_[index] = "";
      saveSettings();
    }
    return;
  }
  switch (doubleClickAction_[index]) {
    case 1:
      open(Screen::Apps);
      break;
    case 2:
      powerIndex_ = 0;
      powerEditing_ = false;
      open(Screen::Power);
      break;
    case 3:
      open(Screen::Settings);
      break;
    case 4:
      detailIndex_ = 0;
      detailEditing_ = false;
      open(Screen::DisplaySound);
      break;
    case 5:
      wifiIndex_ = 0;
      open(Screen::Wifi);
      break;
    case 6:
      bluetoothIndex_ = 0;
      open(Screen::Bluetooth);
      break;
    case 7:
      detailIndex_ = 0;
      open(Screen::MainMenuSettings);
      break;
    case 8:
      open(Screen::SystemInfo);
      break;
    default:
      break;
  }
}

void FireOS::playButtonSound(uint8_t index, bool longPress) {
  if (!buttonSoundsEnabled_ || !M5.Speaker.isEnabled()) return;
  if (screen_ == Screen::AiDeveloper &&
      (aiAudioCaptureActive_ || aiAudioOutputActive_ || aiWorkflowState_ > 0))
    return;
  const float frequency = index == 1 ? 740.0f : 560.0f;
  M5.Speaker.tone(frequency, longPress ? 28 : 18, 0, true);
}

void FireOS::open(Screen screen) {
  if (screen_ == Screen::Debug && screen != Screen::Debug) cleanupDebugTests();
  // Any OS navigation from a running Lua app is an app exit, including
  // configurable double-click shortcuts. Home/Back use their own path, but
  // this guard closes the remaining routes through one cleanup boundary.
  if (screen_ == Screen::LuaApp && screen != Screen::LuaApp)
    stopLuaApp("os_navigation");
  if (screen_ == Screen::Bluetooth && screen != Screen::Bluetooth) {
    closeBluetoothSettings();
  }
  previousScreen_ = screen_;
  screen_ = screen;
  if (screen == Screen::Bluetooth) {
    if (bluetoothMode_ == 2) {
      bluetoothEnabled_ = false;
      bluetoothStatus_ = "Bluetooth Off";
    } else {
      bluetoothEnabled_ = bluetoothRadioReady;
      bluetoothBootInitPending_ = !bluetoothRadioReady;
      bluetoothStatus_ = bluetoothRadioReady ? "BLE ready" : "Starting BLE...";
    }
  }
  if (screen == Screen::Apps) {
    externalAppSelection_ = 0;
    externalAppOffset_ = 0;
    externalAppMessage_ = "";
    externalAppCount_ = 0;
    luaAppCount_ = 0;
    externalAppMessage_ = "Scanning apps...";
    appScanPending_ = true;
  }
  if (screen == Screen::AppsSettings) {
    externalAppSelection_ = 0;
    externalAppOffset_ = 0;
    externalAppMessage_ = "";
    appManagerActionMenu_ = false;
    appManagerActionIndex_ = 0;
    appManagerDeleteConfirm_ = false;
    appManagerDeleteMode_ = 0;
    appManagerDeleteWaiting_ = false;
    appManagerVersionDialog_ = false;
    managerSelection_ = 0;
    managerOffset_ = 0;
    managerItemCount_ = 0;
    managerStatus_ = "Scanning apps...";
    backendAppCount_ = 0;
    backendCatalogRequested_ = false;
    backendCatalogLoading_ = false;
    backendCatalogNextOffset_ = 0;
    externalAppCount_ = 0;
    luaAppCount_ = 0;
    externalAppMessage_ = "Scanning apps...";
    appScanPending_ = true;
  }
  if (screen == Screen::AiDeveloper) {
    aiProjectPickerActive_ = true;
    aiProjectSelection_ = 0;
    aiProjectOffset_ = 0;
    aiVoiceTestMode_ = false;
    aiVoiceTestPlaybackActive_ = false;
    aiProjectId_ = "";
    aiProjectName_ = "New app";
    scanLuaApps();
    if (backendClient_) backendClient_->setProjectId("");
    aiDeveloperMode_ = 0;
    aiWorkflowState_ = 0;
    aiBuildProgress_ = 0;
    aiWorkflowStarted_ = millis();
    aiRestPhase_ = 0;
    aiRestPhaseStarted_ = millis();
    aiRestPhaseDuration_ = 30000 + (esp_random() % 30001);
    aiTurnId_ = "";
    aiProposalId_ = "";
    aiPackageId_ = "";
    aiInstallId_ = "";
    aiAssistantText_ = "";
    aiWorkflowText_ = "";
  }
  if (screen == Screen::AiApi) {
    wifiIndex_ = 0;
  }
  if (screen == Screen::FileExplorer) {
    sdPath_ = "/";
    sdSelection_ = 0;
    sdOffset_ = 0;
    sdActionMenu_ = false;
    sdDeleteConfirm_ = false;
    sdNameEditor_ = false;
    sdPreview_ = false;
    sdImagePreview_ = false;
    sdImageRendered_ = false;
    releaseSdImageBuffer();
    sdMessage_.clear();
    sdEntryCount_ = 0;
    sdMessage_ = "Opening SD...";
    fileExplorerScanPending_ = true;
  }
  if (screen == Screen::Firmware) {
    firmwareSelection_ = 0;
    firmwareOffset_ = 0;
    firmwareCount_ = 0;
    firmwareGithubDialog_ = false;
    firmwareSdDialog_ = false;
    firmwareGithubOverwriteConfirm_ = false;
    firmwareGithubPendingIndex_ = 0;
    firmwareGithubSelection_ = 0;
    firmwareGithubOffset_ = 0;
    firmwareInstallConfirm_ = false;
    firmwareInstallPending_ = false;
    firmwareMessage_ = "Scanning /firmware...";
    firmwareScanPending_ = true;
  }
}

uint8_t FireOS::visibleMainCount() const {
  uint8_t count = 0;
  for (uint8_t index = 0; index < kSystemMainCount; ++index) {
    if (mainVisible_[index]) ++count;
  }
  for (uint8_t index = 0; index < luaAppCount_; ++index)
    if (luaMenuSelected_[index]) ++count;
  return count;
}

uint8_t FireOS::mainItemAtPosition(uint8_t position) const {
  uint8_t visible = 0;
  for (uint8_t index = 0; index < kSystemMainCount; ++index) {
    if (!mainVisible_[index]) continue;
    if (visible++ == position) return index;
  }
  for (uint8_t index = 0; index < luaAppCount_; ++index) {
    if (!luaMenuSelected_[index]) continue;
    if (visible++ == position) return kSystemMainCount + index;
  }
  return 1;  // Settings remains the recovery fallback.
}

uint8_t FireOS::nextVisibleMain(uint8_t current, int8_t direction) const {
  const uint8_t count = visibleMainCount();
  if (count == 0) return 1;
  uint8_t position = 0;
  for (uint8_t index = 0; index < count; ++index) {
    if (mainItemAtPosition(index) == current) {
      position = index;
      break;
    }
  }
  position = static_cast<uint8_t>((position + count + direction) % count);
  return mainItemAtPosition(position);
}

void FireOS::startMainSlide(uint8_t nextIndex, int8_t direction) {
  if (carouselAnimating_) {
    carouselQueuedDirection_ = direction;
    return;
  }
  if (nextIndex == mainIndex_) return;
  carouselFromIndex_ = mainIndex_;
  carouselToIndex_ = nextIndex;
  carouselDirection_ = direction;
  carouselOffset_ = 0;
  carouselLastStepAt_ = millis();
  carouselQueuedDirection_ = 0;
  carouselAnimating_ = true;
  mainIndex_ = nextIndex;
}

void FireOS::back() {
  if (screen_ == Screen::Main) return;
  if (screen_ == Screen::Debug) cleanupDebugTests();
  if (screen_ == Screen::AiDeveloper &&
      (aiAudioCaptureActive_ || aiAudioOutputActive_ ||
       aiVoiceTestPlaybackActive_)) {
    cancelConversationTurn("READY", false);
  }
  if (screen_ == Screen::LuaApp) stopLuaApp("back");
  if (screen_ == Screen::Bluetooth) closeBluetoothSettings();
  screen_ = previousScreen_;
}

void FireOS::home() {
  if (screen_ == Screen::Debug) cleanupDebugTests();
  if (screen_ == Screen::AiDeveloper &&
      (aiAudioCaptureActive_ || aiAudioOutputActive_ ||
       aiVoiceTestPlaybackActive_)) {
    cancelConversationTurn("READY", false);
  }
  if (screen_ == Screen::LuaApp) stopLuaApp("home");
  goToBootApp();
}

void FireOS::goToBootApp() {
  if (screen_ == Screen::Debug) cleanupDebugTests();
  if (screen_ == Screen::Bluetooth) closeBluetoothSettings();
  // The current Boot setting is Default. Keep this single routing point so a
  // future installed-app boot target cannot create a second Home behavior.
  screen_ = Screen::Main;
  mainIndex_ = mainItemAtPosition(0);
  carouselAnimating_ = false;
  carouselOffset_ = 0;
  carouselLastStepAt_ = 0;
  carouselQueuedDirection_ = 0;
}

void FireOS::openQuickSettings() {
  if (screen_ == Screen::Debug) cleanupDebugTests();
  if (screen_ == Screen::Bluetooth) closeBluetoothSettings();
  previousScreen_ = screen_;
  quickIndex_ = 0;
  quickEditing_ = false;
  screen_ = Screen::QuickSettings;
}

void FireOS::openDateTimeEditor() {
  tm local{};
  const time_t now = time(nullptr);
  localtime_r(&now, &local);
  editYear_ = local.tm_year + 1900;
  editMonth_ = local.tm_mon + 1;
  editDay_ = local.tm_mday;
  editHour_ = local.tm_hour;
  editMinute_ = local.tm_min;
  editTimezone_ = dateTime_.timezoneIndex();
  editDstAuto_ = dateTime_.dstAuto();
  dateField_ = 0;
  dateEditing_ = false;
  open(Screen::DateTime);
}

void FireOS::handleDateTimeButton(uint8_t index) {
  if (dateEditing_) {
    if (index == 0) {
      adjustDateField(-1);
    } else if (index == 2) {
      adjustDateField(1);
    } else {
      dateEditing_ = false;
    }
    return;
  }

  if (index == 0) {
    dateField_ = (dateField_ + kDateFieldCount - 1) % kDateFieldCount;
  } else if (index == 2) {
    dateField_ = (dateField_ + 1) % kDateFieldCount;
  } else {
    if (dateField_ == 0) {
      wifiTimeSync_ = !wifiTimeSync_;
      saveSettings();
      timeSyncPending_ = false;
      timeSyncConfigured_ = false;
      timeSyncStatus_ = wifiTimeSync_ ? "Wi-Fi sync on; use Sync now"
                                      : "Wi-Fi sync off";
    } else if (dateField_ == 1) {
      if (wifiTimeSync_) {
        startTimeSync();
      } else {
        timeSyncStatus_ = "Enable Wi-Fi sync first";
      }
    } else if (dateField_ <= 8) {
      dateEditing_ = true;
    } else if (dateField_ == 9) {
      commitDateTime();
      screen_ = Screen::Settings;
    } else {
      screen_ = Screen::Settings;
    }
  }
}

void FireOS::handleDisplaySoundButton(uint8_t index) {
  if (detailEditing_) {
    if (index == 0 || index == 2) {
      const int8_t direction = index == 0 ? -1 : 1;
      if (detailIndex_ == 0) {
        brightnessStep_ = (brightnessStep_ + kBrightnessStepCount + direction) %
                          kBrightnessStepCount;
        brightness_ = kBrightnessValues[brightnessStep_];
        M5.Display.setBrightness(brightness_);
      } else if (detailIndex_ == 1) {
        volumeStep_ = (volumeStep_ + kVolumeStepCount + direction) %
                      kVolumeStepCount;
        volume_ = volumeValue(volumeStep_);
        M5.Speaker.setVolume(speakerVolumeValue(volume_));
      } else if (detailIndex_ == 2) {
        dimOption_ = (dimOption_ + kDurationCount + direction) % kDurationCount;
      } else if (detailIndex_ == 3) {
        screenOffOption_ = (screenOffOption_ + kDurationCount + direction) %
                           kDurationCount;
      }
      saveSettings();
    } else if (index == 1) {
      detailEditing_ = false;
      saveSettings();
    }
    return;
  }

  constexpr uint8_t kCount = 6;
  if (index == 0) {
    detailIndex_ = (detailIndex_ + kCount - 1) % kCount;
  } else if (index == 2) {
    detailIndex_ = (detailIndex_ + 1) % kCount;
  } else {
    if (detailIndex_ <= 3) {
      detailEditing_ = true;
    } else if (detailIndex_ == 4) {
      buttonSoundsEnabled_ = !buttonSoundsEnabled_;
      saveSettings();
    } else {
      back();
    }
  }
}

void FireOS::handleBootButton(uint8_t index) {
  if (bootAppPicker_) {
    const uint8_t appCount = externalAppCount_ + luaAppCount_;
    const uint8_t itemCount = appCount + 1;
    if (index == 0) {
      bootAppSelection_ = (bootAppSelection_ + itemCount - 1) % itemCount;
    } else if (index == 2) {
      bootAppSelection_ = (bootAppSelection_ + 1) % itemCount;
    } else {
      if (bootAppSelection_ == 0) {
        selectedBootAppPath_ = "";
      } else if (bootAppSelection_ - 1 < externalAppCount_) {
        selectedBootAppPath_ = externalAppPaths_[bootAppSelection_ - 1];
      } else {
        selectedBootAppPath_ =
            luaAppPaths_[bootAppSelection_ - 1 - externalAppCount_];
      }
      saveSettings();
      bootAppPicker_ = false;
    }
    if (bootAppSelection_ < bootAppOffset_) bootAppOffset_ = bootAppSelection_;
    if (bootAppSelection_ >= bootAppOffset_ + 6)
      bootAppOffset_ = bootAppSelection_ - 5;
    return;
  }
  constexpr uint8_t kCount = 4;
  if (index == 0) {
    detailIndex_ = (detailIndex_ + kCount - 1) % kCount;
  } else if (index == 2) {
    detailIndex_ = (detailIndex_ + 1) % kCount;
  } else if (detailIndex_ == 1) {
    bootRgbPulse_ = !bootRgbPulse_;
    saveSettings();
  } else if (detailIndex_ == 2) {
    bootMelody_ = !bootMelody_;
    saveSettings();
  } else if (detailIndex_ == 3) {
    back();
  } else if (detailIndex_ == 0) {
    scanExternalApps();
    scanLuaApps();
    bootAppSelection_ = selectedBootAppPath_.length() == 0 ? 0 : 1;
    for (uint8_t i = 0; i < externalAppCount_; ++i) {
      if (externalAppPaths_[i] == selectedBootAppPath_) {
        bootAppSelection_ = i + 1;
        break;
      }
    }
    if (bootAppSelection_ == 1 && selectedBootAppPath_.endsWith("/main.lua")) {
      for (uint8_t i = 0; i < luaAppCount_; ++i) {
        if (luaAppPaths_[i] == selectedBootAppPath_) {
          bootAppSelection_ = externalAppCount_ + i + 1;
          break;
        }
      }
    }
    bootAppOffset_ = bootAppSelection_ > 5 ? bootAppSelection_ - 5 : 0;
    bootAppPicker_ = true;
  }
}

void FireOS::handleFirmwareButton(uint8_t index) {
  if (firmwareGithubOverwriteConfirm_) {
    if (index == 0 || index == 2) {
      firmwareGithubOverwriteConfirm_ = false;
      firmwareMessage_ = "Download cancelled";
    } else if (githubFirmware_ &&
               githubFirmware_->startDownload(firmwareGithubPendingIndex_,
                                               true)) {
      firmwareGithubOverwriteConfirm_ = false;
      firmwareGithubDialog_ = false;
      firmwareMessage_ = "Downloading and overwriting...";
    } else {
      firmwareMessage_ = "GitHub download unavailable";
    }
    return;
  }
  if (firmwareGithubDialog_) {
    const uint8_t remoteCount = githubFirmware_ ? githubFirmware_->entryCount() : 0;
    const uint8_t itemCount = remoteCount + 1;
    if (index == 0) {
      firmwareGithubSelection_ =
          (firmwareGithubSelection_ + itemCount - 1) % itemCount;
    } else if (index == 2) {
      firmwareGithubSelection_ =
          (firmwareGithubSelection_ + 1) % itemCount;
    } else if (firmwareGithubSelection_ < remoteCount) {
      const String name = githubFirmware_->entryName(firmwareGithubSelection_);
      if (sdReady_ && SD.exists("/firmware/" + name)) {
        firmwareGithubPendingIndex_ = firmwareGithubSelection_;
        firmwareGithubOverwriteConfirm_ = true;
        firmwareMessage_ = "File exists: overwrite or cancel";
      } else if (githubFirmware_ &&
                 githubFirmware_->startDownload(firmwareGithubSelection_)) {
        firmwareGithubDialog_ = false;
        firmwareMessage_ = "Downloading from GitHub...";
      } else {
        firmwareMessage_ = "GitHub download unavailable";
      }
    } else {
      firmwareGithubDialog_ = false;
      firmwareMessage_ = "GitHub list closed";
    }
    if (firmwareGithubSelection_ < firmwareGithubOffset_)
      firmwareGithubOffset_ = firmwareGithubSelection_;
    if (firmwareGithubSelection_ >= firmwareGithubOffset_ + 5)
      firmwareGithubOffset_ = firmwareGithubSelection_ - 4;
    return;
  }
  if (firmwareSdDialog_) {
    const uint8_t itemCount = firmwareCount_ + 1;
    if (index == 0) {
      firmwareSelection_ = (firmwareSelection_ + itemCount - 1) % itemCount;
    } else if (index == 2) {
      firmwareSelection_ = (firmwareSelection_ + 1) % itemCount;
    } else if (firmwareSelection_ < firmwareCount_) {
      if (firmwareStorage_ && firmwareStorage_->busy()) {
        firmwareMessage_ = "Wait for firmware download";
      } else {
        firmwareInstallConfirm_ = true;
        firmwareMessage_ = "Confirm firmware flash";
      }
    } else {
      firmwareSdDialog_ = false;
      firmwareSelection_ = 1;
      firmwareOffset_ = 0;
      firmwareMessage_ = "SD firmware list closed";
    }
    if (firmwareSelection_ < firmwareOffset_)
      firmwareOffset_ = firmwareSelection_;
    if (firmwareSelection_ >= firmwareOffset_ + 5)
      firmwareOffset_ = firmwareSelection_ - 4;
    return;
  }
  if (firmwareInstallConfirm_) {
    if (index == 0 || index == 2) {
      firmwareInstallConfirm_ = false;
      firmwareMessage_ = "Flash cancelled";
    } else {
      firmwareInstallConfirm_ = false;
      firmwareInstallPending_ = true;
      firmwareMessage_ = "Flashing selected firmware...";
    }
    return;
  }
  const uint8_t itemCount = 3;  // GitHub files, SD files, Back.
  if (index == 0) {
    firmwareSelection_ = (firmwareSelection_ + itemCount - 1) % itemCount;
  } else if (index == 2) {
    firmwareSelection_ = (firmwareSelection_ + 1) % itemCount;
  } else if (firmwareSelection_ == 0) {
    firmwareMessage_ = "Updating GitHub list...";
    firmwareGithubDialog_ = true;
    firmwareGithubSelection_ = 0;
    firmwareGithubOffset_ = 0;
    if (githubFirmware_) githubFirmware_->startManifest();
  } else if (firmwareSelection_ == 1) {
    firmwareMessage_ = "Scanning /firmware...";
    firmwareSelection_ = 0;
    firmwareOffset_ = 0;
    firmwareSdDialog_ = true;
    firmwareScanPending_ = true;
  } else {
    back();
  }
}

void FireOS::playBootRgbPulse() {
  struct BootColor {
    uint8_t red;
    uint8_t green;
    uint8_t blue;
  };
  const BootColor colors[] = {{255, 0, 0}, {0, 90, 255}, {0, 255, 40},
                              {255, 80, 0}};
  const bool playMelody = bootMelody_ && M5.Speaker.isEnabled();
  const uint32_t melodyNotesAt[] = {0, 80, 160};
  const float melodyNotes[] = {523.251f, 659.255f, 783.991f};
  uint8_t nextMelodyNote = 0;
  const uint32_t pulseStarted = millis();
  auto updateMelody = [&]() {
    if (!playMelody) return;
    const uint32_t elapsed = millis() - pulseStarted;
    while (nextMelodyNote < 3 && elapsed >= melodyNotesAt[nextMelodyNote]) {
      M5.Speaker.tone(melodyNotes[nextMelodyNote],
                      nextMelodyNote == 2 ? 100 : 70);
      ++nextMelodyNote;
    }
  };
  updateMelody();
  for (uint8_t color = 0; color < 4; ++color) {
    for (int level = 0; level <= 255; level += 51) {
      M5.Led.setBrightness(static_cast<uint8_t>(level));
      M5.Led.setAllColor(colors[color].red, colors[color].green,
                         colors[color].blue);
      M5.Led.display();
      delay(42);
      updateMelody();
    }
    for (int level = 204; level >= 0; level -= 51) {
      M5.Led.setBrightness(static_cast<uint8_t>(level));
      M5.Led.display();
      delay(42);
      updateMelody();
    }
  }
  M5.Led.setBrightness(0);
  M5.Led.setAllColor(0, 0, 0);
  M5.Led.display();
}

void FireOS::playBootMelody() {
  if (!M5.Speaker.isEnabled()) return;
  M5.Speaker.tone(523.251f, 70);
  delay(80);
  M5.Speaker.tone(659.255f, 70);
  delay(80);
  M5.Speaker.tone(783.991f, 100);
  delay(110);
}

void FireOS::handleHelpButton(uint8_t index) {
  if (index == 0) {
    helpPage_ = (helpPage_ + 2) % 3;
  } else if (index == 2) {
    helpPage_ = (helpPage_ + 1) % 3;
  } else {
    back();
  }
}

void FireOS::handleAiDeveloperButton(uint8_t index) {
  if (aiProjectPickerActive_) {
    const uint8_t itemCount =
        luaAppCount_ + 4;  // Chat + Voice test + New + apps + Back.
    if (index == 0) {
      aiProjectSelection_ =
          (aiProjectSelection_ + itemCount - 1) % itemCount;
    } else if (index == 2) {
      aiProjectSelection_ = (aiProjectSelection_ + 1) % itemCount;
    } else if (aiProjectSelection_ == itemCount - 1) {
      back();
    } else {
      aiProjectPickerActive_ = false;
      if (aiProjectSelection_ == 0) {
        aiVoiceTestMode_ = false;
        aiConversationMode_ = 1;
        aiProjectId_ = "";
        aiProjectName_ = "Chat";
        if (backendClient_) {
          backendClient_->setConversationMode("chat");
          backendClient_->setProjectId("");
        }
      } else if (aiProjectSelection_ == 1) {
        aiVoiceTestMode_ = true;
        aiConversationMode_ = 1;
        aiProjectId_ = "";
        aiProjectName_ = "Voice test";
        if (backendClient_) {
          backendClient_->setProjectId("");
          backendClient_->setConversationMode("chat");
        }
      } else if (aiProjectSelection_ == 2) {
        aiVoiceTestMode_ = false;
        aiConversationMode_ = 0;
        aiProjectId_ = "";
        aiProjectName_ = "New app";
        if (backendClient_) {
          backendClient_->setConversationMode("develop");
          backendClient_->setProjectId("");
          backendClient_->setAppMode("new");
        }
      } else {
        aiVoiceTestMode_ = false;
        aiConversationMode_ = 0;
        const uint8_t selected = aiProjectSelection_ - 3;
        const String source = luaAppPaths_[selected];
        const int slash = source.lastIndexOf('/');
        const String appFolder = slash > 0 ? source.substring(0, slash) : source;
        const String appId = sdBaseName(appFolder);
        aiProjectId_ = preferences.getString(
            compactPreferenceKey("pr_", appId).c_str(), appId);
        aiProjectName_ = luaAppNames_[selected];
      }
      if (backendClient_) {
        backendClient_->setProjectId(aiProjectId_);
        if (aiProjectId_.length() > 0) {
          backendClient_->setConversationMode("develop");
          backendClient_->setAppMode("update");
        }
      }
      aiWorkflowText_ = aiVoiceTestMode_
                            ? "VOICE TEST - PRESS B TO RECORD"
                        : aiProjectId_.length() > 0
                            ? "EDIT " + aiProjectName_
                            : "NEW APP";
      aiDeveloperMode_ = 0;
      aiWorkflowState_ = 0;
      aiAssistantText_ = "";
      redrawRequested_ = true;
    }
    if (aiProjectSelection_ < aiProjectOffset_)
      aiProjectOffset_ = aiProjectSelection_;
    if (aiProjectSelection_ >= aiProjectOffset_ + 5)
      aiProjectOffset_ = aiProjectSelection_ - 4;
    return;
  }
  if (index == 1) {
    if (aiWorkflowState_ == 0) {
      if (aiVoiceTestMode_ || (backendClient_ && backendClient_->sessionReady())) {
        if (!startAiRecording()) {
          aiWorkflowText_ = aiAudioError_.length() > 0
                                ? aiAudioError_
                                : "Microphone unavailable";
          aiDeveloperMode_ = 0;
          aiWorkflowState_ = 0;
        }
      } else if (!backendClient_ || !backendClient_->configured()) {
        aiWorkflowState_ = 1;
        aiDeveloperMode_ = 1;
        aiTurnId_ = "turn-" + String(millis(), HEX);
      } else {
        aiWorkflowText_ = backendClient_->connected()
                              ? "WAITING FOR SESSION"
                              : "BACKEND OFFLINE";
        aiDeveloperMode_ = 2;
      }
    } else if (aiWorkflowState_ == 1) {
      if (aiVoiceTestMode_ || (backendClient_ && backendClient_->sessionReady())) {
        finishAiRecording();
      } else if (!backendClient_ || !backendClient_->configured()) {
        aiWorkflowState_ = 2;
        aiDeveloperMode_ = 2;
        aiWorkflowStarted_ = millis();
      } else {
        aiWorkflowText_ = "BACKEND OFFLINE";
        aiWorkflowState_ = 0;
        aiDeveloperMode_ = 0;
      }
    } else if (aiWorkflowState_ == 2 || aiWorkflowState_ == 3 ||
               aiWorkflowState_ == 5) {
      cancelConversationTurn("READY - ADDING CONTEXT", true);
      if (aiVoiceTestMode_ || (backendClient_ && backendClient_->sessionReady()))
        startAiRecording();
    }
  } else if (index == 0 && aiWorkflowState_ == 3) {
    if (backendClient_ && backendClient_->connected() && aiProposalId_.length() > 0) {
      if (backendClient_->confirmBuild(aiProposalId_)) {
        aiWorkflowText_ = "SENDING BUILD";
        aiWorkflowState_ = 4;
        aiDeveloperMode_ = 2;
        aiBuildProgress_ = 0;
        aiWorkflowStarted_ = millis();
      } else {
        aiWorkflowText_ = "BUILD SEND FAILED - TRY AGAIN";
      }
    } else if (!backendClient_ || !backendClient_->configured()) {
      aiWorkflowState_ = 4;
      aiDeveloperMode_ = 2;
      aiBuildProgress_ = 0;
      aiWorkflowStarted_ = millis();
    }
  } else if (index == 2 &&
             (aiWorkflowState_ == 1 || aiWorkflowState_ == 2 ||
              aiWorkflowState_ == 3 || aiWorkflowState_ == 5)) {
    cancelConversationTurn("READY - PRESS B TO SPEAK", false);
    aiBuildProgress_ = 0;
    aiWorkflowStarted_ = millis();
  } else if (index == 0 && aiWorkflowState_ == 5) {
    if (backendClient_ && backendClient_->connected() && aiPackageId_.length() > 0) {
      if (backendClient_->confirmRun(aiPackageId_)) {
        aiWorkflowText_ = "SENDING RUN";
        aiWorkflowState_ = 6;
        aiDeveloperMode_ = 3;
        aiWorkflowStarted_ = millis();
      } else {
        aiWorkflowText_ = "RUN SEND FAILED - TRY AGAIN";
      }
    } else if (!backendClient_ || !backendClient_->configured()) {
      aiWorkflowState_ = 6;
      aiDeveloperMode_ = 3;
      aiWorkflowStarted_ = millis();
    }
  } else if (index == 0) {
    aiDeveloperMode_ = 0;
    aiWorkflowState_ = 0;
    aiBuildProgress_ = 0;
    aiWorkflowStarted_ = millis();
    aiRestPhase_ = 0;
    aiRestPhaseStarted_ = millis();
    aiRestPhaseDuration_ = 30000 + (esp_random() % 30001);
  }
}

bool FireOS::startAiRecording() {
#ifndef FIRE_AUDIO_CAPTURE_ENABLED
#define FIRE_AUDIO_CAPTURE_ENABLED 0
#endif
#if !FIRE_AUDIO_CAPTURE_ENABLED
  aiAudioError_ = "Audio capture unavailable in this build";
  return false;
#else
  const bool localVoiceTest = aiVoiceTestMode_;
  if ((!localVoiceTest &&
       (!backendClient_ || !backendClient_->sessionReady())) ||
      !M5.Mic.isEnabled() || aiAudioCaptureActive_) {
    aiAudioError_ = aiAudioCaptureActive_ ? "Recording already active"
                                 : "Microphone or backend unavailable";
    return false;
  }
  if (!stopAiAudioOutput()) {
    aiAudioError_ = "Audio is still playing";
    return false;
  }
  if (localVoiceTest) suspendVoiceTestRadio();
  if (!aiAudioBuffer_) {
    aiAudioBuffer_ = static_cast<uint8_t*>(ps_malloc(kAiAudioWavBytes));
    if (!aiAudioBuffer_) aiAudioBuffer_ = static_cast<uint8_t*>(malloc(kAiAudioWavBytes));
  }
  if (!aiAudioBuffer_) {
    aiAudioError_ = "Not enough memory for recording";
    if (localVoiceTest) restoreVoiceTestRadio();
    return false;
  }
  if (!fireStartMicCapture(
          reinterpret_cast<int16_t*>(aiAudioBuffer_ + 44), kAiAudioSamples,
          kAiAudioSampleRate)) {
    aiAudioError_ = "Microphone capture unavailable";
    if (localVoiceTest) restoreVoiceTestRadio();
    return false;
  }
  aiTurnId_ = localVoiceTest
                  ? ""
                  : "turn-" + String(millis(), HEX) + "-" +
                        String(esp_random(), HEX);
  aiAudioCaptureFinished_ = false;
  aiAudioStopSent_ = false;
  aiAudioUploadFinished_ = false;
  aiAudioUploadOk_ = false;
  aiAudioUploadStarted_ = false;
  aiAudioCaptureActive_ = true;
  aiAudioCapturedSamples_ = 0;
  aiAudioWavLength_ = 0;
  aiAudioCaptureStartedAt_ = millis();
  aiAudioCaptureElapsedMs_ = 0;
  aiAudioCaptureRms_ = 0;
  aiAudioCapturePeak_ = 0;
  aiAudioError_ = "";
  aiVoiceTestPlaybackActive_ = false;
  if (!localVoiceTest &&
      (!backendClient_ || !backendClient_->listenStart(aiTurnId_))) {
    cancelConversationTurn("Could not start backend recording", false);
    aiAudioError_ = "Could not start backend recording";
    return false;
  }
  aiWorkflowState_ = 1;
  aiDeveloperMode_ = 1;
  aiWorkflowText_ = localVoiceTest ? "VOICE TEST - LISTENING"
                                   : "LISTENING (15 SEC MAX)";
  aiWorkflowStarted_ = millis();
  return true;
#endif
}

void FireOS::suspendVoiceTestRadio() {
  if (aiVoiceTestRadioSuspended_) return;
  aiVoiceTestWifiWasEnabled_ = WiFi.getMode() != WIFI_OFF;
  if (aiVoiceTestWifiWasEnabled_) {
    WiFi.disconnect(false, false);
    WiFi.mode(WIFI_OFF);
    wifiConnectActive_ = false;
    wifiEnabled_ = false;
    wifiStatus_ = "Wi-Fi paused for Voice Test";
  }
  aiVoiceTestRadioSuspended_ = true;
}

void FireOS::restoreVoiceTestRadio() {
  if (!aiVoiceTestRadioSuspended_) return;
  const bool restoreWifi = aiVoiceTestWifiWasEnabled_ && wifiMode_ != 2;
  aiVoiceTestRadioSuspended_ = false;
  aiVoiceTestWifiWasEnabled_ = false;
  if (restoreWifi) {
    wifiEnabled_ = true;
    beginWifiConnection();
  }
}

bool FireOS::stopAiAudioOutput() {
  if (!aiAudioOutputActive_ && !aiAudioOutputBuffer_ &&
      !aiVoiceTestPlaybackActive_)
    return true;
  if (backendClient_) backendClient_->cancelAudioTransfer();
  M5.Speaker.stop();
  if (M5.Speaker.isPlaying()) return false;
  free(aiAudioOutputBuffer_);
  aiAudioOutputBuffer_ = nullptr;
  aiAudioOutputLength_ = 0;
  aiAudioOutputActive_ = false;
  aiAudioOutputId_ = "";
  aiAudioOutputTurnId_ = "";
  aiAudioDownloadPending_ = false;
  aiAudioDownloadStarted_ = false;
  aiAudioDownloadUrl_ = "";
  aiVoiceTestPlaybackActive_ = false;
  return true;
}

void FireOS::cancelConversationTurn(const String& reason, bool startNew) {
  const String oldTurn = aiTurnId_;
  fireStopMicCapture();
  fireReleaseMicCapture();
  if (backendClient_) backendClient_->cancelAudioTransfer();
  aiAudioCaptureActive_ = false;
  aiAudioCaptureFinished_ = false;
  aiAudioUploadFinished_ = false;
  aiAudioUploadOk_ = false;
  aiAudioUploadStarted_ = false;
  aiAudioDownloadPending_ = false;
  aiAudioDownloadStarted_ = false;
  aiAudioDownloadUrl_ = "";
  stopAiAudioOutput();
  if (aiVoiceTestMode_) restoreVoiceTestRadio();
  if (backendClient_ && backendClient_->sessionReady() && oldTurn.length() > 0)
    backendClient_->cancelTurn(oldTurn);
  aiTurnId_ = "";
  if (startNew) {
    aiProposalId_ = "";
    aiAssistantText_ = "";
    aiTranscriptText_ = "";
    aiWorkflowState_ = 0;
    aiDeveloperMode_ = 0;
    aiWorkflowText_ = "READY - PRESS B TO SPEAK";
  } else {
    aiWorkflowState_ = 0;
    aiDeveloperMode_ = 0;
    aiWorkflowText_ = reason.length() > 0 ? reason : "READY";
  }
}

void FireOS::finishAiRecording() {
  if (aiAudioStopSent_) return;
  aiAudioStopSent_ = true;
  fireStopMicCapture();
  if (aiVoiceTestMode_) {
    aiWorkflowState_ = 2;
    aiDeveloperMode_ = 2;
    aiWorkflowText_ = "PREPARING RECORDING";
    return;
  }
  if (!backendClient_ || !backendClient_->listenStop(aiTurnId_)) {
    aiAudioError_ = "Backend session not ready";
    aiWorkflowText_ = "SESSION LOST - TRY AGAIN";
    aiWorkflowState_ = 0;
    aiDeveloperMode_ = 0;
    return;
  }
  aiWorkflowState_ = 2;
  aiDeveloperMode_ = 2;
  aiWorkflowText_ = "PROCESSING AUDIO";
  aiWorkflowStarted_ = millis();
}

void FireOS::updateAiAudio() {
  if (aiAudioCaptureActive_) {
#if FIRE_AUDIO_CAPTURE_ENABLED
    const bool captureFailed = fireMicCaptureFailed();
    const bool captureRunning = fireMicCaptureRunning();
#else
    const bool captureFailed = true;
    const bool captureRunning = false;
#endif
    if (captureFailed) {
      cancelConversationTurn("MIC CAPTURE FAILED", false);
      aiAudioError_ = "MIC CAPTURE FAILED";
      aiWorkflowText_ = aiAudioError_;
    } else if (!captureRunning) {
        const size_t rawCapturedSamples = fireMicCapturedSamples();
        if (!fireReleaseMicCapture()) {
          aiAudioError_ = "MIC STOP TIMEOUT";
          aiWorkflowText_ = aiAudioError_;
          aiWorkflowState_ = 0;
          aiDeveloperMode_ = 0;
          restoreVoiceTestRadio();
          return;
        }
        aiAudioCaptureActive_ = false;
        aiAudioCaptureElapsedMs_ = millis() - aiAudioCaptureStartedAt_;
        aiAudioCapturedSamples_ = normalizePcmDuration(
            reinterpret_cast<int16_t*>(aiAudioBuffer_ + 44),
            rawCapturedSamples, aiAudioCaptureElapsedMs_, kAiAudioSampleRate,
            kAiAudioSamples);
        const uint32_t payloadBytes =
            aiAudioCapturedSamples_ * sizeof(int16_t);
        int32_t peak = 0;
        uint64_t squareSum = 0;
        const auto* pcm = reinterpret_cast<const int16_t*>(aiAudioBuffer_ + 44);
        for (size_t index = 0; index < aiAudioCapturedSamples_; ++index) {
          const int32_t value = pcm[index];
          peak = max<int32_t>(peak, value < 0 ? -value : value);
          squareSum += static_cast<uint64_t>(value) * static_cast<uint64_t>(value);
        }
        aiAudioCapturePeak_ = peak;
        aiAudioCaptureRms_ = aiAudioCapturedSamples_ == 0
                                 ? 0
                                 : static_cast<uint32_t>(sqrt(
                                       static_cast<double>(squareSum) /
                                       aiAudioCapturedSamples_));
        Serial.printf(
            "FIRE audio capture: raw=%u samples=%u elapsed=%ums peak=%ld wav=%u\n",
                      static_cast<unsigned>(rawCapturedSamples),
                      static_cast<unsigned>(aiAudioCapturedSamples_),
                      static_cast<unsigned>(aiAudioCaptureElapsedMs_),
                      static_cast<long>(peak),
                      static_cast<unsigned>(44 + payloadBytes));
        writeWavHeader(aiAudioBuffer_, payloadBytes, kAiAudioSampleRate);
        aiAudioWavLength_ = 44 + payloadBytes;
        aiAudioCaptureFinished_ = true;
        if (!aiAudioStopSent_) finishAiRecording();
        if (aiVoiceTestMode_) {
          const bool played =
              aiAudioCapturedSamples_ > 0 && M5.Speaker.isEnabled() &&
              M5.Speaker.playRaw(
                  reinterpret_cast<const int16_t*>(aiAudioBuffer_ + 44),
                  aiAudioCapturedSamples_, kAiAudioSampleRate, false, 1, 0,
                  true);
          if (played) {
            aiVoiceTestPlaybackActive_ = true;
            aiDeveloperMode_ = 3;
            aiWorkflowState_ = 2;
            aiWorkflowText_ = "PLAYING RECORDING";
          } else {
            aiAudioError_ = "VOICE PLAYBACK FAILED";
            aiWorkflowText_ = aiAudioError_;
            aiWorkflowState_ = 0;
            aiDeveloperMode_ = 0;
            restoreVoiceTestRadio();
          }
        } else {
          aiWorkflowText_ = "SENDING AUDIO";
          aiAudioUploadStarted_ =
              backendClient_ && backendClient_->beginAudioUpload(
                  aiTurnId_, aiAudioBuffer_, aiAudioWavLength_);
          if (!aiAudioUploadStarted_) {
            aiAudioUploadOk_ = false;
            aiAudioUploadFinished_ = true;
            aiAudioError_ = "Backend audio upload failed";
          }
        }
    }
  }
  if (aiAudioUploadStarted_ && backendClient_ &&
      backendClient_->audioTransferFinished()) {
    aiAudioUploadStarted_ = false;
    aiAudioUploadOk_ = backendClient_->audioTransferOk();
    aiAudioUploadFinished_ = true;
    if (!aiAudioUploadOk_) aiAudioError_ = "Backend audio upload failed";
  }
  if (aiAudioCaptureFinished_ && !aiAudioStopSent_) finishAiRecording();
  if (aiAudioUploadFinished_) {
    aiAudioUploadFinished_ = false;
    if (!aiAudioUploadOk_) {
      aiWorkflowText_ = "AUDIO SEND FAILED - TRY AGAIN";
      aiWorkflowState_ = 0;
      aiDeveloperMode_ = 0;
    } else {
      aiWorkflowText_ = "TRANSCRIBING";
    }
  }
}

void FireOS::failAiAudioPlayback(const String& audioId, const String& turnId,
                                  const String& errorCode,
                                  const String& message, const char* phase,
                                  bool releaseBuffer) {
  if (backendClient_ && audioId.length() > 0 && turnId.length() > 0) {
    backendClient_->audioPlaybackFailed(audioId, turnId, errorCode, message,
                                        audioDiagnosticsJson(phase));
  }
  if (releaseBuffer) {
    free(aiAudioOutputBuffer_);
    aiAudioOutputBuffer_ = nullptr;
    aiAudioOutputLength_ = 0;
    aiAudioDownloadPending_ = false;
    aiAudioDownloadStarted_ = false;
    aiAudioDownloadUrl_ = "";
    aiAudioOutputActive_ = false;
    aiAudioOutputId_ = "";
    aiAudioOutputTurnId_ = "";
  }
  aiAudioError_ = message;
  // Preserve the proposal/build confirmation state. Without a proposal the
  // user is returned to the normal B-to-speak state instead of being trapped
  // in workflowState=2 after an audio-only failure.
  aiWorkflowState_ = aiProposalId_.length() > 0 ? 3 : 0;
  aiDeveloperMode_ = aiProposalId_.length() > 0 ? 2 : 0;
  aiWorkflowText_ = aiProposalId_.length() > 0
                        ? "A BUILD / B SPEAK"
                        : "AUDIO ERROR - B SPEAK AGAIN";
}

void FireOS::updateAiAudioOutput() {
  if (aiVoiceTestPlaybackActive_) {
    if (M5.Speaker.isPlaying()) return;
    aiVoiceTestPlaybackActive_ = false;
    aiAudioCaptureFinished_ = false;
    aiWorkflowState_ = 0;
    aiDeveloperMode_ = 0;
    aiWorkflowText_ = "VOICE TEST - PRESS B TO RECORD";
    restoreVoiceTestRadio();
    return;
  }
  if (aiAudioDownloadPending_) {
    if (!backendClient_) {
      failAiAudioPlayback(aiAudioDownloadId_, aiAudioDownloadTurnId_,
                          "backend_unavailable", "Backend unavailable",
                          "audio_download");
      return;
    }
    if (!aiAudioDownloadStarted_) {
      // A WAV upload and a response download use separate HTTP tasks, but
      // share the bounded audio transport. Wait for the upload to retire
      // instead of turning a normal overlap into a generic playback error.
      if (backendClient_->audioTransferActive()) return;
      if (!backendClient_->beginAudioDownload(
              aiAudioDownloadUrl_, aiAudioOutputBuffer_,
              aiAudioDownloadSize_)) {
        failAiAudioPlayback(aiAudioDownloadId_, aiAudioDownloadTurnId_,
                            "download_start_failed",
                            "Audio download could not start", "audio_download");
        return;
      }
      aiAudioDownloadStarted_ = true;
      aiWorkflowText_ = "DOWNLOADING AI VOICE";
      return;
    }
    if (!backendClient_->audioTransferFinished()) return;
    const bool transferOk = backendClient_->audioTransferOk() &&
                            backendClient_->audioTransferLength() ==
                                aiAudioDownloadSize_;
    if (!transferOk) {
      const String code = backendClient_->audioTransferOk()
                              ? "audio_length_mismatch"
                              : "http_error";
      const String message =
          String("Audio download failed; bytes=") +
          String(static_cast<unsigned long>(backendClient_->audioTransferLength())) +
          "/" + String(static_cast<unsigned long>(aiAudioDownloadSize_));
      failAiAudioPlayback(aiAudioDownloadId_, aiAudioDownloadTurnId_, code,
                          message, "audio_download");
      return;
    }
    bool hashOk = false;
    uint8_t digest[32] = {};
    mbedtls_sha256_context sha;
    mbedtls_sha256_init(&sha);
    mbedtls_sha256_starts_ret(&sha, 0);
    mbedtls_sha256_update_ret(&sha, aiAudioOutputBuffer_,
                              aiAudioDownloadSize_);
    mbedtls_sha256_finish_ret(&sha, digest);
    mbedtls_sha256_free(&sha);
    const char* digits = "0123456789abcdef";
    String actual;
    actual.reserve(64);
    for (uint8_t value : digest) {
      actual += digits[value >> 4];
      actual += digits[value & 0x0F];
    }
    hashOk = actual.equalsIgnoreCase(aiAudioDownloadHash_);
    if (!hashOk) {
      failAiAudioPlayback(aiAudioDownloadId_, aiAudioDownloadTurnId_,
                          "sha256_mismatch", "Audio hash mismatch",
                          "audio_download");
      return;
    }
    if (!M5.Speaker.isEnabled()) {
      failAiAudioPlayback(aiAudioDownloadId_, aiAudioDownloadTurnId_,
                          "speaker_disabled", "Speaker unavailable",
                          "audio_playback");
      return;
    }
    const bool played =
                        M5.Speaker.playRaw(
                            reinterpret_cast<const int16_t*>(aiAudioOutputBuffer_),
                            aiAudioDownloadSize_ / sizeof(int16_t), 24000, false,
                            1, 0, true);
    aiAudioDownloadPending_ = false;
    aiAudioDownloadStarted_ = false;
    if (!played) {
      failAiAudioPlayback(aiAudioDownloadId_, aiAudioDownloadTurnId_,
                          "play_raw_rejected", "Speaker rejected audio",
                          "audio_playback");
      return;
    }
    aiAudioOutputLength_ = aiAudioDownloadSize_;
    aiAudioOutputActive_ = true;
    aiAudioOutputId_ = aiAudioDownloadId_;
    aiAudioOutputTurnId_ = aiAudioDownloadTurnId_;
    aiLastAudioId_ = aiAudioOutputId_;
    aiLastAudioTurnId_ = aiAudioOutputTurnId_;
    aiWorkflowText_ = "AI SPEAKING";
    backendClient_->audioPlaybackStarted(aiAudioOutputId_,
                                         aiAudioOutputTurnId_);
  }
  if (!aiAudioOutputActive_) return;
  if (M5.Speaker.isPlaying()) return;
  if (backendClient_)
    backendClient_->audioPlaybackFinished(aiAudioOutputId_,
                                         aiAudioOutputTurnId_);
  free(aiAudioOutputBuffer_);
  aiAudioOutputBuffer_ = nullptr;
  aiAudioOutputLength_ = 0;
  aiAudioOutputActive_ = false;
  aiAudioOutputId_ = "";
  aiAudioOutputTurnId_ = "";
  aiAudioDownloadUrl_ = "";
  aiDeveloperMode_ = 0;
  aiWorkflowState_ = 0;
  aiWorkflowText_ = "ANSWER - SPEAK AGAIN";
}

bool FireOS::startLuaApp(const String& path, const String& name,
                         const String& launchPackageId) {
  if (!luaRuntime_) {
    luaAppError_ = "Lua runtime unavailable";
    return false;
  }
  if (!sdReady_ && !initSdCard()) {
    luaAppError_ = "SD card unavailable";
    return false;
  }
  const int appSlash = path.lastIndexOf('/');
  const String appFolder = appSlash > 0 ? path.substring(0, appSlash) : "";
  const String manifestPath = appFolder.length() > 0
                                  ? sdJoinPath(appFolder, "manifest.json")
                                  : String();
  if (appFolder.length() == 0 || !SD.exists(manifestPath)) {
    luaAppError_ = "App manifest missing";
    return false;
  }
  File manifestFile = SD.open(manifestPath, FILE_READ);
  if (!manifestFile || manifestFile.size() > 8192) {
    luaAppError_ = "App manifest invalid";
    if (manifestFile) manifestFile.close();
    return false;
  }
  String manifest;
  while (manifestFile.available()) manifest += static_cast<char>(manifestFile.read());
  manifestFile.close();
  const String manifestId = jsonStringField(manifest, "id");
  const String manifestApi = jsonStringField(manifest, "api_version");
  const String manifestContract = jsonStringField(manifest, "api_contract");
  const String manifestHash = jsonStringField(manifest, "checksum");
  const int manifestMemory =
      jsonIntField(manifest, "max_memory", FireLuaRuntime::kMaxMemoryBytes);
  const int manifestRuntime = jsonIntField(manifest, "max_runtime_ms", -1);
  const bool hardwareApi = manifestApi == "fire-lua-0.2";
  if (manifestId != sdBaseName(appFolder) ||
      (manifestApi != "fire-lua-0.1" && !hardwareApi) ||
      (hardwareApi && manifestContract != FireLuaRuntime::hardwareApiContract()) ||
      !validSha256Hex(manifestHash) || manifestRuntime < -1 ||
      manifestMemory < 65536 ||
      manifestMemory > static_cast<int>(FireLuaRuntime::kMaxMemoryBytes) ||
      manifestRuntime > static_cast<int>(FireLuaRuntime::kMaxRuntimeMs)) {
    luaAppError_ = "App manifest does not match source";
    return false;
  }
  uint32_t serviceMask = 0;
  const bool servicesValid = hardwareApi
                                 ? luaManifestServiceMask(manifest, serviceMask)
                                 : (serviceMask = kLuaServiceDisplay |
                                                kLuaServiceButtons |
                                                kLuaServiceRgb | kLuaServiceImu |
                                                kLuaServiceTime,
                                    true);
  if (hardwareApi && (!servicesValid || serviceMask == 0 ||
                      (serviceMask & kLuaServiceI2c &&
                       !(serviceMask & kLuaServiceJobs)) ||
                      (serviceMask & kLuaServiceUart &&
                       !(serviceMask & kLuaServiceJobs)) ||
                      (serviceMask & kLuaServiceSpi &&
                       !(serviceMask & kLuaServiceJobs)) ||
                      (serviceMask & kLuaServiceSd &&
                       !(serviceMask & kLuaServiceJobs)) ||
                      (serviceMask & kLuaServiceSpeaker &&
                       (!(serviceMask & kLuaServiceJobs) ||
                        !(serviceMask & kLuaServiceSd))))) {
    luaAppError_ = "Hardware service dependencies invalid";
    return false;
  }
  if (hardwareApi && (serviceMask & kLuaServiceSd) && sdReady_) {
    const String appDataPath = "/apps/" + manifestId + "/appdata";
    if (!SD.exists(appDataPath) && !SD.mkdir(appDataPath)) {
      luaAppError_ = "App data directory unavailable";
      return false;
    }
  }
  if (hardwareApi && (serviceMask & kLuaServiceSd) && !sdReady_) {
    luaAppError_ = "SD card unavailable";
    return false;
  }
  if (!luaRuntimeReady_) {
    FireLuaRuntime::Host luaHost;
    luaHost.context = this;
    luaHost.displayClear = luaDisplayClear;
    luaHost.displayCircle = luaDisplayCircle;
    luaHost.displayRect = luaDisplayRect;
    luaHost.displayLine = luaDisplayLine;
    luaHost.displayText = luaDisplayText;
    luaHost.displayFillRect = luaDisplayFillRect;
    luaHost.displayFillCircle = luaDisplayFillCircle;
    luaHost.displayPixel = luaDisplayPixel;
    luaHost.displayGrid = luaDisplayGrid;
    luaHost.buttonPressed = luaButtonPressed;
    luaHost.rgbSet = luaRgbSet;
    luaHost.imuAccel = luaImuAccel;
    luaHost.imuGyro = luaImuGyro;
    luaHost.imuTemperature = luaImuTemperature;
    luaHost.timeMillis = luaTimeMillis;
    luaHost.gpioMode = luaGpioModeCallback;
    luaHost.gpioRead = luaGpioReadCallback;
    luaHost.gpioWrite = luaGpioWriteCallback;
    luaHost.gpioRelease = luaGpioReleaseCallback;
    luaHost.pwmConfigure = luaPwmConfigureCallback;
    luaHost.pwmWrite = luaPwmWriteCallback;
    luaHost.pwmStop = luaPwmStopCallback;
    luaHost.uartOpen = luaUartOpenCallback;
    luaHost.uartRead = luaUartReadCallback;
    luaHost.uartWrite = luaUartWriteCallback;
    luaHost.uartClose = luaUartCloseCallback;
    luaHost.i2cScan = luaI2cScanCallback;
    luaHost.i2cRead = luaI2cReadCallback;
    luaHost.i2cWrite = luaI2cWriteCallback;
    luaHost.adcRead = luaAdcReadCallback;
    luaHost.dacWrite = luaDacWriteCallback;
    luaHost.dacStop = luaDacStopCallback;
    luaHost.spiOpen = luaSpiOpenCallback;
    luaHost.spiTransfer = luaSpiTransferCallback;
    luaHost.spiClose = luaSpiCloseCallback;
    luaHost.sdList = luaSdListCallback;
    luaHost.sdRead = luaSdReadCallback;
    luaHost.sdWrite = luaSdWriteCallback;
    luaHost.sdRemove = luaSdRemoveCallback;
    luaHost.sdMkdir = luaSdMkdirCallback;
    luaHost.powerStatus = luaPowerStatusCallback;
    luaHost.powerBrightness = luaPowerBrightnessCallback;
    luaHost.powerSleep = luaPowerSleepCallback;
    luaHost.rtcNow = luaRtcNowCallback;
    luaHost.rtcSet = luaRtcSetCallback;
    luaHost.speakerTone = luaSpeakerToneCallback;
    luaHost.speakerPlay = luaSpeakerPlayCallback;
    luaHost.speakerStop = luaSpeakerStopCallback;
    luaHost.jobPoll = luaJobPollCallback;
    luaHost.jobResult = luaJobResultCallback;
    luaHost.jobClose = luaJobCloseCallback;
    luaHost.jobCancel = luaJobCancelCallback;
    luaRuntime_->setHardwareApi(hardwareApi);
    luaRuntime_->setServiceMask(serviceMask);
    luaRuntimeReady_ = luaRuntime_->begin(luaHost);
    if (!luaRuntimeReady_) {
      luaRuntimeReady_ = false;
      luaAppError_ = luaRuntime_->lastError();
      return false;
    }
  }
  const uint32_t maxRuntimeMs =
      manifestRuntime < 0 ? FireLuaRuntime::kDefaultRuntimeMs
                          : static_cast<uint32_t>(manifestRuntime);
  String packageId = launchPackageId;
  if (packageId.length() == 0) {
    packageId = jsonStringField(manifest, "package_id");
  }
  if (packageId.length() == 0) {
    packageId = preferences.getString(
        compactPreferenceKey("ap_", manifestId).c_str(), "");
  }
  auto reportLocalLoadFailure = [&](const char* code, const String& message) {
    if (launchPackageId.length() == 0 && packageId.length() > 0) {
      queueLuaDiagnostic(manifestId, packageId, code, message,
                         luaDiagnosticsJson("load"));
      flushLuaDiagnostic();
    }
  };
  File sourceFile = SD.open(path, FILE_READ);
  if (!sourceFile || sourceFile.isDirectory()) {
    luaAppError_ = "Cannot open app source";
    if (sourceFile) sourceFile.close();
    reportLocalLoadFailure("source_empty", luaAppError_);
    return false;
  }
  const size_t length = sourceFile.size();
  if (length == 0 || length > FireLuaRuntime::kMaxSourceBytes) {
    sourceFile.close();
    luaAppError_ = length == 0 ? "App source is empty" : "App source is too large";
    reportLocalLoadFailure(length == 0 ? "source_empty" : "source_size",
                           luaAppError_);
    return false;
  }
  uint8_t* buffer = static_cast<uint8_t*>(
      ESP.getPsramSize() > 0 ? ps_malloc(length) : malloc(length));
  if (!buffer) {
    sourceFile.close();
    luaAppError_ = "Not enough memory for app";
    reportLocalLoadFailure("memory_error", luaAppError_);
    return false;
  }
  const size_t readBytes = sourceFile.read(buffer, length);
  sourceFile.close();
  uint8_t sourceDigest[32] = {};
  mbedtls_sha256_context sourceSha;
  mbedtls_sha256_init(&sourceSha);
  mbedtls_sha256_starts_ret(&sourceSha, 0);
  mbedtls_sha256_update_ret(&sourceSha, buffer, readBytes);
  mbedtls_sha256_finish_ret(&sourceSha, sourceDigest);
  mbedtls_sha256_free(&sourceSha);
  String sourceHash;
  sourceHash.reserve(64);
  const char* hex = "0123456789abcdef";
  for (uint8_t value : sourceDigest) {
    sourceHash += hex[value >> 4];
    sourceHash += hex[value & 0x0F];
  }
  if (readBytes != length || !sourceHash.equalsIgnoreCase(manifestHash)) {
    free(buffer);
    luaAppError_ = "App source checksum mismatch";
    reportLocalLoadFailure("source_hash", luaAppError_);
    return false;
  }
  luaRuntime_->setMaxRuntimeMs(maxRuntimeMs);
  const bool loaded = readBytes == length && luaRuntime_->loadSource(buffer, length);
  free(buffer);
  if (!loaded) {
    luaAppError_ = luaRuntime_->lastError();
    const char* failureCode = luaFailureCode(luaAppError_);
    const String diagnostics = luaDiagnosticsJson(
        String(failureCode) == "init_error" ? "init" : "load");
    luaRuntime_->stop();
    luaRuntimeReady_ = false;
    if (launchPackageId.length() == 0 && packageId.length() > 0) {
      queueLuaDiagnostic(manifestId, packageId, failureCode, luaAppError_,
                         diagnostics);
      flushLuaDiagnostic();
    }
    return false;
  }
  luaAppPath_ = path;
  luaAppName_ = name.length() > 0 ? name : sdBaseName(path);
  luaAppId_ = manifestId;
  luaPackageId_ = packageId;
  luaMaxRuntimeMs_ = maxRuntimeMs;
  if (launchPackageId.length() > 0) {
    preferences.putString(compactPreferenceKey("ap_", manifestId).c_str(),
                          launchPackageId);
  }
  luaAppError_ = "";
  luaAppActive_ = true;
  luaRunId_ = "";
  luaHealthySent_ = false;
  luaLastFrameAt_ = millis();
  previousScreen_ = screen_;
  screen_ = Screen::LuaApp;
  return true;
}

void FireOS::stopLuaApp(const String& reason) {
  const String stoppedRunId = luaRunId_;
  const String stoppedAppId = luaAppId_;
  const String stoppedPackageId = luaPackageId_.length() > 0
                                      ? luaPackageId_
                                      : aiPackageId_;
  const bool userExit = reason == "back" || reason == "home" ||
                        reason == "user_exit";
  const bool requestedStop = reason == "remote_stop" || reason == "rollback";
  const String stoppedDiagnostics = luaDiagnosticsJson(
      reason == "runtime_limit" ? "stop"
                                 : (userExit ? "stop" : "update"));
  if (luaAppActive_ && reason.length() > 0) {
    Serial.printf("Lua app stopped: %s\n", reason.c_str());
  }
  releaseLuaHardware();
  if (stoppedRunId.length() == 0 && stoppedAppId.length() > 0 &&
      stoppedPackageId.length() > 0 && reason.length() > 0 && !userExit &&
      !requestedStop) {
    const String errorCode = reason == "runtime_limit" ? "runtime_limit"
                                                         : "runtime_error";
    queueLuaDiagnostic(stoppedAppId, stoppedPackageId, errorCode, reason,
                       stoppedDiagnostics);
  }
  luaAppActive_ = false;
  if (luaRuntime_) luaRuntime_->stop();
  luaRuntimeReady_ = false;
  for (auto& pixel : luaRgbValues_)
    pixel[0] = pixel[1] = pixel[2] = 0;
#ifdef FIRE_OS_BLE
  writeFireRgbRaw(0, 0, 0, 0);
#else
  M5.Led.setAllColor(0, 0, 0);
  M5.Led.display();
#endif
  luaRunId_ = "";
  luaAppId_ = "";
  luaPackageId_ = "";
  luaMaxRuntimeMs_ = FireLuaRuntime::kDefaultRuntimeMs;
  luaHealthySent_ = false;
  flushLuaDiagnostic();
  if (stoppedRunId.length() > 0 && backendClient_) {
    if (userExit)
      backendClient_->appStopped(stoppedRunId, stoppedPackageId, "", "user_exit",
                                 stoppedDiagnostics);
    else if (reason == "runtime_limit")
      backendClient_->appStopped(stoppedRunId, stoppedPackageId, "", "runtime_limit",
                                 stoppedDiagnostics);
    else if (reason.length() > 0 && !requestedStop)
      backendClient_->appFailed(stoppedRunId, stoppedPackageId, "runtime_error",
                                reason, stoppedDiagnostics);
  }
  if (reason.length() > 0 && reason != "back" && reason != "home") {
    luaAppError_ = reason;
  }
}

String FireOS::luaDiagnosticsJson(const char* phase) const {
  String json = "{\"phase\":\"" + String(phase ? phase : "stop") +
                "\",\"elapsed_ms\":" +
                String(luaRuntime_ ? luaRuntime_->elapsedMs() : 0) +
                ",\"callback_us\":" +
                String(luaRuntime_ ? luaRuntime_->lastCallbackUs() : 0) +
                ",\"free_heap\":" + String(ESP.getFreeHeap()) +
                ",\"min_free_heap\":" + String(ESP.getMinFreeHeap()) +
                ",\"lua_bytes\":" +
                String(luaRuntime_ ? luaRuntime_->memoryUsed() : 0) +
                ",\"source_bytes\":" +
                String(luaRuntime_ ? luaRuntime_->sourceBytes() : 0) +
                ",\"frames\":" +
                String(luaRuntime_ ? luaRuntime_->frameCount() : 0) + "}";
  return json;
}

String FireOS::audioDiagnosticsJson(const char* phase) const {
  return "{\"phase\":\"" + String(phase ? phase : "audio_playback") +
         "\",\"free_heap\":" + String(ESP.getFreeHeap()) +
         ",\"min_free_heap\":" + String(ESP.getMinFreeHeap()) + "}";
}

void FireOS::queueLuaDiagnostic(const String& appId, const String& packageId,
                                const String& errorCode,
                                const String& message,
                                const String& diagnostics) {
  // Never fabricate a package identity. The backend scopes diagnostics to an
  // installed package owned by this device, so an unknown local package is
  // reported only to the serial log until it has a real install mapping.
  if (appId.length() == 0 || packageId.length() == 0 ||
      errorCode.length() == 0) {
    Serial.println("Lua diagnostic deferred: package identity unavailable");
    return;
  }
  pendingDiagnosticAppId_ = appId;
  pendingDiagnosticPackageId_ = packageId;
  pendingDiagnosticErrorCode_ = errorCode;
  pendingDiagnosticMessage_ = message.substring(0, 240);
  pendingDiagnosticJson_ = diagnostics;
  preferences.putString("diag_app", pendingDiagnosticAppId_);
  preferences.putString("diag_pkg", pendingDiagnosticPackageId_);
  preferences.putString("diag_code", pendingDiagnosticErrorCode_);
  preferences.putString("diag_msg", pendingDiagnosticMessage_);
  preferences.putString("diag_meta", pendingDiagnosticJson_);
}

void FireOS::flushLuaDiagnostic() {
  if (pendingDiagnosticAppId_.length() == 0 || !backendClient_ ||
      !backendClient_->sessionReady()) {
    return;
  }
  if (!backendClient_->appDiagnostic(
          pendingDiagnosticAppId_, pendingDiagnosticPackageId_,
          pendingDiagnosticErrorCode_, pendingDiagnosticMessage_,
          pendingDiagnosticJson_)) {
    return;
  }
  preferences.remove("diag_app");
  preferences.remove("diag_pkg");
  preferences.remove("diag_code");
  preferences.remove("diag_msg");
  preferences.remove("diag_meta");
  pendingDiagnosticAppId_ = "";
  pendingDiagnosticPackageId_ = "";
  pendingDiagnosticErrorCode_ = "";
  pendingDiagnosticMessage_ = "";
  pendingDiagnosticJson_ = "";
}

void FireOS::updateLuaApp() {
  if (!luaAppActive_) return;
  const uint32_t now = millis();
  const uint32_t elapsed = now - luaLastFrameAt_;
  luaLastFrameAt_ = now;
  if (!luaRuntime_ || !luaRuntime_->update(min<uint32_t>(elapsed, 100))) {
    const String error = luaRuntime_ ? luaRuntime_->lastError()
                                     : String("runtime unavailable");
    const bool runtimeLimit = error == "Lua app runtime limit exceeded";
    stopLuaApp(runtimeLimit ? "runtime_limit" : error);
  } else if (luaRunId_.length() > 0 && !luaHealthySent_) {
    if (backendClient_)
      backendClient_->appHealthy(luaRunId_, luaPackageId_,
                                 luaDiagnosticsJson("update"));
    luaHealthySent_ = true;
  }
}

void FireOS::updateBackend() {
  if (!backendClient_) return;
  const bool backendDemand = screen_ == Screen::AiDeveloper ||
                              screen_ == Screen::AiApi ||
                              screen_ == Screen::LuaApp ||
                              screen_ == Screen::Settings ||
                              screen_ == Screen::AppsSettings ||
                              screen_ == Screen::Firmware ||
                              (packageManager_ && packageManager_->busy()) ||
                              (firmwareStorage_ && firmwareStorage_->busy()) ||
                              (githubFirmware_ && githubFirmware_->busy()) ||
                              pendingDiagnosticAppId_.length() > 0;
  if (!backendDemand) {
    // Do not let a failed PC connection stall normal FIRE OS navigation.
    if (backendClient_->active()) backendClient_->disconnect();
    return;
  }
  if (backendClient_->configured() && wifiMode_ != 2 &&
      WiFi.status() != WL_CONNECTED && !wifiConnectActive_ &&
      wifiSsid_.length() > 0) {
    // Start Auto-mode Wi-Fi only after the new screen has already been drawn.
    requestWifi(true);
  }
  backendClient_->service(WiFi.status() == WL_CONNECTED);
  updateAppManagerBackend();
  flushLuaDiagnostic();
}

void FireOS::backendState(void* context, bool connected, const String& status) {
  auto* os = static_cast<FireOS*>(context);
  if (!os) return;
  os->backendStatus_ = status;
  if (!connected && os->screen_ == Screen::AppsSettings) {
    os->backendCatalogLoading_ = false;
    os->backendCatalogRequested_ = false;
    os->managerStatus_ = "Backend disconnected";
  }
  os->redrawRequested_ = true;
  if (!connected && os->screen_ == Screen::AiDeveloper &&
      os->aiWorkflowState_ > 0) {
    os->aiWorkflowText_ = "BACKEND OFFLINE";
  }
}

void FireOS::packageStatus(void* context, const String& status) {
  auto* os = static_cast<FireOS*>(context);
  if (!os) return;
  os->aiWorkflowText_ = status;
  if (os->screen_ == Screen::AppsSettings) os->managerStatus_ = status;
  os->aiDeveloperMode_ = 2;
}

void FireOS::packageResult(void* context, bool ok, const String& packageId,
                           const String& archiveHash, const String& message) {
  auto* os = static_cast<FireOS*>(context);
  if (!os) return;
  os->aiPackageId_ = packageId;
  os->aiWorkflowText_ = ok ? "INSTALLED" : message;
  if (os->screen_ == Screen::AppsSettings) {
    os->managerStatus_ = ok ? "Downloaded to FIRE" : message;
    if (ok) {
      os->scanExternalApps();
      os->rebuildAppManagerItems();
      os->sendAppInventory();
    }
  }
  if (ok) {
    const String installedPath = os->packageManager_
                                     ? os->packageManager_->installedPath()
                                     : String();
    const int sourceSlash = installedPath.lastIndexOf('/');
    const String appFolder = sourceSlash > 0
                                 ? installedPath.substring(0, sourceSlash)
                                 : String();
    const String appId = appFolder.length() > 0 ? os->sdBaseName(appFolder)
                                                : String();
    preferences.putString(compactPreferenceKey("lp_", packageId).c_str(),
                          installedPath);
    preferences.putString(compactPreferenceKey("lh_", packageId).c_str(),
                          archiveHash);
    if (appId.length() > 0) {
      // Apps opened locally do not have a run_id. Preserve the real backend
      // package identity from installation so a later local crash can emit
      // app_diagnostic without inventing a run or package ID.
      preferences.putString(compactPreferenceKey("ap_", appId).c_str(),
                            packageId);
    }
    if (os->backendClient_) os->backendClient_->deviceInstallResult(
        os->aiInstallId_, packageId, true, archiveHash, "installed");
    os->aiWorkflowState_ = 5;
  } else {
    if (os->backendClient_) os->backendClient_->deviceInstallResult(
        os->aiInstallId_, packageId, false, archiveHash, message);
    os->aiWorkflowState_ = 0;
  }
}

void FireOS::firmwareStatus(void* context, const String& status) {
  auto* os = static_cast<FireOS*>(context);
  if (!os) return;
  os->firmwareMessage_ = status;
  os->redrawRequested_ = true;
}

void FireOS::firmwareResult(void* context, const String& transferId,
                            const String& firmwareId, bool ok,
                            const String& sha256, const String& errorCode,
                            const String& message) {
  auto* os = static_cast<FireOS*>(context);
  if (!os) return;
  os->firmwareMessage_ = ok ? "Stored on SD" : "Transfer failed: " + errorCode;
  if (os->sdReady_) os->scanFirmwareFiles();
  if (os->backendClient_)
    os->backendClient_->firmwareStoreResult(transferId, firmwareId, ok,
                                            sha256, errorCode, message);
  os->redrawRequested_ = true;
}

void FireOS::githubFirmwareStatus(void* context, const String& status) {
  auto* os = static_cast<FireOS*>(context);
  if (!os) return;
  os->firmwareMessage_ = status;
  os->redrawRequested_ = true;
}

void FireOS::githubFirmwareResult(void* context, bool manifest, bool ok,
                                  const String& message) {
  auto* os = static_cast<FireOS*>(context);
  if (!os) return;
  os->firmwareMessage_ = ok ? (manifest ? "GitHub list ready" : "Saved on SD")
                            : message;
  if (!manifest && ok) os->scanFirmwareFiles();
  os->redrawRequested_ = true;
}

void FireOS::backendMessage(void* context, const String& message) {
  auto* os = static_cast<FireOS*>(context);
  if (os) os->handleBackendMessage(message);
}

void FireOS::handleBackendMessage(const String& message) {
  redrawRequested_ = true;
  const String type = jsonStringField(message, "type");
  if (type == "session_started") {
    backendServerTime_ = jsonIntField(message, "server_time");
    backendServerSeenAt_ = millis();
    const String mode = jsonStringField(message, "conversation_mode");
    if (mode == "chat") aiConversationMode_ = 1;
    else if (mode == "develop") aiConversationMode_ = 0;
    aiWorkflowText_ = "CONNECTED";
    return;
  }
  if (type == "session_snapshot") {
    backendServerTime_ = jsonIntField(message, "server_time");
    backendServerSeenAt_ = millis();
    const String mode = jsonStringField(message, "conversation_mode");
    if (mode == "chat") aiConversationMode_ = 1;
    else if (mode == "develop") aiConversationMode_ = 0;
    const String proposal = jsonStringField(message, "proposal_id");
    const String packageId = jsonStringField(message, "package_id");
    if (proposal.length() > 0) aiProposalId_ = proposal;
    if (packageId.length() > 0) aiPackageId_ = packageId;
    const String activity = jsonStringField(message, "activity");
    if (activity == "listening") {
      aiWorkflowState_ = 1;
      aiDeveloperMode_ = 1;
    } else if (activity == "processing") {
      aiWorkflowState_ = 2;
      aiDeveloperMode_ = 2;
    } else if (activity == "speaking") {
      aiDeveloperMode_ = 3;
      aiWorkflowState_ = 2;
    }
    aiWorkflowText_ = "CONNECTED - STATE RESTORED";
    return;
  }
  if (type == "app_inventory_request") {
    scanLuaApps();
    rebuildAppManagerItems();
    sendAppInventory();
    return;
  }
  if (type == "app_catalog") {
    parseBackendAppCatalog(message);
    return;
  }
  if (type == "app_versions") {
    parseBackendAppVersions(message);
    return;
  }
  if (type == "app_backend_delete_ready") {
    appManagerDeleteId_ = jsonStringField(message, "delete_id");
    appManagerDeleteProjectId_ = jsonStringField(message, "project_id");
    appManagerDeleteAppId_ = jsonStringField(message, "app_id");
    appManagerDeletePackageId_ = jsonStringField(message, "package_id");
    appManagerDeleteName_ = jsonStringField(message, "name");
    const String scope = jsonStringField(message, "delete_scope");
    appManagerDeleteScope_ = scope == "version" ? 1 : 2;
    appManagerDeleteMode_ = 2;
    appManagerDeleteConfirm_ = appManagerDeleteId_.length() > 0;
    appManagerDeleteWaiting_ = false;
    appManagerActionMenu_ = false;
    managerStatus_ = "Confirm backend delete";
    redrawRequested_ = true;
    return;
  }
  if (type == "app_backend_deleted") {
    const String deletedAppId = jsonStringField(message, "app_id");
    for (uint8_t index = 0; index < backendAppCount_; ++index) {
      if (backendApps_[index].appId != deletedAppId) continue;
      backendApps_[index] = BackendAppInfo();
      for (uint8_t move = index + 1; move < backendAppCount_; ++move)
        backendApps_[move - 1] = backendApps_[move];
      if (backendAppCount_ > 0) --backendAppCount_;
      break;
    }
    appManagerDeleteConfirm_ = false;
    appManagerDeleteWaiting_ = false;
    appManagerDeleteMode_ = 0;
    rebuildAppManagerItems();
    managerStatus_ = "Backend app deleted";
    backendCatalogRequested_ = false;
    redrawRequested_ = true;
    return;
  }
  if (type == "event_ack") {
    const String status = jsonStringField(message, "status");
    if (status == "awaiting_device_install")
      managerStatus_ = "Download queued";
    else if (status == "confirmation_required")
      managerStatus_ = "Confirm deletion";
    redrawRequested_ = true;
    return;
  }
  if (type == "assistant_message" || type == "transcript") {
    const String text = jsonStringField(message, "text");
    if (type == "transcript") {
      aiTranscriptText_ = text;
      aiAssistantText_ = "Jeg hørte: " + text;
    } else {
      aiAssistantText_ = text;
    }
    if (type == "assistant_message") {
      // A completed answer returns to the conversational idle state so B can
      // start another turn and add context before the user builds.
      aiDeveloperMode_ = 3;
      aiWorkflowState_ = 0;
      aiWorkflowText_ = "ANSWER - SPEAK AGAIN";
    } else {
      aiDeveloperMode_ = 2;
      aiWorkflowState_ = 2;
      aiWorkflowText_ = "TRANSCRIBED - WAITING FOR AI";
    }
    return;
  }
  if (type == "input_retry" ||
      (type == "error" &&
       (jsonStringField(message, "code") == "no_speech" ||
        jsonStringField(message, "code") == "audio_upload_missing"))) {
    const String turnId = jsonStringField(message, "turn_id");
    if (turnId.length() == 0 || turnId == aiTurnId_) {
      cancelConversationTurn("TRY AGAIN - PRESS B", false);
      aiWorkflowText_ = "TRY AGAIN - PRESS B";
    }
    return;
  }
  if (type == "turn_cancelled") {
    const String turnId = jsonStringField(message, "turn_id");
    if (turnId.length() == 0 || turnId == aiTurnId_)
      cancelConversationTurn("READY - PRESS B TO SPEAK", false);
    return;
  }
  if (type == "ui_event") {
    String state = jsonStringField(message, "state");
    if (state.length() == 0) state = jsonStringField(message, "activity");
    if (state == "listening") {
      aiWorkflowState_ = 1;
      aiDeveloperMode_ = 1;
    } else if (state == "processing" || state == "thinking") {
      aiWorkflowState_ = 2;
      aiDeveloperMode_ = 2;
    } else if (state == "speaking") {
      aiDeveloperMode_ = 3;
    }
    aiWorkflowText_ = state;
    return;
  }
  if (type == "build_proposal") {
    aiProposalId_ = jsonStringField(message, "proposal_id");
    aiAssistantText_ = jsonStringField(message, "summary");
    aiWorkflowState_ = aiProposalId_.length() > 0 ? 3 : 0;
    aiDeveloperMode_ = 2;
    aiWorkflowText_ = "READY TO BUILD";
    return;
  }
  if (type == "build_progress") {
    aiBuildProgress_ = constrain(jsonIntField(message, "progress"), 0, 100);
    const String phase = jsonStringField(message, "phase");
    aiWorkflowState_ = phase == "ready" ? 5 : phase == "failed" ? 0 : 4;
    aiWorkflowText_ = phase.length() > 0 ? phase : "BUILDING";
    aiDeveloperMode_ = 2;
    return;
  }
  if (type == "audio_ready") {
    const String audioId = jsonStringField(message, "audio_id");
    const String turnId = jsonStringField(message, "turn_id");
    const String url = jsonStringField(message, "download_url");
    const String format = jsonStringField(message, "format");
    const String expectedHash = jsonStringField(message, "sha256");
    const int sampleRate = jsonIntField(message, "sample_rate");
    const int channels = jsonIntField(message, "channels");
    const uint32_t size = static_cast<uint32_t>(jsonIntField(message, "size_bytes"));
    constexpr uint32_t kMaxPcmBytes = 1440000;
    if (!backendClient_ || audioId.length() == 0 || turnId.length() == 0 ||
        (aiTurnId_.length() > 0 && turnId != aiTurnId_) ||
        audioId == aiLastAudioId_ || url.length() == 0 ||
        format != "pcm_s16le" || !validSha256Hex(expectedHash) ||
        sampleRate != 24000 || channels != 1 || size == 0 ||
        size > kMaxPcmBytes || (size & 1U) != 0) {
      failAiAudioPlayback(audioId, turnId, "invalid_audio_metadata",
                          "Invalid audio response", "audio_download",
                          !aiAudioOutputActive_ && !M5.Speaker.isPlaying());
      return;
    }
    // Never release a buffer while Speaker may still be reading it. A newer
    // answer can supersede the old one, but the old playback must be stopped
    // and observed idle before its memory is reused.
    if (aiAudioOutputActive_ || aiAudioOutputBuffer_) {
      M5.Speaker.stop();
      if (M5.Speaker.isPlaying()) {
        if (backendClient_ && audioId.length() > 0 && turnId.length() > 0)
          backendClient_->audioPlaybackFailed(
              audioId, turnId, "speaker_busy", "Speaker is busy",
              audioDiagnosticsJson("audio_playback"));
        aiWorkflowText_ = "VOICE BUSY - TRY AGAIN";
        aiDeveloperMode_ = 3;
        return;
      }
      free(aiAudioOutputBuffer_);
      aiAudioOutputBuffer_ = nullptr;
      aiAudioOutputLength_ = 0;
      aiAudioOutputActive_ = false;
    }
    aiAudioOutputBuffer_ = static_cast<uint8_t*>(ps_malloc(size));
    if (!aiAudioOutputBuffer_)
      aiAudioOutputBuffer_ = static_cast<uint8_t*>(malloc(size));
    aiAudioDownloadId_ = audioId;
    aiAudioDownloadTurnId_ = turnId;
    aiAudioDownloadUrl_ = url;
    aiAudioDownloadHash_ = expectedHash;
    aiAudioDownloadSize_ = size;
    aiAudioDownloadPending_ = true;
    aiAudioDownloadStarted_ = false;
    if (!aiAudioOutputBuffer_) {
      failAiAudioPlayback(audioId, turnId, "buffer_unavailable",
                          "Audio buffer unavailable", "audio_download");
      return;
    }
    aiDeveloperMode_ = 3;
    aiWorkflowState_ = 2;
    aiWorkflowText_ = "QUEUED AI VOICE";
    return;
  }
  if (type == "firmware_store_request") {
    const String transferId = jsonStringField(message, "transfer_id");
    const String firmwareId = jsonStringField(message, "firmware_id");
    const String filename = jsonStringField(message, "filename");
    const String sdPath = jsonStringField(message, "sd_path");
    const String url = jsonStringField(message, "download_url");
    const String expectedHash = jsonStringField(message, "sha256");
    const uint32_t expectedSize =
        static_cast<uint32_t>(jsonIntField(message, "size_bytes"));
    const uint32_t expiresAt =
        static_cast<uint32_t>(jsonIntField(message, "expires_at"));
    const String commandBoot = jsonStringField(message, "boot_id");
    firmwareMessage_ = "Firmware request received";
    if (commandBoot.length() > 0 && backendClient_ &&
        commandBoot != backendClient_->bootId()) {
      firmwareMessage_ = "Firmware request is stale";
      return;
    }
    if (!backendCommandUnexpired(expiresAt)) {
      firmwareMessage_ = "Firmware request expired";
      if (backendClient_ && transferId.length() > 0 && firmwareId.length() > 0)
        backendClient_->firmwareStoreResult(
            transferId, firmwareId, false, "", "expired", "Request expired");
      return;
    }
    const bool accepted =
        firmwareStorage_ && backendClient_ && backendClient_->sessionReady() &&
        firmwareStorage_->startRequest(
            backendHost_, backendPort_, backendToken_, url, transferId,
            firmwareId, filename, sdPath, expectedHash, expectedSize,
            expiresAt);
    if (!accepted) {
      firmwareMessage_ = firmwareStorage_
                             ? firmwareStorage_->errorMessage()
                             : String("Firmware storage unavailable");
      if (backendClient_ && transferId.length() > 0 && firmwareId.length() > 0)
        backendClient_->firmwareStoreResult(
            transferId, firmwareId, false, "",
            firmwareStorage_ && firmwareStorage_->errorCode().length() > 0
                ? firmwareStorage_->errorCode()
                : "storage_unavailable",
            firmwareMessage_);
    }
    redrawRequested_ = true;
    return;
  }
  if (type == "package_ready") {
    aiPackageId_ = jsonStringField(message, "package_id");
    const String projectId = jsonStringField(message, "project_id");
    if (projectId.length() > 0 && aiPackageId_.length() > 0) {
      preferences.putString(compactPreferenceKey("pr_", aiPackageId_).c_str(),
                            projectId);
      saveSettings();
    }
    aiWorkflowText_ = "PACKAGE READY";
    return;
  }
  if (type == "install_request") {
    aiPackageId_ = jsonStringField(message, "package_id");
    aiInstallId_ = jsonStringField(message, "install_id");
    const String url = jsonStringField(message, "download_url");
    const String hash = jsonStringField(message, "archive_sha256");
    const String projectId = jsonStringField(message, "project_id");
    const uint32_t size = static_cast<uint32_t>(jsonIntField(message, "size_bytes"));
    const String commandBoot = jsonStringField(message, "boot_id");
    const uint32_t expiresAt = static_cast<uint32_t>(jsonIntField(message, "expires_at"));
    if (backendClient_ && commandBoot.length() > 0 &&
        commandBoot != backendClient_->bootId()) {
      backendClient_->deviceInstallResult(aiInstallId_, aiPackageId_, false,
                                           hash, "stale boot_id");
      aiWorkflowText_ = "DOWNLOAD REJECTED";
      return;
    }
    if (!backendCommandUnexpired(expiresAt)) {
      if (backendClient_) backendClient_->deviceInstallResult(
          aiInstallId_, aiPackageId_, false, hash, "expired install command");
      aiWorkflowText_ = "DOWNLOAD EXPIRED";
      return;
    }
    const bool accepted = packageManager_ && packageManager_->startDownload(
        backendHost_, backendPort_, backendToken_, url, aiPackageId_, aiInstallId_,
        hash, size);
    if (projectId.length() > 0 && aiPackageId_.length() > 0) {
      preferences.putString(compactPreferenceKey("pr_", aiPackageId_).c_str(),
                            projectId);
      saveSettings();
    }
    if (!accepted && backendClient_)
      backendClient_->deviceInstallResult(aiInstallId_, aiPackageId_, false,
                                          hash, "download rejected");
    aiWorkflowText_ = accepted ? "DOWNLOADING" : "DOWNLOAD REJECTED";
    return;
  }
  if (type == "run_request") {
    const String runId = jsonStringField(message, "run_id");
    const String packageId = jsonStringField(message, "package_id");
    const String commandBoot = jsonStringField(message, "boot_id");
    const String commandHash = jsonStringField(message, "archive_sha256");
    const uint32_t expiresAt = static_cast<uint32_t>(jsonIntField(message, "expires_at"));
    if (runId.length() == 0 || packageId.length() == 0 ||
        (backendClient_ && commandBoot.length() > 0 &&
         commandBoot != backendClient_->bootId())) {
      if (backendClient_)
        backendClient_->appFailed(runId, packageId, "invalid_command",
                                  "Invalid or stale run command");
      aiWorkflowText_ = "RUN REJECTED";
      return;
    }
    if (!backendCommandUnexpired(expiresAt)) {
      if (backendClient_)
        backendClient_->appFailed(runId, packageId, "expired_command",
                                  "Run command expired");
      aiWorkflowText_ = "RUN EXPIRED";
      return;
    }
    const String consumedKey = compactPreferenceKey("rr_", runId);
    const String previousRun = preferences.getString(consumedKey.c_str(), "");
    if (previousRun.length() > 0) {
      if (backendClient_ && (previousRun == "started" || previousRun == "healthy"))
        backendClient_->appStarted(runId, packageId);
      else if (backendClient_)
        backendClient_->appFailed(runId, packageId, "previous_failure",
                                  "Run command was already consumed");
      aiWorkflowText_ = previousRun == "failed" ? "RUN FAILED" : "RUN ALREADY CONSUMED";
      return;
    }
    const String path = preferences.getString(
        compactPreferenceKey("lp_", packageId).c_str(), "");
    const String installedHash = preferences.getString(
        compactPreferenceKey("lh_", packageId).c_str(), "");
    aiPackageId_ = packageId;
    if (commandHash.length() > 0 && installedHash.length() > 0 &&
        !commandHash.equalsIgnoreCase(installedHash)) {
      preferences.putString(consumedKey.c_str(), "failed");
      saveSettings();
      if (backendClient_)
        backendClient_->appFailed(runId, packageId, "archive_mismatch",
                                  "Installed package hash does not match command");
      aiWorkflowText_ = "RUN REJECTED";
      return;
    }
    preferences.putString(consumedKey.c_str(), "starting");
    saveSettings();
    if (path.length() > 0 &&
        startLuaApp(path, sdBaseName(path), packageId)) {
      luaRunId_ = runId;
      luaPackageId_ = packageId;
      luaHealthySent_ = false;
      aiWorkflowState_ = 6;
      aiDeveloperMode_ = 3;
      aiWorkflowText_ = "RUNNING";
      preferences.putString(consumedKey.c_str(), "started");
      saveSettings();
      if (backendClient_)
        backendClient_->appStarted(runId, packageId,
                                   luaDiagnosticsJson("start"));
    } else {
      preferences.putString(consumedKey.c_str(), "failed");
      saveSettings();
      const String failure = path.length() > 0 && luaAppError_.length() > 0
                                 ? luaAppError_
                                 : String("Package is not installed on FIRE");
      const String errorCode = path.length() > 0 && luaAppError_.startsWith("Lua init")
                                   ? "init_error"
                                   : path.length() > 0 && luaAppError_.startsWith("Lua syntax")
                                         ? "load_error"
                                         : "not_installed";
      if (backendClient_)
        backendClient_->appFailed(runId, packageId, errorCode, failure);
      aiWorkflowText_ = "APP NOT INSTALLED";
    }
    return;
  }
  if (type == "stop_request") {
    const String runId = jsonStringField(message, "run_id");
    const String packageId = jsonStringField(message, "package_id");
    const String stopId = jsonStringField(message, "stop_id");
    const String commandBoot = jsonStringField(message, "boot_id");
    const uint32_t expiresAt = static_cast<uint32_t>(jsonIntField(message, "expires_at"));
    if (backendClient_ && commandBoot.length() > 0 &&
        commandBoot != backendClient_->bootId()) {
      if (backendClient_) backendClient_->appStopped(runId, packageId, stopId,
                                                     "requested");
      return;
    }
    if (!backendCommandUnexpired(expiresAt)) return;
    const bool activeRun = luaAppActive_ && luaRunId_ == runId;
    if (activeRun) stopLuaApp("remote_stop");
    if (backendClient_)
      backendClient_->appStopped(runId, packageId, stopId, "requested");
    aiWorkflowState_ = 5;
    aiWorkflowText_ = activeRun ? "STOPPED" : "ALREADY STOPPED";
    return;
  }
  if (type == "rollback_request") {
    const String rollbackId = jsonStringField(message, "rollback_id");
    const String packageId = jsonStringField(message, "package_id");
    const String commandBoot = jsonStringField(message, "boot_id");
    const uint32_t expiresAt = static_cast<uint32_t>(jsonIntField(message, "expires_at"));
    String path = preferences.getString(
        compactPreferenceKey("lp_", packageId).c_str(), "");
    const bool bootOk = backendCommandUnexpired(expiresAt) &&
                        (!backendClient_ || commandBoot.length() == 0 ||
                         commandBoot == backendClient_->bootId());
    bool available = bootOk && path.length() > 0 && SD.exists(path);
    bool restored = false;
    if (available) {
      const String targetHash = preferences.getString(
          compactPreferenceKey("lh_", packageId).c_str(), "");
      const String currentHash = sha256File(path);
      if (!validSha256Hex(targetHash)) {
        available = false;
      } else if (!currentHash.equalsIgnoreCase(targetHash)) {
        const int slash = path.lastIndexOf('/');
        const String folder = slash > 0 ? path.substring(0, slash) : "";
        const String appId = sdBaseName(folder);
        const String previous = "/apps/.previous-" + appId;
        const String previousMain = previous + "/main.lua";
        if (SD.exists(previousMain) &&
            sha256File(previousMain).equalsIgnoreCase(targetHash)) {
          const String backup = "/apps/.rollback-" + appId;
          const bool cleared = !SD.exists(backup) || removeSdTree(backup);
          bool swapped = cleared && SD.rename(folder, backup) &&
                         SD.rename(previous, folder);
          if (!swapped) {
            if (SD.exists(folder) && !SD.exists(previous)) SD.rename(folder, previous);
            if (SD.exists(backup) && !SD.exists(folder)) SD.rename(backup, folder);
          } else {
            removeSdTree(backup);
            path = folder + "/main.lua";
            preferences.putString(compactPreferenceKey("lp_", packageId).c_str(), path);
            preferences.putString(compactPreferenceKey("lh_", packageId).c_str(), targetHash);
            saveSettings();
            restored = true;
            available = true;
          }
        } else {
          available = false;
        }
      }
    }
    if (luaAppActive_) stopLuaApp("rollback");
    if (backendClient_)
      backendClient_->rollbackResult(
          rollbackId, packageId, available,
          available ? (restored ? "Previous package restored and hash verified"
                                 : "Validated package already active")
                    : "Validated package is not available on SD");
    aiWorkflowState_ = available ? 5 : 0;
    aiWorkflowText_ = available ? "ROLLBACK READY" : "ROLLBACK FAILED";
    return;
  }
  if (type == "app_started" || type == "app_healthy") {
    aiWorkflowState_ = 6;
    aiDeveloperMode_ = 3;
    aiWorkflowText_ = type == "app_healthy" ? "RUNNING" : "STARTING";
    return;
  }
  if (type == "error" || type == "app_failed") {
    aiWorkflowState_ = 0;
    aiDeveloperMode_ = 0;
    aiWorkflowText_ = jsonStringField(message, "message");
    if (aiWorkflowText_.length() == 0) aiWorkflowText_ = "BACKEND ERROR";
  }
}

void FireOS::luaDisplayClear(void* context, int color) {
  auto* os = static_cast<FireOS*>(context);
  if (os) ui.fillSprite(static_cast<uint16_t>(color));
}

void FireOS::luaDisplayCircle(void* context, int x, int y, int radius,
                              int color) {
  auto* os = static_cast<FireOS*>(context);
  if (os) ui.drawCircle(x, y, radius, static_cast<uint16_t>(color));
}

void FireOS::luaDisplayRect(void* context, int x, int y, int width, int height,
                            int color) {
  auto* os = static_cast<FireOS*>(context);
  if (os) ui.drawRect(x, y, width, height, static_cast<uint16_t>(color));
}

void FireOS::luaDisplayLine(void* context, int x1, int y1, int x2, int y2,
                            int color) {
  auto* os = static_cast<FireOS*>(context);
  if (os) ui.drawLine(x1, y1, x2, y2, static_cast<uint16_t>(color));
}

void FireOS::luaDisplayText(void* context, int x, int y, const char* text,
                            int color) {
  auto* os = static_cast<FireOS*>(context);
  if (!os) return;
  ui.setTextSize(1);
  ui.setTextColor(static_cast<uint16_t>(color), TFT_BLACK);
  ui.drawString(text ? text : "", x, y);
}

void FireOS::luaDisplayFillRect(void* context, int x, int y, int width,
                                int height, int color) {
  auto* os = static_cast<FireOS*>(context);
  if (os) ui.fillRect(x, y, width, height, static_cast<uint16_t>(color));
}

void FireOS::luaDisplayFillCircle(void* context, int x, int y, int radius,
                                  int color) {
  auto* os = static_cast<FireOS*>(context);
  if (os) ui.fillCircle(x, y, radius, static_cast<uint16_t>(color));
}

void FireOS::luaDisplayPixel(void* context, int x, int y, int color) {
  auto* os = static_cast<FireOS*>(context);
  if (os) ui.drawPixel(x, y, static_cast<uint16_t>(color));
}

void FireOS::luaDisplayGrid(void* context, int x, int y, int cellWidth,
                            int cellHeight, int columns, int rows,
                            const uint8_t* cells, size_t cellCount,
                            const uint16_t* palette, size_t paletteCount) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !cells || !palette) return;
  for (size_t index = 0; index < cellCount; ++index) {
    const int column = static_cast<int>(index % columns);
    const int row = static_cast<int>(index / columns);
    if (row >= rows || cells[index] >= paletteCount) continue;
    ui.fillRect(x + column * cellWidth, y + row * cellHeight, cellWidth,
                cellHeight, palette[cells[index]]);
  }
}

bool FireOS::luaButtonPressed(void* context, const char* button) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !button || strlen(button) != 1) return false;
  const uint8_t index = button[0] == 'A' ? 0 : button[0] == 'B' ? 1 : 2;
  return os->buttons_[index].down;
}

void FireOS::luaRgbSet(void* context, int index, int red, int green,
                       int blue) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || index < 0 || index >= 10) return;
  os->luaRgbValues_[index][0] = static_cast<uint8_t>(red);
  os->luaRgbValues_[index][1] = static_cast<uint8_t>(green);
  os->luaRgbValues_[index][2] = static_cast<uint8_t>(blue);
#ifdef FIRE_OS_BLE
  writeFireRgbArray(os->luaRgbValues_, 180);
#else
  M5.Led.setBrightness(180);
  M5.Led.setAllColor(static_cast<uint8_t>(red), static_cast<uint8_t>(green),
                     static_cast<uint8_t>(blue));
  M5.Led.display();
#endif
}

bool FireOS::luaImuAccel(void* context, float* x, float* y, float* z) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !x || !y || !z || !M5.Imu.isEnabled()) return false;
  m5::imu_data_t data;
  M5.Imu.getImuData(&data);
  *x = data.accel.x;
  *y = data.accel.y;
  *z = data.accel.z;
  return true;
}

bool FireOS::luaImuGyro(void* context, float* x, float* y, float* z) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !x || !y || !z || !M5.Imu.isEnabled()) return false;
  m5::imu_data_t data;
  M5.Imu.getImuData(&data);
  *x = data.gyro.x;
  *y = data.gyro.y;
  *z = data.gyro.z;
  return true;
}

bool FireOS::luaImuTemperature(void* context, float* value) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !value || !M5.Imu.isEnabled()) return false;
  return M5.Imu.getTemp(value);
}

uint32_t FireOS::luaTimeMillis(void*) { return millis(); }

void FireOS::handleAiApiButton(uint8_t index) {
  if (wifiSetupActive_) {
    if (index == 1 || index == 2) stopWifiSetup();
    return;
  }
  constexpr uint8_t kCount = 3;
  if (index == 0) {
    detailIndex_ = (detailIndex_ + kCount - 1) % kCount;
  } else if (index == 2) {
    detailIndex_ = (detailIndex_ + 1) % kCount;
  } else if (detailIndex_ == 0) {
    startAiApiSetup();
  } else if (detailIndex_ == 2) {
    back();
  }
}

void FireOS::handleAppsButton(uint8_t index) {
  const uint8_t appCount = externalAppCount_ + luaAppCount_;
  const uint8_t itemCount = appCount + 1;  // Includes Back.
  if (index == 0 || index == 2) {
    externalAppSelection_ =
        (externalAppSelection_ + itemCount + (index == 0 ? -1 : 1)) %
        itemCount;
    if (externalAppSelection_ < externalAppOffset_)
      externalAppOffset_ = externalAppSelection_;
    if (externalAppSelection_ >= externalAppOffset_ + 5)
      externalAppOffset_ = externalAppSelection_ - 4;
  } else if (index == 1) {
    if (externalAppSelection_ == appCount) {
      back();
      return;
    }
    if (appCount == 0) {
      scanExternalApps();
      externalAppMessage_ = "No apps found";
      return;
    }
    if (externalAppSelection_ >= externalAppCount_) {
      const uint8_t luaIndex = externalAppSelection_ - externalAppCount_;
      if (!startLuaApp(luaAppPaths_[luaIndex], luaAppNames_[luaIndex])) {
        externalAppMessage_ = luaAppError_;
      }
    } else {
      externalAppMessage_ = "Installing...";
      draw();
      // Starting a .bin app is a temporary launch. The Boot App setting
      // remains unchanged so FIRE OS is restored after reboot.
      installExternalApp(externalAppPaths_[externalAppSelection_], true, false);
    }
  }
}

void FireOS::handleAppsSettingsButton(uint8_t index) {
  if (screen_ == Screen::AppsSettings) {
    if (appManagerVersionDialog_) {
      const uint8_t itemCount = appManagerVersionCount_ + 1;
      if (index == 0)
        appManagerVersionSelection_ =
            (appManagerVersionSelection_ + itemCount - 1) % itemCount;
      else if (index == 2)
        appManagerVersionSelection_ =
            (appManagerVersionSelection_ + 1) % itemCount;
      else if (appManagerVersionSelection_ == appManagerVersionCount_) {
        appManagerVersionDialog_ = false;
      } else if (appManagerVersionDownloadable_[appManagerVersionSelection_]) {
        const String packageId =
            appManagerVersionPackageIds_[appManagerVersionSelection_];
        if (backendClient_ && backendClient_->appDownload(
                                  appManagerVersionProjectId_, packageId,
                                  appManagerVersionAppId_)) {
          appManagerVersionDialog_ = false;
          managerStatus_ = "Download requested";
        } else {
          managerStatus_ = "Backend unavailable";
        }
      } else {
        managerStatus_ = appManagerVersionReasons_[appManagerVersionSelection_];
        if (managerStatus_.length() == 0) managerStatus_ = "Version unavailable";
      }
      if (appManagerVersionSelection_ < appManagerVersionOffset_)
        appManagerVersionOffset_ = appManagerVersionSelection_;
      if (appManagerVersionSelection_ >= appManagerVersionOffset_ + 6)
        appManagerVersionOffset_ = appManagerVersionSelection_ - 5;
      return;
    }
    if (appManagerDeleteConfirm_) {
      if (index == 0 || index == 2) {
        appManagerDeleteConfirm_ = false;
        appManagerDeleteMode_ = 0;
      } else if (index == 1 && appManagerDeleteMode_ == 1) {
        if (managerSelection_ < managerItemCount_) {
          const ManagerItem& item = managerItems_[managerSelection_];
          bool deleted = false;
          if (item.kind == 1) deleted = deleteLuaApp(item.localPath);
          else if (item.kind == 0) deleted = deleteExternalApp(item.localPath);
          managerStatus_ = deleted ? "Local app deleted" : "Local delete failed";
          appManagerDeleteConfirm_ = false;
          appManagerDeleteMode_ = 0;
          scanExternalApps();
          rebuildAppManagerItems();
          sendAppInventory();
          backendCatalogRequested_ = false;
        }
      } else if (index == 1 && appManagerDeleteMode_ == 2) {
        if (backendClient_ && backendClient_->appBackendDeleteConfirm(
                                  appManagerDeleteId_)) {
          appManagerDeleteConfirm_ = false;
          appManagerDeleteWaiting_ = true;
          managerStatus_ = "Deleting backend history...";
        } else {
          managerStatus_ = "Backend unavailable";
        }
      }
      return;
    }
    if (appManagerActionMenu_) {
      if (index == 0)
        appManagerActionIndex_ =
            (appManagerActionIndex_ + appManagerActionCount_ - 1) %
            appManagerActionCount_;
      else if (index == 2)
        appManagerActionIndex_ =
            (appManagerActionIndex_ + 1) % appManagerActionCount_;
      else {
        const uint8_t action =
            appManagerActionCodes_[appManagerActionIndex_];
        appManagerActionMenu_ = false;
        if (managerSelection_ >= managerItemCount_) return;
        const ManagerItem& item = managerItems_[managerSelection_];
        if (action == 1) {
          if (item.kind == 1)
            startLuaApp(item.localPath, item.name, item.localPackageId);
          else if (item.kind == 0)
            installExternalApp(item.localPath, true, false);
        } else if (action == 2) {
          requestSelectedAppVersions();
        } else if (action == 3) {
          appManagerDeleteMode_ = 1;
          appManagerDeleteConfirm_ = true;
        } else if (action == 4) {
          if (backendClient_ && backendClient_->appBackendDeletePrepare(
                                    item.projectId, item.appId, "all")) {
            appManagerDeleteWaiting_ = true;
            managerStatus_ = "Preparing backend delete...";
          } else {
            managerStatus_ = "Backend unavailable";
          }
        }
      }
      return;
    }

    const uint8_t itemCount = managerItemCount_ + 1;
    if (index == 0 || index == 2) {
      managerSelection_ =
          (managerSelection_ + itemCount + (index == 0 ? -1 : 1)) % itemCount;
      if (managerSelection_ < managerOffset_) managerOffset_ = managerSelection_;
      if (managerSelection_ >= managerOffset_ + 6)
        managerOffset_ = managerSelection_ - 5;
    } else if (managerSelection_ == managerItemCount_) {
      back();
    } else if (managerItemCount_ == 0) {
      managerStatus_ = "No apps found";
    } else {
      prepareAppManagerActions();
      appManagerActionMenu_ = appManagerActionCount_ > 0;
    }
    return;
  }
  if (screen_ == Screen::MainMenuSettings) {
    if (luaMenuPicker_) {
      const uint8_t itemCount = luaAppCount_ + 1;
      if (index == 0) {
        luaMenuSelection_ = (luaMenuSelection_ + itemCount - 1) % itemCount;
      } else if (index == 2) {
        luaMenuSelection_ = (luaMenuSelection_ + 1) % itemCount;
      } else if (luaMenuSelection_ < luaAppCount_) {
        luaMenuSelected_[luaMenuSelection_] =
            !luaMenuSelected_[luaMenuSelection_];
        saveLuaAppSelections();
        if (visibleMainCount() == 0) mainVisible_[1] = true;
        if (mainIndex_ < kSystemMainCount && !mainVisible_[mainIndex_])
          mainIndex_ = mainItemAtPosition(0);
      } else {
        luaMenuPicker_ = false;
        luaMenuSelection_ = 0;
        luaMenuOffset_ = 0;
        detailIndex_ = 5;
      }
      if (luaMenuSelection_ < luaMenuOffset_) luaMenuOffset_ = luaMenuSelection_;
      if (luaMenuSelection_ >= luaMenuOffset_ + 6)
        luaMenuOffset_ = luaMenuSelection_ - 5;
      return;
    }
    constexpr uint8_t kCount = 7;
    if (index == 0) {
      detailIndex_ = (detailIndex_ + kCount - 1) % kCount;
    } else if (index == 2) {
      detailIndex_ = (detailIndex_ + 1) % kCount;
    } else if (detailIndex_ < 5) {
      if (detailIndex_ == 1 && mainVisible_[1] && visibleMainCount() == 1) {
        // Keep Settings reachable as the recovery entry when every other
        // main-menu item has been hidden.
        return;
      }
      mainVisible_[detailIndex_] = !mainVisible_[detailIndex_];
      if (visibleMainCount() == 0) mainVisible_[1] = true;
      if (mainIndex_ < kSystemMainCount && !mainVisible_[mainIndex_])
        mainIndex_ = mainItemAtPosition(0);
      saveSettings();
    } else if (detailIndex_ == 5) {
      scanLuaApps();
      luaMenuPicker_ = true;
      luaMenuSelection_ = 0;
      luaMenuOffset_ = 0;
    } else {
      back();
    }
    return;
  }
  if (screen_ == Screen::Shortcuts) {
    if (shortcutPicker_) {
      const uint8_t count = shortcutActionCount();
      uint8_t position = shortcutPositionForAction(shortcutPickerAction_);
      if (index == 0 || index == 2) {
        position = (position + count + (index == 0 ? -1 : 1)) % count;
        shortcutPickerAction_ = shortcutActionAtPosition(position);
        shortcutPickerOffset_ = position > 6 ? position - 6 : 0;
      } else {
        doubleClickAction_[shortcutPickerButton_] = shortcutPickerAction_;
        if (shortcutPickerAction_ < kBaseDoubleClickActionCount) {
          doubleClickLuaAppId_[shortcutPickerButton_] = "";
        } else {
          const uint8_t appIndex = shortcutPickerAction_ -
                                   kBaseDoubleClickActionCount;
          doubleClickLuaAppId_[shortcutPickerButton_] =
              appIndex < luaAppCount_ ? luaAppIds_[appIndex] : String();
        }
        shortcutPicker_ = false;
        saveSettings();
      }
      return;
    }
    constexpr uint8_t kCount = 7;
    if (index == 0) {
      detailIndex_ = (detailIndex_ + kCount - 1) % kCount;
    } else if (index == 2) {
      detailIndex_ = (detailIndex_ + 1) % kCount;
    } else if (detailIndex_ >= 3 && detailIndex_ <= 5) {
      shortcutPickerButton_ = detailIndex_ - 3;
      shortcutPickerAction_ = doubleClickAction_[shortcutPickerButton_];
      shortcutPickerOffset_ = shortcutPositionForAction(shortcutPickerAction_) > 6
                                  ? shortcutPositionForAction(shortcutPickerAction_) - 6
                                  : 0;
      shortcutPicker_ = true;
    } else if (detailIndex_ == 6) {
      back();
    }
    return;
  }
  if (index == 2 || index == 1) back();
}

void FireOS::handleWifiButton(uint8_t index) {
  if (wifiSavedDialog_) {
    if (index == 0 || index == 2) {
      const uint8_t itemCount = wifiSavedCount_ + 4;
      if (index == 0 && wifiSavedSelection_ > 0) --wifiSavedSelection_;
      if (index == 2 && wifiSavedSelection_ + 1 < itemCount) {
        ++wifiSavedSelection_;
      }
      if (wifiSavedSelection_ < wifiSavedOffset_) {
        wifiSavedOffset_ = wifiSavedSelection_;
      } else if (wifiSavedSelection_ >= wifiSavedOffset_ + 6) {
        wifiSavedOffset_ = wifiSavedSelection_ - 5;
      }
      if (wifiSavedSelection_ < wifiSavedCount_) {
        wifiSavedTarget_ = wifiSavedSelection_;
      }
    } else if (index == 1) {
      if (wifiSavedSelection_ < wifiSavedCount_) {
        wifiSsid_ = wifiSavedSsid_[wifiSavedSelection_];
        wifiPassword_ = wifiSavedPassword_[wifiSavedSelection_];
        wifiSavedTarget_ = wifiSavedSelection_;
        wifiSavedDialog_ = false;
        wifiDeleteArmed_ = false;
        wifiMode_ = 1;
        saveSettings();
        beginWifiConnection();
      } else if (wifiSavedSelection_ == wifiSavedCount_) {
        if (wifiSavedTarget_ < wifiSavedCount_) {
          moveSelectedWifiNetwork(-1);
        }
      } else if (wifiSavedSelection_ == wifiSavedCount_ + 1) {
        if (wifiSavedTarget_ + 1 < wifiSavedCount_) {
          moveSelectedWifiNetwork(1);
        }
      } else if (wifiSavedSelection_ == wifiSavedCount_ + 2) {
        if (wifiDeleteArmed_) deleteSelectedWifiNetwork();
        else wifiDeleteArmed_ = true;
      } else {
        wifiSavedDialog_ = false;
        wifiDeleteArmed_ = false;
      }
    }
    return;
  }
  if (wifiScanDialog_) {
    if (index == 0 || index == 2) {
      if (wifiScanCount_ > 0) {
        if (index == 0 && wifiScanSelection_ > 0) --wifiScanSelection_;
        if (index == 2 && wifiScanSelection_ + 1 < wifiScanCount_) {
          ++wifiScanSelection_;
        }
        if (wifiScanSelection_ < wifiScanOffset_) {
          wifiScanOffset_ = wifiScanSelection_;
        } else if (wifiScanSelection_ >= wifiScanOffset_ + 5) {
          wifiScanOffset_ = wifiScanSelection_ - 4;
        }
      }
    } else if (index == 1) {
      wifiScanDialog_ = false;
      WiFi.scanDelete();
      wifiScanCount_ = -1;
    }
    return;
  }
  if (wifiSetupActive_) {
    if (index == 1 || index == 2) stopWifiSetup();
    return;
  }
  constexpr uint8_t kCount = 5;
  if (index == 0) {
    wifiIndex_ = (wifiIndex_ + kCount - 1) % kCount;
  } else if (index == 2) {
    wifiIndex_ = (wifiIndex_ + 1) % kCount;
  } else {
    switch (wifiIndex_) {
      case 0:
        wifiMode_ = (wifiMode_ + 1) % 3;
        saveSettings();
        applyWifiMode();
        break;
      case 1:
        scanWifiNetworks();
        break;
      case 2:
        startWifiSetup();
        break;
      case 3:
        wifiSavedDialog_ = true;
        wifiSavedSelection_ = 0;
        wifiSavedTarget_ = 0;
        wifiSavedOffset_ = 0;
        wifiDeleteArmed_ = false;
        break;
      case 4:
        stopWifiSetup();
        back();
        break;
    }
  }
}

void FireOS::handleBluetoothButton(uint8_t index) {
  constexpr uint8_t kCount = 8;
  if (index == 0) {
    bluetoothIndex_ = (bluetoothIndex_ + kCount - 1) % kCount;
  } else if (index == 2) {
    bluetoothIndex_ = (bluetoothIndex_ + 1) % kCount;
  } else {
    switch (bluetoothIndex_) {
      case 0:
        bluetoothMode_ = (bluetoothMode_ + 1) % 3;
        if (bluetoothMode_ == 1) {
          bluetoothEnabled_ = initBluetooth();
          setBluetoothVisibility(bluetoothEnabled_);
        } else {
          disconnectBluetoothDevice();
          bluetoothEnabled_ = false;
          setBluetoothVisibility(false);
#ifdef FIRE_OS_BLE
          if (bluetoothRadioReady) {
            NimBLEDevice::deinit(true);
            bluetoothRadioReady = false;
          }
#endif
        }
        saveSettings();
        bluetoothStatus_ = bluetoothMode_ == 2
                               ? "Bluetooth policy: Off"
                               : bluetoothMode_ == 0
                                     ? "Bluetooth policy: Auto"
                                     : bluetoothEnabled_
                                           ? "Bluetooth enabled"
                                           : "BLE start failed";
        break;
      case 1:
        scanBluetoothDevices();
        break;
      case 2:
        if (bluetoothScanCount_ > 0) {
          bluetoothScanSelection_ = 0;
          bluetoothScanOffset_ = 0;
          bluetoothScanDialog_ = true;
        } else {
          scanBluetoothDevices();
        }
        break;
      case 3:
        if (bluetoothSavedCount_ > 0) {
          bluetoothSavedSelection_ = 0;
          bluetoothSavedOffset_ = 0;
          bluetoothSavedDeleteArmed_ = false;
          bluetoothSavedDialog_ = true;
        } else {
          bluetoothStatus_ = "No saved devices";
        }
        break;
      case 4:
        if (bluetoothConnected_) {
          disconnectBluetoothDevice();
          bluetoothStatus_ = "Disconnected";
        } else {
          bluetoothStatus_ = "No connected devices";
        }
        break;
      case 5:
        bluetoothVisible_ = !bluetoothVisible_;
        setBluetoothVisibility(bluetoothVisible_);
        bluetoothStatus_ = bluetoothVisible_ ? "Visible to nearby devices"
                                              : "Hidden from new devices";
        break;
      case 6:
        {
          bool activeConnection = bluetoothConnected_;
#ifdef FIRE_OS_BLE
          activeConnection = activeConnection || bluetoothPeripheralConnected;
#endif
          bluetoothStatus_ = bluetoothRadioReady
                                 ? (activeConnection
                                        ? "Connected / Wi-Fi coexist"
                                        : "BLE ready / Wi-Fi coexist")
                                 : "BLE radio off";
        }
        break;
      case 7:
        back();
        break;
    }
  }
}

void FireOS::scanWifiNetworks() {
  wifiEnabled_ = true;
  WiFi.setHostname("M5Stack-FIRE");
  WiFi.mode(WIFI_STA);
  wifiScanCount_ = -1;
  wifiScanDialog_ = false;
  wifiScanActive_ = true;
  wifiOperationStarted_ = millis();
  WiFi.scanNetworks(true, true);
  wifiStatus_ = "Scanning networks...";
}

void FireOS::connectSavedWifi() {
  if (wifiSsid_.length() == 0) {
    wifiStatus_ = "No saved network";
    return;
  }
  wifiEnabled_ = true;
  wifiMode_ = 1;
  beginWifiConnection();
}

void FireOS::beginWifiConnection() {
  if (wifiSsid_.length() == 0) {
    wifiConnectActive_ = false;
    wifiStatus_ = "No saved network";
    return;
  }
  WiFi.setHostname("M5Stack-FIRE");
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  // Force a fresh association so a corrected password is used immediately.
  WiFi.disconnect(false, false);
  delay(75);
  WiFi.begin(wifiSsid_.c_str(), wifiPassword_.c_str());
  wifiConnectActive_ = true;
  wifiOperationStarted_ = millis();
  wifiStatus_ = "Connecting to " + wifiSsid_;
}

void FireOS::updateWifiState() {
  const wl_status_t status = WiFi.status();
  if (wifiScanActive_) {
    const int result = WiFi.scanComplete();
    if (result >= 0) {
      wifiScanCount_ = result;
      wifiScanActive_ = false;
      wifiScanDialog_ = true;
      wifiScanSelection_ = 0;
      wifiScanOffset_ = 0;
      wifiStatus_ = "Scan complete";
    } else if (result == WIFI_SCAN_FAILED ||
               millis() - wifiOperationStarted_ > 15000) {
      wifiScanActive_ = false;
      wifiStatus_ = "Scan failed";
      WiFi.scanDelete();
    }
  }

  if (wifiConnectActive_) {
    if (status == WL_CONNECTED) {
      wifiConnectActive_ = false;
      wifiEnabled_ = true;
      wifiStatus_ = "Connected: " + WiFi.SSID();
      stopWifiSetup();
    } else if (millis() - wifiOperationStarted_ > 15000) {
      wifiConnectActive_ = false;
      wifiStatus_ = "Connection failed: check password/network (" +
                    wifiFailureReason(status) + ")";
    }
  }

  wifiEnabled_ = WiFi.getMode() != WIFI_OFF;
  if (status == WL_CONNECTED && !wifiScanActive_ && !wifiConnectActive_) {
    wifiStatus_ = "Connected: " + WiFi.SSID();
  }
}

void FireOS::startTimeSync() {
  if (!wifiTimeSync_) return;
  if (wifiMode_ == 2) {
    timeSyncPending_ = false;
    timeSyncConfigured_ = false;
    timeSyncStatus_ = "Wi-Fi policy is Off";
    return;
  }
  timeSyncPending_ = true;
  timeSyncConfigured_ = false;
  timeSyncStarted_ = millis();
  timeSyncLastConnectAttempt_ = 0;
  timeSyncLastPollAt_ = 0;
  timeSyncStatus_ = "Waiting for Wi-Fi...";
  if (WiFi.status() != WL_CONNECTED) requestWifi(true);
}

void FireOS::updateTimeSync() {
  if (!timeSyncPending_) return;
  if (wifiMode_ == 2) {
    timeSyncPending_ = false;
    timeSyncConfigured_ = false;
    timeSyncStatus_ = "Wi-Fi policy is Off";
    return;
  }

  if (WiFi.status() != WL_CONNECTED) {
    if (wifiSsid_.length() == 0) {
      timeSyncPending_ = false;
      timeSyncConfigured_ = false;
      timeSyncStatus_ = "Connect Wi-Fi to sync time";
      return;
    }
    // Auto and On both reconnect as needed during a boot sync. The normal
    // Wi-Fi state machine may have timed out once; retry without restarting
    // the entire OS.
    if (!wifiConnectActive_ &&
        millis() - timeSyncLastConnectAttempt_ >= 5000) {
      timeSyncLastConnectAttempt_ = millis();
      beginWifiConnection();
      timeSyncStatus_ = "Connecting Wi-Fi for time...";
    }
    if (millis() - timeSyncStarted_ > 45000) {
      timeSyncPending_ = false;
      timeSyncConfigured_ = false;
      timeSyncStatus_ = "Wi-Fi time sync timed out";
    }
    return;
  }

  if (WiFi.status() == WL_CONNECTED) {
    // NTP provides UTC. configTzTime converts it to the selected local zone
    // before getLocalTime() returns the value. This avoids applying Oslo's
    // offset a second time in setSystemLocalDateTime().
    if (!timeSyncConfigured_) {
      configTzTime(dateTime_.timezoneRule(), "pool.ntp.org", "time.nist.gov",
                   "time.google.com");
      timeSyncConfigured_ = true;
      timeSyncStatus_ = "Synchronizing time...";
    }
    tm local{};
    if (millis() - timeSyncLastPollAt_ < 250) return;
    timeSyncLastPollAt_ = millis();
    if (sntp_get_sync_status() == SNTP_SYNC_STATUS_COMPLETED &&
        getLocalTime(&local, 25) && local.tm_year + 1900 >= 2020) {
      if (dateTime_.setSystemLocalDateTime(local)) {
        timeSyncLast_ = dateTime_.localDateTime();
        preferences.putString("wifi_time_last", timeSyncLast_);
        timeSyncStatus_ = "Last Wi-Fi sync: " + timeSyncLast_;
        timeSyncPending_ = false;
        timeSyncConfigured_ = false;
        if (wifiMode_ == 0) requestWifi(false);
      }
    }
  } else if (millis() - timeSyncStarted_ > 15000) {
    timeSyncStatus_ = "Connect to Wi-Fi for time sync";
    timeSyncPending_ = false;
    timeSyncConfigured_ = false;
  }
}

void FireOS::startWifiSetup() {
  wifiSetupPassword_ = "fire-connect-2026";
  wifiSetupToken_ = String(static_cast<unsigned long>(esp_random()), HEX);
  aiApiSetupActive_ = false;

  WiFi.setHostname("M5Stack-FIRE");
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAPsetHostname("M5Stack-FIRE");
  WiFi.softAP("FIRE-Setup", wifiSetupPassword_.c_str());
  wifiSetupServer.on("/", HTTP_GET, handleWifiSetupRoot);
  wifiSetupServer.on("/save", HTTP_POST, handleWifiSetupSave);
  wifiSetupServer.begin();
  wifiSetupActive_ = true;
  wifiStatus_ = "FIRE-Setup " + WiFi.softAPIP().toString();
}

void FireOS::startAiApiSetup() {
  if (wifiSetupActive_) stopWifiSetup();
  wifiSetupPassword_ = "fire-connect-2026";
  wifiSetupToken_ = String(static_cast<unsigned long>(esp_random()), HEX);
  aiApiSetupActive_ = true;
  WiFi.setHostname("M5Stack-FIRE");
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAPsetHostname("M5Stack-FIRE");
  WiFi.softAP("FIRE-Setup", wifiSetupPassword_.c_str());
  wifiSetupServer.on("/", HTTP_GET, handleWifiSetupRoot);
  wifiSetupServer.on("/save", HTTP_POST, handleWifiSetupSave);
  wifiSetupServer.on("/provision", HTTP_GET, handleWifiBackendProvision);
  wifiSetupServer.begin();
  wifiSetupActive_ = true;
}

void FireOS::stopWifiSetup() {
  if (!wifiSetupActive_) return;
  wifiSetupServer.stop();
  WiFi.softAPdisconnect(true);
  wifiSetupActive_ = false;
  aiApiSetupActive_ = false;
  wifiSetupPassword_ = "";
  wifiSetupToken_ = "";
}

void FireOS::saveWifiCredentials(const String& ssid, const String& password) {
  wifiSsid_ = ssid;
  wifiPassword_ = password;
  wifiMode_ = 1;
  wifiEnabled_ = true;
  uint8_t existing = wifiSavedCount_;
  for (uint8_t index = 0; index < wifiSavedCount_; ++index) {
    if (wifiSavedSsid_[index] == ssid) {
      existing = index;
      break;
    }
  }
  if (existing < wifiSavedCount_) {
    wifiSavedPassword_[existing] = password;
  } else {
    if (wifiSavedCount_ < 5) ++wifiSavedCount_;
    for (uint8_t index = wifiSavedCount_ - 1; index > 0; --index) {
      wifiSavedSsid_[index] = wifiSavedSsid_[index - 1];
      wifiSavedPassword_[index] = wifiSavedPassword_[index - 1];
    }
    wifiSavedSsid_[0] = ssid;
    wifiSavedPassword_[0] = password;
  }
  saveSettings();
  stopWifiSetup();
  beginWifiConnection();
}

void FireOS::saveMobileSetupFields(const String& ssid, const String& password,
                                   const String& apiKey) {
  if (ssid.length() > 0 || password.length() > 0) {
    const String newSsid = ssid.length() > 0 ? ssid : wifiSsid_;
    const String newPassword = password.length() > 0 ? password : wifiPassword_;
    if (newSsid.length() > 0) saveWifiCredentials(newSsid, newPassword);
  }
  (void)apiKey;
  aiApiKey_ = "";
  preferences.remove("openai_key");
  saveSettings();
  if (wifiSetupActive_) stopWifiSetup();
}

bool FireOS::saveBackendSetupFields(const String& host, const String& port,
                                    const String& token, const String& deviceId) {
  auto validText = [](const String& value, size_t maximum,
                      bool allowColon) {
    if (value.length() == 0 || value.length() > maximum) return false;
    for (size_t index = 0; index < value.length(); ++index) {
      const char c = value[index];
      if (static_cast<uint8_t>(c) < 0x21 || c == '\r' || c == '\n' ||
          c == '\0' || (!allowColon && c == ':'))
        return false;
    }
    return true;
  };
  auto validDeviceId = [](const String& value) {
    if (value.length() == 0 || value.length() > 64) return false;
    for (size_t index = 0; index < value.length(); ++index) {
      const char c = value[index];
      const bool ok = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ||
                      c == '_' || c == '-';
      if (!ok || (index == 0 && (c == '_' || c == '-'))) return false;
    }
    return true;
  };

  const String nextHost = host.length() > 0 ? host : backendHost_;
  const String nextToken = token.length() > 0 ? token : backendToken_;
  const String nextDevice = deviceId.length() > 0 ? deviceId : backendDeviceId_;
  uint32_t nextPort = backendPort_;
  if (port.length() > 0) {
    if (port.length() > 5) return false;
    uint32_t parsed = 0;
    for (size_t index = 0; index < port.length(); ++index) {
      if (port[index] < '0' || port[index] > '9') return false;
      parsed = parsed * 10 + static_cast<uint32_t>(port[index] - '0');
      if (parsed > 65535) return false;
    }
    if (parsed == 0) return false;
    nextPort = parsed;
  }
  if (!validText(nextHost, 128, true) || !validText(nextToken, 128, false) ||
      nextToken.length() < 24 || !validDeviceId(nextDevice))
    return false;

  // Commit all four values together only after every field is valid.
  backendHost_ = nextHost;
  backendPort_ = static_cast<uint16_t>(nextPort);
  backendToken_ = nextToken;
  backendDeviceId_ = nextDevice;
  aiApiKey_ = "";
  preferences.remove("openai_key");
  saveSettings();
  if (backendClient_) {
    reverseTransport_.configure(backendDeviceId_, backendToken_);
    backendClient_->configure(backendHost_, backendPort_, backendToken_,
                              backendDeviceId_, kFirmwareVersion);
    backendStatus_ = backendClient_->status();
  }
  if (wifiMode_ != 2 && backendHost_.length() > 0 &&
      backendToken_.length() >= 24) {
    // Backend configuration is an explicit app dependency. Auto mode may
    // keep Wi-Fi off at boot, so request it when the backend is configured.
    requestWifi(true);
  }
  return true;
}

bool FireOS::wifiSetupTokenValid(const String& token) const {
  return wifiSetupActive_ && token.length() > 0 && token == wifiSetupToken_;
}

void FireOS::requestWifi(bool enabled) {
  if (enabled) {
    wifiMode_ = wifiMode_ == 2 ? 2 : wifiMode_;
    if (wifiMode_ == 2) {
      wifiStatus_ = "Wi-Fi policy is Off";
      return;
    }
    wifiEnabled_ = true;
    if (wifiSsid_.length() > 0) beginWifiConnection();
    else applyWifiMode();
  } else {
    wifiConnectActive_ = false;
    WiFi.disconnect(false, false);
    WiFi.mode(WIFI_OFF);
    wifiEnabled_ = false;
    wifiStatus_ = "Wi-Fi off";
  }
}

void FireOS::applyWifiMode() {
  if (wifiMode_ == 2 || (wifiMode_ == 0 && !wifiConnectActive_)) {
    WiFi.disconnect(false, false);
    WiFi.mode(WIFI_OFF);
    wifiEnabled_ = false;
    return;
  }
  wifiEnabled_ = true;
  if (wifiSsid_.length() > 0) beginWifiConnection();
}

void FireOS::deleteSelectedWifiNetwork() {
  if (wifiSavedCount_ == 0 || wifiSavedTarget_ >= wifiSavedCount_) return;
  for (uint8_t index = wifiSavedTarget_; index + 1 < wifiSavedCount_; ++index) {
    wifiSavedSsid_[index] = wifiSavedSsid_[index + 1];
    wifiSavedPassword_[index] = wifiSavedPassword_[index + 1];
  }
  --wifiSavedCount_;
  if (wifiSavedCount_ == 0) {
    wifiSsid_ = "";
    wifiPassword_ = "";
    wifiConnectActive_ = false;
    WiFi.disconnect(false, false);
  } else {
    wifiSavedTarget_ = min<uint8_t>(wifiSavedTarget_, wifiSavedCount_ - 1);
    wifiSavedSelection_ = min<uint8_t>(wifiSavedSelection_, wifiSavedCount_ + 3);
    wifiSsid_ = wifiSavedSsid_[wifiSavedTarget_];
    wifiPassword_ = wifiSavedPassword_[wifiSavedTarget_];
  }
  saveSettings();
  wifiDeleteArmed_ = false;
}

void FireOS::moveSelectedWifiNetwork(int8_t direction) {
  if (wifiSavedCount_ < 2 || wifiSavedTarget_ >= wifiSavedCount_) return;
  const int target = static_cast<int>(wifiSavedTarget_) + direction;
  if (target < 0 || target >= wifiSavedCount_) return;
  String ssid = wifiSavedSsid_[wifiSavedTarget_];
  String password = wifiSavedPassword_[wifiSavedTarget_];
  wifiSavedSsid_[wifiSavedTarget_] = wifiSavedSsid_[target];
  wifiSavedPassword_[wifiSavedTarget_] = wifiSavedPassword_[target];
  wifiSavedSsid_[target] = ssid;
  wifiSavedPassword_[target] = password;
  wifiSavedTarget_ = target;
  wifiSavedSelection_ = target;
  saveSettings();
  if (wifiSsid_ == wifiSavedSsid_[target]) {
    wifiPassword_ = wifiSavedPassword_[target];
  }
}

void FireOS::scanBluetoothDevices() {
  if (bluetoothMode_ == 2) {
    bluetoothStatus_ = "Bluetooth is off";
    return;
  }
  if (!initBluetooth()) {
    bluetoothStatus_ = "BLE start failed";
    return;
  }
  bluetoothEnabled_ = true;
#ifdef FIRE_OS_BLE
  bluetoothScanDialog_ = true;
  bluetoothUnknownDialog_ = false;
  bluetoothScanSelection_ = 0;
  bluetoothScanOffset_ = 0;
  bluetoothStatus_ = "Scanning BLE...";
  bluetoothScanCount_ = 0;
  bluetoothScanInProgress_ = false;
  for (uint8_t index = 0; index < kMaxBluetoothDevices; ++index) {
    bluetoothNames_[index] = "";
    bluetoothAddresses_[index] = "";
    bluetoothRssi_[index] = 0;
    bluetoothAddressTypes_[index] = 0;
  }
  bluetoothScan->clearResults();
  // Start asynchronously. A synchronous getResults(3000) blocks the entire
  // FIRE UI loop and makes every button appear dead during the scan.
  if (!bluetoothScan->start(3000, false, true)) {
    bluetoothStatus_ = "BLE scan could not start";
    bluetoothScanDialog_ = false;
    return;
  }
  bluetoothScanInProgress_ = true;
#else
  bluetoothStatus_ = "BLE support not compiled";
  bluetoothScanCount_ = 0;
#endif
}

void FireOS::updateBluetoothScan() {
#ifdef FIRE_OS_BLE
  if (!bluetoothScanInProgress_ || !bluetoothScan) return;
  if (bluetoothScan->isScanning()) return;
  bluetoothScanInProgress_ = false;
  NimBLEScanResults results = bluetoothScan->getResults();
  const int count = results.getCount();
  bluetoothScanCount_ = min(count, static_cast<int>(kMaxBluetoothDevices));
  for (int index = 0; index < bluetoothScanCount_; ++index) {
    const NimBLEAdvertisedDevice* device = results.getDevice(index);
    bluetoothAddresses_[index] = device->getAddress().toString().c_str();
    bluetoothAddressTypes_[index] = device->getAddress().getType();
    bluetoothRssi_[index] = device->getRSSI();
    bluetoothNames_[index] = device->getName().length() > 0
                                 ? device->getName().c_str()
                                 : bluetoothAddresses_[index];
  }
  bluetoothStatus_ = count > kMaxBluetoothDevices
                         ? "Showing " + String(kMaxBluetoothDevices) + " of " +
                               String(count) + " devices"
                         : "Found " + String(count) + " BLE device(s)";
  bluetoothScan->clearResults();
  redrawRequested_ = true;
#endif
}

bool FireOS::isUnknownBluetoothDevice(uint8_t index) const {
  if (index >= bluetoothScanCount_) return true;
  const String& name = bluetoothNames_[index];
  if (name.length() == 0) return true;
  if (name.length() != 17) return false;
  for (uint8_t position = 0; position < 17; ++position) {
    if (position == 2 || position == 5 || position == 8 || position == 11 ||
        position == 14) {
      if (name[position] != ':') return false;
    } else {
      const char value = name[position];
      const bool hex = (value >= '0' && value <= '9') ||
                       (value >= 'a' && value <= 'f') ||
                       (value >= 'A' && value <= 'F');
      if (!hex) return false;
    }
  }
  return true;
}

uint8_t FireOS::bluetoothDeviceListCount(bool unknownOnly) const {
  if (unknownOnly) {
    uint8_t count = 0;
    for (uint8_t index = 0; index < bluetoothScanCount_; ++index) {
      if (isUnknownBluetoothDevice(index)) ++count;
    }
    return count;
  }

  uint8_t knownCount = 0;
  for (uint8_t index = 0; index < bluetoothScanCount_; ++index) {
    if (!isUnknownBluetoothDevice(index)) ++knownCount;
  }
  const bool hasUnknown = knownCount != bluetoothScanCount_;
  return knownCount + (hasUnknown ? 1 : 0);
}

int8_t FireOS::bluetoothDeviceListIndex(uint8_t listIndex,
                                        bool unknownOnly) const {
  if (unknownOnly) {
    uint8_t visible = 0;
    for (uint8_t index = 0; index < bluetoothScanCount_; ++index) {
      if (!isUnknownBluetoothDevice(index)) continue;
      if (visible++ == listIndex) return index;
    }
    return -1;
  }

  uint8_t knownVisible = 0;
  const bool hasUnknown = bluetoothDeviceListCount(true) > 0;
  if (hasUnknown) {
    if (listIndex == 0) return -1;  // The Unknown devices group row.
    listIndex--;
  }
  for (uint8_t index = 0; index < bluetoothScanCount_; ++index) {
    if (isUnknownBluetoothDevice(index)) continue;
    if (knownVisible++ == listIndex) return index;
  }
  return -1;
}

void FireOS::handleBluetoothScanDialogButton(uint8_t index) {
  const uint8_t deviceCount = bluetoothDeviceListCount(bluetoothUnknownDialog_);
  const uint8_t backItem = deviceCount;
  if (index == 0) {
    const uint8_t itemCount = backItem + 1;
    bluetoothScanSelection_ =
        (bluetoothScanSelection_ + itemCount - 1) % itemCount;
  } else if (index == 2) {
    const uint8_t itemCount = backItem + 1;
    bluetoothScanSelection_ = (bluetoothScanSelection_ + 1) % itemCount;
  } else {
    if (bluetoothScanSelection_ == backItem) {
      if (bluetoothUnknownDialog_) {
        bluetoothUnknownDialog_ = false;
        bluetoothScanSelection_ = 0;
        bluetoothScanOffset_ = 0;
      } else {
#ifdef FIRE_OS_BLE
        if (bluetoothScanInProgress_ && bluetoothScan) bluetoothScan->stop();
#endif
        bluetoothScanInProgress_ = false;
        bluetoothScanDialog_ = false;
      }
      return;
    }
    if (!bluetoothUnknownDialog_ &&
        bluetoothDeviceListIndex(bluetoothScanSelection_, false) < 0) {
      bluetoothUnknownDialog_ = true;
      bluetoothScanSelection_ = 0;
      bluetoothScanOffset_ = 0;
      return;
    }
    const int8_t deviceIndex = bluetoothDeviceListIndex(
        bluetoothScanSelection_, bluetoothUnknownDialog_);
    if (deviceIndex < 0) return;
    bluetoothStatus_ = "Pairing with " + bluetoothNames_[deviceIndex];
    const bool connected = connectBluetoothDevice(deviceIndex);
    bluetoothStatus_ = connected
                           ? "Connected to " +
                                 bluetoothNames_[deviceIndex]
                           : "Pairing failed - try again";
    bluetoothScanDialog_ = false;
    return;
  }
  if (bluetoothScanSelection_ < bluetoothScanOffset_) {
    bluetoothScanOffset_ = bluetoothScanSelection_;
  } else if (bluetoothScanSelection_ >= bluetoothScanOffset_ + 5) {
    bluetoothScanOffset_ = bluetoothScanSelection_ - 4;
  }
}

void FireOS::handleBluetoothSavedDialogButton(uint8_t index) {
  const uint8_t deleteItem = bluetoothSavedCount_;
  const uint8_t backItem = bluetoothSavedCount_ + 1;
  const uint8_t itemCount = backItem + 1;
  if (index == 0) {
    bluetoothSavedSelection_ =
        (bluetoothSavedSelection_ + itemCount - 1) % itemCount;
  } else if (index == 2) {
    bluetoothSavedSelection_ = (bluetoothSavedSelection_ + 1) % itemCount;
  } else if (bluetoothSavedSelection_ == deleteItem) {
    if (bluetoothSavedDeleteArmed_) {
      deleteSelectedBluetoothDevice();
    } else {
      bluetoothSavedDeleteArmed_ = true;
      bluetoothStatus_ = "Press B again to delete";
    }
  } else if (bluetoothSavedSelection_ == backItem) {
    bluetoothSavedDialog_ = false;
    bluetoothSavedDeleteArmed_ = false;
  } else {
    const uint8_t selected = bluetoothSavedSelection_;
    bluetoothStatus_ = "Connecting to " + bluetoothSavedNames_[selected];
    bluetoothScanCount_ = 1;
    bluetoothNames_[0] = bluetoothSavedNames_[selected];
    bluetoothAddresses_[0] = bluetoothSavedAddresses_[selected];
    bluetoothAddressTypes_[0] = bluetoothSavedAddressTypes_[selected];
    const bool connected = connectBluetoothDevice(0);
    bluetoothStatus_ = connected
                           ? "Connected to " + bluetoothSavedNames_[selected]
                           : "Connection failed - device unavailable";
    bluetoothSavedDialog_ = false;
  }
  if (bluetoothSavedSelection_ < bluetoothSavedOffset_) {
    bluetoothSavedOffset_ = bluetoothSavedSelection_;
  } else if (bluetoothSavedSelection_ >= bluetoothSavedOffset_ + 5) {
    bluetoothSavedOffset_ = bluetoothSavedSelection_ - 4;
  }
}

bool FireOS::initBluetooth() {
#ifdef FIRE_OS_BLE
  if (bluetoothRadioReady) return true;
  NimBLEDevice::init("M5Stack-FIRE");
  NimBLEDevice::setSecurityAuth(true, true, true);
  NimBLEDevice::setPower(ESP_PWR_LVL_N0);
  bluetoothServer = NimBLEDevice::createServer();
  bluetoothServer->setCallbacks(new FireBluetoothServerCallbacks());
  NimBLEService* service = bluetoothServer->createService(kBluetoothServiceUuid);
  bluetoothCharacteristic = service->createCharacteristic(
      kBluetoothCharacteristicUuid,
      NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::NOTIFY);
  bluetoothCharacteristic->setCallbacks(new FireBluetoothCallbacks());
  bluetoothCharacteristic->setValue("FIRE OS BLE");
  bluetoothServer->start();
  NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();
  advertising->addServiceUUID(kBluetoothServiceUuid);
  advertising->start();
  bluetoothScan = NimBLEDevice::getScan();
  bluetoothScan->setActiveScan(true);
  bluetoothScan->setMaxResults(40);
  bluetoothRadioReady = true;
  bluetoothStatus_ = "BLE ready / Hidden";
  return true;
#else
  return false;
#endif
}

bool FireOS::connectBluetoothDevice(uint8_t index) {
#ifdef FIRE_OS_BLE
  if (index >= bluetoothScanCount_ || bluetoothAddresses_[index].length() == 0 ||
      !initBluetooth()) {
    return false;
  }
  if (bluetoothClient != nullptr && bluetoothClient->isConnected()) {
    bluetoothClient->disconnect();
  }
  bluetoothClient = NimBLEDevice::createClient();
  if (!bluetoothClient->connect(
          NimBLEAddress(std::string(bluetoothAddresses_[index].c_str()),
                        bluetoothAddressTypes_[index]))) {
    bluetoothClient = nullptr;
    bluetoothConnected_ = false;
    return false;
  }
  bluetoothConnected_ = true;
  bluetoothSavedName_ = bluetoothNames_[index];
  bluetoothSavedAddress_ = bluetoothAddresses_[index];
  uint8_t savedIndex = bluetoothSavedCount_;
  for (uint8_t item = 0; item < bluetoothSavedCount_; ++item) {
    if (bluetoothSavedAddresses_[item] == bluetoothAddresses_[index]) {
      savedIndex = item;
      break;
    }
  }
  if (savedIndex >= kMaxBluetoothSavedDevices) {
    savedIndex = kMaxBluetoothSavedDevices - 1;
  }
  if (savedIndex == bluetoothSavedCount_ &&
      bluetoothSavedCount_ < kMaxBluetoothSavedDevices) {
    ++bluetoothSavedCount_;
  }
  bluetoothSavedNames_[savedIndex] = bluetoothNames_[index];
  bluetoothSavedAddresses_[savedIndex] = bluetoothAddresses_[index];
  bluetoothSavedAddressTypes_[savedIndex] = bluetoothAddressTypes_[index];
  saveSettings();
  return true;
#else
  return false;
#endif
}

void FireOS::disconnectBluetoothDevice() {
#ifdef FIRE_OS_BLE
  if (bluetoothClient != nullptr && bluetoothClient->isConnected()) {
    bluetoothClient->disconnect();
  }
#endif
  bluetoothConnected_ = false;
}

void FireOS::deleteSelectedBluetoothDevice() {
  if (bluetoothSavedCount_ == 0 ||
      bluetoothSavedSelection_ >= bluetoothSavedCount_) {
    return;
  }
  for (uint8_t index = bluetoothSavedSelection_;
       index + 1 < bluetoothSavedCount_; ++index) {
    bluetoothSavedNames_[index] = bluetoothSavedNames_[index + 1];
    bluetoothSavedAddresses_[index] = bluetoothSavedAddresses_[index + 1];
    bluetoothSavedAddressTypes_[index] = bluetoothSavedAddressTypes_[index + 1];
  }
  --bluetoothSavedCount_;
  bluetoothSavedSelection_ = min<uint8_t>(bluetoothSavedSelection_,
                                          bluetoothSavedCount_ == 0
                                              ? 0
                                              : bluetoothSavedCount_ - 1);
  bluetoothSavedDeleteArmed_ = false;
  saveSettings();
  bluetoothStatus_ = "Saved device deleted";
}

void FireOS::setBluetoothVisibility(bool visible) {
#ifdef FIRE_OS_BLE
  if (!bluetoothRadioReady || bluetoothMode_ == 2) {
    bluetoothVisible_ = false;
    return;
  }
  NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();
  if (visible) {
    advertising->start();
    bluetoothVisible_ = true;
    bluetoothStatus_ = "Visible / accepting connections";
  } else {
    advertising->stop();
    bluetoothVisible_ = false;
    bluetoothStatus_ = bluetoothPeripheralConnected || bluetoothConnected_
                           ? "Connected / hidden"
                           : "Ready / hidden";
  }
#else
  bluetoothVisible_ = false;
#endif
}

void FireOS::closeBluetoothSettings() {
#ifdef FIRE_OS_BLE
  if (bluetoothScanInProgress_ && bluetoothScan) bluetoothScan->stop();
#endif
  bluetoothScanInProgress_ = false;
  bluetoothBootInitPending_ = false;
  bluetoothScanDialog_ = false;
  bluetoothUnknownDialog_ = false;
  setBluetoothVisibility(false);
#ifdef FIRE_OS_BLE
  if (bluetoothRadioReady && bluetoothMode_ != 1 && !bluetoothConnected_ &&
      !bluetoothPeripheralConnected) {
    NimBLEDevice::deinit(true);
    bluetoothRadioReady = false;
    bluetoothEnabled_ = false;
  }
#endif
}

void FireOS::handleQuickButton(uint8_t index) {
  if (quickEditing_) {
    if (index == 0 || index == 2) {
      const int8_t direction = index == 0 ? -1 : 1;
      if (quickIndex_ == 0) {
        brightnessStep_ = (brightnessStep_ + kBrightnessStepCount + direction) %
                          kBrightnessStepCount;
        brightness_ = kBrightnessValues[brightnessStep_];
        M5.Display.setBrightness(brightness_);
      } else if (quickIndex_ == 1) {
        volumeStep_ = (volumeStep_ + kVolumeStepCount + direction) %
                      kVolumeStepCount;
        volume_ = volumeValue(volumeStep_);
        M5.Speaker.setVolume(speakerVolumeValue(volume_));
      }
      saveSettings();
    } else if (index == 1) {
      quickEditing_ = false;
      saveSettings();
    }
    return;
  }

  if (index == 0) {
    quickIndex_ = (quickIndex_ + kQuickCount - 1) % kQuickCount;
  } else if (index == 2) {
    quickIndex_ = (quickIndex_ + 1) % kQuickCount;
  } else {
    switch (quickIndex_) {
      case 0:
        quickEditing_ = true;
        break;
      case 1:
        quickEditing_ = true;
        break;
      case 2:
        wifiMode_ = (wifiMode_ + 1) % 3;
        saveSettings();
        applyWifiMode();
        break;
      case 3:
        bluetoothMode_ = (bluetoothMode_ + 1) % 3;
        if (bluetoothMode_ == 1) {
          bluetoothEnabled_ = initBluetooth();
        } else {
          disconnectBluetoothDevice();
          bluetoothEnabled_ = false;
          setBluetoothVisibility(false);
#ifdef FIRE_OS_BLE
          if (bluetoothRadioReady && bluetoothMode_ == 2) {
            NimBLEDevice::deinit(true);
            bluetoothRadioReady = false;
          }
#endif
        }
        saveSettings();
        break;
      case 4:
        open(Screen::FileExplorer);
        break;
      case 5:
        powerActionIndex_ = 0;
        open(Screen::PowerActions);
        break;
      case 6:
        open(Screen::Settings);
        break;
      case 7:
        screen_ = previousScreen_;
        break;
    }
  }
}

void FireOS::handleFactoryResetButton(uint8_t index) {
  if (index == 0) {
    home();
  } else if (index == 2) {
    back();
  } else if (factoryResetArmed_) {
    resetSettings();
    home();
  } else {
    factoryResetArmed_ = true;
  }
}

void FireOS::handlePowerButton(uint8_t index) {
  if (powerEditing_) {
    if (index == 0 || index == 2) {
      const int8_t direction = index == 0 ? -1 : 1;
      if (powerIndex_ == 2) {
        sleepOption_ = (sleepOption_ + kDurationCount + direction) %
                       kDurationCount;
      } else if (powerIndex_ == 3) {
        dimOption_ = (dimOption_ + kDurationCount + direction) % kDurationCount;
      } else if (powerIndex_ == 4) {
        screenOffOption_ = (screenOffOption_ + kDurationCount + direction) %
                           kDurationCount;
      }
    } else if (index == 1) {
      powerEditing_ = false;
      saveSettings();
    }
    return;
  }

  if (index == 0) {
    powerIndex_ = (powerIndex_ + kPowerCount - 1) % kPowerCount;
  } else if (index == 2) {
    powerIndex_ = (powerIndex_ + 1) % kPowerCount;
  } else {
    switch (powerIndex_) {
      case 0:
        ESP.restart();
        break;
      case 1:
        M5.Power.powerOff();
        break;
      case 2:
        powerEditing_ = true;
        break;
      case 3:
        powerEditing_ = true;
        break;
      case 4:
        powerEditing_ = true;
        break;
      case 5:
        back();
        break;
    }
  }
}

void FireOS::handlePowerActionsButton(uint8_t index) {
  if (index == 0) {
    powerActionIndex_ = (powerActionIndex_ + kPowerActionCount - 1) %
                        kPowerActionCount;
  } else if (index == 2) {
    powerActionIndex_ = (powerActionIndex_ + 1) % kPowerActionCount;
  } else if (powerActionIndex_ == 0) {
    M5.Power.powerOff();
  } else if (powerActionIndex_ == 1) {
    ESP.restart();
  } else if (powerActionIndex_ == 2) {
    enterLightSleep();
  } else {
    back();
  }
}

void FireOS::manageDisplayPower() {
  const bool activeWork = aiAudioCaptureActive_ || aiAudioOutputActive_ ||
                          (packageManager_ && packageManager_->busy()) ||
                          luaAppActive_ ||
                          (screen_ == Screen::AiDeveloper &&
                           aiWorkflowState_ > 0 &&
                           aiWorkflowState_ < 5);
  if (activeWork) {
    // Conversation/audio/install work is a power-management wakelock. Do not
    // let a short user-configured timer kill the operation mid-transaction.
    lastActivity_ = millis();
    if (displayPowerState_ != 0) wakeDisplay();
    return;
  }
  const uint32_t idleMs = millis() - lastActivity_;
  const uint32_t dimMs = static_cast<uint32_t>(kDurationMinutes[dimOption_]) * 60000UL;
  const uint32_t offMs = static_cast<uint32_t>(kDurationMinutes[screenOffOption_]) * 60000UL;
  const uint32_t sleepMs = static_cast<uint32_t>(kDurationMinutes[sleepOption_]) * 60000UL;

  if (sleepMs > 0 && idleMs >= sleepMs) {
    M5.Power.powerOff();
    return;
  }

  if (offMs > 0 && idleMs >= offMs && displayPowerState_ < 2) {
    M5.Display.setBrightness(0);
    displayPowerState_ = 2;
  } else if (dimMs > 0 && idleMs >= dimMs && displayPowerState_ == 0) {
    M5.Display.setBrightness(max<uint8_t>(8, brightness_ / 3));
    displayPowerState_ = 1;
  }
}

void FireOS::wakeDisplay() {
  lastActivity_ = millis();
  displayPowerState_ = 0;
  M5.Display.setBrightness(brightness_);
}

void FireOS::enterLightSleep() {
  if (digitalRead(kButtonPins[0]) == LOW || digitalRead(kButtonPins[1]) == LOW ||
      digitalRead(kButtonPins[2]) == LOW) {
    return;
  }
  M5.Display.setBrightness(0);
  displayPowerState_ = 2;
  for (const uint8_t pin : kButtonPins) {
    gpio_wakeup_enable(static_cast<gpio_num_t>(pin), GPIO_INTR_LOW_LEVEL);
  }
  esp_sleep_enable_gpio_wakeup();
  esp_light_sleep_start();
  esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_GPIO);
  wakeDisplay();
}

void FireOS::adjustDateField(int8_t amount) {
  switch (dateField_) {
    case 0:
      break;
    case 1:
      break;
    case 2:
      editYear_ = constrain(static_cast<int>(editYear_) + amount, 2020, 2099);
      break;
    case 3:
      editMonth_ = (editMonth_ - 1 + amount + 12) % 12 + 1;
      clampDate();
      break;
    case 4:
      editDay_ = (editDay_ - 1 + amount + daysInMonth(editYear_, editMonth_)) %
                     daysInMonth(editYear_, editMonth_) +
                 1;
      break;
    case 5:
      editHour_ = (editHour_ + 24 + amount) % 24;
      break;
    case 6:
      editMinute_ = (editMinute_ + 60 + amount) % 60;
      break;
    case 7:
      editTimezone_ = (editTimezone_ + kTimezoneCount + amount) % kTimezoneCount;
      break;
    case 8:
      editDstAuto_ = !editDstAuto_;
      break;
  }
}

void FireOS::clampDate() {
  editDay_ = min<uint8_t>(editDay_, daysInMonth(editYear_, editMonth_));
}

void FireOS::commitDateTime() {
  dateTime_.setTimezone(editTimezone_);
  dateTime_.setDstAuto(editDstAuto_);
  if (dateTime_.setLocalDateTime(editYear_, editMonth_, editDay_, editHour_,
                                 editMinute_)) {
    dateTime_.save();
  }
}

void FireOS::resetSettings() {
  stopWifiSetup();
  preferences.clear();
  brightnessStep_ = 6;
  volumeStep_ = 8;
  brightness_ = kBrightnessValues[brightnessStep_];
  volume_ = volumeValue(volumeStep_);
  sleepOption_ = 0;
  dimOption_ = 5;
  screenOffOption_ = 10;
  doubleClickAction_[0] = 0;
  doubleClickAction_[1] = 0;
  doubleClickAction_[2] = 0;
  buttonSoundsEnabled_ = true;
  bootRgbPulse_ = true;
  bootMelody_ = true;
  selectedBootAppPath_ = "";
  mainVisible_[0] = true;
  mainVisible_[1] = true;
  mainVisible_[2] = true;
  mainVisible_[3] = true;
  mainVisible_[4] = true;
  wifiEnabled_ = false;
  wifiMode_ = 0;
  wifiTimeSync_ = false;
  timeSyncPending_ = false;
  timeSyncConfigured_ = false;
  timeSyncStatus_ = "";
  timeSyncLast_ = "";
  wifiSsid_ = "";
  wifiPassword_ = "";
  aiApiKey_ = "";
  pendingDiagnosticAppId_ = "";
  pendingDiagnosticPackageId_ = "";
  pendingDiagnosticErrorCode_ = "";
  pendingDiagnosticMessage_ = "";
  pendingDiagnosticJson_ = "";
  wifiSavedCount_ = 0;
  wifiSavedSelection_ = 0;
  wifiSavedTarget_ = 0;
  wifiSavedOffset_ = 0;
  wifiSavedDialog_ = false;
  wifiDeleteArmed_ = false;
  wifiStatus_ = "Wi-Fi off";
  wifiScanActive_ = false;
  wifiScanDialog_ = false;
  wifiConnectActive_ = false;
  wifiScanCount_ = -1;
  WiFi.scanDelete();
  WiFi.disconnect(true, true);
  WiFi.setHostname("M5Stack-FIRE");
  WiFi.mode(WIFI_OFF);
  bluetoothEnabled_ = false;
  bluetoothVisible_ = false;
  bluetoothRadioReady = false;
  bluetoothScanCount_ = -1;
  bluetoothSavedCount_ = 0;
  bluetoothSavedDialog_ = false;
  bluetoothSavedDeleteArmed_ = false;
  bluetoothStatus_ = "Bluetooth unavailable";
#ifdef FIRE_OS_BLE
  bluetoothPeripheralConnected = false;
#endif
  M5.Display.setBrightness(brightness_);
  M5.Speaker.setVolume(speakerVolumeValue(volume_));
  displayPowerState_ = 0;
  lastActivity_ = millis();
  dateTime_.reset();
}

void FireOS::setWifi(bool enabled) {
  wifiEnabled_ = enabled;
  if (enabled) {
    wifiMode_ = 1;
    if (wifiSsid_.length() > 0) {
      beginWifiConnection();
    } else {
      WiFi.setHostname("M5Stack-FIRE");
      WiFi.mode(WIFI_STA);
      wifiConnectActive_ = false;
      wifiStatus_ = "Wi-Fi on; no saved network";
    }
  } else {
    wifiMode_ = 2;
    stopWifiSetup();
    wifiConnectActive_ = false;
    WiFi.scanDelete();
    WiFi.disconnect(true, true);
    WiFi.mode(WIFI_OFF);
    wifiStatus_ = "Wi-Fi off";
  }
  saveSettings();
}

void FireOS::draw() {
  lastDrawAt_ = millis();
  redrawRequested_ = false;
  if (screen_ == Screen::FileExplorer && sdImagePreview_ && sdImageRendered_) {
    return;
  }
  ui.fillSprite(kBg);
  if (screen_ == Screen::QuickSettings) {
    drawScreen(previousScreen_);
    drawQuickSettings();
  } else {
    drawScreen(screen_);
  }
  ui.pushSprite(0, 0);
  if (screen_ == Screen::FileExplorer && sdImagePreview_) {
    M5.Display.fillRect(0, 28, 320, 188, kBg);
    bool drawn = false;
    if (!sdImageBuffer_ || sdImageBufferSize_ == 0) {
      M5.Display.setTextColor(TFT_ORANGE, kBg);
      M5.Display.drawString("Image buffer unavailable", 24, 100);
      sdImageRendered_ = true;
      return;
    }
    if (sdImagePreviewType_ == 1) {
      drawn = M5.Display.drawJpg(sdImageBuffer_, sdImageBufferSize_, 10, 30,
                                 300, 182, 0, 0, 1.0f, 0.0f);
    } else if (sdImagePreviewType_ == 2) {
      drawn = M5.Display.drawPng(sdImageBuffer_, sdImageBufferSize_, 10, 30,
                                 300, 182, 0, 0, 1.0f, 0.0f);
    } else if (sdImagePreviewType_ == 3) {
      drawn = M5.Display.drawBmp(sdImageBuffer_, sdImageBufferSize_, 10, 30,
                                 300, 182, 0, 0, 1.0f, 0.0f);
    }
    if (!drawn) {
      M5.Display.setTextColor(TFT_ORANGE, kBg);
      M5.Display.drawString("Image preview failed", 24, 100);
    }
    sdImageRendered_ = true;
  }
}

void FireOS::drawScreen(Screen screen) {
  switch (screen) {
    case Screen::Main:
      drawMain();
      break;
    case Screen::Apps:
      drawApps();
      break;
    case Screen::Settings:
      drawSettings();
      break;
    case Screen::DateTime:
      drawDateTime();
      break;
    case Screen::DisplaySound:
      drawDisplaySound();
      break;
    case Screen::Wifi:
      drawWifi();
      break;
    case Screen::Bluetooth:
      drawBluetooth();
      break;
    case Screen::Boot:
      drawBoot();
      break;
    case Screen::Firmware:
      drawFirmware();
      break;
    case Screen::MainMenuSettings:
      drawMainMenuSettings();
      break;
    case Screen::Shortcuts:
      drawShortcuts();
      break;
    case Screen::AppsSettings:
      drawAppsSettingsBackend();
      break;
    case Screen::Help:
      drawHelp();
      break;
    case Screen::QuickSettings:
      break;
    case Screen::Placeholder:
      drawPlaceholder();
      break;
    case Screen::Debug:
      drawDebug();
      break;
    case Screen::SystemInfo:
      drawSystemInfo();
      break;
    case Screen::Power:
      drawPower();
      break;
    case Screen::PowerActions:
      drawPowerActions();
      break;
    case Screen::FactoryReset:
      drawFactoryReset();
      break;
    case Screen::FileExplorer:
      drawFileExplorer();
      break;
    case Screen::AiDeveloper:
      drawAiDeveloper();
      break;
    case Screen::AiApi:
      drawAiApi();
      break;
    case Screen::LuaApp:
      drawLuaApp();
      break;
  }
}

void FireOS::drawStatusBar(const char* title) {
  (void)title;
  ui.fillRect(0, 0, 320, 28, kPanel);
  const String statusDateTime = dateTime_.statusDateTime();
  const String clock = statusDateTime.substring(0, 5);
  drawText(6, 9, clock, TFT_WHITE, 1, kPanel);
  drawText(7, 9, clock, TFT_WHITE, 1, kPanel);  // compact bold clock
  ui.setTextDatum(MC_DATUM);
  drawText(160, 14, statusDateTime.substring(8), TFT_WHITE, 1, kPanel);
  ui.setTextDatum(TL_DATUM);
  const uint8_t wifiState = WiFi.status() == WL_CONNECTED
                                ? 2
                                : (wifiConnectActive_ || wifiScanActive_ ||
                                   wifiSetupActive_)
                                      ? 1
                                      : 0;
  drawWifiIcon(252, 6, wifiState);
  drawBluetoothIcon(276, 5, bluetoothEnabled_);
  drawBatteryIcon(298, 6, batteryLevel(), batteryCharging());
}

void FireOS::drawFooter(const char* left, const char* middle, const char* right) {
  ui.fillRect(0, 216, 320, 24, kPanel);
  drawText(8, 222, cleanFooterLabel(left), kMuted, 1, kPanel);
  ui.setTextDatum(MC_DATUM);
  drawText(160, 222, cleanFooterLabel(middle), TFT_WHITE, 1, kPanel);
  ui.setTextDatum(MR_DATUM);
  drawText(312, 222, cleanFooterLabel(right), kMuted, 1, kPanel);
  ui.setTextDatum(TL_DATUM);
}

void FireOS::drawMain() {
  drawStatusBar(safeMode_ ? "FIRE OS  SAFE" : "FIRE OS");
  // Visibility can change in Menu Layout while the previous carousel index is
  // still cached. Normalize before drawing so a hidden card is never shown at
  // boot or after returning Home.
  if (mainIndex_ < kSystemMainCount && !mainVisible_[mainIndex_])
    mainIndex_ = mainItemAtPosition(0);
  constexpr int32_t kLargeCard = 150;
  constexpr int32_t kSmallCard = 58;
  constexpr int32_t kCenterX = 160;
  constexpr int32_t kCenterY = 120;
  if (carouselAnimating_) {
    const uint8_t previous = nextVisibleMain(carouselToIndex_, -1);
    const uint8_t next = nextVisibleMain(carouselToIndex_, 1);
    if (visibleMainCount() > 1) {
      drawMainCard(previous, 48 - kSmallCard / 2, kCenterY - kSmallCard / 2,
                   kSmallCard);
      drawMainCard(next, 272 - kSmallCard / 2, kCenterY - kSmallCard / 2,
                   kSmallCard);
    }
    const int32_t oldSize = kLargeCard -
                            (kLargeCard - kSmallCard) * carouselOffset_ /
                                kCarouselDistance;
    const int32_t newSize = kSmallCard +
                            (kLargeCard - kSmallCard) * carouselOffset_ /
                                kCarouselDistance;
    const int32_t oldCenter = kCenterX + carouselDirection_ * carouselOffset_;
    const int32_t newCenter = kCenterX - carouselDirection_ *
                                          (kCarouselDistance - carouselOffset_);
    drawMainCard(carouselFromIndex_, oldCenter - oldSize / 2,
                 kCenterY - oldSize / 2, oldSize);
    drawMainCard(carouselToIndex_, newCenter - newSize / 2,
                 kCenterY - newSize / 2, newSize);
  } else {
    const uint8_t previous = nextVisibleMain(mainIndex_, -1);
    const uint8_t next = nextVisibleMain(mainIndex_, 1);
    if (visibleMainCount() > 1) {
      drawMainCard(previous, 48 - kSmallCard / 2, kCenterY - kSmallCard / 2,
                   kSmallCard);
      drawMainCard(next, 272 - kSmallCard / 2, kCenterY - kSmallCard / 2,
                   kSmallCard);
    }
    drawMainCard(mainIndex_, kCenterX - kLargeCard / 2,
                 kCenterY - kLargeCard / 2, kLargeCard);
  }
  ui.setTextDatum(TL_DATUM);
  const uint8_t count = visibleMainCount();
  const int firstDot = 160 - static_cast<int>(count - 1) * 5;
  for (uint8_t position = 0; position < count; ++position) {
    const uint8_t item = mainItemAtPosition(position);
    const uint16_t color = item == 0 ? kCyan
                          : item == 1 ? kPurple
                          : item == 2 ? kOrange
                          : item == 3 ? kGreen
                          : kCyan;
    ui.fillCircle(firstDot + position * 10, 207, 3,
                  item == mainIndex_ ? color : kMuted);
  }
  drawFooter("Previous", "Open", "Next");
}

void FireOS::drawMainCard(uint8_t item, int32_t x, int32_t y, int32_t size) {
  const uint16_t accent = item == 0 ? kCyan
                        : item == 1 ? kPurple
                        : item == 2 ? kOrange
                        : item == 3 ? kGreen
                        : item >= kSystemMainCount ? kCyan
                                                    : kCyan;
  const bool large = size >= 100;
  const int32_t centerX = x + size / 2;
  const int32_t centerY = y + size / 2;
  const int32_t iconCenterY = large ? centerY : y + size - 20;
  ui.setTextDatum(MC_DATUM);
  String title = item == 0 ? "Apps"
                : item == 1 ? "Settings"
                : item == 2 ? "Power"
                : item == 3 ? "Files"
                : item == 4 ? "AI Developer"
                : (item - kSystemMainCount < luaAppCount_
                       ? luaAppDisplayNames_[item - kSystemMainCount]
                       : String("App"));
  if (title.length() > (large ? 14 : 9))
    title = title.substring(0, large ? 14 : 9);
  drawText(centerX, y + (large ? 20 : 11), title, TFT_WHITE,
           large ? 2 : 1, kBg);
  const int iconSize = large ? 78 : 36;
  ui.fillRoundRect(centerX - iconSize / 2, iconCenterY - iconSize / 2,
                   iconSize, iconSize, large ? 10 : 6, kBg);
  ui.drawRoundRect(centerX - iconSize / 2, iconCenterY - iconSize / 2,
                   iconSize, iconSize, large ? 10 : 6, accent);

  if (item == 0) {
    const int tile = large ? 22 : 9;
    const int gap = large ? 5 : 3;
    const int startX = centerX - tile - gap / 2;
    const int startY = iconCenterY - tile - gap / 2;
    for (uint8_t row = 0; row < 2; ++row) {
      for (uint8_t column = 0; column < 2; ++column) {
        ui.fillRoundRect(startX + column * (tile + gap),
                         startY + row * (tile + gap), tile, tile,
                         large ? 5 : 3, accent);
      }
    }
  } else if (item == 1) {
    const int radius = large ? 25 : 12;
    ui.drawCircle(centerX, iconCenterY, radius, accent);
    ui.drawCircle(centerX, iconCenterY, large ? 9 : 5, accent);
    const int tooth = large ? 10 : 6;
    ui.fillRect(centerX - tooth / 2, iconCenterY - radius - 4, tooth, tooth,
                accent);
    ui.fillRect(centerX - tooth / 2, iconCenterY + radius - 5, tooth, tooth,
                accent);
    ui.fillRect(centerX - radius - 4, iconCenterY - tooth / 2, tooth, tooth,
                accent);
    ui.fillRect(centerX + radius - 5, iconCenterY - tooth / 2, tooth, tooth,
                accent);
  } else if (item == 2) {
    const int radius = large ? 26 : 13;
    ui.drawCircle(centerX, iconCenterY, radius, accent);
    ui.drawLine(centerX, iconCenterY - radius - 8, centerX, iconCenterY, accent);
    ui.drawArc(centerX, iconCenterY, radius - 5, radius - 5, 45, 315, accent);
  } else if (item == 3) {
    const int width = large ? 54 : 26;
    const int height = large ? 42 : 21;
    ui.drawRoundRect(centerX - width / 2, iconCenterY - height / 2,
                     width, height, large ? 5 : 3, accent);
    ui.drawLine(centerX - width / 2, iconCenterY - height / 2 + 7,
                centerX + width / 2, iconCenterY - height / 2 + 7, accent);
    ui.drawLine(centerX - width / 2 + 8, iconCenterY - height / 2,
                centerX - width / 2 + 14, iconCenterY - height / 2 - 6,
                accent);
  } else if (item == 4) {
    const int radius = large ? 25 : 12;
    ui.drawCircle(centerX, iconCenterY, radius, accent);
    ui.fillCircle(centerX - (large ? 9 : 5), iconCenterY - (large ? 5 : 3),
                  large ? 4 : 2, accent);
    ui.fillCircle(centerX + (large ? 9 : 5), iconCenterY - (large ? 5 : 3),
                  large ? 4 : 2, accent);
    ui.drawArc(centerX, iconCenterY + (large ? 5 : 3), large ? 14 : 7,
               large ? 8 : 4, 205, 335, accent);
  } else {
    const int dot = large ? 9 : 4;
    const int gap = large ? 16 : 8;
    for (uint8_t row = 0; row < 2; ++row) {
      for (uint8_t column = 0; column < 2; ++column) {
        ui.fillCircle(centerX - gap / 2 + column * gap,
                      iconCenterY - gap / 2 + row * gap, dot / 2, accent);
      }
    }
  }

  ui.setTextDatum(TL_DATUM);
}

void FireOS::drawApps() {
  drawStatusBar("Apps");
  drawText(16, 35, "SD /apps", kMuted, 1);
  const uint8_t appCount = externalAppCount_ + luaAppCount_;
  const uint8_t itemCount = appCount + 1;
  const uint8_t visible = min<uint8_t>(5, itemCount - externalAppOffset_);
  for (uint8_t row = 0; row < visible; ++row) {
    const uint8_t item = externalAppOffset_ + row;
    const int y = 60 + row * 25;
    const bool selected = item == externalAppSelection_;
    if (selected) ui.fillRoundRect(12, y - 3, 296, 21, 4, kCyan);
    if (item == appCount) {
      drawText(22, y + 1, "Back", selected ? kBg : kText, 1,
               selected ? kCyan : kBg);
      continue;
    }
    const bool luaApp = item >= externalAppCount_;
    const uint8_t appIndex = luaApp ? item - externalAppCount_ : item;
    String name = luaApp ? luaAppNames_[appIndex] : externalAppNames_[appIndex];
    if (name.length() > 28) name = name.substring(0, 25) + "...";
    const uint16_t nameColor = selected
                                   ? kBg
                                   : (luaApp || externalAppCompatible_[appIndex] ? kText
                                                                   : kOrange);
    drawText(22, y + 1, name, nameColor, 1,
             selected ? kCyan : kBg);
    ui.setTextDatum(MR_DATUM);
    drawText(300, y + 1,
             luaApp ? "Lua" : formatBytes(externalAppSizes_[appIndex]),
             selected ? kBg
                      : (luaApp || externalAppCompatible_[appIndex] ? kMuted : kOrange),
             1, selected ? kCyan : kBg);
    ui.setTextDatum(TL_DATUM);
  }
  if (appCount == 0)
    drawText(18, 182, "No apps in /apps; select Back", kMuted, 1);
  if (externalAppMessage_.length() > 0) {
    drawText(16, 190, externalAppMessage_, kOrange, 1);
  }
  drawFooter("A  UP", "B  OPEN", "DOWN  C");
}

void FireOS::drawSettings() {
  static const char* labels[kSettingsCount] = {
      "Date / Time",       "Display & Sound", "Wi-Fi",       "Bluetooth",
      "File Explorer",     "Boot",             "Firmware",      "Menu Layout",
      "Shortcuts",         "App Manager",      "Debug",         "System Info",
      "Help",              "Factory Reset",    "AI settings",   "Power",
      "Back",
  };
  drawStatusBar("Settings");
  drawText(16, 37, "System settings", kMuted, 1);
  String backend = "Backend: ";
  if (backendClient_ && backendClient_->sessionReady()) {
    backend += "connected";
  } else if (!backendClient_ || !backendClient_->configured()) {
    backend += "not configured";
  } else {
    backend += backendStatus_.length() > 21 ? backendStatus_.substring(0, 21)
                                            : backendStatus_;
  }
  if (backend.length() > 35) backend = backend.substring(0, 35);
  drawText(16, 49, backend,
           backendClient_ && backendClient_->sessionReady() ? kGreen : kMuted,
           1);
  const uint8_t first = settingsIndex_ < 5 ? 0 : settingsIndex_ - 4;
  for (uint8_t row = 0; row < 6; ++row) {
    const uint8_t item = first + row;
    if (item >= kSettingsCount) break;
    drawRow(row, labels[item], item == settingsIndex_);
  }
  drawFooter("A  UP", "B  OPEN", "DOWN  C");
}

void FireOS::drawDateTime() {
  static const char* fields[] = {"Wi-Fi sync", "Sync now", "Year", "Month",
                                 "Day",       "Hour",     "Minute", "Timezone",
                                 "Summer time", "Save",    "Back"};
  drawStatusBar("Date / Time");
  drawText(16, 31, dateTime_.localDateTime(), TFT_WHITE, 1);
  String status = timeSyncPending_ ? timeSyncStatus_ : timeSyncLast_;
  if (!timeSyncPending_ && status.length() > 0) {
    status = "Last Wi-Fi sync: " + status;
  }
  if (status.length() == 0) {
    status = wifiTimeSync_ ? "Wi-Fi sync enabled" : "Wi-Fi sync disabled";
  }
  if (status.length() > 38) status = status.substring(0, 38);
  drawText(16, 47, status, timeSyncPending_ ? kCyan : kMuted, 1);
  String values[] = {wifiTimeSync_ ? "On" : "Off", "", String(editYear_),
                     String(editMonth_), String(editDay_), String(editHour_),
                     String(editMinute_), dateTime_.timezoneLabel(editTimezone_),
                     editDstAuto_ ? "Auto" : "Off", "", ""};
  for (uint8_t row = 0; row < kDateFieldCount; ++row) {
    const int y = 62 + row * 14;
    const bool selected = row == dateField_;
    const uint16_t highlight = dateEditing_ && row == dateField_ ? kOrange : kCyan;
    if (selected) ui.fillRoundRect(10, y - 1, 300, 14, 4, highlight);
    drawText(18, y + 1, fields[row], selected ? kBg : kText, 1,
             selected ? highlight : kBg);
    ui.setTextDatum(MR_DATUM);
    drawText(302, y + 1, values[row], selected ? kBg : TFT_WHITE, 1,
             selected ? highlight : kBg);
    ui.setTextDatum(TL_DATUM);
  }
  drawFooter("Previous", dateEditing_ ? "Finish" : "Edit", "Next");
}

void FireOS::drawDisplaySound() {
  drawStatusBar("Display & Sound");
  drawLevelRow(0, "Brightness", brightnessStep_, kBrightnessStepCount,
               detailIndex_ == 0, kCyan, detailEditing_ && detailIndex_ == 0);
  drawLevelRow(1, "Volume", volumeStep_, kVolumeStepCount, detailIndex_ == 1,
               kGreen, detailEditing_ && detailIndex_ == 1);
  drawRow(2, "Dim screen after", detailIndex_ == 2,
          durationLabel(dimOption_), detailEditing_ && detailIndex_ == 2);
  drawRow(3, "Screen off after", detailIndex_ == 3,
          durationLabel(screenOffOption_), detailEditing_ && detailIndex_ == 3);
  drawRow(4, "Button sounds", detailIndex_ == 4,
          buttonSoundsEnabled_ ? "ON" : "OFF");
  drawRow(5, "Back", detailIndex_ == 5);
  drawFooter("Previous", detailEditing_ ? "Finish" : "Edit", "Next");
}

void FireOS::drawWifi() {
  drawStatusBar("Wi-Fi");
  if (wifiSavedDialog_) {
    ui.fillRoundRect(12, 32, 296, 180, 12, kPanel);
    drawText(24, 42, "Saved networks", TFT_WHITE, 2, kPanel);
    const uint8_t itemCount = wifiSavedCount_ + 4;
    const int visible = min<int>(itemCount - wifiSavedOffset_, 6);
    for (int row = 0; row < visible; ++row) {
      const uint8_t item = wifiSavedOffset_ + row;
      const int y = 67 + row * 22;
      const bool selected = item == wifiSavedSelection_;
      if (selected) ui.fillRoundRect(18, y - 4, 284, 19, 4, kCyan);
      String label;
      if (item < wifiSavedCount_) {
        label = wifiSavedSsid_[item];
      } else if (item == wifiSavedCount_) {
        label = "Move selected up";
      } else if (item == wifiSavedCount_ + 1) {
        label = "Move selected down";
      } else if (item == wifiSavedCount_ + 2) {
        label = wifiDeleteArmed_ ? "Confirm delete" : "Delete selected";
      } else {
        label = "Back";
      }
      drawText(24, y, label, selected ? kBg : kText, 1,
               selected ? kCyan : kPanel);
    }
    if (wifiSavedCount_ == 0) drawText(24, 67, "No saved networks", kMuted, 1, kPanel);
    drawFooter("Previous", "Select / Connect", "Next");
    return;
  }
  if (wifiScanDialog_) {
    ui.fillRoundRect(12, 32, 296, 180, 12, kPanel);
    drawText(24, 42, "Networks found", TFT_WHITE, 2, kPanel);
    const int visible = min(wifiScanCount_ - static_cast<int>(wifiScanOffset_), 5);
    for (int row = 0; row < visible; ++row) {
      const int index = wifiScanOffset_ + row;
      String ssid = WiFi.SSID(index);
      if (ssid.length() == 0) ssid = "Hidden network";
      if (ssid.length() > 25) ssid = ssid.substring(0, 25);
      const int y = 76 + row * 23;
      if (index == wifiScanSelection_) {
        ui.fillRoundRect(18, y - 4, 284, 20, 4, kCyan);
      }
      drawText(24, y, ssid, index == wifiScanSelection_ ? kBg : kText, 1,
               index == wifiScanSelection_ ? kCyan : kPanel);
      drawText(270, y, String(WiFi.RSSI(index)),
               index == wifiScanSelection_ ? kBg : kMuted, 1,
               index == wifiScanSelection_ ? kCyan : kPanel);
    }
    if (visible == 0) drawText(24, 85, "No networks found", kMuted, 1, kPanel);
    if (wifiScanCount_ > 5) {
      drawText(24, 194, String(wifiScanSelection_ + 1) + "/" +
                           String(wifiScanCount_), kMuted, 1, kPanel);
    } else {
      drawText(24, 194, "Center closes", kMuted, 1, kPanel);
    }
    drawFooter("Previous", "Close", "Next");
    return;
  }

  if (wifiSetupActive_) {
    ui.fillRoundRect(12, 32, 296, 180, 12, kPanel);
    drawText(24, 41, "Mobile Wi-Fi setup", TFT_WHITE, 2, kPanel);
    const String url = "http://" + WiFi.softAPIP().toString() +
                       "/?token=" + wifiSetupToken_;
    ui.qrcode(url, 190, 60, 112, 4);
    drawText(24, 78, "1. Join network", kText, 1, kPanel);
    drawText(24, 96, "FIRE-Setup", kCyan, 1, kPanel);
    drawText(24, 120, "2. Password", kText, 1, kPanel);
    drawText(24, 138, "fire-connect-2026", kCyan, 1, kPanel);
    drawText(24, 166, "3. Scan QR and enter", kText, 1, kPanel);
    drawText(24, 184, "your home Wi-Fi details", kMuted, 1, kPanel);
    drawFooter("", "Close", "");
    return;
  }

  const String modeLabel = wifiMode_ == 0
                               ? (wifiEnabled_ ? "Auto (ON)" : "Auto (OFF)")
                               : wifiMode_ == 1 ? "On" : "Off";
  drawRow(0, "Mode", wifiIndex_ == 0, modeLabel);
  drawRow(1, wifiScanActive_ ? "Scanning..." : "Scan networks", wifiIndex_ == 1);
  drawRow(2, "Mobile setup", wifiIndex_ == 2);
  drawRow(3, "Saved networks", wifiIndex_ == 3);
  drawRow(4, "Back", wifiIndex_ == 4);
  if (wifiStatus_.length() > 0) {
    String status = wifiStatus_;
    if (status.length() > 36) status = status.substring(0, 36);
    ui.setTextDatum(MC_DATUM);
    drawText(160, 43, status,
             wifiScanActive_ || wifiConnectActive_ ? kCyan : kMuted, 1, kBg);
    ui.setTextDatum(TL_DATUM);
  }
  drawFooter("Previous", "Select", "Next");
}

void FireOS::drawBluetooth() {
  drawStatusBar("Bluetooth");
  static const char* labels[] = {"Mode",          "Scan Devices",
                                 "Pair Device",   "Saved Devices",
                                 "Connected",     "Visibility",
                                 "Advanced",      "Back"};
  const uint8_t first = bluetoothIndex_ < 5 ? 0 : bluetoothIndex_ - 4;
  for (uint8_t row = 0; row < 6; ++row) {
    const uint8_t item = first + row;
    if (item >= 8) break;
    String value;
    if (item == 0) {
      value = bluetoothMode_ == 0
                  ? (bluetoothEnabled_ ? "Auto (ON)" : "Auto (OFF)")
                  : bluetoothMode_ == 1 ? "On" : "Off";
    }
    if (item == 5) value = bluetoothVisible_ ? "VISIBLE" : "HIDDEN";
    drawRow(row, labels[item], bluetoothIndex_ == item, value);
  }
  bool activeConnection = bluetoothConnected_;
#ifdef FIRE_OS_BLE
  activeConnection = activeConnection || bluetoothPeripheralConnected;
#endif
  if (activeConnection) {
    ui.setTextDatum(MC_DATUM);
    drawText(160, 197, "Connected", kGreen, 1, kBg);
    ui.setTextDatum(TL_DATUM);
  } else if (bluetoothStatus_.length() > 0) {
    String status = bluetoothStatus_;
    if (status.length() > 34) status = status.substring(0, 34);
    ui.setTextDatum(MC_DATUM);
    drawText(160, 197, status, kMuted, 1, kBg);
    ui.setTextDatum(TL_DATUM);
  } else {
    ui.setTextDatum(MC_DATUM);
    const String status = bluetoothMode_ == 2
                              ? "Bluetooth Off"
                              : bluetoothVisible_
                                    ? "Visible / accepting connections"
                                    : bluetoothRadioReady
                                          ? "Ready / hidden"
                                          : "Auto / standby";
    drawText(160, 197, status, kMuted, 1, kBg);
    ui.setTextDatum(TL_DATUM);
  }
  drawFooter("Previous", "Select", "Next");
  if (bluetoothScanDialog_) drawBluetoothScanDialog();
  if (bluetoothSavedDialog_) drawBluetoothSavedDialog();
}

void FireOS::drawBluetoothScanDialog() {
  ui.fillRoundRect(8, 31, 304, 181, 8, kPanel);
  ui.drawRoundRect(8, 31, 304, 181, 8, kCyan);
  drawText(18, 39, bluetoothUnknownDialog_ ? "Unknown devices" : "BLE devices",
           TFT_WHITE, 2, kPanel);

  const uint8_t deviceCount = bluetoothDeviceListCount(bluetoothUnknownDialog_);
  if (deviceCount == 0) {
    drawText(18, 78, "No devices found", kMuted, 1, kPanel);
    drawText(18, 102, "Select Back to close", kText, 1, kPanel);
  } else {
    const uint8_t visible = min<uint8_t>(5, deviceCount - bluetoothScanOffset_);
    for (uint8_t row = 0; row < visible; ++row) {
      const uint8_t item = bluetoothScanOffset_ + row;
      const bool selected = item == bluetoothScanSelection_;
      const int y = 64 + row * 25;
      if (selected) ui.fillRoundRect(15, y - 3, 290, 21, 4, kCyan);
      const int8_t deviceIndex =
          bluetoothDeviceListIndex(item, bluetoothUnknownDialog_);
      String name;
      String signal;
      if (deviceIndex < 0) {
        name = "Unknown devices";
        uint8_t unknownCount = bluetoothDeviceListCount(true);
        signal = String(unknownCount) + " found";
      } else {
        name = bluetoothNames_[deviceIndex];
        signal = String(bluetoothRssi_[deviceIndex]) + " dBm";
      }
      if (name.length() > 23) name = name.substring(0, 23);
      drawText(22, y + 1, name, selected ? kBg : kText, 1,
               selected ? kCyan : kPanel);
      ui.setTextDatum(MR_DATUM);
      drawText(298, y + 1, signal,
               selected ? kBg : kMuted, 1, selected ? kCyan : kPanel);
      ui.setTextDatum(TL_DATUM);
    }
  }

  const uint8_t backItem = deviceCount;
  const bool backSelected = bluetoothScanSelection_ == backItem;
  if (backSelected) ui.fillRoundRect(15, 188, 290, 18, 4, kCyan);
  drawText(22, 191, "Back", backSelected ? kBg : kText, 1,
           backSelected ? kCyan : kPanel);
  ui.setTextDatum(MC_DATUM);
  drawText(160, 204, bluetoothUnknownDialog_ ? "A/C move   B pair/back"
                                             : "A/C move   B select",
           kMuted, 1, kPanel);
  ui.setTextDatum(TL_DATUM);
}

void FireOS::drawBluetoothSavedDialog() {
  ui.fillRoundRect(8, 31, 304, 181, 8, kPanel);
  ui.drawRoundRect(8, 31, 304, 181, 8, kCyan);
  drawText(18, 39, "Saved devices", TFT_WHITE, 2, kPanel);

  const uint8_t itemCount = bluetoothSavedCount_ + 2;
  const uint8_t visible = min<uint8_t>(5, itemCount - bluetoothSavedOffset_);
  for (uint8_t row = 0; row < visible; ++row) {
    const uint8_t item = bluetoothSavedOffset_ + row;
    const bool selected = item == bluetoothSavedSelection_;
    const int y = 64 + row * 25;
    if (selected) ui.fillRoundRect(15, y - 3, 290, 21, 4, kCyan);
    String label;
    if (item < bluetoothSavedCount_) {
      label = bluetoothSavedNames_[item];
    } else if (item == bluetoothSavedCount_) {
      label = bluetoothSavedDeleteArmed_ ? "Confirm delete" : "Delete selected";
    } else {
      label = "Back";
    }
    if (label.length() > 29) label = label.substring(0, 29);
    drawText(22, y + 1, label, selected ? kBg : kText, 1,
             selected ? kCyan : kPanel);
  }
  ui.setTextDatum(MC_DATUM);
  drawText(160, 204, "A/C move   B connect/select", kMuted, 1, kPanel);
  ui.setTextDatum(TL_DATUM);
}

void FireOS::drawBoot() {
  drawStatusBar("Boot");
  String bootLabel = "Default";
  if (selectedBootAppPath_.length() > 0) {
    if (selectedBootAppPath_.endsWith("/main.lua")) {
      for (uint8_t index = 0; index < luaAppCount_; ++index) {
        if (luaAppPaths_[index] == selectedBootAppPath_) {
          bootLabel = luaAppDisplayNames_[index];
          break;
        }
      }
    } else {
      bootLabel = externalAppBaseName(selectedBootAppPath_);
    }
  }
  drawRow(0, "Boot app", detailIndex_ == 0, bootLabel);
  drawRow(1, "RGB pulse", detailIndex_ == 1, bootRgbPulse_ ? "ON" : "OFF");
  drawRow(2, "Startup melody", detailIndex_ == 2, bootMelody_ ? "ON" : "OFF");
  drawRow(3, "Back", detailIndex_ == 3);
  drawText(16, 177, "App auto-boot becomes available", kMuted, 1);
  drawText(16, 192, "when the app registry is installed.", kMuted, 1);
  if (bootAppPicker_) {
    ui.fillRoundRect(12, 32, 296, 180, 10, kPanel);
    drawText(24, 40, "Choose Boot App", TFT_WHITE, 2, kPanel);
    const uint8_t itemCount = externalAppCount_ + luaAppCount_ + 1;
    const uint8_t visible = min<uint8_t>(6, itemCount - bootAppOffset_);
    for (uint8_t row = 0; row < visible; ++row) {
      const uint8_t item = bootAppOffset_ + row;
      const bool selected = item == bootAppSelection_;
      const int y = 72 + row * 22;
      if (selected) ui.fillRoundRect(18, y - 3, 284, 19, 4, kCyan);
      String name = "FIRE OS (Default)";
      if (item > 0 && item - 1 < externalAppCount_) {
        name = externalAppNames_[item - 1];
      } else if (item > externalAppCount_) {
        name = luaAppDisplayNames_[item - 1 - externalAppCount_];
      }
      if (name.length() > 25) name = name.substring(0, 22) + "...";
      drawText(26, y, name, selected ? kBg : kText, 1,
               selected ? kCyan : kPanel);
      if (item > externalAppCount_) {
        ui.setTextDatum(MR_DATUM);
        drawText(298, y, "Lua", selected ? kBg : kCyan, 1,
                 selected ? kCyan : kPanel);
        ui.setTextDatum(TL_DATUM);
      }
    }
    drawFooter("Previous", "Select", "Next");
    return;
  }
  drawFooter("Previous", "Select", "Next");
}

void FireOS::drawFirmware() {
  drawStatusBar("Firmware");
  if (firmwareGithubOverwriteConfirm_) {
    ui.fillRoundRect(12, 44, 296, 142, 12, kPanel);
    drawText(26, 56, "File already exists", kOrange, 2, kPanel);
    String name = githubFirmware_
                      ? githubFirmware_->entryName(firmwareGithubPendingIndex_)
                      : String();
    if (name.length() > 28) name = name.substring(0, 25) + "...";
    drawText(26, 88, name, TFT_WHITE, 1, kPanel);
    drawText(26, 112, "Overwrite existing file?", kText, 1, kPanel);
    drawText(26, 140, "B overwrite   A/C cancel", kCyan, 1, kPanel);
    drawFooter("Cancel", "Overwrite", "Cancel");
    return;
  }
  if (firmwareGithubDialog_) {
    drawGithubFirmwareDialog();
    return;
  }
  if (firmwareSdDialog_) {
    drawSdFirmwareDialog();
    return;
  }
  if (firmwareInstallConfirm_) {
    ui.fillRoundRect(14, 40, 292, 150, 12, kPanel);
    drawText(28, 52, "Flash firmware?", kOrange, 2, kPanel);
    String name = firmwareSelection_ < firmwareCount_
                      ? firmwareNames_[firmwareSelection_]
                      : String();
    if (name.length() > 28) name = name.substring(0, 25) + "...";
    drawText(28, 88, name, TFT_WHITE, 1, kPanel);
    drawText(28, 114, "Writes inactive OTA slot", kMuted, 1, kPanel);
    drawText(28, 132, "Reboots FIRE OS", kMuted, 1, kPanel);
    drawText(28, 158, "B flash   A/C cancel", kCyan, 1, kPanel);
    drawFooter("Cancel", "Flash", "Cancel");
    return;
  }
  drawText(16, 34, "Running", kCyan, 1);
  drawText(16, 48, firmwareVersionLabel(), TFT_WHITE, 2);

  const uint8_t itemCount = 3;
  const uint8_t visible = min<uint8_t>(3, itemCount - firmwareOffset_);
  for (uint8_t row = 0; row < visible; ++row) {
    const uint8_t item = firmwareOffset_ + row;
    const bool selected = item == firmwareSelection_;
    const int y = 70 + row * 22;
    if (selected) ui.fillRoundRect(10, y - 3, 300, 19, 4, kCyan);
    if (item == 0) {
      drawText(20, y, "GitHub firmware files", selected ? kBg : kText, 1,
               selected ? kCyan : kBg);
    } else if (item == 1) {
      drawText(20, y, "SD firmware files", selected ? kBg : kText, 1,
               selected ? kCyan : kBg);
    } else {
      drawText(20, y, "Back", selected ? kBg : kText, 1,
               selected ? kCyan : kBg);
    }
  }

  String status = firmwareStorage_ && firmwareStorage_->busy()
                      ? firmwareStorage_->status()
                      : firmwareMessage_;
  if (status.length() > 38) status = status.substring(0, 38);
  ui.setTextDatum(MC_DATUM);
  drawText(160, 190, status, kMuted, 1, kBg);
  ui.setTextDatum(TL_DATUM);
  drawFooter("A  UP", "B  SELECT", "DOWN  C");
}

void FireOS::drawSdFirmwareDialog() {
  ui.fillRoundRect(8, 31, 304, 181, 8, kPanel);
  ui.drawRoundRect(8, 31, 304, 181, 8, kCyan);
  drawText(18, 39, "SD firmware files", TFT_WHITE, 2, kPanel);
  const uint8_t itemCount = firmwareCount_ + 1;
  if (firmwareCount_ == 0) {
    ui.setTextDatum(MC_DATUM);
    drawText(160, 105, sdReady_ ? "No .bin files" : "SD not detected",
             kMuted, 1, kPanel);
    ui.setTextDatum(TL_DATUM);
  } else {
    const uint8_t visible = min<uint8_t>(5, itemCount - firmwareOffset_);
    for (uint8_t row = 0; row < visible; ++row) {
      const uint8_t item = firmwareOffset_ + row;
      const bool selected = item == firmwareSelection_;
      const int y = 68 + row * 25;
      if (selected) ui.fillRoundRect(15, y - 3, 290, 21, 4, kCyan);
      if (item < firmwareCount_) {
        String name = firmwareNames_[item];
        if (name.length() > 22) name = name.substring(0, 19) + "...";
        drawText(22, y, name, selected ? kBg : kText, 1,
                 selected ? kCyan : kPanel);
        drawText(250, y, "Local", selected ? kBg : kGreen, 1,
                 selected ? kCyan : kPanel);
        ui.setTextDatum(MR_DATUM);
        drawText(300, y, formatBytes(firmwareSizes_[item]),
                 selected ? kBg : kMuted, 1, selected ? kCyan : kPanel);
        ui.setTextDatum(TL_DATUM);
      } else {
        drawText(22, y, "Back", selected ? kBg : kText, 1,
                 selected ? kCyan : kPanel);
      }
    }
  }
  String status = firmwareMessage_;
  if (status.length() > 35) status = status.substring(0, 35);
  ui.setTextDatum(MC_DATUM);
  drawText(160, 190, status, kMuted, 1, kPanel);
  ui.setTextDatum(TL_DATUM);
  drawFooter("A  UP", "B  FLASH", "DOWN  C");
}

void FireOS::drawGithubFirmwareDialog() {
  ui.fillRoundRect(8, 31, 304, 181, 8, kPanel);
  ui.drawRoundRect(8, 31, 304, 181, 8, kCyan);
  drawText(18, 39, "GitHub firmware", TFT_WHITE, 2, kPanel);
  const uint8_t remoteCount = githubFirmware_ ? githubFirmware_->entryCount() : 0;
  const uint8_t itemCount = remoteCount + 1;
  const uint8_t visible = min<uint8_t>(5, itemCount - firmwareGithubOffset_);
  if (remoteCount == 0 && githubFirmware_ && githubFirmware_->busy()) {
    ui.setTextDatum(MC_DATUM);
    drawText(160, 105, "Loading catalog...", kCyan, 1, kPanel);
    ui.setTextDatum(TL_DATUM);
  } else if (remoteCount == 0) {
    ui.setTextDatum(MC_DATUM);
    drawText(160, 105, "No GitHub files", kOrange, 1, kPanel);
    ui.setTextDatum(TL_DATUM);
  } else {
    for (uint8_t row = 0; row < visible; ++row) {
      const uint8_t item = firmwareGithubOffset_ + row;
      const bool selected = item == firmwareGithubSelection_;
      const int y = 68 + row * 25;
      if (selected) ui.fillRoundRect(15, y - 3, 290, 21, 4, kCyan);
      if (item < remoteCount) {
        String name = githubFirmware_->entryName(item);
        if (name.length() > 22) name = name.substring(0, 19) + "...";
        drawText(22, y, name, selected ? kBg : kText, 1,
                 selected ? kCyan : kPanel);
        const bool local = sdReady_ && SD.exists("/firmware/" +
                                                  githubFirmware_->entryName(item));
        drawText(230, y, local ? "Both" : "Cloud",
                 selected ? kBg : (local ? kGreen : kCyan), 1,
                 selected ? kCyan : kPanel);
        ui.setTextDatum(MR_DATUM);
        drawText(300, y, formatBytes(githubFirmware_->entrySize(item)),
                 selected ? kBg : kMuted, 1, selected ? kCyan : kPanel);
        ui.setTextDatum(TL_DATUM);
      } else {
        drawText(22, y, "Back", selected ? kBg : kText, 1,
                 selected ? kCyan : kPanel);
      }
    }
  }
  String status = firmwareMessage_;
  if (status.length() > 35) status = status.substring(0, 35);
  ui.setTextDatum(MC_DATUM);
  drawText(160, 190, status, kMuted, 1, kPanel);
  ui.setTextDatum(TL_DATUM);
  drawFooter("A  UP", "B  DOWNLOAD", "DOWN  C");
}

void FireOS::drawMainMenuSettings() {
  drawStatusBar("Menu Layout");
  if (luaMenuPicker_) {
    drawText(16, 37, "Select Lua apps for carousel", kMuted, 1);
    const uint8_t itemCount = luaAppCount_ + 1;
    const uint8_t visible = min<uint8_t>(7, itemCount - luaMenuOffset_);
    for (uint8_t row = 0; row < visible; ++row) {
      const uint8_t item = luaMenuOffset_ + row;
      const bool selected = item == luaMenuSelection_;
      const int y = 57 + row * 21;
      if (selected) ui.fillRoundRect(10, y - 3, 300, 18, 4, kCyan);
      if (item < luaAppCount_) {
        String name = luaAppDisplayNames_[item];
        if (name.length() > 24) name = name.substring(0, 21) + "...";
        drawText(18, y, name, selected ? kBg : kText, 1,
                 selected ? kCyan : kBg);
        ui.setTextDatum(MR_DATUM);
        drawText(300, y, luaMenuSelected_[item] ? "Shown" : "Hidden",
                 selected ? kBg : (luaMenuSelected_[item] ? kGreen : kMuted),
                 1, selected ? kCyan : kBg);
        ui.setTextDatum(TL_DATUM);
      } else {
        drawText(18, y, "Back", selected ? kBg : kText, 1,
                 selected ? kCyan : kBg);
      }
    }
    if (luaAppCount_ == 0)
      drawText(18, 76, "No Lua apps installed", kMuted, 1);
    drawFooter("Previous", "Toggle", "Next");
    return;
  }
  drawText(16, 38, "System menu layout", kMuted, 1);
  drawRow(0, "Apps", detailIndex_ == 0, mainVisible_[0] ? "Visible" : "Hidden");
  drawRow(1, "Settings", detailIndex_ == 1, mainVisible_[1] ? "Visible" : "Hidden");
  drawRow(2, "Power", detailIndex_ == 2, mainVisible_[2] ? "Visible" : "Hidden");
  drawRow(3, "File Explorer", detailIndex_ == 3,
          mainVisible_[3] ? "Visible" : "Hidden");
  drawRow(4, "AI Developer", detailIndex_ == 4,
          mainVisible_[4] ? "Visible" : "Hidden");
  drawRow(5, "Show selected apps", detailIndex_ == 5);
  drawRow(6, "Back", detailIndex_ == 6);
  drawText(16, 192, "B toggles visibility.", kMuted, 1);
  drawFooter("Previous", "Select", "Next");
}

void FireOS::drawShortcuts() {
  drawStatusBar("Shortcuts");
  drawText(16, 37, "Hold all 3 buttons at boot = Default", kMuted, 1);
  const char* labels[] = {"Long left",    "Long center",  "Long right",
                          "Double left",  "Double center", "Double right",
                          "Back"};
  const String values[] = {"Home", "Quick Settings", "Back",
                           shortcutActionLabel(doubleClickAction_[0]),
                           shortcutActionLabel(doubleClickAction_[1]),
                           shortcutActionLabel(doubleClickAction_[2]), ""};
  for (uint8_t row = 0; row < 7; ++row) {
    const int y = 53 + row * 22;
    const bool selected = row == detailIndex_;
    if (selected) ui.fillRoundRect(10, y - 2, 300, 19, 5, kCyan);
    drawText(20, y + 2, labels[row], selected ? kBg : kText, 1,
             selected ? kCyan : kBg);
    if (values[row].length() > 0) {
      ui.setTextDatum(MR_DATUM);
      String value = values[row];
      if (value.length() > 17) value = value.substring(0, 14) + "...";
      drawText(300, y + 2, value, selected ? kBg : kMuted, 1,
               selected ? kCyan : kBg);
      ui.setTextDatum(TL_DATUM);
    }
  }
  if (shortcutPicker_) {
    ui.fillRoundRect(12, 32, 296, 180, 10, kPanel);
    drawText(24, 40, "Choose shortcut", TFT_WHITE, 2, kPanel);
    const uint8_t actionCount = shortcutActionCount();
    const uint8_t visible = min<uint8_t>(7, actionCount - shortcutPickerOffset_);
    for (uint8_t row = 0; row < visible; ++row) {
      const uint8_t position = shortcutPickerOffset_ + row;
      const uint8_t action = shortcutActionAtPosition(position);
      const int y = 70 + row * 19;
      const bool selected = action == shortcutPickerAction_;
      if (selected) ui.fillRoundRect(18, y - 3, 284, 17, 4, kCyan);
      String label = shortcutActionLabel(action);
      if (label.length() > 27) label = label.substring(0, 24) + "...";
      drawText(26, y, label, selected ? kBg : kText, 1,
               selected ? kCyan : kPanel);
    }
  }
  drawFooter("Previous", "Select", "Next");
}

void FireOS::drawAiDeveloper() {
  // AI Developer is intentionally immersive: no system status bar or panel.
  ui.fillSprite(TFT_BLACK);
  if (aiProjectPickerActive_) {
    ui.fillRoundRect(12, 28, 296, 188, 12, kPanel);
    ui.setTextDatum(MC_DATUM);
    drawText(160, 45, "AI DEVELOPER", TFT_WHITE, 2, kPanel);
    String backendLabel = "BACKEND: ";
    uint16_t backendColor = kMuted;
    if (!backendClient_ || !backendClient_->configured()) {
      backendLabel += "NOT CONFIGURED";
      backendColor = kOrange;
    } else if (backendClient_->sessionReady()) {
      backendLabel += "CONNECTED";
      backendColor = kGreen;
    } else if (WiFi.status() != WL_CONNECTED) {
      backendLabel += "WAITING FOR WI-FI";
      backendColor = kOrange;
    } else if (backendStatus_.indexOf("failed") >= 0 ||
               backendStatus_.indexOf("timeout") >= 0 ||
               backendStatus_.indexOf("rejected") >= 0 ||
               backendStatus_.indexOf("disconnected") >= 0) {
      backendLabel += "DISCONNECTED";
      backendColor = kOrange;
    } else {
      backendLabel += "CONNECTING";
      backendColor = kCyan;
    }
    drawText(160, 59, backendLabel, backendColor, 1, kPanel);
    const uint8_t itemCount = luaAppCount_ + 4;
    const uint8_t visible = min<uint8_t>(6, itemCount - aiProjectOffset_);
    for (uint8_t row = 0; row < visible; ++row) {
      const uint8_t item = aiProjectOffset_ + row;
      const bool selected = item == aiProjectSelection_;
      const int y = 72 + row * 22;
      if (selected) ui.fillRoundRect(20, y - 4, 280, 19, 4, kCyan);
      String label = item == 0
                         ? "Chat only"
                         : item == 1
                             ? "Voice test"
                             : item == 2
                                 ? "New app"
                                 : item == itemCount - 1
                                     ? "Back"
                                     : luaAppNames_[item - 3];
      if (label.length() > 28) label = label.substring(0, 25) + "...";
      drawText(160, y, label, selected ? kBg : kText, 1,
               selected ? kCyan : kPanel);
    }
    drawText(48, 232, "PREV", kMuted, 1, TFT_BLACK);
    drawText(160, 232, "SELECT", kMuted, 1, TFT_BLACK);
    drawText(272, 232, "NEXT", kMuted, 1, TFT_BLACK);
    ui.setTextDatum(TL_DATUM);
    return;
  }
  static const char* const states[] = {"REST", "LISTEN", "THINK", "TALK"};
  const uint32_t now = millis();
  static uint32_t nextBlinkAt = 0;
  static uint32_t blinkUntil = 0;
  static uint32_t nextFeatureAt = 0;
  static uint32_t featureSeed = 0;
  if (nextBlinkAt == 0) nextBlinkAt = now + 900;
  if (now >= nextBlinkAt) {
    blinkUntil = now + 90 + (esp_random() % 110);
    nextBlinkAt = now + 1500 + (esp_random() % 3000);
  }
  if (now >= nextFeatureAt) {
    featureSeed = esp_random();
    nextFeatureAt = now + 350 + (featureSeed % 1100);
  }
  const bool blink = now < blinkUntil;
  const int cx = 160;
  const int cy = 108;
  const uint16_t line = TFT_WHITE;
  if (aiDeveloperMode_ == 0 && aiRestPhaseStarted_ != 0 &&
      now - aiRestPhaseStarted_ >= aiRestPhaseDuration_) {
    aiRestPhase_ = static_cast<uint8_t>((aiRestPhase_ + 1) % 3);
    aiRestPhaseStarted_ = now;
    aiRestPhaseDuration_ = 30000 + (esp_random() % 30001);
  }
  const bool tired = aiDeveloperMode_ == 0 && aiRestPhase_ == 1;
  const bool sleeping = aiDeveloperMode_ == 0 && aiRestPhase_ == 2;
  static uint32_t nextSquintAt = 0;
  static uint32_t squintUntil = 0;
  if (nextSquintAt == 0) nextSquintAt = now + 700;
  if (now >= nextSquintAt) {
    if ((esp_random() % 100) < 45)
      squintUntil = now + 180 + (esp_random() % 420);
    nextSquintAt = now + 900 + (esp_random() % 2600);
  }
  const bool squint = !sleeping && now < squintUntil;
  const int eyeDrift = static_cast<int>((featureSeed >> 4) % 7) - 3;
  const int eyeY = cy - 22 + static_cast<int>((featureSeed >> 8) % 5) - 2;
  const int eyeLeft = cx - 52 + eyeDrift;
  const int eyeRight = cx + 52 + eyeDrift;
  const int leftEyeY = eyeY + static_cast<int>((featureSeed >> 16) % 5) - 2;
  const int rightEyeY = eyeY + static_cast<int>((featureSeed >> 20) % 5) - 2;

  // One face language across every state, with mode-specific posture and
  // motion. Eyes stay solid white while gaze and brows vary subtly.
  if (sleeping) {
    ui.drawLine(eyeLeft - 13, leftEyeY, eyeLeft + 13, leftEyeY, line);
    ui.drawLine(eyeRight - 13, rightEyeY, eyeRight + 13, rightEyeY, line);
  } else if (blink) {
    ui.drawLine(eyeLeft - 13, leftEyeY, eyeLeft + 13, leftEyeY, line);
    ui.drawLine(eyeRight - 13, rightEyeY, eyeRight + 13, rightEyeY, line);
  } else if (squint || tired) {
    const int height = tired ? 5 : 7;
    ui.fillRoundRect(eyeLeft - 13, leftEyeY - height / 2, 26, height,
                     height / 2, line);
    ui.fillRoundRect(eyeRight - 13, rightEyeY - height / 2, 26, height,
                     height / 2, line);
  } else {
    ui.fillCircle(eyeLeft, leftEyeY, 12, line);
    ui.fillCircle(eyeRight, rightEyeY, 12, line);
  }

  const int browTilt = static_cast<int>((featureSeed >> 24) % 9) - 4;
  if (aiDeveloperMode_ == 1) {
    // Listening: raised brows, alert gaze and small sound-wave marks.
    ui.drawLine(eyeLeft - 15, leftEyeY - 22, eyeLeft + 9,
                leftEyeY - 27 - browTilt, line);
    ui.drawLine(eyeRight - 9, rightEyeY - 27 - browTilt,
                eyeRight + 15, rightEyeY - 22, line);
    ui.drawLine(cx - 82, cy + 7, cx - 72, cy + 7, line);
    ui.drawLine(cx + 72, cy + 7, cx + 82, cy + 7, line);
  } else if (aiDeveloperMode_ == 2) {
    // Thinking: one brow is higher and the gaze drifts upward.
    ui.drawLine(eyeLeft - 15, leftEyeY - 28 - browTilt,
                eyeLeft + 9, leftEyeY - 23, line);
    ui.drawLine(eyeRight - 9, rightEyeY - 23,
                eyeRight + 15, rightEyeY - 28 + browTilt, line);
  } else if (aiDeveloperMode_ == 3) {
    // Talking: relaxed, asymmetric brows while the mouth animates.
    ui.drawLine(eyeLeft - 15, leftEyeY - 24,
                eyeLeft + 9, leftEyeY - 26 - browTilt, line);
    ui.drawLine(eyeRight - 9, rightEyeY - 26 + browTilt,
                eyeRight + 15, rightEyeY - 24, line);
  } else {
    // Resting: gentle, slightly changing expression.
    const int tiredDrop = tired ? 7 : 0;
    ui.drawLine(eyeLeft - 15, leftEyeY - 25 + tiredDrop - browTilt,
                eyeLeft + 9, leftEyeY - 25 + tiredDrop, line);
    ui.drawLine(eyeRight - 9, rightEyeY - 25 + tiredDrop,
                eyeRight + 15, rightEyeY - 25 + tiredDrop - browTilt, line);
  }

  const int mouthY = cy + 48 + static_cast<int>((featureSeed >> 18) % 5) - 2;
  if (aiDeveloperMode_ == 3) {
    // TALK: a fast, open sideways-D mouth. The top remains straight while
    // the lower half changes rapidly to suggest syllables.
    static const uint8_t openings[] = {3, 9, 15, 5, 12, 4, 17, 7};
    const uint8_t phoneme =
        static_cast<uint8_t>((now / 70 + (featureSeed & 3)) % 8);
    const int mouthHalfWidth = 29 + static_cast<int>((featureSeed >> 12) % 9);
    const int mouthHeight = openings[phoneme];
    const int left = cx - mouthHalfWidth;
    const int right = cx + mouthHalfWidth;
    const int bottom = mouthY + mouthHeight;
    ui.drawLine(left, mouthY, right, mouthY, line);
    ui.drawLine(left, mouthY, left + 7, bottom - 2, line);
    ui.drawLine(left + 7, bottom - 2, cx, bottom, line);
    ui.drawLine(cx, bottom, right - 7, bottom - 2, line);
    ui.drawLine(right - 7, bottom - 2, right, mouthY, line);
    const int talkCorner = static_cast<int>((featureSeed >> 28) % 7) - 3;
    ui.drawLine(left - 6, mouthY + talkCorner, left, mouthY, line);
    ui.drawLine(right, mouthY, right + 6, mouthY - talkCorner, line);
  } else {
    const int mouthHalfWidth = aiDeveloperMode_ == 1
                                   ? 20 + static_cast<int>((featureSeed >> 12) % 5)
                               : aiDeveloperMode_ == 2
                                   ? 25 + static_cast<int>((featureSeed >> 12) % 7)
                                   : 29 + static_cast<int>((featureSeed >> 12) % 9);
    const int centerOffset = sleeping
                                 ? 0
                             : tired
                                 ? -1
                             : aiDeveloperMode_ == 0
                                 ? 4
                             : aiDeveloperMode_ == 2 ? -2 : 1;
    const int adjustedWidth = sleeping ? 16 : tired ? 23 : mouthHalfWidth;
    const int left = cx - adjustedWidth;
    const int right = cx + adjustedWidth;
    ui.drawLine(left, mouthY, cx, mouthY + centerOffset, line);
    ui.drawLine(cx, mouthY + centerOffset, right, mouthY, line);
    const int cornerTilt = static_cast<int>((featureSeed >> 28) % 7) - 3;
    ui.drawLine(left - 6, mouthY + cornerTilt, left, mouthY, line);
    ui.drawLine(right, mouthY, right + 6, mouthY - cornerTilt, line);
  }

  const char* stateLabel =
      aiVoiceTestMode_
          ? (aiDeveloperMode_ == 1
                 ? "LISTEN"
                 : aiDeveloperMode_ == 3 ? "PLAYBACK" : "VOICE TEST")
          : states[aiDeveloperMode_];
  static const char* const workflowLabels[] = {
      "PRESS CENTER TO LISTEN", "LISTENING", "UNDERSTANDING...",
      "READY TO BUILD", "BUILDING...", "READY TO RUN", "RUNNING"};
  ui.setTextDatum(MC_DATUM);
  drawText(cx, 190, stateLabel, kMuted, 1, TFT_BLACK);
  String workflowLabel = aiWorkflowText_.length() > 0
                             ? aiWorkflowText_
                             : workflowLabels[min<uint8_t>(aiWorkflowState_, 6)];
  if (aiWorkflowState_ == 1 && aiAudioCaptureStartedAt_ > 0) {
    workflowLabel = "REC " + String((millis() - aiAudioCaptureStartedAt_) / 1000.0f, 1) +
                    "s - SPEAK NEAR MIC";
  }
  if (aiConversationMode_ == 1 && aiWorkflowState_ == 0 &&
      aiWorkflowText_.length() == 0)
    workflowLabel = "CHAT - PRESS B TO SPEAK";
  if (workflowLabel.length() > 28) workflowLabel = workflowLabel.substring(0, 28);
  drawText(cx, 207, workflowLabel, kMuted, 1, TFT_BLACK);
  if (aiAssistantText_.length() > 0) {
    String assistant = aiAssistantText_;
    if (assistant.length() > 34) assistant = assistant.substring(0, 31) + "...";
    drawText(cx, 174, assistant, 0xBDF7, 1, TFT_BLACK);
  }
  if (aiWorkflowState_ == 4) {
    ui.drawRoundRect(45, 214, 230, 6, 3, 0x5AEB);
    ui.fillRoundRect(47, 216,
                     static_cast<int32_t>(226 * aiBuildProgress_ / 100), 3,
                     1, 0x5AEB);
  }
  const char* leftHint = "HOLD HOME";
  const char* centerHint = "SPEAK";
  const char* rightHint = "HOLD BACK";
  if (aiWorkflowState_ == 1) {
    centerHint = "FINISH";
  } else if (aiWorkflowState_ == 2) {
    centerHint = "NEW TALK";
    rightHint = "CANCEL";
  } else if (aiWorkflowState_ == 3) {
    leftHint = "BUILD";
    centerHint = "ADD TALK";
    rightHint = "CANCEL";
  } else if (aiWorkflowState_ == 4) {
    leftHint = "WAIT";
    centerHint = "QUICK";
    rightHint = "CANCEL";
  } else if (aiWorkflowState_ == 5) {
    leftHint = "RUN";
    centerHint = "QUICK";
    rightHint = "CANCEL";
  } else if (aiWorkflowState_ == 6) {
    centerHint = "QUICK";
  }
  if (aiVoiceTestMode_) {
    centerHint = aiAudioCaptureActive_
                     ? "FINISH"
                     : aiVoiceTestPlaybackActive_ ? "NEW TEST" : "RECORD";
    rightHint = aiVoiceTestPlaybackActive_ ? "CANCEL" : "HOLD BACK";
  }
  ui.setTextDatum(MC_DATUM);
  drawText(46, 232, leftHint, kMuted, 1, TFT_BLACK);
  drawText(160, 232, centerHint, kMuted, 1, TFT_BLACK);
  drawText(274, 232, rightHint, kMuted, 1, TFT_BLACK);
  ui.setTextDatum(TL_DATUM);

#ifdef FIRE_OS_BLE
  static uint32_t lastLedUpdate = 0;
  if (now - lastLedUpdate >= 80) {
    lastLedUpdate = now;
    const uint8_t brightness = static_cast<uint8_t>(
        40 + ((now / 12) % 180));
    writeFireRgbRaw(0, 150, 220, brightness);
  }
#endif
}

void FireOS::drawAiApi() {
  drawStatusBar("AI settings");
  if (wifiSetupActive_) {
    ui.fillRoundRect(12, 32, 296, 180, 12, kPanel);
    drawText(24, 41, "Backend config", TFT_WHITE, 2, kPanel);
    const String url = "http://" + WiFi.softAPIP().toString() +
                       "/?token=" + wifiSetupToken_;
    ui.qrcode(url, 190, 60, 112, 4);
    drawText(24, 78, "1. Join network", kText, 1, kPanel);
    drawText(24, 96, "FIRE-Setup", kCyan, 1, kPanel);
    drawText(24, 120, "2. Password", kText, 1, kPanel);
    drawText(24, 138, "fire-connect-2026", kCyan, 1, kPanel);
    drawText(24, 166, "3. Scan backend QR", kText, 1, kPanel);
    drawText(24, 184, "PC, port, ID and token", kMuted, 1, kPanel);
    drawFooter("", "Close", "");
    return;
  }
  drawRow(0, "Backend config", detailIndex_ == 0);
  drawRow(1, "Connection status", detailIndex_ == 1,
          backendClient_ && backendClient_->configured() ? backendStatus_ : "Not configured");
  drawRow(2, "Back", detailIndex_ == 2);
  String host = backendHost_.length() > 0 ? backendHost_ : "not set";
  if (host.length() > 24) host = host.substring(0, 21) + "...";
  String device = backendDeviceId_.length() > 0 ? backendDeviceId_ : "not set";
  if (device.length() > 19) device = device.substring(0, 16) + "...";
  drawText(16, 174, "PC: " + host, kMuted, 1);
  drawText(16, 190, "Port: " + String(backendPort_) + "  ID: " + device,
           kMuted, 1);
  drawText(16, 206, "Token: " + String(backendToken_.length() >= 24 ? "configured" : "not set"),
           backendToken_.length() >= 24 ? kGreen : kOrange, 1);
  drawFooter("Previous", "Select", "Next");
}

void FireOS::drawLuaApp() {
  ui.fillSprite(TFT_BLACK);
  if (luaAppActive_) {
    // The Lua callback renders directly into the same sprite as the OS.
    // This keeps the app full-screen without a second framebuffer.
    updateLuaApp();
  }
  if (!luaAppActive_ && luaAppError_.length() > 0) {
    ui.setTextDatum(MC_DATUM);
    drawText(160, 96, "APP ERROR", kOrange, 2, TFT_BLACK);
    drawText(160, 126, luaAppError_.substring(0, 38), kText, 1, TFT_BLACK);
    drawText(160, 160, "Hold left for Home", kMuted, 1, TFT_BLACK);
    ui.setTextDatum(TL_DATUM);
  }
}

void FireOS::drawAppsSettings() {
  drawStatusBar("App Manager");
  if (appManagerDeleteConfirm_) {
    ui.fillRoundRect(18, 54, 284, 112, 10, kPanel);
    drawText(32, 68, "Delete app?", TFT_WHITE, 2, kPanel);
    const bool luaSelected = externalAppSelection_ >= externalAppCount_ &&
                             externalAppSelection_ < externalAppCount_ + luaAppCount_;
    const uint8_t selectedIndex = luaSelected
                                      ? externalAppSelection_ - externalAppCount_
                                      : externalAppSelection_;
    String name = luaSelected
                      ? luaAppNames_[selectedIndex]
                      : (selectedIndex < externalAppCount_
                             ? externalAppNames_[selectedIndex]
                             : "Selected app");
    if (name.length() > 27) name = name.substring(0, 24) + "...";
    drawText(32, 101, name, kText, 1, kPanel);
    drawText(32, 128, "B delete   A/C cancel", kOrange, 1, kPanel);
    drawFooter("Cancel", "Delete", "Cancel");
    return;
  }
  if (appManagerActionMenu_) {
    ui.fillRoundRect(18, 40, 284, 150, 10, kPanel);
    const bool luaSelected = externalAppSelection_ >= externalAppCount_ &&
                             externalAppSelection_ < externalAppCount_ + luaAppCount_;
    const uint8_t selectedIndex = luaSelected
                                      ? externalAppSelection_ - externalAppCount_
                                      : externalAppSelection_;
    String name = luaSelected ? luaAppNames_[selectedIndex]
                              : externalAppNames_[selectedIndex];
    if (name.length() > 26) name = name.substring(0, 23) + "...";
    drawText(30, 50, name, TFT_WHITE, 1, kPanel);
    static const char* actions[] = {"Launch", "Delete", "Back"};
    for (uint8_t row = 0; row < 3; ++row) {
      const int y = 82 + row * 27;
      const bool selected = row == appManagerActionIndex_;
      if (selected) ui.fillRoundRect(26, y - 4, 268, 22, 5, kCyan);
      drawText(38, y, actions[row], selected ? kBg : kText, 1,
               selected ? kCyan : kPanel);
    }
    drawFooter("A  UP", "B  SELECT", "DOWN  C");
    return;
  }

  drawText(16, 34, "SD /apps  (.bin / Lua)", kMuted, 1);
  const uint8_t appCount = externalAppCount_ + luaAppCount_;
  const uint8_t itemCount = appCount + 1;
  const uint8_t visible = min<uint8_t>(6, itemCount - externalAppOffset_);
  for (uint8_t row = 0; row < visible; ++row) {
    const uint8_t item = externalAppOffset_ + row;
    const int y = 54 + row * 22;
    const bool selected = item == externalAppSelection_;
    if (selected) ui.fillRoundRect(12, y - 3, 296, 19, 4, kCyan);
    if (item == appCount) {
      drawText(22, y, "Back", selected ? kBg : kText, 1,
               selected ? kCyan : kBg);
      continue;
    }
    const bool luaSelected = item >= externalAppCount_;
    const uint8_t selectedIndex = luaSelected ? item - externalAppCount_ : item;
    String name = luaSelected ? luaAppNames_[selectedIndex]
                              : externalAppNames_[selectedIndex];
    if (name.length() > 26) name = name.substring(0, 23) + "...";
    const uint16_t nameColor = selected
                                   ? kBg
                                   : (luaSelected || externalAppCompatible_[selectedIndex]
                                          ? kText
                                          : kOrange);
    drawText(22, y, name, nameColor, 1,
             selected ? kCyan : kBg);
    ui.setTextDatum(MR_DATUM);
    drawText(300, y, luaSelected ? "Lua" : formatBytes(externalAppSizes_[selectedIndex]),
             selected ? kBg
                      : (luaSelected || externalAppCompatible_[selectedIndex] ? kMuted : kOrange),
             1, selected ? kCyan : kBg);
    ui.setTextDatum(TL_DATUM);
  }
  if (appCount == 0)
    drawText(20, 100, "No apps in /apps", kMuted, 1);
  if (externalAppMessage_.length() > 0)
    drawText(16, 190, externalAppMessage_, kOrange, 1);
  drawFooter("A  UP", "B  ACTIONS", "DOWN  C");
}

void FireOS::drawAppsSettingsBackend() {
  drawStatusBar("App Manager");
  if (appManagerVersionDialog_) {
    drawAppManagerVersions();
    return;
  }
  if (appManagerDeleteConfirm_) {
    ui.fillRoundRect(18, 54, 284, 112, 10, kPanel);
    drawText(32, 68, appManagerDeleteMode_ == 2 ? "Delete backend?"
                                                : "Delete local?",
             TFT_WHITE, 2, kPanel);
    String name = appManagerDeleteName_;
    if (name.length() == 0 && managerSelection_ < managerItemCount_)
      name = managerItems_[managerSelection_].name;
    if (name.length() > 27) name = name.substring(0, 24) + "...";
    drawText(32, 101, name, kText, 1, kPanel);
    drawText(32, 128, appManagerDeleteMode_ == 2
                          ? "ALL backend versions"
                          : "Only local SD files",
             kOrange, 1, kPanel);
    drawFooter("Cancel", "Confirm", "Cancel");
    return;
  }
  if (appManagerActionMenu_) {
    ui.fillRoundRect(18, 40, 284, 150, 10, kPanel);
    String name = managerSelection_ < managerItemCount_
                      ? managerItems_[managerSelection_].name
                      : String();
    if (name.length() > 26) name = name.substring(0, 23) + "...";
    drawText(30, 50, name, TFT_WHITE, 1, kPanel);
    for (uint8_t row = 0; row < appManagerActionCount_; ++row) {
      const int y = 82 + row * 27;
      const bool selected = row == appManagerActionIndex_;
      if (selected) ui.fillRoundRect(26, y - 4, 268, 22, 5, kCyan);
      drawText(38, y, appManagerActionLabels_[row], selected ? kBg : kText, 1,
               selected ? kCyan : kPanel);
    }
    drawFooter("A  UP", "B  SELECT", "DOWN  C");
    return;
  }

  String heading = "Local + backend apps";
  if (backendClient_ && !backendClient_->sessionReady()) heading += " (offline)";
  drawText(16, 34, heading, kMuted, 1);
  const uint8_t itemCount = managerItemCount_ + 1;
  const uint8_t visible = min<uint8_t>(6, itemCount - managerOffset_);
  for (uint8_t row = 0; row < visible; ++row) {
    const uint8_t item = managerOffset_ + row;
    const int y = 54 + row * 22;
    const bool selected = item == managerSelection_;
    if (selected) ui.fillRoundRect(12, y - 3, 296, 19, 4, kCyan);
    if (item == managerItemCount_) {
      drawText(22, y, "Back", selected ? kBg : kText, 1,
               selected ? kCyan : kBg);
      continue;
    }
    const ManagerItem& managerItem = managerItems_[item];
    String name = managerItem.name;
    if (name.length() > 26) name = name.substring(0, 23) + "...";
    drawText(22, y, name, selected ? kBg : kText, 1,
             selected ? kCyan : kBg);
    ui.setTextDatum(MR_DATUM);
    String value = managerItem.backend && managerItem.local
                       ? "Both"
                   : managerItem.backend
                       ? (managerItem.downloadable ? "Cloud" : "Locked")
                   : managerItem.kind == 0 ? "BIN" : "Lua";
    drawText(300, y, value, selected ? kBg : kMuted, 1,
             selected ? kCyan : kBg);
    ui.setTextDatum(TL_DATUM);
  }
  String status = managerStatus_.length() > 0 ? managerStatus_ : externalAppMessage_;
  if (status.length() > 38) status = status.substring(0, 38);
  drawText(16, 190, status, kMuted, 1);
  drawFooter("A  UP", "B  ACTIONS", "DOWN  C");
}

void FireOS::drawAppManagerVersions() {
  drawStatusBar("App versions");
  ui.fillRoundRect(8, 31, 304, 181, 8, kPanel);
  drawText(18, 39, "Choose version", TFT_WHITE, 2, kPanel);
  const uint8_t itemCount = appManagerVersionCount_ + 1;
  const uint8_t visible = min<uint8_t>(6, itemCount - appManagerVersionOffset_);
  for (uint8_t row = 0; row < visible; ++row) {
    const uint8_t item = appManagerVersionOffset_ + row;
    const bool selected = item == appManagerVersionSelection_;
    const int y = 64 + row * 23;
    if (selected) ui.fillRoundRect(15, y - 3, 290, 19, 4, kCyan);
    if (item == appManagerVersionCount_) {
      drawText(22, y, "Back", selected ? kBg : kText, 1,
               selected ? kCyan : kPanel);
    } else {
      String label = appManagerVersionLabels_[item];
      if (label.length() == 0) label = "Version";
      if (!appManagerVersionDownloadable_[item]) label += " (locked)";
      if (label.length() > 28) label = label.substring(0, 25) + "...";
      drawText(22, y, label, selected ? kBg : kText, 1,
               selected ? kCyan : kPanel);
    }
  }
  drawFooter("A  UP", "B  DOWNLOAD", "DOWN  C");
}

void FireOS::drawHelp() {
  drawStatusBar("Help");
  if (helpPage_ == 0) {
    drawText(18, 48, "FIRE OS", kCyan, 2);
    drawText(18, 86, "Use the left and right buttons", kText, 1);
    drawText(18, 104, "to move through menus.", kText, 1);
    drawText(18, 134, "Select with the center button.", kMuted, 1);
    drawText(18, 164, "Hold left for Home.", kMuted, 1);
  } else if (helpPage_ == 1) {
    drawText(18, 48, "Navigation", kCyan, 2);
    drawText(18, 86, "Lists: left/right move selection.", kText, 1);
    drawText(18, 108, "Center selects or edits.", kText, 1);
    drawText(18, 130, "Back is the final list item.", kText, 1);
    drawText(18, 160, "Quick Settings is a temporary overlay.", kMuted, 1);
  } else {
    drawText(18, 48, "Hardware", kCyan, 2);
    drawText(18, 86, "LCD, buttons, audio, IMU and LEDs", kText, 1);
    drawText(18, 108, "are shared OS services.", kText, 1);
    drawText(18, 138, "Wi-Fi, Bluetooth and SD are optional.", kMuted, 1);
    drawText(18, 160, "The OS can boot without them.", kMuted, 1);
  }
  drawFooter("Previous", "Back", "Next");
}

void FireOS::drawQuickSettings() {
  ui.fillRoundRect(12, 32, 296, 180, 12, kPanel);
  drawText(24, 40, "Quick Settings", TFT_WHITE, 2, kPanel);
  drawLevelRow(0, "Brightness", brightnessStep_, kBrightnessStepCount,
               quickIndex_ == 0, kCyan, quickEditing_ && quickIndex_ == 0);
  drawLevelRow(1, "Volume", volumeStep_, kVolumeStepCount, quickIndex_ == 1,
               kGreen, quickEditing_ && quickIndex_ == 1);
  const String wifiModeLabel = wifiMode_ == 0 ? "Auto" : wifiMode_ == 1 ? "On" : "Off";
  String wifiValue;
  if (wifiMode_ == 2) {
    wifiValue = "Off";
  } else if (WiFi.status() == WL_CONNECTED) {
    wifiValue = WiFi.SSID() + " (" + wifiModeLabel + ")";
  } else if (wifiConnectActive_) {
    wifiValue = "Connecting (" + wifiModeLabel + ")";
  } else {
    wifiValue = "Disconnected (" + wifiModeLabel + ")";
  }
  if (wifiValue.length() > 21) wifiValue = wifiValue.substring(0, 21);

  const String bluetoothModeLabel = bluetoothMode_ == 0
                                        ? "Auto"
                                        : bluetoothMode_ == 1 ? "On" : "Off";
  String bluetoothValue;
  bool activeBluetoothConnection = bluetoothConnected_;
#ifdef FIRE_OS_BLE
  bool peripheralConnection = false;
  peripheralConnection = bluetoothPeripheralConnected;
  activeBluetoothConnection = activeBluetoothConnection || peripheralConnection;
#endif
  if (bluetoothMode_ == 2) {
    bluetoothValue = "Off";
  } else if (activeBluetoothConnection) {
    bluetoothValue = "";
#ifdef FIRE_OS_BLE
    if (peripheralConnection && bluetoothPeripheralAddress.length() > 0) {
      bluetoothValue += bluetoothPeripheralAddress;
    } else
#endif
    if (bluetoothSavedName_.length() > 0) {
      bluetoothValue += bluetoothSavedName_;
    } else {
      bluetoothValue += "Connected";
    }
    bluetoothValue += " (" + bluetoothModeLabel + ")";
  } else if (bluetoothVisible_) {
    bluetoothValue = "Visible (" + bluetoothModeLabel + ")";
  } else {
    bluetoothValue = "Disconnected (" + bluetoothModeLabel + ")";
  }
  if (bluetoothValue.length() > 21) bluetoothValue = bluetoothValue.substring(0, 21);
  const String sdValue = sdStorageLabel();

  auto drawQuickRow = [&](uint8_t item, const String& label,
                          const String& value) {
    const int y = 105 + static_cast<int>(item - 2) * 17;
    const bool selected = quickIndex_ == item;
    if (selected) ui.fillRoundRect(10, y - 3, 300, 18, 5, kCyan);
    drawText(20, y + 1, label, selected ? kBg : kText, 1,
             selected ? kCyan : kPanel);
    if (value.length() > 0) {
      ui.setTextDatum(MR_DATUM);
      drawText(300, y + 1, value, selected ? kBg : kMuted, 1,
               selected ? kCyan : kPanel);
      ui.setTextDatum(TL_DATUM);
    }
  };
  drawQuickRow(2, "Wi-Fi", wifiValue);
  drawQuickRow(3, "Bluetooth", bluetoothValue);
  drawQuickRow(4, "SD card", sdValue);
  drawQuickRow(5, "Power", "");
  drawQuickRow(6, "All settings", "");
  drawQuickRow(7, "Back", "");
  drawFooter("", quickEditing_ ? "Adjust" : "Select", "");
}

void FireOS::drawFileExplorer() {
  drawStatusBar("File Explorer");
  if (sdImagePreview_) {
    drawText(20, 42, "Image preview", TFT_WHITE, 2, kPanel);
    drawText(20, 68, sdBaseName(sdImagePreviewPath_), kMuted, 1, kPanel);
    drawFooter("", "Close", "");
    return;
  }
  if (sdPreview_) {
    ui.fillRoundRect(10, 32, 300, 180, 10, kPanel);
    drawText(20, 40, sdBaseName(sdEntryPaths_[sdSelection_]), TFT_WHITE, 1,
             kPanel);
    for (uint8_t line = 0; line < sdPreviewLineCount_; ++line) {
      drawText(18, 62 + line * 17, sdPreviewLines_[line], kText, 1, kPanel);
    }
    drawFooter("", "Close", "");
    return;
  }
  if (sdNameEditor_) {
    ui.fillRoundRect(10, 32, 300, 180, 10, kPanel);
    drawText(20, 42, sdNameIsNewFolder_ ? "New folder" : "Rename", TFT_WHITE,
             2, kPanel);
    drawText(20, 80, sdNameBuffer_, kCyan, 2, kPanel);
    ui.drawLine(20 + sdNameCursor_ * 12, 102,
                30 + sdNameCursor_ * 12, 102, kOrange);
    drawText(20, 135, "A/C change character", kMuted, 1, kPanel);
    drawText(20, 153, "B next / save", kMuted, 1, kPanel);
    drawFooter("", "Save", "");
    return;
  }
  if (sdDeleteConfirm_) {
    ui.fillRoundRect(18, 54, 284, 120, 10, kPanel);
    drawText(32, 68, "Delete selected?", kOrange, 2, kPanel);
    drawText(32, 104, sdSelection_ < sdEntryCount_ ? sdEntryNames_[sdSelection_]
                                                   : "", kText, 1, kPanel);
    drawText(32, 132, "B confirm   A/C cancel", kMuted, 1, kPanel);
    drawFooter("Cancel", "Delete", "");
    return;
  }
  if (sdActionMenu_) {
    static const char* actions[] = {"Open",  "Copy", "Move", "Rename",
                                    "Delete", "New folder", "Sort", "Back"};
    ui.fillRoundRect(12, 32, 296, 180, 10, kPanel);
    drawText(24, 40, "File actions", TFT_WHITE, 2, kPanel);
    for (uint8_t row = 0; row < 7; ++row) {
      const uint8_t action = (sdActionIndex_ + row) % 8;
      const int y = 70 + row * 19;
      const bool selected = row == 0;
      if (selected) ui.fillRoundRect(18, y - 3, 284, 17, 4, kCyan);
      drawText(26, y, actions[action], selected ? kBg : kText, 1,
               selected ? kCyan : kPanel);
    }
    drawFooter("Previous", "Select", "Next");
    return;
  }
  if (!sdReady_) {
    drawText(20, 62, "SD card not present", kOrange, 2);
    drawText(20, 100, "Insert a FAT32 card", kText, 1);
    drawFooter("", "Retry", "Back");
    return;
  }
  String pathLabel = sdPath_;
  if (pathLabel.length() > 28) pathLabel = "..." + pathLabel.substring(pathLabel.length() - 25);
  drawText(16, 34, pathLabel, kCyan, 1);
  drawText(16, 48, sdStorageLabel(), kMuted, 1);
  if (sdMessage_.length() > 0) {
    String message = sdMessage_;
    if (message.length() > 34) message = message.substring(0, 34);
    ui.setTextDatum(MR_DATUM);
    drawText(304, 48, message, kOrange, 1);
    ui.setTextDatum(TL_DATUM);
  }
  const uint8_t itemCount = sdEntryCount_ + 1;
  const uint8_t visible = min<uint8_t>(kFileVisibleRows, itemCount - sdOffset_);
  if (sdEntryCount_ == 0) drawText(20, 85, "Empty folder", kMuted, 1);
  for (uint8_t row = 0; row < visible; ++row) {
    const uint8_t item = sdOffset_ + row;
    const int y = 70 + row * 23;
    const bool selected = item == sdSelection_;
    if (selected) ui.fillRoundRect(12, y - 3, 296, 20, 4, kCyan);
    if (item < sdEntryCount_) {
      const uint16_t color = selected ? kBg : kCyan;
      if (sdEntryDirectories_[item]) {
        ui.drawRect(20, y + 2, 13, 10, color);
        ui.drawLine(21, y + 2, 26, y - 1, color);
      } else {
        ui.drawRect(21, y, 11, 14, color);
        ui.drawLine(23, y + 4, 30, y + 4, color);
      }
      String name = sdEntryNames_[item];
      if (name.length() > 25) name = name.substring(0, 22) + "...";
      drawText(40, y + 1, name, selected ? kBg : kText, 1,
               selected ? kCyan : kPanel);
      ui.setTextDatum(MR_DATUM);
      drawText(302, y + 1,
               sdEntryDirectories_[item] ? "DIR" : formatBytes(sdEntrySizes_[item]),
               selected ? kBg : kMuted, 1, selected ? kCyan : kPanel);
      ui.setTextDatum(TL_DATUM);
    } else {
      drawText(20, y + 1, "Back", selected ? kBg : kText, 1,
               selected ? kCyan : kPanel);
    }
  }
  drawFooter("Previous", "Open", "Next");
}

void FireOS::drawPlaceholder() {
  drawStatusBar("FIRE OS");
  drawText(20, 68, "This section is ready", kCyan, 2);
  drawText(20, 105, "for the next OS module.", kText, 1);
  drawText(20, 135, "The core remains available", kMuted, 1);
  drawText(20, 153, "without network or SD card.", kMuted, 1);
  drawFooter("", "", "BACK  C");
}

void FireOS::updateDebugTests() {
  if (debugMicRecording_) {
    if (fireMicCaptureFailed()) {
      fireReleaseMicCapture();
      debugMicRecording_ = false;
      debugMicSamples_ = 0;
      debugMicStatus_ = "Microphone capture failed";
    } else if (!fireMicCaptureRunning()) {
      const size_t captured =
          min(fireMicCapturedSamples(), static_cast<size_t>(kDebugMicSamples));
      if (!fireReleaseMicCapture()) {
        debugMicRecording_ = false;
        debugMicSamples_ = 0;
        debugMicStatus_ = "Microphone stop failed";
      } else {
        debugMicRecording_ = false;
        debugMicSamples_ = captured;
        if (captured == 0 || !M5.Speaker.isEnabled() ||
            !M5.Speaker.playRaw(debugMicBuffer_, captured,
                                kDebugMicSampleRate, false, 1, 0, true)) {
          debugMicSamples_ = 0;
          debugMicStatus_ = "Playback failed";
        } else {
          debugMicPlaying_ = true;
          debugMicStatus_ = "Playing recording";
        }
      }
      redrawRequested_ = true;
    } else {
      debugMicStatus_ =
          "Recording " + String((millis() - debugMicStartedAt_) / 1000) +
          "/" + String(kDebugMicSeconds) + " sec";
      redrawRequested_ = true;
    }
  }
  if (debugMicPlaying_ && !M5.Speaker.isPlaying()) {
    debugMicPlaying_ = false;
    debugMicStatus_ = "Ready - press B to record";
    redrawRequested_ = true;
  }
  if (!debugMicRecording_ && !debugMicPlaying_ && debugMicBuffer_ &&
      screen_ != Screen::Debug) {
    free(debugMicBuffer_);
    debugMicBuffer_ = nullptr;
    debugMicSamples_ = 0;
  }
}

void FireOS::startDebugMicTest() {
  if (!M5.Mic.isEnabled()) {
    debugMicStatus_ = "Microphone unavailable";
    return;
  }
  if (!debugMicBuffer_) {
    debugMicBuffer_ = static_cast<int16_t*>(ps_malloc(
        kDebugMicSamples * sizeof(int16_t)));
    if (!debugMicBuffer_)
      debugMicBuffer_ = static_cast<int16_t*>(malloc(
          kDebugMicSamples * sizeof(int16_t)));
  }
  if (!debugMicBuffer_) {
    debugMicStatus_ = "Not enough memory";
    return;
  }
  debugMicSamples_ = 0;
  if (!fireStartMicCapture(debugMicBuffer_, kDebugMicSamples,
                           kDebugMicSampleRate)) {
    debugMicStatus_ = "Microphone capture unavailable";
    return;
  }
  debugMicStartedAt_ = millis();
  debugMicRecording_ = true;
  debugMicPlaying_ = false;
  debugMicStatus_ = "Recording 0/3 sec";
}

void FireOS::stopDebugMicTest() {
  if (!debugMicRecording_) return;
  fireStopMicCapture();
  debugMicStatus_ = "Stopping recording";
}

void FireOS::releaseDebugTestAudio() {
  if (debugMicRecording_) fireStopMicCapture();
  if (debugMicRecording_ || fireMicCaptureRunning()) fireReleaseMicCapture();
  debugMicRecording_ = false;
  if (debugMicPlaying_) M5.Speaker.stop();
  debugMicPlaying_ = M5.Speaker.isPlaying();
  if (!debugMicPlaying_ && debugMicBuffer_) {
    free(debugMicBuffer_);
    debugMicBuffer_ = nullptr;
    debugMicSamples_ = 0;
  }
}

void FireOS::cleanupDebugTests() {
  releaseDebugTestAudio();
  writeRgbForDebug(0, 0, 0, 0);
  debugRgbIndex_ = 0;
}

void FireOS::drawDebug() {
  drawStatusBar("Debug");
  if (!sdReady_ && millis() - sdLastProbe_ > 2000) initSdCard();
  auto statusColor = [](const String& status) -> uint16_t {
    if (status == "ENABLED") return kCyan;
    if (status == "READY") return kGreen;
    if (status.indexOf('%') >= 0) return kCyan;
    if (status == "DISABLED" || status == "NOT PRESENT" ||
        status == "UNAVAILABLE")
      return kMuted;
    return kOrange;
  };
  auto drawTitle = [&](const char* title, const char* subtitle) {
    ui.setTextDatum(MC_DATUM);
    drawText(160, 34, title, kCyan, 2, kBg);
    drawText(160, 45, subtitle, kMuted, 1, kBg);
    ui.setTextDatum(TL_DATUM);
  };
  auto drawStatusRow = [&](uint8_t row, const String& label,
                           const String& status) {
    const int y = 56 + row * 24;
    drawText(16, y, label, kMuted, 2, kBg);
    ui.setTextDatum(MR_DATUM);
    drawText(307, y, status, statusColor(status), 2, kBg);
    ui.setTextDatum(TL_DATUM);
  };
  auto drawValueRow = [&](uint8_t row, const String& label,
                          const String& value) {
    const int y = 57 + row * 22;
    drawText(16, y, label, kMuted, 1, kBg);
    ui.setTextDatum(MR_DATUM);
    drawText(307, y, value, kText, 1, kBg);
    ui.setTextDatum(TL_DATUM);
  };
  auto drawValueAt = [&](int y, const String& label, const String& value) {
    drawText(96, y, label, kMuted, 1, kBg);
    ui.setTextDatum(MR_DATUM);
    drawText(307, y, value, kText, 1, kBg);
    ui.setTextDatum(TL_DATUM);
  };

  if (detailIndex_ < 3) {
    drawTitle("Core hardware", detailIndex_ == 0
                                  ? "Device"
                                  : detailIndex_ == 1 ? "Connectivity & ports"
                                                      : "Storage & Lua API");
    if (detailIndex_ == 0) {
      drawStatusRow(0, "LCD", "READY");
      drawStatusRow(1, "Buttons", "READY");
      drawStatusRow(2, "IMU", M5.Imu.isEnabled() ? "ENABLED" : "UNAVAILABLE");
      drawStatusRow(3, "Microphone", M5.Mic.isEnabled() ? "ENABLED" : "READY");
      drawStatusRow(4, "Speaker",
                    M5.Speaker.isEnabled() ? "ENABLED" : "UNAVAILABLE");
      drawStatusRow(5, "RGB", "READY");
    } else if (detailIndex_ == 1) {
      drawStatusRow(0, "Wi-Fi", wifiMode_ == 2
                                    ? "DISABLED"
                                    : wifiEnabled_ ? "ENABLED" : "READY");
#ifdef FIRE_OS_BLE
      drawStatusRow(1, "Bluetooth", bluetoothMode_ == 2
                                        ? "DISABLED"
                                        : bluetoothEnabled_ ? "ENABLED" : "READY");
#else
      drawStatusRow(1, "Bluetooth", "UNAVAILABLE");
#endif
      drawStatusRow(2, "GPIO / B", "READY");
      drawStatusRow(3, "UART / B", "READY");
      drawStatusRow(4, "I2C / POGO A", "READY");
      // G16/G17 are reserved by FIRE PSRAM and are not exposed to Lua.
      drawStatusRow(5, "Port C", "DISABLED");
    } else {
      drawStatusRow(0, "SD card", sdReady_ ? "READY" : "NOT PRESENT");
      drawStatusRow(1, "SPI / VSPI", sdReady_ ? "BUSY (SD)" : "READY");
      int level = batteryLevel();
      String battery = level >= 0 ? String(level) + "%" : "UNAVAILABLE";
      if (level >= 0) battery += batteryCharging() ? " CHG" : " BAT";
      drawStatusRow(2, "Battery", battery);
      drawStatusRow(3, "Lua API / display", "READY");
      drawStatusRow(4, "Lua API / audio", "READY");
      drawStatusRow(5, "Lua API / I/O", "READY");
    }
    ui.setTextDatum(MR_DATUM);
    drawText(307, 193, "READY = FW/API", kMuted, 1, kBg);
    ui.setTextDatum(TL_DATUM);
  } else if (detailIndex_ == 3) {
    drawTitle("Hardware tests", "Buttons and RGB");
    drawStatusRow(0, "Button A", buttons_[0].down ? "DOWN" : "UP");
    drawStatusRow(1, "Button B", buttons_[1].down ? "DOWN" : "UP");
    drawStatusRow(2, "Button C", buttons_[2].down ? "DOWN" : "UP");
    static const char* const colors[] = {"OFF", "RED", "GREEN", "BLUE",
                                         "ORANGE", "PURPLE", "WHITE"};
    const uint8_t percent = static_cast<uint16_t>(debugRgbBrightness_) * 100 / 255;
    drawStatusRow(3, "RGB", String(colors[debugRgbIndex_]) + " " +
                               String(percent) + "%");
    drawText(16, 178, "B: next color   2xB: brightness", kMuted, 1, kBg);
    drawText(16, 194, "Press A/C for previous/next page", kMuted, 1, kBg);
  } else {
    drawTitle("Hardware tests", "IMU, microphone and ports");
    m5::imu_data_t imu{};
    const bool imuReady = M5.Imu.isEnabled();
    if (imuReady) M5.Imu.getImuData(&imu);
    ui.drawRoundRect(12, 55, 70, 64, 5, kPanel);
    ui.drawRect(18, 61, 58, 50, kMuted);
    ui.drawLine(47, 63, 47, 109, kMuted);
    ui.drawLine(21, 86, 73, 86, kMuted);
    int bubbleX = 47;
    int bubbleY = 86;
    if (imuReady) {
      bubbleX += constrain(static_cast<int>(imu.accel.x * 24.0f), -22, 22);
      bubbleY -= constrain(static_cast<int>(imu.accel.y * 20.0f), -18, 18);
      ui.fillCircle(bubbleX, bubbleY, 7, kCyan);
    }
    ui.setTextDatum(MC_DATUM);
    drawText(47, 115, imuReady ? "TILT" : "N/A", kText, 1, kPanel);
    ui.setTextDatum(TL_DATUM);
    drawValueAt(57, "Accel g", imuReady
                                   ? String(imu.accel.x, 2) + "  " +
                                         String(imu.accel.y, 2) + "  " +
                                         String(imu.accel.z, 2)
                                   : "UNAVAILABLE");
    drawValueAt(79, "Gyro dps", imuReady
                                  ? String(imu.gyro.x, 1) + "  " +
                                        String(imu.gyro.y, 1) + "  " +
                                        String(imu.gyro.z, 1)
                                  : "UNAVAILABLE");
    float temperature = 0.0f;
    drawValueAt(101, "IMU temp", imuReady && M5.Imu.getTemp(&temperature)
                                   ? String(temperature, 1) + " C"
                                   : "UNAVAILABLE");
    drawValueRow(3, "Mic test", debugMicStatus_);
    analogReadResolution(12);
    drawValueRow(4, "Port B raw", String("G26=") + String(digitalRead(26)) +
                                       "  G36 ADC=" + String(analogRead(36)));
    drawValueRow(5, "I2C raw", String("G21=") + String(digitalRead(21)) +
                                   "  G22=" + String(digitalRead(22)));
    drawText(16, 190, "B: record/stop/play mic test", kMuted, 1, kBg);
  }
  ui.setTextDatum(MR_DATUM);
  drawText(307, 207, String("Page ") + String(detailIndex_ + 1) + "/5",
           kMuted, 1, kBg);
  ui.setTextDatum(TL_DATUM);
  drawFooter("Previous", detailIndex_ >= 3 ? "Test" : "Refresh", "Next");
}

void FireOS::drawSystemInfo() {
  drawStatusBar("System Info");
  drawText(16, 40, "Hardware", kMuted, 1);
  drawText(16, 58, "ESP32 / M5Stack FIRE", kText, 1);
  drawText(16, 78, "CPU", kMuted, 1);
  drawText(140, 78, String(ESP.getCpuFreqMHz()) + " MHz", kText, 1);
  drawText(16, 98, "Free heap", kMuted, 1);
  drawText(140, 98, formatBytes(ESP.getFreeHeap()), kText, 1);
  drawText(16, 118, "Free PSRAM", kMuted, 1);
  drawText(140, 118, formatBytes(ESP.getFreePsram()), kText, 1);
  drawText(16, 138, "Flash", kMuted, 1);
  drawText(140, 138, formatBytes(ESP.getFlashChipSize()), kText, 1);
  drawText(16, 158, "Battery", kMuted, 1);
  String charge = batteryLevel() >= 0 ? String(batteryLevel()) + "%" : "N/A";
  charge += batteryCharging() ? "  CHG" : "  BAT";
  drawText(140, 158, charge, kText, 1);
  drawText(16, 178, "OS", kMuted, 1);
  drawText(140, 178, firmwareVersionLabel(), kGreen, 1);
  drawFooter("", "", "BACK  C");
}

void FireOS::drawPower() {
  drawStatusBar("Power");
  drawText(18, 42, "Power options", kMuted, 1);
  drawRow(0, "Restart", powerIndex_ == 0);
  drawRow(1, "Power Off", powerIndex_ == 1);
  drawRow(2, "Shutdown timer", powerIndex_ == 2, durationLabel(sleepOption_),
          powerEditing_ && powerIndex_ == 2);
  drawRow(3, "Dim screen after", powerIndex_ == 3, durationLabel(dimOption_),
          powerEditing_ && powerIndex_ == 3);
  drawRow(4, "Screen off after", powerIndex_ == 4,
          durationLabel(screenOffOption_), powerEditing_ && powerIndex_ == 4);
  drawRow(5, "Back", powerIndex_ == 5);
  drawFooter("Previous", "Select", "Next");
}

void FireOS::drawPowerActions() {
  drawStatusBar("Power");
  drawText(18, 42, "Choose action", kMuted, 1);
  drawRow(0, "Power Off", powerActionIndex_ == 0);
  drawRow(1, "Restart", powerActionIndex_ == 1);
  drawRow(2, "Sleep", powerActionIndex_ == 2);
  drawRow(3, "Back", powerActionIndex_ == 3);
  drawFooter("Previous", "Select", "Next");
}

int FireOS::batteryLevel() const {
  refreshBatteryStatus();
  return batteryLevelCached_;
}

bool FireOS::batteryCharging() const {
  refreshBatteryStatus();
  return batteryChargingCached_;
}

void FireOS::refreshBatteryStatus() const {
  if (batteryStatusAt_ != 0 && millis() - batteryStatusAt_ < 1000) return;
  batteryStatusAt_ = millis();
  batteryLevelCached_ = M5.Power.getBatteryLevel();
  batteryChargingCached_ =
      M5.Power.isCharging() == m5::Power_Class::is_charging;
}

void FireOS::drawWifiIcon(int32_t x, int32_t y, uint8_t state) {
  uint16_t color = kMuted;
  if (state == 2) {
    color = kGreen;
  } else if (state == 1) {
    color = (millis() / 250) % 2 == 0 ? kGreen : kMuted;
  }
  ui.drawLine(x, y + 3, x + 6, y, color);
  ui.drawLine(x + 6, y, x + 12, y + 3, color);
  ui.drawLine(x + 3, y + 7, x + 6, y + 5, color);
  ui.drawLine(x + 6, y + 5, x + 9, y + 7, color);
  ui.fillCircle(x + 6, y + 11, 1, color);
}

void FireOS::drawBluetoothIcon(int32_t x, int32_t y, bool enabled) {
  const uint16_t color = enabled ? kCyan : kMuted;
  ui.drawLine(x + 5, y, x + 5, y + 14, color);
  ui.drawLine(x + 5, y, x + 10, y + 4, color);
  ui.drawLine(x + 10, y + 4, x + 5, y + 8, color);
  ui.drawLine(x + 5, y + 8, x + 10, y + 12, color);
  ui.drawLine(x + 10, y + 12, x + 5, y + 14, color);
  ui.drawLine(x + 5, y + 7, x, y + 2, color);
  ui.drawLine(x + 5, y + 7, x, y + 12, color);
}

void FireOS::drawBatteryIcon(int32_t x, int32_t y, int level, bool charging) {
  const uint16_t color = charging ? kGreen : kText;
  ui.drawRect(x, y + 1, 18, 10, color);
  ui.fillRect(x + 18, y + 4, 2, 4, color);
  if (level >= 0) {
    const int width = constrain(level, 0, 100) * 14 / 100;
    ui.fillRect(x + 2, y + 3, width, 6, color);
  }
  if (charging) {
    ui.drawLine(x + 8, y - 2, x + 5, y + 5, color);
    ui.drawLine(x + 5, y + 5, x + 9, y + 5, color);
    ui.drawLine(x + 9, y + 5, x + 7, y + 13, color);
  }
}

void FireOS::drawFactoryReset() {
  drawStatusBar("Factory Reset");
  drawText(18, 58, "Reset all settings?", kOrange, 2);
  drawText(18, 92, factoryResetArmed_ ? "Ready - confirm again"
                                     : "Select to arm reset",
           TFT_WHITE, 1);
  drawText(18, 120, "App data is not removed yet.", kMuted, 1);
  drawText(18, 140, "This will restart the OS.", kMuted, 1);
  drawFooter("", "B  CONFIRM", "BACK  C");
}

void FireOS::drawRow(uint8_t row, const String& label, bool selected,
                     const String& value, bool editing) {
  const int y = 65 + row * 25;
  const int height = 21;
  const uint16_t highlight = editing ? kOrange : kCyan;
  if (selected) ui.fillRoundRect(10, y - 3, 300, height, 5, highlight);
  drawText(20, y + 2, label, selected ? kBg : kText, 1,
           selected ? highlight : kBg);
  if (value.length() > 0) {
    ui.setTextDatum(MR_DATUM);
    drawText(300, y + 2, value, selected ? kBg : kMuted, 1,
             selected ? highlight : kBg);
    ui.setTextDatum(TL_DATUM);
  }
}

void FireOS::drawLevelRow(uint8_t row, const String& label, uint8_t step,
                          uint8_t stepCount, bool selected, uint16_t accent,
                          bool editing) {
  const int y = 65 + row * 25;
  const uint16_t highlight = editing ? kOrange : kCyan;
  if (selected) ui.fillRoundRect(10, y - 3, 300, 21, 5, highlight);
  drawText(20, y + 2, label, selected ? kBg : kText, 1,
           selected ? highlight : kBg);

  constexpr int kSegments = 10;
  constexpr int kSegmentWidth = 11;
  constexpr int kSegmentGap = 2;
  const int firstX = 159;
  const uint8_t filled = stepCount <= 1
                             ? 0
                             : static_cast<uint8_t>(step * kSegments /
                                                    (stepCount - 1));
  for (int segment = 0; segment < kSegments; ++segment) {
    const bool on = segment < filled || (step == stepCount - 1 && segment == kSegments - 1);
    const uint16_t selectedAccent = accent == kCyan ? kGreen : accent;
    const uint16_t color = on ? (selected ? selectedAccent : accent)
                              : (selected ? kMuted : kPanel);
    ui.fillRoundRect(firstX + segment * (kSegmentWidth + kSegmentGap), y + 3,
                     kSegmentWidth, 9, 2, color);
  }
}

void FireOS::drawText(int32_t x, int32_t y, const String& text, uint16_t color,
                      uint8_t size, uint16_t background) {
  ui.setTextSize(size);
  ui.setTextColor(color, background);
  ui.drawString(text, x, y);
}

