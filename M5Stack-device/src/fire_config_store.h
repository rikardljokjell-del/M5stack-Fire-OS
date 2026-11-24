#pragma once
#include <Preferences.h>
#include <nvs_flash.h>
#include <esp_partition.h>

// Only dedicated, exactly located configuration partitions may be formatted.
// Their first migration can encounter old SPIFFS bytes. Never erase default NVS.
inline bool fireOpenConfig(Preferences& prefs, const char* space, const char* partition,
                           uint32_t address, uint32_t size) {
  const auto* part = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_NVS, partition);
  if (!part || part->address != address || part->size != size) return false;
  esp_err_t error = nvs_flash_init_partition(partition);
  if (error == ESP_ERR_NVS_NO_FREE_PAGES || error == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    if (nvs_flash_erase_partition(partition) != ESP_OK) return false;
    error = nvs_flash_init_partition(partition);
  }
  return error == ESP_OK && prefs.begin(space, false, partition);
}
