#include "fire_lua_runtime.h"

#include <esp_heap_caps.h>
#include <esp_timer.h>
#include <math.h>
#include <string.h>
extern "C" {
#include <lauxlib.h>
}

namespace {
constexpr int kDisplayWidth = 320;
constexpr int kDisplayHeight = 240;
constexpr uint32_t kServiceDisplay = 1u << 0;
constexpr uint32_t kServiceButtons = 1u << 1;
constexpr uint32_t kServiceRgb = 1u << 2;
constexpr uint32_t kServiceImu = 1u << 3;
constexpr uint32_t kServiceTime = 1u << 4;
constexpr uint32_t kServiceJobs = 1u << 5;
constexpr uint32_t kServiceGpio = 1u << 6;
constexpr uint32_t kServicePwm = 1u << 7;
constexpr uint32_t kServiceI2c = 1u << 8;
constexpr uint32_t kServiceUart = 1u << 9;
// Register-backed service bits. Services are only placed in the advertised
// capability set when their OS callbacks are wired into the runtime.
constexpr uint32_t kServiceAdc = 1u << 10;
constexpr uint32_t kServiceDac = 1u << 11;
constexpr uint32_t kServiceSpi = 1u << 12;
constexpr uint32_t kServiceWifi = 1u << 13;
constexpr uint32_t kServiceBluetooth = 1u << 14;
constexpr uint32_t kServiceMic = 1u << 15;
constexpr uint32_t kServiceSpeaker = 1u << 16;
constexpr uint32_t kServiceSd = 1u << 17;
constexpr uint32_t kServicePower = 1u << 18;
constexpr uint32_t kServiceRtc = 1u << 19;

int boundedInt(lua_State* state, int index, int minimum, int maximum) {
  const lua_Integer value = luaL_checkinteger(state, index);
  return static_cast<int>(constrain(static_cast<long>(value), minimum, maximum));
}

// Hardware API arguments are contract values, not UI sliders.  Clamping an
// invalid value would silently address a different pin/register and makes the
// generated-app contract impossible to reason about.  Keep boundedInt() for
// Lua helper semantics, but reject out-of-range hardware arguments explicitly.
int strictInt(lua_State* state, int index, int minimum, int maximum) {
  const lua_Integer value = luaL_checkinteger(state, index);
  if (value < minimum || value > maximum) {
    luaL_argerror(state, index, "value outside contract range");
  }
  return static_cast<int>(value);
}

const char* checkedString(lua_State* state, int index) {
  return luaL_checklstring(state, index, nullptr);
}
}  // namespace

const char* FireLuaRuntime::hardwareApiContract() {
  return "0b29618a077256268c1dc78512ccf2700517e6c162cbe72f2f4a171dcfc3cd40";
}

void* FireLuaRuntime::allocator(void* user, void* pointer, size_t oldSize,
                                size_t newSize) {
  auto* runtime = static_cast<FireLuaRuntime*>(user);
  // Lua passes a type tag in oldSize for a fresh allocation; it is not
  // allocated-byte accounting until a real pointer exists.
  if (!pointer) oldSize = 0;
  if (newSize == 0) {
    if (pointer) {
      heap_caps_free(pointer);
      if (runtime) runtime->memoryUsed_ -= min(runtime->memoryUsed_, oldSize);
    }
    return nullptr;
  }

  if (runtime && newSize > oldSize &&
      runtime->memoryUsed_ + (newSize - oldSize) >
          FireLuaRuntime::kMaxMemoryBytes) {
    return nullptr;
  }

  void* result = heap_caps_realloc(pointer, newSize,
                                   MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!result) {
    result = heap_caps_realloc(pointer, newSize, MALLOC_CAP_8BIT);
  }
  if (runtime && result) {
    if (newSize >= oldSize) {
      runtime->memoryUsed_ += newSize - oldSize;
    } else {
      runtime->memoryUsed_ -= min(runtime->memoryUsed_, oldSize - newSize);
    }
  }
  return result;
}

FireLuaRuntime* FireLuaRuntime::self(lua_State* state) {
  auto** pointer = static_cast<FireLuaRuntime**>(lua_getextraspace(state));
  return pointer ? *pointer : nullptr;
}

void FireLuaRuntime::instructionHook(lua_State* state, lua_Debug*) {
  auto* runtime = self(state);
  if (!runtime) return;
  runtime->instructions_ += 1000;
  if (runtime->instructions_ > kMaxInstructionsPerCallback)
    luaL_error(state, "app instruction budget exceeded");
  if (runtime->callbackBudgetMs_ > 0 &&
       esp_timer_get_time() - runtime->callbackStartedUs_ >
           static_cast<int64_t>(runtime->callbackBudgetMs_) * 1000) {
    luaL_error(state, "app callback time budget exceeded");
  }
}

void FireLuaRuntime::setFunction(lua_State* state, const char* name,
                                 lua_CFunction fn) {
  lua_pushcfunction(state, fn);
  lua_setfield(state, -2, name);
}

bool FireLuaRuntime::serviceAllowed(const FireLuaRuntime* runtime,
                                    uint32_t bit) {
  return runtime && (runtime->serviceMask_ & bit) != 0;
}

bool FireLuaRuntime::chargeIo(size_t bytes, bool text) {
  if (++ioCalls_ > 64 || ioBytes_ + bytes > 2048) return false;
  if (text && textBytes_ + bytes > 256) return false;
  ioBytes_ = static_cast<uint16_t>(ioBytes_ + min<size_t>(bytes, 65535));
  if (text) textBytes_ = static_cast<uint16_t>(textBytes_ + min<size_t>(bytes, 65535));
  return true;
}

int FireLuaRuntime::pushError(lua_State* state, const char* error) {
  lua_pushnil(state);
  lua_pushstring(state, error ? error : "unavailable");
  return 2;
}

