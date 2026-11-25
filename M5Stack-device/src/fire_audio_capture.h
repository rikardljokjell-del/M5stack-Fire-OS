#pragma once

#include <Arduino.h>

bool fireStartMicCapture(int16_t* target, size_t maxSamples,
                         uint32_t sampleRate,bool rawMeasurement=false);
bool fireMicCaptureRunning();
size_t fireMicCapturedSamples();
bool fireMicCaptureFailed();
void fireStopMicCapture();
bool fireReleaseMicCapture();
bool fireTryReleaseMicCapture();
