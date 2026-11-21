#include "fire_lua_runtime.h"

#include <esp_heap_caps.h>
#include <math.h>
extern "C" {
#include <lauxlib.h>
}

namespace {
constexpr int kDisplayWidth = 320;
constexpr int kDisplayHeight = 240;

int boundedInt(lua_State* state, int index, int minimum, int maximum) {
  const lua_Integer value = luaL_checkinteger(state, index);
  return static_cast<int>(constrain(static_cast<long>(value), minimum, maximum));
}

const char* checkedString(lua_State* state, int index) {
  return luaL_checklstring(state, index, nullptr);
}
}  // namespace

void* FireLuaRuntime::allocator(void* user, void* pointer, size_t oldSize,
                                size_t newSize) {
  auto* runtime = static_cast<FireLuaRuntime*>(user);
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
  if (runtime->instructions_ > kMaxInstructionsPerCallback ||
      millis() - runtime->frameStarted_ > kMaxCallbackMs) {
    luaL_error(state, "app callback budget exceeded");
  }
}

void FireLuaRuntime::setFunction(lua_State* state, const char* name,
                                 lua_CFunction fn) {
  lua_pushcfunction(state, fn);
  lua_setfield(state, -2, name);
}

void FireLuaRuntime::registerApi(lua_State* state) {
  auto* runtime = self(state);
  if (!runtime) return;

  lua_newtable(state);  // fire

  lua_newtable(state);  // fire.display
  setFunction(state, "clear", displayClear);
  setFunction(state, "circle", displayCircle);
  setFunction(state, "rect", displayRect);
  setFunction(state, "line", displayLine);
  setFunction(state, "text", displayText);
  lua_setfield(state, -2, "display");

  lua_newtable(state);  // fire.buttons
  setFunction(state, "pressed", buttonPressed);
  lua_setfield(state, -2, "buttons");

  lua_newtable(state);  // fire.rgb
  setFunction(state, "set", rgbSet);
  lua_setfield(state, -2, "rgb");

  lua_newtable(state);  // fire.imu
  setFunction(state, "accel", imuAccel);
  lua_setfield(state, -2, "imu");

  lua_newtable(state);  // fire.time
  setFunction(state, "millis", timeMillis);
  lua_setfield(state, -2, "time");

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
  host_ = host;
  lua_ = lua_newstate(allocator, this);
  if (!lua_) return fail("Lua memory unavailable");
  auto** pointer = static_cast<FireLuaRuntime**>(lua_getextraspace(lua_));
  *pointer = this;

  // Only the small, safe subset needed by generated apps is exposed.
  registerBase(lua_);
  registerMath(lua_);
  removeUnsafeGlobals(lua_);
  registerApi(lua_);
  lua_sethook(lua_, instructionHook, LUA_MASKCOUNT, 1000);
  state_ = State::Stopped;
  error_ = "";
  return true;
}

bool FireLuaRuntime::loadSource(const uint8_t* source, size_t length) {
  if (!lua_ || !source || length == 0 || length > kMaxSourceBytes) {
    return fail("Invalid Lua source");
  }
  clearState();
  instructions_ = 0;
  frameStarted_ = millis();
  if (luaL_loadbufferx(lua_, reinterpret_cast<const char*>(source), length,
                       "main.lua", "t") != LUA_OK) {
    return fail(String("Lua syntax: ") + lua_tostring(lua_, -1));
  }
  if (lua_pcall(lua_, 0, 0, 0) != LUA_OK) {
    return fail(String("Lua init chunk: ") + lua_tostring(lua_, -1));
  }
  lua_getglobal(lua_, "init");
  if (!lua_isfunction(lua_, -1)) {
    lua_pop(lua_, 1);
    return fail("Lua app requires init()");
  }
  if (lua_pcall(lua_, 0, 0, 0) != LUA_OK) {
    return fail(String("Lua init: ") + lua_tostring(lua_, -1));
  }
  lua_getglobal(lua_, "update");
  const bool hasUpdate = lua_isfunction(lua_, -1);
  lua_pop(lua_, 1);
  if (!hasUpdate) return fail("Lua app requires update(dt_ms)");
  state_ = State::Running;
  startedAt_ = millis();
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
  instructions_ = 0;
  frameStarted_ = millis();
  if (lua_pcall(lua_, argumentCount, 0, 0) != LUA_OK) {
    return fail(String("Lua ") + function + ": " + lua_tostring(lua_, -1));
  }
  return true;
}