void FireLuaRuntime::registerApi(lua_State* state) {
  auto* runtime = self(state);
  if (!runtime) return;

  lua_newtable(state);  // fire

  if (serviceAllowed(runtime, kServiceDisplay)) {
    lua_newtable(state);  // fire.display
    setFunction(state, "clear", displayClear);
    setFunction(state, "circle", displayCircle);
    setFunction(state, "rect", displayRect);
    setFunction(state, "line", displayLine);
    setFunction(state, "text", displayText);
    if (runtime->hardwareApi_) {
      setFunction(state, "fill_rect", displayFillRect);
      setFunction(state, "fill_circle", displayFillCircle);
      setFunction(state, "pixel", displayPixel);
      setFunction(state, "grid", displayGrid);
    }
    lua_setfield(state, -2, "display");
  }
  if (serviceAllowed(runtime, kServiceButtons)) {
    lua_newtable(state);
    setFunction(state, "pressed", buttonPressed);
    lua_setfield(state, -2, "buttons");
  }
  if (serviceAllowed(runtime, kServiceRgb)) {
    lua_newtable(state);
    setFunction(state, "set", rgbSet);
    lua_setfield(state, -2, "rgb");
  }
  if (serviceAllowed(runtime, kServiceImu)) {
    lua_newtable(state);
    setFunction(state, "accel", imuAccel);
    if (runtime->hardwareApi_) {
      setFunction(state, "gyro", imuGyro);
      setFunction(state, "temperature", imuTemperature);
    }
    lua_setfield(state, -2, "imu");
  }
  if (serviceAllowed(runtime, kServiceTime)) {
    lua_newtable(state);
    setFunction(state, "millis", timeMillis);
    lua_setfield(state, -2, "time");
  }
  if (runtime->hardwareApi_ && serviceAllowed(runtime, kServiceJobs)) {
    lua_newtable(state);
    setFunction(state, "poll", jobsPoll);
    setFunction(state, "result", jobsResult);
    setFunction(state, "close", jobsClose);
    setFunction(state, "cancel", jobsCancel);
    lua_setfield(state, -2, "jobs");
  }
  if (runtime->hardwareApi_ && serviceAllowed(runtime, kServiceGpio)) {
    lua_newtable(state);
    setFunction(state, "mode", gpioMode);
    setFunction(state, "read", gpioRead);
    setFunction(state, "write", gpioWrite);
    setFunction(state, "release", gpioRelease);
    lua_setfield(state, -2, "gpio");
  }
  if (runtime->hardwareApi_ && serviceAllowed(runtime, kServicePwm)) {
    lua_newtable(state);
    setFunction(state, "configure", pwmConfigure);
    setFunction(state, "write", pwmWrite);
    setFunction(state, "stop", pwmStop);
    lua_setfield(state, -2, "pwm");
  }
  if (runtime->hardwareApi_ && serviceAllowed(runtime, kServiceI2c)) {
    lua_newtable(state);
    setFunction(state, "scan", i2cScan);
    setFunction(state, "read", i2cRead);
    setFunction(state, "write", i2cWrite);
    lua_setfield(state, -2, "i2c");
  }
  if (runtime->hardwareApi_ && serviceAllowed(runtime, kServiceUart)) {
    lua_newtable(state);
    setFunction(state, "open", uartOpen);
    setFunction(state, "read", uartRead);
    setFunction(state, "write", uartWrite);
    setFunction(state, "close", uartClose);
    lua_setfield(state, -2, "uart");
  }
  if (runtime->hardwareApi_ && serviceAllowed(runtime, kServiceAdc)) {
    lua_newtable(state);
    setFunction(state, "read", adcRead);
    lua_setfield(state, -2, "adc");
  }
  if (runtime->hardwareApi_ && serviceAllowed(runtime, kServiceDac)) {
    lua_newtable(state);
    setFunction(state, "write", dacWrite);
    setFunction(state, "stop", dacStop);
    lua_setfield(state, -2, "dac");
  }
  if (runtime->hardwareApi_ && serviceAllowed(runtime, kServiceSpi)) {
    lua_newtable(state);
    setFunction(state, "open", spiOpen);
    setFunction(state, "transfer", spiTransfer);
    setFunction(state, "close", spiClose);
    lua_setfield(state, -2, "spi");
  }
  if (runtime->hardwareApi_ && serviceAllowed(runtime, kServiceSd)) {
    lua_newtable(state);
    setFunction(state, "list", sdList);
    setFunction(state, "read", sdRead);
    setFunction(state, "write", sdWrite);
    setFunction(state, "remove", sdRemove);
    setFunction(state, "mkdir", sdMkdir);
    lua_setfield(state, -2, "sd");
  }
  if (runtime->hardwareApi_ && serviceAllowed(runtime, kServiceRtc)) {
    lua_newtable(state);
    setFunction(state, "now", rtcNow);
    setFunction(state, "set", rtcSet);
    lua_setfield(state, -2, "rtc");
  }
  if (runtime->hardwareApi_ && serviceAllowed(runtime, kServiceSpeaker)) {
    lua_newtable(state);
    setFunction(state, "tone", speakerTone);
    setFunction(state, "play", speakerPlay);
    setFunction(state, "stop", speakerStop);
    lua_setfield(state, -2, "speaker");
  }

  lua_setglobal(state, "fire");
}

namespace {
int luaBaseType(lua_State* state) {
  lua_pushstring(state, luaL_typename(state, 1));
  return 1;
}

int luaBaseToNumber(lua_State* state) {
  int isNumber = 0;
  const lua_Number value = lua_tonumberx(state, 1, &isNumber);
  if (!isNumber) {
    lua_pushnil(state);
  } else {
    lua_pushnumber(state, value);
  }
  return 1;
}

int luaBaseToString(lua_State* state) {
  luaL_tolstring(state, 1, nullptr);
  return 1;
}

int luaBaseNext(lua_State* state) {
  luaL_checktype(state, 1, LUA_TTABLE);
  lua_settop(state, 2);  // next(table) has an implicit nil key.
  if (lua_next(state, 1) == 0) return 0;
  return 2;
}

int luaBasePairs(lua_State* state) {
  luaL_checktype(state, 1, LUA_TTABLE);
  lua_pushcfunction(state, luaBaseNext);
  lua_pushvalue(state, 1);
  lua_pushnil(state);
  return 3;
}

int luaBaseIpairsNext(lua_State* state) {
  lua_Integer index = lua_tointeger(state, lua_upvalueindex(2)) + 1;
  lua_pushinteger(state, index);
  lua_replace(state, lua_upvalueindex(2));
  lua_pushvalue(state, lua_upvalueindex(1));
  lua_pushinteger(state, index);
  lua_gettable(state, -2);
  lua_remove(state, -2);
  if (lua_isnil(state, -1)) {
    lua_settop(state, 0);
    return 0;
  }
  return 2;
}

int luaBaseIpairs(lua_State* state) {
  luaL_checktype(state, 1, LUA_TTABLE);
  lua_pushvalue(state, 1);
  lua_pushinteger(state, 0);
  lua_pushcclosure(state, luaBaseIpairsNext, 2);
  lua_pushvalue(state, 1);
  lua_pushinteger(state, 0);
  return 3;
}
}  // namespace

void FireLuaRuntime::registerBase(lua_State* state) {
  lua_pushglobaltable(state);
  setFunction(state, "type", luaBaseType);
  setFunction(state, "tonumber", luaBaseToNumber);
  setFunction(state, "tostring", luaBaseToString);
  setFunction(state, "next", luaBaseNext);
  setFunction(state, "pairs", luaBasePairs);
  setFunction(state, "ipairs", luaBaseIpairs);
  lua_pop(state, 1);
}

namespace {
int luaStringLen(lua_State* state) {
  size_t length = 0;
  luaL_checklstring(state, 1, &length);
  lua_pushinteger(state, static_cast<lua_Integer>(length));
  return 1;
}

int luaStringSub(lua_State* state) {
  const char* value = luaL_checkstring(state, 1);
  const int start = boundedInt(state, 2, -512, 512);
  const int end = lua_gettop(state) >= 3 ? boundedInt(state, 3, -512, 512) : -1;
  String text(value);
  const int length = static_cast<int>(text.length());
  int first = start >= 0 ? start : length + start + 1;
  int last = end == -1 ? length : (end >= 0 ? end : length + end + 1);
  first = max(1, first);
  last = min(length, last);
  if (first > last) {
    lua_pushliteral(state, "");
  } else {
    lua_pushlstring(state, text.substring(first - 1, last).c_str(),
                    static_cast<size_t>(last - first + 1));
  }
  return 1;
}

int luaStringByte(lua_State* state) {
  const char* value = luaL_checkstring(state, 1);
  const int index = boundedInt(state, 2, 1, 512);
  if (index > static_cast<int>(strlen(value))) {
    lua_pushnil(state);
    return 1;
  }
  lua_pushinteger(state, static_cast<unsigned char>(value[index - 1]));
  return 1;
}

int luaStringChar(lua_State* state) {
  const int count = lua_gettop(state);
  if (count > 16) return luaL_error(state, "string.char limit");
  char buffer[17] = {};
  for (int index = 1; index <= count; ++index)
    buffer[index - 1] = static_cast<char>(boundedInt(state, index, 0, 255));
  lua_pushlstring(state, buffer, count);
  return 1;
}

int luaTableConcat(lua_State* state) {
  luaL_checktype(state, 1, LUA_TTABLE);
  const char* separator = lua_gettop(state) >= 2 ? luaL_checkstring(state, 2) : "";
  String output;
  for (int index = 1; index <= 128; ++index) {
    lua_geti(state, 1, index);
    if (lua_isnil(state, -1)) {
      lua_pop(state, 1);
      break;
    }
    if (!lua_isstring(state, -1)) return luaL_error(state, "table.concat value");
    if (output.length() > 0) output += separator;
    output += lua_tostring(state, -1);
    lua_pop(state, 1);
    if (output.length() > 512) return luaL_error(state, "table.concat too long");
  }
  lua_pushlstring(state, output.c_str(), output.length());
  return 1;
}

int luaTableInsert(lua_State* state) {
  luaL_checktype(state, 1, LUA_TTABLE);
  const int top = static_cast<int>(lua_rawlen(state, 1));
  if (top >= 128) return luaL_error(state, "table limit");
  const int position = lua_gettop(state) >= 3 ? boundedInt(state, 2, 1, top + 1) : top + 1;
  if (lua_gettop(state) >= 3) {
    for (int index = top + 1; index > position; --index) {
      lua_geti(state, 1, index - 1);
      lua_seti(state, 1, index);
    }
    lua_pushvalue(state, 3);
    lua_seti(state, 1, position);
  } else {
    lua_pushvalue(state, 2);
    lua_seti(state, 1, top + 1);
  }
  return 0;
}

int luaTableRemove(lua_State* state) {
  luaL_checktype(state, 1, LUA_TTABLE);
  const int top = static_cast<int>(lua_rawlen(state, 1));
  if (top == 0) {
    lua_pushnil(state);
    return 1;
  }
  const int position = lua_gettop(state) >= 2 ? boundedInt(state, 2, 1, top) : top;
  lua_geti(state, 1, position);
  for (int index = position; index < top; ++index) {
    lua_geti(state, 1, index + 1);
    lua_seti(state, 1, index);
  }
  lua_pushnil(state);
  lua_seti(state, 1, top);
  return 1;
}
}  // namespace

