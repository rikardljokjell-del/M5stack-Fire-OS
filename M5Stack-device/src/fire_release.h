#pragma once
#include <Arduino.h>
#include <SD.h>

struct FireRelease {
  String name, version, notes, hash, path, commit;
  uint32_t size = 0;
};
struct FireReleaseCatalog {
  FireRelease files[8];
  uint8_t count = 0;
};
bool fireVerifyCatalog(const String& envelope, FireReleaseCatalog& result);
bool fireVerifyReleaseFile(const String& path, FireRelease& release);
bool fireRecoveryLayout();
