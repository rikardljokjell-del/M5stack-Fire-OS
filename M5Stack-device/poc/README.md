# FIRE OS external-loader POC

This proof of concept is intentionally isolated from the stable FIRE OS environments.

It verifies the first safe layer of the external-firmware design:

- custom 16 MB partition table with a `factory` loader and two OTA app slots;
- `/apps/*.bin` discovery on the FIRE SD card;
- basic ESP32 image-header, chip-id and slot-size validation;
- OTA writing to the inactive app slot through `esp_ota_*` APIs;
- preservation of the active slot when validation or writing fails;
- detection of the A+B+C safe-boot condition.

The POC does not automatically install or select an app. Hardware testing must first
confirm the partition table, safe boot, reset behavior, SD removal behavior and rollback
behavior. Only after that should the loader be integrated with the full FIRE OS UI and
permanent Boot App setting.

Generic third-party `.bin` files are not guaranteed to return to FIRE OS. A production
version therefore needs either a FIRE OS app contract/health handshake or a verified
bootloader-level recovery path.