void FireLuaRuntime::registerSafeHelpers(lua_State* state) {
  lua_newtable(state);
  setFunction(state, "len", luaStringLen);
  setFunction(state, "sub", luaStringSub);
  setFunction(state, "byte", luaStringByte);
  setFunction(state, "char", luaStringChar);
  lua_setglobal(state, "string");
  lua_newtable(state);
  setFunction(state, "concat", luaTableConcat);
  setFunction(state, "insert", luaTableInsert);
  setFunction(state, "remove", luaTableRemove);
  lua_setglobal(state, "table");
}

namespace {
int luaMathAbs(lua_State* state) {
  lua_pushnumber(state, fabsf(static_cast<float>(luaL_checknumber(state, 1))));
  return 1;
}

int luaMathFloor(lua_State* state) {
  lua_pushnumber(state, floorf(static_cast<float>(luaL_checknumber(state, 1))));
  return 1;
}

int luaMathCeil(lua_State* state) {
  lua_pushnumber(state, ceilf(static_cast<float>(luaL_checknumber(state, 1))));
  return 1;
}

int luaMathSqrt(lua_State* state) {
  lua_pushnumber(state, sqrtf(static_cast<float>(luaL_checknumber(state, 1))));
  return 1;
}

int luaMathSin(lua_State* state) {
  lua_pushnumber(state, sinf(static_cast<float>(luaL_checknumber(state, 1))));
  return 1;
}

int luaMathCos(lua_State* state) {
  lua_pushnumber(state, cosf(static_cast<float>(luaL_checknumber(state, 1))));
  return 1;
}

int luaMathMin(lua_State* state) {
  const int count = lua_gettop(state);
  if (count < 1) return luaL_error(state, "math.min needs an argument");
  lua_Number value = luaL_checknumber(state, 1);
  for (int index = 2; index <= count; ++index)
    value = min(value, luaL_checknumber(state, index));
  lua_pushnumber(state, value);
  return 1;
}

int luaMathMax(lua_State* state) {
  const int count = lua_gettop(state);
  if (count < 1) return luaL_error(state, "math.max needs an argument");
  lua_Number value = luaL_checknumber(state, 1);
  for (int index = 2; index <= count; ++index)
    value = max(value, luaL_checknumber(state, index));
  lua_pushnumber(state, value);
  return 1;
}
}  // namespace

void FireLuaRuntime::registerMath(lua_State* state) {
  lua_newtable(state);
  setFunction(state, "abs", luaMathAbs);
  setFunction(state, "floor", luaMathFloor);
  setFunction(state, "ceil", luaMathCeil);
  setFunction(state, "sqrt", luaMathSqrt);
  setFunction(state, "sin", luaMathSin);
  setFunction(state, "cos", luaMathCos);
  setFunction(state, "min", luaMathMin);
  setFunction(state, "max", luaMathMax);
  lua_pushnumber(state, 3.14159265358979323846f);
  lua_setfield(state, -2, "pi");
  lua_setglobal(state, "math");
}

void FireLuaRuntime::removeUnsafeGlobals(lua_State* state) {
  static const char* const unsafe[] = {
      "collectgarbage", "dofile", "load",       "loadfile", "print",
      "require",        "select", "setmetatable", "getmetatable", "rawget",
      "rawset",         "rawlen", "rawequal",    "pcall",      "xpcall",
      nullptr};
  for (const char* const* name = unsafe; *name; ++name) {
    lua_pushnil(state);
    lua_setglobal(state, *name);
  }
  lua_pushnil(state);
  lua_setglobal(state, "io");
  lua_pushnil(state);
  lua_setglobal(state, "os");
  lua_pushnil(state);
  lua_setglobal(state, "debug");
  lua_pushnil(state);
  lua_setglobal(state, "package");
  lua_pushnil(state);
  lua_setglobal(state, "coroutine");
}

bool FireLuaRuntime::begin(const Host& host) {
  stop();
  instructions_ = lastCallbackUs_ = maxCallbackUs_ = 0;
  host_ = host;
  lua_ = lua_newstate(allocator, this);
  if (!lua_) return fail("Lua memory unavailable");
  auto** pointer = static_cast<FireLuaRuntime**>(lua_getextraspace(lua_));
  *pointer = this;

  // Only the small, safe subset needed by generated apps is exposed.
  registerBase(lua_);
  registerMath(lua_);
  if (hardwareApi_) registerSafeHelpers(lua_);
  removeUnsafeGlobals(lua_);
  registerApi(lua_);
  lua_sethook(lua_, instructionHook, LUA_MASKCOUNT, 1000);
  state_ = State::Stopped;
  error_ = "";
  return true;
}

void FireLuaRuntime::setMaxRuntimeMs(uint32_t maxRuntimeMs) {
  // Zero is the explicit unlimited-until-user-exit profile. Positive values
  // remain bounded legacy lifetimes and may never exceed the advertised
  // safety ceiling.
  maxRuntimeMs_ = min<uint32_t>(maxRuntimeMs, kMaxRuntimeMs);
}

void FireLuaRuntime::beginCallback(CallbackPhase phase, uint32_t budgetMs) {
  callbackPhase_ = phase;
  callbackBudgetMs_ = budgetMs;
  frameStarted_ = millis();
  callbackStartedUs_ = static_cast<uint64_t>(esp_timer_get_time());
  ioCalls_ = 0;
  ioBytes_ = 0;
  textBytes_ = 0;
}

bool FireLuaRuntime::finishCallback() {
  const int64_t elapsed = esp_timer_get_time() -
                          static_cast<int64_t>(callbackStartedUs_);
  const int64_t bounded = elapsed < 0 ? 0 : elapsed > 60000000 ? 60000000 : elapsed;
  lastCallbackUs_ = static_cast<uint32_t>(bounded);
  maxCallbackUs_ = max(maxCallbackUs_, lastCallbackUs_);
  // A native host call does not execute Lua instructions. Check again after
  // return, even when fewer than 1000 further VM instructions were executed.
  if (callbackBudgetMs_ && elapsed > static_cast<int64_t>(callbackBudgetMs_) * 1000) {
    error_ = "app callback time budget exceeded";
    state_ = State::Failed;
    return false;
  }
  return true;
}

uint32_t FireLuaRuntime::elapsedMs() const {
  return startedAt_ == 0 ? 0 : millis() - startedAt_;
}

const char* FireLuaRuntime::lastPhase() const {
  switch (callbackPhase_) {
    case CallbackPhase::Load:
      return "load";
    case CallbackPhase::Init:
      return "init";
    case CallbackPhase::Update:
      return "update";
    case CallbackPhase::OnButton:
      return "on_button";
    default:
      return nullptr;
  }
}

