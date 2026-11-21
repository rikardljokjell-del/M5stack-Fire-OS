#include "fire_os.h"

FireOS* fireOs = nullptr;

void setup() {
  Serial.begin(115200);
  fireOs = new FireOS();
  if (fireOs) fireOs->begin();
}

void loop() {
  if (fireOs) fireOs->update();
}
