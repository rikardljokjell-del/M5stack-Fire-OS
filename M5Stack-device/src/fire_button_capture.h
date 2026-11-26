#pragma once
#include "fire_buttons.h"
namespace fire_button_capture {
bool begin();
void pause();
bool active();
uint8_t mask();
void sleeping(bool value);
void shown(uint32_t context);
bool pop(fire_buttons::Edge& edge);
bool pending();
bool takeOverflow();
void discard();
uint32_t dropped();
}
