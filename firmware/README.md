# FIRE OS firmware

This folder contains device-compatible FIRE OS `.bin` builds for the M5Stack
FIRE. Copy a selected `.bin` to the SD card at `/firmware/`, then open
`Settings -> Firmware` on the device.

The device validates the ESP32 image, writes the inactive OTA slot, verifies
the result and reboots only after explicit confirmation. Keep the previous
known-good firmware available for recovery.

`index.json` is the public catalog used by `Settings -> Firmware -> GitHub
firmware`. It must contain only tested M5Stack FIRE builds and the exact
SHA-256/size of each binary.

The current catalog entry is `fire-os-1.1.bin`.

The current binary is the device firmware from the latest verified
`m5stack-fire-ble` build. Always use the exact size and SHA-256 from
`index.json`; the firmware menu rejects mismatches.
