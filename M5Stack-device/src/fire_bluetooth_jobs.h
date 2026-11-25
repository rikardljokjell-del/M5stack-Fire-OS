#pragma once
#include <Arduino.h>
#include <atomic>
#ifdef FIRE_OS_BLE
#include <NimBLEDevice.h>
#ifdef USING_NIMBLE_ARDUINO_HEADERS
#include "nimble/nimble/host/include/host/ble_gatt.h"
#include "nimble/nimble/host/include/host/ble_hs_mbuf.h"
#else
#include <host/ble_gatt.h>
#include <host/ble_hs_mbuf.h>
#endif
#include <esp_timer.h>

// One controller owner, same existing Lua jobs. NimBLE callbacks only publish
// bounded records/results; no Lua, SD, UI, credentials or pairing in callbacks.
class FireBluetoothJobs : public NimBLEScanCallbacks {
 public:
  struct Packet {uint64_t us=0;uint8_t address[6]={};uint8_t type=0,event=0,length=0,advLength=0;int8_t rssi=0;uint8_t bytes[62]={};};
  bool busy() const {return owner_!=0;}
  uint16_t owner() const {return owner_;}
  bool scan(uint16_t owner,uint32_t duration);
  bool pop(Packet& packet);
  bool pendingPackets() const {
    portENTER_CRITICAL(&mux_);const bool pending=count_!=0;portEXIT_CRITICAL(&mux_);return pending;
  }
  uint8_t queuedPackets() const {portENTER_CRITICAL(&mux_);const uint8_t value=count_;portEXIT_CRITICAL(&mux_);return value;}
  bool scanning() const {return scan_ && scan_->isScanning();}
  uint32_t dropped() const {return dropped_.load(std::memory_order_acquire);}
  bool advertise(uint16_t owner,const uint8_t* bytes,size_t length,uint32_t duration);
  bool gatt(uint16_t owner,const char* address,uint8_t type,const char* service,const char* characteristic,
            const uint8_t* bytes,size_t length,bool write);
  void service();
  bool finished() const {return done_;}
  bool succeeded() const {return ok_;}
  size_t result(uint8_t* bytes,size_t capacity) const;
  void cancel(uint16_t owner);
  void reset();
  void onResult(const NimBLEAdvertisedDevice* device) override;
 private:
  uint16_t owner_=0;
  NimBLEScan* scan_=nullptr;
  NimBLEClient* client_=nullptr; // NimBLEDevice owns/deletes on controller teardown
  NimBLEAdvertisementData oldAdv_,oldScan_;
  bool advertising_=false,wasAdvertising_=false,write_=false,done_=false,ok_=false;
  uint32_t deadline_=0;
  std::atomic<uint32_t> generation_{0};
  std::atomic<uint8_t> phase_{0};
  uint16_t start_=0,end_=0,value_=0,connection_=BLE_HS_CONN_HANDLE_NONE;
  NimBLEUUID service_,characteristic_;
  NimBLEAddress expected_;
  uint8_t payload_[128]={},result_[512]={};
  size_t payloadLength_=0,resultLength_=0;
  Packet packets_[16];uint8_t read_=0,writeIndex_=0,count_=0;
  std::atomic<bool> recording_{false};
  std::atomic<uint32_t> dropped_{0};
  mutable portMUX_TYPE mux_=portMUX_INITIALIZER_UNLOCKED;
  struct Lock {portMUX_TYPE& mux;explicit Lock(portMUX_TYPE& value):mux(value) {portENTER_CRITICAL(&mux);}~Lock() {portEXIT_CRITICAL(&mux);}};
  static int serviceCallback(uint16_t,const ble_gatt_error*,const ble_gatt_svc*,void*);
  static int characteristicCallback(uint16_t,const ble_gatt_error*,const ble_gatt_chr*,void*);
  static int readCallback(uint16_t,const ble_gatt_error*,ble_gatt_attr*,void*);
  static int writeCallback(uint16_t,const ble_gatt_error*,ble_gatt_attr*,void*);
  static std::atomic<FireBluetoothJobs*> callbackOwner_;
  bool current(uint16_t connection,void* generation) const;
};
#else
class FireBluetoothJobs {
 public:
  bool busy() const {return false;}
  uint16_t owner() const {return 0;}
  void service() {}
  void cancel(uint16_t) {}
  void reset() {}
};
#endif