bool FireLuaRuntime::update(uint32_t dtMs) {
  if (state_ != State::Running) return state_ != State::Failed;
  if (millis() - startedAt_ > kMaxRuntimeMs)
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
  instructions_ = 0;
  frameStarted_ = millis();
  if (lua_pcall(lua_, 2, 0, 0) != LUA_OK) {
    return fail(String("Lua on_button: ") + lua_tostring(lua_, -1));
  }
  return true;
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
  const int color = boundedInt(state, 1, 0, 65535);
  if (runtime->host_.displayClear) runtime->host_.displayClear(runtime->host_.context, color);
  return 0;
}

int FireLuaRuntime::displayCircle(lua_State* state) {
  auto* runtime = self(state);
  const int x = boundedInt(state, 1, 0, kDisplayWidth - 1);
  const int y = boundedInt(state, 2, 0, kDisplayHeight - 1);
  const int radius = boundedInt(state, 3, 0, kDisplayWidth);
  if (!checkColor(state, 4)) return luaL_error(state, "invalid color");
  const int color = static_cast<int>(lua_tointeger(state, 4));
  if (runtime->host_.displayCircle) runtime->host_.displayCircle(runtime->host_.context, x, y, radius, color);
  return 0;
}

int FireLuaRuntime::displayRect(lua_State* state) {
  auto* runtime = self(state);
  const int x = boundedInt(state, 1, 0, kDisplayWidth - 1);
  const int y = boundedInt(state, 2, 0, kDisplayHeight - 1);
  const int width = boundedInt(state, 3, 0, kDisplayWidth);
  const int height = boundedInt(state, 4, 0, kDisplayHeight);
  if (!checkColor(state, 5)) return luaL_error(state, "invalid color");
  const int color = static_cast<int>(lua_tointeger(state, 5));
  if (runtime->host_.displayRect) runtime->host_.displayRect(runtime->host_.context, x, y, width, height, color);
  return 0;
}

int FireLuaRuntime::displayLine(lua_State* state) {
  auto* runtime = self(state);
  const int x1 = boundedInt(state, 1, 0, kDisplayWidth - 1);
  const int y1 = boundedInt(state, 2, 0, kDisplayHeight - 1);
  const int x2 = boundedInt(state, 3, 0, kDisplayWidth - 1);
  const int y2 = boundedInt(state, 4, 0, kDisplayHeight - 1);
  if (!checkColor(state, 5)) return luaL_error(state, "invalid color");
  const int color = static_cast<int>(lua_tointeger(state, 5));
  if (runtime->host_.displayLine) runtime->host_.displayLine(runtime->host_.context, x1, y1, x2, y2, color);
  return 0;
}

int FireLuaRuntime::displayText(lua_State* state) {
  auto* runtime = self(state);
  const int x = boundedInt(state, 1, 0, kDisplayWidth - 1);
  const int y = boundedInt(state, 2, 0, kDisplayHeight - 1);
  const char* text = checkedString(state, 3);
  if (strlen(text) > 80) return luaL_error(state, "text too long");
  if (!checkColor(state, 4)) return luaL_error(state, "invalid color");
  if (runtime->host_.displayText) runtime->host_.displayText(runtime->host_.context, x, y, text, static_cast<int>(lua_tointeger(state, 4)));
  return 0;
}

int FireLuaRuntime::buttonPressed(lua_State* state) {
  auto* runtime = self(state);
  const char* name = checkedString(state, 1);
  lua_pushboolean(state, runtime->host_.buttonPressed && runtime->host_.buttonPressed(runtime->host_.context, name));
  return 1;
}

int FireLuaRuntime::rgbSet(lua_State* state) {
  auto* runtime = self(state);
  const int index = boundedInt(state, 1, 0, 9);
  const int red = boundedInt(state, 2, 0, 255);
  const int green = boundedInt(state, 3, 0, 255);
  const int blue = boundedInt(state, 4, 0, 255);
  if (runtime->host_.rgbSet) runtime->host_.rgbSet(runtime->host_.context, index, red, green, blue);
  return 0;
}

int FireLuaRuntime::imuAccel(lua_State* state) {
  auto* runtime = self(state);
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

int FireLuaRuntime::timeMillis(lua_State* state) {
  auto* runtime = self(state);
  lua_pushinteger(state, runtime->host_.timeMillis ? runtime->host_.timeMillis(runtime->host_.context) : millis());
  return 1;
}
