#pragma once

#include <Arduino.h>
#include <SD.h>
#include <esp_ota_ops.h>
#include "fire_lua_runtime.h"
#include "fire_backend_client.h"
#include "fire_lua_package_manager.h"
#include "fire_reverse_transport.h"

class DateTimeService {
 public:
  static constexpr uint8_t kTimezoneCount = 7;

  void begin();
  bool setLocalDateTime(uint16_t year, uint8_t month, uint8_t day,
                       uint8_t hour, uint8_t minute);
  bool setSystemLocalDateTime(const tm& localTime);
  void setTimezone(uint8_t index);
  void setDstAuto(bool enabled);
  void reset();
  void save();

  String localDateTime() const;
  String statusDateTime() const;
  String localTime() const;
  String timezoneLabel() const;
  String timezoneLabel(uint8_t index) const;
  const char* timezoneRule() const;
  uint8_t timezoneIndex() const { return timezoneIndex_; }
  bool dstAuto() const { return dstAuto_; }
  bool configured() const { return configured_; }

 private:
  uint8_t timezoneIndex_ = 1;
  bool dstAuto_ = true;
  bool configured_ = false;

  void applyTimezone() const;
};

class FireOS {
 public:
  void begin();
  void update();

  DateTimeService& dateTime() { return dateTime_; }
  const DateTimeService& dateTime() const { return dateTime_; }
  bool safeMode() const { return safeMode_; }
  void requestWifi(bool enabled);
  void saveWifiCredentials(const String& ssid, const String& password);
  void saveMobileSetupFields(const String& ssid, const String& password,
                             const String& apiKey);
  void saveBackendSetupFields(const String& host, const String& port,
                              const String& token, const String& deviceId);
  bool wifiSetupTokenValid(const String& token) const;
  bool aiApiSetupActive() const { return aiApiSetupActive_; }

 private:
  enum class Screen : uint8_t {
    Main,
    Apps,
    Settings,
    DateTime,
    DisplaySound,
    Wifi,
    Bluetooth,
    Boot,
    MainMenuSettings,
    Shortcuts,
    AppsSettings,
    Help,
    QuickSettings,
    Placeholder,
    Debug,
    SystemInfo,
    Power,
    PowerActions,
    FactoryReset,
    FileExplorer,
    AiDeveloper,
    AiApi,
    LuaApp,
  };

  struct ButtonState {
    bool down = false;
    bool rawPressed = false;
    bool longTriggered = false;
    bool wakeOnly = false;
    bool clickPending = false;
    uint32_t started = 0;
    uint32_t lastClickAt = 0;
    uint32_t rawChangedAt = 0;
  };

  static constexpr uint8_t kButtonCount = 3;
  static constexpr uint8_t kMainCount = 5;
  static constexpr uint8_t kSettingsCount = 16;
  static constexpr uint8_t kQuickCount = 8;
  static constexpr uint8_t kPowerCount = 6;
  static constexpr uint8_t kPowerActionCount = 4;
  static constexpr uint8_t kMaxBluetoothDevices = 32;
  static constexpr uint8_t kMaxBluetoothSavedDevices = 5;
  static constexpr uint8_t kDurationCount = 21;
  static constexpr uint8_t kDateFieldCount = 11;
  static constexpr uint8_t kDoubleClickActionCount = 9;
  static constexpr int16_t kCarouselDistance = 112;
  static constexpr uint32_t kLongPressMs = 650;
  static constexpr uint32_t kDoubleClickWindowMs = 350;
  static constexpr uint32_t kButtonDebounceMs = 18;

  Screen screen_ = Screen::Main;
  Screen previousScreen_ = Screen::Main;
  ButtonState buttons_[kButtonCount];
  DateTimeService dateTime_;

