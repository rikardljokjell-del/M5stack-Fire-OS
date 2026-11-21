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
  struct Host {
    void* context = nullptr;
    void (*displayClear)(void*, int) = nullptr;
    void (*displayCircle)(void*, int, int, int, int) = nullptr;
    void (*displayRect)(void*, int, int, int, int, int) = nullptr;
    void (*displayLine)(void*, int, int, int, int, int) = nullptr;
    void (*displayText)(void*, int, int, const char*, int) = nullptr;
    bool (*buttonPressed)(void*, const char*) = nullptr;
    void (*rgbSet)(void*, int, int, int, int) = nullptr;
    bool (*imuAccel)(void*, float*, float*, float*) = nullptr;
    uint32_t (*timeMillis)(void*) = nullptr;
  };

  static constexpr size_t kMaxSourceBytes = 100000;
  static constexpr size_t kMaxMemoryBytes = 131072;
  static constexpr uint32_t kMaxInstructionsPerCallback = 200000;
  static constexpr uint32_t kMaxCallbackMs = 12;
  static constexpr uint32_t kMaxRuntimeMs = 10000;

  bool begin(const Host& host);
  bool loadSource(const uint8_t* source, size_t length);
  void stop();
  bool update(uint32_t dtMs);
  bool button(const char* name, const char* action);

  bool running() const { return state_ == State::Running; }
  const String& lastError() const { return error_; }
  uint32_t instructionCount() const { return instructions_; }
  size_t memoryUsed() const { return memoryUsed_; }

 private:
  enum class State : uint8_t { Stopped, Running, Failed };

  lua_State* lua_ = nullptr;
  Host host_;
  State state_ = State::Stopped;
  String error_;
  uint32_t instructions_ = 0;
  uint32_t frameStarted_ = 0;
  uint32_t startedAt_ = 0;
  size_t memoryUsed_ = 0;

  static void* allocator(void* user, void* pointer, size_t oldSize,
                         size_t newSize);
  static void instructionHook(lua_State* state, lua_Debug* debug);
  static FireLuaRuntime* self(lua_State* state);
  static void registerApi(lua_State* state);
  static void registerBase(lua_State* state);
  static void registerMath(lua_State* state);
  static void removeUnsafeGlobals(lua_State* state);
  static bool checkColor(lua_State* state, int index);
  static int displayClear(lua_State* state);
  static int displayCircle(lua_State* state);
  static int displayRect(lua_State* state);
  static int displayLine(lua_State* state);
  static int displayText(lua_State* state);
  static int buttonPressed(lua_State* state);
  static int rgbSet(lua_State* state);
  static int imuAccel(lua_State* state);
  static int timeMillis(lua_State* state);
  static void setFunction(lua_State* state, const char* name, lua_CFunction fn);

  bool callVoid(const char* function, int argumentCount = 0);
  bool fail(const String& message);
  void clearState();
};
