#include "fire_os.h"

extern "C" bool verifyRollbackLater() { return true; }

FireOS* fireOs = nullptr;

void setup() {
  Serial.begin(115200);
  fireOs = new FireOS();
  if (fireOs) fireOs->begin();
  // Arduino feeds this task only between loop iterations. SDK 2.0.14 uses
  // the existing 5 s panic/reset watchdog; a hung UI must not feed itself.
  enableLoopWDT();
}

void loop() {
  if (fireOs) fireOs->update();
}
