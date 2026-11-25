#include "fire_lua_runtime.h"
#include "fire_app_sdk_data.h"
#include "fire_runtime_ai_json.h"
#include "fire_data_engine_contract.h"
#include "fire_data_paths.h"
#include "fire_app_bitmap.h"

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
constexpr uint32_t kServiceAi = 1u << 20;
constexpr uint32_t kServiceData = 1u << 21;

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

bool optionalBool(lua_State* state,int index,bool fallback) {
  if (lua_isnoneornil(state,index)) return fallback;
  luaL_checktype(state,index,LUA_TBOOLEAN);
  return lua_toboolean(state,index)!=0;
}

const char* sdkString(lua_State* state,int index,size_t maximum,size_t* length=nullptr) {
  luaL_checktype(state,index,LUA_TSTRING);
  size_t size=0;const char* value=lua_tolstring(state,index,&size);
  if (size>maximum || memchr(value,0,size)) luaL_argerror(state,index,"invalid SDK string");
  if (length) *length=size;
  return value;
}

const char* sdkFont(lua_State* state,int index) {
  return lua_isnoneornil(state,index)?"ui16":sdkString(state,index,32);
}

int sdkInt(lua_State* state,int index,int minimum,int maximum) {
  // Our safe math.floor/min/max return numbers, so integral floats must work;
  // numeric strings must not be coerced into coordinates or palette colors.
  luaL_checktype(state,index,LUA_TNUMBER);
  return strictInt(state,index,minimum,maximum);
}
int sdkGenerationalGc(lua_State* state) {
  if(lua_gc(state,LUA_GCGEN,20,100)<0) return luaL_error(state,"SDK GC mode unavailable");
  return 0;
}
}  // namespace

const char* FireLuaRuntime::hardwareApiContract() {
  return "0b29618a077256268c1dc78512ccf2700517e6c162cbe72f2f4a171dcfc3cd40";
}
const char* FireLuaRuntime::appSdkVersion() {return FireSdkData::kVersion;}
const char* FireLuaRuntime::appSdkContract() {return FireSdkData::kContract;}

