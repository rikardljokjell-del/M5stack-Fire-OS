#pragma once

#include <Arduino.h>

extern "C" {
#include <lua.h>
}

// Small, cooperative Lua 5.4 host. Lua never receives direct hardware,
// filesystem, radio or OS handles; every operation is routed through these
// narrow callbacks owned by FIRE OS.
class FireLuaRuntime {
 public:
  struct JobSnapshot {
    struct FileEntry {
      String name;
      uint32_t sizeBytes = 0;
      bool directory = false;
    };
    enum ResultKind : uint8_t {
      None,
      I2cScan,
      Bytes,
      Write,
      Uart,
      Files,
      WifiStatus,
      WifiScan,
      BluetoothScan,
      Handle,
      Recording,
      Http
    };
    uint8_t state = 0;  // 0=pending, 1=ready, 2=failed, 3=cancelled
    ResultKind resultKind = None;
    String errorCode;
    uint16_t addresses[126] = {};
    uint16_t addressCount = 0;
    uint8_t bytes[512] = {};
    uint16_t byteCount = 0;
    String text;
    uint32_t written = 0;
    uint16_t handle = 0;
    uint16_t entryCount = 0;
    FileEntry entries[32];
    String ssid;
    String ip;
    int16_t rssi = 0;
    bool connected = false;
    uint32_t sizeBytes = 0;
    uint32_t sampleRate = 0;
    String path;
    int statusCode = 0;
  };

  struct Host {
    void* context = nullptr;
    void (*displayClear)(void*, int) = nullptr;
    void (*displayCircle)(void*, int, int, int, int) = nullptr;
    void (*displayRect)(void*, int, int, int, int, int) = nullptr;
    void (*displayLine)(void*, int, int, int, int, int) = nullptr;
    void (*displayText)(void*, int, int, const char*, int) = nullptr;
    void (*displayFillRect)(void*, int, int, int, int, int) = nullptr;
    void (*displayFillCircle)(void*, int, int, int, int) = nullptr;
    void (*displayPixel)(void*, int, int, int) = nullptr;
    void (*displayGrid)(void*, int, int, int, int, int, int,
                        const uint8_t*, size_t, const uint16_t*, size_t) = nullptr;
    bool (*buttonPressed)(void*, const char*) = nullptr;
    void (*rgbSet)(void*, int, int, int, int) = nullptr;
    bool (*imuAccel)(void*, float*, float*, float*) = nullptr;
    bool (*imuGyro)(void*, float*, float*, float*) = nullptr;
    bool (*imuTemperature)(void*, float*) = nullptr;
    uint32_t (*timeMillis)(void*) = nullptr;
    bool (*gpioMode)(void*, int, const char*, const char**) = nullptr;
    bool (*gpioRead)(void*, int, int*, const char**) = nullptr;
    bool (*gpioWrite)(void*, int, int, const char**) = nullptr;
    bool (*gpioRelease)(void*, int, const char**) = nullptr;
    bool (*pwmConfigure)(void*, int, int, int, const char**) = nullptr;
    bool (*pwmWrite)(void*, int, int, const char**) = nullptr;
    bool (*pwmStop)(void*, int, const char**) = nullptr;
    bool (*uartOpen)(void*, int, int, int, int, const char*, const char**) = nullptr;
    uint16_t (*uartRead)(void*, int, int, const char**) = nullptr;
    uint16_t (*uartWrite)(void*, int, const char*, size_t, const char**) = nullptr;
    bool (*uartClose)(void*, int, const char**) = nullptr;
    uint16_t (*i2cScan)(void*, int, const char**) = nullptr;
    uint16_t (*i2cRead)(void*, int, int, int, int, const char**) = nullptr;
    uint16_t (*i2cWrite)(void*, int, int, const uint8_t*, size_t,
                         const char**) = nullptr;
    bool (*adcRead)(void*, int, int*, const char**) = nullptr;
    bool (*dacWrite)(void*, int, int, const char**) = nullptr;
    bool (*dacStop)(void*, int, const char**) = nullptr;
    bool (*spiOpen)(void*, int, int, int, int, int, int, int,
                    const char**) = nullptr;
    uint16_t (*spiTransfer)(void*, int, const uint8_t*, size_t,
                            const char**) = nullptr;
    bool (*spiClose)(void*, int, const char**) = nullptr;
    uint16_t (*sdList)(void*, const char*, const char**) = nullptr;
    uint16_t (*sdRead)(void*, const char*, uint32_t, uint16_t,
                       const char**) = nullptr;
    uint16_t (*sdWrite)(void*, const char*, const char*, size_t, bool,
                        const char**) = nullptr;
    uint16_t (*sdRemove)(void*, const char*, const char**) = nullptr;
    bool (*sdMkdir)(void*, const char*, const char**) = nullptr;
    bool (*powerStatus)(void*, float*, float*, bool*, bool*) = nullptr;
    bool (*powerBrightness)(void*, int, const char**) = nullptr;
    uint16_t (*powerSleep)(void*, uint32_t, const char**) = nullptr;
    bool (*rtcNow)(void*, uint32_t*, int*, int*, int*, int*, int*, int*,
                   const char**) = nullptr;
    bool (*rtcSet)(void*, uint32_t, const char**) = nullptr;
    uint16_t (*speakerTone)(void*, int, int, int, const char**) = nullptr;
    uint16_t (*speakerPlay)(void*, const char*, int, const char**) = nullptr;
    bool (*speakerStop)(void*, const char**) = nullptr;
    bool (*jobPoll)(void*, uint16_t, JobSnapshot*) = nullptr;
    bool (*jobResult)(void*, uint16_t, JobSnapshot*) = nullptr;
    bool (*jobClose)(void*, uint16_t) = nullptr;
    bool (*jobCancel)(void*, uint16_t) = nullptr;
  };

