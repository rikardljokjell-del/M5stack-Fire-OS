#include "fire_bluetooth_jobs.h"
#ifdef FIRE_OS_BLE
std::atomic<FireBluetoothJobs*> FireBluetoothJobs::callbackOwner_{nullptr};

bool FireBluetoothJobs::scan(uint16_t owner,uint32_t duration) {
  if (owner_ || !owner || !duration) return false;
  scan_=NimBLEDevice::getScan();if (!scan_ || scan_->isScanning()) return false;
  {Lock lock(mux_);owner_=owner;read_=writeIndex_=count_=0;dropped_=0;done_=false;++generation_;}
  scan_->clearResults();scan_->setScanCallbacks(this,true);scan_->setMaxResults(0);
  recording_.store(true,std::memory_order_release);
  if (!scan_->start(duration)) {cancel(owner);return false;}
  return true;
}
void FireBluetoothJobs::onResult(const NimBLEAdvertisedDevice* device) {
  if (!recording_ || !device) return;
  const uint32_t generation=generation_.load(std::memory_order_acquire);
  const auto& payload=device->getPayload();
  Packet packet;packet.us=static_cast<uint64_t>(esp_timer_get_time());
  memcpy(packet.address,device->getAddress().getVal(),6);packet.type=device->getAddressType();
  packet.rssi=device->getRSSI();packet.event=device->getAdvType();
  const size_t advLength=device->getAdvLength();
  if (advLength<=payload.size()) packet.advLength=advLength;
  if (payload.size()<=sizeof(packet.bytes)) {packet.length=payload.size();memcpy(packet.bytes,payload.data(),payload.size());}
  portENTER_CRITICAL(&mux_);
  if (recording_ && generation==generation_.load(std::memory_order_acquire)) {
    if (payload.size()>sizeof(packet.bytes) || advLength>payload.size() || count_==16) {if (dropped_!=UINT32_MAX) ++dropped_;}
    else {packets_[writeIndex_]=packet;writeIndex_=(writeIndex_+1)%16;++count_;}
  }
  portEXIT_CRITICAL(&mux_);
}
bool FireBluetoothJobs::pop(Packet& packet) {
  portENTER_CRITICAL(&mux_);const bool ready=count_>0;
  if (ready) {packet=packets_[read_];read_=(read_+1)%16;--count_;}
  portEXIT_CRITICAL(&mux_);return ready;
}
bool FireBluetoothJobs::advertise(uint16_t owner,const uint8_t* bytes,size_t length,uint32_t duration) {
  if (owner_ || !owner || !bytes || !length || length>31) return false;
  auto* advertising=NimBLEDevice::getAdvertising();if (!advertising) return false;
  oldAdv_=advertising->getAdvertisementData();oldScan_=advertising->getScanData();wasAdvertising_=advertising->isAdvertising();
  advertising->stop();
  NimBLEAdvertisementData data,empty;
  if (!data.addData(bytes,length) || !advertising->setAdvertisementData(data) || !advertising->setScanResponseData(empty) || !advertising->start(duration)) {
    advertising->setAdvertisementData(oldAdv_);advertising->setScanResponseData(oldScan_);
    if (wasAdvertising_) advertising->start();
    return false;
  }
  owner_=owner;advertising_=true;done_=false;ok_=false;deadline_=duration?millis()+duration:0;
  return true;
}
bool FireBluetoothJobs::gatt(uint16_t owner,const char* address,uint8_t type,const char* service,const char* characteristic,
    const uint8_t* bytes,size_t length,bool write) {
  if (owner_ || !owner || !address || strlen(address)!=17 || length>sizeof(payload_)) return false;
  if (!client_) client_=NimBLEDevice::createClient();
  if (!client_ || client_->isConnected()) return false;
  service_=NimBLEUUID(service);characteristic_=NimBLEUUID(characteristic);
  if (service_.bitSize()==0 || characteristic_.bitSize()==0) return false;
  {Lock lock(mux_);owner_=owner;write_=write;done_=false;ok_=false;start_=end_=value_=0;resultLength_=0;++generation_;}
  payloadLength_=length;if (length) memcpy(payload_,bytes,length);
  callbackOwner_=this;phase_=1;client_->setConnectTimeout(2000);client_->setConnectRetries(0);
  expected_=NimBLEAddress(std::string(address),type);
  if (!client_->connect(expected_,true,true,false)) {cancel(owner);return false;}
  return true;
}
bool FireBluetoothJobs::current(uint16_t connection,void* generation) const {
  return connection==connection_ && reinterpret_cast<uintptr_t>(generation)==generation_.load(std::memory_order_acquire);
}
int FireBluetoothJobs::serviceCallback(uint16_t connection,const ble_gatt_error* error,const ble_gatt_svc* service,void* generation) {
  auto* self=callbackOwner_.load();if (!self) return 0;Lock lock(self->mux_);
  if (!self->current(connection,generation)) return 0;
  if (!error->status && service) {self->start_=service->start_handle;self->end_=service->end_handle;}
  else self->phase_.store(error->status==BLE_HS_EDONE && self->start_?3:9,std::memory_order_release);
  return 0;
}
int FireBluetoothJobs::characteristicCallback(uint16_t connection,const ble_gatt_error* error,const ble_gatt_chr* characteristic,void* generation) {
  auto* self=callbackOwner_.load();if (!self) return 0;Lock lock(self->mux_);
  if (!self->current(connection,generation)) return 0;
  if (!error->status && characteristic) self->value_=characteristic->val_handle;
  else self->phase_.store(error->status==BLE_HS_EDONE && self->value_?5:9,std::memory_order_release);
  return 0;
}
int FireBluetoothJobs::readCallback(uint16_t connection,const ble_gatt_error* error,ble_gatt_attr* attribute,void* generation) {
  auto* self=callbackOwner_.load();if (!self) return 0;Lock lock(self->mux_);
  if (!self->current(connection,generation)) return 0;
  if (!error->status && attribute) {
    const size_t length=OS_MBUF_PKTLEN(attribute->om);
    if (length>sizeof(self->result_)-self->resultLength_ || os_mbuf_copydata(attribute->om,0,length,self->result_+self->resultLength_)) {
      self->phase_.store(9,std::memory_order_release);return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    }
    self->resultLength_+=length;return 0;
  }
  self->phase_.store(error->status==0 || error->status==BLE_HS_EDONE?8:9,std::memory_order_release);return 0;
}
int FireBluetoothJobs::writeCallback(uint16_t connection,const ble_gatt_error* error,ble_gatt_attr*,void* generation) {
  auto* self=callbackOwner_.load();if (!self) return 0;Lock lock(self->mux_);
  if (self->current(connection,generation)) self->phase_.store(!error->status?8:9,std::memory_order_release);
  return 0;
}
void FireBluetoothJobs::service() {
  if (!owner_ || done_) return;
  if (scan_) {if (!scan_->isScanning()) {recording_=false;done_=true;ok_=true;}return;}
  if (advertising_) {if (deadline_ && static_cast<int32_t>(millis()-deadline_)>=0) {done_=true;ok_=true;}return;}
  if (!client_) return;
  const uint8_t phase=phase_.load(std::memory_order_acquire);
  void* context=reinterpret_cast<void*>(static_cast<uintptr_t>(generation_.load()));
  if (phase==1 && client_->isConnected()) {
    if (client_->getConnInfo().getAddress()!=expected_) {phase_=9;return;}
    const uint16_t connection=client_->getConnHandle();
    {Lock lock(mux_);connection_=connection;phase_=2;}
    if (ble_gattc_disc_svc_by_uuid(connection_,service_.getBase(),serviceCallback,context)) phase_=9;
  } else if (phase==3) {
    phase_=4;if (ble_gattc_disc_chrs_by_uuid(connection_,start_,end_,characteristic_.getBase(),characteristicCallback,context)) phase_=9;
  } else if (phase==5) {
    phase_=6;int status=0;
    if (write_) {
      os_mbuf* buffer=ble_hs_mbuf_from_flat(payload_,payloadLength_);
      status=buffer?ble_gattc_write_long(connection_,value_,0,buffer,writeCallback,context):BLE_HS_ENOMEM;
    } else status=ble_gattc_read_long(connection_,value_,0,readCallback,context);
    if (status) phase_=9;
  } else if (phase==8 || phase==9) {ok_=phase==8;done_=true;client_->disconnect();}
}
size_t FireBluetoothJobs::result(uint8_t* bytes,size_t capacity) const {
  const size_t length=min<size_t>(resultLength_,capacity);if (bytes && length) memcpy(bytes,result_,length);return length;
}
void FireBluetoothJobs::cancel(uint16_t owner) {
  if (!owner || owner_!=owner) return;
  {Lock lock(mux_);recording_=false;++generation_;}
  if (scan_) {scan_->stop();scan_->setScanCallbacks(nullptr,false);scan_->setMaxResults(40);scan_->clearResults();scan_=nullptr;}
  if (advertising_) {
    auto* advertising=NimBLEDevice::getAdvertising();advertising->stop();
    advertising->setAdvertisementData(oldAdv_);advertising->setScanResponseData(oldScan_);
    if (wasAdvertising_) advertising->start();
    advertising_=false;
  }
  if (client_) {client_->cancelConnect();client_->disconnect();}
  owner_=0;phase_=0;done_=false;
}
void FireBluetoothJobs::reset() {wasAdvertising_=false;cancel(owner_);client_=nullptr;callbackOwner_=nullptr;}
#endif