bool FireLuaRuntime::supportsManifestApi(const char* version, size_t versionLength,
                                        const char* contract, size_t contractLength) {
  const auto exact=[](const char* value, size_t length, const char* expected) {
    return value && length==strlen(expected) && !memcmp(value, expected, length);
  };
  // Legacy0.1 did not require an API contract; retain that installation rule.
  if (exact(version, versionLength, "fire-lua-0.1")) return true;
  if (exact(version, versionLength, hardwareApiVersion()))
    return exact(contract, contractLength, hardwareApiContract());
  return exact(version, versionLength, appSdkVersion()) &&
         exact(contract, contractLength, appSdkContract());
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
    runtime->peakMemoryUsed_ = max(runtime->peakMemoryUsed_,runtime->memoryUsed_);
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
    if (runtime->appSdk_) {
      setFunction(state, "set_background", displaySetBackground);
      setFunction(state,"text_style",displayTextStyle);
      setFunction(state,"measure_text",displayMeasureText);
      setFunction(state,"asset",displayAsset);
      setFunction(state,"round_rect",displayRoundRect);
      setFunction(state,"triangle",displayTriangle);
      setFunction(state,"polyline",displayPolyline);
      setFunction(state,"polygon",displayPolygon);
      setFunction(state,"gradient_rect",displayGradient);
      setFunction(state,"arc",displayArc);
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
  if (runtime->appSdk_ && serviceAllowed(runtime,kServiceAi) &&
      serviceAllowed(runtime,kServiceJobs) && runtime->host_.aiRequest) {
    lua_newtable(state);setFunction(state,"request",aiRequest);lua_setfield(state,-2,"ai");
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
  if (runtime->hardwareApi_ && serviceAllowed(runtime, kServiceMic) &&
      serviceAllowed(runtime, kServiceJobs) && serviceAllowed(runtime, kServiceSd) &&
      runtime->host_.micRecord) {
    lua_newtable(state);
    setFunction(state, "level", micLevel);
    setFunction(state, "record", micRecord);
    lua_setfield(state, -2, "mic");
  }
  if (runtime->hardwareApi_ && serviceAllowed(runtime,kServiceBluetooth) &&
      serviceAllowed(runtime,kServiceJobs) && runtime->host_.bluetoothRequest) {
    lua_newtable(state);setFunction(state,"scan",bluetoothScan);
    setFunction(state,"read_gatt",bluetoothReadGatt);setFunction(state,"write_gatt",bluetoothWriteGatt);
    setFunction(state,"advertise",bluetoothAdvertise);setFunction(state,"close",bluetoothClose);
    if (runtime->appSdk_ && runtime->dataEngine_ && serviceAllowed(runtime,kServiceData))
      setFunction(state,"advertise_raw",bluetoothAdvertiseRaw);
    lua_setfield(state,-2,"bluetooth");
  }
  if (runtime->hardwareApi_ && serviceAllowed(runtime,kServiceWifi) && runtime->host_.wifiStatus) {
    lua_newtable(state);setFunction(state,"status",wifiStatus);
    if (serviceAllowed(runtime,kServiceJobs) && runtime->host_.wifiScan) setFunction(state,"scan",wifiScan);
    lua_setfield(state,-2,"wifi");
  }

  if (runtime->hardwareApi_ && runtime->appSdk_ && runtime->dataEngine_ &&
      serviceAllowed(runtime,kServiceData) && serviceAllowed(runtime,kServiceJobs) &&
      serviceAllowed(runtime,kServiceSd) && runtime->host_.dataRequest) {
    lua_newtable(state);
    setFunction(state,"create",dataCreate);setFunction(state,"append",dataAppend);
    setFunction(state,"mark",dataMark);setFunction(state,"seal",dataSeal);
    setFunction(state,"info",dataInfo);setFunction(state,"read",dataRead);
    setFunction(state,"record",dataRecord);setFunction(state,"process",dataProcess);
    setFunction(state,"develop",dataDevelop);
    lua_setfield(state,-2,"data");
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
  instructions_ = 0;
  callbackPhase_ = phase;
  callbackBudgetMs_ = budgetMs;
  frameStarted_ = millis();
  callbackStartedUs_ = static_cast<uint64_t>(esp_timer_get_time());
  ioCalls_ = 0;
  ioBytes_ = 0;
  textBytes_ = 0;
  sdkGridCells_ = 0;
  sdkGridPixels_ = 0;
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
    frameBackground_ = 0;
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
  frameBackground_ = 0;
  clearState();
  if (appSdk_ && serviceAllowed(this,kServiceDisplay)) {
    if (!host_.appSdkUiSource || !host_.appSdkUiBytes) return fail("SDK UI unavailable");
    beginCallback(CallbackPhase::Load,250);
    lua_getglobal(lua_,"fire");
    const int loaded=luaL_loadbufferx(lua_,host_.appSdkUiSource,host_.appSdkUiBytes,"fire.ui","t");
    if (loaded!=LUA_OK || lua_pcall(lua_,0,1,0)!=LUA_OK) {
      finishCallback();return fail(String("SDK UI: ")+lua_tostring(lua_,-1));
    }
    if (!lua_istable(lua_,-1)) return fail("SDK UI must return a table");
    lua_setfield(lua_,-2,"ui");lua_pop(lua_,1);
    if (!finishCallback()) return false;
  }
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
  if(appSdk_) {
    // Long-lived UI data becomes old; short-lived frame options use minors.
    // Mode transition may collect: protect it and retain the SAME init timer.
    lua_pushcfunction(lua_,sdkGenerationalGc);
    if(lua_pcall(lua_,0,0,0)!=LUA_OK) {
      finishCallback();return fail(String("Lua init GC: ")+lua_tostring(lua_,-1));
    }
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
  peakMemoryUsed_ = 0;
  instructions_ = 0;
  startedAt_ = 0;
  maxRuntimeMs_ = kDefaultRuntimeMs;
  callbackBudgetMs_ = kMaxCallbackMs;
  callbackStartedUs_ = 0;
  frames_ = 0;
  sourceBytes_ = 0;
  frameBackground_ = 0;
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
  beginCallback(CallbackPhase::Update, appSdk_ ? FireSdkData::kUpdateCallbackMs : kMaxCallbackMs);
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
  callbackButtonPressed_ = action && !strcmp(action,"pressed");
  beginCallback(CallbackPhase::OnButton, kMaxCallbackMs);
  if (lua_pcall(lua_, 2, 0, 0) != LUA_OK) {
    callbackButtonPressed_ = false;
    finishCallback();
    return fail(String("Lua on_button: ") + lua_tostring(lua_, -1));
  }
  callbackButtonPressed_ = false;
  return finishCallback();
}

bool FireLuaRuntime::fail(const String& message) {
  error_ = message;
  state_ = State::Failed;
  frameBackground_ = 0;
  if (lua_ && lua_gettop(lua_) > 0) lua_settop(lua_, 0);
  return false;
}

bool FireLuaRuntime::checkColor(lua_State* state, int index) {
  const lua_Integer value = luaL_checkinteger(state, index);
  return value >= 0 && value <= 65535;
}

int FireLuaRuntime::displaySetBackground(lua_State* state) {
  auto* runtime=self(state);
  const int color=sdkInt(state,1,0,65535);
  if (!runtime->chargeIo(1)) return luaL_error(state,"display io budget exceeded");
  runtime->frameBackground_=static_cast<uint16_t>(color);
  return 0;
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
  runtime->paintDisplay();
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
  runtime->paintDisplay();
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
  runtime->paintDisplay();
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
  runtime->paintDisplay();
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
  runtime->paintDisplay();
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
  runtime->paintDisplay();
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
  runtime->paintDisplay();
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
  const uint32_t pixels=uint32_t(cellCount)*cellWidth*cellHeight;
  if (runtime->appSdk_ && (runtime->sdkGridCells_+cellCount>384 ||
                          runtime->sdkGridPixels_+pixels>32768))
    return luaL_error(state,"SDK grid callback budget exceeded");
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
  if (runtime->appSdk_) {
    runtime->sdkGridCells_+=uint16_t(cellCount);
    runtime->sdkGridPixels_+=pixels;
  }
  runtime->paintDisplay();
  if (runtime->host_.displayGrid)
    runtime->host_.displayGrid(runtime->host_.context, x, y, cellWidth,
                               cellHeight, columns, rows, cells, cellCount,
                               palette, paletteCount);
  return 0;
}

int FireLuaRuntime::displayTextStyle(lua_State* state) {
  auto* runtime=self(state);
  const int x=sdkInt(state,1,-1024,1024),y=sdkInt(state,2,-1024,1024);
  size_t length=0;const char* text=sdkString(state,3,80,&length);
  const int color=sdkInt(state,4,0,65535);
  const char* font=sdkFont(state,5);
  const char* align=lua_isnoneornil(state,6)?"left":sdkString(state,6,6);
  const int alignment=!strcmp(align,"left")?0:!strcmp(align,"center")?1:!strcmp(align,"right")?2:-1;
  if (alignment<0) return luaL_argerror(state,6,"unknown text alignment");
  const int width=lua_isnoneornil(state,7)?320:sdkInt(state,7,1,1024);
  if (!runtime->chargeIo(length,true)) return luaL_error(state,"display io budget exceeded");
  runtime->paintDisplay();
  if (!runtime->host_.displayTextStyle || !runtime->host_.displayTextStyle(runtime->host_.context,
      x,y,text,length,color,font,alignment,width)) return luaL_error(state,"unknown font or invalid UTF-8 text");
  return 0;
}

int FireLuaRuntime::displayMeasureText(lua_State* state) {
  auto* runtime=self(state);size_t length=0;
  const char* text=sdkString(state,1,80,&length);const char* font=sdkFont(state,2);
  if (!runtime->chargeIo(length,true)) return luaL_error(state,"display io budget exceeded");
  int width=0,height=0;
  if (!runtime->host_.displayMeasureText || !runtime->host_.displayMeasureText(runtime->host_.context,
      text,length,font,&width,&height)) return luaL_error(state,"unknown font or invalid UTF-8 text");
  lua_pushinteger(state,width);lua_pushinteger(state,height);return 2;
}

int FireLuaRuntime::displayAsset(lua_State* state) {
  auto* runtime=self(state);
  const int x=sdkInt(state,1,-1024,1024),y=sdkInt(state,2,-1024,1024);
  size_t length=0;const char* id=sdkString(state,3,96,&length);
  const int scale=lua_isnoneornil(state,4)?1:sdkInt(state,4,1,4);
  const int tint=lua_isnoneornil(state,5)?-1:sdkInt(state,5,0,65535);
  const bool flipX=optionalBool(state,6,false),flipY=optionalBool(state,7,false);
  if (!runtime->chargeIo(length)) return luaL_error(state,"display io budget exceeded");
  runtime->paintDisplay();
  if (!runtime->host_.displayAsset || !runtime->host_.displayAsset(runtime->host_.context,
      x,y,id,scale,tint,flipX,flipY)) return luaL_error(state,"unknown or invalid SDK asset");
  return 0;
}

int FireLuaRuntime::displayRoundRect(lua_State* state) {
  auto* runtime=self(state);
  const int x=sdkInt(state,1,-1024,1024),y=sdkInt(state,2,-1024,1024);
  const int w=sdkInt(state,3,1,1024),h=sdkInt(state,4,1,1024);
  const int radius=sdkInt(state,5,0,min(160,min(w,h)/2));
  const int color=sdkInt(state,6,0,65535);const bool filled=optionalBool(state,7,false);
  if (!runtime->chargeIo(1)) return luaL_error(state,"display io budget exceeded");
  runtime->paintDisplay();
  if (runtime->host_.displayRoundRect) runtime->host_.displayRoundRect(runtime->host_.context,x,y,w,h,radius,color,filled);
  return 0;
}

int FireLuaRuntime::displayTriangle(lua_State* state) {
  auto* runtime=self(state);
  int values[6];for (int i=0;i<6;++i) values[i]=sdkInt(state,i+1,-1024,1024);
  const int color=sdkInt(state,7,0,65535);const bool filled=optionalBool(state,8,false);
  if (!runtime->chargeIo(1)) return luaL_error(state,"display io budget exceeded");
  runtime->paintDisplay();
  if (runtime->host_.displayTriangle) runtime->host_.displayTriangle(runtime->host_.context,
      values[0],values[1],values[2],values[3],values[4],values[5],color,filled);
  return 0;
}

int FireLuaRuntime::displayPoints(lua_State* state,bool polygon) {
  auto* runtime=self(state);luaL_checktype(state,1,LUA_TTABLE);
  const size_t length=lua_rawlen(state,1),count=length/2;
  if ((length&1) || count<(polygon?3u:2u) || count>(polygon?16u:64u))
    return luaL_argerror(state,1,"invalid point count");
  int16_t points[128];
  for (size_t i=0;i<length;++i) {
    lua_rawgeti(state,1,static_cast<lua_Integer>(i+1));
    points[i]=static_cast<int16_t>(sdkInt(state,-1,-1024,1024));lua_pop(state,1);
  }
  const int color=sdkInt(state,2,0,65535);const bool flag=optionalBool(state,3,false);
  if (!runtime->chargeIo(count*4)) return luaL_error(state,"display io budget exceeded");
  runtime->paintDisplay();
  if (runtime->host_.displayPolyline) runtime->host_.displayPolyline(runtime->host_.context,
      points,count,color,polygon||flag,polygon&&flag);
  return 0;
}
int FireLuaRuntime::displayPolyline(lua_State* state) {return displayPoints(state,false);}
int FireLuaRuntime::displayPolygon(lua_State* state) {return displayPoints(state,true);}

int FireLuaRuntime::displayGradient(lua_State* state) {
  auto* runtime=self(state);
  const int x=sdkInt(state,1,-1024,1024),y=sdkInt(state,2,-1024,1024);
  const int w=sdkInt(state,3,1,1024),h=sdkInt(state,4,1,1024);
  const int a=sdkInt(state,5,0,65535),b=sdkInt(state,6,0,65535);
  const bool vertical=optionalBool(state,7,true);
  if (!runtime->chargeIo(1)) return luaL_error(state,"display io budget exceeded");
  runtime->paintDisplay();
  if (runtime->host_.displayGradient) runtime->host_.displayGradient(runtime->host_.context,x,y,w,h,a,b,vertical);
  return 0;
}

int FireLuaRuntime::displayArc(lua_State* state) {
  auto* runtime=self(state);
  const int x=sdkInt(state,1,-1024,1024),y=sdkInt(state,2,-1024,1024);
  const int r=sdkInt(state,3,1,160),start=sdkInt(state,4,0,360),end=sdkInt(state,5,start,360);
  const int color=sdkInt(state,6,0,65535),thickness=lua_isnoneornil(state,7)?1:sdkInt(state,7,1,r);
  if (!runtime->chargeIo(1)) return luaL_error(state,"display io budget exceeded");
  runtime->paintDisplay();
  if (runtime->host_.displayArc) runtime->host_.displayArc(runtime->host_.context,x,y,r,start,end,color,thickness);
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
  if (runtime->dataEngine_ && runtime->host_.imuBusy && runtime->host_.imuBusy(runtime->host_.context)) return pushError(state,"busy");
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
  if (runtime->dataEngine_ && runtime->host_.imuBusy && runtime->host_.imuBusy(runtime->host_.context)) return pushError(state,"busy");
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

namespace {
const char* dataString(lua_State* state,int index,size_t maximum,size_t* length=nullptr) {
  const char* value=sdkString(state,index,maximum,length);
  size_t at=0;uint32_t cp=0;const size_t bytes=strlen(value);
  while (at<bytes) if (!fire_app_bitmap::codepoint(value,bytes,at,cp)) luaL_argerror(state,index,"invalid UTF-8");
  return value;
}
const char* dataId(lua_State* state,int index) {
  size_t length=0;const char* id=dataString(state,index,FireDataEngineContract::kIdentifierBytes,&length);
  if (!length) luaL_argerror(state,index,"empty dataset identifier");
  for (size_t i=0;i<length;++i) {
    const char c=id[i];
    if (!((c>='a' && c<='z') || (c>='A' && c<='Z') || (c>='0' && c<='9') || c=='_' || c=='-'))
      luaL_argerror(state,index,"invalid dataset identifier");
  }
  return id;
}
const char* dataOptions(lua_State* state,int index,size_t maximum) {
  if (lua_isnoneornil(state,index)) return "{}";
  size_t length=0;const char* value=dataString(state,index,maximum,&length);
  if (!fire_runtime_ai_json::validObject(value,length,maximum,FireDataEngineContract::kJsonDepth))
    luaL_argerror(state,index,"invalid bounded JSON object");
  return value;
}
} // namespace

int FireLuaRuntime::dataCreate(lua_State* s) {return dataCall(s,"create");}
int FireLuaRuntime::dataAppend(lua_State* s) {return dataCall(s,"append");}
int FireLuaRuntime::dataMark(lua_State* s) {return dataCall(s,"mark");}
int FireLuaRuntime::dataSeal(lua_State* s) {return dataCall(s,"seal");}
int FireLuaRuntime::dataInfo(lua_State* s) {return dataCall(s,"info");}
int FireLuaRuntime::dataRead(lua_State* s) {return dataCall(s,"read");}
int FireLuaRuntime::dataRecord(lua_State* s) {return dataCall(s,"record");}
int FireLuaRuntime::dataProcess(lua_State* s) {return dataCall(s,"process");}
int FireLuaRuntime::dataCall(lua_State* state,const char* op) {
  auto* runtime=self(state);
  if (!runtime->appSdk_ || !runtime->dataEngine_ || !serviceAllowed(runtime,kServiceData) ||
      !serviceAllowed(runtime,kServiceJobs) || !serviceAllowed(runtime,kServiceSd)) return pushError(state,"permission_denied");
  const char *first="",*second="",*options="{}";
  uint8_t bytes[FireDataEngineContract::kAppendBytes];
  const uint8_t* payload=nullptr;size_t length=0;uint32_t offset=0;uint16_t count=0;
  if (!strcmp(op,"create")) {
    first=dataString(state,1,FireDataEngineContract::kLabelBytes);
    second=dataString(state,2,8);
    if (strcmp(second,"csv") && strcmp(second,"text") && strcmp(second,"binary") && strcmp(second,"audio")) return pushError(state,"invalid_argument");
    options=dataOptions(state,3,FireDataEngineContract::kMetadataBytes);
  } else if (!strcmp(op,"record")) {
    first=dataString(state,1,32);options=dataOptions(state,2,FireDataEngineContract::kOptionsBytes);
  } else {
    first=dataId(state,1);
    if (!strcmp(op,"append")) {
      if (lua_type(state,2)==LUA_TSTRING) payload=reinterpret_cast<const uint8_t*>(lua_tolstring(state,2,&length));
      else {
        luaL_checktype(state,2,LUA_TTABLE);length=lua_rawlen(state,2);
        if (!length || length>sizeof(bytes)) return pushError(state,"invalid_argument");
        for (size_t i=0;i<length;++i) {
          lua_geti(state,2,i+1);if (!lua_isinteger(state,-1)) return luaL_argerror(state,2,"byte must be an integer");
          bytes[i]=static_cast<uint8_t>(strictInt(state,-1,0,255));lua_pop(state,1);
        }
        payload=bytes;
      }
      if (!length || length>FireDataEngineContract::kAppendBytes) return pushError(state,"invalid_argument");
    } else if (!strcmp(op,"mark")) second=dataString(state,2,FireDataEngineContract::kMarkerBytes);
    else if (!strcmp(op,"read")) {
      offset=static_cast<uint32_t>(strictInt(state,2,0,FireDataEngineContract::kDatasetBytes));
      count=static_cast<uint16_t>(strictInt(state,3,1,FireDataEngineContract::kReadBytes));
    } else if (!strcmp(op,"process")) {
      second=dataString(state,2,16);
      if (strcmp(second,"stats") && strcmp(second,"filter") && strcmp(second,"spectrum") && strcmp(second,"compare")) return pushError(state,"unsupported_operation");
      options=dataOptions(state,3,FireDataEngineContract::kOptionsBytes);
    }
  }
  if (!runtime->chargeIo(strlen(first)+strlen(second)+strlen(options)+length)) return luaL_error(state,"hardware io budget exceeded");
  const char* error="unavailable";
  const uint16_t id=runtime->host_.dataRequest?runtime->host_.dataRequest(runtime->host_.context,op,first,second,options,payload,length,offset,count,&error):0;
  if (!id) return pushError(state,error);
  lua_pushinteger(state,id);return 1;
}
int FireLuaRuntime::dataDevelop(lua_State* state) {
  auto* runtime=self(state);
  if (!runtime->dataEngine_ || !runtime->callbackButtonPressed_ || runtime->callbackPhase_!=CallbackPhase::OnButton)
    return pushError(state,"permission_denied");
  const char* mode=dataString(state,1,8);
  if (strcmp(mode,"update") && strcmp(mode,"fork") && strcmp(mode,"feedback")) return pushError(state,"invalid_argument");
  const char* instruction=lua_isnoneornil(state,2)?"":dataString(state,2,FireDataEngineContract::kInstructionBytes);
  if (!runtime->chargeIo(strlen(mode)+strlen(instruction))) return luaL_error(state,"hardware io budget exceeded");
  const char* error="unavailable";
  if (!runtime->host_.dataDevelop || !runtime->host_.dataDevelop(runtime->host_.context,mode,instruction,&error)) return pushError(state,error);
  lua_pushboolean(state,1);return 1;
}
int FireLuaRuntime::bluetoothAdvertiseRaw(lua_State* state) {
  auto* runtime=self(state);luaL_checktype(state,1,LUA_TTABLE);
  const size_t length=lua_rawlen(state,1);uint8_t bytes[31];
  if (!length || length>sizeof(bytes)) return pushError(state,"invalid_argument");
  for (size_t i=0;i<length;++i) {
    lua_geti(state,1,i+1);if (!lua_isinteger(state,-1)) return luaL_argerror(state,1,"byte must be an integer");
    bytes[i]=static_cast<uint8_t>(strictInt(state,-1,0,255));lua_pop(state,1);
  }
  const uint32_t duration=static_cast<uint32_t>(strictInt(state,2,100,10000));
  if (!runtime->chargeIo(length)) return luaL_error(state,"hardware io budget exceeded");
  const char* error="unavailable";
  const uint16_t id=runtime->host_.bluetoothAdvertiseRaw?runtime->host_.bluetoothAdvertiseRaw(runtime->host_.context,bytes,length,duration,&error):0;
  if (!id) return pushError(state,error);
  lua_pushinteger(state,id);return 1;
}
int FireLuaRuntime::bluetoothScan(lua_State* s) {return bluetoothCall(s,"scan");}
int FireLuaRuntime::bluetoothReadGatt(lua_State* s) {return bluetoothCall(s,"read_gatt");}
int FireLuaRuntime::bluetoothWriteGatt(lua_State* s) {return bluetoothCall(s,"write_gatt");}
int FireLuaRuntime::bluetoothAdvertise(lua_State* s) {return bluetoothCall(s,"advertise");}
int FireLuaRuntime::bluetoothCall(lua_State* state,const char* op) {
  auto* runtime=self(state);const char *a="",*b="",*c="";uint8_t bytes[128];size_t length=0;
  if (!strcmp(op,"scan")) {
    a=dataString(state,1,8);if (strcmp(a,"ble")) return pushError(state,"unavailable");
  } else if (!strcmp(op,"advertise")) {a=dataString(state,1,32);b=dataString(state,2,40);}
  else {
    a=dataString(state,1,64);b=dataString(state,2,40);c=dataString(state,3,40);
    if (!strcmp(op,"write_gatt")) {
      luaL_checktype(state,4,LUA_TTABLE);length=lua_rawlen(state,4);
      if (!length || length>sizeof(bytes)) return pushError(state,"invalid_argument");
      for (size_t i=0;i<length;++i) {
        lua_geti(state,4,i+1);if (!lua_isinteger(state,-1)) return luaL_argerror(state,4,"byte must be an integer");
        bytes[i]=static_cast<uint8_t>(strictInt(state,-1,0,255));lua_pop(state,1);
      }
    }
  }
  if (!runtime->chargeIo(strlen(a)+strlen(b)+strlen(c)+length)) return luaL_error(state,"hardware io budget exceeded");
  const char* error="unavailable";
  const uint16_t id=runtime->host_.bluetoothRequest?runtime->host_.bluetoothRequest(runtime->host_.context,op,a,b,c,bytes,length,&error):0;
  if (!id) return pushError(state,error);
  lua_pushinteger(state,id);return 1;
}
int FireLuaRuntime::bluetoothClose(lua_State* state) {
  auto* runtime=self(state);const uint16_t id=static_cast<uint16_t>(strictInt(state,1,1,65535));
  if (!runtime->chargeIo(1)) return luaL_error(state,"hardware io budget exceeded");
  lua_pushboolean(state,runtime->host_.bluetoothClose && runtime->host_.bluetoothClose(runtime->host_.context,id));return 1;
}

int FireLuaRuntime::micLevel(lua_State* state) {
  auto* runtime = self(state);
  if (!runtime->chargeIo(1)) return luaL_error(state, "hardware io budget exceeded");
  float level = 0;
  const char* error = "unavailable";
  if (!runtime->host_.micLevel ||
      !runtime->host_.micLevel(runtime->host_.context, &level, &error))
    return pushError(state, error);
  lua_pushnumber(state, level);
  return 1;
}
int FireLuaRuntime::wifiStatus(lua_State* state) {
  auto* runtime=self(state);String ssid,ip;int rssi=0;bool connected=false;
  if (!runtime->chargeIo(1)) return luaL_error(state,"hardware io budget exceeded");
  if (!runtime->host_.wifiStatus || !runtime->host_.wifiStatus(runtime->host_.context,&ssid,&ip,&rssi,&connected)) return pushError(state,"unavailable");
  lua_newtable(state);lua_pushboolean(state,connected);lua_setfield(state,-2,"connected");
  lua_pushlstring(state,ssid.c_str(),ssid.length());lua_setfield(state,-2,"ssid");
  lua_pushlstring(state,ip.c_str(),ip.length());lua_setfield(state,-2,"ip");
  lua_pushinteger(state,rssi);lua_setfield(state,-2,"rssi");return 1;
}
int FireLuaRuntime::wifiScan(lua_State* state) {
  auto* runtime=self(state);
  if (!runtime->chargeIo(1)) return luaL_error(state,"hardware io budget exceeded");
  const char* error="unavailable";const uint16_t id=runtime->host_.wifiScan?runtime->host_.wifiScan(runtime->host_.context,&error):0;
  if (!id) return pushError(state,error);
  lua_pushinteger(state,id);return 1;
}

int FireLuaRuntime::micRecord(lua_State* state) {
  auto* runtime = self(state);
  size_t length = 0;
  const char* path = checkedPath(state, 1, &length);
  const int duration = strictInt(state, 2, 100, 10000);
  if (!fire_data_paths::safeMutation(path)) return pushError(state,"permission_denied");
  const int rate = strictInt(state, 3, 8000, 16000);
  if (rate != 8000 && rate != 16000) return luaL_argerror(state, 3, "unsupported sample rate");
  if (!runtime->chargeIo(length, true)) return luaL_error(state, "hardware io budget exceeded");
  const char* error = "unavailable";
  const uint16_t job = runtime->host_.micRecord
      ? runtime->host_.micRecord(runtime->host_.context, path, duration, rate, &error) : 0;
  if (!job) return pushError(state, error);
  lua_pushinteger(state, job);
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

struct AiLuaJsonSink {
  lua_State* state;
  bool object() {lua_newtable(state);return true;}
  bool array() {lua_newtable(state);return true;}
  bool key(const char* value,size_t length) {lua_pushlstring(state,value,length);return true;}
  bool index(unsigned value) {lua_pushinteger(state,value);return true;}
  bool pair() {lua_rawset(state,-3);return true;}
  bool end() {return true;}
  bool string(const char* value,size_t length) {lua_pushlstring(state,value,length);return true;}
  bool number(double value) {
    const lua_Number number=static_cast<lua_Number>(value);if(!isfinite(number)) return false;
    const double upper=-static_cast<double>(LUA_MININTEGER);
    if(value>=static_cast<double>(LUA_MININTEGER) && value<upper && floor(value)==value)
      lua_pushinteger(state,static_cast<lua_Integer>(value));
    else lua_pushnumber(state,number);
    return true;
  }
  bool boolean(bool value) {lua_pushboolean(state,value);return true;}
  bool null() {lua_pushnil(state);return true;}
};

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
  if (snapshot.resultKind == FireLuaRuntime::JobSnapshot::Data) {
    const int top=lua_gettop(state);AiLuaJsonSink sink{state};
    const bool valid=snapshot.text.length()<=FireDataEngineContract::kResultBytes &&
      fire_runtime_ai_json::Reader<AiLuaJsonSink>(snapshot.text.c_str(),snapshot.text.length(),sink,FireDataEngineContract::kJsonDepth).object();
    if (valid) lua_replace(state,top);
    else {lua_settop(state,top);lua_pushboolean(state,0);lua_setfield(state,-2,"ok");lua_pushliteral(state,"invalid_data");lua_setfield(state,-2,"error_code");}
  } else if (snapshot.resultKind == FireLuaRuntime::JobSnapshot::DataRead) {
    lua_newtable(state);
    for (uint16_t i=0;i<snapshot.byteCount && i<FireDataEngineContract::kReadBytes;++i) {lua_pushinteger(state,snapshot.bytes[i]);lua_seti(state,-2,i+1);}
    lua_setfield(state,-2,"bytes");lua_pushinteger(state,snapshot.written);lua_setfield(state,-2,"offset");
    lua_pushboolean(state,snapshot.connected);lua_setfield(state,-2,"eof");
  } else if (snapshot.resultKind == FireLuaRuntime::JobSnapshot::RuntimeAi) {
    const int top=lua_gettop(state);AiLuaJsonSink sink{state};
    const bool valid=snapshot.text.length()<=FireRuntimeAiContract::kResultBytes &&
      fire_runtime_ai_json::Reader<AiLuaJsonSink>(snapshot.text.c_str(),snapshot.text.length(),sink,FireRuntimeAiContract::kJsonDepth).object();
    if(valid) lua_setfield(state,-2,"data");
    else {
      lua_settop(state,top);lua_pushboolean(state,0);lua_setfield(state,-2,"ok");
      lua_pushliteral(state,"invalid_result");lua_setfield(state,-2,"error_code");
    }
  } else if (snapshot.resultKind == FireLuaRuntime::JobSnapshot::I2cScan) {
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
  } else if (snapshot.resultKind == FireLuaRuntime::JobSnapshot::Recording) {
    lua_pushlstring(state, snapshot.path.c_str(), snapshot.path.length());
    lua_setfield(state, -2, "path");
    lua_pushinteger(state, snapshot.sizeBytes);
    lua_setfield(state, -2, "size_bytes");
    lua_pushinteger(state, snapshot.sampleRate);
    lua_setfield(state, -2, "sample_rate");
  } else if (snapshot.resultKind == FireLuaRuntime::JobSnapshot::Handle) {
    lua_pushinteger(state,snapshot.handle);lua_setfield(state,-2,"handle");
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
  if((snapshot.resultKind==JobSnapshot::RuntimeAi || snapshot.resultKind==JobSnapshot::Data) &&
     !runtime->chargeIo(snapshot.text.length())) return luaL_error(state,"hardware io budget exceeded");
  if(snapshot.resultKind==JobSnapshot::DataRead && !runtime->chargeIo(snapshot.byteCount)) return luaL_error(state,"hardware io budget exceeded");
  pushJobResult(state, snapshot);
  return 1;
}

int FireLuaRuntime::aiRequest(lua_State* state) {
  auto* runtime=self(state);
  if(!runtime->appSdk_ || !serviceAllowed(runtime,kServiceAi) || !serviceAllowed(runtime,kServiceJobs))
    return pushError(state,"permission_denied");
  if(runtime->callbackPhase_!=CallbackPhase::Update && runtime->callbackPhase_!=CallbackPhase::OnButton)
    return pushError(state,"stale_run");
  if(lua_gettop(state)<3 || lua_gettop(state)>4 || lua_type(state,1)!=LUA_TSTRING ||
     lua_type(state,2)!=LUA_TSTRING || lua_type(state,3)!=LUA_TSTRING) return pushError(state,"invalid_json");
  size_t ni=0,nd=0,ns=0;
  const char* instructions=lua_tolstring(state,1,&ni);const char* data=lua_tolstring(state,2,&nd);const char* schema=lua_tolstring(state,3,&ns);
  if(!ni || !nd || !ns || ni>FireRuntimeAiContract::kInstructionsBytes || nd>FireRuntimeAiContract::kDataBytes ||
     ns>FireRuntimeAiContract::kSchemaBytes || ni+nd+ns>FireRuntimeAiContract::kRequestBytes) return pushError(state,"payload_too_large");
  size_t offset=0;uint32_t cp=0;
  while(offset<ni) if(!fire_app_bitmap::codepoint(instructions,ni,offset,cp)) return pushError(state,"invalid_json");
  if(!fire_runtime_ai_json::validObject(data,nd,FireRuntimeAiContract::kDataBytes)) return pushError(state,"invalid_json");
  // Schema structural nesting exceeds result nesting (properties/items wrappers).
  // Semantic schema validation occurs at the OS host and again in the backend.
  if(!fire_runtime_ai_json::validObject(schema,ns,FireRuntimeAiContract::kSchemaBytes,12)) return pushError(state,"invalid_schema");
  uint32_t timeout=FireRuntimeAiContract::kTimeoutDefaultMs;
  if(lua_gettop(state)==4 && !lua_isnil(state,4)) {
    if(!lua_isinteger(state,4)) return pushError(state,"invalid_json");
    const lua_Integer value=lua_tointeger(state,4);
    if(value<static_cast<lua_Integer>(FireRuntimeAiContract::kTimeoutMinMs) ||
       value>static_cast<lua_Integer>(FireRuntimeAiContract::kTimeoutMaxMs)) return pushError(state,"invalid_json");
    timeout=static_cast<uint32_t>(value);
  }
  if(!runtime->chargeIo(ni+nd+ns)) return luaL_error(state,"hardware io budget exceeded");
  const char* error="unavailable";
  const uint16_t id=runtime->host_.aiRequest?runtime->host_.aiRequest(runtime->host_.context,instructions,ni,data,nd,schema,ns,timeout,&error):0;
  if(!id) return pushError(state,error?error:"unavailable");lua_pushinteger(state,id);return 1;
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
