#pragma once

#include <Arduino.h>
#include <SD.h>
#include <SPI.h>
#include <esp_ota_ops.h>
#include "fire_lua_runtime.h"
#include "fire_backend_client.h"
#include "fire_firmware_storage.h"
#include "fire_github_firmware.h"
#include "fire_lua_package_manager.h"
#include "fire_reverse_transport.h"
#include "fire_home.h"
#include "fire_ota.h"
#include "fire_setup_portal.h"

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
  bool saveBackendSetupFields(const String& host, const String& port,
                              const String& token, const String& deviceId);
  bool wifiSetupTokenValid(const String& token) const;
  bool aiApiSetupActive() const { return aiApiSetupActive_; }
  void finishBackendSetup() { stopWifiSetup(); }

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
    Firmware,
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
    Home,
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
  static constexpr uint8_t kSystemMainCount = 6;
  static constexpr uint8_t kMaxLuaApps = 32;
  static constexpr uint8_t kMainCount = kSystemMainCount + kMaxLuaApps;
  static constexpr uint8_t kSettingsCount = 17;
  static constexpr uint8_t kQuickCount = 9;
  static constexpr uint8_t kPowerCount = 6;
  static constexpr uint8_t kPowerActionCount = 4;
  static constexpr uint8_t kMaxBluetoothDevices = 32;
  static constexpr uint8_t kMaxBluetoothSavedDevices = 5;
  static constexpr uint8_t kDurationCount = 21;
  static constexpr uint8_t kDateFieldCount = 11;
  static constexpr uint8_t kBaseDoubleClickActionCount = 9;
  static constexpr uint8_t kDoubleClickActionCount =
      kBaseDoubleClickActionCount + kMaxLuaApps;
  static constexpr int16_t kCarouselDistance = 112;
  static constexpr uint32_t kLongPressMs = 650;
  static constexpr uint32_t kDoubleClickWindowMs = 350;
  static constexpr uint32_t kButtonDebounceMs = 18;

  Screen screen_ = Screen::Main;
  Screen previousScreen_ = Screen::Main;
  ButtonState buttons_[kButtonCount];
  DateTimeService dateTime_;

  uint8_t mainIndex_ = 0;
  bool mainVisible_[kMainCount] = {true, true, true, true, true, true};
  FireHome homeApp_;
  FireOta ota_;
  uint32_t otaRebootAt_ = 0;
  FireSetupPortal setupPortal_;
  bool portalApplying_ = false, portalReconnect_ = false;
  uint32_t portalCloseAt_ = 0, wifiBeginAt_ = 0;
  uint32_t wifiSetupStartedAt_ = 0;
  bool luaMenuSelected_[kMaxLuaApps] = {};
  bool luaMenuPicker_ = false;
  uint8_t luaMenuSelection_ = 0;
  uint8_t luaMenuOffset_ = 0;
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
  String doubleClickLuaAppId_[kButtonCount];
  uint8_t placeholderIndex_ = 0;
  bool safeMode_ = false;
  bool factoryResetArmed_ = false;
  bool wifiEnabled_ = false;
  uint8_t wifiMode_ = 0;  // 0=Auto, 1=On, 2=Off
  uint8_t backendMode_ = 0;  // 0=Auto, 1=On, 2=Off
  bool wifiTimeSync_ = false;
  bool backendBootPending_ = false;
  bool backendBootAttempted_ = false;
  uint32_t backendBootAttemptedAt_ = 0;
  bool backendBootSyncWaiting_ = false;
  bool backendBootJobsReceived_ = false;
  uint32_t backendBootSyncStartedAt_ = 0;
  uint8_t buildJobsRetryCount_ = 0;
  uint32_t buildJobsRequestAt_ = 0;
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
  static constexpr uint8_t kMaxBackendApps = 32;
  static constexpr uint8_t kMaxBackendVersions = 8;
  static constexpr uint8_t kMaxManagerItems = 40;
  static constexpr uint8_t kMaxFirmwareFiles = 24;
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
  String firmwarePaths_[kMaxFirmwareFiles];
  String firmwareNames_[kMaxFirmwareFiles];
  uint32_t firmwareSizes_[kMaxFirmwareFiles] = {};
  uint8_t firmwareCount_ = 0;
  uint8_t firmwareSelection_ = 0;
  uint8_t firmwareOffset_ = 0;
  bool firmwareScanPending_ = false;
  bool firmwareInstallConfirm_ = false;
  bool firmwareInstallPending_ = false;
  bool firmwareGithubDialog_ = false;
  bool firmwareSdDialog_ = false;
  bool firmwareGithubOverwriteConfirm_ = false;
  bool firmwareGithubActionMenu_ = false, firmwareInstallFromGithub_ = false;
  uint8_t firmwareGithubActionIndex_ = 0;
  FireRelease firmwareGithubRelease_;
  String firmwareGithubCatalog_, firmwarePendingSdPath_;
  enum class FirmwareAction : uint8_t { None, Manifest, SaveSd, InstallGithub, InstallSd };
  FirmwareAction firmwareAction_ = FirmwareAction::None;
  bool firmwareNetworkPaused_ = false, firmwareSaveOverwrite_ = false;
  uint32_t firmwareQuietAt_ = 0;
  uint8_t firmwareGithubPendingIndex_ = 0;
  uint8_t firmwareGithubSelection_ = 0;
  uint8_t firmwareGithubOffset_ = 0;
  bool firmwareBootGuardActive_ = false;
  uint32_t firmwareBootGuardStarted_ = 0;
  String firmwareMessage_;
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
  uint8_t appManagerActionCount_ = 0;
  uint8_t appManagerActionCodes_[6] = {};
  String appManagerActionLabels_[6];
  bool appManagerDeleteConfirm_ = false;
  uint8_t appManagerDeleteMode_ = 0;  // 1=local, 2=backend
  String appManagerDeleteId_;
  String appManagerDeleteProjectId_;
  String appManagerDeleteAppId_;
  String appManagerDeletePackageId_;
  String appManagerDeleteName_;
  uint8_t appManagerDeleteScope_ = 0;  // 1=version, 2=all
  bool appManagerDeleteWaiting_ = false;

  struct BackendAppInfo {
    String appId;
    String projectId;
    String name;
    String latestPackageId;
    String latestVersion;
    String deleteReason;
    bool downloadable = false;
    bool canDelete = false;
    uint8_t versionCount = 0;
  };
  BackendAppInfo backendApps_[kMaxBackendApps];
  uint8_t backendAppCount_ = 0;
  bool backendCatalogRequested_ = false;
  bool backendCatalogLoading_ = false;
  int32_t backendCatalogNextOffset_ = 0;
  String backendCatalogStatus_;

  struct ManagerItem {
    uint8_t kind = 0;  // 0=external, 1=Lua, 2=backend-only
    bool local = false;
    bool backend = false;
    bool downloadable = false;
    bool canDeleteBackend = false;
    String appId;
    String projectId;
    String name;
    String localPath;
    String localVersion;
    String localPackageId;
    String packageId;
    String version;
    String backendBlockReason;
    uint8_t versionCount = 0;
  };
  ManagerItem managerItems_[kMaxManagerItems];
  uint8_t managerItemCount_ = 0;
  uint8_t managerSelection_ = 0;
  uint8_t managerOffset_ = 0;
  String managerStatus_;

  bool appManagerVersionDialog_ = false;
  uint8_t appManagerVersionSelection_ = 0;
  uint8_t appManagerVersionOffset_ = 0;
  String appManagerVersionProjectId_;
  String appManagerVersionAppId_;
  String appManagerVersionPackageIds_[kMaxBackendVersions];
  String appManagerVersionLabels_[kMaxBackendVersions];
  String appManagerVersionReasons_[kMaxBackendVersions];
  bool appManagerVersionDownloadable_[kMaxBackendVersions] = {};
  uint8_t appManagerVersionCount_ = 0;
  String luaAppPaths_[kMaxLuaApps];
  String luaAppNames_[kMaxLuaApps];
  String luaAppIds_[kMaxLuaApps];
  String luaAppDisplayNames_[kMaxLuaApps];
  String luaAppVersions_[kMaxLuaApps];
  String luaAppChecksums_[kMaxLuaApps];
  String luaAppPackageIds_[kMaxLuaApps];
  uint8_t luaAppCount_ = 0;
  struct LuaScanItem {
    String path, name, id, displayName, version, checksum, packageId;
  };
  LuaScanItem luaScanItems_[kMaxLuaApps];
  enum class LuaScanPhase : uint8_t {
    Idle, CheckStorage, RootExists, OpenRoot, Next, SourceExists, OpenManifest, Read, Parse, Finish
  };
  LuaScanPhase luaScanPhase_ = LuaScanPhase::Idle;
  File luaScanDirectory_, luaScanManifest_;
  String luaScanFolder_, luaScanBody_;
  uint32_t luaScanRevision_ = 0, luaScanActiveRevision_ = 0;
  uint32_t luaScanStartedAt_ = 0;
  size_t luaScanExpected_ = 0;
  uint8_t luaScanCount_ = 0;
  bool luaScanPending_ = false, luaScanComplete_ = true;
  bool luaCacheValid_ = false, luaCacheComplete_ = false;
  bool appInventoryPending_ = false;
  uint32_t appInventoryDemandAt_ = 0, backendDrainStartedAt_ = 0;
  bool fileExplorerScanPending_ = false;

  enum class LuaJobKind : uint8_t {
    None,
    I2cScan,
    I2cRead,
    I2cWrite,
    UartRead,
    UartWrite,
    SpiTransfer,
    SdList,
    SdRead,
    SdWrite,
    SdRemove,
    PowerSleep,
    SpeakerTone,
    SpeakerPlay
  };
  struct LuaHardwareJob {
    uint16_t id = 0;
    LuaJobKind kind = LuaJobKind::None;
    uint8_t state = 0;  // 0=pending, 1=ready, 2=failed, 3=cancelled
    uint32_t startedAt = 0;
    uint32_t lastProgressAt = 0;
    uint32_t timeoutMs = 3000;
    uint8_t bus = 0;
    uint8_t address = 0;
    int16_t reg = -1;
    uint16_t count = 0;
    uint16_t step = 0;
    uint8_t payload[512] = {};
    uint16_t payloadCount = 0;
    uint8_t bytes[512] = {};
    uint16_t byteCount = 0;
    uint16_t addresses[126] = {};
    uint16_t addressCount = 0;
    uint32_t written = 0;
    String text;
    String errorCode;
    String path;
    uint32_t offset = 0;
    bool append = false;
    uint16_t entryCount = 0;
    String entryNames[32];
    uint32_t entrySizes[32] = {};
    bool entryDirectories[32] = {};
    uint32_t frequency = 0;
    uint32_t durationMs = 0;
    uint8_t appVolume = 0;
    uint32_t mediaSize = 0;
    uint32_t mediaRead = 0;
    bool started = false;
  };
  static constexpr uint8_t kMaxLuaJobs = 4;
  LuaHardwareJob luaJobs_[kMaxLuaJobs];
  uint16_t nextLuaJobId_ = 1;
  bool luaGpioClaimed_[40] = {};
  uint8_t luaGpioMode_[40] = {};
  int8_t luaPwmPin_ = -1;
  uint8_t luaPwmChannel_ = 7;
  bool luaI2cStarted_ = false;
  bool luaUartOpen_ = false;
  int luaUartRxPin_ = -1;
  int luaUartTxPin_ = -1;
  int8_t luaDacPin_ = -1;
  SPIClass* luaSpi_ = nullptr;
  int luaSpiBus_ = -1;
  uint32_t luaSpiFrequency_ = 1000000;
  uint8_t luaSpiMode_ = 0;
  static constexpr uint8_t kLuaSpeakerChannel = 6;
  static constexpr size_t kMaxLuaWavBytes = 512 * 1024;
  File luaSpeakerFile_;
  uint8_t* luaSpeakerBuffer_ = nullptr;
  size_t luaSpeakerBufferSize_ = 0;
  volatile bool luaSpeakerBufferReleased_ = false;
  uint16_t luaSpeakerJobId_ = 0;
  bool luaSpeakerPlaying_ = false;

  FireLuaRuntime* luaRuntime_ = nullptr;
  bool luaRuntimeReady_ = false;
  bool luaAppActive_ = false;
  String luaAppPath_;
  String luaAppName_;
  String luaAppId_;
  String luaAppVersion_;
  String luaSourceHash_;
  String luaPackageId_;
  String luaAppError_;
  String luaErrorAppId_;
  String luaErrorAppName_;
  String luaErrorAppVersion_;
  String luaErrorPackageId_;
  String luaErrorSourceHash_;
  String luaErrorRunId_;
  String luaErrorCode_;
  String luaErrorDiagnostics_;
  String luaRepairId_;
  String luaRepairProposalId_;
  String luaRepairProjectId_;
  String luaRepairReadyPackageId_;
  String luaRepairReadyVersion_;
  String luaRepairStatus_;
  String luaRepairPhase_;
  String luaRepairMessage_;
  uint8_t luaRepairProgress_ = 0;
  uint8_t luaErrorAction_ = 0;  // 0=Fix error, 1=Run fixed app
  bool luaRepairRequested_ = false;
  bool luaRepairPrepareSent_ = false;
  bool luaRepairBuildConfirmed_ = false;
  bool luaRepairConfirmPending_ = false;
  bool luaRepairStatusQueryPending_ = false;
  bool luaRepairRunAfterInstall_ = false;
  bool luaRepairCancelPending_ = false;
  bool repairCancelSupported_ = false;
  uint32_t luaRepairLastAttemptAt_ = 0;
  uint32_t luaRepairConfirmLastAttemptAt_ = 0;
  uint32_t luaMaxRuntimeMs_ = FireLuaRuntime::kDefaultRuntimeMs;
  uint32_t luaLastFrameAt_ = 0;
  uint8_t luaRgbValues_[10][3] = {};
  bool luaRgbDirty_ = false;
  uint32_t luaRgbDirtyAt_ = 0;
  uint32_t luaRgbLastFlushAt_ = 0;
  FireBackendClient* backendClient_ = nullptr;
  FireFirmwareStorage* firmwareStorage_ = nullptr;
  FireGithubFirmwareManager* githubFirmware_ = nullptr;
  FireLuaPackageManager* packageManager_ = nullptr;
  FireReverseTransport reverseTransport_;
  String backendStatus_;
  String aiTurnId_;
  String aiTranscriptText_;
  uint8_t aiConversationMode_ = 0;  // 0=develop, 1=chat
  bool aiVoiceTestMode_ = false;    // Local microphone/WAV playback diagnostic
  bool aiVoiceTestPlaybackActive_ = false;
  bool aiVoiceTestRadioSuspended_ = false;
  bool aiVoiceTestWifiWasEnabled_ = false;
  String aiBasePackageId_;
  bool aiProjectPickerActive_ = false;
  uint8_t aiProjectSelection_ = 0;
  uint8_t aiProjectOffset_ = 0;
  String aiProjectId_;
  String aiProjectName_;
  String aiBuildId_;
  bool backgroundBuildsSupported_ = false;
  bool failedBuildResumeSupported_ = false;
  bool backgroundBuildActive_ = false;
  bool buildJobsRequested_ = false;
  bool aiResumeAvailable_ = false;
  bool aiBuildResumePending_ = false;
  bool aiBuildRetryPending_ = false;
  bool aiBuildCanResume_ = false;
  bool aiBuildCanRetry_ = false;
  int32_t aiBuildResumeCount_ = -1;
  uint8_t buildJobCount_ = 0;
  String buildJobIds_[4];
  String buildJobNames_[4];
  String buildJobStatuses_[4];
  String buildJobErrors_[4];
  String buildJobErrorCodes_[4];
  String buildJobDiagnostics_[4];
  bool buildJobCanResume_[4] = {};
  bool buildJobCanRetry_[4] = {};
  String aiBuildErrorCode_;
  String aiBuildErrorStatus_;
  String aiBuildDiagnosticMessage_;
  bool buildNoticeActive_ = false;
  String buildNoticeId_;
  String buildNoticeAckedId_;
  String buildNoticePendingId_;
  String buildNoticePendingAction_;
  String buildNoticePendingEvent_;
  uint32_t buildNoticeLastSendAt_ = 0;
  uint32_t maxLoopUs_ = 0;
  uint32_t maxLoopGapUs_ = 0, diagnosticsAt_ = 0;
  int64_t lastLoopStartedUs_ = 0;
  uint32_t minLargestInternal_ = UINT32_MAX;
  String buildNoticeName_;
  String buildNoticeMessage_ = "Appen er klar";
  uint8_t buildProgress_ = 0;
  String buildPhase_;
  String buildStatusMessage_;
  String aiProposalId_;
  String aiPackageId_;
  String aiInstallId_;
  String luaRunId_;
  bool luaHealthySent_ = false;
  String aiAssistantText_;
  String aiWorkflowText_;
  static constexpr uint32_t kAiAudioSampleRate = 16000;
  static constexpr uint32_t kAiAudioSeconds = 15;
  static constexpr size_t kAiAudioSamples =
      kAiAudioSampleRate * kAiAudioSeconds;
  static constexpr size_t kAiAudioWavBytes = 44 + kAiAudioSamples * 2;
  uint8_t* aiAudioBuffer_ = nullptr;
  volatile bool aiAudioCaptureFinished_ = false;
  volatile bool aiAudioStopSent_ = false;
  volatile bool aiAudioUploadFinished_ = false;
  volatile bool aiAudioUploadOk_ = false;
  bool aiAudioUploadStarted_ = false;
  bool aiAudioCaptureActive_ = false;
  size_t aiAudioCapturedSamples_ = 0;
  size_t aiAudioWavLength_ = 0;
  uint32_t aiAudioCaptureStartedAt_ = 0;
  uint32_t aiAudioCaptureElapsedMs_ = 0;
  uint32_t aiAudioCaptureRms_ = 0;
  int32_t aiAudioCapturePeak_ = 0;
  String aiAudioError_;
  uint8_t* aiAudioOutputBuffer_ = nullptr;
  size_t aiAudioOutputLength_ = 0;
  bool aiAudioOutputActive_ = false;
  String aiAudioOutputId_;
  String aiAudioOutputTurnId_;
  String aiLastAudioId_;
  String aiLastAudioTurnId_;
  bool aiAudioDownloadPending_ = false;
  String aiAudioDownloadId_;
  String aiAudioDownloadTurnId_;
  String aiAudioDownloadUrl_;
  String aiAudioDownloadHash_;
  uint32_t aiAudioDownloadSize_ = 0;
  bool aiAudioDownloadStarted_ = false;
  bool aiConversationCancelPending_ = false;

  static constexpr uint32_t kDebugMicSampleRate = 16000;
  static constexpr uint32_t kDebugMicSeconds = 3;
  static constexpr size_t kDebugMicSamples =
      kDebugMicSampleRate * kDebugMicSeconds;
  int16_t* debugMicBuffer_ = nullptr;
  size_t debugMicSamples_ = 0;
  uint32_t debugMicStartedAt_ = 0;
  bool debugMicRecording_ = false;
  bool debugMicPlaying_ = false;
  String debugMicStatus_ = "Press B to record";
  uint8_t debugRgbIndex_ = 0;
  uint8_t debugRgbBrightness_ = 120;

  // One bounded diagnostic is retained across a temporary backend outage.
  // It is only sent for a package identity known to belong to this device.
  String pendingDiagnosticAppId_;
  String pendingDiagnosticPackageId_;
  String pendingDiagnosticErrorCode_;
  String pendingDiagnosticMessage_;
  String pendingDiagnosticJson_;

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
  uint32_t backendServerTime_ = 0;
  uint32_t backendServerSeenAt_ = 0;
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
  void scanFirmwareFiles();
  bool installFirmwareFile(const String& path);
  bool firmwareBusy() const;
  bool queueFirmwareAction(FirmwareAction action, bool overwrite = false);
  void serviceFirmwareAction();
  bool handlePendingFirmwareBoot();
  void updateFirmwareBootGuard();
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
  void invalidateLuaApps();
  void serviceLuaAppScan();
  void publishLuaAppScan();
  void syncLuaAppSelections();
  void saveLuaAppSelections();
  uint8_t shortcutActionCount() const;
  uint8_t shortcutActionAtPosition(uint8_t position) const;
  uint8_t shortcutPositionForAction(uint8_t action) const;
  String shortcutActionLabel(uint8_t action) const;
  void serviceLuaHardwareJobs();
  void releaseLuaHardware();
  LuaHardwareJob* findLuaJob(uint16_t id);
  const LuaHardwareJob* findLuaJob(uint16_t id) const;
  uint16_t createLuaJob(LuaJobKind kind, const char** error);
  static void setLuaError(const char** error, const char* value);
  bool luaI2cAllowed(uint8_t bus, uint8_t address, bool write) const;
  bool luaGpioAllowed(int pin, bool write) const;
  bool luaPwmAllowed(int pin) const;
  bool luaPrivateAppPath(const char* relative, String& result,
                         const char** error) const;
  static bool luaGpioModeCallback(void*, int, const char*, const char**);
  static bool luaGpioReadCallback(void*, int, int*, const char**);
  static bool luaGpioWriteCallback(void*, int, int, const char**);
  static bool luaGpioReleaseCallback(void*, int, const char**);
  static bool luaPwmConfigureCallback(void*, int, int, int, const char**);
  static bool luaPwmWriteCallback(void*, int, int, const char**);
  static bool luaPwmStopCallback(void*, int, const char**);
  static bool luaUartOpenCallback(void*, int, int, int, int, const char*, const char**);
  static uint16_t luaUartReadCallback(void*, int, int, const char**);
  static uint16_t luaUartWriteCallback(void*, int, const char*, size_t, const char**);
  static bool luaUartCloseCallback(void*, int, const char**);
  static uint16_t luaI2cScanCallback(void*, int, const char**);
  static uint16_t luaI2cReadCallback(void*, int, int, int, int, const char**);
  static uint16_t luaI2cWriteCallback(void*, int, int, const uint8_t*, size_t, const char**);
  static bool luaAdcReadCallback(void*, int, int*, const char**);
  static bool luaDacWriteCallback(void*, int, int, const char**);
  static bool luaDacStopCallback(void*, int, const char**);
  static bool luaSpiOpenCallback(void*, int, int, int, int, int, int, int,
                                 const char**);
  static uint16_t luaSpiTransferCallback(void*, int, const uint8_t*, size_t,
                                         const char**);
  static bool luaSpiCloseCallback(void*, int, const char**);
  static uint16_t luaSdListCallback(void*, const char*, const char**);
  static uint16_t luaSdReadCallback(void*, const char*, uint32_t, uint16_t,
                                    const char**);
  static uint16_t luaSdWriteCallback(void*, const char*, const char*, size_t,
                                     bool, const char**);
  static uint16_t luaSdRemoveCallback(void*, const char*, const char**);
  static bool luaSdMkdirCallback(void*, const char*, const char**);
  static bool luaPowerStatusCallback(void*, float*, float*, bool*, bool*);
  static bool luaPowerBrightnessCallback(void*, int, const char**);
  static uint16_t luaPowerSleepCallback(void*, uint32_t, const char**);
  static bool luaRtcNowCallback(void*, uint32_t*, int*, int*, int*, int*, int*,
                                int*, const char**);
  static bool luaRtcSetCallback(void*, uint32_t, const char**);
  static uint16_t luaSpeakerToneCallback(void*, int, int, int, const char**);
  static uint16_t luaSpeakerPlayCallback(void*, const char*, int, const char**);
  static bool luaSpeakerStopCallback(void*, const char**);
  static void luaSpeakerBufferReleaseCallback(void*, const void*, uint8_t);
  bool validateLuaWav(const uint8_t*, size_t, uint32_t&, uint32_t&) const;
  void releaseLuaSpeakerBufferIfReady();
  static bool luaJobPollCallback(void*, uint16_t, FireLuaRuntime::JobSnapshot*);
  static bool luaJobResultCallback(void*, uint16_t, FireLuaRuntime::JobSnapshot*);
  static bool luaJobCloseCallback(void*, uint16_t);
  static bool luaJobCancelCallback(void*, uint16_t);
  void rebuildAppManagerItems();
  int8_t managerItemForAppId(const String& appId) const;
  void sendAppInventory();
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
  void handleFirmwareButton(uint8_t index);
  void handleAppsSettingsButton(uint8_t index);
  void updateAppManagerBackend();
  void parseBackendAppCatalog(const String& message);
  void parseBackendAppVersions(const String& message);
  void prepareAppManagerActions();
  void requestSelectedAppVersions();
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
  void cancelConversationTurn(const String& reason, bool startNew = false);
  bool stopAiAudioOutput();
  bool startAiRecording();
  void suspendVoiceTestRadio();
  void restoreVoiceTestRadio();
  void finishAiRecording();
  void updateAiAudio();
  void updateAiAudioOutput();
  void failAiAudioPlayback(const String& audioId, const String& turnId,
                           const String& errorCode, const String& message,
                           const char* phase, bool releaseBuffer = true);
  void handleAiApiButton(uint8_t index);
  bool startLuaApp(const String& path, const String& name = String(),
                   const String& launchPackageId = String());
  void stopLuaApp(const String& reason = String());
  void updateLuaApp();
  void handleLuaErrorButton(uint8_t index);
  void requestLuaRepair();
  void requestLuaRepairStatus();
  void serviceLuaRepair();
  void cancelLuaRepair();
  void handleLuaRepairStatus(const String& message);
  void startLuaRepairRun();
  void writeLuaErrorSnapshot(const String& errorCode, const String& message,
                             const String& diagnostics);
  void flushLuaRgb();
  void queueLuaDiagnostic(const String& appId, const String& packageId,
                          const String& errorCode, const String& message,
                          const String& diagnostics = String());
  void flushLuaDiagnostic();
  String luaDiagnosticsJson(const char* phase) const;
  String audioDiagnosticsJson(const char* phase) const;
  void updateBackend();
  void applyBackendMode();
  void handleBackendMessage(const String& message);
  void handleBackgroundBuildMessage(const String& message);
  void requestBackgroundBuildJobs();
  static void backendMessage(void* context, const String& message);
  static void backendState(void* context, bool connected, const String& status);
  static void packageStatus(void* context, const String& status);
  static void packageResult(void* context, bool ok, const String& packageId,
                            const String& archiveHash, const String& message);
  static void firmwareStatus(void* context, const String& status);
  static void firmwareResult(void* context, const String& transferId,
                             const String& firmwareId, bool ok,
                             const String& sha256, const String& errorCode,
                             const String& message);
  static void githubFirmwareStatus(void* context, const String& status);
  static void githubFirmwareResult(void* context, bool manifest, bool ok,
                                   const String& message);
  void manageDisplayPower();
  void enterLightSleep();
  void wakeDisplay();
  void adjustDateField(int8_t amount);
  void clampDate();
  void commitDateTime();
  void resetSettings();
  void setWifi(bool enabled);
  bool allButtonsHeldAtBoot() const;
  bool backendCommandUnexpired(uint32_t expiresAt) const;

  void draw();
  void drawScreen(Screen screen);
  void drawStatusBar(const char* title);
  void drawFooter(const char* left, const char* middle, const char* right);
  void drawMain();
  void drawBuildNoticeOverlay();
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
  void drawFirmware();
  void drawGithubFirmwareDialog();
  void drawSdFirmwareDialog();
  void drawMainMenuSettings();
  void drawShortcuts();
  void drawAppsSettings();
  void drawAppsSettingsBackend();
  void drawAppManagerVersions();
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
  void updateDebugTests();
  void startDebugMicTest();
  void stopDebugMicTest();
  void releaseDebugTestAudio();
  void cleanupDebugTests();
  void drawLevelRow(uint8_t row, const String& label, uint8_t step,
                    uint8_t stepCount, bool selected, uint16_t accent,
                    bool editing = false);
  void drawWifiIcon(int32_t x, int32_t y, uint8_t state);
  void drawBackendIcon(int32_t x, int32_t y, uint8_t state);
  void drawBluetoothIcon(int32_t x, int32_t y, uint8_t state);
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
  static void luaDisplayFillRect(void* context, int x, int y, int width,
                                 int height, int color);
  static void luaDisplayFillCircle(void* context, int x, int y, int radius,
                                   int color);
  static void luaDisplayPixel(void* context, int x, int y, int color);
  static void luaDisplayGrid(void* context, int x, int y, int cellWidth,
                             int cellHeight, int columns, int rows,
                             const uint8_t* cells, size_t cellCount,
                             const uint16_t* palette, size_t paletteCount);
  static bool luaDisplayTextStyle(void*,int,int,const char*,size_t,int,const char*,int,int);
  static bool luaDisplayMeasureText(void*,const char*,size_t,const char*,int*,int*);
  static bool luaDisplayAsset(void*,int,int,const char*,int,int,bool,bool);
  static void luaDisplayRoundRect(void*,int,int,int,int,int,int,bool);
  static void luaDisplayTriangle(void*,int,int,int,int,int,int,int,bool);
  static void luaDisplayPolyline(void*,const int16_t*,size_t,int,bool,bool);
  static void luaDisplayGradient(void*,int,int,int,int,int,int,bool);
  static void luaDisplayArc(void*,int,int,int,int,int,int,int);
  static bool luaButtonPressed(void* context, const char* button);
  static void luaRgbSet(void* context, int index, int red, int green,
                        int blue);
  static bool luaImuAccel(void* context, float* x, float* y, float* z);
  static bool luaImuGyro(void* context, float* x, float* y, float* z);
  static bool luaImuTemperature(void* context, float* value);
  static uint32_t luaTimeMillis(void* context);
};

// Shared OS singleton for future apps and system services.
extern FireOS* fireOs;