  uint8_t mainIndex_ = 0;
  bool mainVisible_[kMainCount] = {true, true, true, true, true};
  uint8_t carouselFromIndex_ = 0;
  uint8_t carouselToIndex_ = 0;
  int8_t carouselDirection_ = 0;
  int16_t carouselOffset_ = 0;
  uint32_t carouselLastStepAt_ = 0;
  int8_t carouselQueuedDirection_ = 0;
  bool carouselAnimating_ = false;
  uint8_t appsIndex_ = 0;
  uint8_t settingsIndex_ = 0;
  uint8_t quickIndex_ = 0;
  bool quickEditing_ = false;
  uint8_t powerIndex_ = 0;
  bool powerEditing_ = false;
  uint8_t powerActionIndex_ = 0;
  uint8_t sleepOption_ = 0;
  uint8_t dimOption_ = 2;
  uint8_t screenOffOption_ = 3;
  uint8_t doubleClickAction_[kButtonCount] = {0, 0, 0};
  uint8_t placeholderIndex_ = 0;
  bool safeMode_ = false;
  bool factoryResetArmed_ = false;
  bool wifiEnabled_ = false;
  uint8_t wifiMode_ = 0;  // 0=Auto, 1=On, 2=Off
  bool wifiTimeSync_ = false;
  bool timeSyncPending_ = false;
  bool timeSyncConfigured_ = false;
  uint32_t timeSyncStarted_ = 0;
  uint32_t timeSyncLastConnectAttempt_ = 0;
  uint32_t timeSyncLastPollAt_ = 0;
  String timeSyncStatus_;
  String timeSyncLast_;
  bool bluetoothEnabled_ = false;
  bool bluetoothBootInitPending_ = false;
  bool bluetoothScanInProgress_ = false;
  bool bootFeedbackActive_ = false;
  uint32_t bootFeedbackStarted_ = 0;
  uint32_t bootFeedbackLastFrame_ = 0;
  bool bootMelodyStarted_ = false;
  uint8_t brightness_ = 180;
  uint8_t volume_ = 90;
  uint8_t brightnessStep_ = 6;
  uint8_t volumeStep_ = 8;
  uint8_t aiDeveloperMode_ = 0;  // 0=idle, 1=listening, 2=thinking, 3=speaking
  uint8_t aiWorkflowState_ = 0;  // 0 idle, 1 listening, 2 thinking, 3 confirm, 4 building, 5 ready, 6 running
  uint8_t aiBuildProgress_ = 0;
  uint32_t aiWorkflowStarted_ = 0;
  uint8_t aiRestPhase_ = 0;       // 0=rest, 1=tired, 2=sleeping
  uint32_t aiRestPhaseStarted_ = 0;
  uint32_t aiRestPhaseDuration_ = 0;
  uint32_t lastActivity_ = 0;
  uint32_t lastDrawAt_ = 0;
  bool redrawRequested_ = true;
  mutable int batteryLevelCached_ = -1;
  mutable bool batteryChargingCached_ = false;
  mutable uint32_t batteryStatusAt_ = 0;
  uint8_t displayPowerState_ = 0;

  static constexpr uint8_t kMaxFileEntries = 40;
  static constexpr uint8_t kFileVisibleRows = 6;
  static constexpr uint8_t kMaxExternalApps = 16;
  static constexpr uint8_t kMaxLuaApps = 16;
  bool sdReady_ = false;
  uint32_t sdLastProbe_ = 0;
  String sdPath_ = "/";
  String sdEntryNames_[kMaxFileEntries];
  String sdEntryPaths_[kMaxFileEntries];
  uint32_t sdEntrySizes_[kMaxFileEntries] = {};
  bool sdEntryDirectories_[kMaxFileEntries] = {};
  uint8_t sdEntryCount_ = 0;
  uint8_t sdSelection_ = 0;
  uint8_t sdOffset_ = 0;
  uint8_t sdSortMode_ = 0;
  bool sdActionMenu_ = false;
  uint8_t sdActionIndex_ = 0;
  bool sdDeleteConfirm_ = false;
  bool sdNameEditor_ = false;
  bool sdNameIsNewFolder_ = false;
  String sdNameBuffer_;
  uint8_t sdNameCursor_ = 0;
  String sdMessage_;
  bool sdPreview_ = false;
  bool sdImagePreview_ = false;
  String sdImagePreviewPath_;
  uint8_t sdImagePreviewType_ = 0;  // 1=JPG, 2=PNG, 3=BMP
  uint8_t* sdImageBuffer_ = nullptr;
  size_t sdImageBufferSize_ = 0;
  bool sdImageRendered_ = false;
  String sdPreviewLines_[8];
  uint8_t sdPreviewLineCount_ = 0;
  bool shortcutPicker_ = false;
  uint8_t shortcutPickerButton_ = 0;
  uint8_t shortcutPickerAction_ = 0;
  uint8_t shortcutPickerOffset_ = 0;
  String externalAppPaths_[kMaxExternalApps];
  String externalAppNames_[kMaxExternalApps];
  uint32_t externalAppSizes_[kMaxExternalApps] = {};
  uint32_t externalAppOffsets_[kMaxExternalApps] = {};
  bool externalAppCompatible_[kMaxExternalApps] = {};
  uint8_t externalAppCount_ = 0;
  bool appScanPending_ = false;
  uint8_t externalAppSelection_ = 0;
  uint8_t externalAppOffset_ = 0;
  String selectedBootAppPath_;
  bool bootAppPicker_ = false;
  uint8_t bootAppSelection_ = 0;
  uint8_t bootAppOffset_ = 0;
  String externalAppMessage_;
  bool appManagerActionMenu_ = false;
  uint8_t appManagerActionIndex_ = 0;
  bool appManagerDeleteConfirm_ = false;
  String luaAppPaths_[kMaxLuaApps];
  String luaAppNames_[kMaxLuaApps];
  uint8_t luaAppCount_ = 0;
  bool fileExplorerScanPending_ = false;