bool FireLuaRuntime::loadSource(const uint8_t* source, size_t length) {
  if (!lua_) return fail("vm_not_initialized");
  if (!source || length == 0) return fail("source_empty");
  if (length > kMaxSourceBytes) return fail("source_size");
  sourceBytes_ = length;
  clearState();
  beginCallback(CallbackPhase::Load, 1000);
  const int loadResult = luaL_loadbufferx(
      lua_, reinterpret_cast<const char*>(source), length, "main.lua", "t");
  finishCallback();
  if (loadResult != LUA_OK) {
    return fail(String("Lua syntax: ") + lua_tostring(lua_, -1));
  }
  if (lastCallbackUs_ > 1000000) return fail("source_load_budget_exceeded");
  beginCallback(CallbackPhase::Init, 250);
  if (lua_pcall(lua_, 0, 0, 0) != LUA_OK) {
    finishCallback();
    return fail(String("Lua init chunk: ") + lua_tostring(lua_, -1));
  }
  if (!finishCallback()) return false;
  lua_getglobal(lua_, "init");
  if (!lua_isfunction(lua_, -1)) {
    lua_pop(lua_, 1);
    return fail("Lua app requires init()");
  }
  beginCallback(CallbackPhase::Init, 250);
  if (lua_pcall(lua_, 0, 0, 0) != LUA_OK) {
    finishCallback();
    return fail(String("Lua init: ") + lua_tostring(lua_, -1));
  }
  if (!finishCallback()) return false;
  lua_getglobal(lua_, "update");
  const bool hasUpdate = lua_isfunction(lua_, -1);
  lua_pop(lua_, 1);
  if (!hasUpdate) return fail("Lua app requires update(dt_ms)");
  state_ = State::Running;
  startedAt_ = millis();
  callbackPhase_ = CallbackPhase::None;
  callbackBudgetMs_ = kMaxCallbackMs;
  frames_ = 0;
  error_ = "";
  return true;
}

void FireLuaRuntime::clearState() {
  if (!lua_) return;
  lua_pushglobaltable(lua_);
  lua_pushnil(lua_);
  lua_setfield(lua_, -2, "init");
  lua_pushnil(lua_);
  lua_setfield(lua_, -2, "update");
  lua_pushnil(lua_);
  lua_setfield(lua_, -2, "on_button");
  lua_pop(lua_, 1);
}

void FireLuaRuntime::stop() {
  state_ = State::Stopped;
  if (lua_) {
    lua_close(lua_);
    lua_ = nullptr;
  }
  memoryUsed_ = 0;
  instructions_ = 0;
  startedAt_ = 0;
  maxRuntimeMs_ = kDefaultRuntimeMs;
  callbackBudgetMs_ = kMaxCallbackMs;
  callbackStartedUs_ = 0;
  frames_ = 0;
  sourceBytes_ = 0;
  callbackPhase_ = CallbackPhase::None;
  error_ = "";
}

bool FireLuaRuntime::callVoid(const char* function, int argumentCount) {
  if (!lua_) return fail("Lua runtime is not initialized");
  lua_getglobal(lua_, function);
  if (!lua_isfunction(lua_, -1)) {
    lua_pop(lua_, 1);
    return true;
  }
  // update() pushes its argument before calling this helper. Move the
  // function below those arguments so lua_pcall sees [function, args...].
  if (argumentCount > 0) lua_insert(lua_, -argumentCount - 1);
  beginCallback(CallbackPhase::Update, kMaxCallbackMs);
  ++frames_;
  if (lua_pcall(lua_, argumentCount, 0, 0) != LUA_OK) {
    finishCallback();
    return fail(String("Lua ") + function + ": " + lua_tostring(lua_, -1));
  }
  return finishCallback();
}

bool FireLuaRuntime::update(uint32_t dtMs) {
  if (state_ != State::Running) return state_ != State::Failed;
  if (maxRuntimeMs_ > 0 && millis() - startedAt_ > maxRuntimeMs_)
    return fail("Lua app runtime limit exceeded");
  instructions_ = 0;
  frameStarted_ = millis();
  lua_pushinteger(lua_, static_cast<lua_Integer>(dtMs));
  if (!callVoid("update", 1)) return false;
  return true;
}

bool FireLuaRuntime::button(const char* name, const char* action) {
  if (state_ != State::Running) return state_ != State::Failed;
  lua_getglobal(lua_, "on_button");
  if (!lua_isfunction(lua_, -1)) {
    lua_pop(lua_, 1);
    return true;
  }
  lua_pushstring(lua_, name);
  lua_pushstring(lua_, action);
  beginCallback(CallbackPhase::OnButton, kMaxCallbackMs);
  if (lua_pcall(lua_, 2, 0, 0) != LUA_OK) {
    finishCallback();
    return fail(String("Lua on_button: ") + lua_tostring(lua_, -1));
  }
  return finishCallback();
}

bool FireLuaRuntime::fail(const String& message) {
  error_ = message;
  state_ = State::Failed;
  if (lua_ && lua_gettop(lua_) > 0) lua_settop(lua_, 0);
  return false;
}

bool FireLuaRuntime::checkColor(lua_State* state, int index) {
  const lua_Integer value = luaL_checkinteger(state, index);
  return value >= 0 && value <= 65535;
}

int FireLuaRuntime::displayClear(lua_State* state) {
  auto* runtime = self(state);
  const int color = strictInt(state, 1, 0, 65535);
  if (!runtime->chargeIo(1)) return luaL_error(state, "display io budget exceeded");
  if (runtime->host_.displayClear) runtime->host_.displayClear(runtime->host_.context, color);
  return 0;
}

int FireLuaRuntime::displayCircle(lua_State* state) {
  auto* runtime = self(state);
  const int x = strictInt(state, 1, 0, kDisplayWidth - 1);
  const int y = strictInt(state, 2, 0, kDisplayHeight - 1);
  const int radius = strictInt(state, 3, 0, 160);
  if (!checkColor(state, 4)) return luaL_error(state, "invalid color");
  if (!runtime->chargeIo(1)) return luaL_error(state, "display io budget exceeded");
  const int color = static_cast<int>(lua_tointeger(state, 4));
  if (runtime->host_.displayCircle) runtime->host_.displayCircle(runtime->host_.context, x, y, radius, color);
  return 0;
}

int FireLuaRuntime::displayRect(lua_State* state) {
  auto* runtime = self(state);
  const int x = strictInt(state, 1, 0, kDisplayWidth - 1);
  const int y = strictInt(state, 2, 0, kDisplayHeight - 1);
  const int width = strictInt(state, 3, 0, kDisplayWidth);
  const int height = strictInt(state, 4, 0, kDisplayHeight);
  if (!checkColor(state, 5)) return luaL_error(state, "invalid color");
  if (!runtime->chargeIo(1)) return luaL_error(state, "display io budget exceeded");
  const int color = static_cast<int>(lua_tointeger(state, 5));
  if (runtime->host_.displayRect) runtime->host_.displayRect(runtime->host_.context, x, y, width, height, color);
  return 0;
}

int FireLuaRuntime::displayLine(lua_State* state) {
  auto* runtime = self(state);
  const int x1 = strictInt(state, 1, 0, kDisplayWidth - 1);
  const int y1 = strictInt(state, 2, 0, kDisplayHeight - 1);
  const int x2 = strictInt(state, 3, 0, kDisplayWidth - 1);
  const int y2 = strictInt(state, 4, 0, kDisplayHeight - 1);
  if (!checkColor(state, 5)) return luaL_error(state, "invalid color");
  if (!runtime->chargeIo(1)) return luaL_error(state, "display io budget exceeded");
  const int color = static_cast<int>(lua_tointeger(state, 5));
  if (runtime->host_.displayLine) runtime->host_.displayLine(runtime->host_.context, x1, y1, x2, y2, color);
  return 0;
}

int FireLuaRuntime::displayText(lua_State* state) {
  auto* runtime = self(state);
  const int x = strictInt(state, 1, 0, kDisplayWidth - 1);
  const int y = strictInt(state, 2, 0, kDisplayHeight - 1);
  size_t textLength = 0;
  const char* text = luaL_checklstring(state, 3, &textLength);
  if (textLength > 80) return luaL_error(state, "text too long");
  if (!runtime->chargeIo(textLength, true))
    return luaL_error(state, "display io budget exceeded");
  if (!checkColor(state, 4)) return luaL_error(state, "invalid color");
  if (runtime->host_.displayText) runtime->host_.displayText(runtime->host_.context, x, y, text, static_cast<int>(lua_tointeger(state, 4)));
  return 0;
}

