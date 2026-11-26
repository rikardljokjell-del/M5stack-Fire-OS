#include "fire_app_icons.h"
#include "fire_os.h"
#include "fire_backend_policy.h"
#include "fire_audio_capture.h"
#include "fire_json_guard.h"
#include "fire_app_graphics.h"
#include "fire_app_bitmap.h"
#include "fire_canvas_fill.h"
#include "fire_app_sdk_data.h"
#include "fire_runtime_ai_json.h"
#include "fire_hardware_policy.h"
#include "fire_data_paths.h"
#include "fire_data_deadline.h"
#include "fire_ai_workflow.h"
#include "fire_app_updates.h"
#include "fire_ui.h"
#include "fire_ai_menu_ui.h"
#include "fire_button_capture.h"
#include "fire_ui_cadence.h"
#include "fire_ui_antialias.h"

#include <M5Unified.h>
#ifdef FIRE_OS_BLE
#include <driver/rmt.h>
#include <hal/rmt_ll.h>
#endif
#include <utility/led/LED_Strip_Class.hpp>
#include <Preferences.h>
#include <nvs.h>
#include <SD.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <Wire.h>
#include <WebServer.h>
#include <driver/gpio.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <esp_sleep.h>
#include <esp_ota_ops.h>
#include <sys/time.h>
#include <time.h>
#include <esp_sntp.h>
#include <math.h>
#include <string.h>
#include <errno.h>
#include <mbedtls/sha256.h>
#include <mbedtls/md.h>
#include <cJSON.h>
#ifdef FIRE_OS_BLE
#include <NimBLEDevice.h>
#endif

