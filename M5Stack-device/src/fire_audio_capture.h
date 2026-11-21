#pragma once

#include <Arduino.h>

bool firePrepareMicCapture(uint32_t sampleRate);
void fireReleaseMicCapture();
bool fireRecordMic(int16_t* samples, size_t sampleCount, uint32_t sampleRate);