int FireLuaRuntime::displayFillRect(lua_State* state) {
  auto* runtime = self(state);
  const int x = strictInt(state, 1, 0, kDisplayWidth - 1);
  const int y = strictInt(state, 2, 0, kDisplayHeight - 1);
  const int width = strictInt(state, 3, 1, kDisplayWidth);
  const int height = strictInt(state, 4, 1, kDisplayHeight);
  if (!checkColor(state, 5)) return luaL_error(state, "invalid color");
  if (!runtime->chargeIo(1)) return luaL_error(state, "display io budget exceeded");
  if (runtime->host_.displayFillRect)
    runtime->host_.displayFillRect(runtime->host_.context, x, y, width, height,
                                   static_cast<int>(lua_tointeger(state, 5)));
  return 0;
}

int FireLuaRuntime::displayFillCircle(lua_State* state) {
  auto* runtime = self(state);
  const int x = strictInt(state, 1, 0, kDisplayWidth - 1);
  const int y = strictInt(state, 2, 0, kDisplayHeight - 1);
  const int radius = strictInt(state, 3, 0, 160);
  if (!checkColor(state, 4)) return luaL_error(state, "invalid color");
  if (!runtime->chargeIo(1)) return luaL_error(state, "display io budget exceeded");
  if (runtime->host_.displayFillCircle)
    runtime->host_.displayFillCircle(runtime->host_.context, x, y, radius,
                                     static_cast<int>(lua_tointeger(state, 4)));
  return 0;
}

int FireLuaRuntime::displayPixel(lua_State* state) {
  auto* runtime = self(state);
  const int x = strictInt(state, 1, 0, kDisplayWidth - 1);
  const int y = strictInt(state, 2, 0, kDisplayHeight - 1);
  if (!checkColor(state, 3)) return luaL_error(state, "invalid color");
  if (!runtime->chargeIo(1)) return luaL_error(state, "display io budget exceeded");
  if (runtime->host_.displayPixel)
    runtime->host_.displayPixel(runtime->host_.context, x, y,
                                static_cast<int>(lua_tointeger(state, 3)));
  return 0;
}

int FireLuaRuntime::displayGrid(lua_State* state) {
  auto* runtime = self(state);
  const int x = strictInt(state, 1, 0, 319);
  const int y = strictInt(state, 2, 0, 239);
  const int cellWidth = strictInt(state, 3, 1, 32);
  const int cellHeight = strictInt(state, 4, 1, 32);
  const int columns = strictInt(state, 5, 1, 32);
  const int rows = strictInt(state, 6, 1, 32);
  luaL_checktype(state, 7, LUA_TTABLE);
  luaL_checktype(state, 8, LUA_TTABLE);
  const size_t cellCount = static_cast<size_t>(columns) * rows;
  if (cellCount > 384 || !runtime->chargeIo(1, false))
    return luaL_error(state, "display grid budget exceeded");
  uint8_t cells[384] = {};
  uint16_t palette[16] = {};
  const int paletteCount = static_cast<int>(lua_rawlen(state, 8));
  if (paletteCount < 1 || paletteCount > 16)
    return luaL_error(state, "invalid palette");
  for (int index = 1; index <= paletteCount; ++index) {
    lua_geti(state, 8, index);
    if (!lua_isinteger(state, -1) || !checkColor(state, -1))
      return luaL_error(state, "invalid palette");
    palette[index - 1] = static_cast<uint16_t>(lua_tointeger(state, -1));
    lua_pop(state, 1);
  }
  for (size_t index = 0; index < cellCount; ++index) {
    lua_geti(state, 7, static_cast<lua_Integer>(index + 1));
    if (!lua_isinteger(state, -1)) return luaL_error(state, "invalid cells");
    const lua_Integer value = lua_tointeger(state, -1);
    lua_pop(state, 1);
    if (value < 0 || value >= paletteCount)
      return luaL_error(state, "invalid cell index");
    cells[index] = static_cast<uint8_t>(value);
  }
  if (runtime->host_.displayGrid)
    runtime->host_.displayGrid(runtime->host_.context, x, y, cellWidth,
                               cellHeight, columns, rows, cells, cellCount,
                               palette, paletteCount);
  return 0;
}

int FireLuaRuntime::buttonPressed(lua_State* state) {
  auto* runtime = self(state);
  const char* name = checkedString(state, 1);
  if (strcmp(name, "A") != 0 && strcmp(name, "B") != 0 &&
      strcmp(name, "C") != 0)
    return luaL_argerror(state, 1, "button must be A, B or C");
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  lua_pushboolean(state, runtime->host_.buttonPressed && runtime->host_.buttonPressed(runtime->host_.context, name));
  return 1;
}

int FireLuaRuntime::rgbSet(lua_State* state) {
  auto* runtime = self(state);
  const int index = strictInt(state, 1, 0, 9);
  const int red = strictInt(state, 2, 0, 255);
  const int green = strictInt(state, 3, 0, 255);
  const int blue = strictInt(state, 4, 0, 255);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  if (runtime->host_.rgbSet) runtime->host_.rgbSet(runtime->host_.context, index, red, green, blue);
  return 0;
}

int FireLuaRuntime::imuAccel(lua_State* state) {
  auto* runtime = self(state);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  float x = 0.0f, y = 0.0f, z = 0.0f;
  if (runtime->host_.imuAccel) runtime->host_.imuAccel(runtime->host_.context, &x, &y, &z);
  lua_newtable(state);
  lua_pushnumber(state, x);
  lua_setfield(state, -2, "x");
  lua_pushnumber(state, y);
  lua_setfield(state, -2, "y");
  lua_pushnumber(state, z);
  lua_setfield(state, -2, "z");
  return 1;
}

int FireLuaRuntime::imuGyro(lua_State* state) {
  auto* runtime = self(state);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  float x = 0.0f, y = 0.0f, z = 0.0f;
  if (!runtime->host_.imuGyro ||
      !runtime->host_.imuGyro(runtime->host_.context, &x, &y, &z))
    return pushError(state, "unavailable");
  lua_newtable(state);
  lua_pushnumber(state, x);
  lua_setfield(state, -2, "x");
  lua_pushnumber(state, y);
  lua_setfield(state, -2, "y");
  lua_pushnumber(state, z);
  lua_setfield(state, -2, "z");
  return 1;
}

int FireLuaRuntime::imuTemperature(lua_State* state) {
  auto* runtime = self(state);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  float value = 0.0f;
  if (!runtime->host_.imuTemperature ||
      !runtime->host_.imuTemperature(runtime->host_.context, &value))
    return pushError(state, "unavailable");
  lua_pushnumber(state, value);
  return 1;
}

int FireLuaRuntime::timeMillis(lua_State* state) {
  auto* runtime = self(state);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  lua_pushinteger(state, runtime->host_.timeMillis ? runtime->host_.timeMillis(runtime->host_.context) : millis());
  return 1;
}

int FireLuaRuntime::gpioMode(lua_State* state) {
  auto* runtime = self(state);
  const int pin = strictInt(state, 1, 0, 39);
  const char* mode = checkedString(state, 2);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  const char* error = nullptr;
  if (!runtime->host_.gpioMode ||
      !runtime->host_.gpioMode(runtime->host_.context, pin, mode, &error))
    return pushError(state, error ? error : "unavailable");
  lua_pushboolean(state, 1);
  return 1;
}

int FireLuaRuntime::gpioRead(lua_State* state) {
  auto* runtime = self(state);
  const int pin = strictInt(state, 1, 0, 39);
  const char* error = nullptr;
  int value = 0;
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  if (!runtime->host_.gpioRead ||
      !runtime->host_.gpioRead(runtime->host_.context, pin, &value, &error))
    return pushError(state, error ? error : "unavailable");
  lua_pushinteger(state, value);
  return 1;
}

