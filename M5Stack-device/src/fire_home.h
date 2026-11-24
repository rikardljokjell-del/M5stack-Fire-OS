#pragma once
#include <Arduino.h>
#include <M5GFX.h>
#include <Preferences.h>
#include <mqtt_client.h>
#include <atomic>
#include <freertos/queue.h>
#include <freertos/semphr.h>

// Native Home v1. No dependency on AI/backend classes or Lua permissions.
class FireHome {
 public:
  void begin();
  void service(bool wifiConnected, bool allowNetwork);
  void draw(M5Canvas& canvas);
  void button(uint8_t index);
  void settings() { settings_ = true; detail_ = false; focus_ = 0; }
  bool back();
  bool configure(const String& body, String& error);
  bool configured() const;
  String profileName() const { return profile_ ? "Camper" : "Home"; }
  const char* setupPage() const;
  bool takeSetupRequest() { bool result = setupRequested_; setupRequested_ = false; return result; }
  void setupHint(const String& password) { setupHint_ = "FIRE-Setup / " + password; }
 private:
  struct Profile {
    String site, device, localHost, remoteHost, localUser, localPassword;
    String remoteUser, remotePassword, ca;
  } profiles_[2];
  struct Card {
    String id, name, kind, unit, state = "unknown", mode = "unknown";
    uint8_t ops = 0;
    double value = 0, target = 0, minimum = 5, maximum = 35, step = .5;
    uint8_t modes = 0;
    bool hasValue = false, hasTarget = false;
    bool favorite = false;
  } cards_[12];
  uint8_t count_ = 0, focus_ = 0, profile_ = 0, routeMode_ = 0, layout_ = 0;
  bool settings_ = false, detail_ = false, confirm_ = false, favoritesOnly_ = false;
  bool editing_ = false;
  bool setupRequested_ = false;
  String setupHint_;
  String detailCardId_;
  uint8_t detailAction_ = 0;
  double editValue_ = 0;
  Preferences preferences_;
  bool preferencesReady_ = false;
  String epoch_, revision_, pendingRid_, status_ = "Ikke konfigurert";
  uint32_t lastSeq_ = 0, catalogAt_ = 0, stateAt_ = 0, catalogTtl_ = 0;
  uint32_t stateTtl_ = 0, pendingAt_ = 0;
  uint32_t pendingSeq_ = 0;
  uint32_t helloAt_ = 0;
  uint8_t helloAttempts_ = 0;
  bool remoteAllowed_ = false, catalogValid_ = false;
  std::atomic<bool> wanted_{false}, online_{false}, remote_{false}, helloNeeded_{false};
  std::atomic<uint32_t> generation_{0};
  SemaphoreHandle_t configMutex_ = nullptr;
  QueueHandle_t inbox_ = nullptr, outgoing_ = nullptr;
  struct Message { uint8_t kind; uint32_t length; char* body; uint32_t generation; bool remote; uint32_t connection; };
  std::atomic<uint32_t> connection_{0};
  uint32_t connectionGeneration_ = 0;
  struct Outgoing { char body[513]; uint32_t generation, connection; };
  char* assembly_ = nullptr;
  uint32_t assemblyLength_ = 0, assemblyExpected_ = 0;
  uint8_t assemblyKind_ = 0;
  String topicPrefix_;
  static void task(void* context);
  void run();
  static void event(void* context, esp_event_base_t, int32_t id, void* data);
  void handleEvent(esp_mqtt_event_handle_t event);
  bool catalog(const char* body);
  bool state(const char* body);
  void acknowledge(const char* body);
  bool current() const;
  bool stateFresh() const;
  bool sendCommand(const Card& card, const char* op, double value, bool number,
                   const char* text = nullptr);
  bool queue(const String& body);
  void persist();
  void invalidate();
  void reorder();
  uint8_t visible(uint8_t* indices) const;
  String favoriteKey(const String& id) const;
};
