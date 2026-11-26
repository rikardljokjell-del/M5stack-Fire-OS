#pragma once
#include <stdint.h>
namespace fire_ui_cadence {
template<class Screen> constexpr Screen contentScreen(Screen current,Screen previous,Screen overlay) {return current==overlay?previous:current;}
inline bool networkAllowed(bool wifiOff,bool backendOff) {return !wifiOff && !backendOff;}
enum class View:uint8_t {Static,Live,Developer,Lua};
constexpr uint32_t period(View view) {return view==View::Developer?33:view==View::Lua?25:view==View::Live?50:1000;}
inline bool due(uint32_t now,uint32_t last,bool dirty,View view) {return dirty || uint32_t(now-last)>=period(view);}
}