int FireLuaRuntime::gpioWrite(lua_State* state) {
  auto* runtime = self(state);
  const int pin = strictInt(state, 1, 0, 33);
  const int value = strictInt(state, 2, 0, 1);
  const char* error = nullptr;
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  if (!runtime->host_.gpioWrite ||
      !runtime->host_.gpioWrite(runtime->host_.context, pin, value, &error))
    return pushError(state, error ? error : "unavailable");
  lua_pushboolean(state, 1);
  return 1;
}

int FireLuaRuntime::gpioRelease(lua_State* state) {
  auto* runtime = self(state);
  const int pin = strictInt(state, 1, 0, 39);
  const char* error = nullptr;
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  if (!runtime->host_.gpioRelease ||
      !runtime->host_.gpioRelease(runtime->host_.context, pin, &error))
    return pushError(state, error ? error : "unavailable");
  lua_pushboolean(state, 1);
  return 1;
}

int FireLuaRuntime::pwmConfigure(lua_State* state) {
  auto* runtime = self(state);
  const int pin = strictInt(state, 1, 0, 33);
  const int frequency = strictInt(state, 2, 1, 20000);
  const int resolution = strictInt(state, 3, 1, 12);
  const char* error = nullptr;
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  if (!runtime->host_.pwmConfigure ||
      !runtime->host_.pwmConfigure(runtime->host_.context, pin, frequency,
                                    resolution, &error))
    return pushError(state, error ? error : "unavailable");
  lua_pushboolean(state, 1);
  return 1;
}

int FireLuaRuntime::pwmWrite(lua_State* state) {
  auto* runtime = self(state);
  const int pin = strictInt(state, 1, 0, 33);
  const int duty = strictInt(state, 2, 0, 4095);
  const char* error = nullptr;
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  if (!runtime->host_.pwmWrite ||
      !runtime->host_.pwmWrite(runtime->host_.context, pin, duty, &error))
    return pushError(state, error ? error : "unavailable");
  lua_pushboolean(state, 1);
  return 1;
}

int FireLuaRuntime::pwmStop(lua_State* state) {
  auto* runtime = self(state);
  const int pin = strictInt(state, 1, 0, 33);
  const char* error = nullptr;
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  if (!runtime->host_.pwmStop ||
      !runtime->host_.pwmStop(runtime->host_.context, pin, &error))
    return pushError(state, error ? error : "unavailable");
  lua_pushboolean(state, 1);
  return 1;
}

int FireLuaRuntime::uartOpen(lua_State* state) {
  auto* runtime = self(state);
  const int port = strictInt(state, 1, 1, 2);
  const int baud = strictInt(state, 2, 300, 1000000);
  const int rx = strictInt(state, 3, 0, 39);
  const int tx = strictInt(state, 4, 0, 33);
  const char* format = checkedString(state, 5);
  const char* error = nullptr;
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  if (!runtime->host_.uartOpen ||
      !runtime->host_.uartOpen(runtime->host_.context, port, baud, rx, tx,
                               format, &error))
    return pushError(state, error ? error : "unavailable");
  lua_pushboolean(state, 1);
  return 1;
}

int FireLuaRuntime::uartRead(lua_State* state) {
  auto* runtime = self(state);
  const int port = strictInt(state, 1, 1, 2);
  const int maxBytes = strictInt(state, 2, 1, 512);
  const char* error = nullptr;
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  const uint16_t job = runtime->host_.uartRead
                           ? runtime->host_.uartRead(runtime->host_.context,
                                                     port, maxBytes, &error)
                           : 0;
  if (job == 0) return pushError(state, error ? error : "busy");
  lua_pushinteger(state, job);
  return 1;
}

int FireLuaRuntime::uartWrite(lua_State* state) {
  auto* runtime = self(state);
  const int port = strictInt(state, 1, 1, 2);
  size_t length = 0;
  const char* text = luaL_checklstring(state, 2, &length);
  if (length > 512) return pushError(state, "payload_too_large");
  if (!runtime->chargeIo(length)) return luaL_error(state, "hardware io budget exceeded");
  const char* error = nullptr;
  const uint16_t job = runtime->host_.uartWrite
                           ? runtime->host_.uartWrite(runtime->host_.context,
                                                      port, text, length, &error)
                           : 0;
  if (job == 0) return pushError(state, error ? error : "busy");
  lua_pushinteger(state, job);
  return 1;
}

int FireLuaRuntime::uartClose(lua_State* state) {
  auto* runtime = self(state);
  const int port = strictInt(state, 1, 1, 2);
  const char* error = nullptr;
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  if (!runtime->host_.uartClose ||
      !runtime->host_.uartClose(runtime->host_.context, port, &error))
    return pushError(state, error ? error : "unavailable");
  lua_pushboolean(state, 1);
  return 1;
}

int FireLuaRuntime::i2cScan(lua_State* state) {
  auto* runtime = self(state);
  const int bus = strictInt(state, 1, 0, 1);
  const char* error = nullptr;
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  const uint16_t job = runtime->host_.i2cScan
                           ? runtime->host_.i2cScan(runtime->host_.context, bus,
                                                    &error)
                           : 0;
  if (job == 0) return pushError(state, error ? error : "busy");
  lua_pushinteger(state, job);
  return 1;
}

int FireLuaRuntime::i2cRead(lua_State* state) {
  auto* runtime = self(state);
  const int bus = strictInt(state, 1, 0, 1);
  const int address = strictInt(state, 2, 1, 126);
  const int reg = strictInt(state, 3, -1, 255);
  const int count = strictInt(state, 4, 1, 128);
  const char* error = nullptr;
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  const uint16_t job = runtime->host_.i2cRead
                           ? runtime->host_.i2cRead(runtime->host_.context, bus,
                                                    address, reg, count, &error)
                           : 0;
  if (job == 0) return pushError(state, error ? error : "busy");
  lua_pushinteger(state, job);
  return 1;
}

int FireLuaRuntime::i2cWrite(lua_State* state) {
  auto* runtime = self(state);
  const int bus = strictInt(state, 1, 0, 1);
  const int address = strictInt(state, 2, 1, 126);
  luaL_checktype(state, 3, LUA_TTABLE);
  const int count = static_cast<int>(lua_rawlen(state, 3));
  if (count < 1 || count > 128) return pushError(state, "invalid_payload");
  if (!runtime->chargeIo(static_cast<size_t>(count)))
    return luaL_error(state, "hardware io budget exceeded");
  uint8_t bytes[128] = {};
  for (int index = 1; index <= count; ++index) {
    lua_geti(state, 3, index);
    if (!lua_isinteger(state, -1)) return pushError(state, "invalid_payload");
    bytes[index - 1] = static_cast<uint8_t>(strictInt(state, -1, 0, 255));
    lua_pop(state, 1);
  }
  const char* error = nullptr;
  const uint16_t job = runtime->host_.i2cWrite
                           ? runtime->host_.i2cWrite(runtime->host_.context, bus,
                                                     address, bytes, count, &error)
                           : 0;
  if (job == 0) return pushError(state, error ? error : "busy");
  lua_pushinteger(state, job);
  return 1;
}

int FireLuaRuntime::adcRead(lua_State* state) {
  auto* runtime = self(state);
  const int pin = strictInt(state, 1, 0, 39);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  const char* error = nullptr;
  int value = 0;
  if (!runtime->host_.adcRead ||
      !runtime->host_.adcRead(runtime->host_.context, pin, &value, &error))
    return pushError(state, error ? error : "unavailable");
  lua_pushinteger(state, value);
  return 1;
}

int FireLuaRuntime::dacWrite(lua_State* state) {
  auto* runtime = self(state);
  const int pin = strictInt(state, 1, 25, 26);
  const int value = strictInt(state, 2, 0, 255);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  const char* error = nullptr;
  if (!runtime->host_.dacWrite ||
      !runtime->host_.dacWrite(runtime->host_.context, pin, value, &error))
    return pushError(state, error ? error : "unavailable");
  lua_pushboolean(state, 1);
  return 1;
}

int FireLuaRuntime::dacStop(lua_State* state) {
  auto* runtime = self(state);
  const int pin = strictInt(state, 1, 0, 39);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  const char* error = nullptr;
  if (!runtime->host_.dacStop ||
      !runtime->host_.dacStop(runtime->host_.context, pin, &error))
    return pushError(state, error ? error : "unavailable");
  lua_pushboolean(state, 1);
  return 1;
}