  FireLuaRuntime* luaRuntime_ = nullptr;
  bool luaRuntimeReady_ = false;
  bool luaAppActive_ = false;
  String luaAppPath_;
  String luaAppName_;
  String luaAppError_;
  uint32_t luaLastFrameAt_ = 0;
  uint8_t luaRgbValues_[10][3] = {};
  FireBackendClient* backendClient_ = nullptr;
  FireLuaPackageManager* packageManager_ = nullptr;
  FireReverseTransport reverseTransport_;
  String backendStatus_;
  String aiTurnId_;
  String aiProposalId_;
  String aiPackageId_;
  String aiInstallId_;
  String luaRunId_;
  bool luaHealthySent_ = false;
  String aiAssistantText_;
  String aiWorkflowText_;
  static constexpr uint32_t kAiAudioSampleRate = 16000;
  static constexpr uint32_t kAiAudioSeconds = 5;
  static constexpr size_t kAiAudioSamples =
      kAiAudioSampleRate * kAiAudioSeconds;
  static constexpr size_t kAiAudioWavBytes = 44 + kAiAudioSamples * 2;
  uint8_t* aiAudioBuffer_ = nullptr;
  volatile bool aiAudioCaptureFinished_ = false;
  volatile bool aiAudioStopSent_ = false;
  volatile bool aiAudioUploadFinished_ = false;
  volatile bool aiAudioUploadOk_ = false;
  bool aiAudioCaptureActive_ = false;
  size_t aiAudioCapturedSamples_ = 0;
  size_t aiAudioWavLength_ = 0;
  String aiAudioError_;

  // Date/time editor state. A/C select a field; B enters/leaves editing.
  uint8_t dateField_ = 0;
  bool dateEditing_ = false;
  uint8_t detailIndex_ = 0;
  bool detailEditing_ = false;
  uint8_t helpPage_ = 0;
  uint8_t wifiIndex_ = 0;
  int wifiScanCount_ = -1;
  bool wifiScanActive_ = false;
  bool wifiScanDialog_ = false;
  uint8_t wifiScanSelection_ = 0;
  uint8_t wifiScanOffset_ = 0;
  bool wifiConnectActive_ = false;
  uint32_t wifiOperationStarted_ = 0;
  String wifiStatus_;
  String wifiSsid_;
  String wifiPassword_;
  String wifiSavedSsid_[5];
  String wifiSavedPassword_[5];
  uint8_t wifiSavedCount_ = 0;
  uint8_t wifiSavedSelection_ = 0;
  uint8_t wifiSavedTarget_ = 0;
  uint8_t wifiSavedOffset_ = 0;
  bool wifiSavedDialog_ = false;
  bool wifiDeleteArmed_ = false;
  bool wifiSetupActive_ = false;
  bool aiApiSetupActive_ = false;
  String wifiSetupPassword_;
  String wifiSetupToken_;
  String aiApiKey_;
  String backendHost_;
  uint16_t backendPort_ = 8765;
  String backendToken_;
  String backendDeviceId_ = "m5stack-fire-01";
  uint8_t bluetoothIndex_ = 0;
  uint8_t bluetoothMode_ = 0;  // 0=Auto, 1=On, 2=Off
  int bluetoothScanCount_ = -1;
  uint8_t bluetoothScanSelection_ = 0;
  uint8_t bluetoothScanOffset_ = 0;
  bool bluetoothScanDialog_ = false;
  bool bluetoothUnknownDialog_ = false;
  bool bluetoothVisible_ = false;
  String bluetoothStatus_;
  String bluetoothNames_[kMaxBluetoothDevices];
  String bluetoothAddresses_[kMaxBluetoothDevices];
  int16_t bluetoothRssi_[kMaxBluetoothDevices] = {};
  uint8_t bluetoothAddressTypes_[kMaxBluetoothDevices] = {};
  String bluetoothSavedName_;
  String bluetoothSavedAddress_;
  String bluetoothSavedNames_[kMaxBluetoothSavedDevices];
  String bluetoothSavedAddresses_[kMaxBluetoothSavedDevices];
  uint8_t bluetoothSavedAddressTypes_[kMaxBluetoothSavedDevices] = {};
  uint8_t bluetoothSavedCount_ = 0;
  uint8_t bluetoothSavedSelection_ = 0;
  uint8_t bluetoothSavedOffset_ = 0;
  bool bluetoothSavedDialog_ = false;
  bool bluetoothSavedDeleteArmed_ = false;
  bool bluetoothConnected_ = false;
  bool buttonSoundsEnabled_ = true;
  bool bootRgbPulse_ = true;
  bool bootMelody_ = true;
  uint16_t editYear_ = 2026;
  uint8_t editMonth_ = 1;
  uint8_t editDay_ = 1;
  uint8_t editHour_ = 0;
  uint8_t editMinute_ = 0;
  uint8_t editTimezone_ = 1;
  bool editDstAuto_ = true;

