// Frozen RC14 producer, retained solely for byte-parity testing.
  const String fields = ",\"target\":\"device\",\"boot_id\":\"" +
                        jsonEscape(bootId_) +
                        "\",\"capabilities\":{\"api_version\":\"fire-lua-0.2\",\"api_contract\":\"" +
                        FireLuaRuntime::hardwareApiContract() +
                        "\",\"app_sdk\":{\"version\":\"" + FireLuaRuntime::appSdkVersion() +
                        "\",\"contract\":\"" + FireLuaRuntime::appSdkContract() +
                        "\"},\"runtime_ai\":{\"version\":\""+FireRuntimeAiContract::kVersion+
                        "\",\"contract\":\""+FireRuntimeAiContract::kContract+"\"},\"evolution\":{\"version\":\""+FireEvolutionContract::kVersion+
                        "\",\"contract\":\""+FireEvolutionContract::kContract+"\"},\"data_engine\":"+dataCapabilities() +
                        hardwareServiceCapabilities() + ",\"hardware\":{\"gpio_read\":[26,35,36],\"gpio_write\":[26],\"adc\":[36],\"dac\":[26],\"pwm\":[26],\"i2c\":[0],\"i2c_write_addresses\":"+i2cWriteResources()+",\"uart\":[2],\"spi\":[2]},\"max_memory\":131072,\"max_runtime_ms\":0,\"audio_input\":true,\"audio_output\":true,\"firmware_storage\":false,\"firmware_max_bytes\":4194304,\"firmware_version\":\"" +
                        jsonEscape(firmwareVersion_) + "\"}";
  String payload = "{\"type\":\"device_event\",\"protocol_version\":\"0.2\",\"event_id\":\"" +
                   eventId("evt") + "\",\"device_id\":\"" +
                   jsonEscape(deviceId_) + "\",\"event\":\"session_start\"" +
                   fire_session::startFields(resumeSessionId_,developmentContext_) +
                   fields + "}";