int FireLuaRuntime::spiOpen(lua_State* state) {
  auto* runtime = self(state);
  const int bus = strictInt(state, 1, 1, 2);
  const int sclk = strictInt(state, 2, 0, 33);
  const int miso = strictInt(state, 3, 0, 39);
  const int mosi = strictInt(state, 4, 0, 33);
  const int cs = strictInt(state, 5, 0, 33);
  const int frequency = strictInt(state, 6, 100000, 10000000);
  const int mode = strictInt(state, 7, 0, 3);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  const char* error = nullptr;
  if (!runtime->host_.spiOpen ||
      !runtime->host_.spiOpen(runtime->host_.context, bus, sclk, miso, mosi,
                               cs, frequency, mode, &error))
    return pushError(state, error ? error : "unavailable");
  lua_pushboolean(state, 1);
  return 1;
}

int FireLuaRuntime::spiTransfer(lua_State* state) {
  auto* runtime = self(state);
  const int bus = strictInt(state, 1, 1, 2);
  luaL_checktype(state, 2, LUA_TTABLE);
  const int count = static_cast<int>(lua_rawlen(state, 2));
  if (count < 1 || count > 512) return pushError(state, "invalid_payload");
  if (!runtime->chargeIo(static_cast<size_t>(count)))
    return luaL_error(state, "hardware io budget exceeded");
  uint8_t bytes[512] = {};
  for (int index = 1; index <= count; ++index) {
    lua_geti(state, 2, index);
    if (!lua_isinteger(state, -1)) return pushError(state, "invalid_payload");
    bytes[index - 1] = static_cast<uint8_t>(strictInt(state, -1, 0, 255));
    lua_pop(state, 1);
  }
  const char* error = nullptr;
  const uint16_t job = runtime->host_.spiTransfer
                           ? runtime->host_.spiTransfer(runtime->host_.context,
                                                        bus, bytes, count,
                                                        &error)
                           : 0;
  if (!job) return pushError(state, error ? error : "busy");
  lua_pushinteger(state, job);
  return 1;
}

int FireLuaRuntime::spiClose(lua_State* state) {
  auto* runtime = self(state);
  const int bus = strictInt(state, 1, 1, 2);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  const char* error = nullptr;
  if (!runtime->host_.spiClose ||
      !runtime->host_.spiClose(runtime->host_.context, bus, &error))
    return pushError(state, error ? error : "unavailable");
  lua_pushboolean(state, 1);
  return 1;
}

static const char* checkedPath(lua_State* state, int index, size_t* length) {
  const char* path = luaL_checklstring(state, index, length);
  if (*length > 96) luaL_argerror(state, index, "path too long");
  if (memchr(path, '\0', *length) != nullptr)
    luaL_argerror(state, index, "path contains NUL");
  return path;
}

int FireLuaRuntime::sdList(lua_State* state) {
  auto* runtime = self(state);
  size_t length = 0;
  const char* path = checkedPath(state, 1, &length);
  if (!runtime->chargeIo(length, true)) return luaL_error(state, "hardware io budget exceeded");
  const char* error = nullptr;
  const uint16_t job = runtime->host_.sdList
                           ? runtime->host_.sdList(runtime->host_.context, path,
                                                   &error)
                           : 0;
  if (!job) return pushError(state, error ? error : "busy");
  lua_pushinteger(state, job);
  return 1;
}

int FireLuaRuntime::sdRead(lua_State* state) {
  auto* runtime = self(state);
  size_t length = 0;
  const char* path = checkedPath(state, 1, &length);
  const int offset = strictInt(state, 2, 0, 1048576);
  const int count = strictInt(state, 3, 1, 512);
  if (!runtime->chargeIo(length, true)) return luaL_error(state, "hardware io budget exceeded");
  const char* error = nullptr;
  const uint16_t job = runtime->host_.sdRead
                           ? runtime->host_.sdRead(runtime->host_.context, path,
                                                   static_cast<uint32_t>(offset),
                                                   static_cast<uint16_t>(count),
                                                   &error)
                           : 0;
  if (!job) return pushError(state, error ? error : "busy");
  lua_pushinteger(state, job);
  return 1;
}

int FireLuaRuntime::sdWrite(lua_State* state) {
  auto* runtime = self(state);
  size_t pathLength = 0;
  const char* path = checkedPath(state, 1, &pathLength);
  size_t textLength = 0;
  const char* text = luaL_checklstring(state, 2, &textLength);
  if (textLength > 512) return pushError(state, "payload_too_large");
  luaL_checktype(state, 3, LUA_TBOOLEAN);
  if (!runtime->chargeIo(pathLength + textLength, true))
    return luaL_error(state, "hardware io budget exceeded");
  const char* error = nullptr;
  const uint16_t job = runtime->host_.sdWrite
                           ? runtime->host_.sdWrite(runtime->host_.context, path,
                                                    text, textLength,
                                                    lua_toboolean(state, 3),
                                                    &error)
                           : 0;
  if (!job) return pushError(state, error ? error : "busy");
  lua_pushinteger(state, job);
  return 1;
}

int FireLuaRuntime::sdRemove(lua_State* state) {
  auto* runtime = self(state);
  size_t length = 0;
  const char* path = checkedPath(state, 1, &length);
  if (!runtime->chargeIo(length, true)) return luaL_error(state, "hardware io budget exceeded");
  const char* error = nullptr;
  const uint16_t job = runtime->host_.sdRemove
                           ? runtime->host_.sdRemove(runtime->host_.context,
                                                     path, &error)
                           : 0;
  if (!job) return pushError(state, error ? error : "busy");
  lua_pushinteger(state, job);
  return 1;
}

int FireLuaRuntime::sdMkdir(lua_State* state) {
  auto* runtime = self(state);
  size_t length = 0;
  const char* path = checkedPath(state, 1, &length);
  if (!runtime->chargeIo(length, true)) return luaL_error(state, "hardware io budget exceeded");
  const char* error = nullptr;
  if (!runtime->host_.sdMkdir ||
      !runtime->host_.sdMkdir(runtime->host_.context, path, &error))
    return pushError(state, error ? error : "unavailable");
  lua_pushboolean(state, 1);
  return 1;
}

int FireLuaRuntime::powerStatus(lua_State* state) {
  auto* runtime = self(state);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  float battery = 0.0f;
  float voltage = 0.0f;
  bool charging = false;
  bool usb = false;
  if (!runtime->host_.powerStatus ||
      !runtime->host_.powerStatus(runtime->host_.context, &battery, &voltage,
                                   &charging, &usb))
    return pushError(state, "unavailable");
  lua_newtable(state);
  lua_pushnumber(state, battery);
  lua_setfield(state, -2, "battery_percent");
  lua_pushnumber(state, voltage);
  lua_setfield(state, -2, "voltage");
  lua_pushboolean(state, charging);
  lua_setfield(state, -2, "charging");
  lua_pushboolean(state, usb);
  lua_setfield(state, -2, "usb");
  return 1;
}

int FireLuaRuntime::powerBrightness(lua_State* state) {
  auto* runtime = self(state);
  const int brightness = strictInt(state, 1, 0, 255);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  const char* error = nullptr;
  if (!runtime->host_.powerBrightness ||
      !runtime->host_.powerBrightness(runtime->host_.context, brightness,
                                      &error))
    return pushError(state, error ? error : "unavailable");
  lua_pushboolean(state, 1);
  return 1;
}

int FireLuaRuntime::powerSleep(lua_State* state) {
  auto* runtime = self(state);
  const int duration = strictInt(state, 1, 1, 3600000);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  const char* error = nullptr;
  const uint16_t job = runtime->host_.powerSleep
                           ? runtime->host_.powerSleep(runtime->host_.context,
                                                       static_cast<uint32_t>(duration),
                                                       &error)
                           : 0;
  if (!job) return pushError(state, error ? error : "busy");
  lua_pushinteger(state, job);
  return 1;
}