  void loadSettings();
  void saveSettings();
  void loadSavedWifiNetworks();
  void saveSavedWifiNetworks();
  void loadSavedBluetoothDevices();
  void saveSavedBluetoothDevices();
  bool initSdCard();
  void refreshSdDirectory();
  void handleFileExplorerButton(uint8_t index);
  void handleFileExplorerAction(uint8_t index);
  void openSelectedSdEntry();
  void deleteSelectedSdEntry();
  void commitSdNameEditor();
  void copySelectedSdEntry();
  void moveSelectedSdEntry();
  String sdStorageLabel() const;
  String sdParentPath(const String& path) const;
  String sdJoinPath(const String& base, const String& name) const;
  String sdBaseName(const String& path) const;
  bool sdIsTextFile(const String& name) const;
  bool sdIsImageFile(const String& name) const;
  void previewSelectedSdFile();
  void previewSelectedSdImage();
  void releaseSdImageBuffer();
  void scanExternalApps();
  void scanLuaApps();
  bool deleteExternalApp(const String& path);
  bool deleteLuaApp(const String& path);
  bool inspectExternalImage(File& file, uint32_t& imageOffset,
                            uint32_t& imageSize,
                            bool verifyChecksum = true) const;
  bool installExternalApp(const String& path, bool rebootAfterInstall,
                          bool makeBootApp);
  bool launchSelectedBootApp();
  String externalAppBaseName(const String& path) const;
  void pollButtons();
  void onButton(uint8_t index, bool longPress);
  void onDoubleClick(uint8_t index);
  void playButtonSound(uint8_t index, bool longPress);
  void open(Screen screen);
  void startMainSlide(uint8_t nextIndex, int8_t direction);
  uint8_t visibleMainCount() const;
  uint8_t mainItemAtPosition(uint8_t position) const;
  uint8_t nextVisibleMain(uint8_t current, int8_t direction) const;
  void back();
  void home();
  void goToBootApp();
  void openQuickSettings();
  void openDateTimeEditor();
  void handleDateTimeButton(uint8_t index);
  void handleDisplaySoundButton(uint8_t index);
  void handleBootButton(uint8_t index);
  void playBootRgbPulse();
  void playBootMelody();
  void updateBootFeedback();
  void updateAiDeveloperMock();
  void handleHelpButton(uint8_t index);
  void handleAppsButton(uint8_t index);
  void handleAppsSettingsButton(uint8_t index);
  void handleWifiButton(uint8_t index);
  void handleBluetoothButton(uint8_t index);
  void handleBluetoothScanDialogButton(uint8_t index);
  void handleBluetoothSavedDialogButton(uint8_t index);
  bool isUnknownBluetoothDevice(uint8_t index) const;
  uint8_t bluetoothDeviceListCount(bool unknownOnly) const;
  int8_t bluetoothDeviceListIndex(uint8_t listIndex, bool unknownOnly) const;
  void scanWifiNetworks();
  void connectSavedWifi();
  void beginWifiConnection();
  void applyWifiMode();
  void deleteSelectedWifiNetwork();
  void moveSelectedWifiNetwork(int8_t direction);
  void updateWifiState();
  void startTimeSync();
  void updateTimeSync();
  void startWifiSetup();
  void startAiApiSetup();
  void stopWifiSetup();
  void scanBluetoothDevices();
  void updateBluetoothScan();
  bool initBluetooth();
  bool connectBluetoothDevice(uint8_t index);
  void disconnectBluetoothDevice();
  void deleteSelectedBluetoothDevice();
  void setBluetoothVisibility(bool visible);
  void closeBluetoothSettings();
  void handleQuickButton(uint8_t index);
  void handleFactoryResetButton(uint8_t index);
  void handlePowerButton(uint8_t index);
  void handlePowerActionsButton(uint8_t index);
  void handleAiDeveloperButton(uint8_t index);
  bool startAiRecording();
  void finishAiRecording();
  void updateAiAudio();
  void handleAiApiButton(uint8_t index);
  bool startLuaApp(const String& path, const String& name = String());
  void stopLuaApp(const String& reason = String());
  void updateLuaApp();
  void updateBackend();
  void handleBackendMessage(const String& message);
  static void backendMessage(void* context, const String& message);
  static void backendState(void* context, bool connected, const String& status);
  static void packageStatus(void* context, const String& status);
  static void packageResult(void* context, bool ok, const String& packageId,
                            const String& archiveHash, const String& message);
  void manageDisplayPower();
  void enterLightSleep();
  void wakeDisplay();
  void adjustDateField(int8_t amount);
  void clampDate();
  void commitDateTime();
  void resetSettings();
  void setWifi(bool enabled);
  bool allButtonsHeldAtBoot() const;