  static constexpr size_t kMaxSourceBytes = 100000;
  static constexpr size_t kMaxMemoryBytes = 131072;
  static constexpr uint32_t kMaxInstructionsPerCallback = 200000;
  static constexpr uint32_t kMaxCallbackMs = 12;
  static constexpr uint32_t kMaxRuntimeMs = 10000;
  static constexpr uint32_t kDefaultRuntimeMs = kMaxRuntimeMs;

  bool begin(const Host& host);
  void setHardwareApi(bool enabled) { hardwareApi_ = enabled; }
  void setServiceMask(uint32_t mask) { serviceMask_ = mask; }
  void setMaxRuntimeMs(uint32_t maxRuntimeMs);
  bool loadSource(const uint8_t* source, size_t length);
  void stop();
  bool update(uint32_t dtMs);
  bool button(const char* name, const char* action);

  bool running() const { return state_ == State::Running; }
  const String& lastError() const { return error_; }
  uint32_t instructionCount() const { return instructions_; }
  size_t memoryUsed() const { return memoryUsed_; }
  uint32_t elapsedMs() const;
  uint32_t lastCallbackUs() const { return lastCallbackUs_; }
  uint32_t frameCount() const { return frames_; }
  size_t sourceBytes() const { return sourceBytes_; }
  static const char* hardwareApiContract();
  static const char* hardwareApiVersion() { return "fire-lua-0.2"; }
  const char* lastPhase() const;

 private:
  enum class State : uint8_t { Stopped, Running, Failed };

  lua_State* lua_ = nullptr;
  Host host_;
  State state_ = State::Stopped;
  String error_;
  uint32_t instructions_ = 0;
  uint32_t frameStarted_ = 0;
  uint32_t startedAt_ = 0;
  uint32_t maxRuntimeMs_ = kDefaultRuntimeMs;
  uint32_t callbackBudgetMs_ = kMaxCallbackMs;
  uint64_t callbackStartedUs_ = 0;
  uint32_t lastCallbackUs_ = 0;
  uint32_t frames_ = 0;
  size_t sourceBytes_ = 0;
  enum class CallbackPhase : uint8_t { None, Load, Init, Update, OnButton };
  CallbackPhase callbackPhase_ = CallbackPhase::None;
  size_t memoryUsed_ = 0;
  bool hardwareApi_ = false;
  uint32_t serviceMask_ = 0x1FU;
  uint16_t ioCalls_ = 0;
  uint16_t ioBytes_ = 0;
  uint16_t textBytes_ = 0;

  static void* allocator(void* user, void* pointer, size_t oldSize,
                         size_t newSize);
  static void instructionHook(lua_State* state, lua_Debug* debug);
  static FireLuaRuntime* self(lua_State* state);
  static void registerApi(lua_State* state);
  static void registerBase(lua_State* state);
  static void registerMath(lua_State* state);
  static void registerSafeHelpers(lua_State* state);
  static void removeUnsafeGlobals(lua_State* state);
  static bool checkColor(lua_State* state, int index);
  static int displayClear(lua_State* state);
  static int displayCircle(lua_State* state);
  static int displayRect(lua_State* state);
  static int displayLine(lua_State* state);
  static int displayText(lua_State* state);
  static int displayFillRect(lua_State* state);
  static int displayFillCircle(lua_State* state);
  static int displayPixel(lua_State* state);
  static int displayGrid(lua_State* state);
  static int buttonPressed(lua_State* state);
  static int rgbSet(lua_State* state);
  static int imuAccel(lua_State* state);
  static int imuGyro(lua_State* state);
  static int imuTemperature(lua_State* state);
  static int timeMillis(lua_State* state);
  static int gpioMode(lua_State* state);
  static int gpioRead(lua_State* state);
  static int gpioWrite(lua_State* state);
  static int gpioRelease(lua_State* state);
  static int pwmConfigure(lua_State* state);
  static int pwmWrite(lua_State* state);
  static int pwmStop(lua_State* state);
  static int uartOpen(lua_State* state);
  static int uartRead(lua_State* state);
  static int uartWrite(lua_State* state);
  static int uartClose(lua_State* state);
  static int i2cScan(lua_State* state);
  static int i2cRead(lua_State* state);
  static int i2cWrite(lua_State* state);
  static int adcRead(lua_State* state);
  static int dacWrite(lua_State* state);
  static int dacStop(lua_State* state);
  static int spiOpen(lua_State* state);
  static int spiTransfer(lua_State* state);
  static int spiClose(lua_State* state);
  static int sdList(lua_State* state);
  static int sdRead(lua_State* state);
  static int sdWrite(lua_State* state);
  static int sdRemove(lua_State* state);
  static int sdMkdir(lua_State* state);
  static int powerStatus(lua_State* state);
  static int powerBrightness(lua_State* state);
  static int powerSleep(lua_State* state);
  static int rtcNow(lua_State* state);
  static int rtcSet(lua_State* state);
  static int speakerTone(lua_State* state);
  static int speakerPlay(lua_State* state);
  static int speakerStop(lua_State* state);
  static int jobsPoll(lua_State* state);
  static int jobsResult(lua_State* state);
  static int jobsClose(lua_State* state);
  static int jobsCancel(lua_State* state);
  static void setFunction(lua_State* state, const char* name, lua_CFunction fn);
  static bool serviceAllowed(const FireLuaRuntime* runtime, uint32_t bit);
  bool chargeIo(size_t bytes, bool text = false);
  static int pushError(lua_State* state, const char* error);

  bool callVoid(const char* function, int argumentCount = 0);
  void beginCallback(CallbackPhase phase, uint32_t budgetMs);
  void finishCallback();
  bool fail(const String& message);
  void clearState();
};