int FireLuaRuntime::rtcNow(lua_State* state) {
  auto* runtime = self(state);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  uint32_t epoch = 0;
  int year = 0, month = 0, day = 0, hour = 0, minute = 0, second = 0;
  const char* error = nullptr;
  if (!runtime->host_.rtcNow ||
      !runtime->host_.rtcNow(runtime->host_.context, &epoch, &year, &month,
                              &day, &hour, &minute, &second, &error))
    return pushError(state, error ? error : "unavailable");
  lua_newtable(state);
  lua_pushinteger(state, epoch);
  lua_setfield(state, -2, "epoch");
  lua_pushinteger(state, year);
  lua_setfield(state, -2, "year");
  lua_pushinteger(state, month);
  lua_setfield(state, -2, "month");
  lua_pushinteger(state, day);
  lua_setfield(state, -2, "day");
  lua_pushinteger(state, hour);
  lua_setfield(state, -2, "hour");
  lua_pushinteger(state, minute);
  lua_setfield(state, -2, "minute");
  lua_pushinteger(state, second);
  lua_setfield(state, -2, "second");
  return 1;
}

int FireLuaRuntime::rtcSet(lua_State* state) {
  auto* runtime = self(state);
  const int epoch = strictInt(state, 1, 0, 2147483647);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  const char* error = nullptr;
  if (!runtime->host_.rtcSet ||
      !runtime->host_.rtcSet(runtime->host_.context,
                             static_cast<uint32_t>(epoch), &error))
    return pushError(state, error ? error : "unavailable");
  lua_pushboolean(state, 1);
  return 1;
}

int FireLuaRuntime::speakerTone(lua_State* state) {
  auto* runtime = self(state);
  const int frequency = strictInt(state, 1, 20, 20000);
  const int duration = strictInt(state, 2, 1, 5000);
  const int volume = strictInt(state, 3, 0, 255);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  const char* error = nullptr;
  const uint16_t job = runtime->host_.speakerTone
                           ? runtime->host_.speakerTone(runtime->host_.context,
                                                        frequency, duration,
                                                        volume, &error)
                           : 0;
  if (!job) return pushError(state, error ? error : "busy");
  lua_pushinteger(state, job);
  return 1;
}

int FireLuaRuntime::speakerPlay(lua_State* state) {
  auto* runtime = self(state);
  size_t pathLength = 0;
  const char* path = checkedPath(state, 1, &pathLength);
  const int volume = strictInt(state, 2, 0, 255);
  if (!runtime->chargeIo(pathLength, true))
    return luaL_error(state, "hardware io budget exceeded");
  const char* error = nullptr;
  const uint16_t job = runtime->host_.speakerPlay
                           ? runtime->host_.speakerPlay(runtime->host_.context,
                                                        path, volume, &error)
                           : 0;
  if (!job) return pushError(state, error ? error : "busy");
  lua_pushinteger(state, job);
  return 1;
}

int FireLuaRuntime::speakerStop(lua_State* state) {
  auto* runtime = self(state);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  const char* error = nullptr;
  if (!runtime->host_.speakerStop ||
      !runtime->host_.speakerStop(runtime->host_.context, &error))
    return pushError(state, error ? error : "unavailable");
  lua_pushboolean(state, 1);
  return 1;
}

static void pushJobState(lua_State* state,
                         const FireLuaRuntime::JobSnapshot& snapshot) {
  lua_newtable(state);
  const char* stateName = snapshot.state == 0
                              ? "pending"
                          : snapshot.state == 1
                              ? "ready"
                          : snapshot.state == 2 ? "failed" : "cancelled";
  lua_pushstring(state, stateName);
  lua_setfield(state, -2, "state");
  lua_pushboolean(state, snapshot.state != 0);
  lua_setfield(state, -2, "done");
  lua_pushlstring(state, snapshot.errorCode.c_str(), snapshot.errorCode.length());
  lua_setfield(state, -2, "error_code");
}

static void pushJobResult(lua_State* state,
                          const FireLuaRuntime::JobSnapshot& snapshot) {
  if (snapshot.state == 0) {
    lua_newtable(state);
    lua_pushboolean(state, 0);
    lua_setfield(state, -2, "ok");
    lua_pushliteral(state, "not_ready");
    lua_setfield(state, -2, "error_code");
    return;
  }
  if (snapshot.state != 1) {
    lua_newtable(state);
    lua_pushboolean(state, 0);
    lua_setfield(state, -2, "ok");
    lua_pushlstring(state, snapshot.errorCode.c_str(), snapshot.errorCode.length());
    lua_setfield(state, -2, "error_code");
    return;
  }
  lua_newtable(state);
  lua_pushboolean(state, 1);
  lua_setfield(state, -2, "ok");
  if (snapshot.resultKind == FireLuaRuntime::JobSnapshot::I2cScan) {
    lua_newtable(state);
    for (uint16_t index = 0; index < snapshot.addressCount; ++index) {
      lua_pushinteger(state, snapshot.addresses[index]);
      lua_seti(state, -2, index + 1);
    }
    lua_setfield(state, -2, "addresses");
  } else if (snapshot.resultKind == FireLuaRuntime::JobSnapshot::Bytes ||
             snapshot.resultKind == FireLuaRuntime::JobSnapshot::Uart) {
    lua_newtable(state);
    for (uint16_t index = 0; index < snapshot.byteCount; ++index) {
      lua_pushinteger(state, snapshot.bytes[index]);
      lua_seti(state, -2, index + 1);
    }
    lua_setfield(state, -2, "bytes");
    lua_pushlstring(state, snapshot.text.c_str(), snapshot.text.length());
    lua_setfield(state, -2, "text");
  } else if (snapshot.resultKind == FireLuaRuntime::JobSnapshot::Files) {
    lua_newtable(state);
    for (uint16_t index = 0; index < snapshot.entryCount; ++index) {
      lua_newtable(state);
      lua_pushlstring(state, snapshot.entries[index].name.c_str(),
                      snapshot.entries[index].name.length());
      lua_setfield(state, -2, "name");
      lua_pushinteger(state, snapshot.entries[index].sizeBytes);
      lua_setfield(state, -2, "size_bytes");
      lua_pushboolean(state, snapshot.entries[index].directory);
      lua_setfield(state, -2, "is_directory");
      lua_seti(state, -2, index + 1);
    }
    lua_setfield(state, -2, "entries");
  } else if (snapshot.resultKind == FireLuaRuntime::JobSnapshot::Write) {
    lua_pushinteger(state, snapshot.written);
    lua_setfield(state, -2, "written");
  }
}

int FireLuaRuntime::jobsPoll(lua_State* state) {
  auto* runtime = self(state);
  const uint16_t id = static_cast<uint16_t>(strictInt(state, 1, 1, 65535));
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  JobSnapshot snapshot;
  if (!runtime->host_.jobPoll ||
      !runtime->host_.jobPoll(runtime->host_.context, id, &snapshot))
    return pushError(state, "invalid_handle");
  pushJobState(state, snapshot);
  return 1;
}

int FireLuaRuntime::jobsResult(lua_State* state) {
  auto* runtime = self(state);
  const uint16_t id = static_cast<uint16_t>(strictInt(state, 1, 1, 65535));
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  JobSnapshot snapshot;
  if (!runtime->host_.jobResult ||
      !runtime->host_.jobResult(runtime->host_.context, id, &snapshot))
    return pushError(state, "invalid_handle");
  pushJobResult(state, snapshot);
  return 1;
}

int FireLuaRuntime::jobsClose(lua_State* state) {
  auto* runtime = self(state);
  const uint16_t id = static_cast<uint16_t>(strictInt(state, 1, 1, 65535));
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  lua_pushboolean(state, runtime->host_.jobClose &&
                              runtime->host_.jobClose(runtime->host_.context, id));
  return 1;
}

int FireLuaRuntime::jobsCancel(lua_State* state) {
  auto* runtime = self(state);
  const uint16_t id = static_cast<uint16_t>(strictInt(state, 1, 1, 65535));
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  lua_pushboolean(state, runtime->host_.jobCancel &&
                              runtime->host_.jobCancel(runtime->host_.context, id));
  return 1;
}