  void draw();
  void drawScreen(Screen screen);
  void drawStatusBar(const char* title);
  void drawFooter(const char* left, const char* middle, const char* right);
  void drawMain();
  void drawMainCard(uint8_t item, int32_t x, int32_t y, int32_t size);
  void drawApps();
  void drawSettings();
  void drawDateTime();
  void drawDisplaySound();
  void drawWifi();
  void drawBluetooth();
  void drawBluetoothScanDialog();
  void drawBluetoothSavedDialog();
  void drawBoot();
  void drawMainMenuSettings();
  void drawShortcuts();
  void drawAppsSettings();
  void drawHelp();
  void drawQuickSettings();
  void drawPlaceholder();
  void drawDebug();
  void drawSystemInfo();
  void drawPower();
  void drawPowerActions();
  void drawFactoryReset();
  void drawFileExplorer();
  void drawAiDeveloper();
  void drawAiApi();
  void drawLuaApp();
  void drawLevelRow(uint8_t row, const String& label, uint8_t step,
                    uint8_t stepCount, bool selected, uint16_t accent,
                    bool editing = false);
  void drawWifiIcon(int32_t x, int32_t y, uint8_t state);
  void drawBluetoothIcon(int32_t x, int32_t y, bool enabled);
  void drawBatteryIcon(int32_t x, int32_t y, int level, bool charging);
  int batteryLevel() const;
  bool batteryCharging() const;
  void refreshBatteryStatus() const;
  void drawRow(uint8_t row, const String& label, bool selected,
               const String& value = String(), bool editing = false);
  void drawText(int32_t x, int32_t y, const String& text, uint16_t color,
                uint8_t size = 1, uint16_t background = 0x1082);

  static void luaDisplayClear(void* context, int color);
  static void luaDisplayCircle(void* context, int x, int y, int radius,
                               int color);
  static void luaDisplayRect(void* context, int x, int y, int width,
                             int height, int color);
  static void luaDisplayLine(void* context, int x1, int y1, int x2, int y2,
                             int color);
  static void luaDisplayText(void* context, int x, int y, const char* text,
                             int color);
  static bool luaButtonPressed(void* context, const char* button);
  static void luaRgbSet(void* context, int index, int red, int green,
                        int blue);
  static bool luaImuAccel(void* context, float* x, float* y, float* z);
  static uint32_t luaTimeMillis(void* context);
};

// Shared OS singleton for future apps and system services.
extern FireOS* fireOs;

