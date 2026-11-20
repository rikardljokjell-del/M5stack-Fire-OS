# FIRE OS external app recovery contract

External firmware is installed into an ESP32 OTA slot. The bootloader can
return to FIRE OS after a reset only when the external firmware participates in
the OTA rollback contract.

An Arduino/ESP-IDF external app must defer OTA verification and leave its image
pending until it is intentionally approved:

```cpp
extern "C" bool verifyRollbackLater() {
  return true;
}
```

If the app then reboots or loses power before calling
`esp_ota_mark_app_valid_cancel_rollback()`, the ESP32 bootloader rolls back to
the previous FIRE OS image. FIRE OS then applies its saved Boot App setting.

An app that marks itself valid becomes a normal persistent OTA image and cannot
be forcibly returned to FIRE OS by FIRE OS alone. Arbitrary third-party `.bin`
files therefore cannot be guaranteed to return after power loss without this
contract or a custom bootloader. FIRE OS keeps the factory image protected and
uses A+B+C at boot as the unconditional recovery path.