namespace {
String aiJobText(const cJSON* row,const char* key) {
  const cJSON* value=cJSON_GetObjectItemCaseSensitive(row,key);
  return cJSON_IsString(value) && value->valuestring?String(value->valuestring):String();
}

constexpr uint8_t kSdCsPin = 4;
const char* osMenuIcon(const String& label);
constexpr char kSdNameCharset[] =
    " ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-.";
constexpr uint8_t kButtonPins[] = {39, 38, 37};
constexpr uint16_t kBg = FireUI::Bg;
constexpr uint16_t kPanel = FireUI::Panel;
constexpr uint16_t kText = FireUI::Text;
constexpr uint16_t kMuted = FireUI::Muted;
constexpr uint16_t kCyan = FireUI::Accent;
constexpr uint16_t kOrange = FireUI::Amber;
constexpr uint16_t kGreen = FireUI::Green;
constexpr uint16_t kRed = FireUI::Red;
constexpr uint16_t kPurple = FireUI::Purple;
constexpr uint16_t kDurationMinutes[] = {
    0,  1,  2,  3,  4,  5,  6,  7,  8,  9,  10,
    11, 12, 13, 14, 15, 16, 17, 18, 19, 20};
constexpr uint8_t kBrightnessValues[] = {24, 42, 60, 90, 120,
                                         150, 180, 210, 235, 255};
constexpr uint8_t kBrightnessStepCount = 10;
constexpr uint8_t kVolumeStepCount = 10;
constexpr uint8_t kTimezoneCount = DateTimeService::kTimezoneCount;
constexpr char kFirmwareVersion[] = "fire-os-1.6.0-rc14";
// Fixed labels only: never log app names, paths, endpoints or credentials.
// Keep the lifetime loop maxima intact while locating blocking UI phases.
class FireUiPhaseTimer {
 public:
  explicit FireUiPhaseTimer(const char* phase)
      : phase_(phase), started_(esp_timer_get_time()) {}
  ~FireUiPhaseTimer() {
    const int64_t elapsed = esp_timer_get_time() - started_;
    if (elapsed >= 100000)
      Serial.printf("FIRE slow phase=%s us=%lu uptime_ms=%lu\n", phase_,
                    static_cast<unsigned long>(elapsed),
                    static_cast<unsigned long>(millis()));
  }
 private:
  const char* phase_;
  int64_t started_;
};
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
constexpr uint32_t kLuaServiceAi = 1u << 20;
constexpr uint32_t kLuaServiceData = 1u << 21;
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
FireOS* activeFireOs = nullptr;
bool bluetoothRadioReady = false;
bool fireRgbReady = false;
bool fireRgbInFlight = false;
uint32_t fireRgbTimeouts = 0;

void configureFireRgbStrip() {
#ifdef FIRE_OS_BLE
  pinMode(15, OUTPUT_OPEN_DRAIN);
  rmt_config_t config = {};
  config.rmt_mode = RMT_MODE_TX;
  config.channel = RMT_CHANNEL_0;
  config.gpio_num = GPIO_NUM_15;
  config.clk_div = 2;
  // Ten RGB LEDs need 241 words including reset. Four hardware blocks hold
  // the complete frame, so the RMT peripheral needs no refill ISR/driver task.
  // FIRE OS owns RMT channel 0 and memory blocks 0..3; Lua never owns RMT.
  config.mem_block_num = 4;
  config.tx_config.loop_en = false;
  config.tx_config.carrier_en = false;
  config.tx_config.idle_output_en = true;
  config.tx_config.idle_level = RMT_IDLE_LEVEL_LOW;
  fireRgbReady = rmt_config(&config) == ESP_OK;
  rmt_ll_enable_tx_end_interrupt(&RMT, 0, false);
  rmt_ll_enable_tx_err_interrupt(&RMT, 0, false);
  rmt_ll_enable_tx_thres_interrupt(&RMT, 0, false);
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
  if (!fireRgbReady) return;
  // A preceding hardware frame normally finishes in <400 us. Never wait for
  // an unbounded driver semaphore, or disable interrupts for LED timing.
  const int64_t waiting = esp_timer_get_time();
  while (fireRgbInFlight && !RMT.int_raw.ch0_tx_end && esp_timer_get_time() - waiting < 600) {}
  if (fireRgbInFlight && !RMT.int_raw.ch0_tx_end) { ++fireRgbTimeouts; return; }
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
  if (rmt_fill_tx_items(RMT_CHANNEL_0, items, item + 1, 0) != ESP_OK) return;
  rmt_ll_tx_reset_pointer(&RMT, 0);
  rmt_ll_clear_tx_end_interrupt(&RMT, 0);
  rmt_ll_tx_start(&RMT, 0);
  fireRgbInFlight = true;
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

int jsonObjectEnd(const String& json, int start) {
  if (start < 0 || start >= json.length() || json[start] != '{') return -1;
  int depth = 0;
  bool inString = false;
  bool escaped = false;
  for (int index = start; index < json.length(); ++index) {
    const char character = json[index];
    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (character == '\\') {
        escaped = true;
      } else if (character == '"') {
        inString = false;
      }
      continue;
    }
    if (character == '"') {
      inString = true;
    } else if (character == '{') {
      ++depth;
    } else if (character == '}' && --depth == 0) {
      return index;
    }
  }
  return -1;
}

String clipUtf8(const String& input, size_t maxBytes) {
  if (input.length() <= maxBytes) return input;
  if (maxBytes <= 3) return input.substring(0, maxBytes);
  size_t end = maxBytes - 3;
  while (end > 0 &&
         (static_cast<uint8_t>(input[end]) & 0xC0U) == 0x80U) {
    --end;
  }
  return input.substring(0, end) + "...";
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

String compactStatusText(const String& raw) {
  String value = raw;
  value.trim();
  String lower = value;
  lower.toLowerCase();
  if(lower=="backend session rejected") return "Tilkobling avvist";
  if(lower.indexOf("callback time budget")>=0) return "Appen brukte for lang tid";
  if(lower.indexOf("instruction budget")>=0 || lower.indexOf("io budget")>=0) return "Appens arbeidsgrense nådd";
  if(lower.indexOf("memory")>=0 && (lower.indexOf("budget")>=0 || lower.indexOf("error")>=0)) return "Appen mangler minne";
  if(lower.indexOf("checksum")>=0 || lower.indexOf("sha256 mismatch")>=0) return "Appkontroll feilet";
  if(lower.indexOf("failed")>=0 || lower.indexOf("rejected")>=0 || lower.indexOf("feilet")>=0) return "Apphandling feilet";
  if(lower=="package ready" || lower=="ready to run" || lower=="installed") return "App klar til kjøring";
  if(lower=="sending run" || lower=="running") return "Starter app";
  if(lower=="sending build") return "Starter bygging";
  if(lower=="connected" || lower=="connected - state restored") return "Tilkoblet";
  if(lower=="answer - speak again") return "Svar mottatt";
  if(lower=="transcribed - waiting for ai") return "Tale mottatt – vurderer";
  if (lower == "preparing" || lower.indexOf("preparing repair") >= 0)
    return "Forbereder reparasjon";
  if (lower == "awaiting_confirmation" ||
      lower.indexOf("repair proposal") >= 0)
    return "Venter på reparasjonsforslag";
  if (lower == "queued") return "Lagt i kø";
  if (lower == "building" || lower == "generating") return "Lager app";
  if (lower == "validating") return "Validerer app";
  if (lower == "compiling") return "Kontrollerer app";
  if (lower == "testing") return "Tester app";
  if (lower == "packaging") return "Pakker app";
  if (lower == "ready" || lower == "ready_to_run") return "App klar";
  if (lower == "failed") return "Bygging feilet";
  if (lower == "downloading" || lower.indexOf("downloading") >= 0)
    return "Laster ned app";
  if (lower == "installing" || lower.indexOf("install") >= 0)
    return "Installerer app";
  if (lower == "starting" || lower.indexOf("starting fixed") >= 0)
    return "Starter rettet app";
  if (lower == "running") return "App kjører";
  if (lower.indexOf("backend disconnected") >= 0)
    return "Backend er frakoblet";
  if (lower.indexOf("backend connection") >= 0)
    return "Kobler til backend";
  if (lower.indexOf("waiting for backend") >= 0)
    return "Venter på backend";
  if (value.length() <= 28 && value.indexOf("...")<0 && value.indexOf("…")<0 &&
      value.indexOf('\n')<0 && lower.indexOf("du spurte om")<0) return value;
  return "Arbeider";
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

int buildProgressField(const String& json,int fallback=0) {
  int progress = jsonIntField(json, "progress_percent", -1);
  if (progress >= 0) return progress;
  const int progressAt = json.indexOf("\"progress\"");
  if (progressAt < 0) return fallback;
  const int colon = json.indexOf(':', progressAt);
  if (colon < 0) return fallback;
  int valueAt = colon + 1;
  while (valueAt < json.length() &&
         (json[valueAt] == ' ' || json[valueAt] == '\t' ||
          json[valueAt] == '\r' || json[valueAt] == '\n'))
    ++valueAt;
  if (valueAt < json.length() && json[valueAt] == '{') {
    const int end = jsonObjectEnd(json, valueAt);
    if (end > valueAt) {
      const String object = json.substring(valueAt, end + 1);
      progress = jsonIntField(object, "percent", -1);
      if (progress < 0) progress = jsonIntField(object, "progress", -1);
      if (progress >= 0) return progress;
    }
    return fallback;
  }
  return json.substring(valueAt).toInt();
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
    else if (service == "bluetooth") bit = kLuaServiceBluetooth;
    else if (service == "wifi") bit = kLuaServiceWifi;
    else if (service == "sd") bit = kLuaServiceSd;
    else if (service == "rtc") bit = kLuaServiceRtc;
    else if (service == "speaker") bit = kLuaServiceSpeaker;
    else if (service == "mic") bit = kLuaServiceMic;
    else if (service == "ai") bit = kLuaServiceAi;
    else if (service == "data") bit = kLuaServiceData;
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

bool luaDataManifest(const String& manifest,bool sdk,uint32_t mask) {
  if (manifest.indexOf("\\u0000")>=0) return false;
  cJSON* root=cJSON_Parse(manifest.c_str());if (!root) return false;
  const cJSON* extension=cJSON_GetObjectItemCaseSensitive(root,"data_engine");
  const bool requested=(mask&kLuaServiceData)!=0;
  const cJSON* permissions=cJSON_GetObjectItemCaseSensitive(root,"permissions");
  bool permitted=false;
  const cJSON* permission=nullptr;
  if (cJSON_IsArray(permissions)) {cJSON_ArrayForEach(permission,permissions)
    if (cJSON_IsString(permission) && !strcmp(permission->valuestring,"fire.data")) permitted=true;}
  const cJSON* version=cJSON_GetObjectItemCaseSensitive(extension,"version");
  const cJSON* contract=cJSON_GetObjectItemCaseSensitive(extension,"contract");
  const bool valid=requested?(sdk && (mask&kLuaServiceJobs) && (mask&kLuaServiceSd) && permitted &&
      cJSON_IsObject(extension) && cJSON_GetArraySize(extension)==2 && cJSON_IsString(version) &&
      !strcmp(version->valuestring,FireDataEngineContract::kVersion) && cJSON_IsString(contract) &&
      !strcmp(contract->valuestring,FireDataEngineContract::kContract)):!extension;
  cJSON_Delete(root);return valid;
}

bool luaRuntimeAiManifest(const String& manifest,bool sdk,uint32_t mask) {
  cJSON* root=cJSON_Parse(manifest.c_str());if(!root) return false;
  const cJSON* extension=cJSON_GetObjectItemCaseSensitive(root,"runtime_ai");
  const bool ai=(mask&kLuaServiceAi)!=0;
  bool permitted=false;
  const cJSON* permissions=cJSON_GetObjectItemCaseSensitive(root,"permissions");
  const cJSON* entry=nullptr;
  if(cJSON_IsArray(permissions)) {cJSON_ArrayForEach(entry,permissions)
    if(cJSON_IsString(entry) && !strcmp(entry->valuestring,"fire.ai")) permitted=true;}
  const cJSON* version=cJSON_GetObjectItemCaseSensitive(extension,"version");
  const cJSON* contract=cJSON_GetObjectItemCaseSensitive(extension,"contract");
  const bool valid=ai?(sdk && (mask&kLuaServiceJobs) && permitted && cJSON_IsObject(extension) &&
    cJSON_IsString(version) && !strcmp(version->valuestring,FireRuntimeAiContract::kVersion) &&
    cJSON_IsString(contract) && !strcmp(contract->valuestring,FireRuntimeAiContract::kContract)):!extension;
  cJSON_Delete(root);return valid;
}

String durationLabel(uint8_t option) {
  const uint16_t minutes = kDurationMinutes[min<uint8_t>(option, 20)];
  return minutes == 0 ? "Always on" : String(minutes) + " min";
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
  if (text == "Select / Connect") return "Connect";
  if (text == "BACKGROUND") return "Background";
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
  // Only prior-boot FIRE run receipts are disposable. Namespace/settings and
  // all package/rollback indices are retained. New runs use a boot-local ring.
  char oldRunKeys[32][16];size_t oldRunCount=0;
  nvs_iterator_t iterator=nvs_entry_find("nvs","fire_os",NVS_TYPE_STR);
  while(iterator && oldRunCount<32) {
    nvs_entry_info_t info;nvs_entry_info(iterator,&info);
    if(fire_run_receipts::legacyKey(info.key)) {
      const String value=preferences.getString(info.key,"");
      if(fire_run_receipts::legacyValue(value.c_str())) strlcpy(oldRunKeys[oldRunCount++],info.key,16);
    }
    iterator=nvs_entry_next(iterator);
  }
  nvs_release_iterator(iterator);
  size_t removed=0;
  for(size_t i=0;i<oldRunCount;++i) {
    const String value=preferences.getString(oldRunKeys[i],"");
    if(fire_run_receipts::legacyValue(value.c_str()) && preferences.remove(oldRunKeys[i])) ++removed;
  }
  Serial.printf("FIRE prior-boot run receipts removed=%u\n",unsigned(removed));
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
  fireInitTrust();
  homeApp_.begin();
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
    backendClient_->setRuntimeAiMode(aiRuntimeAuto_?"auto":"off",false);
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
  backendBootPending_ = backendClient_ && backendClient_->configured() &&
                        wifiMode_ != 2 && backendMode_ != 2;
  backendBootAttempted_ = false;
  backendBootAttemptedAt_ = 0;
  backendBootSyncWaiting_ = backendBootPending_;
  backendBootJobsReceived_ = false;
  backendBootSyncStartedAt_ = 0;
  buildJobsRetryCount_ = 0;
  buildJobsRequestAt_ = 0;

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
  beginButtonCapture();
}

void FireOS::update() {
  const int64_t loopStartedUs = esp_timer_get_time();
  bool renderedThisLoop = false;
  if (lastLoopStartedUs_) maxLoopGapUs_ = max(maxLoopGapUs_, static_cast<uint32_t>(min<int64_t>(60000000, loopStartedUs - lastLoopStartedUs_)));
  lastLoopStartedUs_ = loopStartedUs;
  { FireUiPhaseTimer timing("m5_update"); M5.update(); }
  // M5Unified updates button state in M5.update(), but the IMU data register
  // is refreshed separately. Keep one bounded 50 Hz update for the Debug view
  // and the shared Lua IMU service so both expose live sensor values.
  static uint32_t lastImuUpdateAt = 0;
  const uint32_t now = millis();
  if (M5.Imu.isEnabled() && !luaDataImu_.active() && now - lastImuUpdateAt >= 20) {
    M5.Imu.update();
    lastImuUpdateAt = now;
  }
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
  { FireUiPhaseTimer timing("boot_feedback"); updateBootFeedback(); }
  updateFirmwareBootGuard();
  if (ota_.busy() || ota_.finished()) {
    firmwareMessage_ = ota_.message();
    if (!ota_.busy()) { if (ota_.succeeded()) otaRebootAt_ = millis(); ota_.acknowledge(); }
  }
  if (otaRebootAt_ && millis() - otaRebootAt_ >= 750) ESP.restart();
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
  if (redrawRequested_) {
    FireUiPhaseTimer timing("draw_input");
    draw();
    renderedThisLoop = true;pollButtons();
  }
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
  serviceLocalQa();
  serviceFirmwareAction();
  servicePackageInstall();
  if (auto* request = setupPortal_.take()) {
    const bool provision = request->operation == FireSetupPortal::Operation::Provision;
    bool ok = wifiSetupActive_ && !portalCloseAt_ && setupPortal_.current(*request) &&
        ((provision && aiApiSetupActive_ && !request->token.length()) || wifiSetupTokenValid(request->token));
    String response = "Ugyldig oppsett eller lukket oppsettsokt";
    portalApplying_ = true;
    if (ok && request->operation == FireSetupPortal::Operation::Home) {
      ok = homeApp_.configure(request->config, response);
      if (ok) response = "Home-oppsett lagret og kontrollert.";
    } else if (ok && (provision || request->operation == FireSetupPortal::Operation::Backend)) {
      ok = aiApiSetupActive_ && saveBackendSetupFields(request->host, request->port, request->secret, request->device);
      if (ok) { response = "Backend-oppsett lagret."; finishBackendSetup(); }
      else response = "Ugyldig backend-oppsett";
    } else if (ok) {
      saveMobileSetupFields(request->ssid, request->password, "");
      response = "Wi-Fi-oppsett lagret.";
    }
    portalApplying_ = false; setupPortal_.complete(ok, response);
  }
  if (portalCloseAt_ && setupPortal_.replied() && millis() - portalCloseAt_ >= 100) {
    const bool reconnect = portalReconnect_;
    stopWifiSetup();
    if (reconnect && wifiMode_ != 2) beginWifiConnection();
  }
  if (wifiSetupActive_ && millis() - wifiSetupStartedAt_ > 600000) stopWifiSetup();
  if (homeApp_.configured() && screen_ == Screen::Home && wifiMode_ != 2 &&
      WiFi.status() != WL_CONNECTED && !wifiConnectActive_ && wifiSsid_.length())
    requestWifi(true);
  { FireUiPhaseTimer timing("home_service"); homeApp_.service(WiFi.status() == WL_CONNECTED, wifiMode_ != 2 && !firmwareNetworkPaused_ && !(packageManager_ && packageManager_->otherNetworksPaused())); }
  if (homeApp_.takeSetupRequest()) {
    startWifiSetup(); homeApp_.setupHint(wifiSetupPassword_);
  }
  serviceLuaAppScan();
  updateWifiState();
  updateBluetoothScan();
  { FireUiPhaseTimer timing("hardware_jobs"); serviceLuaHardwareJobs(); }
  serviceDataDevelopHandoff();
  {
  FireUiPhaseTimer timing("reverse_service");
  reverseTransport_.service(!firmwareNetworkPaused_ && !(packageManager_ && packageManager_->networkPaused()) && WiFi.status() == WL_CONNECTED &&
                            backendClient_ && backendClient_->configured());
  }
  { FireUiPhaseTimer timing("time_sync"); updateTimeSync(); }
  updateBackend();
  serviceEvolution();
  updateAiAudio();
  updateDebugTests();
  updateAiAudioOutput();
  if (firmwareStorage_)
    firmwareStorage_->service(WiFi.status() == WL_CONNECTED, sdReady_);
  if (githubFirmware_)
    githubFirmware_->service(WiFi.status() == WL_CONNECTED, sdReady_);
  manageDisplayPower();
  // A static menu is not an animation. Input/network callbacks request an
  // immediate frame; the one-second fallback refreshes clock/battery/status.
  const auto cadence=screen_==Screen::LuaApp && luaAppActive_?fire_ui_cadence::View::Lua:
      screen_==Screen::AiDeveloper && !aiProjectPickerActive_?fire_ui_cadence::View::Developer:
      screen_==Screen::Debug || screen_==Screen::Home ||
      (screen_==Screen::QuickSettings && previousScreen_==Screen::LuaApp && luaAppActive_)?fire_ui_cadence::View::Live:fire_ui_cadence::View::Static;
  pollButtons(); // drain edges captured during the previous frame/background work
  if (!renderedThisLoop && fire_ui_cadence::due(millis(),lastDrawAt_,redrawRequested_,cadence)) {
    if (esp_timer_get_time() - loopStartedUs < 20000) {
      FireUiPhaseTimer timing("draw_frame"); draw();
    } else {
      // A costly callback already used this turn. Keep the frame pending so
      // the next turn renders it before optional work, including animation.
      redrawRequested_ = true;
    }
  }
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
  maxLoopUs_ = max(maxLoopUs_, static_cast<uint32_t>(min<int64_t>(
      60000000, esp_timer_get_time() - loopStartedUs)));
  if (millis() - diagnosticsAt_ >= 30000) {
    diagnosticsAt_ = millis();
    const uint32_t caps = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
    const uint32_t largest = heap_caps_get_largest_free_block(caps);
    minLargestInternal_ = min(minLargestInternal_, largest);
    Serial.printf("FIRE diag loop_us=%lu gap_us=%lu callback_us=%lu heap=%u min_heap=%u largest=%u min_largest=%lu stack=%u rgb_timeouts=%lu input_dispatch_us=%lu input_present_us=%lu input_dropped=%lu render_us=%lu present_us=%lu\n",
        (unsigned long)maxLoopUs_, (unsigned long)maxLoopGapUs_,
        (unsigned long)(luaRuntime_ ? luaRuntime_->maxCallbackUs() : 0),
        heap_caps_get_free_size(caps), heap_caps_get_minimum_free_size(caps), largest,
        (unsigned long)minLargestInternal_, uxTaskGetStackHighWaterMark(nullptr), (unsigned long)fireRgbTimeouts, (unsigned long)maxInputDispatchUs_, (unsigned long)maxInputPresentUs_, (unsigned long)fire_button_capture::dropped(), (unsigned long)maxUiRenderUs_, (unsigned long)maxUiPresentUs_);
  }
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
  backendMode_ = min<uint8_t>(preferences.getUChar("backend_mode", 0), 2);
  aiRuntimeAuto_=preferences.getBool("runtime_ai_auto",true);
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
  luaRepairId_ = preferences.isKey("repair_id")
                     ? preferences.getString("repair_id", "")
                     : String();
  luaRepairProjectId_ = preferences.isKey("repair_project")
                            ? preferences.getString("repair_project", "")
                            : String();
  luaRepairProposalId_ = preferences.isKey("repair_proposal")
                             ? preferences.getString("repair_proposal", "")
                             : String();
  luaRepairReadyPackageId_ = preferences.isKey("repair_package")
                                ? preferences.getString("repair_package", "")
                                : String();
  luaRepairReadyVersion_ = preferences.isKey("repair_version")
                              ? preferences.getString("repair_version", "")
                              : String();
  luaRepairStatus_ = preferences.isKey("repair_status")
                         ? preferences.getString("repair_status", "")
                         : String();
  luaRepairPhase_ = preferences.isKey("repair_phase")
                        ? preferences.getString("repair_phase", "")
                        : String();
  luaRepairMessage_ = preferences.isKey("repair_message")
                          ? preferences.getString("repair_message", "")
                          : String();
  luaRepairProgress_ = preferences.getUChar("repair_progress", 0);
  if (pendingDiagnosticAppId_.length() > 0) {
    luaErrorAppId_ = pendingDiagnosticAppId_;
    luaErrorPackageId_ = pendingDiagnosticPackageId_;
    luaErrorCode_ = pendingDiagnosticErrorCode_;
    luaAppError_ = pendingDiagnosticMessage_;
    luaErrorDiagnostics_ = pendingDiagnosticJson_;
  }
  const bool persistedRepair = luaRepairId_.length() > 0 &&
                               luaRepairStatus_ != "cancelled" &&
                               luaRepairStatus_ != "failed" &&
                               luaRepairStatus_ != "unavailable";
  luaRepairRequested_ = persistedRepair;
  luaRepairPrepareSent_ = persistedRepair;
  luaRepairStatusQueryPending_ = persistedRepair;
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
  preferences.putUChar("backend_mode", backendMode_);
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
  // Legacy dbl_/dbl_app_ keys are deliberately neither read nor rewritten.
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
  if (firmwareBusy()) return sdReady_;
  invalidateLuaApps();
  sdLastProbe_ = millis();
  // SD.begin() initializes the default VSPI bus (18/19/23 on FIRE).
  sdReady_ = SD.begin(kSdCsPin);
  if (!sdReady_) sdMessage_ = "SD card not detected";
  return sdReady_;
}

void FireOS::scanFirmwareFiles() {
  if (firmwareBusy()) { firmwareMessage_ = "Vent til firmwarearbeidet er ferdig"; return; }
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
  const auto* running = esp_ota_get_running_partition();
  esp_ota_img_states_t state = ESP_OTA_IMG_UNDEFINED;
  firmwareBootGuardActive_ = running && esp_ota_get_state_partition(running, &state) == ESP_OK &&
                             state == ESP_OTA_IMG_PENDING_VERIFY;
  firmwareBootGuardStarted_ = millis();
  // Legacy NVS counters cannot replace or override bootloader rollback state.
  preferences.remove("fw_pending"); preferences.remove("fw_attempts"); preferences.remove("fw_target");
  return false;
}

void FireOS::updateFirmwareBootGuard() {
  if (!firmwareBootGuardActive_ || millis() - firmwareBootGuardStarted_ < kFirmwareBootGuardMs) return;
  // Local health only: unavailable internet/PC is not a broken firmware.
  const bool healthy = uiCanvas && M5.Display.width() == 320 && M5.Display.height() == 240 &&
      ESP.getFreeHeap() > 32768 && millis() - lastDrawAt_ < 1000;
  if (!healthy) { esp_ota_mark_app_invalid_rollback_and_reboot(); return; }
  if (esp_ota_mark_app_valid_cancel_rollback() == ESP_OK) {
    firmwareBootGuardActive_ = false;
    Serial.println("FIRE OTA local self-test accepted; network/physical matrix not implied");
  }
}

bool FireOS::firmwareBusy() const {
  return firmwareAction_ != FirmwareAction::None || ota_.busy() || otaRebootAt_ ||
      (githubFirmware_ && githubFirmware_->busy()) ||
      (firmwareStorage_ && firmwareStorage_->busy());
}

bool FireOS::queueFirmwareAction(FirmwareAction action, bool overwrite) {
  if (firmwareBusy()) { firmwareMessage_ = "Vent til firmwarearbeidet er ferdig"; return false; }
  if (luaAppActive_ || backgroundBuildActive_ || aiAudioCaptureActive_ || aiAudioOutputActive_ ||
      aiAudioDownloadPending_ || aiVoiceTestPlaybackActive_ || aiBuildResumePending_ ||
      aiWorkflowState_ == 1 || aiWorkflowState_ == 2 ||
      aiWorkflowState_ == 3 || aiWorkflowState_ == 4 || aiWorkflowState_ == 6 ||
      (packageManager_ && packageManager_->busy()) ||
      (backendClient_ && backendClient_->audioTransferActive())) {
    firmwareMessage_ = "Fullfor aktiv AI/app-jobb for firmwareoppdatering"; return false;
  }
  invalidateLuaApps();  // Close candidate SD handles before a firmware worker.
  firmwareAction_ = action; firmwareSaveOverwrite_ = overwrite;
  firmwareNetworkPaused_ = true; firmwareQuietAt_ = millis();
  if (backendClient_ && backendClient_->active()) backendClient_->disconnect();
  reverseTransport_.service(false);
  homeApp_.service(WiFi.status() == WL_CONNECTED, false);
  if (action != FirmwareAction::InstallSd && WiFi.status() != WL_CONNECTED) requestWifi(true);
  firmwareMessage_ = "Klargjor firmwarearbeid"; redrawRequested_ = true;
  return true;
}

void FireOS::serviceFirmwareAction() {
  if (firmwareAction_ == FirmwareAction::None) {
    if (firmwareNetworkPaused_ && !firmwareBusy()) firmwareNetworkPaused_ = false;
    return;
  }
  if (firmwareBootGuardActive_) {
    firmwareMessage_ = "Venter pa oppstartskontroll";
    return;
  }
  if (firmwareAction_ != FirmwareAction::InstallSd && WiFi.status() != WL_CONNECTED) {
    if (wifiMode_ != 2 && millis() - firmwareQuietAt_ < 20000) {
      firmwareMessage_ = "Venter pa Wi-Fi"; return;
    }
    firmwareAction_ = FirmwareAction::None; firmwareNetworkPaused_ = false;
    firmwareMessage_ = "Koble til Wi-Fi og prov igjen"; redrawRequested_ = true; return;
  }
  const bool quiet = (!backendClient_ || backendClient_->networkIdle()) && homeApp_.networkIdle();
  if (!quiet || millis() - firmwareQuietAt_ < 300) {
    if (millis() - firmwareQuietAt_ < 12000) return;
    firmwareAction_ = FirmwareAction::None; firmwareNetworkPaused_ = false;
    firmwareMessage_ = "Nettverk rydder fortsatt. Prov firmware igjen"; redrawRequested_ = true; return;
  }
  const auto action = firmwareAction_; firmwareAction_ = FirmwareAction::None;
  const uint32_t caps = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
  Serial.printf("FIRE firmware quiet heap=%u largest=%u\n",
      heap_caps_get_free_size(caps), heap_caps_get_largest_free_block(caps));
  bool started = false;
  if (action == FirmwareAction::Manifest) started = githubFirmware_ && githubFirmware_->startManifest();
  else if (action == FirmwareAction::SaveSd) started = githubFirmware_ &&
      githubFirmware_->startDownload(firmwareGithubRelease_, firmwareGithubCatalog_, firmwareSaveOverwrite_);
  else if (action == FirmwareAction::InstallGithub)
    started = ota_.startGithub(firmwareGithubCatalog_, firmwareGithubRelease_.name);
  else if (action == FirmwareAction::InstallSd) started = installFirmwareFile(firmwarePendingSdPath_);
  // The selected worker now owns its frozen signed envelope. The catalog
  // manager retains the verified list for a later explicit selection/retry.
  if (started && (action == FirmwareAction::SaveSd || action == FirmwareAction::InstallGithub))
    firmwareGithubCatalog_ = static_cast<const char*>(nullptr);
  if (!started) { firmwareMessage_ = "Firmwarearbeid kunne ikke starte. Prov igjen"; firmwareNetworkPaused_ = false; }
  redrawRequested_ = true;
}

bool FireOS::installFirmwareFile(const String& path) {
  if (firmwareBusy() || (!sdReady_ && !initSdCard())) return false;
  invalidateLuaApps();
  const bool started = ota_.start(path);
  firmwareMessage_ = started ? "Kontrollerer firmware" : "Ugyldig firmwarevalg";
  redrawRequested_ = true;
  return started;
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
  invalidateLuaApps();
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
  invalidateLuaApps();
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
  invalidateLuaApps();
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
  invalidateLuaApps();
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
  if (firmwareBusy()) { sdMessage_ = "Vent til firmwarearbeidet er ferdig"; return; }
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
  if (firmwareBusy()) return;
  externalAppCount_ = 0;
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
  // Requests coalesce. Files and the candidate belong solely to the UI task.
  if (luaScanPhase_ == LuaScanPhase::Idle) luaScanPending_ = true;
}

void FireOS::invalidateLuaApps() {
  ++luaScanRevision_;
  luaScanManifest_.close();
  luaScanDirectory_.close();
  luaScanPhase_ = LuaScanPhase::Idle;
  luaScanBody_ = "";
  luaCacheValid_ = false;
  luaScanPending_ = true;
  appInventoryPending_ = true;
  if (backendMode_ == 2 || wifiMode_ == 2) return;
}

void FireOS::serviceLuaAppScan() {
  FireUiPhaseTimer timing("lua_scan_step");
  // Package extraction mutates /apps on its existing worker. Never read a
  // partially installed tree, nor publish a candidate from before that change.
  if (firmwareBusy() || (packageManager_ && packageManager_->busy())) {
    if (luaScanPhase_ != LuaScanPhase::Idle) invalidateLuaApps();
    return;
  }
  if (luaScanPhase_ == LuaScanPhase::Idle) {
    if (!luaScanPending_) {
      if (appInventoryPending_ && luaCacheValid_) sendAppInventory();
      return;
    }
    luaScanPending_ = false;
    luaScanCount_ = 0;
    luaScanComplete_ = sdReady_;
    luaScanActiveRevision_ = luaScanRevision_;
    luaScanStartedAt_ = millis();
    luaScanPhase_ = sdReady_ ? LuaScanPhase::CheckStorage : LuaScanPhase::Finish;
    return;
  }
  if (luaScanActiveRevision_ != luaScanRevision_) {
    invalidateLuaApps();
    return;
  }
  switch (luaScanPhase_) {
    case LuaScanPhase::CheckStorage:
      luaScanDirectory_ = SD.open("/");
      if (!luaScanDirectory_ || !luaScanDirectory_.isDirectory()) {
        luaScanComplete_ = false;
        luaScanPhase_ = LuaScanPhase::Finish;
      } else luaScanPhase_ = LuaScanPhase::RootExists;
      break;
    case LuaScanPhase::RootExists:
      errno = 0;
      luaScanPhase_ = SD.exists("/apps") ? LuaScanPhase::OpenRoot : LuaScanPhase::Finish;
      if (errno && errno != ENOENT) luaScanComplete_ = false;
      break;
    case LuaScanPhase::OpenRoot:
      luaScanDirectory_.close();
      luaScanDirectory_ = SD.open("/apps");
      if (!luaScanDirectory_ || !luaScanDirectory_.isDirectory()) {
        luaScanComplete_ = false;
        luaScanPhase_ = LuaScanPhase::Finish;
      } else luaScanPhase_ = LuaScanPhase::Next;
      break;
    case LuaScanPhase::Next: {
      // At most one directory entry per turn, including hidden/non-app files.
      errno = 0;
      File entry = luaScanDirectory_.openNextFile();
      if (!entry) {
        if (errno) luaScanComplete_ = false;
        luaScanPhase_ = LuaScanPhase::Finish;
        break;
      }
      String folder = entry.name();
      const bool directory = entry.isDirectory();
      entry.close();
      if (!directory || sdBaseName(folder).startsWith(".")) break;
      if (luaScanCount_ == kMaxLuaApps) {
        luaScanComplete_ = false;  // Do not claim an exhaustive truncated list.
        luaScanPhase_ = LuaScanPhase::Finish;
        break;
      }
      luaScanFolder_ = folder.startsWith("/") ? folder : "/apps/" + folder;
      luaScanPhase_ = LuaScanPhase::SourceExists;
      break;
    }
    case LuaScanPhase::SourceExists:
      errno = 0;
      luaScanPhase_ = SD.exists(sdJoinPath(luaScanFolder_, "main.lua"))
                          ? LuaScanPhase::OpenManifest : LuaScanPhase::Next;
      if (errno && errno != ENOENT) luaScanComplete_ = false;
      break;
    case LuaScanPhase::OpenManifest:
      luaScanManifest_ = SD.open(sdJoinPath(luaScanFolder_, "manifest.json"), FILE_READ);
      luaScanBody_ = "";
      luaScanExpected_ = luaScanManifest_ ? luaScanManifest_.size() : 0;
      if (!luaScanManifest_ || luaScanManifest_.isDirectory() ||
          !luaScanExpected_ || luaScanExpected_ > 8192 ||
          !luaScanBody_.reserve(luaScanExpected_)) {
        luaScanManifest_.close();
        luaScanComplete_ = false;
        luaScanPhase_ = LuaScanPhase::Next;
      } else luaScanPhase_ = LuaScanPhase::Read;
      break;
    case LuaScanPhase::Read: {
      // Bulk reads replace bytewise SD calls. One bounded block per UI turn.
      uint8_t block[256];
      const size_t amount = min(sizeof(block), luaScanExpected_ - luaScanBody_.length());
      const size_t received = luaScanManifest_.read(block, amount);
      if (received != amount || !luaScanBody_.concat(reinterpret_cast<const char*>(block), received)) {
        luaScanManifest_.close();
        luaScanComplete_ = false;
        luaScanPhase_ = LuaScanPhase::Next;
      } else if (luaScanBody_.length() == luaScanExpected_) {
        luaScanManifest_.close();
        luaScanPhase_ = LuaScanPhase::Parse;
      }
      break;
    }
    case LuaScanPhase::Parse: {
      cJSON* document = fireJsonSafe(luaScanBody_.c_str(), luaScanBody_.length(), 8192)
          ? cJSON_ParseWithOpts(luaScanBody_.c_str(), nullptr, true) : nullptr;
      if (!document || !cJSON_IsObject(document)) {
        luaScanComplete_ = false;
      } else {
        auto field = [document](const char* name) -> String {
          const cJSON* value = cJSON_GetObjectItemCaseSensitive(document, name);
          return cJSON_IsString(value) && value->valuestring ? String(value->valuestring) : String();
        };
        LuaScanItem& item = luaScanItems_[luaScanCount_++];
        item.path = sdJoinPath(luaScanFolder_, "main.lua");
        item.name = sdBaseName(luaScanFolder_);
        item.id = field("id");
        if (!item.id.length()) item.id = item.name;
        item.displayName = field("name");
        if (!item.displayName.length()) item.displayName = item.name;
        item.icon=fire_app_icons::select(item.displayName.c_str(),field("icon").c_str());
        item.version = field("version");
        item.checksum = field("checksum");
        fire_lua_install::Identity identity;
        const auto identityStatus=fire_lua_install::read(SD,(luaScanFolder_+"/"+fire_lua_install::kFilename).c_str(),identity);
        if(identityStatus==fire_lua_install::Read::Valid && item.id==identity.app &&
           item.name==identity.app && item.checksum.equalsIgnoreCase(identity.source)) item.packageId=identity.package;
        else if(identityStatus==fire_lua_install::Read::Absent)
          item.packageId=preferences.getString(compactPreferenceKey("ap_",item.name).c_str(),"");
        else luaScanComplete_=false;
        if (item.id.length() > 96 || item.displayName.length() > 128 ||
            item.version.length() > 64 || item.checksum.length() > 64 ||
            item.packageId.length() > 128) luaScanComplete_ = false;
      }
      cJSON_Delete(document);
      luaScanBody_ = "";
      luaScanPhase_ = LuaScanPhase::Next;
      break;
    }
    case LuaScanPhase::Finish:
      luaScanDirectory_.close();
      publishLuaAppScan();
      break;
    default: break;
  }
}

void FireOS::publishLuaAppScan() {
  FireUiPhaseTimer timing("lua_scan_publish");
  if (luaScanActiveRevision_ != luaScanRevision_) { invalidateLuaApps(); return; }
  // Keep the previous complete snapshot on any read/parse/truncation failure.
  // An incomplete inventory must never tell the backend that an app vanished.
  if (luaScanComplete_) {
    const String selectedMain = mainIndex_ >= kSystemMainCount &&
        mainIndex_ - kSystemMainCount < luaAppCount_ ? luaAppIds_[mainIndex_ - kSystemMainCount] : String();
    const String selectedApp = externalAppSelection_ >= externalAppCount_ &&
        externalAppSelection_ - externalAppCount_ < luaAppCount_ ? luaAppPaths_[externalAppSelection_ - externalAppCount_] : String();
    const String selectedMenu = luaMenuSelection_ < luaAppCount_ ? luaAppIds_[luaMenuSelection_] : String();
    const uint8_t oldProjectSelection=aiProjectSelection_;
    const String selectedProject = aiPickerPage_==fire_ai_menu::Page::Apps && aiProjectSelection_<luaAppCount_
        ? luaAppIds_[aiProjectSelection_] : String();
    for (uint8_t i = 0; i < luaScanCount_; ++i)
      for (uint8_t j = i + 1; j < luaScanCount_; ++j)
        if (luaScanItems_[j].name.compareTo(luaScanItems_[i].name) < 0) {
          LuaScanItem swap = luaScanItems_[i]; luaScanItems_[i] = luaScanItems_[j]; luaScanItems_[j] = swap;
        }
    luaAppCount_ = luaScanCount_;
    if (selectedMain.length()) mainIndex_ = 0;
    externalAppSelection_ = selectedApp.length() ? externalAppCount_ + luaAppCount_
        : min<uint8_t>(externalAppSelection_, externalAppCount_ + luaAppCount_);
    luaMenuSelection_ = 0;
    aiProjectSelection_ = aiPickerPage_==fire_ai_menu::Page::Apps?0:oldProjectSelection;
    if (bootAppPicker_) bootAppSelection_ = 0;
    for (uint8_t i = 0; i < luaAppCount_; ++i) {
      const LuaScanItem& item = luaScanItems_[i];
      luaAppPaths_[i] = item.path; luaAppNames_[i] = item.name;
      luaAppIds_[i] = item.id; luaAppDisplayNames_[i] = item.displayName;
      luaAppIcons_[i] = item.icon;
      luaAppVersions_[i] = item.version; luaAppChecksums_[i] = item.checksum;
      luaAppPackageIds_[i] = item.packageId;
      if (item.id == selectedMain) mainIndex_ = kSystemMainCount + i;
      if (item.path == selectedApp) externalAppSelection_ = externalAppCount_ + i;
      if (item.id == selectedMenu) luaMenuSelection_ = i;
      if (item.id == selectedProject) aiProjectSelection_ = i;
      if (bootAppPicker_ && item.path == selectedBootAppPath_) bootAppSelection_ = externalAppCount_ + i + 1;
    }
    syncLuaAppSelections();
    externalAppOffset_ = externalAppSelection_ > 4 ? externalAppSelection_ - 4 : 0;
    luaMenuOffset_ = luaMenuSelection_ > 5 ? luaMenuSelection_ - 5 : 0;
    aiProjectOffset_ = fire_ai_menu::scroll(aiProjectSelection_,aiProjectOffset_);
    if (bootAppPicker_) bootAppOffset_ = bootAppSelection_ > 5 ? bootAppSelection_ - 5 : 0;
    rebuildAppManagerItems();
    if (managerTargetValid_ && !managerTargetCurrent()) invalidateManagerTarget();
    redrawRequested_ = true;
  }
  luaCacheValid_ = true;
  luaCacheComplete_ = luaScanComplete_;
  luaScanPhase_ = LuaScanPhase::Idle;
  Serial.printf("FIRE inventory scan apps=%u complete=%u elapsed_ms=%lu\n",
                luaScanCount_, luaScanComplete_, static_cast<unsigned long>(millis() - luaScanStartedAt_));
  for (auto& item : luaScanItems_) item = LuaScanItem();
  if (appInventoryPending_) sendAppInventory();
}

void FireOS::syncLuaAppSelections() {
  updatePrefsOwner_=backendDeviceId_;
  const String saved = preferences.getString("lua_menu", "");
  for (uint8_t index = 0; index < kMaxLuaApps; ++index)
    luaMenuSelected_[index] = false;
  for (uint8_t index = 0; index < luaAppCount_; ++index) {
    luaMenuSelected_[index] = saved.indexOf("|" + luaAppIds_[index] + "|") >= 0;
    luaUpdateSuppressed_[index]=preferences.getBool(compactPreferenceKey("up_",backendDeviceId_+"|"+luaAppIds_[index]).c_str(),false);
  }

}

void FireOS::saveLuaAppSelections() {
  String saved = "|";
  for (uint8_t index = 0; index < luaAppCount_; ++index) {
    if (luaMenuSelected_[index]) saved += luaAppIds_[index] + "|";
  }
  preferences.putString("lua_menu", saved);
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
  if (write && address==0x6c && M5.Imu.getType()==m5::imu_sh200q) return false;
  return !write || fire_hardware_policy::externalI2cWrite(address);
}

void FireOS::releaseLuaHardware() {
  for (LuaHardwareJob& job:luaJobs_) if (job.kind==LuaJobKind::Data && job.state==0) cancelLuaDataJob(job,"cancelled");
  finishPartialDataCapture();
  luaDataStore_.close();luaDataAllowed_=false;luaServiceMask_=0;
  luaDataImu_.end();luaDataCaptureJob_=0;
  luaBluetooth_.cancel(luaBluetooth_.owner());luaBluetoothHandle_=0;
  if (luaWifiScanJob_) {esp_wifi_scan_stop();WiFi.scanDelete();luaWifiScanJob_=0;}
  luaDevelopMode_=String();luaDevelopInstruction_=String();luaDevelopContext_=String();luaDevelopJob_=0;
  luaFeedbackConfirmation_=false;luaFeedbackOutcome_=String();luaFeedbackAck_=String();
  for(LuaHardwareJob& job:luaJobs_) if(job.kind==LuaJobKind::RuntimeAi && job.state==0)
    cancelLuaRuntimeAi(job,"cancelled");
  luaRuntimeAiAllowed_=false;luaAiBindPackageId_=String();luaAiBindSent_=false;
  releaseLuaMic();
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
  for (LuaHardwareJob& job : luaJobs_) {noteEvolutionJob(job);job = LuaHardwareJob();}
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
    digitalWrite(26, HIGH);
    pinMode(26, INPUT);
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
      (pin == 26 && (os->luaPwmPin_ >= 0 || os->luaDacPin_ >= 0 || os->luaSpi_))) {
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
      os->luaDacPin_ >= 0 || os->luaSpi_ ||
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
      os->luaGpioClaimed_[txPin] || os->luaPwmPin_ >= 0 || os->luaDacPin_>=0 || os->luaSpi_) {
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
    Wire.setTimeOut(3);
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
  if (address==0x68 && os->luaDataImu_.active()) {
    setLuaError(error,"busy");return 0;
  }
  if (!os->luaI2cStarted_) {
    Wire.begin(21, 22, 400000);
    Wire.setTimeOut(3);
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
    Wire.setTimeOut(3);
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
      os->luaGpioClaimed_[pin] || os->aiAudioCaptureActive_ || os->luaMicJobId_) {
    setLuaError(error, os && (os->aiAudioCaptureActive_ || os->luaMicJobId_) ? "busy" : "unavailable");
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
      os->luaPwmPin_ >= 0 || os->luaSpi_ || (os->luaDacPin_ >= 0 && os->luaDacPin_ != pin)) {
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
  // SD/LCD and the external device use the same Arduino HAL transaction lock.
  // GPIO27 is LCD D/C, never an external CS. Grove B GPIO26 is exclusive.
  if (!os || !fire_hardware_policy::externalSpi(bus, sclk, miso, mosi, cs)) {
    setLuaError(error, "unavailable");
    return false;
  }
  if (os->firmwareBusy() || os->luaSpi_ || os->luaUartOpen_ ||
      os->luaGpioClaimed_[cs] || os->luaPwmPin_ >= 0 || os->luaDacPin_ >= 0) {
    setLuaError(error, "busy");
    return false;
  }
  // Reuse the established bus object. Never end/reinitialize a bus owned by
  // the display or SD when an app closes its own chip-select resource.
  SPI.begin(sclk, miso, mosi);
  pinMode(cs, OUTPUT);
  digitalWrite(cs, HIGH);
  os->luaSpi_ = &SPI;
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
  digitalWrite(26, HIGH);
  pinMode(26, INPUT);
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
  if (!fire_data_paths::privateRelative(path.c_str(),path.length())) {
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
  if (!fire_data_paths::safeMutation(path)) {setLuaError(error,"permission_denied");return 0;}
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
  if (!fire_data_paths::safeMutation(path,true)) {setLuaError(error,"permission_denied");return 0;}
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
  if (!fire_data_paths::safeMutation(path)) {setLuaError(error,"permission_denied");return false;}
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
  if (os->aiAudioCaptureActive_ || os->aiAudioOutputActive_ || os->luaMicJobId_) {
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
  if (os->aiAudioCaptureActive_ || os->aiAudioOutputActive_ || os->luaMicJobId_ ||
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

void FireOS::releaseLuaMic() {
  if (!luaMicJobId_ && !luaMicBuffer_) return;
  if (!fireTryReleaseMicCapture()) return;
  luaMicFile_.close();
  if (luaMicStageOwned_ && luaMicStage_.length()) SD.remove(luaMicStage_);
  free(luaMicBuffer_);
  luaMicBuffer_ = nullptr;
  luaMicBufferBytes_ = 0;
  luaMicStageOwned_ = false;
  luaMicStage_ = String();
  luaMicPrevious_ = String();
  luaMicJobId_ = 0;
}

bool FireOS::luaMicLevelCallback(void* context, float* level, const char** error) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !level || !os->luaMicJobId_) {
    setLuaError(error, "not_recording");
    return false;
  }
  *level = os->luaMicLevel_;
  return true;
}

uint16_t FireOS::luaMicRecordCallback(void* context, const char* path,
    int duration, int rate, const char** error) {
  auto* os = static_cast<FireOS*>(context);
  String resolved;
  if (!os || !os->luaPrivateAppPath(path, resolved, error)) return 0;
  if (duration < 100 || duration > 10000 || (rate != 8000 && rate != 16000)) {
    setLuaError(error, "invalid_argument");
    return 0;
  }
  if (!os->sdReady_ || !M5.Mic.isEnabled()) {
    setLuaError(error, "unavailable");
    return 0;
  }
  if (os->firmwareBusy() || os->aiAudioCaptureActive_ || os->aiAudioOutputActive_ ||
      os->aiAudioDownloadPending_ || os->luaSpeakerJobId_ || os->luaMicJobId_ ||
      fireMicCaptureRunning()) {
    setLuaError(error, "busy");
    return 0;
  }
  const size_t bytes = (static_cast<size_t>(duration) * rate / 1000) * 2 + 44;
  const uint16_t id = os->createLuaJob(LuaJobKind::MicRecord, error);
  if (!id) return 0;
  auto* job = os->findLuaJob(id);
  job->path = resolved;
  job->text = path;
  job->durationMs = duration;
  job->frequency = rate;
  job->mediaSize = bytes;
  job->timeoutMs = duration + 3000;
  os->luaMicJobId_ = id;
  os->luaMicStage_ = resolved + ".record-part";
  os->luaMicPrevious_ = resolved + ".record-previous";
  os->luaMicLevel_ = 0;
  return id;
}

void FireOS::serviceLuaMicJob(LuaHardwareJob& job) {
  const auto fail = [&](const char* code) {
    job.state = 2;
    job.errorCode = code;
    releaseLuaMic();
  };
  if (job.id != luaMicJobId_) { job.state = 3; job.errorCode = "cancelled"; return; }
  if (!job.started) {
    if (M5.Speaker.isPlaying()) return;
    const uint64_t total = SD.totalBytes(), used = SD.usedBytes();
    if (used > total || total - used < job.mediaSize + 4096) { fail("no_space"); return; }
    // Never remove an unowned stage or an earlier recovery copy.
    if (SD.exists(luaMicStage_) || SD.exists(luaMicPrevious_)) { fail("busy"); return; }
    luaMicBuffer_ = static_cast<uint8_t*>(heap_caps_malloc(job.mediaSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!luaMicBuffer_) { fail("memory"); return; }
    luaMicBufferBytes_ = job.mediaSize;
    writeWavHeader(luaMicBuffer_, job.mediaSize - 44, job.frequency);
    luaMicFile_ = SD.open(luaMicStage_, FILE_WRITE);
    if (!luaMicFile_) { fail("open_failed"); return; }
    luaMicStageOwned_ = true;
    if (!luaMicFile_.setBufferSize(512) ||
        !fireStartMicCapture(reinterpret_cast<int16_t*>(luaMicBuffer_ + 44),
                             (job.mediaSize - 44) / 2, job.frequency,true)) {
      fail("capture_failed"); return;
    }
    job.started = true;
  }
  if (job.step == 0) {
    const size_t samples = fireMicCapturedSamples();
    const bool running = fireMicCaptureRunning();
    if (fireMicCaptureFailed() || (!running && samples != (job.mediaSize - 44) / 2)) {
      fail("capture_failed"); return;
    }
    if (samples) {
      const auto* pcm = reinterpret_cast<const int16_t*>(luaMicBuffer_ + 44);
      const size_t count = min<size_t>(samples, 128);
      uint32_t peak = 0;
      for (size_t i = samples - count; i < samples; ++i)
        peak = max<uint32_t>(peak, static_cast<uint32_t>(abs(static_cast<int>(pcm[i]))));
      luaMicLevel_ = static_cast<float>(peak) / 32768.0f;
    }
    const size_t ready = 44 + samples * 2;
    const size_t amount = min<size_t>(ready - job.mediaRead, 4096);
    if (amount) {
      if (luaMicFile_.write(luaMicBuffer_ + job.mediaRead, amount) != amount) {
        fail("write_failed"); return;
      }
      job.mediaRead += amount;
    }
    if (running || job.mediaRead != job.mediaSize) return;
    fireReleaseMicCapture();
    luaMicFile_.close();
    luaMicFile_ = SD.open(luaMicStage_, FILE_READ);
    if (!luaMicFile_ || luaMicFile_.size() != job.mediaSize || !luaMicFile_.setBufferSize(512)) {
      fail("readback_failed"); return;
    }
    job.step = 1;
    return;
  }
  if (job.step == 1) {
    uint8_t buffer[512];
    // Bounded persistence check of every byte, not the fwrite/flush result.
    for (uint8_t part = 0; part < 8 && job.offset < job.mediaSize; ++part) {
      const size_t count = min<size_t>(sizeof(buffer), job.mediaSize - job.offset);
      if (luaMicFile_.read(buffer, count) != count ||
          memcmp(buffer, luaMicBuffer_ + job.offset, count)) {
        fail("readback_failed"); return;
      }
      job.offset += count;
    }
    if (job.offset != job.mediaSize) return;
    luaMicFile_.close();
    const bool previous = SD.exists(job.path);
    if (previous && !SD.rename(job.path, luaMicPrevious_)) { fail("commit_failed"); return; }
    if (!SD.rename(luaMicStage_, job.path)) {
      if (previous) SD.rename(luaMicPrevious_, job.path);
      fail("commit_failed"); return;
    }
    luaMicStageOwned_ = false;
    // Keep the old copy if cleanup fails; never destroy it on a failed rename.
    if (previous) SD.remove(luaMicPrevious_);
    job.state = 1;
    job.written = job.mediaSize;
    releaseLuaMic();
  }
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

uint16_t FireOS::luaAiRequestCallback(void* context,const char* instructions,size_t ni,
    const char* data,size_t nd,const char* schema,size_t ns,uint32_t timeout,const char** error) {
  auto* os=static_cast<FireOS*>(context);
  if(!os || !os->luaAppActive_ || !os->luaRuntimeAiAllowed_ || !os->luaRuntime_ || !os->luaRuntime_->running())
    {setLuaError(error,"permission_denied");return 0;}
  if(!os->runtimeAiEnabled_) {setLuaError(error,"disabled");return 0;}
  if(os->luaRunId_.length()==0 && os->luaPackageId_.length()) {
    if(os->luaAiBindPackageId_!=os->luaPackageId_) {
      os->luaAiBindPackageId_=os->luaPackageId_;os->luaAiBindAt_=millis();os->luaAiBindSent_=false;
    }
  }
  if(!os->backendClient_ || !os->backendClient_->sessionReady() || !os->luaRunId_.length())
    {setLuaError(error,"not_connected");return 0;}
  for(const LuaHardwareJob& job:os->luaJobs_) if(job.kind==LuaJobKind::RuntimeAi && job.id && job.state==0)
    {setLuaError(error,"busy");return 0;}
  if(os->nextRuntimeAiRequest_==UINT32_MAX) {setLuaError(error,"busy");return 0;}
  const uint16_t id=os->createLuaJob(LuaJobKind::RuntimeAi,error);if(!id) return 0;
  auto* job=os->findLuaJob(id);job->timeoutMs=timeout;
  job->aiRequestId="rai-"+os->backendClient_->bootId()+"-"+String(++os->nextRuntimeAiRequest_)+"-"+String(id);
  const bool copied=job->text.concat(instructions,ni) && job->path.concat(data,nd) && job->aiSchema.concat(schema,ns);
  if(!copied || job->text.length()!=ni || job->path.length()!=nd || job->aiSchema.length()!=ns) {
    *job=LuaHardwareJob();setLuaError(error,"busy");return 0;
  }
  job->requestRun=os->luaRunId_;
  cJSON* parsed=cJSON_ParseWithLength(data,nd+1);
  if (!parsed) {*job=LuaHardwareJob();setLuaError(error,"busy");return 0;}
  const cJSON* refs=cJSON_GetObjectItemCaseSensitive(parsed,"dataset_refs");
  if (refs) {
    if (!os->luaDataAllowed_ || !cJSON_IsArray(refs) || cJSON_GetArraySize(refs)<1 ||
        cJSON_GetArraySize(refs)>static_cast<int>(FireDataEngineContract::kContextDatasetRefs)) {
      cJSON_Delete(parsed);*job=LuaHardwareJob();setLuaError(error,"permission_denied");return 0;
    }
    cJSON* ids=cJSON_CreateArray();const cJSON* ref=nullptr;bool valid=ids!=nullptr;
    cJSON_ArrayForEach(ref,refs) {
      const cJSON* name=cJSON_IsString(ref)?ref:cJSON_GetObjectItemCaseSensitive(ref,"dataset_id");
      if (!cJSON_IsString(name) || !FireDataStore::identifier(name->valuestring,strlen(name->valuestring))) {valid=false;break;}
      if (!cJSON_AddItemToArray(ids,cJSON_CreateString(name->valuestring))) {valid=false;break;}
    }
    char* encoded=valid?cJSON_PrintUnformatted(ids):nullptr;
    const String names=encoded?String(encoded):String();cJSON_free(encoded);cJSON_Delete(ids);
    if (!names.length()) {cJSON_Delete(parsed);*job=LuaHardwareJob();setLuaError(error,"invalid_argument");return 0;}
    const uint16_t child=os->createLuaJob(LuaJobKind::Data,error);
    if (!child) {cJSON_Delete(parsed);*job=LuaHardwareJob();return 0;}
    auto* sync=os->findLuaJob(child);sync->dataOperation="sync";sync->path=names;sync->aiSchema="{}";
    sync->timeoutMs=FireDataEngineContract::kNetworkJobTimeoutMs;job->count=child;
  }
  cJSON_Delete(parsed);
  return id;
}

void FireOS::cancelLuaRuntimeAi(LuaHardwareJob& job,const char* reason) {
  if(job.kind!=LuaJobKind::RuntimeAi || job.state!=0) return;
  if(job.started && backendClient_ && backendClient_->sessionReady())
    backendClient_->runtimeAiCancel(job.aiRequestId,luaAppId_,luaPackageId_,luaSourceHash_,luaRunId_);
  if (job.count) {luaJobCloseCallback(this,job.count);job.count=0;}
  job.state=!strcmp(reason,"cancelled")?3:2;job.errorCode=reason;
  job.text=String();job.path=String();job.aiSchema=String();
}

void FireOS::handleRuntimeAiResult(const String& message) {
  if(!luaAppActive_ || !luaRuntimeAiAllowed_ || !luaRuntime_ || !luaRuntime_->running() || !backendClient_) return;
  if(jsonStringField(message,"app_id")!=luaAppId_ || jsonStringField(message,"package_id")!=luaPackageId_ ||
     jsonStringField(message,"source_sha256")!=luaSourceHash_ || jsonStringField(message,"run_id")!=luaRunId_ ||
     jsonStringField(message,"boot_id")!=backendClient_->bootId()) return;
  const String requestId=jsonStringField(message,"request_id");
  for(LuaHardwareJob& job:luaJobs_) {
    if(!job.id || job.kind!=LuaJobKind::RuntimeAi || job.state!=0 || !job.started || job.aiRequestId!=requestId) continue;
    if(millis()-job.startedAt>job.timeoutMs) {cancelLuaRuntimeAi(job,"timeout");return;}
    cJSON* root=cJSON_Parse(message.c_str());if(!root) {cancelLuaRuntimeAi(job,"invalid_result");return;}
    const cJSON* state=cJSON_GetObjectItemCaseSensitive(root,"state");
    const cJSON* data=cJSON_GetObjectItemCaseSensitive(root,"result_json");
    const cJSON* code=cJSON_GetObjectItemCaseSensitive(root,"error_code");
    if(!runtimeAiEnabled_) {job.state=2;job.errorCode="disabled";}
    else if(cJSON_IsString(state) && !strcmp(state->valuestring,"completed")) {
      const size_t bytes=cJSON_IsString(data)?strlen(data->valuestring):0;
      if(bytes>FireRuntimeAiContract::kResultBytes) {job.state=2;job.errorCode="result_too_large";}
      else if(!fire_runtime_ai_json::validObject(cJSON_IsString(data)?data->valuestring:nullptr,bytes,FireRuntimeAiContract::kResultBytes))
        {job.state=2;job.errorCode="invalid_result";}
      else if(!job.text.concat(data->valuestring,bytes) || job.text.length()!=bytes) {job.state=2;job.errorCode="invalid_result";}
      else job.state=1;
    } else if(cJSON_IsString(state) && (!strcmp(state->valuestring,"failed") || !strcmp(state->valuestring,"cancelled"))) {
      job.state=!strcmp(state->valuestring,"cancelled")?3:2;
      job.errorCode=cJSON_IsString(code) && strlen(code->valuestring)<=64?code->valuestring:"provider_error";
    } else {job.state=2;job.errorCode="invalid_result";}
    cJSON_Delete(root);if(job.state!=1) job.text=String();return;
  }
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
  if (job->kind==LuaJobKind::Bluetooth && job->dataOperation=="advertise") snapshot->handle=job->written;
  snapshot->entryCount = job->entryCount;
  for (uint16_t index = 0; index < job->entryCount && index < 32; ++index) {
    snapshot->entries[index].name = job->entryNames[index];
    snapshot->entries[index].sizeBytes = job->entrySizes[index];
    snapshot->entries[index].directory = job->entryDirectories[index];
  }
  snapshot->path = job->path;
  if (job->kind==LuaJobKind::Data && job->dataOperation=="read") {
    snapshot->written=job->offset;snapshot->connected=job->append;
  }
  if (job->kind == LuaJobKind::MicRecord) {
    snapshot->path = job->text;
    snapshot->sizeBytes = job->mediaSize;
    snapshot->sampleRate = job->frequency;
  }
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
                         : job->kind == LuaJobKind::RuntimeAi
                             ? FireLuaRuntime::JobSnapshot::RuntimeAi
                         : job->kind == LuaJobKind::MicRecord
                             ? FireLuaRuntime::JobSnapshot::Recording
                         : job->kind == LuaJobKind::Data
                             ? (job->dataOperation=="read"?FireLuaRuntime::JobSnapshot::DataRead:FireLuaRuntime::JobSnapshot::Data)
                         : job->kind == LuaJobKind::Bluetooth
                             ? (job->dataOperation=="scan"?FireLuaRuntime::JobSnapshot::Data:
                                job->dataOperation=="advertise"?FireLuaRuntime::JobSnapshot::Handle:
                                job->dataOperation=="read_gatt"?FireLuaRuntime::JobSnapshot::Bytes:FireLuaRuntime::JobSnapshot::Write)
                         : job->kind == LuaJobKind::WifiScan
                             ? FireLuaRuntime::JobSnapshot::Data
                         : FireLuaRuntime::JobSnapshot::Write;
  return true;
}

bool FireOS::luaJobCloseCallback(void* context, uint16_t id) {
  auto* os = static_cast<FireOS*>(context);
  LuaHardwareJob* job = os ? os->findLuaJob(id) : nullptr;
  if (!job) return false;
  os->noteEvolutionJob(*job);
  if (job->kind==LuaJobKind::Data && job->state==0) os->cancelLuaDataJob(*job,"cancelled");
  if(job->kind==LuaJobKind::RuntimeAi && job->state==0) os->cancelLuaRuntimeAi(*job,"cancelled");
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
  if (job->kind==LuaJobKind::Data) {os->cancelLuaDataJob(*job,"cancelled");return true;}
  if(job->kind==LuaJobKind::RuntimeAi) {os->cancelLuaRuntimeAi(*job,"cancelled");return true;}
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

#include "fire_os_bluetooth.inc"
#include "fire_os_data.inc"

void FireOS::serviceLuaHardwareJobs() {
  for (LuaHardwareJob& job:luaJobs_) noteEvolutionJob(job);
  finishPartialDataCapture();
  if (luaWifiScanJob_) {
    const LuaHardwareJob* job=findLuaJob(luaWifiScanJob_);
    if (!job || job->state!=0) {esp_wifi_scan_stop();WiFi.scanDelete();luaWifiScanJob_=0;}
  }
  luaBluetooth_.service();
  if (luaBluetooth_.owner() && luaBluetooth_.owner()!=luaBluetoothHandle_) {
    const uint16_t id=luaBluetooth_.owner();const LuaHardwareJob* owner=findLuaJob(id);
    if (!owner || owner->state!=0) luaBluetooth_.cancel(id);
  }
  if (luaDataUploadJob_) {
    const LuaHardwareJob* upload=findLuaJob(luaDataUploadJob_);
    if (!upload || upload->state!=0 || luaDataUploadCancelled_) {
      if (backendClient_ && backendClient_->audioTransferActive()) backendClient_->cancelAudioTransfer();
      else {
        free(luaDataUploadBuffer_);luaDataUploadBuffer_=nullptr;
        luaDataUploadJob_=0;luaDataUploadCancelled_=false;
      }
    }
  }
  if (luaMicJobId_) {
    const LuaHardwareJob* mic=findLuaJob(luaMicJobId_);
    if (!mic || mic->state!=0) releaseLuaMic();
  }
  if (luaDataStore_.hashingJob()) {
    const uint16_t id=luaDataStore_.hashingJob();const LuaHardwareJob* active=findLuaJob(id);
    if (!active || active->state!=0) luaDataStore_.cancel(id);
  }
  if (luaDataCaptureJob_) {
    const LuaHardwareJob* active=findLuaJob(luaDataCaptureJob_);
    if (!active || active->state!=0) {
      luaDataImu_.end();luaDataCaptureJob_=0;
    }
  }
  if (luaSpeakerJobId_ == 0) releaseLuaSpeakerBufferIfReady();
  if (luaSpeakerPlaying_ && volume_ == 0 && M5.Speaker.isEnabled())
    M5.Speaker.stop(kLuaSpeakerChannel);
  for (LuaHardwareJob& job : luaJobs_) {
    if (job.id == 0 || job.state != 0) continue;
    const uint32_t now = millis();
    const bool dataLocal=job.kind==LuaJobKind::Data && job.dataOperation!="process" && job.dataOperation!="develop" && job.dataOperation!="sync";
    if (fire_data_deadline::expired(now,job.startedAt,job.lastProgressAt,job.timeoutMs,dataLocal,
          job.kind==LuaJobKind::RuntimeAi && job.count!=0)) {
      if (job.kind==LuaJobKind::Data) {cancelLuaDataJob(job,"timeout");continue;}
      if (job.kind == LuaJobKind::MicRecord) releaseLuaMic();
      if(job.kind==LuaJobKind::RuntimeAi) {cancelLuaRuntimeAi(job,"timeout");continue;}
      job.state = 2;
      job.errorCode = "timeout";
      continue;
    }
    if (job.kind == LuaJobKind::WifiScan) {serviceLuaWifiScan(job);continue;}
    if (job.kind == LuaJobKind::Bluetooth) {serviceLuaBluetoothJob(job);continue;}
    if (job.kind == LuaJobKind::Data) {serviceLuaDataJob(job);continue;}
    if (job.kind == LuaJobKind::MicRecord) {
      serviceLuaMicJob(job);
      continue;
    }
    if(job.kind==LuaJobKind::RuntimeAi) {
      if(!luaAppActive_ || !luaRuntimeAiAllowed_ || !luaRuntime_ || !luaRuntime_->running()) {cancelLuaRuntimeAi(job,"stale_run");continue;}
      if(!runtimeAiEnabled_) {cancelLuaRuntimeAi(job,"disabled");continue;}
      if(!backendClient_ || !backendClient_->sessionReady()) {cancelLuaRuntimeAi(job,"not_connected");continue;}
      if (job.requestRun!=luaRunId_) {cancelLuaRuntimeAi(job,"stale_run");continue;}
      if (job.count) {
        const LuaHardwareJob* sync=findLuaJob(job.count);
        if (!sync || sync->state>1) {cancelLuaRuntimeAi(job,sync?sync->errorCode.c_str():"cancelled");continue;}
        if (sync->state==0) continue;
        if (!jsonBoolField(sync->text,"ok",false)) {cancelLuaRuntimeAi(job,"invalid_data");continue;}
        luaJobCloseCallback(this,job.count);job.count=0;job.append=true;
      }
      if(!job.started) {
        if(backendClient_->runtimeAiRequest(job.aiRequestId,luaAppId_,luaPackageId_,luaSourceHash_,luaRunId_,
              job.text,job.path,job.aiSchema,job.timeoutMs)) {
          if (job.append) {job.startedAt=millis();job.append=false;}
          job.started=true;job.text=String();job.path=String();job.aiSchema=String();
        } else cancelLuaRuntimeAi(job,"not_connected");
      }
      continue;
    } else if (job.kind == LuaJobKind::I2cScan) {
      uint8_t processed = 0;
      while (job.step < 127 && processed++ < 2) {
        const uint8_t address = static_cast<uint8_t>(job.step++);
        Wire.beginTransmission(address);
        if (Wire.endTransmission() == 0 && job.addressCount < 126)
          job.addresses[job.addressCount++] = address;
      }
      if (job.step >= 127) job.state = 1;
    } else if (job.kind == LuaJobKind::I2cRead) {
      if (job.address==0x68 && luaDataImu_.active()) {
        job.state=2;job.errorCode="busy";continue;
      }
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
      const uint16_t chunk = job.payloadCount;
      luaSpi_->beginTransaction(
          SPISettings(luaSpiFrequency_, MSBFIRST, luaSpiMode_));
      digitalWrite(26, LOW);
      for (uint16_t index = 0; index < chunk; ++index) {
        job.bytes[job.step + index] =
            luaSpi_->transfer(job.payload[job.step + index]);
      }
      digitalWrite(26, HIGH);
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
        if (aiAudioCaptureActive_ || aiAudioOutputActive_ || luaMicJobId_) {
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
        if (aiAudioCaptureActive_ || aiAudioOutputActive_ || luaMicJobId_) {
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
  FireUiPhaseTimer timing("app_manager");
  const String selectedId = managerSelection_ < managerItemCount_ ? managerItems_[managerSelection_].appId : String();
  const String selectedPath = managerSelection_ < managerItemCount_ ? managerItems_[managerSelection_].localPath : String();
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
    item.name = luaAppDisplayNames_[index].length()?luaAppDisplayNames_[index]:luaAppNames_[index];
    item.localPath = source;
    item.localPackageId = luaAppPackageIds_[index];
    item.localVersion = luaAppVersions_[index];
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
  for (uint8_t i = 0; i < managerItemCount_; ++i)
    if ((selectedId.length() && managerItems_[i].appId == selectedId) ||
        (!selectedId.length() && selectedPath.length() && managerItems_[i].localPath == selectedPath))
      managerSelection_ = i;
  const uint8_t itemCount = managerItemCount_ + 1;
  if (managerSelection_ >= itemCount) managerSelection_ = itemCount - 1;
  if (managerSelection_ < managerOffset_) managerOffset_ = managerSelection_;
  if (managerSelection_ >= managerOffset_ + 6)
    managerOffset_ = managerSelection_ - 5;
}

bool FireOS::requestBackendCatalogPage(uint32_t offset) {
  if (!backendClient_ || !backendClient_->sessionReady()) return false;
  backendCatalogRequest_="catalog-"+String(esp_random(),HEX)+"-"+String(millis(),HEX);
  backendCatalogRequestAt_=millis();backendCatalogRequestEpoch_=backendClient_->connectionEpoch();
  backendCatalogNextOffset_=offset;
  backendCatalogLoading_=backendClient_->appList(offset,backendCatalogRequest_);
  return backendCatalogLoading_;
}
void FireOS::failBackendCatalog() {
  backendCatalogLoading_=false;backendCatalogRequested_=false;backendCatalogRequest_=String();
  backendCatalogFailures_=min<uint8_t>(2,backendCatalogFailures_+1);backendCatalogAttemptAt_=millis();
  backendCatalogStatus_="Katalog ikke oppdatert";
  if (screen_==Screen::AppsSettings && !managerTargetValid_ && downloadPhase_!=1 && downloadPhase_!=2) managerStatus_=backendCatalogStatus_;
  redrawRequested_=true;
}
void FireOS::invalidateBackendCatalog() {
  if (backendCatalogLoading_) backendCatalogDirty_=true;
  backendCatalogRequested_=false;
}
void FireOS::clearBackendCatalog() {
  for (uint8_t i=0;i<backendAppCount_;++i) backendApps_[i]=BackendAppInfo();
  backendAppCount_=0;backendCatalogEpoch_=backendCatalogAt_=backendCatalogSeen_=0;
  backendCatalogRequested_=backendCatalogLoading_=backendCatalogOverflow_=backendCatalogDirty_=false;
  backendCatalogRequestAt_=backendCatalogAttemptAt_=backendCatalogRequestEpoch_=0;
  backendCatalogFailures_=0;backendCatalogRequest_=String();
  appUpdateStage_=0;appUpdateReady_=false;appUpdateRequest_=String();
  invalidateManagerTarget();
  if(downloadPhase_==1 || downloadPhase_==2) cancelAppDownload();
  userRunAfterInstall_=String();
  appManagerVersionCount_=0;appManagerVersionDialog_=false;
  appManagerActionMenu_=false;appManagerDeleteConfirm_=appManagerDeleteWaiting_=false;appManagerDeleteMode_=0;
  rebuildAppManagerItems();
}
void FireOS::updateAppManagerBackend() {
  if(appManagerVersionsWaiting_ && (uint32_t(millis()-appManagerRequestAt_)>=10000 ||
      (backendClient_ && backendClient_->sessionReady() && appManagerRequestEpoch_!=backendClient_->connectionEpoch()))) {
    appManagerVersionsWaiting_=false;appManagerRequest_=String();managerStatus_="Versjoner ikke mottatt. Velg på nytt.";redrawRequested_=true;
  }
  if(appManagerDeleteWaiting_ && appManagerDeleteRequest_.length() && uint32_t(millis()-appManagerRequestAt_)>=10000) {
    appManagerDeleteWaiting_=false;appManagerDeleteRequest_=String();managerStatus_="Sletting ikke bekreftet. Velg på nytt.";redrawRequested_=true;
  }
  // Only existing online demand reaches this service. App opening never calls it.
  if (!backendClient_ || !backendClient_->sessionReady()) return;
  const uint32_t now=millis();
  if (fire_app_updates::catalogTimeout(now,backendCatalogLoading_,backendCatalogRequestAt_)) failBackendCatalog();
  if (!luaCacheValid_ || !luaCacheComplete_ || appInventoryPending_ ||
      !fire_app_updates::catalogDue(now,backendCatalogLoading_,backendCatalogRequested_,backendCatalogAt_,backendCatalogAttemptAt_,backendCatalogFailures_)) return;
  backendCatalogAttemptAt_=now;backendCatalogSeen_=0;backendCatalogOverflow_=false;backendCatalogDirty_=false;
  if (requestBackendCatalogPage(0)) {
    backendCatalogRequested_=true;backendCatalogStatus_="Loading backend apps...";
    if(screen_==Screen::AppsSettings && !managerTargetValid_ && downloadPhase_!=1 && downloadPhase_!=2) managerStatus_=backendCatalogStatus_;
    redrawRequested_=true;
  } else failBackendCatalog();
}

void FireOS::parseBackendAppCatalog(const String& message) {
  if (!backendCatalogLoading_ || !backendClient_ || !backendClient_->sessionReady()) return;
  cJSON* catalog=cJSON_Parse(message.c_str());
  const cJSON* offset=cJSON_GetObjectItemCaseSensitive(catalog,"offset");
  const bool match=cJSON_IsNumber(offset) && fire_app_updates::catalogReply(backendClient_->connectionEpoch(),backendCatalogRequestEpoch_,
      offset->valueint,backendCatalogNextOffset_,backendCatalogRequest_.c_str(),aiJobText(catalog,"request_event_id").c_str());
  const cJSON* apps=cJSON_GetObjectItemCaseSensitive(catalog,"apps");
  if (!match || !cJSON_IsArray(apps) || cJSON_GetArraySize(apps)>4) {cJSON_Delete(catalog);return;}
  const cJSON* nextValue=cJSON_GetObjectItemCaseSensitive(catalog,"next_offset");
  const bool completed=cJSON_IsNull(nextValue);
  const int next=cJSON_IsNumber(nextValue)?nextValue->valueint:-1;
  for (int row=0;row<cJSON_GetArraySize(apps);++row) {
    const cJSON* object=cJSON_GetArrayItem(apps,row);
    if (!cJSON_IsObject(object)) continue;
    const String appId=aiJobText(object,"app_id");if(!appId.length()) continue;
    int8_t existing=-1;
    for (uint8_t i=0;i<backendAppCount_;++i) if (backendApps_[i].appId==appId) {existing=i;break;}
    if (existing<0 && backendAppCount_>=kMaxBackendApps) {backendCatalogOverflow_=true;continue;}
    const uint8_t index=existing>=0?static_cast<uint8_t>(existing):backendAppCount_++;
    backendCatalogSeen_|=uint32_t(1)<<index;
    BackendAppInfo& item=backendApps_[index];
    item.appId=appId;item.projectId=aiJobText(object,"project_id");item.name=aiJobText(object,"name");
    item.latestPackageId=aiJobText(object,"latest_package_id");item.latestVersion=aiJobText(object,"latest_version");
    const cJSON* count=cJSON_GetObjectItemCaseSensitive(object,"version_count");
    item.versionCount=cJSON_IsNumber(count)?constrain(count->valueint,0,255):0;
    item.downloadable=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(object,"downloadable"));
    item.canDelete=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(object,"can_delete_from_device"));
    item.deleteReason=aiJobText(object,"download_block_reason");
    if(!item.deleteReason.length()) item.deleteReason=aiJobText(object,"device_delete_block_reason");
  }
  cJSON_Delete(catalog);
  rebuildAppManagerItems(); // existing app-ID selection preservation
  if (!completed) {
    if (next>backendCatalogNextOffset_ && next<kMaxBackendApps && requestBackendCatalogPage(next)) return;
    failBackendCatalog();return;
  }
  // Only a fully correlated successful batch may remove absent/deleted rows.
  uint8_t write=0;
  for (uint8_t i=0;i<backendAppCount_;++i) if (fire_app_updates::seen(backendCatalogSeen_,i)) {
    if(write!=i) backendApps_[write]=backendApps_[i];
    ++write;
  }
  for (uint8_t i=write;i<backendAppCount_;++i) backendApps_[i]=BackendAppInfo();
  backendAppCount_=write;backendCatalogLoading_=false;backendCatalogRequested_=true;
  backendCatalogFailures_=0;backendCatalogRequest_=String();
  backendCatalogEpoch_=backendClient_->connectionEpoch();backendCatalogAt_=millis();
  if (backendCatalogDirty_ || (backendCatalogOverflow_ && backendAppCount_<kMaxBackendApps)) backendCatalogRequested_=false;
  rebuildAppManagerItems();
  backendCatalogStatus_="Backend apps: "+String(backendAppCount_);
  if(screen_==Screen::AppsSettings && !managerTargetValid_ && downloadPhase_!=1 && downloadPhase_!=2) managerStatus_=backendCatalogStatus_;
  redrawRequested_=true;
}

void FireOS::parseBackendAppVersions(const String& message) {
  if(!appManagerVersionsWaiting_ || screen_!=Screen::AppsSettings || !managerTargetCurrent() ||
      !backendClient_ || !backendClient_->sessionReady() || appManagerRequestEpoch_!=backendClient_->connectionEpoch() ||
      jsonStringField(message,"request_event_id")!=appManagerRequest_ ||
      jsonStringField(message,"project_id")!=managerTarget_.projectId) return;
  appManagerVersionsWaiting_=false;appManagerRequest_=String();
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
  managerTarget_=managerItems_[managerSelection_];managerTargetValid_=true;
  appManagerDeleteId_=appManagerDeleteName_=appManagerDeletePackageId_=appManagerDeleteProjectId_=appManagerDeleteAppId_=String();
  appManagerDeleteScope_=0;appManagerDeleteRequest_=String();
  const ManagerItem& item = managerTarget_;
  managerStatus_=String();
  auto add = [&](uint8_t code, const char* label) {
    if (appManagerActionCount_ >= 10) return;
    appManagerActionCodes_[appManagerActionCount_] = code;
    appManagerActionLabels_[appManagerActionCount_++] = label;
  };
  if (item.local) add(1, "Launch");
  if (item.local && item.kind==1 && item.localPackageId.length()) {
    add(7,"Improve app");add(8,"New app from this");add(9,"Test feedback");
  }
  if (item.kind==1 || item.backend) add(10,"Evolution");
  if (item.backend && item.packageId.length() > 0) add(2, "Download/update");
  if (item.local && item.kind==1) {
    bool suppressed=false;for(uint8_t i=0;i<luaAppCount_;++i) if(luaAppIds_[i]==item.appId && updatePrefsOwner_==backendDeviceId_) suppressed=luaUpdateSuppressed_[i];
    add(11,suppressed?"Spør om oppdatering: Av":"Spør om oppdatering: På");
  }
  if (item.local) add(3, "Delete local");
  if (item.backend && item.canDeleteBackend) add(4, "Delete backend");
  add(5, "Back");
  appManagerActionIndex_ = 0;
}

void FireOS::requestSelectedAppVersions() {
  if (!managerTargetCurrent() || !backendClient_ || !backendClient_->sessionReady() || !managerTarget_.backend) {
    managerStatus_="Backend er ikke tilkoblet";return;
  }
  appManagerVersionProjectId_=managerTarget_.projectId;appManagerVersionAppId_=managerTarget_.appId;
  appManagerVersionDialog_=true;appManagerVersionCount_=0;appManagerVersionSelection_=appManagerVersionOffset_=0;
  appManagerRequest_="ver-"+String(esp_random(),HEX)+"-"+String(esp_random(),HEX);
  appManagerRequestAt_=millis();appManagerRequestEpoch_=backendClient_->connectionEpoch();
  appManagerVersionsWaiting_=true;managerStatus_="Henter versjoner";redrawRequested_=true;
  if(!backendClient_->appVersions(managerTarget_.projectId,managerTarget_.appId,0,appManagerRequest_)) {
    appManagerVersionsWaiting_=false;appManagerRequest_=String();managerStatus_="Kunne ikke hente versjoner";
  }
}

bool FireOS::managerTargetCurrent() const {
  if(!managerTargetValid_) return false;
  for(uint8_t i=0;i<managerItemCount_;++i) {
    const ManagerItem& row=managerItems_[i];
    if(row.appId==managerTarget_.appId && row.localPath==managerTarget_.localPath &&
       row.localPackageId==managerTarget_.localPackageId && row.projectId==managerTarget_.projectId &&
       row.packageId==managerTarget_.packageId && row.kind==managerTarget_.kind) return true;
  }
  return false;
}
void FireOS::invalidateManagerTarget() {
  managerTargetValid_=false;appManagerActionMenu_=false;appManagerDeleteConfirm_=false;
  appManagerDeleteWaiting_=false;appManagerDeleteMode_=0;appManagerDevelopConfirm_=0;
  appManagerVersionDialog_=appManagerVersionsWaiting_=false;
  appManagerRequest_=appManagerDeleteRequest_=String();managerStatus_="Appvalget er endret. Velg app på nytt.";
  redrawRequested_=true;
}

bool FireOS::applyBackendDeleteResult(const cJSON* result) {
  if(!managerTargetValid_ || !backendClient_ || backendClient_->connectionEpoch()!=appManagerRequestEpoch_ ||
      aiJobText(result,"delete_id")!=appManagerDeleteId_ || aiJobText(result,"app_id")!=managerTarget_.appId ||
      aiJobText(result,"project_id")!=managerTarget_.projectId || aiJobText(result,"status")!="deleted") return false;
  const cJSON* count=cJSON_GetObjectItemCaseSensitive(result,"remaining_versions");
  if(cJSON_IsNumber(count) && count->valueint==0) for(uint8_t i=0;i<backendAppCount_;++i) if(backendApps_[i].appId==managerTarget_.appId) {
    for(uint8_t move=i+1;move<backendAppCount_;++move) backendApps_[move-1]=backendApps_[move];
    backendApps_[--backendAppCount_]=BackendAppInfo();break;
  }
  appManagerDeleteConfirm_=appManagerDeleteWaiting_=false;appManagerDeleteMode_=0;appManagerDeleteRequest_=String();
  managerTargetValid_=false;managerStatus_="Backend app deleted";rebuildAppManagerItems();
  backendCatalogLoading_=false;backendCatalogRequest_=String();invalidateBackendCatalog();redrawRequested_=true;return true;
}

void FireOS::sendAppInventory() {
  FireUiPhaseTimer timing("inventory_send");
  appInventoryPending_ = true;
  if (!backendClient_ || !backendClient_->sessionReady()) return;
  if (luaScanPending_ || luaScanPhase_ != LuaScanPhase::Idle ||
      (packageManager_ && packageManager_->busy())) return;
  if (!luaCacheValid_) { scanLuaApps(); return; }
  if (!luaCacheComplete_ || !sdReady_) {
    // complete=false suppresses missing inference, but PRESENT entries still
    // change backend state. Never serialize stale UI rows after a failed scan.
    appInventoryPending_ = !backendClient_->appInventory("[]", sdReady_, false);
    return;
  }
  String appsJson = "[";
  for (uint8_t index = 0; index < luaAppCount_; ++index) {
    if (index > 0) appsJson += ',';
    appsJson += "{\"app_id\":\"" + jsonEscapeField(luaAppNames_[index]);
    if (luaAppPackageIds_[index].length())
      appsJson += "\",\"package_id\":\"" + jsonEscapeField(luaAppPackageIds_[index]);
    appsJson += "\",\"version\":\"" + jsonEscapeField(luaAppVersions_[index]) +
                "\",\"checksum\":\"" + jsonEscapeField(luaAppChecksums_[index]) + "\"}";
  }
  appsJson += ']';
  if (appsJson.length() > 6144) {
    // Leave room for the event envelope in the backend client's 8 KiB frame.
    appInventoryPending_ = !backendClient_->appInventory("[]", sdReady_, false);
    return;
  }
  appInventoryPending_ = !backendClient_->appInventory(appsJson, sdReady_, luaCacheComplete_ && sdReady_);
}

bool FireOS::deleteExternalApp(const String& path) {
  if (path.length() == 0 || (!sdReady_ && !initSdCard())) return false;
  invalidateLuaApps();
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
  invalidateLuaApps();
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
  (void)rebootAfterInstall; (void)makeBootApp;
  // Legacy native-app images must not bypass signed OS OTA or replace a
  // rollback slot. AI/local apps use the restricted Lua package runtime.
  if (!path.startsWith("/firmware/fire-")) {
    externalAppMessage_ = "Bruk Lua-apper eller signert firmware";
    return false;
  }
  return installFirmwareFile(path);
}

bool FireOS::launchSelectedBootApp() {
  if (selectedBootAppPath_.length() == 0) return false;
  if (!sdReady_ && !initSdCard()) return false;
  if (selectedBootAppPath_.endsWith("/main.lua")) {
    // Boot launch reads/validates its own manifest; it does not need an index.
    return startLuaApp(selectedBootAppPath_, sdBaseName(selectedBootAppPath_));
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

uint32_t FireOS::backendCommandNow() const {
  if(backendServerTime_>0) return backendServerTime_+(millis()-backendServerSeenAt_)/1000UL;
  const time_t now=time(nullptr);
  return now>=1577836800?static_cast<uint32_t>(now):0;
}
bool FireOS::backendCommandUnexpired(uint32_t expiresAt) const {
  const uint32_t now=backendCommandNow();return now && expiresAt>now;
}

bool FireOS::resolveLuaPackage(const String& packageId,const String& archiveHash,
                               const String& sourceHash,String& path) {
  path=String();luaAppError_=String();
  const auto candidate=[&](const String& source,bool legacy) {
    if(!source.startsWith("/apps/") || !source.endsWith("/main.lua")) return false;
    const String folder=source.substring(0,source.lastIndexOf('/'));
    const String app=sdBaseName(folder);
    if(!fire_lua_install::id(app.c_str())) return false;
    fire_lua_install::Identity identity;
    const auto status=fire_lua_install::read(SD,(folder+"/"+fire_lua_install::kFilename).c_str(),identity);
    if(status==fire_lua_install::Read::Valid) {
      if(!identity.matches(app.c_str(),packageId.c_str(),archiveHash.c_str(),sourceHash.c_str())) return false;
      path=source;return true;
    }
    if(status==fire_lua_install::Read::Invalid) {luaAppError_="metadata_error";return false;}
    if(!legacy) return false;
    // Older installations alone may use the retained NVS index. The incoming
    // source digest is still checked against actual bytes in startLuaApp.
    const String saved=preferences.getString(compactPreferenceKey("lh_",packageId).c_str(),"");
    if(!validSha256Hex(saved) || !saved.equalsIgnoreCase(archiveHash)) {luaAppError_="archive_mismatch";return false;}
    path=source;return true;
  };
  // The completed worker path covers an immediate RUN before incremental scan
  // publishes; current cache covers reconnect/reboot without any NVS write.
  if(packageManager_ && !packageManager_->busy() && candidate(packageManager_->installedPath(),false)) return true;
  if(luaCacheValid_ && luaCacheComplete_ && !luaScanPending_) {
    for(uint8_t i=0;i<luaAppCount_;++i)
      if(luaAppPackageIds_[i]==packageId && luaAppChecksums_[i]==sourceHash && candidate(luaAppPaths_[i],false)) return true;
  }
  return candidate(preferences.getString(compactPreferenceKey("lp_",packageId).c_str(),""),true);
}


bool FireOS::rollbackLuaPackage(const String& packageId,const String& archiveHash,const String& sourceHash) {
  if(!fire_lua_install::id(packageId.c_str()) || !fire_lua_install::hash(archiveHash.c_str()) ||
     !fire_lua_install::hash(sourceHash.c_str()) || (packageManager_ && packageManager_->busy())) return false;
  const auto filesMatch=[&](const String& folder,const String& app) {
    File manifest=SD.open(folder+"/manifest.json",FILE_READ);
    if(!manifest || manifest.isDirectory() || !manifest.size() || manifest.size()>8192) {manifest.close();return false;}
    String body;const size_t size=manifest.size();bool ok=body.reserve(size);uint8_t block[256];
    while(ok && body.length()<size) {
      const size_t got=manifest.read(block,min(sizeof(block),size-body.length()));
      ok=got && body.concat(reinterpret_cast<const char*>(block),got);
    }
    manifest.close();
    if(!ok || body.length()!=size || jsonStringField(body,"id")!=app ||
       !jsonStringField(body,"checksum").equalsIgnoreCase(sourceHash)) return false;
    const String api=jsonStringField(body,"api_version"),contract=jsonStringField(body,"api_contract");
    if(!FireLuaRuntime::supportsManifestApi(api.c_str(),api.length(),contract.c_str(),contract.length())) return false;
    File source=SD.open(folder+"/main.lua",FILE_READ);
    const bool bounded=source && !source.isDirectory() && source.size()>0 && source.size()<=FireLuaRuntime::kMaxSourceBytes;
    source.close();return bounded && sha256File(folder+"/main.lua")==sourceHash;
  };
  const String legacy=preferences.getString(compactPreferenceKey("lp_",packageId).c_str(),"");
  const String legacyArchive=preferences.getString(compactPreferenceKey("lh_",packageId).c_str(),"");
  bool attempted=false;
  const auto candidate=[&](const String& source) {
    if(!source.startsWith("/apps/") || !source.endsWith("/main.lua")) return false;
    const String folder=source.substring(0,source.lastIndexOf('/')),app=sdBaseName(folder);
    if(!fire_lua_install::id(app.c_str())) return false;
    const String previous="/apps/.previous-"+app;
    const String temporary="/apps/.rollback-"+app;
    for(unsigned version=0;version<2;++version) {
      const String selected=version?previous:folder;
      fire_lua_install::Identity identity;
      const auto status=fire_lua_install::read(SD,(selected+"/"+fire_lua_install::kFilename).c_str(),identity);
      const bool exact=status==fire_lua_install::Read::Valid &&
        identity.matches(app.c_str(),packageId.c_str(),archiveHash.c_str(),sourceHash.c_str());
      const bool old=status==fire_lua_install::Read::Absent && source==legacy &&
        validSha256Hex(legacyArchive) && legacyArchive.equalsIgnoreCase(archiveHash);
      if((!exact && !old) || !filesMatch(selected,app)) continue;
      attempted=true;
      if(luaAppActive_) stopLuaApp("rollback");
      if(old) {
        strlcpy(identity.app,app.c_str(),sizeof(identity.app));strlcpy(identity.package,packageId.c_str(),sizeof(identity.package));
        strlcpy(identity.archive,archiveHash.c_str(),sizeof(identity.archive));strlcpy(identity.source,sourceHash.c_str(),sizeof(identity.source));
        const String project=preferences.getString(compactPreferenceKey("pr_",packageId).c_str(),"");
        if(fire_lua_install::id(project.c_str(),true)) strlcpy(identity.project,project.c_str(),sizeof(identity.project));
        if(!fire_lua_install::writeVerified(SD,(selected+"/"+fire_lua_install::kFilename).c_str(),identity)) return false;
      }
      if(version && !fire_lua_install::swapPrevious(SD,folder,previous,temporary)) return false;
      fire_lua_install::Identity back;
      const bool verified=fire_lua_install::read(SD,(folder+"/"+fire_lua_install::kFilename).c_str(),back)==fire_lua_install::Read::Valid &&
        back==identity && filesMatch(folder,app);
      if(!verified && version) fire_lua_install::swapPrevious(SD,folder,previous,temporary);
      return verified;
    }
    return false;
  };
  if(candidate(legacy)) return true;
  if(attempted) return false;
  if(packageManager_ && candidate(packageManager_->installedPath())) return true;
  if(attempted) return false;
  for(uint8_t i=0;i<luaAppCount_;++i) {
    if(candidate(luaAppPaths_[i])) return true;
    if(attempted) return false;
  }
  return false;
}

uint64_t FireOS::buttonView() const {
  uint64_t details=0;
  switch(screen_) {
    case Screen::AiDeveloper:details=aiProjectPickerActive_ | (uint64_t(aiPickerPage_)<<1) | (uint64_t(backendSettingsUi_.page)<<4) | (uint64_t(aiWorkflowState_)<<8);break;
    case Screen::Evolution:details=uint64_t(evolutionUi_.page);break;
    case Screen::AppsSettings:details=appManagerActionMenu_ | (uint64_t(appManagerDeleteConfirm_)<<1) | (uint64_t(appManagerVersionDialog_)<<2) | (uint64_t(appManagerDevelopConfirm_)<<3);break;
    case Screen::FileExplorer:details=sdActionMenu_ | (uint64_t(sdDeleteConfirm_)<<1) | (uint64_t(sdNameEditor_)<<2) | (uint64_t(sdPreview_)<<3);break;
    case Screen::Firmware:details=firmwareInstallConfirm_ | (uint64_t(firmwareGithubDialog_)<<1) | (uint64_t(firmwareSdDialog_)<<2) | (uint64_t(firmwareGithubOverwriteConfirm_)<<3) | (uint64_t(firmwareGithubActionMenu_)<<4);break;
    case Screen::Wifi:details=wifiScanDialog_ | (uint64_t(wifiSavedDialog_)<<1);break;
    case Screen::Bluetooth:details=bluetoothScanDialog_ | (uint64_t(bluetoothSavedDialog_)<<1) | (uint64_t(bluetoothUnknownDialog_)<<2);break;
    case Screen::Boot:details=bootAppPicker_;break;
    case Screen::MainMenuSettings:details=luaMenuPicker_;break;
    case Screen::QuickSettings:details=quickEditing_;break;
    case Screen::DateTime:details=dateEditing_;break;
    case Screen::LuaApp:details=luaFeedbackConfirmation_ | (uint64_t(luaRepairConfirmPending_)<<1);break;
    default:break;
  }
  uint16_t row=0;
  switch(screen_) {
    case Screen::Main:row=mainIndex_;break;
    case Screen::Apps:row=externalAppSelection_;break;
    case Screen::Settings:row=settingsIndex_;break;
    case Screen::QuickSettings:row=quickIndex_;break;
    case Screen::AppsSettings:
      row=appManagerVersionDialog_?appManagerVersionSelection_:appManagerActionMenu_?appManagerActionIndex_:managerSelection_;
      if(appManagerActionMenu_ && appManagerActionIndex_<appManagerActionCount_) row|=uint16_t(appManagerActionCodes_[appManagerActionIndex_])<<8;
      break;
    case Screen::AiDeveloper:row=backendSettingsUi_.page!=FireBackendSettingsUi::None?backendSettingsUi_.selection:aiProjectPickerActive_?aiProjectSelection_:aiWorkflowState_;break;
    case Screen::Evolution:row=evolutionUi_.selection;break;
    case Screen::FileExplorer:row=sdActionMenu_?sdActionIndex_:sdSelection_;break;
    case Screen::Firmware:row=firmwareGithubActionMenu_?firmwareGithubActionIndex_:firmwareGithubDialog_?firmwareGithubSelection_:firmwareSelection_;break;
    case Screen::Wifi:row=wifiScanDialog_?wifiScanSelection_:wifiSavedDialog_?wifiSavedSelection_:wifiIndex_;break;
    case Screen::Bluetooth:row=bluetoothScanDialog_?bluetoothScanSelection_:bluetoothSavedDialog_?bluetoothSavedSelection_:bluetoothIndex_;break;
    case Screen::Boot:row=bootAppPicker_?bootAppSelection_:detailIndex_;break;
    case Screen::MainMenuSettings:row=luaMenuPicker_?luaMenuSelection_:detailIndex_;break;
    case Screen::DateTime:row=dateField_;break;
    case Screen::Power:row=powerIndex_;break;
    case Screen::PowerActions:row=powerActionIndex_;break;
    case Screen::Help:row=helpPage_;break;
    case Screen::LuaApp:row=luaErrorAction_;break;
    default:row=detailIndex_;break;
  }
  if(appUpdateStage_)row=appUpdateSelection_;
  return uint64_t(screen_) | (details<<8) | (uint64_t(row)<<40) | (uint64_t(appUpdateStage_)<<60) | (uint64_t(buildNoticeActive_)<<63);
}
String FireOS::buttonViewIdentity() const {
  if(appUpdateStage_) return appUpdateCandidate_;
  if(buildNoticeActive_) return buildNoticeId_;
  if(screen_==Screen::Evolution && evolutionUi_.page==FireEvolutionUi::Proposal) return evolutionUi_.proposalId;
  if(screen_==Screen::AiDeveloper) {
    if(backendSettingsUi_.page==FireBackendSettingsUi::Proposal) return backendSettingsUi_.proposalId;
    if(!aiProjectPickerActive_ && aiWorkflowState_==3) return aiProposalId_;
  }
  if(screen_==Screen::AppsSettings) {
    const bool ownsTarget=appManagerActionMenu_ || appManagerDeleteConfirm_ || appManagerVersionDialog_ ||
      appManagerDevelopConfirm_ || appManagerVersionsWaiting_ || appManagerDeleteWaiting_;
    const ManagerItem* target=ownsTarget && managerTargetValid_?&managerTarget_:
      (managerSelection_<managerItemCount_?&managerItems_[managerSelection_]:nullptr);
    if(!target) return "back";
    String id=target->appId+"|"+target->projectId+"|"+target->localPath+"|"+target->localPackageId+"|"+target->packageId;
    if(appManagerVersionDialog_ && appManagerVersionSelection_<appManagerVersionCount_) id+="|"+appManagerVersionPackageIds_[appManagerVersionSelection_];
    if(appManagerDeleteConfirm_) id+="|"+appManagerDeleteId_;
    return id;
  }
  if(screen_==Screen::Apps && externalAppSelection_>=externalAppCount_ && externalAppSelection_<externalAppCount_+luaAppCount_)
    return luaAppIds_[externalAppSelection_-externalAppCount_]+"|"+luaAppPackageIds_[externalAppSelection_-externalAppCount_];
  if(screen_==Screen::Main && mainIndex_>=kSystemMainCount && mainIndex_-kSystemMainCount<luaAppCount_)
    return luaAppIds_[mainIndex_-kSystemMainCount]+"|"+luaAppPackageIds_[mainIndex_-kSystemMainCount];
  if(screen_==Screen::AiDeveloper && aiProjectPickerActive_ && aiPickerPage_==fire_ai_menu::Page::Jobs && aiProjectSelection_<buildJobCount_)
    return buildJobIds_[aiProjectSelection_]+"|"+buildJobRepairIds_[aiProjectSelection_];
  if(screen_==Screen::AiDeveloper && aiProjectPickerActive_ && (aiPickerPage_==fire_ai_menu::Page::Job || aiPickerPage_==fire_ai_menu::Page::Work))
    return aiJobBuild_+"|"+aiJobRepair_;
  if(screen_==Screen::LuaApp && luaFeedbackConfirmation_) return luaDevelopContext_;
  return String();
}
void FireOS::publishButtonView() {
  const uint64_t view=buttonView();const String identity=buttonViewIdentity();
  if(view!=inputShownView_ || identity!=inputShownIdentity_) {
    inputShownView_=view;inputShownIdentity_=identity;if(++inputContext_==0) ++inputContext_;
  }
  fire_button_capture::shown(inputContext_);
  presentLocalQa();
  if(inputPresentationPending_) {
    maxInputPresentUs_=max(maxInputPresentUs_,static_cast<uint32_t>(esp_timer_get_time())-inputPendingAtUs_);
    inputPresentationPending_=false;
  }
}
void FireOS::beginButtonCapture() {
  beginLocalQa();
  const bool ready=fire_button_capture::begin();
  fire_button_capture::sleeping(displayPowerState_!=0);fire_button_capture::discard();
  inputSyncUs_=static_cast<uint32_t>(esp_timer_get_time());const uint8_t mask=fire_button_capture::mask();
  for(uint8_t i=0;i<kButtonCount;++i) buttons_[i].resync(mask&(1u<<i),inputSyncUs_);
  Serial.printf("FIRE input edge_capture=%u\n",ready?1:0);
}
void FireOS::pollButtons() {
  const auto resync=[&]() {
    // Never turn an incomplete gesture into an irreversible B action.
    fire_button_capture::discard();inputSyncUs_=static_cast<uint32_t>(esp_timer_get_time());
    const uint8_t mask=fire_button_capture::mask();
    for(uint8_t i=0;i<kButtonCount;++i) buttons_[i].resync(mask&(1u<<i),inputSyncUs_);
  };
  if (fire_button_capture::takeOverflow()) {resync();return;}
  const auto advance=[&](uint32_t at) {
    for(uint8_t i=0;i<kButtonCount;++i) for(unsigned n=0;n<2;++n) {
      const auto event=buttons_[i].advance(at);if(event.kind==fire_buttons::Kind::None) break;
      if(event.kind==fire_buttons::Kind::Press) {lastActivity_=millis();continue;}
      if(event.kind==fire_buttons::Kind::Wake) {wakeDisplay();redrawRequested_=true;}
      else {
        if(i==1 && event.kind==fire_buttons::Kind::Click && !fire_buttons::visibleClick(event,inputContext_,buttonView(),inputShownView_,buttonViewIdentity()==inputShownIdentity_)) continue;
        if(event.kind==fire_buttons::Kind::Click) {
          const uint32_t now=static_cast<uint32_t>(esp_timer_get_time());
          maxInputDispatchUs_=max(maxInputDispatchUs_,now-event.at);
          if(!inputPresentationPending_ || uint32_t(now-event.at)>uint32_t(now-inputPendingAtUs_)) inputPendingAtUs_=event.at;
          inputPresentationPending_=true;
        }
        lastActivity_=millis();onButton(i,event.kind==fire_buttons::Kind::Hold);
      }
    }
  };
  fire_buttons::Edge edge;
  for(unsigned n=0;n<fire_buttons::Ring::capacity && fire_button_capture::pop(edge);++n) {
    if(fire_button_capture::takeOverflow()) {resync();return;}
    if(!fire_buttons::afterOrEqual(edge.at,inputSyncUs_)) continue;
    inputSyncUs_=edge.at;advance(edge.at);
    if(inputSyncUs_!=edge.at) return; // sleep/wake resynchronized during dispatch
    for(uint8_t i=0;i<kButtonCount;++i) buttons_[i].edge(edge.mask&(1u<<i),edge.at,edge.sleeping,edge.context);
  }
  const uint32_t now=static_cast<uint32_t>(esp_timer_get_time());
  if(!fire_button_capture::active()) {
    const uint8_t mask=fire_button_capture::mask();
    for(uint8_t i=0;i<kButtonCount;++i) buttons_[i].edge(mask&(1u<<i),now,displayPowerState_!=0,inputContext_);
  }
  if(!fire_button_capture::pending()) {inputSyncUs_=now;advance(now);}
}

void FireOS::onButton(uint8_t index, bool longPress) {
  redrawRequested_ = true;
  const bool conversationAudio = screen_ == Screen::AiDeveloper && index == 1;
  const bool debugAudio = screen_ == Screen::Debug && detailIndex_ == 4;
  if (!conversationAudio && !debugAudio && !aiAudioOutputActive_)
    playButtonSound(index, longPress);
  if(fire_app_updates::active(appUpdateStage_,screen_==Screen::QuickSettings) && !longPress) {handleAppUpdateButton(index);return;}
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
        home();
      } else {
        back();
      }
    }
    return;
  }

  if (luaDevelopJob_ && luaAppActive_) {
    auto* job=findLuaJob(luaDevelopJob_);
    if (luaFeedbackConfirmation_ && luaDevelopContext_.length()) {
      if (index==0) {if (job) cancelLuaDataJob(*job,"cancelled");}
      else if (!luaFeedbackAck_.length() && backendClient_) {
        const String action=index==1?String("confirm"):String("reject");
        const String event="obs-"+luaDevelopContext_+"-"+action;
        if (backendClient_->confirmObservation(luaDevelopContext_,action,event)) {
          luaFeedbackOutcome_=action;luaFeedbackAck_=event;luaFeedbackAt_=millis();
        }
      }
    } else if (index==0 && job) cancelLuaDataJob(*job,"cancelled");
    return;
  }
  if (buildNoticeActive_) {
    if (index == 1) {
      const String noticeBuild = buildNoticeId_;
      buildNoticeRunBuildId_=noticeBuild;buildNoticeRunPackageId_=buildNoticePackageId_;
      buildNoticePendingId_ = noticeBuild;
      buildNoticePendingAction_ = "open";
      buildNoticePendingEvent_ = "";
      buildNoticeLastSendAt_ = 0;
      buildNoticeActive_ = false;
      open(Screen::AiDeveloper);
      aiBuildId_ = noticeBuild;
      backgroundBuildActive_ = false;
      aiWorkflowState_ = 4;
      aiWorkflowText_ = "Åpner ferdig app";
    } else if (index == 2) {
      buildNoticePendingId_ = buildNoticeId_;
      buildNoticePendingAction_ = "dismiss";
      buildNoticePendingEvent_ = "";
      buildNoticeLastSendAt_ = 0;
      buildNoticeActive_ = false;
    }
    return;
  }

  if (screen_ == Screen::Home) { homeApp_.button(index); return; }
  if (screen_ == Screen::Evolution) {handleEvolutionButton(index);return;}

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
    if (!luaAppActive_ && luaAppError_.length() > 0) {
      handleLuaErrorButton(index);
      return;
    }
    const char* buttonName = index == 0 ? "A" : index == 1 ? "B" : "C";
    if (luaAppActive_ && luaRuntime_) {
      evolution_.button(index);
      const uint32_t serial=luaRuntime_->callbackSerial();
      const bool ok=luaRuntime_->button(buttonName,"pressed");
      if (luaRuntime_->callbackSerial()!=serial && luaRuntime_->lastPhase() && !strcmp(luaRuntime_->lastPhase(),"on_button"))
        evolution_.callback(2,luaRuntime_->lastCallbackUs(),heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),luaRuntime_->peakMemoryUsed());
      if (!ok) {const String error=luaRuntime_->lastError();stopLuaApp(error);}
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
        cancelConversationTurn("READY", false);
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
      selectMainItem(nextIndex);
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
      selectMainItem(nextIndex);
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
      } else if (mainIndex_ == 5) {
        open(Screen::Home);
      } else if (mainIndex_ >= kSystemMainCount) {
        const uint8_t appIndex = mainIndex_ - kSystemMainCount;
        if (appIndex < luaAppCount_)
          requestLuaAppOpen(luaAppPaths_[appIndex],luaAppDisplayNames_[appIndex],luaAppPackageIds_[appIndex]);
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
        detailIndex_ = 0;
        open(Screen::AiApi);
      } else if (settingsIndex_ == 15) {
        powerIndex_ = 0;
        powerEditing_ = false;
        open(Screen::Power);
      } else if (settingsIndex_ == 16) {
        home();
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
  // ordinary navigation. Home/Back use their own path, but
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
    externalAppMessage_ = "Scanning apps...";
    appScanPending_ = true;
  }
  if (screen == Screen::AppsSettings) {
    managerTargetValid_=false;appManagerVersionsWaiting_=false;appManagerRequest_=appManagerDeleteRequest_=String();
    appManagerDevelopConfirm_=0;
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
    backendCatalogRequested_ = false;
    backendCatalogLoading_ = false;backendCatalogRequest_=String();
    backendCatalogNextOffset_ = 0;
    externalAppCount_ = 0;
    externalAppMessage_ = "Scanning apps...";
    appScanPending_ = true;
  }
  if (screen == Screen::AiDeveloper) {
    aiProjectPickerActive_ = true;
    aiPickerPage_=fire_ai_menu::Page::Main;
    backendSettingsUi_.page=FireBackendSettingsUi::None;
    aiProjectSelection_ = 0;
    aiProjectOffset_ = 0;
    aiJobViewing_=aiJobOpenPending_=aiJobNeedsInstall_=false;
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
    aiProposalProjectId_=String();aiProposalJobId_=String();aiProposalAppName_=String();
    aiPackageId_ = "";
    aiReadyPackageId_=String();
    aiInstallId_ = "";
    aiAssistantText_ = "";
    aiWorkflowText_ = "";
    if (backgroundBuildsSupported_) requestBackgroundBuildJobs();
  }
  if (screen == Screen::AiApi) {
    wifiIndex_ = 0;
  }
  if (screen == Screen::MainMenuSettings) {luaMenuPicker_=false;luaMenuSelection_=luaMenuOffset_=0;detailIndex_=0;}
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
    firmwareGithubActionMenu_ = false;
    firmwareInstallFromGithub_ = false;
    firmwareMessage_ = "Velg GitHub eller SD-filer";
    firmwareScanPending_ = false;
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

void FireOS::selectMainItem(uint8_t nextIndex) {
  mainIndex_ = nextIndex;
  redrawRequested_ = true;
}

void FireOS::back() {
  if(appUpdateStage_) {if(appUpdateStage_==2) cancelAppDownload();appUpdateStage_=0;redrawRequested_=true;return;}
  if (screen_==Screen::AiDeveloper) {backAiDeveloper();return;}
  if (screen_==Screen::LuaApp && !luaAppActive_ && aiJobViewing_) {
    screen_=Screen::AiDeveloper;backAiDeveloper();return;
  }
  if (screen_ == Screen::Home) {
    if (!homeApp_.back()) home();
    redrawRequested_ = true;
    return;
  }
  if (screen_ == Screen::Main) return;
  if (screen_==Screen::AppsSettings) {invalidateManagerTarget();}
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
  aiJobViewing_=aiJobOpenPending_=false;
  if(appUpdateStage_) {appUpdateStage_=0;userRunAfterInstall_=String();}
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
}

void FireOS::openQuickSettings() {
  appUpdateStage_=0; // reserved long-B opens a usable overlay, never a hidden update modal

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
    const uint8_t itemCount = appCount + 2;
    if (index == 0) {
      bootAppSelection_ = (bootAppSelection_ + itemCount - 1) % itemCount;
    } else if (index == 2) {
      bootAppSelection_ = (bootAppSelection_ + 1) % itemCount;
    } else {
      if (bootAppSelection_ == appCount + 1) {
        bootAppPicker_ = false;
        return;
      }
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
  if (firmwareBusy()) {
    if (index == 0 && ota_.busy() && ota_.cancel()) firmwareMessage_ = "Avbryter installering";
    else firmwareMessage_ = "Firmwarearbeid pagar";
    return;
  }
  // Confirmation must precede the still-open SD/catalog lists.
  if (firmwareInstallConfirm_) {
    firmwareInstallConfirm_ = false;
    if (index == 1) {
      if (firmwareInstallFromGithub_) queueFirmwareAction(FirmwareAction::InstallGithub);
      else queueFirmwareAction(FirmwareAction::InstallSd);
    } else {
      firmwareMessage_ = "Installering avbrutt";
      if (firmwareInstallFromGithub_) firmwareGithubActionMenu_ = true;
      else firmwareSdDialog_ = true;
    }
    return;
  }
  if (firmwareGithubOverwriteConfirm_) {
    firmwareGithubOverwriteConfirm_ = false;
    if (index == 1) queueFirmwareAction(FirmwareAction::SaveSd, true);
    else { firmwareGithubActionMenu_ = true; firmwareMessage_ = "Lagring avbrutt"; }
    return;
  }
  if (firmwareGithubActionMenu_) {
    if (index != 1) firmwareGithubActionIndex_ = (firmwareGithubActionIndex_ + 3 + (index == 0 ? -1 : 1)) % 3;
    else if (firmwareGithubActionIndex_ == 0) {
      firmwareGithubActionMenu_ = false;
      firmwareInstallFromGithub_ = true; firmwareInstallConfirm_ = true;
      firmwareMessage_ = "Bekreft installering og omstart";
    } else if (firmwareGithubActionIndex_ == 1) {
      if (!sdReady_ && !initSdCard()) { firmwareMessage_ = "SD-kort er ikke tilgjengelig"; return; }
      firmwareGithubActionMenu_ = false; firmwareGithubOverwriteConfirm_ = true;
      firmwareMessage_ = "Lagre pa SD uten installering";
    } else { firmwareGithubActionMenu_ = false; firmwareGithubDialog_ = true; }
    return;
  }
  if (firmwareGithubDialog_) {
    const uint8_t remoteCount = githubFirmware_ ? githubFirmware_->entryCount() : 0;
    const uint8_t itemCount = remoteCount + 1;
    if (index != 1) firmwareGithubSelection_ = (firmwareGithubSelection_ + itemCount + (index == 0 ? -1 : 1)) % itemCount;
    else if (firmwareGithubSelection_ < remoteCount) {
      if (githubFirmware_->selection(firmwareGithubSelection_, firmwareGithubRelease_, firmwareGithubCatalog_)) {
        firmwareGithubDialog_ = false; firmwareGithubActionMenu_ = true; firmwareGithubActionIndex_ = 0;
      } else firmwareMessage_ = "Utgaven kunne ikke velges. Hent listen igjen";
    } else { firmwareGithubDialog_ = false; firmwareMessage_ = "GitHub-listen lukket"; }
    if (firmwareGithubSelection_ < firmwareGithubOffset_) firmwareGithubOffset_ = firmwareGithubSelection_;
    if (firmwareGithubSelection_ >= firmwareGithubOffset_ + 5) firmwareGithubOffset_ = firmwareGithubSelection_ - 4;
    return;
  }
  if (firmwareSdDialog_) {
    const uint8_t count = firmwareCount_ + 1;
    if (index != 1) firmwareSelection_ = (firmwareSelection_ + count + (index == 0 ? -1 : 1)) % count;
    else if (firmwareSelection_ < firmwareCount_) {
      firmwarePendingSdPath_ = firmwarePaths_[firmwareSelection_];
      firmwareSdDialog_ = false; firmwareInstallFromGithub_ = false; firmwareInstallConfirm_ = true;
      firmwareMessage_ = "Bekreft installering og omstart";
    } else { firmwareSdDialog_ = false; firmwareSelection_ = 1; firmwareOffset_ = 0; }
    if (firmwareSelection_ < firmwareOffset_) firmwareOffset_ = firmwareSelection_;
    if (firmwareSelection_ >= firmwareOffset_ + 5) firmwareOffset_ = firmwareSelection_ - 4;
    return;
  }
  if (index != 1) firmwareSelection_ = (firmwareSelection_ + 3 + (index == 0 ? -1 : 1)) % 3;
  else if (firmwareSelection_ == 0) {
    firmwareGithubDialog_ = true; firmwareGithubSelection_ = firmwareGithubOffset_ = 0;
    queueFirmwareAction(FirmwareAction::Manifest);
  } else if (firmwareSelection_ == 1) {
    firmwareMessage_ = "Leser SD-filer"; firmwareSelection_ = firmwareOffset_ = 0;
    firmwareSdDialog_ = true; firmwareScanPending_ = true;
  } else back();
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
  if((downloadPhase_==1 || downloadPhase_==2) && index==2) {cancelAppDownload();return;}
  if (!aiProjectPickerActive_ && index==1 && !aiVoiceTestMode_ && aiWorkflowState_>=2 && aiWorkflowState_<=5) {openAiWork();return;}
  if (aiProjectPickerActive_) {handleAiPicker(index);return;}
  if (index==0 && aiWorkflowState_==1) return;
  if (aiWorkflowState_==4 && !aiBuildId_.length()) {
    if (index==0) {home();return;}
    if (index==2) {cancelConversationTurn("Avbryter",false);return;}
  }
  if (index==2 && (aiWorkflowState_==0 || aiWorkflowState_==6 || (aiVoiceTestMode_ && !aiAudioCaptureActive_ && !aiVoiceTestPlaybackActive_))) {
    aiProjectPickerActive_=true;aiPickerPage_=fire_ai_menu::Page::Main;
    aiProjectSelection_=aiProjectOffset_=0;backendSettingsUi_.page=FireBackendSettingsUi::None;redrawRequested_=true;return;
  }
  if (aiBuildResumePending_ && index == 2 &&
      (aiWorkflowState_ == 2 || aiWorkflowState_ == 3)) {
    // Leave the preserved failure view without cancelling the backend job.
    back();
    return;
  }
  if (aiBuildResumePending_ && index == 1 && aiWorkflowState_ == 2) {
    aiWorkflowText_ = "VENTER PÅ RETRY-PLAN";
    redrawRequested_ = true;
    return;
  }
  if (index == 1) {
    if (aiWorkflowState_ == 0) {
      if (!aiVoiceTestMode_ && backendClient_ && backendClient_->sessionRejected()) {
        aiWorkflowText_="Tilkobling avvist";aiDeveloperMode_=0;return;
      }
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
  } else if (index == 0 && aiWorkflowState_ == 4 &&
             backgroundBuildsSupported_ && aiBuildId_.length() > 0) {
    if (backendClient_ && backendClient_->buildBackground(aiBuildId_)) {
      // Keep the last authoritative work status; this is only a view change.
      aiWorkflowText_ = "Bygger i bakgrunnen";
      goToBootApp();
    }
  } else if (index == 0 && aiWorkflowState_ == 3) {
    if (backendClient_ && backendClient_->connected() && aiProposalId_.length() > 0) {
      if (backendClient_->confirmBuild(aiProposalId_)) {
        aiBuildRetryPending_ = aiBuildResumePending_;
        aiBuildResumePending_ = false;
        aiBuildErrorStatus_ = "";
        aiBuildDiagnosticMessage_ = "";
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
  } else if (index == 2 && aiWorkflowState_ == 4 &&
             backgroundBuildsSupported_ && aiBuildId_.length() > 0) {
    if (backendClient_ && backendClient_->buildCancel(aiBuildId_)) {
      aiWorkflowText_ = "Avbryter bygging";
    }
  } else if (index == 2 &&
             (aiWorkflowState_ == 1 || aiWorkflowState_ == 2 ||
              aiWorkflowState_ == 3 || aiWorkflowState_ == 5)) {
    cancelConversationTurn("READY - PRESS B TO SPEAK", false);
    aiBuildProgress_ = 0;
    aiWorkflowStarted_ = millis();
  } else if (index == 0 && aiWorkflowState_ == 5) {
    if (packageManager_ && packageManager_->busy()) {aiWorkflowText_="Venter på installkvittering";return;}
    if (backendClient_ && backendClient_->sessionReady() && aiReadyPackageId_.length() > 0) {
      if (aiJobNeedsInstall_) {
        if (requestAppDownload(aiProjectId_,aiReadyPackageId_,String(),true)) {
          aiWorkflowState_=4;
          aiWorkflowText_="Laster ned valgt app";
        } else aiWorkflowText_="Nedlasting kunne ikke startes";
        return;
      }
      if (backendClient_->confirmRun(aiReadyPackageId_)) {
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
    if (aiWorkflowState_==2) cancelConversationTurn("Klar",false);
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
  if (!localVoiceTest && backendClient_ && backendClient_->selectionPending()) {
    aiAudioError_=backendClient_->selectionUnclear()?"Valg uavklart. Velg app igjen":"Venter på appvalg";
    return false;
  }
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
  if (luaMicJobId_) {
    LuaHardwareJob* capture = findLuaJob(luaMicJobId_);
    if (capture) { capture->state = 3; capture->errorCode = "audio_preempted"; }
    releaseLuaMic();
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
    aiProposalProjectId_=String();aiProposalJobId_=String();aiProposalAppName_=String();
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
  aiWorkflowState_ = fireConversationState(aiWorkflowState_,aiProposalId_.length()>0?3:0);
  if(aiWorkflowState_<4) {
    aiDeveloperMode_ = aiProposalId_.length() > 0 ? 2 : 0;
    aiWorkflowText_ = aiProposalId_.length() > 0
                          ? "Klar til bygging"
                          : "Lydfeil – prøv igjen";
  }
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
      aiWorkflowText_ = "Henter AI-svar";
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
  aiWorkflowState_ = fireConversationState(aiWorkflowState_,0);
  if(aiWorkflowState_<3) aiWorkflowText_ = "Svar mottatt";
}

bool FireOS::startLuaApp(const String& path, const String& name,
                         const String& launchPackageId,const String& expectedSourceHash) {
  aiJobViewing_=aiJobOpenPending_=false;appUpdateStage_=0;
  luaSdkFrame_.invalidate();
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
  const String manifestName = jsonStringField(manifest, "name");
  const String manifestVersion = jsonStringField(manifest, "version");
  const String manifestApi = jsonStringField(manifest, "api_version");
  const String manifestContract = jsonStringField(manifest, "api_contract");
  const String manifestHash = jsonStringField(manifest, "checksum");
  const int manifestMemory =
      jsonIntField(manifest, "max_memory", FireLuaRuntime::kMaxMemoryBytes);
  const int manifestRuntime = jsonIntField(manifest, "max_runtime_ms", -1);
  fire_lua_install::Identity installIdentity;
  const auto identityStatus=fire_lua_install::read(SD,(appFolder+"/"+fire_lua_install::kFilename).c_str(),installIdentity);
  if(identityStatus==fire_lua_install::Read::Invalid ||
     (identityStatus==fire_lua_install::Read::Valid &&
      (manifestId!=installIdentity.app || !manifestHash.equalsIgnoreCase(installIdentity.source) ||
       (launchPackageId.length() && launchPackageId!=installIdentity.package)))) {
    luaAppError_="metadata_error";return false;
  }
  const bool appSdk = manifestApi == FireLuaRuntime::appSdkVersion();
  const bool hardwareApi = appSdk || manifestApi == FireLuaRuntime::hardwareApiVersion();
  if (manifestId != sdBaseName(appFolder) ||
      (manifestApi != "fire-lua-0.1" && !hardwareApi) ||
      (hardwareApi && manifestContract != (appSdk ? FireLuaRuntime::appSdkContract()
                                                 : FireLuaRuntime::hardwareApiContract())) ||
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
                        !(serviceMask & kLuaServiceSd))) ||
                      (serviceMask & kLuaServiceMic &&
                       (!(serviceMask & kLuaServiceJobs) || !(serviceMask & kLuaServiceSd))) ||
                      (serviceMask & kLuaServiceBluetooth && !(serviceMask & kLuaServiceJobs)))) {
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
  if(!luaRuntimeAiManifest(manifest,appSdk,serviceMask)) {
    luaAppError_="Runtime AI permission or contract invalid";return false;
  }
  if (!luaDataManifest(manifest,appSdk,serviceMask)) {
    luaAppError_="Data Engine permission or contract invalid";return false;
  }
  // A new verified source starts with its own API/permissions and no live jobs
  // from the previous app. An identical authorized active run is handled before
  // entering this loader, preserving its local measurement/game state.
  if(luaRuntimeReady_) stopLuaApp("os_navigation");
  if (!luaRuntimeReady_) {
    FireLuaRuntime::Host luaHost;
    luaHost.context = this;
    luaHost.appSdkUiSource = FireSdkData::kUiSource;
    luaHost.appSdkUiBytes = sizeof(FireSdkData::kUiSource)-1;
    luaHost.displayPaint = luaDisplayPaint;
    luaHost.displayClear = luaDisplayClear;
    luaHost.displayCircle = luaDisplayCircle;
    luaHost.displayRect = luaDisplayRect;
    luaHost.displayLine = luaDisplayLine;
    luaHost.displayText = luaDisplayText;
    luaHost.displayFillRect = luaDisplayFillRect;
    luaHost.displayFillCircle = luaDisplayFillCircle;
    luaHost.displayPixel = luaDisplayPixel;
    luaHost.displayGrid = luaDisplayGrid;
    luaHost.displayTextStyle = luaDisplayTextStyle;
    luaHost.displayMeasureText = luaDisplayMeasureText;
    luaHost.displayAsset = luaDisplayAsset;
    luaHost.displayRoundRect = luaDisplayRoundRect;
    luaHost.displayTriangle = luaDisplayTriangle;
    luaHost.displayPolyline = luaDisplayPolyline;
    luaHost.displayGradient = luaDisplayGradient;
    luaHost.displayArc = luaDisplayArc;
    luaHost.buttonPressed = luaButtonPressed;
    luaHost.rgbSet = luaRgbSet;
    luaHost.imuAccel = luaImuAccel;
    luaHost.imuBusy = [](void* context) {return static_cast<FireOS*>(context)->luaDataImu_.active();};
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
    luaHost.micLevel = luaMicLevelCallback;
    luaHost.micRecord = luaMicRecordCallback;
    luaHost.bluetoothRequest = luaBluetoothRequestCallback;
    luaHost.bluetoothAdvertiseRaw = luaBluetoothRawCallback;
    luaHost.bluetoothClose = luaBluetoothCloseCallback;
    luaHost.wifiStatus = luaWifiStatusCallback;
    luaHost.wifiScan = luaWifiScanCallback;
    luaHost.dataRequest = luaDataRequestCallback;
    luaHost.dataDevelop = luaDataDevelopCallback;
    luaHost.jobPoll = luaJobPollCallback;
    luaHost.jobResult = luaJobResultCallback;
    luaHost.jobClose = luaJobCloseCallback;
    luaHost.jobCancel = luaJobCancelCallback;
    luaHost.aiRequest = luaAiRequestCallback;
    luaRuntime_->setHardwareApi(hardwareApi);
    luaRuntime_->setAppSdk(appSdk);
    luaRuntime_->setDataEngine((serviceMask&kLuaServiceData)!=0);
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
  if(packageId.length()==0 && identityStatus==fire_lua_install::Read::Valid) packageId=installIdentity.package;
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
  if (readBytes != length || !sourceHash.equalsIgnoreCase(manifestHash) ||
      (expectedSourceHash.length() && sourceHash!=expectedSourceHash)) {
    free(buffer);
    luaAppError_ = "App source checksum mismatch";
    reportLocalLoadFailure("source_hash", luaAppError_);
    return false;
  }
  luaRuntime_->setMaxRuntimeMs(maxRuntimeMs);
  luaDataAllowed_=(serviceMask&kLuaServiceData)!=0;luaServiceMask_=serviceMask;
  if (luaDataAllowed_) {
    FireDataStore::Owner owner;
    owner.app=manifestId;owner.package=packageId;owner.source=sourceHash;
    owner.boot=backendClient_?backendClient_->bootId():String("local-boot");
    owner.instance=owner.boot+"-"+String(esp_random(),HEX);
    luaDataStore_.configure(SD,owner);
  }
  evolution_.select(SD,manifestId,packageId,sourceHash,backendClient_?backendClient_->bootId():String("local-boot"),millis());
  if (evolutionUi_.loaded && evolutionUi_.app==manifestId && evolutionUi_.acknowledgedConsent &&
      backendClient_ && backendClient_->sessionReady() && !evolutionUi_.request.length() && millis()-evolutionUi_.consentAt<15000)
    evolution_.consent(manifestId,true,millis());
  evolutionUi_.runtimeApp=String();evolutionUi_.runtimeRequest=String();
  const bool loaded = readBytes == length && luaRuntime_->loadSource(buffer, length);
  if (evolution_.consented() && (loaded || (luaRuntime_->lastPhase() && !strcmp(luaRuntime_->lastPhase(),"init"))))
    evolution_.callback(0,luaRuntime_->lastCallbackUs(),heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),luaRuntime_->peakMemoryUsed());
  free(buffer);
  if (!loaded) {
    releaseLuaHardware();evolution_.finish(millis());
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
  luaAppName_ = manifestName.length() > 0
                    ? manifestName
                    : (name.length() > 0 ? name : sdBaseName(path));
  luaAppId_ = manifestId;
  luaAppVersion_ = manifestVersion;
  luaSourceHash_ = sourceHash;
  luaPackageId_ = packageId;
  luaMaxRuntimeMs_ = maxRuntimeMs;
  luaAppError_ = "";
  luaRgbDirty_ = false;
  luaRgbLastFlushAt_ = millis();
  luaAppActive_ = true;
  luaRunId_ = "";
  luaRuntimeAiAllowed_=(serviceMask&kLuaServiceAi)!=0;
  if((luaRuntimeAiAllowed_ || luaDataAllowed_) && packageId.length()) {
    luaAiBindPackageId_=packageId;luaAiBindAt_=millis();luaAiBindSent_=false;
  }
  luaHealthySent_ = false;
  luaLastFrameAt_ = millis();
  previousScreen_ = screen_;
  screen_ = Screen::LuaApp;
  return true;
}

void FireOS::stopLuaApp(const String& reason) {
  luaSdkFrame_.invalidate();
  const String stoppedRunId = luaRunId_;
  const String stoppedAppId = luaAppId_;
  const String stoppedAppName = luaAppName_;
  const String stoppedAppVersion = luaAppVersion_;
  const String stoppedSourceHash = luaSourceHash_;
  const String stoppedPackageId = luaPackageId_.length() > 0
                                      ? luaPackageId_
                                      : aiPackageId_;
  const bool userExit = reason == "back" || reason == "home" ||
                        reason == "user_exit";
  const bool requestedStop = reason == "remote_stop" || reason == "rollback";
  const bool osNavigation = reason == "os_navigation";
  const char* diagnosticPhase = "update";
  if (reason == "runtime_limit" || userExit) {
    diagnosticPhase = "stop";
  } else if (luaRuntime_ && luaRuntime_->lastPhase()) {
    diagnosticPhase = luaRuntime_->lastPhase();
  }
  const String stoppedDiagnostics = luaDiagnosticsJson(diagnosticPhase);
  for (LuaHardwareJob& job:luaJobs_) noteEvolutionJob(job);
  evolution_.finish(millis());
  const bool failedRun = reason.length() > 0 && !userExit && !requestedStop &&
                         !osNavigation;
  if (luaAppActive_ && reason.length() > 0) {
    Serial.printf("Lua app stopped: %s\n", reason.c_str());
  }
  releaseLuaHardware();
  if (stoppedRunId.length() == 0 && stoppedAppId.length() > 0 &&
      stoppedPackageId.length() > 0 && reason.length() > 0 && !userExit &&
      !requestedStop && !osNavigation) {
    const String errorCode = reason == "runtime_limit" ? "runtime_limit"
                                                         : "runtime_error";
    queueLuaDiagnostic(stoppedAppId, stoppedPackageId, errorCode, reason,
                       stoppedDiagnostics);
  }
  luaAppActive_ = false;
  if (luaRuntime_) luaRuntime_->stop();
  luaRuntimeReady_ = false;
  if (failedRun && stoppedAppId.length() > 0) {
    luaErrorAppId_ = stoppedAppId;
    luaErrorAppName_ = stoppedAppName;
    luaErrorAppVersion_ = stoppedAppVersion;
    luaErrorPackageId_ = stoppedPackageId;
    luaErrorSourceHash_ = stoppedSourceHash;
    luaErrorRunId_ = stoppedRunId;
    luaErrorCode_ = reason == "runtime_limit" ? "runtime_limit"
                                               : "runtime_error";
    luaErrorDiagnostics_ = stoppedDiagnostics;
    luaAppError_ = reason;
    luaErrorAction_ = 0;
    luaRepairRequested_ = false;
    luaRepairPrepareSent_ = false;
    luaRepairBuildConfirmed_ = false;
    luaRepairConfirmPending_ = false;
    userRunAfterInstall_=String();
    luaRepairStatus_ = "Ready to repair";
    luaRepairPhase_ = "idle";
    luaRepairMessage_ = "Press B to fix this app";
    luaRepairProgress_ = 0;
    writeLuaErrorSnapshot(luaErrorCode_, luaAppError_, stoppedDiagnostics);
  }
  for (auto& pixel : luaRgbValues_)
    pixel[0] = pixel[1] = pixel[2] = 0;
  luaRgbDirty_ = false;
  luaRgbLastFlushAt_ = millis();
#ifdef FIRE_OS_BLE
  writeFireRgbRaw(0, 0, 0, 0);
#else
  M5.Led.setAllColor(0, 0, 0);
  M5.Led.display();
#endif
  luaRunId_ = "";
  luaAppId_ = "";
  luaAppVersion_ = "";
  luaSourceHash_ = "";
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
    else if (reason.length() > 0 && !requestedStop && !osNavigation)
      backendClient_->appFailed(stoppedRunId, stoppedPackageId, "runtime_error",
                                reason, stoppedDiagnostics);
  }
  if (reason.length() > 0 && reason != "back" && reason != "home" &&
      !osNavigation) {
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

void FireOS::flushLuaRgb() {
  if (!luaRgbDirty_ || millis() - luaRgbLastFlushAt_ < 20) return;
  luaRgbLastFlushAt_ = millis();
#ifdef FIRE_OS_BLE
  writeFireRgbArray(luaRgbValues_, 180);
#else
  M5.Led.setBrightness(180);
  M5.Led.setAllColor(luaRgbValues_[0][0], luaRgbValues_[0][1],
                     luaRgbValues_[0][2]);
  M5.Led.display();
#endif
  luaRgbDirty_ = false;
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

void FireOS::writeLuaErrorSnapshot(const String& errorCode,
                                   const String& message,
                                   const String& diagnostics) {
  if (!sdReady_ && !initSdCard()) return;
  if (!SD.exists("/logs") && !SD.mkdir("/logs")) return;
  if (!SD.exists("/logs/ai-developer") &&
      !SD.mkdir("/logs/ai-developer"))
    return;

  static uint8_t slot = 0;
  const String path = "/logs/ai-developer/error-" + String(slot++ % 8) + ".json";
  const String temporary = path + ".tmp";
  String body = "{\"schema_version\":1,\"error_id\":\"error-" +
                String(millis(), HEX) + "-" + String(esp_random(), HEX) +
                "\",\"boot_id\":\"" +
                jsonEscapeField(backendClient_ ? backendClient_->bootId()
                                                : String("boot-local")) +
                "\",\"uptime_ms\":" + String(millis()) +
                ",\"max_loop_us\":" + String(maxLoopUs_) +
                ",\"max_loop_gap_us\":" + String(maxLoopGapUs_) +
                ",\"min_internal_heap\":" + String(heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)) +
                ",\"largest_internal_block\":" + String(heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)) +
                ",\"max_callback_us\":" + String(luaRuntime_ ? luaRuntime_->maxCallbackUs() : 0) +
                ",\"instructions\":" + String(luaRuntime_ ? luaRuntime_->instructionCount() : 0) +
                ",\"app_id\":\"" + jsonEscapeField(luaErrorAppId_) +
                "\",\"app_version\":\"" +
                jsonEscapeField(luaErrorAppVersion_) +
                "\",\"package_id\":\"" +
                jsonEscapeField(luaErrorPackageId_) + "\",\"sha256\":\"" +
                jsonEscapeField(luaErrorSourceHash_) + "\",\"run_id\":\"" +
                jsonEscapeField(luaErrorRunId_) + "\",\"error_code\":\"" +
                jsonEscapeField(errorCode) + "\",\"message\":\"" +
                jsonEscapeField(message.substring(0, 240)) +
                "\",\"diagnostics\":" + diagnostics + "}";
  if (body.length() > 4096) body = body.substring(0, 4093) + "...}";
  File file = SD.open(temporary, FILE_WRITE);
  if (!file) return;
  file.print(body);
  file.close();
  if (SD.exists(path)) SD.remove(path);
  SD.rename(temporary, path);
}

void FireOS::requestLuaRepair() {
  if (luaErrorAppId_.length() == 0) {
    luaRepairMessage_ = "App identity unavailable";
    luaRepairStatus_ = "Unavailable";
    return;
  }
  if (luaRepairStatus_ == "awaiting_confirmation" ||
      luaRepairStatus_ == "preparing" ||
      luaRepairStatus_ == "queued" || luaRepairStatus_ == "building" ||
      luaRepairStatus_ == "testing" || luaRepairStatus_ == "ready" ||
      luaRepairStatus_ == "downloading" || luaRepairStatus_ == "starting" ||
      luaRepairStatus_ == "running") {
    return;
  }
  luaRepairAppId_=luaErrorAppId_;luaRepairAppName_=luaErrorAppName_;
  luaRepairId_ = "";
  luaRepairProposalId_ = "";
  luaRepairProjectId_ = "";
  luaRepairReadyPackageId_ = "";
  luaRepairReadyVersion_ = "";
  luaRepairStatus_ = "Waiting for backend";
  luaRepairPhase_ = "preparing";
  luaRepairMessage_ = "Preparing repair...";
  luaRepairProgress_ = 0;
  luaRepairRequested_ = true;
  luaRepairPrepareSent_ = false;
  luaRepairBuildConfirmed_ = false;
  luaRepairConfirmPending_ = false;
  luaRepairStatusQueryPending_ = false;
  luaErrorAction_ = 0;
}

void FireOS::requestLuaRepairStatus() {
  if (!backendClient_ || !backendClient_->sessionReady() ||
      luaRepairId_.length() == 0)
    return;
  if (backendClient_->appRepairStatus(luaRepairId_, luaRepairAppId_))
    luaRepairStatusQueryPending_ = false;
}

void FireOS::serviceLuaRepair() {
  if (!luaRepairRequested_ || !backendClient_ ||
      !backendClient_->sessionReady())
    return;
  const uint32_t now = millis();
  if (!luaRepairPrepareSent_ && now - luaRepairLastAttemptAt_ >= 1000) {
    luaRepairLastAttemptAt_ = now;
    if (backendClient_->appRepairPrepare(
            luaErrorAppId_, luaErrorPackageId_, luaErrorAppVersion_,
            luaErrorSourceHash_, luaErrorCode_, luaAppError_,
            luaErrorDiagnostics_, luaErrorRunId_)) {
      luaRepairPrepareSent_ = true;
      luaRepairStatus_ = "preparing";
      luaRepairMessage_ = "Forbereder reparasjon";
    } else {
      luaRepairMessage_ = "Backend unavailable - retrying";
    }
  }
}

void FireOS::cancelLuaRepair() {
  if ((downloadPhase_==1 || downloadPhase_==2) && downloadPackage_==luaRepairReadyPackageId_) {
    cancelAppDownload();luaRepairStatus_="ready";luaRepairPhase_="ready";return;
  }
  // Revoke explicit RUN intent before any callback, close or asynchronous cleanup.
  if (userRunAfterInstall_==luaRepairReadyPackageId_) userRunAfterInstall_=String();
  if (!repairCancelSupported_) {
    luaRepairMessage_ = "Cancel not supported";
    return;
  }
  if (luaRepairId_.length() == 0) {
    luaRepairRequested_ = false;
    luaRepairPrepareSent_ = false;
    luaRepairBuildConfirmed_ = false;
    luaRepairConfirmPending_ = false;
    luaRepairCancelPending_ = false;
    luaRepairStatus_ = "cancelled";
    luaRepairPhase_ = "cancelled";
    luaRepairMessage_ = "Byggingen ble avbrutt";
    goToBootApp();
    return;
  }
  luaRepairCancelPending_ = true;
  luaRepairMessage_ = "Avbryter bygging";
  luaRepairStatus_ = "cancelling";
  luaRepairPhase_ = "cancelling";
  goToBootApp();
}

void FireOS::handleLuaRepairStatus(const String& message) {
  const String incomingRepair = jsonStringField(message, "repair_id");
  const String incomingApp = jsonStringField(message, "app_id");
  if ((luaRepairId_.length() > 0 && incomingRepair.length() > 0 &&
       incomingRepair != luaRepairId_) ||
      (incomingApp.length() > 0 && luaRepairAppId_.length() > 0 && incomingApp != luaRepairAppId_) ||
      (luaRepairId_.length()==0 && luaRepairRequested_ && incomingApp.length()>0 && incomingApp!=luaErrorAppId_))
    return;
  const bool opened=aiJobViewing_ && aiJobOpenPending_ && incomingRepair==aiJobRepair_;
  if (opened) {luaErrorAppId_=incomingApp;aiJobOpenPending_=false;}
  if (incomingApp.length()) luaRepairAppId_=incomingApp;
  const String incomingName=jsonStringField(message,"app_name");
  if (incomingName.length()) luaRepairAppName_=incomingName;
  if (opened) {luaErrorAppName_=luaRepairAppName_;luaAppError_="Reparasjon av "+luaRepairAppName_;}
  if (aiRepairResumePending_ && luaRepairAppId_.length()) {
    luaErrorAppId_=luaRepairAppId_;luaErrorAppName_=aiRepairResumeName();
    luaAppError_="Reparasjon av "+luaErrorAppName_;aiRepairResumePending_=false;
  }
  const bool wasReady=luaRepairStatus_=="ready" && incomingRepair==luaRepairId_ &&
      jsonStringField(message,"package_id")==luaRepairReadyPackageId_;
  if (incomingRepair.length() > 0) luaRepairId_ = incomingRepair;
  const String incomingProject = jsonStringField(message, "project_id");
  const String incomingProposal = jsonStringField(message, "proposal_id");
  if (incomingProject.length() > 0) luaRepairProjectId_ = incomingProject;
  if (incomingProposal.length() > 0) luaRepairProposalId_ = incomingProposal;
  const String incomingPackage = jsonStringField(message, "package_id");
  if (incomingPackage.length() > 0) luaRepairReadyPackageId_ = incomingPackage;
  const String incomingVersion = jsonStringField(message, "version");
  if (incomingVersion.length() > 0) luaRepairReadyVersion_ = incomingVersion;
  luaRepairStatus_ = jsonStringField(message, "status");
  luaRepairPhase_ = jsonStringField(message, "phase");
  luaRepairMessage_ = jsonStringField(message, "display_text");
  if(!luaRepairMessage_.length()) luaRepairMessage_=compactStatusText(jsonStringField(message,"message"));
  luaRepairProgress_ = static_cast<uint8_t>(
      constrain(jsonIntField(message, "progress",luaRepairProgress_), 0, 100));
  workCompletedAt_=fire_ai_menu::completionStamp(millis(),workCompletedAt_,wasReady,
      luaRepairStatus_.c_str(),luaRepairPhase_.c_str(),luaRepairReadyPackageId_.c_str());
  luaRepairPrepareSent_ = true;
  if (luaRepairId_.length() > 0) {
    preferences.putString("repair_id", luaRepairId_);
    preferences.putString("repair_project", luaRepairProjectId_);
    preferences.putString("repair_proposal", luaRepairProposalId_);
    preferences.putString("repair_package", luaRepairReadyPackageId_);
    preferences.putString("repair_version", luaRepairReadyVersion_);
    preferences.putString("repair_status", luaRepairStatus_);
    preferences.putString("repair_phase", luaRepairPhase_);
    preferences.putString("repair_message", luaRepairMessage_.substring(0, 240));
    preferences.putUChar("repair_progress", luaRepairProgress_);
  }

  const String repairBuild=jsonStringField(message,"build_id");
  if (fire_ai_menu::stopsTrackedWork(aiBuildId_.c_str(),repairBuild.c_str(),luaRepairStatus_.c_str(),luaRepairPhase_.c_str()))
    backgroundBuildActive_=false;
  const bool repairQueued = luaRepairStatus_ == "queued" ||
                            luaRepairStatus_ == "building" ||
                            luaRepairStatus_ == "testing";
  if (repairQueued) {
    luaRepairConfirmPending_ = false;
    luaRepairBuildConfirmed_ = true;
  } else if (luaRepairStatus_ == "awaiting_confirmation" &&
             luaRepairProposalId_.length() > 0 && fire_ai_menu::autoConfirmRepair(luaRepairRequested_,aiJobViewing_) &&
             backendClient_ && backendClient_->sessionReady() &&
             (!luaRepairConfirmPending_ ||
              millis() - luaRepairConfirmLastAttemptAt_ >= 3000)) {
    if (backendClient_->confirmBuild(luaRepairProposalId_, luaRepairId_)) {
      luaRepairConfirmPending_ = true;
      luaRepairConfirmLastAttemptAt_ = millis();
      luaRepairMessage_ = "Bekrefter reparasjon";
    }
  } else if (luaRepairStatus_ == "ready" &&
             luaRepairReadyPackageId_.length() > 0) {
    if (!wasReady) invalidateBackendCatalog();
    luaErrorAction_ = 1;
    luaRepairMessage_ = luaRepairMessage_.length() > 0
                            ? luaRepairMessage_
                            : "Fixed app ready to run";
  } else if (luaRepairStatus_ == "failed" ||
             luaRepairStatus_ == "interrupted" ||
             luaRepairStatus_ == "unavailable" ||
             luaRepairStatus_ == "cancelled") {
    luaRepairRequested_ = false;
    luaRepairPrepareSent_ = false;
    luaRepairBuildConfirmed_ = false;
    luaRepairConfirmPending_ = false;
    luaRepairCancelPending_ = false;
    preferences.remove("repair_id");
    preferences.remove("repair_project");
    preferences.remove("repair_proposal");
    preferences.remove("repair_package");
    preferences.remove("repair_version");
    preferences.remove("repair_status");
    preferences.remove("repair_phase");
    preferences.remove("repair_message");
    preferences.remove("repair_progress");
    luaRepairId_ = "";
    luaRepairProjectId_ = "";
    luaRepairProposalId_ = "";
    luaRepairReadyPackageId_ = "";
    luaRepairReadyVersion_ = "";
  }
}

void FireOS::startLuaRepairRun() {
  if (luaRepairReadyPackageId_.length() == 0 || !backendClient_ ||
      !backendClient_->sessionReady()) {
    luaRepairMessage_ = "Waiting for backend connection";
    return;
  }
  if (requestAppDownload(luaRepairProjectId_,luaRepairReadyPackageId_,luaErrorAppId_,true)) {
    luaRepairStatus_="downloading";luaRepairPhase_="installing";
  }

}

void FireOS::handleLuaErrorButton(uint8_t index) {
  if((downloadPhase_==1 || downloadPhase_==2) && downloadPackage_==luaRepairReadyPackageId_) {
    if(index==2) cancelAppDownload();
    else if(index==0) {home();} // Minimize retains explicit Run intent; Cancel never does.
    return;
  }
  if (aiJobViewing_ && aiJobOpenPending_ && index==1) {luaRepairMessage_="Venter på jobbstatus";return;}
  if (aiJobViewing_ && index==1 && luaRepairStatus_=="awaiting_confirmation") {
    aiJobViewing_=false;sendAiJobAction("resume");return;
  }
  const bool repairActive = luaRepairRequested_ || luaRepairId_.length() > 0 ||
                            luaRepairStatus_ == "ready" ||
                            luaRepairStatus_ == "building" ||
                            luaRepairStatus_ == "testing" ||
                            luaRepairStatus_ == "queued" ||
                            luaRepairStatus_ == "awaiting_confirmation";
  if (index == 0) {
    // Minimize only. The PC-owned repair continues in the background.
    goToBootApp();
    return;
  }
  if (repairActive && index == 2) {
    cancelLuaRepair();
    return;
  }
  if (index == 2) {
    back();
    return;
  }
  if (repairActive && index==1 && (luaRepairStatus_=="queued" || luaRepairStatus_=="building" || luaRepairStatus_=="testing" || luaRepairStatus_=="paused")) {
    openAiWork();return;
  }
  if (luaErrorAction_ == 0) {
    requestLuaRepair();
  } else {
    startLuaRepairRun();
  }
}

void FireOS::requestBackgroundBuildJobs() {
  if ((!backgroundBuildsSupported_ && !failedBuildResumeSupported_) ||
      buildJobsRequested_ || !backendClient_ ||
      !backendClient_->sessionReady())
    return;
  if (backendClient_->buildJobs(0)) {
    buildJobsRequested_ = true;
    buildJobsRequestAt_ = millis();
  }
}

void FireOS::handleBackgroundBuildMessage(const String& message) {
  const String type = jsonStringField(message, "type");
  const String buildId = jsonStringField(message, "build_id");
  if (type=="job_control_result") {
    const String replyBuild=jsonStringField(message,"build_id"),replyRepair=jsonStringField(message,"repair_id");
    if (!fire_ai_menu::sameJob(aiJobBuild_.c_str(),aiJobRepair_.c_str(),replyBuild.c_str(),replyRepair.c_str())) return;
    aiWorkflowText_=jsonStringField(message,"display_text");
    if (!aiWorkflowText_.length()) aiWorkflowText_=jsonStringField(message,"message");
    if (jsonStringField(message,"status")=="context_ready") {
      aiProjectPickerActive_=false;
      if (!startAiRecording()) {aiWorkflowText_=aiAudioError_;aiProjectPickerActive_=true;aiPickerPage_=fire_ai_menu::Page::Work;}
    } else if (jsonStringField(message,"job_action")=="delete") openAiJobs(buildJobsOffset_);
    redrawRequested_=true;return;
  }
  if (type == "build_jobs") {
    buildJobsOffset_=static_cast<uint32_t>(max<int32_t>(0,jsonIntField(message,"offset",0)));
    buildJobsNext_=jsonIntField(message,"next_offset",-1)>static_cast<int32_t>(buildJobsOffset_);
    buildJobsRequested_ = false;
    buildJobsRequestAt_ = 0;
    buildJobsRetryCount_ = 0;
    backendBootJobsReceived_ = true;
    backendBootSyncWaiting_ = false;
    backendBootPending_ = false;
    buildJobCount_ = 0;
    bool activeBuildFound = false;
    uint8_t activeBuildPriority = 0;
    cJSON* document=cJSON_Parse(message.c_str());
    const cJSON* jobs=cJSON_GetObjectItemCaseSensitive(document,"jobs");
    const bool openingBuild=aiJobOpenPending_ && !aiJobRepair_.length();bool opened=false;
    for (int row=0;cJSON_IsArray(jobs) && row<cJSON_GetArraySize(jobs) && buildJobCount_<4;++row) {
      const cJSON* item=cJSON_GetArrayItem(jobs,row);if(!cJSON_IsObject(item)) continue;
      const uint8_t i=buildJobCount_;
      buildJobIds_[i]=aiJobText(item,"build_id");buildJobRepairIds_[i]=aiJobText(item,"repair_id");
      if (!buildJobIds_[i].length() && !buildJobRepairIds_[i].length()) continue;
      buildJobNames_[i]=aiJobText(item,"app_name");if(!buildJobNames_[i].length()) buildJobNames_[i]=aiJobText(item,"name");
      buildJobCanOpen_[i]=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(item,"can_open"));
      buildJobCanDelete_[i]=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(item,"can_delete"));
      buildJobCanPause_[i]=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(item,"can_pause"));
      buildJobCanContext_[i]=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(item,"can_add_context"));
      buildJobCanResume_[i]=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(item,"can_resume"));
      buildJobCanRetry_[i]=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(item,"can_retry"));
      buildJobStatuses_[i]=aiJobText(item,"status");buildJobErrors_[i]=aiJobText(item,"error_status");
      if(!buildJobErrors_[i].length()) buildJobErrors_[i]=aiJobText(item,"message");
      buildJobErrorCodes_[i]=aiJobText(item,"error_code");buildJobDiagnostics_[i]=aiJobText(item,"diagnostic_message");
      if (openingBuild && buildJobIds_[i]==aiJobBuild_) {restoreAiJob(item);opened=true;}
      const String phase=aiJobText(item,"phase");String text=aiJobText(item,"display_text");
      if(!text.length()) text=aiJobText(item,"message");
      if (fire_ai_menu::stopsTrackedWork(aiBuildId_.c_str(),buildJobIds_[i].c_str(),buildJobStatuses_[i].c_str(),phase.c_str())) {
        const String package=aiJobText(item,"package_id");
        if (fire_ai_menu::workReady(buildJobStatuses_[i].c_str(),phase.c_str(),package.c_str()) && buildPhase_!="ready") workCompletedAt_=millis();
        else if (buildJobStatuses_[i]!="ready") workCompletedAt_=0;
        backgroundBuildActive_=false;buildPhase_=phase;
      }
      const bool selected=!aiJobViewing_ || (!aiJobRepair_.length() && aiJobBuild_==buildJobIds_[i]);
      const bool active=selected && buildJobIds_[i].length() && fire_ai_menu::workActive(buildJobStatuses_[i].c_str(),phase.c_str());
      const uint8_t priority=buildJobStatuses_[i]=="queued" && phase=="queued"?1:2;
      if(active && (!activeBuildFound || priority>activeBuildPriority)) {
        workCompletedAt_=0;
        activeBuildFound=true;activeBuildPriority=priority;aiBuildId_=buildJobIds_[i];
        aiProjectName_=buildJobNames_[i].length()?buildJobNames_[i]:String("Appnavn ikke hentet");
        const cJSON* value=cJSON_GetObjectItemCaseSensitive(item,"progress");
        buildProgress_=cJSON_IsNumber(value)?constrain(value->valueint,0,100):0;aiBuildProgress_=buildProgress_;
        value=cJSON_GetObjectItemCaseSensitive(item,"resume_count");aiBuildResumeCount_=cJSON_IsNumber(value)?value->valueint:-1;
        buildPhase_=phase;buildStatusMessage_=text;aiWorkflowText_=text.length()?text:phase.length()?phase:String("Lager app");
        aiWorkflowState_=4;aiDeveloperMode_=2;backgroundBuildActive_=true;aiBuildResumePending_=aiBuildRetryPending_=false;
      }
      ++buildJobCount_;
    }
    cJSON_Delete(document);
    if(openingBuild && !opened) {aiJobOpenPending_=false;aiJobCanOpen_=false;aiWorkflowText_="Jobblisten er endret. Velg igjen";}
    aiResumeAvailable_ = buildJobCount_ > 0;
    redrawRequested_ = true;
    return;
  }
  const bool buildEvent = type == "build_progress" ||
                          type == "build_job_status" ||
                          type == "build_resumed" ||
                          type == "build_ready_notice" ||
                          type == "build_backgrounded" ||
                          type == "build_cancelled";
  const bool independentNotice = type == "build_ready_notice";
  if (buildEvent && buildId.length() > 0 && aiBuildId_.length() > 0 &&
      buildId != aiBuildId_ && !aiBuildRetryPending_ && !independentNotice) {
    // A delayed event from the previous failed job must not overwrite a
    // newer retry job after reconnect.
    return;
  }
  if (buildEvent && buildId.length() > 0 && buildId != aiBuildId_ &&
      !independentNotice) {
    aiProjectName_=jsonStringField(message,"app_name");
    if(!aiProjectName_.length()) aiProjectName_=jsonStringField(message,"name");
    if(!aiProjectName_.length()) aiProjectName_="Appnavn ikke hentet";
    aiReadyPackageId_=String();aiBuildProgress_=0;buildProgress_=0;
    aiBuildErrorCode_ = "";
    aiBuildErrorStatus_ = "";
    aiBuildDiagnosticMessage_ = "";
    aiBuildResumePending_ = false;
    aiBuildCanResume_ = false;
    aiBuildCanRetry_ = false;
    aiBuildResumeCount_ = -1;
    aiBuildId_ = buildId;
    aiBuildRetryPending_ = false;
  }
  const int incomingResumeCount =
      buildEvent ? jsonIntField(message, "resume_count", -1) : -1;
  if (buildEvent && buildId.length() > 0 && buildId == aiBuildId_ &&
      incomingResumeCount >= 0 && aiBuildResumeCount_ >= 0 &&
      incomingResumeCount < aiBuildResumeCount_) {
    return;
  }
  if (incomingResumeCount >= 0 && (!independentNotice || buildId == aiBuildId_))
    aiBuildResumeCount_ = incomingResumeCount;
  if (type == "build_progress" || type == "build_job_status" ||
      type == "build_resumed") {
    const String status = jsonStringField(message, "status");
    const String state = jsonStringField(message, "state");
    const String incomingPhase = jsonStringField(message, "phase");
    const String readyPackage=jsonStringField(message,"package_id");
    const bool wasReady=buildPhase_=="ready" && readyPackage.length() && readyPackage==aiReadyPackageId_;
    const String errorCode = jsonStringField(message, "error_code");
    const String errorStatus = jsonStringField(message, "error_status");
    const String diagnostic = jsonStringField(message, "diagnostic_message");
    if (errorCode.length() > 0) aiBuildErrorCode_ = errorCode;
    if (errorStatus.length() > 0) aiBuildErrorStatus_ = errorStatus;
    else if (status == "failed") {
      const String fallback = jsonStringField(message, "message");
      if (fallback.length() > 0) aiBuildErrorStatus_ = fallback;
    }
    if (diagnostic.length() > 0) aiBuildDiagnosticMessage_ = diagnostic;
    if (message.indexOf("\"can_resume\"") >= 0)
      aiBuildCanResume_ = jsonBoolField(message, "can_resume", false);
    if (message.indexOf("\"can_retry\"") >= 0)
      aiBuildCanRetry_ = jsonBoolField(message, "can_retry", false);

    if (type == "build_resumed" &&
        (state == "awaiting_build_confirmation" ||
         state == "awaiting_confirmation")) {
      buildProgress_ = static_cast<uint8_t>(
          constrain(buildProgressField(message,aiBuildProgress_), 0, 100));
      buildPhase_ = incomingPhase;
      buildStatusMessage_ = jsonStringField(message, "display_text");
      if(!buildStatusMessage_.length()) buildStatusMessage_=jsonStringField(message,"message");
      aiBuildProgress_ = buildProgress_;
      aiProposalId_ = jsonStringField(message, "proposal_id");
      aiProposalProjectId_=jsonStringField(message,"project_id");aiProposalJobId_=jsonStringField(message,"evolution_job_id");aiProposalAppName_=jsonStringField(message,"app_name");
      aiBuildResumePending_ = true;
      aiBuildRetryPending_ = false;
      backgroundBuildActive_ = false;
      aiWorkflowState_ = aiProposalId_.length() > 0 ? 3 : 2;
      aiDeveloperMode_ = 2;
      aiWorkflowText_ = aiBuildErrorStatus_.length() > 0
                            ? compactStatusText(aiBuildErrorStatus_)
                            : "READY TO RETRY";
      aiAssistantText_ = aiBuildErrorStatus_;
      redrawRequested_ = true;
      return;
    }
    if (status != "failed" && incomingPhase != "failed") {
      // The same build_id continues after retry. Its old failure is history,
      // not the current status shown on FIRE.
      aiBuildErrorCode_ = "";
      aiBuildErrorStatus_ = "";
      aiBuildDiagnosticMessage_ = "";
      aiBuildCanResume_ = false;
      aiBuildCanRetry_ = false;
      aiBuildResumePending_ = false;
      aiBuildRetryPending_ = false;
      aiAssistantText_ = "";
    }
    workCompletedAt_=fire_ai_menu::completionStamp(millis(),workCompletedAt_,wasReady,
        status.c_str(),incomingPhase.c_str(),readyPackage.c_str());
    buildProgress_ = static_cast<uint8_t>(
        constrain(buildProgressField(message,aiBuildProgress_), 0, 100));
    buildPhase_ = incomingPhase;
    buildStatusMessage_ = jsonStringField(message, "display_text");
    if(!buildStatusMessage_.length()) buildStatusMessage_=jsonStringField(message,"message");
    aiBuildProgress_ = buildProgress_;
    aiWorkflowText_ = buildStatusMessage_.length() > 0
                          ? buildStatusMessage_
                          : buildPhase_;
    if (buildPhase_ == "ready" || status == "ready") {
      if(aiJobViewing_ && !aiJobRepair_.length()) aiJobNeedsInstall_=true;
      if(readyPackage.length()) {aiReadyPackageId_=readyPackage;aiPackageId_=readyPackage;}
      aiWorkflowState_ = 5;
      backgroundBuildActive_ = false;
      aiBuildResumePending_ = false;
      if(type=="build_resumed" && buildNoticeRunBuildId_==buildId &&
         buildNoticeRunPackageId_.length() && buildNoticeRunPackageId_==readyPackage) {
        const String target=buildNoticeRunPackageId_;
        buildNoticeRunBuildId_=String();buildNoticeRunPackageId_=String();
        if(backendClient_ && !(packageManager_ && packageManager_->busy()) && backendClient_->confirmRun(target)) {
          aiWorkflowState_=6;aiWorkflowText_="Starter app";
        } else aiWorkflowText_="App klar – velg Kjør";
      }
    } else if (buildPhase_ == "failed" || status == "failed") {
      aiWorkflowState_ = 0;
      aiDeveloperMode_ = 2;
      backgroundBuildActive_ = false;
      aiResumeAvailable_ = true;
      aiBuildResumePending_ = false;
      aiWorkflowText_ = aiBuildErrorStatus_.length() > 0
                            ? compactStatusText(aiBuildErrorStatus_)
                            : "BUILD FAILED";
    } else {
      aiWorkflowState_ = 4;
      aiDeveloperMode_ = 2;
      backgroundBuildActive_ = fire_ai_menu::workActive(status.c_str(),buildPhase_.c_str());
    }
  } else if (type == "build_ready_notice") {
    if (buildId == buildNoticePendingId_) return;
    if (buildId.length() > 0 && buildId == buildNoticeAckedId_) {
      redrawRequested_ = true;
      return;
    }
    const String noticePackage=jsonStringField(message,"package_id");
    if (buildId.length() && fire_ai_menu::workReady(jsonStringField(message,"status").c_str(),jsonStringField(message,"phase").c_str(),noticePackage.c_str())) {
      if (buildId!=buildNoticeId_ || noticePackage!=buildNoticePackageId_) workCompletedAt_=millis();
      if (buildId==aiBuildId_) backgroundBuildActive_=false;
    }
    buildNoticeActive_ = true;
    buildNoticeId_ = buildId;
    buildNoticePackageId_=jsonStringField(message,"package_id");
    buildNoticeName_ = jsonStringField(message, "name");
    buildNoticeMessage_ = jsonStringField(message, "display_text");
    if(!buildNoticeMessage_.length()) buildNoticeMessage_=jsonStringField(message,"message");
    if (buildNoticeMessage_.length() == 0) buildNoticeMessage_ = "Appen er klar";
  } else if (type == "build_notice_closed" || type == "event_ack") {
    bool acknowledged = type == "build_notice_closed" &&
        buildId == buildNoticePendingId_ &&
        jsonStringField(message, "action") == buildNoticePendingAction_;
    if (type == "event_ack" && buildNoticePendingEvent_.length() &&
        jsonStringField(message, "event_id") == buildNoticePendingEvent_) {
      cJSON* root = cJSON_Parse(message.c_str());
      const cJSON* status = cJSON_GetObjectItemCaseSensitive(root, "status");
      const cJSON* result = cJSON_GetObjectItemCaseSensitive(root, "result");
      const cJSON* kind = cJSON_GetObjectItemCaseSensitive(result, "type");
      const cJSON* id = cJSON_GetObjectItemCaseSensitive(result, "build_id");
      const cJSON* action = cJSON_GetObjectItemCaseSensitive(result, "action");
      acknowledged = cJSON_IsString(status) &&
          (!strcmp(status->valuestring, "accepted") || !strcmp(status->valuestring, "duplicate")) &&
          cJSON_IsString(kind) && !strcmp(kind->valuestring, "build_notice_closed") &&
          cJSON_IsString(id) && buildNoticePendingId_ == id->valuestring &&
          cJSON_IsString(action) && buildNoticePendingAction_ == action->valuestring;
      cJSON_Delete(root);
    }
    if (acknowledged) {
      buildNoticeAckedId_ = buildNoticePendingId_;
      buildNoticePendingId_ = "";
      buildNoticePendingEvent_ = "";
    }
  } else if (type == "build_backgrounded") {
    // This ACK changes visibility, not the job state or completion.
    backgroundBuildActive_ = backgroundBuildActive_ && fire_ai_menu::workPhase(buildPhase_.c_str());
    aiWorkflowText_ = "Bygger i bakgrunnen";
    aiWorkflowState_ = 4;
  } else if (type == "build_cancelled") {
    backgroundBuildActive_ = false;workCompletedAt_=0;
    aiWorkflowState_ = 0;
    aiBuildRetryPending_ = false;
    aiWorkflowText_ = "Bygging avbrutt";
  }
  redrawRequested_ = true;
}

void FireOS::updateLuaApp() {
  if (!luaAppActive_) return;
  const uint32_t now = millis();
  const uint32_t elapsed = now - luaLastFrameAt_;
  luaLastFrameAt_ = now;
  const uint32_t previousFrames=luaRuntime_?luaRuntime_->frameCount():0;
  const bool callbackOk=luaRuntime_ && luaRuntime_->update(min<uint32_t>(elapsed,100));
  if (luaRuntime_ && luaRuntime_->frameCount()!=previousFrames)
    evolution_.callback(1,luaRuntime_->lastCallbackUs(),heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),luaRuntime_->peakMemoryUsed());
  if (!callbackOk) {
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
  if (luaAppActive_) flushLuaRgb();
}

void FireOS::cycleBackendMode() {
  if (!fire_backend_policy::saveMode(preferences,backendMode_,static_cast<uint8_t>((backendMode_+1)%3))) {
    backendStatus_="Valget kunne ikke bekreftes";redrawRequested_=true;return;
  }
  applyBackendMode();
}

void FireOS::applyBackendMode() {
  if (backendMode_ == 2) {
    backendBootPending_ = false;
    backendBootSyncWaiting_ = false;
    backendBootAttempted_ = true;
    if (backendClient_ && backendClient_->active()) backendClient_->disconnect();
    backendStatus_ = "Backend sync off";
    return;
  }
  if (backendClient_ && backendClient_->configured() && wifiMode_ != 2) {
    backendClient_->retrySession(); // explicit user policy change clears a terminal admission error
    // Auto performs one lightweight boot check; On remains demanded by
    // updateBackend() until the user changes the policy again.
    backendBootPending_ = true;
    backendBootSyncWaiting_ = true;
    backendBootSyncStartedAt_ = 0;
    backendBootJobsReceived_ = false;
    backendBootAttempted_ = false;
  }
}

void FireOS::updateBackend() {
  FireUiPhaseTimer timing("backend_service");
  if (!backendClient_) return;
  if (firmwareNetworkPaused_ || (packageManager_ && packageManager_->networkPaused())) {
    if (backendClient_->active()) backendClient_->disconnect();
    return;
  }
  if (!fire_ui_cadence::networkAllowed(wifiMode_==2,backendMode_==2)) {
    if (backendClient_->active()) backendClient_->disconnect();
    backendBootPending_ = false;
    backendBootSyncWaiting_ = false;
    return;
  }
  const uint32_t responseNow = millis();
  const bool inventoryInFlight = appInventoryPending_ && backendClient_->sessionReady();
  if (!inventoryInFlight) appInventoryDemandAt_ = 0;
  else if (!appInventoryDemandAt_) appInventoryDemandAt_ = responseNow;
  else if (responseNow - appInventoryDemandAt_ >= 30000) {
    appInventoryPending_ = false;
    appInventoryDemandAt_ = 0;
    Serial.println("FIRE inventory response deadline expired");
  }
  const bool writesPending = backendClient_->pendingWrites();
  if (!writesPending) backendDrainStartedAt_ = 0;
  else if (!backendDrainStartedAt_) backendDrainStartedAt_ = responseNow;
  const bool drainDemand = writesPending && responseNow - backendDrainStartedAt_ < 20000;
  // Time sync has its own deadline. Never make backend discovery depend on NTP.
  if (backendBootSyncWaiting_ && WiFi.status() == WL_CONNECTED &&
      backendBootSyncStartedAt_ == 0) backendBootSyncStartedAt_ = millis();
  const bool bootCheck = backendBootPending_ &&
                         WiFi.status() == WL_CONNECTED &&
                         !backendBootAttempted_;
  const bool evolutionDemand = evolutionUi_.controlRequest.length()>0 ||
      (evolution_.pending() && evolutionUi_.connectAt && millis()-evolutionUi_.connectAt<15000);
  // Quick Settings is an overlay, not an exit from its live conversation.
  const Screen demandScreen=fire_ui_cadence::contentScreen(screen_,previousScreen_,Screen::QuickSettings);
  const bool backendDemand = (packageManager_ && packageManager_->busy()) || evolutionDemand || demandScreen == Screen::AiDeveloper ||
                              (luaAppActive_ && (luaRuntimeAiAllowed_ || luaDataAllowed_ || luaDevelopJob_)) ||
                              luaAiBindPackageId_.length()>0 ||
                              demandScreen == Screen::AiApi ||
                              fire_ui_cadence::repairViewDemand(demandScreen==Screen::LuaApp,luaAppActive_) ||
                              demandScreen == Screen::Settings ||
                              demandScreen == Screen::AppsSettings ||
                              demandScreen == Screen::Evolution ||
                               luaRepairRequested_ || luaRepairId_.length() > 0 ||
                               backgroundBuildActive_ || buildNoticeActive_ ||
                               buildNoticePendingId_.length() > 0 ||
                               (backendMode_ == 1 && backendClient_->configured()) ||
                               backendBootPending_ || backendBootSyncWaiting_ ||
                               // Finish an in-flight inventory without turning
                               // Auto into a permanent offline reconnect loop.
                               (appInventoryPending_ && backendClient_->sessionReady()) ||
                               drainDemand ||
                               bootCheck ||
                              (packageManager_ && packageManager_->busy()) ||
                              (firmwareStorage_ && firmwareStorage_->busy()) ||
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
  if (buildNoticePendingId_.length() && backendClient_->sessionReady() &&
      (!buildNoticeLastSendAt_ || millis() - buildNoticeLastSendAt_ >= 3000)) {
    if (!buildNoticePendingEvent_.length())
      buildNoticePendingEvent_ = "notice-" + backendClient_->bootId() + "-" +
                                 String(esp_random(), HEX);
    if (backendClient_->buildNoticeAck(buildNoticePendingId_,
          buildNoticePendingAction_, buildNoticePendingEvent_))
      buildNoticeLastSendAt_ = millis();
  }
  if (luaRepairCancelPending_ && backendClient_->sessionReady() &&
      luaRepairId_.length() > 0) {
    if (backendClient_->appRepairCancel(luaRepairId_)) {
      luaRepairCancelPending_ = false;
      luaRepairMessage_ = "Venter på avbrytelse";
    }
  }
  if (buildJobsRequested_ && buildJobsRequestAt_ != 0 &&
      millis() - buildJobsRequestAt_ >= 5000) {
    buildJobsRequested_ = false;
    buildJobsRequestAt_ = 0;
    if (buildJobsRetryCount_ < 2 && backendClient_->sessionReady()) {
      ++buildJobsRetryCount_;
      requestBackgroundBuildJobs();
    }
  }
  if (bootCheck) {
    backendBootAttempted_ = true;
    backendBootAttemptedAt_ = millis();
  }
  if (backendBootSyncWaiting_ && backendBootSyncStartedAt_ != 0 &&
      millis() - backendBootSyncStartedAt_ >= 15000) {
    // A boot sync must not hold the UI forever when the PC is offline or the
    // backend does not answer build_jobs. Normal screen demand can reconnect.
    backendBootSyncWaiting_ = false;
    backendBootPending_ = false;
    buildJobsRequested_ = false;
  }
  serviceLuaRepair();
  if(luaAiBindPackageId_.length()) {
    if(!luaAppActive_ || !(luaRuntimeAiAllowed_ || luaDataAllowed_ || luaDevelopJob_) || luaPackageId_!=luaAiBindPackageId_ ||
       millis()-luaAiBindAt_>30000) {luaAiBindPackageId_=String();luaAiBindSent_=false;}
    else if(!luaAiBindSent_ && !appInventoryPending_ && !luaScanPending_ &&
            luaCacheComplete_ && !(packageManager_ && packageManager_->busy()) && !backendClient_->pendingWrites() && backendClient_->sessionReady())
      luaAiBindSent_=backendClient_->confirmRun(luaAiBindPackageId_);
  }
  if (luaRepairStatusQueryPending_ && backendClient_->sessionReady()) {
    if (backendClient_->appRepairStatus(luaRepairId_, luaRepairAppId_))
      luaRepairStatusQueryPending_ = false;
  }
  updateAppManagerBackend();
  flushLuaDiagnostic();
}

void FireOS::backendState(void* context, bool connected, const String& status) {
  auto* os = static_cast<FireOS*>(context);
  if (!os) return;
  const bool transfer=os->packageManager_ && os->packageManager_->networkPaused();
  os->backendStatus_ = transfer?String("Overfører app"):status;
  if(!connected) {
    os->backendCatalogEpoch_=0;os->backendCatalogLoading_=false;os->backendCatalogRequested_=false;os->backendCatalogRequest_=String();
    for(LuaHardwareJob& job:os->luaJobs_) if(job.kind==LuaJobKind::RuntimeAi && job.state==0)
      os->cancelLuaRuntimeAi(job,"not_connected");
    for (LuaHardwareJob& job:os->luaJobs_) if (job.kind==LuaJobKind::Data && job.state==0 && job.started && job.aiRequestId.length())
      os->cancelLuaDataJob(job,"not_connected");
    if(os->luaAppActive_ && (os->luaRuntimeAiAllowed_ || os->luaDataAllowed_ || os->luaDevelopJob_)) {
      // A new authenticated session must bind the real VM again. Failed jobs
      // stay failed; reconnect never replays a paid request.
      os->luaRunId_=String();os->luaAiBindPackageId_=os->luaPackageId_;
      os->luaAiBindAt_=millis();os->luaAiBindSent_=false;
    }
  }
  if (connected) {
    os->backendCatalogRequested_=false;os->backendCatalogLoading_=false;os->backendCatalogAttemptAt_=0;os->backendCatalogFailures_=0;os->backendCatalogRequest_=String();
    os->buildJobsRequested_ = false;
    os->buildJobsRequestAt_ = 0;
    os->buildJobsRetryCount_ = 0;
  } else {
    os->buildJobsRequested_ = false;
    os->buildJobsRequestAt_ = 0;
  }
  if (connected && os->luaRepairId_.length() > 0)
    os->luaRepairStatusQueryPending_ = true;
  if (!connected && os->luaRepairPrepareSent_ &&
      os->luaRepairId_.length() == 0) {
    // The backend reuses the same failed-package repair job on retry, so a
    // lost prepare response can safely be replayed after reconnect.
    os->luaRepairPrepareSent_ = false;
    if(!transfer) os->luaRepairMessage_ = "Backend disconnected - waiting to retry";
  }
  if(transfer && os->downloadPackage_==os->luaRepairReadyPackageId_ && (os->downloadPhase_==1 || os->downloadPhase_==2))
    os->luaRepairMessage_="Overfører app";
  if (!connected && os->screen_ == Screen::AppsSettings) {
    os->backendCatalogLoading_ = false;
    os->backendCatalogRequested_ = false;
    os->managerStatus_ = transfer?"Overfører app":"Backend disconnected";
  }
  os->redrawRequested_ = true;
  if (!connected && os->screen_ == Screen::AiDeveloper &&
      os->aiWorkflowState_ > 0) {
    os->aiWorkflowText_ = transfer?"Overfører app":"BACKEND OFFLINE";
  }
}

void FireOS::packageStatus(void* context, const String& status) {
  auto* os = static_cast<FireOS*>(context);
  if (!os) return;
  os->aiWorkflowText_ = status;
  if(os->packageManager_ && os->packageManager_->packageId()==os->luaRepairReadyPackageId_ &&  (os->downloadPhase_==2 || os->downloadPhase_==3))
    os->luaRepairMessage_=os->downloadPhase_==3?String("Avbryter appoverføring"):compactStatusText(status);
  if (os->screen_ == Screen::AppsSettings) os->managerStatus_ = status;
  os->aiDeveloperMode_ = 2;os->redrawRequested_=true;
  if(os->packageManager_ && os->packageManager_->busy()) {
    os->aiBuildProgress_=os->packageManager_->progress();os->aiWorkflowState_=4;
  }
}

void FireOS::packageResult(void* context, bool ok, const String& packageId,
                           const String& installId, const String& archiveHash,
                           const String& message) {
  auto* os = static_cast<FireOS*>(context);
  if (!os) return;
  (void)installId;
  if(ok) {
    const String source=os->packageManager_?os->packageManager_->installedPath():String();
    const String folder=source.substring(0,source.lastIndexOf('/'));
    fire_lua_install::Identity identity;
    ok=source.endsWith("/main.lua") && SD.exists(source) &&
      fire_lua_install::read(SD,(folder+"/"+fire_lua_install::kFilename).c_str(),identity)==fire_lua_install::Read::Valid &&
      packageId==identity.package && archiveHash==identity.archive && os->sdBaseName(folder)==identity.app;
    if(!ok) {
      os->invalidateLuaApps();
      if(packageId==os->appUpdateCandidate_) {os->appUpdateReady_=false;os->appUpdateFailure_=1;}
      if(os->userRunAfterInstall_==packageId) os->userRunAfterInstall_=String();
      if(os->packageManager_) os->packageManager_->amendOutcome(false,"metadata_error");
    }
  }
  // Called once after BOTH workers have stopped. The mailbox remains busy
  // and immutable after this callback until the exact server receipt ACK.
  if (packageId==os->appUpdateCandidate_) os->appUpdateReady_=false;
  const bool selected=os->aiReadyPackageId_.length()?packageId==os->aiReadyPackageId_:packageId==os->aiPackageId_;
  if (selected) {os->aiPackageId_=packageId;os->aiWorkflowText_="Bekrefter installasjon";os->aiWorkflowState_=4;}
  if (os->screen_==Screen::AppsSettings) os->managerStatus_="Bekrefter installasjon";
  if (ok) {os->invalidateLuaApps();os->scanLuaApps();}
  else if (os->userRunAfterInstall_==packageId) os->userRunAfterInstall_=String();
  (void)message;os->redrawRequested_=true;
}

void FireOS::servicePackageInstall() {
  serviceDownloadIntent();
  if (!packageManager_ || !packageManager_->busy()) return;
  const bool allowed=wifiMode_!=2 && backendMode_!=2;
  if (!allowed && userRunAfterInstall_==packageManager_->packageId()) userRunAfterInstall_=String();
  bool occupied=aiAudioCaptureActive_ || aiAudioOutputActive_ || aiAudioDownloadPending_ || aiVoiceTestPlaybackActive_ ||
      aiConversationCancelPending_ || aiWorkflowState_==1 || aiWorkflowState_==2 || backgroundBuildActive_ ||
      (backendClient_ && (backendClient_->audioTransferActive() || backendClient_->selectionPending() || backendClient_->pendingWrites()));
  for (const LuaHardwareJob& job:luaJobs_) if (job.state==0 && (job.kind==LuaJobKind::RuntimeAi ||
      (job.kind==LuaJobKind::Data && (job.dataOperation=="process" || job.dataOperation=="develop" || job.dataOperation=="sync")))) occupied=true;
  const bool unexpired=backendCommandUnexpired(packageManager_->installExpiry()) && backendClient_ &&
      backendClient_->bootId()==packageManager_->installBoot() && fire_package_delivery::admittedScope(
          backendClient_->sessionReady(),packageManager_->installSession().c_str(),packageManager_->installBoot().c_str(),
          backendClient_->sessionId().c_str(),backendClient_->bootId().c_str());
  const bool quiet=(!backendClient_ || (!backendClient_->active() && backendClient_->networkIdle())) && homeApp_.networkIdle();
  const bool wasPaused=packageManager_->networkPaused();
  packageManager_->service(WiFi.status()==WL_CONNECTED,allowed,occupied,quiet,unexpired);
  if (packageManager_->networkPaused()) {
    backendStatus_="Overfører app";
    if (backendClient_ && backendClient_->active()) backendClient_->disconnect();
    homeApp_.service(WiFi.status()==WL_CONNECTED,false);reverseTransport_.service(false);
    return;
  }
  if (wasPaused && backendClient_) {backendStatus_=backendClient_->status();redrawRequested_=true;}
  if(packageManager_->otherNetworksPaused()) homeApp_.service(WiFi.status()==WL_CONNECTED,false);
  if (!packageManager_->receiptReady()) return;
  const char* receiptStatus=packageTransferLabel();
  if(managerStatus_!=receiptStatus || (downloadPackage_==luaRepairReadyPackageId_ && luaRepairMessage_!=receiptStatus) ||
      ((downloadPackage_==aiReadyPackageId_ || downloadPackage_==aiPackageId_) && aiWorkflowText_!=receiptStatus)) downloadIntentStatus(receiptStatus);
  if (!unexpired || (backendClient_->sessionReady() && !fire_package_delivery::sameScope(
      packageManager_->installSession().c_str(),packageManager_->installBoot().c_str(),
      backendClient_->sessionId().c_str(),backendClient_->bootId().c_str()))) {
    finishPackageReceipt(false);return;
  }
  if (allowed && backendClient_->sessionReady() && packageManager_->receiptDue(millis())) {
    if (backendClient_->deviceInstallResult(packageManager_->installId(),packageManager_->packageId(),
        packageManager_->outcomeOk(),packageManager_->outcomeHash(),packageManager_->outcomeMessage(),packageManager_->receiptEvent()))
      packageManager_->receiptSent(millis());
  }
}

bool FireOS::handlePackageReceipt(const String& message) {
  if (!packageManager_ || !packageManager_->receiptReady() ||
      jsonStringField(message,"event_id")!=packageManager_->receiptEvent()) return false;
  const String type=jsonStringField(message,"type");
  if (type!="event_ack" && type!="error") return false;
  if (!backendClient_ || !backendClient_->sessionReady() || !backendCommandUnexpired(packageManager_->installExpiry()) ||
      !fire_package_delivery::sameScope(packageManager_->installSession().c_str(),packageManager_->installBoot().c_str(),
          backendClient_->sessionId().c_str(),backendClient_->bootId().c_str()) ||
      jsonStringField(message,"session_id")!=packageManager_->installSession()) return true;
  cJSON* root=cJSON_Parse(message.c_str());const cJSON* result=cJSON_GetObjectItemCaseSensitive(root,"result");
  const bool recorded=type=="event_ack" && fire_package_delivery::recordedAck(packageManager_->receiptEvent().c_str(),
      aiJobText(root,"event_id").c_str(),aiJobText(root,"status").c_str(),aiJobText(result,"status").c_str(),
      packageManager_->packageId().c_str(),aiJobText(result,"package_id").c_str(),
      cJSON_GetObjectItemCaseSensitive(result,"error") || cJSON_GetObjectItemCaseSensitive(root,"error"));
  cJSON_Delete(root);finishPackageReceipt(recorded);return true;
}

void FireOS::finishPackageReceipt(bool recorded) {
  if (!packageManager_ || !packageManager_->receiptReady()) return;
  const String package=packageManager_->packageId();
  const bool ok=recorded && packageManager_->outcomeOk();
  if (downloadPackage_==package && downloadPhase_==2) downloadPhase_=0;
  const String detail=recorded?packageManager_->outcomeMessage():String("Installasjonsstatus uavklart");
  packageManager_->finishReceipt(); // one completed slot consumed ONLY here
  if (package==appUpdateCandidate_) {
    appUpdateReady_=ok;appUpdateFailure_=!ok;appUpdateRequest_=String();
    if (appUpdateStage_==2) appUpdateStage_=fire_app_updates::completed(appUpdateStage_,ok);
    appUpdateSelection_=1;
  }
  const bool selected=aiReadyPackageId_.length()?package==aiReadyPackageId_:package==aiPackageId_;
  if (selected) {aiWorkflowState_=ok || aiJobNeedsInstall_?5:0;aiWorkflowText_=ok?"App installert":detail;}
  if (screen_==Screen::AppsSettings) managerStatus_=ok?"Downloaded to FIRE":detail;
  if (package==luaRepairReadyPackageId_) {
    luaRepairStatus_="ready";luaRepairPhase_="ready";luaRepairMessage_=ok?"Reparert app installert":detail;luaErrorAction_=1;
  }
  if (ok) sendAppInventory();
  if (package==userRunAfterInstall_) {
    userRunAfterInstall_=String();
    if (ok && backendClient_ && backendClient_->confirmRun(package)) {
      luaAiBindPackageId_=String();luaAiBindSent_=false;
      aiJobNeedsInstall_=false;aiWorkflowState_=6;aiWorkflowText_="Starter valgt app";
      if (package==luaRepairReadyPackageId_) {luaRepairStatus_="starting";luaRepairPhase_="starting";luaRepairMessage_="Starter reparert app";}
    }
  }
  redrawRequested_=true;
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
  os->firmwareMessage_ = ok ? (manifest ? "GitHub list ready" : "SD kontrollert. Ikke installert")
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
  if (handlePackageReceipt(message)) return;
  if (handleDownloadIntent(message)) return;
  if (handleFeedbackAck(message)) return;
  if(type=="error") {
    const String event=jsonStringField(message,"event_id");
    if(event.length() && ((appManagerVersionsWaiting_ && event==appManagerRequest_) ||
        (appManagerDeleteWaiting_ && event==appManagerDeleteRequest_))) {
      appManagerVersionsWaiting_=appManagerDeleteWaiting_=false;appManagerRequest_=appManagerDeleteRequest_=String();
      managerStatus_="Apphandlingen ble avvist. Velg på nytt.";return;
    }
  }
  if(appUpdateStage_==2 && appUpdateRequest_.length() && jsonStringField(message,"event_id")==appUpdateRequest_ && (type=="error" || type=="event_ack")) {
    cJSON* reply=cJSON_Parse(message.c_str());
    const cJSON* result=cJSON_GetObjectItemCaseSensitive(reply,"result");
    const bool rejected=type=="error" || cJSON_GetObjectItemCaseSensitive(result,"error");
    cJSON_Delete(reply);
    if(rejected) {appUpdateStage_=1;appUpdateFailure_=1;appUpdateSelection_=1;appUpdateRequest_=String();}
  }
  const bool selectedApp=backendClient_ && backendClient_->selectionAppAck();
  const bool selectedMode=backendClient_ && backendClient_->selectionModeAck();
  const bool selectionFailed=backendClient_ && backendClient_->selectionFailed();
  const bool bootstrap=type=="session_started" || type=="session_snapshot";
  // These fields are typed, server-confirmed scope. A socket write is never
  // confirmation, and a delayed reply cannot approve another user's choice.
  if (backendClient_ && (selectedApp || selectionFailed ||
      (bootstrap && !aiJobViewing_ && !backendClient_->selectionPending()))) {
    const String project=backendClient_->confirmedProject();
    if (aiEvolutionGoalProject_!=project) {aiEvolutionGoal_=String();aiEvolutionGoalProject_=String();aiDevelopmentContext_=String();}
    aiProjectId_=project;aiBasePackageId_=backendClient_->confirmedBase();
    backendClient_->setProjectId(project);
    if (selectedApp) {aiProposalProjectId_=String();aiProposalJobId_=String();aiProposalAppName_=String();}
    if (selectedApp && aiEvolutionNewPending_ && backendClient_->confirmedAppMode()=="new" && project.length()) {
      aiEvolutionNewPending_=false;openEvolution(true);
    }
  }
  if (backendClient_ && (selectedMode || selectedApp || selectionFailed || bootstrap || type=="conversation_mode")) {
    const String mode=backendClient_->confirmedMode();
    if (mode=="chat") aiConversationMode_=1;
    else if (mode=="develop") aiConversationMode_=0;
  }
  if (selectionFailed) {
    aiEvolutionNewPending_=false;aiWorkflowText_="Valg avvist. Velg app igjen";
    return;
  }
  if (selectedApp || selectedMode) aiWorkflowText_=backendClient_->selectionPending()?"Venter på modus":"Valg bekreftet";
  if (type=="app_selected" || type=="conversation_mode") return;
  if(type=="runtime_ai_result") {handleRuntimeAiResult(message);return;}
  if(type=="evolution_snapshot" || type=="evolution_proposal" || type=="evolution_telemetry_ack") {handleEvolutionMessage(message);return;}
  if(type=="backend_settings_snapshot" || type=="backend_settings_proposal") {handleBackendSettings(message);return;}
  if(type=="error") {
    const String request=jsonStringField(message,"request_id");
    if (request.length() && request==backendSettingsUi_.request) {handleBackendSettings(message);return;}
    if (request.length() && (request==evolutionUi_.request || request==evolutionUi_.controlRequest || request==evolutionUi_.policyRequest || request==evolutionUi_.runtimeRequest)) {handleEvolutionMessage(message);return;}
  }
  if(type=="data_result" || type=="app_develop_ready") {handleDataResult(message);return;}
  if(type=="session_started" || type=="session_snapshot") {
    const String mode=jsonStringField(message,"runtime_ai_mode");
    if(mode=="auto" || mode=="off") {
      const bool selected=mode=="auto";if(aiRuntimeAuto_!=selected) preferences.putBool("runtime_ai_auto",selected);
      aiRuntimeAuto_=selected;aiRuntimeModeAcked_=true;
      if(backendClient_) backendClient_->setRuntimeAiMode(mode,false);
    }
    runtimeAiEnabled_=jsonBoolField(message,"runtime_ai_enabled",runtimeAiEnabled_);
  }
  if (type == "session_started") {
    // An event's identity is bound to its session. Retry the user's pending
    // notice choice with a fresh event after reauthentication.
    buildNoticePendingEvent_ = "";
    buildNoticeLastSendAt_ = 0;
    backgroundBuildsSupported_ = message.indexOf("background_builds_v1") >= 0;
    jobControlsSupported_=message.indexOf("job_controls_v1")>=0;
    failedBuildResumeSupported_ =
        message.indexOf("failed_build_resume_v1") >= 0;
    repairCancelSupported_ = message.indexOf("repair_cancel_v1") >= 0;
    if (backgroundBuildsSupported_ || failedBuildResumeSupported_)
      requestBackgroundBuildJobs();
    backendServerTime_ = jsonIntField(message, "server_time");
    backendServerSeenAt_ = millis();
    const String mode = backendClient_?backendClient_->confirmedMode():String();
    if (mode == "chat") aiConversationMode_ = 1;
    else if (mode == "develop") aiConversationMode_ = 0;
    aiWorkflowText_ = backendClient_ && backendClient_->selectionPending()?(backendClient_->selectionUnclear()?"Valg uavklart. Velg app igjen":"Venter på appvalg"):"CONNECTED";
    return;
  }
  if (type == "session_snapshot") {
    backgroundBuildsSupported_ = message.indexOf("background_builds_v1") >= 0;
    jobControlsSupported_=message.indexOf("job_controls_v1")>=0;
    failedBuildResumeSupported_ =
        message.indexOf("failed_build_resume_v1") >= 0;
    repairCancelSupported_ = message.indexOf("repair_cancel_v1") >= 0;
    if (backgroundBuildsSupported_ || failedBuildResumeSupported_)
      requestBackgroundBuildJobs();
    backendServerTime_ = jsonIntField(message, "server_time");
    backendServerSeenAt_ = millis();
    const String mode = backendClient_?backendClient_->confirmedMode():String();
    if (mode == "chat") aiConversationMode_ = 1;
    else if (mode == "develop") aiConversationMode_ = 0;
    const String proposal = jsonStringField(message, "proposal_id");
    const String packageId = jsonStringField(message, "package_id");
    if (proposal.length() > 0) {aiProposalId_=proposal;aiProposalProjectId_=jsonStringField(message,"project_id");aiProposalJobId_=jsonStringField(message,"evolution_job_id");aiProposalAppName_=jsonStringField(message,"app_name");}
    if (packageId.length() > 0) aiPackageId_ = packageId;
    const String restoredState=jsonStringField(message,"state");
    if(packageId.length() && (restoredState=="ready_to_run" || restoredState=="installed")) {
      aiReadyPackageId_=packageId;aiWorkflowState_=5;aiWorkflowText_="App klar til kjøring";
    }
    if(restoredState=="building" || restoredState=="testing" || restoredState=="awaiting_install") {
      aiWorkflowState_=4;aiBuildProgress_=constrain(buildProgressField(message,aiBuildProgress_),0,100);
    }
    const String activity = jsonStringField(message, "activity");
    if (activity == "listening") {
      aiWorkflowState_ = fireConversationState(aiWorkflowState_,1);
      aiDeveloperMode_ = 1;
    } else if (activity == "processing") {
      aiWorkflowState_ = fireConversationState(aiWorkflowState_,2);
      aiDeveloperMode_ = 2;
    } else if (activity == "speaking") {
      aiDeveloperMode_ = 3;
      aiWorkflowState_ = fireConversationState(aiWorkflowState_,2);
    }
    const String display=jsonStringField(message,"display_text");
    aiWorkflowText_ = display.length()?display:
      (restoredState=="ready_to_run" || restoredState=="installed")?String("App klar til kjøring"):
      (restoredState=="building" || restoredState=="testing")?compactStatusText(jsonStringField(message,"phase")):String("Tilkoblet");
    if (backendClient_ && backendClient_->selectionPending()) aiWorkflowText_=backendClient_->selectionUnclear()?"Valg uavklart. Velg app igjen":"Venter på appvalg";
    return;
  }
  if (type == "app_inventory_request") {
    FireUiPhaseTimer timing("inventory_request");
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
  if (type == "app_repair_status") {
    handleLuaRepairStatus(message);
    return;
  }
  if (type == "build_progress" || type == "build_job_status" ||
      type == "build_resumed" || type == "build_backgrounded" ||
      type == "build_cancelled" || type == "build_ready_notice" ||
      type == "build_jobs" || type == "job_control_result" || type == "build_notice_closed") {
    handleBackgroundBuildMessage(message);
    return;
  }
  if (type=="app_backend_delete_ready") return; // The exact prepare-ACK owns this dialog.
  if (type == "app_backend_deleted") {
    cJSON* result=cJSON_Parse(message.c_str());applyBackendDeleteResult(result);cJSON_Delete(result);return;
  }
  if (type == "event_ack") {
    if(appManagerDeleteWaiting_ && appManagerDeleteRequest_.length() && jsonStringField(message,"event_id")==appManagerDeleteRequest_) {
      cJSON* reply=cJSON_Parse(message.c_str());const cJSON* result=cJSON_GetObjectItemCaseSensitive(reply,"result");
      const String status=aiJobText(reply,"status");
      if(appManagerDeleteId_.length()) {
        const bool applied=(status=="accepted" || status=="duplicate") && applyBackendDeleteResult(result);
        if(!applied) {appManagerDeleteWaiting_=false;appManagerDeleteRequest_=String();managerStatus_="Sletting ikke bekreftet. Velg på nytt.";}
        cJSON_Delete(reply);return;
      }
      const bool valid=(status=="accepted" || status=="duplicate") && aiJobText(result,"status")=="confirmation_required" &&
        managerTargetCurrent() && screen_==Screen::AppsSettings && backendClient_ &&
        backendClient_->connectionEpoch()==appManagerRequestEpoch_ && aiJobText(result,"project_id")==managerTarget_.projectId &&
        aiJobText(result,"app_id")==managerTarget_.appId && !cJSON_GetObjectItemCaseSensitive(result,"error");
      if(valid) {
        appManagerDeleteId_=aiJobText(result,"delete_id");appManagerDeleteProjectId_=aiJobText(result,"project_id");
        appManagerDeleteAppId_=aiJobText(result,"app_id");appManagerDeletePackageId_=aiJobText(result,"package_id");
        appManagerDeleteName_=managerTarget_.name;appManagerDeleteScope_=aiJobText(result,"delete_scope")=="version"?1:2;
        appManagerDeleteMode_=2;appManagerDeleteConfirm_=appManagerDeleteId_.length()>0;appManagerActionMenu_=false;
        managerStatus_="Bekreft sletting";
      } else managerStatus_="Sletting kunne ikke forberedes";
      appManagerDeleteWaiting_=false;appManagerDeleteRequest_=String();cJSON_Delete(reply);return;
    }
    if (buildNoticePendingEvent_.length() && jsonStringField(message,"event_id")==buildNoticePendingEvent_) handleBackgroundBuildMessage(message);
    redrawRequested_ = true;
    return;
  }
  if (type == "assistant_message" || type == "transcript") {
    const String text = jsonStringField(message, "text");
    String display=jsonStringField(message,"display_text");
    if(!display.length()) display=type=="transcript"?String("Tale mottatt"):compactStatusText(text);
    if (type == "transcript") {
      aiTranscriptText_ = text;
      aiAssistantText_ = display;
    } else {
      aiAssistantText_ = display;
    }
    if (type == "assistant_message") {
      // A completed answer returns to the conversational idle state so B can
      // start another turn and add context before the user builds.
      aiDeveloperMode_ = 3;
      aiWorkflowState_ = fireConversationState(aiWorkflowState_,0);
      if(aiWorkflowState_<3) aiWorkflowText_ = "Svar mottatt";
    } else {
      aiDeveloperMode_ = 2;
      aiWorkflowState_ = fireConversationState(aiWorkflowState_,2);
      if(aiWorkflowState_<3) aiWorkflowText_ = "Tale mottatt – vurderer";
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
    if(jsonStringField(message,"event")=="runtime_ai_policy") {
      const String mode=jsonStringField(message,"mode");
      if(mode=="auto" || mode=="off") {
        const bool selected=mode=="auto";if(aiRuntimeAuto_!=selected) preferences.putBool("runtime_ai_auto",selected);
        aiRuntimeAuto_=selected;aiRuntimeModeAcked_=true;
        if(backendClient_) backendClient_->setRuntimeAiMode(mode,false);
      }
      runtimeAiEnabled_=jsonBoolField(message,"enabled",runtimeAiEnabled_);
      if(!runtimeAiEnabled_) for(LuaHardwareJob& job:luaJobs_) if(job.kind==LuaJobKind::RuntimeAi && job.state==0)
        cancelLuaRuntimeAi(job,"disabled");
      return;
    }
    String state = jsonStringField(message, "state");
    if (state.length() == 0) state = jsonStringField(message, "activity");
    if (state == "listening") {
      aiWorkflowState_ = fireConversationState(aiWorkflowState_,1);
      aiDeveloperMode_ = 1;
    } else if (state == "processing" || state == "thinking") {
      aiWorkflowState_ = fireConversationState(aiWorkflowState_,2);
      aiDeveloperMode_ = 2;
    } else if (state == "speaking") {
      aiDeveloperMode_ = 3;
    } else if(state=="building" || state=="testing" || state=="awaiting_install") {
      aiWorkflowState_=4;aiDeveloperMode_=2;
    } else if((state=="ready_to_run" || state=="installed") && aiReadyPackageId_.length()) {
      aiWorkflowState_=5;aiBuildProgress_=100;
    }
    if(aiWorkflowState_<3 || state=="building" || state=="testing" || state=="awaiting_install" ||
       state=="ready_to_run" || state=="installed") aiWorkflowText_ = compactStatusText(state);
    return;
  }
  if (type == "build_proposal") {
    aiReadyPackageId_=String();
    aiProposalId_ = jsonStringField(message, "proposal_id");
    aiProposalProjectId_=jsonStringField(message,"project_id");aiProposalJobId_=jsonStringField(message,"evolution_job_id");aiProposalAppName_=jsonStringField(message,"app_name");
    const String summary = jsonStringField(message, "summary");
    const String project=jsonStringField(message,"project_id");
    if (project.length()) aiProjectId_=project;
    if (project.length() && summary.length() && summary.length()<=1000) {
      aiEvolutionGoalProject_=project;aiEvolutionGoal_=summary;
      aiDevelopmentContext_=jsonStringField(message,"context_id");
    }
    const String display=jsonStringField(message,"display_text");
    aiAssistantText_ = display.length()?display:compactStatusText(summary.length()?summary:aiBuildErrorStatus_);
    aiWorkflowState_ = aiProposalId_.length() > 0 ? 3 : 0;
    aiDeveloperMode_ = 2;
    aiWorkflowText_ = aiBuildResumePending_
                          ? (aiBuildErrorStatus_.length() > 0
                                 ? compactStatusText(aiBuildErrorStatus_)
                                 : "READY TO RETRY")
                          : "READY TO BUILD";
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
    aiWorkflowState_ = fireConversationState(aiWorkflowState_,2);
    if(aiWorkflowState_<3) aiWorkflowText_ = "Spiller av svar";
    return;
  }
  if (type == "firmware_store_request") {
    const String transfer = jsonStringField(message, "transfer_id");
    const String firmware = jsonStringField(message, "firmware_id");
    if (backendClient_ && transfer.length() && firmware.length())
      backendClient_->firmwareStoreResult(transfer, firmware, false, "", "unsupported", "Use the device signed GitHub catalog");
    firmwareMessage_ = "Firmware hentes direkte fra GitHub";
    redrawRequested_ = true;
    return;
  }
  if (type == "package_ready") {
    invalidateBackendCatalog();
    aiPackageId_ = jsonStringField(message, "package_id");
    aiReadyPackageId_=aiPackageId_;
    const String projectId = jsonStringField(message, "project_id");
    if(projectId.length()) aiProjectId_=projectId;
    aiWorkflowText_ = "PACKAGE READY";
    return;
  }
  if (type == "install_request") {
    const String requestedBy=jsonStringField(message,"request_event_id");
    const String packageId = jsonStringField(message, "package_id");
    const String installId = jsonStringField(message, "install_id");
    const String url = jsonStringField(message, "download_url");
    const String hash = jsonStringField(message, "archive_sha256");
    const String projectId = jsonStringField(message, "project_id");
    const uint32_t size = static_cast<uint32_t>(jsonIntField(message, "size_bytes"));
    const String commandBoot = jsonStringField(message, "boot_id");
    const uint32_t expiresAt = static_cast<uint32_t>(jsonIntField(message, "expires_at"));
    if (backendClient_ && commandBoot.length() > 0 &&
        commandBoot != backendClient_->bootId()) {
      backendClient_->deviceInstallResult(installId, packageId, false,
                                           hash, "stale boot_id");
      aiWorkflowText_ = "DOWNLOAD REJECTED";
      return;
    }
    if (!backendCommandUnexpired(expiresAt)) {
      if (backendClient_) backendClient_->deviceInstallResult(
          installId, packageId, false, hash, "expired install command");
      aiWorkflowText_ = "DOWNLOAD EXPIRED";
      return;
    }
    if (packageManager_ && packageManager_->matchesInstall(packageId,installId,hash,size)) return;
    if (requestedBy.length() && (downloadPhase_!=1 || requestedBy!=downloadRequest_ || packageId!=downloadPackage_ ||
        projectId!=downloadProject_ || !backendClient_ || backendClient_->sessionId()!=downloadSession_ || commandBoot!=downloadBoot_)) {
      if (backendClient_) backendClient_->deviceInstallResult(installId,packageId,false,hash,"Download intent cancelled or stale");
      return;
    }
    if (packageManager_ && packageManager_->busy()) {
      // Replay of the SAME command must not turn an in-flight installation
      // into a failed receipt. A different command cannot replace its identity.
      if (!packageManager_->matchesInstall(packageId, installId, hash, size) && backendClient_)
        backendClient_->deviceInstallResult(installId, packageId, false, hash, "installer busy");
      return;
    }
    const bool accepted = !firmwareBusy() && packageManager_ && packageManager_->startDownload(
        backendHost_, backendPort_, backendToken_, url, packageId, installId,
        hash, size,projectId,backendClient_?backendClient_->sessionId():String(),commandBoot,expiresAt);
    if (accepted) {
      if (requestedBy.length()) downloadPhase_=2;
      aiPackageId_ = packageId;aiInstallId_ = installId;invalidateLuaApps();
    }
    if (!accepted && requestedBy.length()) {cancelAppDownload();downloadIntentStatus("Nedlasting avvist");}
    if (!accepted && backendClient_)
      backendClient_->deviceInstallResult(installId, packageId, false,
                                          hash, "download rejected");
    aiWorkflowText_ = accepted ? "DOWNLOADING" : "DOWNLOAD REJECTED";
    return;
  }
  if (type == "run_request") {
    const String runId = jsonStringField(message, "run_id");
    const String packageId = jsonStringField(message, "package_id");
    const String commandBoot = jsonStringField(message, "boot_id");
    const String commandHash = jsonStringField(message, "archive_sha256");
    const String commandSource = jsonStringField(message,"source_sha256");
    const uint32_t expiresAt = static_cast<uint32_t>(jsonIntField(message, "expires_at"));
    if (runId.length() == 0 || packageId.length() == 0 ||
        !backendClient_ || commandBoot!=backendClient_->bootId()) {
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
    fire_run_receipts::Entry* receipt=nullptr;
    const auto admission=luaRunReceipts_.admit(runId.c_str(),packageId.c_str(),commandSource.c_str(),commandHash.c_str(),
      expiresAt,backendCommandNow(),commandBoot==backendClient_->bootId(),receipt);
    if(admission==fire_run_receipts::Admission::Busy || admission==fire_run_receipts::Admission::Invalid) {
      backendClient_->appFailed(runId,packageId,
        admission==fire_run_receipts::Admission::Busy?"command_busy":"invalid_command",
        admission==fire_run_receipts::Admission::Busy?"Unexpired command receipts are full":"Invalid command identity");
      return;
    }
    if(admission==fire_run_receipts::Admission::Duplicate) {
      const bool started=receipt->state==fire_run_receipts::State::Started || receipt->state==fire_run_receipts::State::Healthy;
      if(started && luaAppActive_ && luaRuntime_ && luaRuntime_->running() && luaRunId_==runId &&
         luaPackageId_==packageId && luaSourceHash_==commandSource) backendClient_->appStarted(runId,packageId,luaSourceHash_);
      else backendClient_->appFailed(runId,packageId,"previous_failure","Run command was already consumed");
      return;
    }
    String path;
    if((packageManager_ && packageManager_->busy()) || !resolveLuaPackage(packageId,commandHash,commandSource,path)) {
      receipt->state=fire_run_receipts::State::Failed;
      const String code=packageManager_ && packageManager_->busy()?String("command_busy"):
        luaAppError_=="metadata_error"?String("metadata_error"):
        luaAppError_=="archive_mismatch"?String("archive_mismatch"):String("not_installed");
      backendClient_->appFailed(runId,packageId,code,code=="not_installed"?"Package is not installed on FIRE":code);
      aiWorkflowText_="Appstart avvist";return;
    }
    aiPackageId_=packageId;
    if(luaAppActive_ && luaRuntime_ && luaRuntime_->running() && luaPackageId_==packageId &&
       luaAppPath_==path && validSha256Hex(commandSource) && luaSourceHash_==commandSource) {
      // The real local VM is already executing these exact verified bytes.
      // Bind the normal authorized command without resetting measurements/UI.
      luaRunId_=runId;luaHealthySent_=false;luaAiBindPackageId_=String();luaAiBindSent_=false;
      luaDataStore_.bindRun(runId);
      evolution_.bindRun(runId,millis());
      receipt->state=fire_run_receipts::State::Started;
      if(backendClient_) backendClient_->appStarted(runId,packageId,luaSourceHash_,luaDiagnosticsJson("start"));
      redrawRequested_=true;return;
    }
    if (path.length() > 0 &&
        startLuaApp(path, sdBaseName(path), packageId,commandSource)) {
      luaRunId_ = runId;
      luaDataStore_.bindRun(runId);
      evolution_.bindRun(runId,millis());
      luaPackageId_ = packageId;
      luaAiBindPackageId_=String();luaAiBindSent_=false;
      luaHealthySent_ = false;
      aiWorkflowState_ = 6;
      aiDeveloperMode_ = 3;
      aiWorkflowText_ = "RUNNING";
      if (packageId == luaRepairReadyPackageId_) {
        luaRepairStatus_ = "running";
        luaRepairPhase_ = "running";
        luaRepairMessage_ = "Fixed app running";
      }
      receipt->state=fire_run_receipts::State::Started;
      if (backendClient_)
        backendClient_->appStarted(runId, packageId, luaSourceHash_,
                                   luaDiagnosticsJson("start"));
    } else {
      receipt->state=fire_run_receipts::State::Failed;
      const String failure = path.length() > 0 && luaAppError_.length() > 0
                                 ? luaAppError_
                                 : String("Package is not installed on FIRE");
      const String errorCode = luaAppError_=="metadata_error"?String("metadata_error"):
                               path.length() > 0 && luaAppError_.startsWith("Lua init")
                                   ? "init_error"
                                   : path.length() > 0 && luaAppError_.startsWith("Lua syntax")
                                         ? "load_error"
                                         : "not_installed";
      if (backendClient_)
        backendClient_->appFailed(runId, packageId, errorCode, failure);
      if (packageId == luaRepairReadyPackageId_) {
        luaRepairStatus_ = "failed";
        luaRepairPhase_ = "failed";
        luaRepairMessage_ = failure;
      }
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
    const String rollbackId=jsonStringField(message,"rollback_id"),packageId=jsonStringField(message,"package_id");
    const String commandBoot=jsonStringField(message,"boot_id");
    const uint32_t expiresAt=static_cast<uint32_t>(jsonIntField(message,"expires_at"));
    const bool bootOk=backendClient_ && commandBoot==backendClient_->bootId() && backendCommandUnexpired(expiresAt);
    const bool available=bootOk && rollbackLuaPackage(packageId,jsonStringField(message,"archive_sha256"),jsonStringField(message,"source_sha256"));
    if(available) {invalidateLuaApps();scanLuaApps();}
    if(backendClient_) backendClient_->rollbackResult(rollbackId,packageId,available,
      available?"Previous package identity/source verified; appdata preserved":"Validated package is not available or metadata_error");
    aiWorkflowState_=available?5:0;aiWorkflowText_=available?"ROLLBACK READY":"ROLLBACK FAILED";return;
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
    aiWorkflowText_ = jsonStringField(message, "display_text");
    if(!aiWorkflowText_.length()) aiWorkflowText_=compactStatusText(jsonStringField(message,"message"));
    if (aiWorkflowText_.length() == 0) aiWorkflowText_ = "BACKEND ERROR";
  }
}

bool FireOS::runningSdkLuaApp() const {
  return luaAppActive_ && luaRuntime_ && luaRuntime_->running() && luaRuntime_->appSdkEnabled();
}

bool FireOS::fullLuaCanvas() const {
  if (!uiCanvas || !ui.getBuffer()) return false;
  int32_t x,y,w,h;ui.getClipRect(&x,&y,&w,&h);
  return ui.width()==320 && ui.height()==240 && ui.getRotation()==0 &&
    unsigned(ui.getColorDepth())==16 && ui.bufferLength()==153600 &&
    !(reinterpret_cast<uintptr_t>(ui.getBuffer())&1u) && x==0 && y==0 && w==320 && h==240;
}

void FireOS::luaDisplayPaint(void* context) {
  auto* os=static_cast<FireOS*>(context);
  if (os) os->luaSdkFrame_.paint();
}

void FireOS::luaDisplayClear(void* context, int color) {
  auto* os = static_cast<FireOS*>(context);
  if (os) os->luaSdkFrame_.clear(ui,static_cast<uint16_t>(color),
    os->luaRuntime_ && os->luaRuntime_->appSdkEnabled(),os->fullLuaCanvas());
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
  fire_app_graphics::indexedGrid(ui,x,y,cellWidth,cellHeight,columns,rows,
    cells,cellCount,palette,paletteCount);
}

bool FireOS::luaDisplayTextStyle(void*,int x,int y,const char* text,size_t length,
                                int color,const char* id,int align,int width) {
  const auto* font=fire_app_bitmap::find(FireSdkData::kFonts,FireSdkData::kFontCount,id);
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  return font && fire_app_bitmap::text(surface,*font,x,y,text,length,uint16_t(color),align,width);
}
bool FireOS::luaDisplayMeasureText(void*,const char* text,size_t length,const char* id,int* w,int* h) {
  const auto* font=fire_app_bitmap::find(FireSdkData::kFonts,FireSdkData::kFontCount,id);
  return font && w && h && fire_app_bitmap::measure(*font,text,length,*w,*h);
}
bool FireOS::luaDisplayAsset(void*,int x,int y,const char* id,int scale,int tint,bool flipX,bool flipY) {
  const auto* entry=fire_app_bitmap::find(FireSdkData::kAssets,FireSdkData::kAssetCount,id);
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  return entry && fire_app_bitmap::asset(surface,*entry,x,y,scale,tint,flipX,flipY);
}
void FireOS::luaDisplayRoundRect(void*,int x,int y,int w,int h,int r,int color,bool filled) {
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  fire_app_graphics::roundRect(surface,x,y,w,h,r,uint16_t(color),filled);
}
void FireOS::luaDisplayTriangle(void* ctx,int x1,int y1,int x2,int y2,int x3,int y3,int color,bool filled) {
  const int16_t points[]={int16_t(x1),int16_t(y1),int16_t(x2),int16_t(y2),int16_t(x3),int16_t(y3)};
  luaDisplayPolyline(ctx,points,3,color,true,filled);
}
void FireOS::luaDisplayPolyline(void*,const int16_t* values,size_t count,int color,bool closed,bool filled) {
  if (!values || count<2 || count>64) return;
  if (filled) {
    if (count>fire_app_graphics::kMaxPolygonPoints) return;
    fire_app_graphics::Point points[fire_app_graphics::kMaxPolygonPoints];
    for (size_t i=0;i<count;++i) points[i]={values[i*2],values[i*2+1]};
    fire_canvas_fill::Surface<M5Canvas> surface(ui);
    fire_app_graphics::polygon(surface,points,count,uint16_t(color));
  } else {
    for (size_t i=1;i<count;++i) ui.drawLine(values[(i-1)*2],values[(i-1)*2+1],values[i*2],values[i*2+1],color);
    if (closed) ui.drawLine(values[(count-1)*2],values[(count-1)*2+1],values[0],values[1],color);
  }
}
void FireOS::luaDisplayGradient(void*,int x,int y,int w,int h,int a,int b,bool vertical) {
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  fire_app_graphics::gradient(surface,x,y,w,h,uint16_t(a),uint16_t(b),vertical);
}
void FireOS::luaDisplayArc(void*,int x,int y,int radius,int start,int end,int color,int thickness) {
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  fire_app_graphics::arc(surface,x,y,radius,start,end,uint16_t(color),thickness);
}

bool FireOS::luaButtonPressed(void* context, const char* button) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || !button || strlen(button) != 1) return false;
  const uint8_t index = button[0] == 'A' ? 0 : button[0] == 'B' ? 1 : 2;
  return os->buttons_[index].down();
}

void FireOS::luaRgbSet(void* context, int index, int red, int green,
                       int blue) {
  auto* os = static_cast<FireOS*>(context);
  if (!os || index < 0 || index >= 10) return;
  os->luaRgbValues_[index][0] = static_cast<uint8_t>(red);
  os->luaRgbValues_[index][1] = static_cast<uint8_t>(green);
  os->luaRgbValues_[index][2] = static_cast<uint8_t>(blue);
  os->luaRgbDirty_ = true;
  os->luaRgbDirtyAt_ = millis();
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
  constexpr uint8_t kCount = 4;
  if (index == 0) {
    detailIndex_ = (detailIndex_ + kCount - 1) % kCount;
  } else if (index == 2) {
    detailIndex_ = (detailIndex_ + 1) % kCount;
  } else if (detailIndex_ == 0) {
    cycleBackendMode();
  } else if (detailIndex_ == 1) {
    startAiApiSetup();
  } else if (detailIndex_ == 3) {
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
      if (!requestLuaAppOpen(luaAppPaths_[luaIndex],luaAppNames_[luaIndex],luaAppPackageIds_[luaIndex])) {
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
    if (downloadPhase_==1 || downloadPhase_==2 || (packageManager_ && packageManager_->busy())) {if(index==2) cancelAppDownload();return;}
    if (appManagerDeleteWaiting_) {if(index==2) {appManagerDeleteWaiting_=false;appManagerDeleteRequest_=String();managerStatus_="Avbrutt";}return;}
    if (appManagerVersionsWaiting_) {if(index==2) {appManagerVersionsWaiting_=false;appManagerRequest_=String();managerStatus_="Avbrutt";}return;}
    if ((appManagerActionMenu_ || appManagerDeleteConfirm_ || appManagerDevelopConfirm_ || appManagerVersionDialog_) && !managerTargetCurrent()) {
      invalidateManagerTarget();return;
    }
    if (appManagerDevelopConfirm_) {
      const uint8_t action=appManagerDevelopConfirm_;appManagerDevelopConfirm_=0;
      if (index!=1 || !managerTargetCurrent()) return;
      const ManagerItem& item=managerTarget_;
      const String path=item.localPath,name=item.name,package=item.localPackageId;
      if (!startLuaApp(path,name,package)) {managerStatus_=luaAppError_;return;}
      const char* error=nullptr;
      if (!queueDataDevelop(action==7?"update":action==8?"fork":"feedback","",true,&error))
        managerStatus_=error?error:"Forbedring utilgjengelig";
      return;
    }
    if (appManagerVersionDialog_) {
      const uint8_t itemCount = appManagerVersionCount_ + 1;
      if (index == 0)
        appManagerVersionSelection_ =
            (appManagerVersionSelection_ + itemCount - 1) % itemCount;
      else if (index == 2)
        appManagerVersionSelection_ =
            (appManagerVersionSelection_ + 1) % itemCount;
      else if (appManagerVersionSelection_ == appManagerVersionCount_) {
        appManagerVersionDialog_ = false;appManagerRequest_=String();appManagerVersionsWaiting_=false;
      } else if (appManagerVersionDownloadable_[appManagerVersionSelection_]) {
        const String packageId =
            appManagerVersionPackageIds_[appManagerVersionSelection_];
        if (requestAppDownload(appManagerVersionProjectId_,packageId,appManagerVersionAppId_)) {
          appManagerVersionDialog_ = false;appManagerRequest_=String();appManagerVersionsWaiting_=false;
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
      if (appManagerVersionSelection_ >= appManagerVersionOffset_ + 5)
        appManagerVersionOffset_ = appManagerVersionSelection_ - 4;
      return;
    }
    if (appManagerDeleteConfirm_) {
      if (index == 0 || index == 2) {
        appManagerDeleteConfirm_ = false;
        appManagerDeleteMode_ = 0;
      } else if (index == 1 && appManagerDeleteMode_ == 1) {
        if (managerTargetCurrent()) {
          const ManagerItem& item = managerTarget_;
          bool deleted = false;
          if (item.kind == 1) deleted = deleteLuaApp(item.localPath);
          else if (item.kind == 0) deleted = deleteExternalApp(item.localPath);
          managerStatus_ = deleted ? "Local app deleted" : "Local delete failed";
          appManagerDeleteConfirm_ = false;
          appManagerDeleteMode_ = 0;
          scanExternalApps();
          rebuildAppManagerItems();
          sendAppInventory();
          invalidateBackendCatalog();
        }
      } else if (index == 1 && appManagerDeleteMode_ == 2) {
        appManagerDeleteRequest_="del-confirm-"+String(esp_random(),HEX);
        appManagerRequestAt_=millis();appManagerRequestEpoch_=backendClient_?backendClient_->connectionEpoch():0;
        if (backendClient_ && backendClient_->appBackendDeleteConfirm(appManagerDeleteId_,appManagerDeleteRequest_)) {
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
        if (!managerTargetCurrent()) return;
        const ManagerItem& item = managerTarget_;
        if (action == 1) {
          if (item.kind == 1)
            requestLuaAppOpen(item.localPath,item.name,item.localPackageId);
          else if (item.kind == 0)
            installExternalApp(item.localPath, true, false);
        } else if (action == 11) {
          bool suppressed=false;for(uint8_t i=0;i<luaAppCount_;++i) if(luaAppIds_[i]==item.appId && updatePrefsOwner_==backendDeviceId_) suppressed=luaUpdateSuppressed_[i];
          managerStatus_=saveAppUpdatePreference(item.appId,!suppressed)?"Oppdateringsvalg lagret":"Valget kunne ikke lagres";
        } else if (action == 10) {
          openEvolution();
        } else if (action == 2) {
          requestSelectedAppVersions();
        } else if (action==7 || action==8 || action==9) {
          if (luaAppActive_ && luaPackageId_==item.localPackageId) {
            const char* error=nullptr;
            if (!queueDataDevelop(action==7?"update":action==8?"fork":"feedback","",true,&error)) {
              managerStatus_=error?error:"Forbedring utilgjengelig";
            }
          } else appManagerDevelopConfirm_=action;
        } else if (action == 3) {
          appManagerDeleteMode_ = 1;
          appManagerDeleteConfirm_ = true;
        } else if (action == 4) {
          appManagerDeleteId_=String();
          appManagerDeleteRequest_="del-"+String(esp_random(),HEX)+"-"+String(esp_random(),HEX);
          appManagerRequestAt_=millis();appManagerRequestEpoch_=backendClient_?backendClient_->connectionEpoch():0;
          if (backendClient_ && backendClient_->appBackendDeletePrepare(
                                    item.projectId, item.appId, "all",String(),appManagerDeleteRequest_)) {
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
    if (index==0 || index==2) detailIndex_=(detailIndex_+4+(index==0?-1:1))%4;
    else if (detailIndex_==3) back();
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
            luaBluetooth_.reset();
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
  FireUiPhaseTimer timing("wifi_prepare");
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
  wifiBeginAt_ = millis();
  wifiConnectActive_ = true;
  wifiOperationStarted_ = millis();
  wifiStatus_ = "Connecting to " + wifiSsid_;
}

void FireOS::updateWifiState() {
  if (wifiBeginAt_ && millis() - wifiBeginAt_ >= 75) {
    wifiBeginAt_ = 0;
    if (wifiEnabled_ && wifiMode_ != 2) {
      FireUiPhaseTimer timing("wifi_begin");
      WiFi.begin(wifiSsid_.c_str(), wifiPassword_.c_str());
    }
  }
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
      if (backendBootPending_ && wifiMode_ == 0) {
        backendBootPending_ = false;
        backendBootAttempted_ = true;
      }
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
  if (millis() - timeSyncStarted_ >= 45000) {
    timeSyncPending_ = false;
    timeSyncConfigured_ = false;
    timeSyncStatus_ = "Time sync timed out";
    return;
  }
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
      backendBootPending_ = false;
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
      backendBootPending_ = false;
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
        // Keep Wi-Fi available for independent backend/Home discovery.
      }
    }
  } else if (millis() - timeSyncStarted_ > 15000) {
    timeSyncStatus_ = "Connect to Wi-Fi for time sync";
    timeSyncPending_ = false;
    timeSyncConfigured_ = false;
    backendBootPending_ = false;
  }
}

void FireOS::startWifiSetup() {
  char secret[33]; for (uint8_t i = 0; i < 4; ++i) snprintf(secret + i * 8, 9, "%08lx", (unsigned long)esp_random());
  wifiSetupToken_ = secret; wifiSetupPassword_ = "fire-" + wifiSetupToken_.substring(0, 12);
  aiApiSetupActive_ = false;

  WiFi.setHostname("M5Stack-FIRE");
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAPsetHostname("M5Stack-FIRE");
  WiFi.softAP("FIRE-Setup", wifiSetupPassword_.c_str());
  wifiSetupActive_ = setupPortal_.open(false, wifiSetupToken_, homeApp_.setupPage());
  portalCloseAt_ = 0; portalReconnect_ = false;
  if (!wifiSetupActive_) { WiFi.softAPdisconnect(true); wifiStatus_ = "Kunne ikke starte oppsett"; return; }
  wifiSetupStartedAt_ = millis();
  wifiStatus_ = "FIRE-Setup " + WiFi.softAPIP().toString();
}

void FireOS::startAiApiSetup() {
  if (wifiSetupActive_) stopWifiSetup();
  char secret[33]; for (uint8_t i = 0; i < 4; ++i) snprintf(secret + i * 8, 9, "%08lx", (unsigned long)esp_random());
  wifiSetupToken_ = secret; wifiSetupPassword_ = "fire-" + wifiSetupToken_.substring(0, 12);
  aiApiSetupActive_ = true;
  WiFi.setHostname("M5Stack-FIRE");
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAPsetHostname("M5Stack-FIRE");
  WiFi.softAP("FIRE-Setup", wifiSetupPassword_.c_str());
  wifiSetupActive_ = setupPortal_.open(true, wifiSetupToken_, homeApp_.setupPage());
  portalCloseAt_ = 0; portalReconnect_ = false;
  if (!wifiSetupActive_) { WiFi.softAPdisconnect(true); wifiStatus_ = "Kunne ikke starte oppsett"; return; }
  wifiSetupStartedAt_ = millis();
}

void FireOS::stopWifiSetup() {
  if (!wifiSetupActive_) return;
  if (portalApplying_) { portalCloseAt_ = millis(); return; }
  setupPortal_.close();
  portalCloseAt_ = 0; portalReconnect_ = false;
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
  if (portalApplying_) { portalReconnect_ = true; stopWifiSetup(); return; }
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
  if (!port.length() && host.length() && host != backendHost_ && fireNetworkTls(host, 0)) nextPort = 443;
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
  if (!fireNetworkEndpointValid(nextHost) || !validText(nextToken, 128, false) ||
      nextToken.length() < 24 || !validDeviceId(nextDevice))
    return false;

  // Commit all four values together only after every field is valid.
  const bool changed=backendHost_!=nextHost || backendPort_!=nextPort || backendToken_!=nextToken || backendDeviceId_!=nextDevice;
  const auto persisted=[&](const String& h,uint16_t p,const String& t,const String& d) {
    const bool wrote=preferences.putString("backend_host",h)==h.length() && preferences.putUShort("backend_port",p)==sizeof(uint16_t) &&
      preferences.putString("backend_token",t)==t.length() && preferences.putString("backend_device",d)==d.length();
    return wrote && preferences.getString("backend_host","")==h && preferences.getUShort("backend_port",0)==p &&
      preferences.getString("backend_token","")==t && preferences.getString("backend_device","")==d;
  };
  if(!persisted(nextHost,static_cast<uint16_t>(nextPort),nextToken,nextDevice)) {
    // Restore the previous scoped values; never publish an unverified new config.
    preferences.putString("backend_host",backendHost_);preferences.putUShort("backend_port",backendPort_);
    preferences.putString("backend_token",backendToken_);preferences.putString("backend_device",backendDeviceId_);
    backendStatus_="Oppsett kunne ikke lagres";redrawRequested_=true;return false;
  }
  backendHost_ = nextHost;
  backendPort_ = static_cast<uint16_t>(nextPort);
  backendToken_ = nextToken;
  backendDeviceId_ = nextDevice;
  if (changed) clearBackendCatalog();
  aiApiKey_ = "";
  preferences.remove("openai_key");

  if (backendClient_) {
    reverseTransport_.configure(backendDeviceId_, backendToken_);
    backendClient_->configure(backendHost_, backendPort_, backendToken_,
                              backendDeviceId_, kFirmwareVersion);
    backendStatus_ = backendClient_->status();
  }
  if (wifiMode_ != 2 && backendMode_ != 2 && backendHost_.length() > 0 &&
      backendToken_.length() >= 24) {
    // Backend configuration is an explicit app dependency. Auto mode may
    // keep Wi-Fi off at boot, so request it when the backend is configured.
    if (portalApplying_) portalReconnect_ = true; else requestWifi(true);
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
    luaBluetooth_.reset();
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
            luaBluetooth_.reset();
            NimBLEDevice::deinit(true);
            bluetoothRadioReady = false;
          }
#endif
        }
        saveSettings();
        break;
      case 4:
        cycleBackendMode();
        break;
      case 5:
        open(Screen::FileExplorer);
        break;
      case 6:
        powerActionIndex_ = 0;
        open(Screen::PowerActions);
        break;
      case 7:
        open(Screen::Settings);
        break;
      case 8:
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
    displayPowerState_ = 2;fire_button_capture::sleeping(true);
  } else if (dimMs > 0 && idleMs >= dimMs && displayPowerState_ == 0) {
    M5.Display.setBrightness(max<uint8_t>(8, brightness_ / 3));
    displayPowerState_ = 1;fire_button_capture::sleeping(true);
  }
}

void FireOS::wakeDisplay() {
  lastActivity_ = millis();
  displayPowerState_ = 0;
  fire_button_capture::sleeping(false);
  M5.Display.setBrightness(brightness_);
}

void FireOS::enterLightSleep() {
  if (digitalRead(kButtonPins[0]) == LOW || digitalRead(kButtonPins[1]) == LOW ||
      digitalRead(kButtonPins[2]) == LOW) {
    return;
  }
  M5.Display.setBrightness(0);
  displayPowerState_ = 2;fire_button_capture::sleeping(true);fire_button_capture::pause();
  for (const uint8_t pin : kButtonPins) {
    gpio_wakeup_enable(static_cast<gpio_num_t>(pin), GPIO_INTR_LOW_LEVEL);
  }
  esp_sleep_enable_gpio_wakeup();
  esp_light_sleep_start();
  esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_GPIO);
  for(const uint8_t pin:kButtonPins) gpio_wakeup_disable(static_cast<gpio_num_t>(pin));
  wakeDisplay();beginButtonCapture();
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
  backendMode_ = 0;
  backendBootPending_ = false;
  backendBootAttempted_ = false;
  backendBootSyncWaiting_ = false;
  backendBootJobsReceived_ = false;
  backendBootSyncStartedAt_ = 0;
  buildJobsRetryCount_ = 0;
  buildJobsRequestAt_ = 0;
  luaRepairId_ = "";
  luaRepairProjectId_ = "";
  luaRepairProposalId_ = "";
  luaRepairReadyPackageId_ = "";
  luaRepairReadyVersion_ = "";
  luaRepairStatus_ = "";
  luaRepairPhase_ = "";
  luaRepairMessage_ = "";
  luaRepairRequested_ = false;
  luaRepairPrepareSent_ = false;
  luaRepairCancelPending_ = false;
  if (backendClient_ && backendClient_->active()) backendClient_->disconnect();
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
  if (screen_ == Screen::FileExplorer && sdImagePreview_ && sdImageRendered_ &&
      !buildNoticeActive_) {
    inputPresentationPending_=false; // unchanged image preview: no new presentation sample
    return;
  }
  const int64_t drawStartedUs=esp_timer_get_time();
  // An active SDK view prepares its whole canvas in drawLuaApp. Do not
  // first paint another full background here; legacy/non-app paths stay as-is.
  const bool sdkAppView=screen_==Screen::LuaApp ||
    (screen_==Screen::QuickSettings && previousScreen_==Screen::LuaApp);
  if (screen_!=Screen::QuickSettings && !(sdkAppView && runningSdkLuaApp() && fullLuaCanvas())) ui.fillSprite(kBg);
  if (screen_ == Screen::QuickSettings) {
    if(previousScreen_==Screen::LuaApp && luaAppActive_) drawScreen(previousScreen_);
    drawQuickSettings();
  } else {
    drawScreen(screen_);
  }
  if (buildNoticeActive_) drawBuildNoticeOverlay();
  if (fire_app_updates::active(appUpdateStage_,screen_==Screen::QuickSettings)) drawAppUpdatePrompt();
  const int64_t presentStartedUs=esp_timer_get_time();
  if (screen_!=Screen::LuaApp) maxUiRenderUs_=max(maxUiRenderUs_,uint32_t(presentStartedUs-drawStartedUs));
  ui.pushSprite(0, 0);
  maxUiPresentUs_=max(maxUiPresentUs_,uint32_t(esp_timer_get_time()-presentStartedUs));
  publishButtonView();
  if (screen_ == Screen::FileExplorer && sdImagePreview_ && !buildNoticeActive_) {
    M5.Display.fillRect(0, 28, 320, 188, kBg);
    bool drawn = false;
    if (!sdImageBuffer_ || sdImageBufferSize_ == 0) {
      M5.Display.setTextColor(kOrange, kBg);
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
      M5.Display.setTextColor(kOrange, kBg);
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
    case Screen::Home:
      homeApp_.draw(ui);
      ui.setFont(nullptr);
      break;
    case Screen::Evolution:
      drawEvolution();
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
  ui.setTextDatum(TL_DATUM);
  ui.fillRect(0, 0, 320, 28, kBg);
  ui.drawFastHLine(10, 27, 300, FireUI::Border);
  const String statusDateTime = dateTime_.statusDateTime();
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  FireUI::text(surface, 10, 7, statusDateTime.substring(0, 5).c_str(), kText, "ui12b", 48);
  FireUI::text(surface, 72, 7, statusDateTime.substring(8).c_str(), kMuted, "ui12", 138, 1);
  const uint8_t wifiState = WiFi.status() == WL_CONNECTED
                                ? 2
                                : (wifiConnectActive_ || wifiScanActive_ ||
                                   wifiSetupActive_)
                                      ? 1
                                      : 0;
  const bool backendConnected = backendClient_ &&
                                backendClient_->sessionReady();
  const bool backendWorking = !backendConnected && backendClient_ &&
                              backendClient_->configured() && !backendClient_->sessionRejected() &&
                              backendMode_ != 2 && wifiMode_ != 2 &&
                              ((packageManager_ && packageManager_->networkPaused()) || backendClient_->active() || backendBootPending_ ||
                               (backendMode_ == 1 &&
                                WiFi.status() == WL_CONNECTED));
  drawBackendIcon(232, 5, backendConnected ? 2 : backendWorking ? 1 : 0);
  drawWifiIcon(252, 6, wifiState);
  bool bluetoothConnected = bluetoothConnected_;
#ifdef FIRE_OS_BLE
  bluetoothConnected = bluetoothConnected || bluetoothPeripheralConnected;
#endif
  const uint8_t bluetoothState =
      bluetoothConnected
          ? 2
          : (bluetoothScanInProgress_ || bluetoothBootInitPending_)
                ? 1
                : (bluetoothEnabled_ || bluetoothRadioReady) ? 3 : 0;
  drawBluetoothIcon(276, 5, bluetoothState);
  drawBatteryIcon(298, 6, batteryLevel(), batteryCharging());
  const bool build=backgroundBuildActive_ && aiBuildId_.length() && fire_ai_menu::workPhase(buildPhase_.c_str());
  const bool repair=luaRepairId_.length() && fire_ai_menu::workActive(luaRepairStatus_.c_str(),luaRepairPhase_.c_str());
  const auto indicator=fire_ai_menu::workIndicator(build,repair,millis(),workCompletedAt_);
  fire_ai_menu_ui::workStatus(surface,indicator,build?buildProgress_:luaRepairProgress_);
}

void FireOS::drawFooter(const char* left, const char* middle, const char* right) {
  const String a = cleanFooterLabel(left), b = cleanFooterLabel(middle), c = cleanFooterLabel(right);
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  FireUI::footer(surface, a.c_str(), b.c_str(), c.c_str());
  ui.setTextDatum(TL_DATUM);
}

void FireOS::drawMain() {
  drawStatusBar(safeMode_ ? "FIRE OS SAFE" : "FIRE OS");
  const uint8_t count = max<uint8_t>(1, visibleMainCount());
  uint8_t position = 0;
  bool found = false;
  for (uint8_t i = 0; i < count; ++i) {
    if (mainItemAtPosition(i) == mainIndex_) { position = i; found = true; break; }
  }
  if (!found) mainIndex_ = mainItemAtPosition(0);
  const uint8_t page = position / 4;
  const uint8_t pages = max<uint8_t>(1, (count + 3) / 4);
  drawText(14, 36, safeMode_ ? "Safe mode" : "FIRE OS", kMuted, 1);
  ui.setTextDatum(TR_DATUM);
  drawText(306, 36, String(page + 1) + " / " + String(pages), kMuted, 1);
  ui.setTextDatum(TL_DATUM);
  for (uint8_t cell = 0; cell < 4; ++cell) {
    const uint8_t at = page * 4 + cell;
    if (at >= count) break;
    const uint8_t item = mainItemAtPosition(at);
    drawMainCard(item, 12 + (cell % 2) * 152, 56 + (cell / 2) * 77,
                 item == mainIndex_);
  }
  drawFooter("Previous", "Open", "Next");
}

void FireOS::drawBuildNoticeOverlay() {
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  FireUI::panel(surface, 20, 48, 280, 140);
  FireUI::icon(surface, "icon.circle-check", 36, 64, kGreen, 24);
  FireUI::text(surface, 72, 66, "Appen er klar", kText, "ui16", 208);
  const String name = buildNoticeName_.length() ? buildNoticeName_ : String("Ny versjon");
  FireUI::text(surface, 36, 100, name.c_str(), kText, "ui12b", 248);
  const String status = compactStatusText(buildNoticeMessage_);
  FireUI::text(surface, 36, 123, status.c_str(), kMuted, "ui12", 248);
  FireUI::pill(surface, 36, 153, 114, buildNoticePackageId_.length() ? "Kjør app" : "Åpne", kCyan);
  FireUI::pill(surface, 164, 153, 120, "Avbryt", kMuted);
  drawFooter("", buildNoticePackageId_.length() ? "Kjør" : "Åpne", "Avbryt");
}

void FireOS::drawMainCard(uint8_t item, int32_t x, int32_t y, bool selected) {
  const uint16_t accent = item == 1 ? kPurple : item == 2 ? kOrange :
                          item == 3 ? kGreen : item == 5 ? FireUI::Blue : kCyan;
  const String title = item == 0 ? "Apps" : item == 1 ? "Settings" :
                 item == 2 ? "Power" : item == 3 ? "Files" :
                 item == 4 ? "AI Developer" : item == 5 ? "Home" :
                 item - kSystemMainCount < luaAppCount_ ?
                   luaAppDisplayNames_[item - kSystemMainCount] : String("App");
  const char* icon = item == 0 ? "icon.layout-grid" : item == 1 ? "icon.settings" :
                     item == 2 ? "icon.power" : item == 3 ? "icon.folder" :
                     item == 4 ? "icon.sparkles" : item == 5 ? "icon.house" :
                     item-kSystemMainCount<luaAppCount_?luaAppIcons_[item-kSystemMainCount]:"icon.code";
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  FireUI::tile(surface, x, y, 144, 70, title.c_str(), icon, accent, selected);
}

void FireOS::drawApps() {
  drawStatusBar("Apps");
  drawText(16, 35, "Applications", kText, 2);
  const uint8_t appCount = externalAppCount_ + luaAppCount_;
  const uint8_t itemCount = appCount + 1;
  const uint8_t visible = min<uint8_t>(5, itemCount - externalAppOffset_);
  for (uint8_t row = 0; row < visible; ++row) {
    const uint8_t item = externalAppOffset_ + row;
    const int y = 60 + row * 27;
    const bool selected = item == externalAppSelection_;
    fire_canvas_fill::Surface<M5Canvas> surface(ui);
    if (item == appCount) {
      FireUI::menuRow(surface, y, "Back", "", selected, "icon.chevron-left");
      continue;
    }
    const bool luaApp = item >= externalAppCount_;
    const uint8_t appIndex = luaApp ? item - externalAppCount_ : item;
    const String& name = luaApp ? luaAppNames_[appIndex] : externalAppNames_[appIndex];
    const String value = luaApp ? "Lua" : formatBytes(externalAppSizes_[appIndex]);
    FireUI::menuRow(surface, y, name.c_str(), value.c_str(), selected,
                    luaApp ? luaAppIcons_[appIndex] : fire_app_icons::select(name.c_str()));
    if (!luaApp && !externalAppCompatible_[appIndex])
      ui.fillCircle(301, y + 5, 3, kOrange);
  }
  if (externalAppMessage_.length()) drawText(16, 199, compactStatusText(externalAppMessage_), kOrange, 1);
  else if (!appCount) drawText(16, 199, "No apps in /apps", kMuted, 1);
  drawFooter("Previous", "Open", "Next");
}

void FireOS::drawSettings() {
  static const char* labels[kSettingsCount] = {
      "Date / Time",       "Display & Sound", "Wi-Fi",       "Bluetooth",
      "File Explorer",     "Boot",             "Firmware",      "Menu Layout",
      "Shortcuts",         "App Manager",      "Debug",         "System Info",
      "Help",              "Factory Reset",    "Backend / AI",   "Power",
      "Back",
  };
  drawStatusBar("Settings");
  drawText(16, 37, "System settings", kMuted, 1);
  String backend = "Backend: ";
  if (packageManager_ && packageManager_->networkPaused()) backend+="Overfører app";
  else if (backendClient_ && backendClient_->sessionReady()) {
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
  drawText(16, 31, dateTime_.localDateTime(), kText, 1);
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
    if (selected) drawSelection(10, y - 1, 300, 14, highlight);
    drawText(18, y + 1, fields[row], kText, 1,
             selected ? FireUI::Selected : kBg);
    ui.setTextDatum(TR_DATUM);
    drawText(302, y + 1, values[row], kText, 1,
             selected ? FireUI::Selected : kBg);
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
    drawPanel(12, 32, 296, 180);
    drawText(24, 42, "Saved networks", kText, 2, kPanel);
    const uint8_t itemCount = wifiSavedCount_ + 4;
    const int visible = min<int>(itemCount - wifiSavedOffset_, 6);
    for (int row = 0; row < visible; ++row) {
      const uint8_t item = wifiSavedOffset_ + row;
      const int y = 67 + row * 22;
      const bool selected = item == wifiSavedSelection_;
      if (selected) drawSelection(18, y - 4, 284, 19, kCyan);
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
      drawText(24, y, label, kText, 1,
               selected ? FireUI::Selected : kPanel);
    }
    if (wifiSavedCount_ == 0) drawText(24, 67, "No saved networks", kMuted, 1, kPanel);
    drawFooter("Previous", "Select / Connect", "Next");
    return;
  }
  if (wifiScanDialog_) {
    drawPanel(12, 32, 296, 180);
    drawText(24, 42, "Networks found", kText, 2, kPanel);
    const int visible = min(wifiScanCount_ - static_cast<int>(wifiScanOffset_), 5);
    for (int row = 0; row < visible; ++row) {
      const int index = wifiScanOffset_ + row;
      String ssid = WiFi.SSID(index);
      if (ssid.length() == 0) ssid = "Hidden network";
      if (ssid.length() > 25) ssid = ssid.substring(0, 25);
      const int y = 76 + row * 23;
      if (index == wifiScanSelection_) {
        drawSelection(18, y - 4, 284, 20, kCyan);
      }
      drawText(24, y, ssid, kText, 1,
               index == wifiScanSelection_ ? FireUI::Selected : kPanel);
      drawText(270, y, String(WiFi.RSSI(index)),
               index == wifiScanSelection_ ? kText : kMuted, 1,
               index == wifiScanSelection_ ? FireUI::Selected : kPanel);
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
    drawPanel(12, 32, 296, 180);
    drawText(24, 41, "Mobile Wi-Fi setup", kText, 2, kPanel);
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
  for (uint8_t row = 0; row < 5; ++row) {
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
    drawText(160, 209, "Connected", kGreen, 1, kBg);
    ui.setTextDatum(TL_DATUM);
  } else if (bluetoothStatus_.length() > 0) {
    String status = bluetoothStatus_;
    if (status.length() > 34) status = status.substring(0, 34);
    ui.setTextDatum(MC_DATUM);
    drawText(160, 209, status, kMuted, 1, kBg);
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
    drawText(160, 209, status, kMuted, 1, kBg);
    ui.setTextDatum(TL_DATUM);
  }
  drawFooter("Previous", "Select", "Next");
  if (bluetoothScanDialog_) drawBluetoothScanDialog();
  if (bluetoothSavedDialog_) drawBluetoothSavedDialog();
}

void FireOS::drawBluetoothScanDialog() {
  drawPanel(8, 31, 304, 181);
  drawRounded(8, 31, 304, 181, 8, kCyan, false);
  drawText(18, 39, bluetoothUnknownDialog_ ? "Unknown devices" : "BLE devices",
           kText, 2, kPanel);

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
      if (selected) drawSelection(15, y - 3, 290, 21, kCyan);
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

      drawText(22, y + 1, name, kText, 1,
               selected ? FireUI::Selected : kPanel);
      ui.setTextDatum(MR_DATUM);
      drawText(298, y + 1, signal,
               selected ? kText : kMuted, 1, selected ? FireUI::Selected : kPanel);
      ui.setTextDatum(TL_DATUM);
    }
  }

  const uint8_t backItem = deviceCount;
  const bool backSelected = bluetoothScanSelection_ == backItem;
  if (backSelected) drawSelection(15, 188, 290, 18, kCyan);
  drawText(22, 191, "Back", kText, 1,
           backSelected ? FireUI::Selected : kPanel);
  ui.setTextDatum(MC_DATUM);
  drawText(160, 204, bluetoothUnknownDialog_ ? "A/C move   B pair/back"
                                             : "A/C move   B select",
           kMuted, 1, kPanel);
  ui.setTextDatum(TL_DATUM);
}

void FireOS::drawBluetoothSavedDialog() {
  drawPanel(8, 31, 304, 181);
  drawRounded(8, 31, 304, 181, 8, kCyan, false);
  drawText(18, 39, "Saved devices", kText, 2, kPanel);

  const uint8_t itemCount = bluetoothSavedCount_ + 2;
  const uint8_t visible = min<uint8_t>(5, itemCount - bluetoothSavedOffset_);
  for (uint8_t row = 0; row < visible; ++row) {
    const uint8_t item = bluetoothSavedOffset_ + row;
    const bool selected = item == bluetoothSavedSelection_;
    const int y = 64 + row * 25;
    if (selected) drawSelection(15, y - 3, 290, 21, kCyan);
    String label;
    if (item < bluetoothSavedCount_) {
      label = bluetoothSavedNames_[item];
    } else if (item == bluetoothSavedCount_) {
      label = bluetoothSavedDeleteArmed_ ? "Confirm delete" : "Delete selected";
    } else {
      label = "Back";
    }

    drawText(22, y + 1, label, kText, 1,
             selected ? FireUI::Selected : kPanel);
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
    drawPanel(12, 32, 296, 180);
    drawText(24, 40, "Choose Boot App", kText, 2, kPanel);
    const uint8_t itemCount = externalAppCount_ + luaAppCount_ + 2;
    const uint8_t visible = min<uint8_t>(6, itemCount - bootAppOffset_);
    for (uint8_t row = 0; row < visible; ++row) {
      const uint8_t item = bootAppOffset_ + row;
      const bool selected = item == bootAppSelection_;
      const int y = 72 + row * 22;
      if (selected) drawSelection(18, y - 3, 284, 19, kCyan);
      const bool backItem = item == itemCount - 1;
      String name = backItem ? "Back" : "FIRE OS (Default)";
      if (item > 0 && item - 1 < externalAppCount_) {
        name = externalAppNames_[item - 1];
      } else if (!backItem && item > externalAppCount_) {
        name = luaAppDisplayNames_[item - 1 - externalAppCount_];
      }

      drawText(26, y, name, kText, 1,
               selected ? FireUI::Selected : kPanel);
      if (!backItem && item > externalAppCount_) {
        ui.setTextDatum(MR_DATUM);
        drawText(298, y, "Lua", selected ? kText : kCyan, 1,
                 selected ? FireUI::Selected : kPanel);
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
  if (firmwareBusy()) {
    drawPanel(12, 44, 296, 142);
    drawText(24, 58, "Firmwareoppdatering", kCyan, 2, kPanel);
    const String status = ota_.busy() ? ota_.message() : firmwareMessage_;
    drawText(24, 101, status.substring(0, 42), kText, 1, kPanel);
    if (status.length() > 42)
      drawText(24, 119, status.substring(42, 84), kText, 1, kPanel);
    if (ota_.busy()) {
      drawRounded(24, 151, 270, 10, 3, kBg, true);
      drawRounded(24, 151, 270 * ota_.progress() / 100, 10, 3, kCyan, true);
    }
    drawFooter(ota_.busy() ? "A  AVBRYT" : "VENT", "ARBEIDER", "");
    return;
  }
  if (ota_.busy()) {
    drawText(18, 45, "Firmwareoppdatering", kCyan, 2);
    String message = ota_.message();
    drawText(18, 85, message.substring(0, 35), kText, 1);
    if (message.length() > 35) drawText(18, 105, message.substring(35, 70), kText, 1);
    drawRounded(18, 140, 284, 18, 4, kMuted, false);
    drawRounded(20, 142, 280 * ota_.progress() / 100, 14, 3, kCyan, true);
    drawFooter("Avbryt", "Vent", "Vent"); return;
  }
  if (firmwareInstallConfirm_) {
    drawPanel(14, 40, 292, 150);
    const bool reinstall = firmwareInstallFromGithub_ && firmwareGithubRelease_.version == kFirmwareVersion;
    drawText(28, 52, reinstall ? "Reinstaller firmware?" : "Installer firmware?", kOrange, 2, kPanel);
    String name = firmwareInstallFromGithub_ ? firmwareGithubRelease_.version : sdBaseName(firmwarePendingSdPath_);

    drawText(28, 88, name, kText, 1, kPanel);
    drawText(28, 114, firmwareInstallFromGithub_ ? "Hentes direkte fra GitHub" : "Kontrollerer signert SD-kopi", kMuted, 1, kPanel);
    drawText(28, 138, "Installerer og starter pa nytt", kCyan, 1, kPanel);
    drawFooter("Avbryt", reinstall ? "Reinstaller" : "Installer", "Avbryt"); return;
  }
  if (firmwareGithubOverwriteConfirm_) {
    drawPanel(12, 44, 296, 142);
    drawText(26, 56, "Last ned til SD?", kOrange, 2, kPanel);
    String name = firmwareGithubRelease_.name;

    drawText(26, 92, name, kText, 1, kPanel);
    drawText(26, 116, "Lagrer uten installering/omstart", kMuted, 1, kPanel);
    drawText(26, 137, "Gammel kopi beholdes som backup", kMuted, 1, kPanel);
    drawFooter("Avbryt", "Last ned", "Avbryt"); return;
  }
  if (firmwareGithubActionMenu_) {
    drawText(16, 38, firmwareGithubRelease_.version, kCyan, 2);
    const char* actions[] = {firmwareGithubRelease_.version == kFirmwareVersion ?
        "Reinstaller direkte fra GitHub" : "Installer direkte fra GitHub", "Last ned til SD", "Tilbake"};
    for (uint8_t i=0; i<3; ++i) {
      const int y = 85 + i*28; const bool selected = i == firmwareGithubActionIndex_;
      if (selected) drawSelection(10,y-4,300,23, kCyan);
      drawText(20,y,actions[i],selected? kText :kText,1,selected ? FireUI::Selected :kBg);
    }
    drawFooter("Forrige", "Velg", "Neste"); return;
  }
  if (firmwareGithubDialog_) { drawGithubFirmwareDialog(); return; }
  if (firmwareSdDialog_) { drawSdFirmwareDialog(); return; }
  drawText(16, 35, "Firmware", kText, 2);
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  const String version = firmwareVersionLabel();
  FireUI::pill(surface, 136, 34, 170, version.c_str(), kMuted);
  drawRow(0, "Oppdater fra GitHub", firmwareSelection_ == 0);
  drawRow(1, "Installer fra SD", firmwareSelection_ == 1);
  drawRow(2, "Back", firmwareSelection_ == 2);

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
  drawPanel(8, 31, 304, 181);
  drawText(18, 39, "Saved firmware", kText, 2, kPanel);
  const uint8_t visible = min<uint8_t>(5, firmwareCount_ + 1 - firmwareOffset_);
  for (uint8_t row = 0; row < visible; ++row) {
    const uint8_t item = firmwareOffset_ + row;
    const bool selected = item == firmwareSelection_;
    String name = item < firmwareCount_ ? firmwareNames_[item] : String("Back");
    if (name.startsWith("fire-os-")) name = name.substring(8);
    if (name.endsWith(".bin")) name.remove(name.length() - 4);
    const String value = item < firmwareCount_ ? formatBytes(firmwareSizes_[item]) : String();
    fire_canvas_fill::Surface<M5Canvas> surface(ui);
    FireUI::menuRow(surface, 62 + row * 26, name.c_str(), value.c_str(), selected,
                    item < firmwareCount_ ? "icon.download" : "icon.chevron-left");
  }
  const String status = compactStatusText(firmwareMessage_);
  drawText(18, 197, status, kMuted, 1, kPanel);
  drawFooter("Previous", "Select", "Next");
}

void FireOS::drawGithubFirmwareDialog() {
  drawPanel(8, 31, 304, 181);
  drawText(18, 39, "GitHub firmware", kText, 2, kPanel);
  const uint8_t count = githubFirmware_ ? githubFirmware_->entryCount() : 0;
  const uint8_t visible = min<uint8_t>(5, count + 1 - firmwareGithubOffset_);
  if (!count) {
    drawText(24, 94, githubFirmware_ && githubFirmware_->busy() ?
             "Loading signed catalog" : "No available releases", kMuted, 1, kPanel);
  } else for (uint8_t row = 0; row < visible; ++row) {
    const uint8_t item = firmwareGithubOffset_ + row;
    const bool selected = item == firmwareGithubSelection_;
    String name = item < count ? githubFirmware_->entryVersion(item) : String("Back");
    if (name.startsWith("fire-os-")) name = name.substring(8);
    const String value = item < count ? formatBytes(githubFirmware_->entrySize(item)) : String();
    const bool local = item < count && sdReady_ && SD.exists("/firmware/" + githubFirmware_->entryName(item));
    fire_canvas_fill::Surface<M5Canvas> surface(ui);
    FireUI::menuRow(surface, 62 + row * 26, name.c_str(), value.c_str(), selected,
                    item == count ? "icon.chevron-left" : local ? "icon.hard-drive" : "icon.download");
  }
  const String status = compactStatusText(firmwareMessage_);
  drawText(18, 197, status, kMuted, 1, kPanel);
  drawFooter("Previous", "Select", "Next");
}

void FireOS::drawMainMenuSettings() {
  drawStatusBar("Menu Layout");
  if (luaMenuPicker_) {
    drawText(16, 37, "Choose apps for the home grid", kMuted, 1);
    const uint8_t itemCount = luaAppCount_ + 1;
    const uint8_t visible = min<uint8_t>(7, itemCount - luaMenuOffset_);
    for (uint8_t row = 0; row < visible; ++row) {
      const uint8_t item = luaMenuOffset_ + row;
      const bool selected = item == luaMenuSelection_;
      const int y = 57 + row * 21;
      if (selected) drawSelection(10, y - 3, 300, 18, kCyan);
      if (item < luaAppCount_) {
        String name = luaAppDisplayNames_[item];

        drawText(18, y, name, kText, 1,
                 selected ? FireUI::Selected : kBg);
        ui.setTextDatum(MR_DATUM);
        drawText(300, y, luaMenuSelected_[item] ? "Shown" : "Hidden",
                 selected ? kText : (luaMenuSelected_[item] ? kGreen : kMuted),
                 1, selected ? FireUI::Selected : kBg);
        ui.setTextDatum(TL_DATUM);
      } else {
        drawText(18, y, "Back", kText, 1,
                 selected ? FireUI::Selected : kBg);
      }
    }
    if (luaAppCount_ == 0)
      drawText(18, 76, "No Lua apps installed", kMuted, 1);
    drawFooter("Previous", "Toggle", "Next");
    return;
  }
  drawText(16, 34, "System menu layout", kText, 2);
  drawText(16, 49, "B toggles visibility", kMuted, 1);
  const char* labels[] = {"Apps", "Settings", "Power", "Files", "AI Developer",
                          "Show selected apps", "Back"};
  const String values[] = {mainVisible_[0] ? "Visible" : "Hidden",
      mainVisible_[1] ? "Visible" : "Hidden", mainVisible_[2] ? "Visible" : "Hidden",
      mainVisible_[3] ? "Visible" : "Hidden", mainVisible_[4] ? "Visible" : "Hidden", "", ""};
  const uint8_t first = detailIndex_ < 6 ? 0 : detailIndex_ - 5;
  for (uint8_t row = 0; row < 6 && first + row < 7; ++row) {
    const uint8_t item = first + row;
    drawRow(row, labels[item], item == detailIndex_, values[item]);
  }
  drawFooter("Previous", "Select", "Next");
}

void FireOS::drawShortcuts() {
  drawStatusBar("Buttons");
  drawText(16,37,"One press performs one action",kMuted,1);
  const char* labels[]={"Hold A","Hold B","Hold C","Back"};
  const char* values[]={"Home","Quick Settings","One level back",""};
  for(uint8_t row=0;row<4;++row) drawRow(row,labels[row],row==detailIndex_,values[row]);
  drawFooter("Previous","Back","Next");
}

void FireOS::drawAiDeveloper() {
  // AI Developer is intentionally immersive: no system status bar or panel.
  ui.fillSprite(kBg);
  if (aiProjectPickerActive_) {drawAiPicker();return;}
  if (aiWorkflowState_==3 && aiProposalId_.length() && aiProposalProjectId_==aiProjectId_ && aiProposalAppName_.length()) {
    fire_canvas_fill::Surface<M5Canvas> surface(ui);
    fire_ai_menu_ui::proposalName(surface,aiProposalAppName_.c_str());
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
  const uint16_t line = kText;
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
    drawRounded(eyeLeft - 13, leftEyeY - height / 2, 26, height,
                     height / 2, line, true);
    drawRounded(eyeRight - 13, rightEyeY - height / 2, 26, height,
                     height / 2, line, true);
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
  const bool failedBuildView = aiBuildResumePending_ &&
                               aiBuildErrorStatus_.length() > 0;
  ui.setTextDatum(MC_DATUM);
  if (!failedBuildView && aiWorkflowState_ != 4) drawText(cx, 190, stateLabel, kMuted, 1, kBg);
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
  workflowLabel = compactStatusText(workflowLabel);
  drawText(cx, 207, workflowLabel, kMuted, 1, kBg);
  if (failedBuildView) {
    drawText(cx, 174, compactStatusText(aiBuildErrorStatus_), kOrange, 1,
             kBg);
    if (aiBuildDiagnosticMessage_.length() > 0)
      drawText(cx, 190, compactStatusText(aiBuildDiagnosticMessage_), kMuted, 1,
               kBg);
  } else if (aiAssistantText_.length() > 0) {
    String assistant = compactStatusText(aiAssistantText_);
    drawText(cx, 174, assistant, kText, 1, kBg);
  }
  if (aiWorkflowState_ == 4) {
    drawRounded(45, 184, 230, 7, 3, FireUI::Border, false);
    drawRounded(47, 186,
                     static_cast<int32_t>(226 * aiBuildProgress_ / 100), 3,
                     1, kCyan, true);
  }
  const char* leftHint="Hvile";
  const char* centerHint="Snakk";
  const char* rightHint="Meny";
  if (aiWorkflowState_==1) {leftHint="";centerHint="Fullfør";rightHint="Avbryt";}
  else if (aiWorkflowState_==2) {leftHint="Hvile";centerHint="Arbeid";rightHint="Avbryt";}
  else if (aiWorkflowState_==3) {leftHint=aiBuildResumePending_?"Prøv igjen":"Bygg";centerHint="Arbeid";rightHint="Avbryt";}
  else if (aiWorkflowState_==4) {leftHint=backgroundBuildsSupported_?"Minimer":"";centerHint="Arbeid";rightHint="Avbryt";}
  else if (aiWorkflowState_==5) {leftHint="Kjør";centerHint="Arbeid";rightHint="Avbryt";}
  else if (aiWorkflowState_==6) {leftHint="Hvile";centerHint="";rightHint="Meny";}
  if (aiVoiceTestMode_) {centerHint=aiAudioCaptureActive_?"Fullfør":aiVoiceTestPlaybackActive_?"Ny test":"Ta opp";rightHint=aiVoiceTestPlaybackActive_?"Avbryt":"Meny";}
  drawFooter(leftHint, centerHint, rightHint);

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
  drawStatusBar("Backend / AI");
  if (wifiSetupActive_) {
    drawPanel(12, 32, 296, 180);
    drawText(24, 41, "Backend config", kText, 2, kPanel);
    const String url = "http://" + WiFi.softAPIP().toString() +
                       "/?token=" + wifiSetupToken_;
    ui.qrcode(url, 190, 60, 112, 4);
    drawText(24, 78, "1. Join network", kText, 1, kPanel);
    drawText(24, 96, "FIRE-Setup", kCyan, 1, kPanel);
    drawText(24, 120, "2. Password", kText, 1, kPanel);
    drawText(24, 138, wifiSetupPassword_, kCyan, 1, kPanel);
    drawText(24, 166, "3. Scan backend QR", kText, 1, kPanel);
    drawText(24, 184, "PC, port, ID and token", kMuted, 1, kPanel);
    drawFooter("", "Close", "");
    return;
  }
  const String backendModeLabel = backendMode_ == 0
                                      ? "Auto"
                                      : backendMode_ == 1 ? "On" : "Off";
  drawRow(0, "Mode", detailIndex_ == 0, backendModeLabel);
  drawRow(1, "Backend config", detailIndex_ == 1);
  drawRow(2, "Connection status", detailIndex_ == 2,
          backendClient_ && backendClient_->configured() ? backendStatus_ : "Not configured");
  drawRow(3, "Back", detailIndex_ == 3);
  String host = backendHost_.length() > 0 ? backendHost_ : "not set";
  if (host.length() > 24) host = host.substring(0, 21) + "...";
  String device = backendDeviceId_.length() > 0 ? backendDeviceId_ : "not set";
  if (device.length() > 19) device = device.substring(0, 16) + "...";
  drawText(16, 169, "PC: " + host, kMuted, 1);
  drawText(16, 185, "Port: " + String(backendPort_) + "  ID: " + device,
           kMuted, 1);
  drawText(16, 201, "Token: " + String(backendToken_.length() >= 24 ? "configured" : "not set"),
           backendToken_.length() >= 24 ? kGreen : kOrange, 1);
  drawFooter("Previous", "Select", "Next");
}

void FireOS::drawLuaApp() {
  luaSdkFrame_.invalidate();
  const bool sdk=runningSdkLuaApp();
  const uint16_t background=sdk?luaRuntime_->frameBackground():uint16_t(TFT_BLACK);
  ui.fillSprite(background);
  // Acknowledge ONLY a completed full fill, never callback entry. The frame
  // remains owned by this UI call until update returns, before any OS overlay.
  if (sdk && fullLuaCanvas()) luaSdkFrame_.acknowledgePrefill(background);
  if (luaAppActive_) {
    // The Lua callback renders directly into the same sprite as the OS.
    // This keeps the app full-screen without a second framebuffer.
    updateLuaApp();
  }
  luaSdkFrame_.invalidate();
  if (sdk && !luaAppActive_ && luaAppError_.length()>0) ui.fillSprite(TFT_BLACK);
  if (luaAppActive_ && luaDevelopJob_) {
    ui.setTextDatum(TL_DATUM);
    if (luaFeedbackConfirmation_) {
      drawPanel(8,30,304,180);
      drawText(20,39,"Din observasjon",kText,2,kPanel);
      // At most 160 UTF-8 bytes, shown completely in bounded glyph lines.
      size_t offset=0;const size_t length=luaDevelopInstruction_.length();
      for (uint8_t line=0;line<8 && offset<length;++line) {
        const size_t start=offset;uint32_t codepoint=0;
        for (uint8_t count=0;count<20 && offset<length;++count)
          if (!fire_app_bitmap::codepoint(luaDevelopInstruction_.c_str(),length,offset,codepoint)) {offset=length;break;}
        drawText(20,65+line*16,luaDevelopInstruction_.substring(start,offset),kText,1,kPanel);
      }
      if(luaFeedbackOutcome_=="unconfirmed") drawText(20,199,"Ikke bekreftet. Prøv igjen.",kOrange,1,kPanel);
      drawFooter("Avbryt",luaFeedbackAck_.length()?"Sender":"Bekreft","Avvis");
    } else {
      drawPanel(16,164,288,44);
      const String status=luaDataUploadJob_?String("Overfører målegrunnlag"):
          !backendClient_ || !backendClient_->sessionReady()?String("Kobler til"):
          !luaRunId_.length()?String("Bekrefter appkjøring"):String("Samler appgrunnlag");
      drawText(28,178,status,kText,1,kPanel);drawFooter("Avbryt","Vent","");
    }
    return;
  }
  if (!luaAppActive_ && luaAppError_.length() > 0) {
    ui.fillSprite(kBg);
    drawPanel(10, 40, 300, 164);
    ui.setTextDatum(MC_DATUM);
    drawText(160, 28, "APP ERROR", kOrange, 2, kBg);
    String appLabel = luaErrorAppName_.length() > 0 ? luaErrorAppName_
                                                     : luaAppName_;
    if (appLabel.length() > 24) appLabel = appLabel.substring(0, 21) + "...";
    drawText(160, 55, appLabel, kText, 2, kBg);
    String version = luaErrorAppVersion_.length() > 0
                         ? "v" + luaErrorAppVersion_
                         : "version unavailable";
    drawText(160, 78, version, kMuted, 1, kBg);
    String error = luaAppError_.substring(0, 38);
    drawText(160, 101, error, kText, 1, kBg);
    String status = luaRepairMessage_.length() > 0 ? luaRepairMessage_
                                                   : "Press B to fix this app";
    status = compactStatusText(status);
    drawText(160, 125, status, kMuted, 1, kBg);
    const bool wifiConnected = WiFi.status() == WL_CONNECTED;
    const String wifiLabel = wifiMode_ == 2
                                 ? "Wi-Fi: OFF"
                                 : wifiConnected
                                       ? "Wi-Fi: connected"
                                       : wifiConnectActive_
                                             ? "Wi-Fi: connecting"
                                             : wifiSsid_.length() > 0
                                                   ? "Wi-Fi: waiting"
                                                   : "Wi-Fi: not configured";
    drawText(160, 139, wifiLabel,
             wifiConnected ? kGreen : wifiMode_ == 2 ? kMuted : kOrange, 1,
             kBg);
    const String backendLabel =
        !backendClient_ || !backendClient_->configured()
            ? "Backend: not configured"
            : backendClient_->sessionReady()
                  ? "Backend: connected"
                  : packageManager_ && packageManager_->networkPaused()?"Overfører app":backendClient_->active() ? "Backend: connecting"
                                             : "Backend: disconnected";
    drawText(160, 152, backendLabel,
             backendClient_ && backendClient_->sessionReady()
                 ? kGreen
                 : kOrange,
             1, kBg);
    if (fire_ai_menu::workActive(luaRepairStatus_.c_str(),luaRepairPhase_.c_str())) {
      drawRounded(32, 160, 256, 10, 4, kMuted, false);
      drawRounded(34, 162,
                       max<int>(2, 252 * luaRepairProgress_ / 100), 6, 3,
                       kCyan, true);
    }
    const uint16_t actionColor = luaErrorAction_ == 0 ? kCyan : kGreen;
    const bool waitingForRepair = luaRepairRequested_ && luaErrorAction_ == 0;
    drawSelection(58, 170, 204, 30, actionColor);
    drawText(160, 185, waitingForRepair ? "Venter" :
             luaErrorAction_ == 0 ? "Fiks feil" : "Kjør rettet app", kText, 2,
             FireUI::Selected);
    if (luaRepairStatus_ == "ready")
    drawText(160, 207,
               "Ny versjon " + luaRepairReadyVersion_, kGreen, 1,
               kBg);
    else
      drawText(160, 207, "B starter valgt handling", kMuted, 1, kBg);
    drawFooter("Minimer",waitingForRepair?"Arbeid":"Velg","Avbryt");
    ui.setTextDatum(TL_DATUM);
  }
}

void FireOS::drawAppsSettings() {
  drawStatusBar("App Manager");
  if (appManagerDeleteConfirm_) {
    drawPanel(18, 54, 284, 112);
    drawText(32, 68, "Delete app?", kText, 2, kPanel);
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

    drawText(32, 101, name, kText, 1, kPanel);
    drawText(32, 128, "B delete   A/C cancel", kOrange, 1, kPanel);
    drawFooter("Cancel", "Delete", "Cancel");
    return;
  }
  if (appManagerActionMenu_) {
    drawPanel(8, 32, 304, 182);
    const bool luaSelected = externalAppSelection_ >= externalAppCount_ &&
                             externalAppSelection_ < externalAppCount_ + luaAppCount_;
    const uint8_t selectedIndex = luaSelected
                                      ? externalAppSelection_ - externalAppCount_
                                      : externalAppSelection_;
    String name = luaSelected ? luaAppNames_[selectedIndex]
                              : externalAppNames_[selectedIndex];

    drawText(24, 40, name, kText, 1, kPanel);
    static const char* actions[] = {"Launch", "Delete", "Back"};
    for (uint8_t row = 0; row < 3; ++row) {
      const String label = actions[row];
      fire_canvas_fill::Surface<M5Canvas> surface(ui);
      FireUI::menuRow(surface, 62 + row * 25, label.c_str(), "",
                      row == appManagerActionIndex_, osMenuIcon(label));
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
    if (selected) drawSelection(12, y - 3, 296, 19, kCyan);
    if (item == appCount) {
      drawText(22, y, "Back", kText, 1,
               selected ? FireUI::Selected : kBg);
      continue;
    }
    const bool luaSelected = item >= externalAppCount_;
    const uint8_t selectedIndex = luaSelected ? item - externalAppCount_ : item;
    String name = luaSelected ? luaAppNames_[selectedIndex]
                              : externalAppNames_[selectedIndex];

    const uint16_t nameColor = selected
                                   ? kText : (luaSelected || externalAppCompatible_[selectedIndex]
                                          ? kText
                                          : kOrange);
    drawText(22, y, name, nameColor, 1,
             selected ? FireUI::Selected : kBg);
    ui.setTextDatum(MR_DATUM);
    drawText(300, y, luaSelected ? "Lua" : formatBytes(externalAppSizes_[selectedIndex]),
             selected ? kText : (luaSelected || externalAppCompatible_[selectedIndex] ? kMuted : kOrange),
             1, selected ? FireUI::Selected : kBg);
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
  const auto statusLine=[&]() {drawText(16,203,compactStatusText(managerStatus_),kOrange,1,kBg);};
  if(appManagerVersionsWaiting_ || appManagerDeleteWaiting_ || downloadPhase_==1 || downloadPhase_==2 || (packageManager_ && packageManager_->busy())) {
    drawPanel(12,48,296,146);drawText(24,64,managerTargetValid_?managerTarget_.name:String("Appoverføring"),kText,1,kPanel);
    drawText(24,100,"Vennligst vent",kText,2,kPanel);
    if(downloadPhase_ || (packageManager_ && packageManager_->busy())) drawText(16,203,packageTransferLabel(),kOrange,1,kBg);else statusLine();
    drawFooter("","Vent","Avbryt");return;
  }
  if (appManagerDevelopConfirm_) {
    drawPanel(12,48,296,150);
    drawText(24,62,"Start appen først?",kText,2,kPanel);
    drawText(24,98,"Appen startes før grunnlaget hentes.",kText,1,kPanel);
    drawText(24,124,"Dette kjører appens vanlige funksjoner.",kMuted,1,kPanel);
    if (managerTargetValid_) drawText(24,154,managerTarget_.name,kText,1,kPanel);
    statusLine();drawFooter("Avbryt","Start app","Avbryt");return;
  }
  if (appManagerVersionDialog_) {
    drawAppManagerVersions();
    return;
  }
  if (appManagerDeleteConfirm_) {
    drawPanel(18, 54, 284, 112);
    drawText(32, 68, appManagerDeleteMode_ == 2 ? "Delete backend?"
                                                : "Delete local?",
             kText, 2, kPanel);
    String name = appManagerDeleteMode_==1?managerTarget_.name:appManagerDeleteName_;
    if(!name.length() && managerTargetValid_) name=managerTarget_.name;

    drawText(32, 101, name, kText, 1, kPanel);
    drawText(32, 128, appManagerDeleteMode_ == 2
                          ? "ALL backend versions"
                          : "Only local SD files",
             kOrange, 1, kPanel);
    statusLine();drawFooter("Cancel", "Confirm", "Cancel");
    return;
  }
  if (appManagerActionMenu_) {
    drawPanel(8, 32, 304, 182);
    String name = managerTargetValid_?managerTarget_.name:String();

    drawText(24, 40, name, kText, 1, kPanel);
    const uint8_t first=appManagerActionIndex_<5?0:appManagerActionIndex_-4;
    for (uint8_t row = 0; row < 5 && first+row<appManagerActionCount_; ++row) {
      const uint8_t item=first+row;
      const String label = appManagerActionLabels_[item];
      fire_canvas_fill::Surface<M5Canvas> surface(ui);
      FireUI::menuRow(surface, 62 + row * 25, label.c_str(), "",
                      item == appManagerActionIndex_, osMenuIcon(label));
    }
    statusLine();drawFooter("A  UP", "B  SELECT", "DOWN  C");
    return;
  }

  String heading = "Local + backend apps";
  if (backendClient_ && !backendClient_->sessionReady()) heading += " (offline)";
  drawText(16, 34, heading, kMuted, 1);
  const uint8_t itemCount = managerItemCount_ + 1;
  const uint8_t visible = min<uint8_t>(6, itemCount - managerOffset_);
  for (uint8_t row = 0; row < visible; ++row) {
    const uint8_t item = managerOffset_ + row;
    const bool selected = item == managerSelection_;
    fire_canvas_fill::Surface<M5Canvas> surface(ui);
    if (item == managerItemCount_) {
      FireUI::menuRow(surface, 52 + row * 25, "Back", "", selected, "icon.chevron-left");
      continue;
    }
    const ManagerItem& entry = managerItems_[item];
    const char* value = entry.backend && entry.local ? "Both" : entry.backend ?
        (entry.downloadable ? "Cloud" : "Locked") : entry.kind == 0 ? "BIN" : "Lua";
    FireUI::menuRow(surface, 52 + row * 25, entry.name.c_str(), value, selected,
                    entry.local ? "icon.package" : "icon.download");
  }
  String status = managerStatus_.length() > 0 ? managerStatus_ : externalAppMessage_;
  status = compactStatusText(status);
  drawText(16, 203, status, kMuted, 1);
  drawFooter("A  UP", "B  ACTIONS", "DOWN  C");
}

void FireOS::drawAppManagerVersions() {
  drawStatusBar("App versions");
  drawPanel(8, 31, 304, 181);
  drawText(18, 39, "Choose version", kText, 2, kPanel);
  const uint8_t itemCount = appManagerVersionCount_ + 1;
  const uint8_t visible = min<uint8_t>(5, itemCount - appManagerVersionOffset_);
  for (uint8_t row = 0; row < visible; ++row) {
    const uint8_t item = appManagerVersionOffset_ + row;
    const bool selected = item == appManagerVersionSelection_;
    const int y = 64 + row * 23;
    if (selected) drawSelection(15, y - 3, 290, 19, kCyan);
    if (item == appManagerVersionCount_) {
      drawText(22, y, "Back", kText, 1,
               selected ? FireUI::Selected : kPanel);
    } else {
      String label = appManagerVersionLabels_[item];
      if (label.length() == 0) label = "Version";
      if (!appManagerVersionDownloadable_[item]) label += " (locked)";

      drawText(22, y, label, kText, 1,
               selected ? FireUI::Selected : kPanel);
    }
  }
  drawText(16,203,compactStatusText(managerStatus_),kOrange,1,kBg);
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
  drawPanel(12, 32, 296, 180);
  drawText(24, 40, "Quick Settings", kText, 2, kPanel);
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
  const String backendModeLabel = backendMode_ == 0
                                      ? "Auto"
                                      : backendMode_ == 1 ? "On" : "Off";
  String backendValue;
  if (backendMode_ == 2) {
    backendValue = "Off";
  } else if (wifiMode_ == 2) {
    backendValue = "Wi-Fi Off";
  } else if (packageManager_ && packageManager_->networkPaused()) {
    backendValue="Overfører app";
  } else if (backendClient_ && backendClient_->sessionReady()) {
    backendValue = "Connected (" + backendModeLabel + ")";
  } else if (backendClient_ && backendClient_->sessionRejected()) {
    backendValue = "Avvist";
  } else if (backendClient_ && backendClient_->active()) {
    backendValue = "Connecting (" + backendModeLabel + ")";
  } else {
    backendValue = "Disconnected (" + backendModeLabel + ")";
  }
  if (backendValue.length() > 21) backendValue = backendValue.substring(0, 21);
  const String sdValue = sdStorageLabel();

  const char* labels[] = {"Brightness", "Volume", "Wi-Fi", "Bluetooth",
      "Backend-sync", "SD card", "Power", "All settings", "Back"};
  const String values[] = {"", "", wifiValue, bluetoothValue, backendValue,
      sdValue, "", "", ""};
  const uint8_t first = quickIndex_ < 6 ? 0 : quickIndex_ - 5;
  for (uint8_t row = 0; row < 6 && first + row < kQuickCount; ++row) {
    const uint8_t item = first + row;
    if (item == 0) drawLevelRow(row, labels[item], brightnessStep_, kBrightnessStepCount,
                               quickIndex_ == item, kCyan, quickEditing_ && quickIndex_ == item);
    else if (item == 1) drawLevelRow(row, labels[item], volumeStep_, kVolumeStepCount,
                                    quickIndex_ == item, kGreen, quickEditing_ && quickIndex_ == item);
    else drawRow(row, labels[item], quickIndex_ == item, values[item]);
  }
  drawFooter("", quickEditing_ ? "Adjust" : "Select", "");
}

void FireOS::drawFileExplorer() {
  drawStatusBar("File Explorer");
  if (sdImagePreview_) {
    drawText(20, 42, "Image preview", kText, 2, kPanel);
    drawText(20, 68, sdBaseName(sdImagePreviewPath_), kMuted, 1, kPanel);
    drawFooter("", "Close", "");
    return;
  }
  if (sdPreview_) {
    drawPanel(10, 32, 300, 180);
    drawText(20, 40, sdBaseName(sdEntryPaths_[sdSelection_]), kText, 1,
             kPanel);
    for (uint8_t line = 0; line < sdPreviewLineCount_; ++line) {
      drawText(18, 62 + line * 17, sdPreviewLines_[line], kText, 1, kPanel);
    }
    drawFooter("", "Close", "");
    return;
  }
  if (sdNameEditor_) {
    drawPanel(10, 32, 300, 180);
    drawText(20, 42, sdNameIsNewFolder_ ? "New folder" : "Rename", kText,
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
    drawPanel(18, 54, 284, 120);
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
    drawPanel(12, 32, 296, 180);
    drawText(24, 40, "File actions", kText, 2, kPanel);
    for (uint8_t row = 0; row < 7; ++row) {
      const uint8_t action = (sdActionIndex_ + row) % 8;
      const int y = 70 + row * 19;
      const bool selected = row == 0;
      if (selected) drawSelection(18, y - 3, 284, 17, kCyan);
      drawText(26, y, actions[action], kText, 1,
               selected ? FireUI::Selected : kPanel);
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
    if (selected) drawSelection(12, y - 3, 296, 20, kCyan);
    if (item < sdEntryCount_) {
      const uint16_t color = selected ? kText : kCyan;
      if (sdEntryDirectories_[item]) {
        ui.drawRect(20, y + 2, 13, 10, color);
        ui.drawLine(21, y + 2, 26, y - 1, color);
      } else {
        ui.drawRect(21, y, 11, 14, color);
        ui.drawLine(23, y + 4, 30, y + 4, color);
      }
      String name = sdEntryNames_[item];

      drawText(40, y + 1, name, kText, 1,
               selected ? FireUI::Selected : kPanel);
      ui.setTextDatum(MR_DATUM);
      drawText(302, y + 1,
               sdEntryDirectories_[item] ? "DIR" : formatBytes(sdEntrySizes_[item]),
               selected ? kText : kMuted, 1, selected ? FireUI::Selected : kPanel);
      ui.setTextDatum(TL_DATUM);
    } else {
      drawText(20, y + 1, "Back", kText, 1,
               selected ? FireUI::Selected : kPanel);
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
    if (aiAudioCaptureActive_) {
      debugMicStatus_ = "Recording - press B to stop";
      redrawRequested_ = true;
    } else if (aiVoiceTestPlaybackActive_) {
      debugMicRecording_ = false;
      debugMicPlaying_ = true;
      debugMicStatus_ = "Playing recording";
      redrawRequested_ = true;
    } else if (aiAudioError_.length() > 0) {
      debugMicRecording_ = false;
      debugMicStatus_ = aiAudioError_;
      aiVoiceTestMode_ = false;
      redrawRequested_ = true;
    }
  }
  if (debugMicPlaying_ && !aiVoiceTestPlaybackActive_ &&
      !aiAudioOutputActive_) {
    debugMicPlaying_ = false;
    aiVoiceTestMode_ = false;
    debugMicStatus_ = "Ready - press B to record";
    redrawRequested_ = true;
  }
}

void FireOS::startDebugMicTest() {
  if (!M5.Mic.isEnabled()) {
    debugMicStatus_ = "Microphone unavailable";
    return;
  }
  aiVoiceTestMode_ = true;
  if (!startAiRecording()) {
    aiVoiceTestMode_ = false;
    debugMicStatus_ = aiAudioError_.length() > 0 ? aiAudioError_
                                                 : "Microphone capture unavailable";
    return;
  }
  debugMicStartedAt_ = millis();
  debugMicRecording_ = true;
  debugMicPlaying_ = false;
  debugMicStatus_ = "Recording - press B to stop";
}

void FireOS::stopDebugMicTest() {
  if (!debugMicRecording_) return;
  finishAiRecording();
  debugMicStatus_ = "Stopping recording";
}

void FireOS::releaseDebugTestAudio() {
  if (debugMicRecording_ || debugMicPlaying_ || aiVoiceTestMode_)
    cancelConversationTurn("READY", false);
  debugMicRecording_ = false;
  debugMicPlaying_ = false;
  aiVoiceTestMode_ = false;
  debugMicStatus_ = "Press B to record";
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
    drawText(160, 36, title, kText, 2, kBg);
    drawText(160, 52, subtitle, kMuted, 1, kBg);
    ui.setTextDatum(TL_DATUM);
  };
  auto drawStatusRow = [&](uint8_t row, const String& label, const String& status) {
    const int y = 65 + row * 23;
    drawRounded(10, y, 300, 21, 5, kPanel, true);
    fire_canvas_fill::Surface<M5Canvas> surface(ui);
    FireUI::text(surface, 20, y + 4, label.c_str(), kMuted, "ui12", 170);
    FireUI::text(surface, 195, y + 4, status.c_str(), statusColor(status), "ui12b", 105, 2);
  };
  auto drawValueRow = [&](uint8_t row, const String& label,
                          const String& value) {
    const int y = 68 + row * 22;
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
      drawStatusRow(5, "Loop max us", String(maxLoopUs_));
    }
    drawText(16, 202, "Firmware/API status", kMuted, 1, kBg);
  } else if (detailIndex_ == 3) {
    drawTitle("Hardware tests", "Buttons and RGB");
    drawStatusRow(0, "Button A", buttons_[0].down() ? "DOWN" : "UP");
    drawStatusRow(1, "Button B", buttons_[1].down() ? "DOWN" : "UP");
    drawStatusRow(2, "Button C", buttons_[2].down() ? "DOWN" : "UP");
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
    drawRounded(12, 65, 70, 64, 5, kPanel, false);
    ui.drawRect(18, 71, 58, 50, kMuted);
    ui.drawLine(47, 73, 47, 119, kMuted);
    ui.drawLine(21, 96, 73, 96, kMuted);
    int bubbleX = 47;
    int bubbleY = 96;
    if (imuReady) {
      bubbleX += constrain(static_cast<int>(imu.accel.x * 24.0f), -22, 22);
      bubbleY -= constrain(static_cast<int>(imu.accel.y * 20.0f), -18, 18);
      ui.fillCircle(bubbleX, bubbleY, 7, kCyan);
    }
    ui.setTextDatum(MC_DATUM);
    drawText(47, 125, imuReady ? "TILT" : "N/A", kText, 1, kPanel);
    ui.setTextDatum(TL_DATUM);
    drawValueAt(67, "Accel g", imuReady
                                   ? String(imu.accel.x, 2) + "  " +
                                         String(imu.accel.y, 2) + "  " +
                                         String(imu.accel.z, 2)
                                   : "UNAVAILABLE");
    drawValueAt(89, "Gyro dps", imuReady
                                  ? String(imu.gyro.x, 1) + "  " +
                                        String(imu.gyro.y, 1) + "  " +
                                        String(imu.gyro.z, 1)
                                  : "UNAVAILABLE");
    float temperature = 0.0f;
    drawValueAt(111, "IMU temp", imuReady && M5.Imu.getTemp(&temperature)
                                   ? String(temperature, 1) + " C"
                                   : "UNAVAILABLE");
    drawValueRow(3, "Mic test", debugMicStatus_);
    analogReadResolution(12);
    drawValueRow(4, "Port B raw", String("G26=") + String(digitalRead(26)) +
                                       "  G36 ADC=" + String(analogRead(36)));
    drawValueRow(5, "I2C raw", String("G21=") + String(digitalRead(21)) +
                                   "  G22=" + String(digitalRead(22)));
    drawText(16, 198, "B: record/stop/play mic test", kMuted, 1, kBg);
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

void FireOS::drawBackendIcon(int32_t x, int32_t y, uint8_t state) {
  const uint16_t color = state == 2 ? kGreen : state == 1 ? kOrange : kRed;
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  FireUI::icon(surface, state ? "icon.cloud" : "icon.cloud-off", x, y, color, 16);
}

void FireOS::drawWifiIcon(int32_t x, int32_t y, uint8_t state) {
  const uint16_t color = state == 2 ? kGreen : state == 1 ? kOrange : kRed;
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  FireUI::icon(surface, state ? "icon.wifi" : "icon.wifi-off", x, y, color, 16);
}

void FireOS::drawBluetoothIcon(int32_t x, int32_t y, uint8_t state) {
  const uint16_t color = state == 2 ? kGreen : state ? kOrange : kMuted;
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  FireUI::icon(surface, state ? "icon.bluetooth" : "icon.bluetooth-off", x, y, color, 16);
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
  drawPanel(10, 40, 300, 160);
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  FireUI::icon(surface, "icon.shield", 26, 56, kOrange, 24);
  FireUI::text(surface, 64, 60, "Reset all settings?", kText, "ui16", 228);
  FireUI::text(surface, 26, 98, factoryResetArmed_ ? "Ready - confirm again" :
                "Select to arm reset", kOrange, "ui12b", 268);
  FireUI::text(surface, 26, 128, "App data is not removed yet.", kMuted, "ui12", 268);
  FireUI::text(surface, 26, 153, "This will restart the OS.", kMuted, "ui12", 268);
  drawFooter("", "Confirm", "Back");
}

void FireOS::drawRounded(int x, int y, int width, int height, int radius,
                         uint16_t color, bool filled) {
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  FireUI::roundRect(surface, x, y, width, height, radius, color, filled);
}

void FireOS::drawSelection(int x, int y, int width, int height, uint16_t accent) {
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  fire_ui_aa::rounded(surface, x, y, width, height, min<int>(6, height / 2),
                      FireUI::Selected, FireUI::Border, true, true);
  ui.fillRect(x, y + 4, 3, max<int>(1, height - 8), accent);
}

void FireOS::drawPanel(int x, int y, int width, int height) {
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  FireUI::panel(surface, x, y, width, height);
}

namespace {
const char* osMenuIcon(const String& label) {
  if (label == "Back" || label == "Tilbake") return "icon.chevron-left";
  if (label.indexOf("Wi-Fi") >= 0) return "icon.wifi";
  if (label.indexOf("Bluetooth") >= 0) return "icon.bluetooth";
  if (label.indexOf("Brightness") >= 0 || label.indexOf("Display") >= 0) return "icon.sun";
  if (label.indexOf("Volume") >= 0 || label.indexOf("sound") >= 0 || label.indexOf("melody") >= 0) return "icon.volume-2";
  if (label.indexOf("Date") >= 0 || label.indexOf("Time") >= 0 || label.indexOf("after") >= 0) return "icon.clock";
  if (label.indexOf("File") >= 0 || label.indexOf("SD") >= 0) return "icon.folder";
  if (label.indexOf("Firmware") >= 0) return "icon.download";
  if (label.indexOf("App") >= 0) return "icon.package";
  if (label.indexOf("Backend") >= 0 || label.indexOf("AI") >= 0) return "icon.cloud";
  if (label.indexOf("Power") >= 0 || label.indexOf("Sleep") >= 0 || label.indexOf("Boot") >= 0) return "icon.power";
  if (label.indexOf("Restart") >= 0 || label.indexOf("Reset") >= 0) return "icon.rotate-ccw";
  if (label.indexOf("Debug") >= 0) return "icon.activity";
  if (label.indexOf("Help") >= 0 || label.indexOf("Info") >= 0) return "icon.info";
  if (label.indexOf("Save") >= 0) return "icon.check";
  if (label.indexOf("Delete") >= 0) return "icon.circle-x";
  if (label.indexOf("Download") >= 0) return "icon.download";
  if (label.indexOf("Launch") >= 0) return "icon.circle-play";
  if (label.indexOf("RGB") >= 0) return "icon.sun";
  if (label.indexOf("Menu") >= 0) return "icon.layout-grid";
  return "icon.settings";
}
}

void FireOS::drawRow(uint8_t row, const String& label, bool selected,
                     const String& value, bool editing) {
  const int y = 62 + row * 25;
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  FireUI::menuRow(surface, y, label.c_str(), value.c_str(), selected, osMenuIcon(label));
  if (selected && editing) {
    ui.fillRect(10, y + 7, 3, 11, kOrange);
  }
}

void FireOS::drawLevelRow(uint8_t row, const String& label, uint8_t step,
                          uint8_t stepCount, bool selected, uint16_t accent,
                          bool editing) {
  const int y = 62 + row * 25;
  if (selected) drawSelection(10, y, 300, 25, editing ? kOrange : kCyan);
  else drawRounded(10, y, 300, 25, 7, kPanel, true);
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  FireUI::icon(surface, osMenuIcon(label), 18, y + 3, selected ? kCyan : kMuted, 19);
  FireUI::text(surface, 42, y + 5, label.c_str(), kText, "ui12", 108);
  constexpr int segments = 10;
  const uint8_t filled = stepCount <= 1 ? 0 : uint8_t(step * segments / (stepCount - 1));
  for (int segment = 0; segment < segments; ++segment) {
    const uint16_t color = segment < filled ? (editing ? kOrange : accent) : FireUI::Border;
    drawRounded(166 + segment * 13, y + 8, 10, 9, 2, color, true);
  }
}

void FireOS::drawText(int32_t x, int32_t y, const String& text, uint16_t color,
                      uint8_t size, uint16_t background) {
  (void)background;  // OS screens are freshly composed; text is transparent.
  const char* font = size >= 3 ? "title20" : size == 2 ? "ui16" : "ui12";
  const auto datum = ui.getTextDatum();
  const bool centered = datum == MC_DATUM;
  const bool right = datum == MR_DATUM || datum == TR_DATUM;
  const int available = right ? x - 10 : centered ? 2 * min<int>(x, 320 - x) - 20 : 310 - x;
  if (available <= 0) return;
  const int width = min<int>(available, FireUI::width(text.c_str(), font));
  if (width <= 0) return;
  const int left = right ? x - width : centered ? x - width / 2 : x;
  const int top = centered || datum == MR_DATUM ? y - FireUI::font(font).lineHeight / 2 : y;
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  FireUI::text(surface, left, top, text.c_str(), color, font, width,
               right ? 2 : centered ? 1 : 0);
}

#include "fire_os_evolution.inc"
#include "fire_os_ai_picker.inc"
#include "fire_os_download.inc"
#include "fire_os_local_qa.inc"
#include "fire_os_backend_settings.inc"
