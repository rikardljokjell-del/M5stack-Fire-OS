static String fireWifiSsid(const String& input) {
  size_t offset=0,end=0;uint32_t cp=0;
  const size_t length=min<size_t>(32,input.length());
  while (offset<length && fire_app_bitmap::codepoint(input.c_str(),length,offset,cp) && cp>=32) end=offset;
  return input.substring(0,end);
}
bool FireOS::luaWifiStatusCallback(void* context,String* ssid,String* ip,int* rssi,bool* connected) {
  auto* os=static_cast<FireOS*>(context);if (!os || !ssid || !ip || !rssi || !connected) return false;
  *connected=WiFi.status()==WL_CONNECTED;
  *ssid=*connected?fireWifiSsid(WiFi.SSID()):String();
  *ip=*connected?WiFi.localIP().toString():String();*rssi=*connected?WiFi.RSSI():0;return true;
}
uint16_t FireOS::luaWifiScanCallback(void* context,const char** error) {
  auto* os=static_cast<FireOS*>(context);
  if (!os || os->wifiMode_==2 || os->firmwareBusy()) {setLuaError(error,"unavailable");return 0;}
  if (os->wifiScanActive_ || os->luaWifiScanJob_) {setLuaError(error,"busy");return 0;}
  const uint16_t id=os->createLuaJob(LuaJobKind::WifiScan,error);
  if (id) os->luaWifiScanJob_=id;
  return id;
}
void FireOS::serviceLuaWifiScan(LuaHardwareJob& job) {
  if (!job.started) {
    const int result=WiFi.scanNetworks(true,false,false,80);
    if (result!=WIFI_SCAN_RUNNING && result<0) {job.state=2;job.errorCode="wifi_scan_failed";return;}
    job.started=true;return;
  }
  const int count=WiFi.scanComplete();if (count==WIFI_SCAN_RUNNING) return;
  if (count<0) {job.state=2;job.errorCode="wifi_scan_failed";return;}
  String result="{\"ok\":true,\"networks\":[";
  for (int i=0;i<count && i<4;++i) {
    if (i) result+=",";
    result+="{\"ssid\":\""+jsonEscapeField(fireWifiSsid(WiFi.SSID(i)))+"\",\"rssi\":"+String(WiFi.RSSI(i))+
        ",\"secure\":"+(WiFi.encryptionType(i)==WIFI_AUTH_OPEN?"false":"true")+"}";
  }
  result+="]}";job.text=result;job.state=1;WiFi.scanDelete();luaWifiScanJob_=0;
}

uint16_t FireOS::luaBluetoothRequestCallback(void* context,const char* operation,
    const char* a,const char* b,const char* c,const uint8_t* bytes,size_t length,const char** error) {
#ifdef FIRE_OS_BLE
  auto* os=static_cast<FireOS*>(context);
  if (!os || os->bluetoothMode_==2 || os->firmwareBusy()) {setLuaError(error,"unavailable");return 0;}
  if (os->luaBluetooth_.busy() || os->bluetoothScanInProgress_ || os->bluetoothConnected_) {setLuaError(error,"busy");return 0;}
  if (length>128) {setLuaError(error,"invalid_argument");return 0;}
  const uint16_t id=os->createLuaJob(LuaJobKind::Bluetooth,error);if (!id) return 0;
  auto* job=os->findLuaJob(id);job->dataOperation=operation;job->path=a;job->text=b;job->aiSchema=c;
  job->payloadCount=length;if (length) memcpy(job->payload,bytes,length);
  return id;
#else
  (void)context;(void)operation;(void)a;(void)b;(void)c;(void)bytes;(void)length;
  setLuaError(error,"unavailable");return 0;
#endif
}
uint16_t FireOS::luaBluetoothRawCallback(void* context,const uint8_t* bytes,size_t length,uint32_t duration,const char** error) {
  auto* os=static_cast<FireOS*>(context);
  if (!os || !os->luaDataAllowed_ || length>FireDataEngineContract::kBleAdvBytes ||
      duration<FireDataEngineContract::kBleAdvertiseMinMs || duration>FireDataEngineContract::kBleAdvertiseMaxMs) {
    setLuaError(error,"permission_denied");return 0;
  }
  const uint16_t id=luaBluetoothRequestCallback(context,"advertise_raw","","","",bytes,length,error);
  if (id) {auto* job=os->findLuaJob(id);job->durationMs=duration;job->timeoutMs=duration+3000;}
  return id;
}
bool FireOS::luaBluetoothCloseCallback(void* context,uint16_t handle) {
  auto* os=static_cast<FireOS*>(context);
  if (!os || !handle || handle!=os->luaBluetoothHandle_) return false;
  os->luaBluetoothHandle_=0;return true; // actual controller cleanup is outside the callback
}

#ifdef FIRE_OS_BLE
static String fireBleAddress(const FireBluetoothJobs::Packet& packet) {
  char address[18];snprintf(address,sizeof(address),"%02x:%02x:%02x:%02x:%02x:%02x",
      packet.address[5],packet.address[4],packet.address[3],packet.address[2],packet.address[1],packet.address[0]);
  return String(address);
}
static String fireBleName(const FireBluetoothJobs::Packet& packet) {
  for (size_t i=0;i+1<packet.length;) {
    const uint8_t length=packet.bytes[i];if (!length || i+length>=packet.length) break;
    if (packet.bytes[i+1]==8 || packet.bytes[i+1]==9) {
      const char* name=reinterpret_cast<const char*>(packet.bytes+i+2);
      const size_t bytes=min<size_t>(length-1,32);size_t offset=0,end=0;uint32_t cp=0;
      while (offset<bytes && fire_app_bitmap::codepoint(name,bytes,offset,cp) && cp>=32) end=offset;
      String result;result.concat(name,end);return result;
    }
    i+=length+1;
  }
  return String("BLE device");
}
#endif
void FireOS::serviceLuaBluetoothJob(LuaHardwareJob& job) {
#ifdef FIRE_OS_BLE
  const auto fail=[&](const char* code) {job.state=2;job.errorCode=code;luaBluetooth_.cancel(job.id);};
  if (bluetoothMode_==2 || firmwareBusy()) {fail("unavailable");return;}
  if (!job.started) {
    if (luaBluetooth_.busy()) return;
    if (!initBluetooth()) {fail("unavailable");return;}
    bool accepted=false;
    if (job.dataOperation=="scan") accepted=luaBluetooth_.scan(job.id,2000);
    else if (job.dataOperation=="advertise_raw") accepted=luaBluetooth_.advertise(job.id,job.payload,job.payloadCount,job.durationMs);
    else if (job.dataOperation=="advertise") {
      NimBLEUUID uuid(job.text.c_str());NimBLEAdvertisementData advertisement;
      if (!uuid.bitSize() || !advertisement.addServiceUUID(uuid)) {fail("invalid_argument");return;}
      const size_t available=31-advertisement.getPayload().size();
      size_t end=0,offset=0;uint32_t cp=0;
      while (offset<job.path.length() && fire_app_bitmap::codepoint(job.path.c_str(),job.path.length(),offset,cp) && offset+2<=available) end=offset;
      if (end) advertisement.setShortName(std::string(job.path.c_str(),end));
      const auto bytes=advertisement.getPayload();
      accepted=luaBluetooth_.advertise(job.id,bytes.data(),bytes.size(),0);
      if (accepted) {luaBluetoothHandle_=job.id;job.written=job.id;job.state=1;}
    } else if (job.dataOperation=="read_gatt" || job.dataOperation=="write_gatt") {
      if (job.path.length()!=17) {fail("invalid_argument");return;}
      for (uint8_t i=0;i<17;++i) {
        const char c=job.path[i];
        if ((i%3==2 && c!=':') || (i%3!=2 && !isxdigit(static_cast<unsigned char>(c)))) {fail("invalid_argument");return;}
      }
      uint8_t type=0;
      for (uint8_t i=0;i<bluetoothScanCount_;++i) if (job.path.equalsIgnoreCase(bluetoothAddresses_[i])) type=bluetoothAddressTypes_[i];
      accepted=luaBluetooth_.gatt(job.id,job.path.c_str(),type,job.text.c_str(),job.aiSchema.c_str(),job.payload,job.payloadCount,job.dataOperation=="write_gatt");
    }
    if (!accepted) {fail("unavailable");return;}
    job.started=true;return;
  }
  luaBluetooth_.service();
  if (job.dataOperation=="scan") {
    FireBluetoothJobs::Packet packet;
    for (uint8_t n=0;n<4 && luaBluetooth_.pop(packet);++n) {
      const String address=fireBleAddress(packet);bool exists=false;
      for (uint8_t i=0;i<job.entryCount;++i) if (job.entryNames[i*2+1]==address) exists=true;
      if (!exists && job.entryCount<4) {
        const uint8_t i=job.entryCount++;job.entryNames[i*2]=fireBleName(packet);job.entryNames[i*2+1]=address;
        job.entrySizes[i]=static_cast<int>(packet.rssi)+128;
        if (bluetoothScanCount_<kMaxBluetoothDevices) {
          const uint8_t index=bluetoothScanCount_++;
          bluetoothAddresses_[index]=address;bluetoothAddressTypes_[index]=packet.type;
        }
      }
    }
    if (!luaBluetooth_.finished()) return;
    String result="{\"ok\":true,\"devices\":[";
    for (uint8_t i=0;i<job.entryCount;++i) {
      if (i) result+=",";
      result+="{\"name\":\""+jsonEscapeField(job.entryNames[i*2])+"\",\"address\":\""+job.entryNames[i*2+1]+
        "\",\"rssi\":"+String(static_cast<int>(job.entrySizes[i])-128)+"}";
    }
    result+="]}";job.text=result;job.state=1;luaBluetooth_.cancel(job.id);return;
  }
  if (luaBluetooth_.finished()) {
    if (!luaBluetooth_.succeeded()) {fail("bluetooth_failed");return;}
    if (job.dataOperation=="read_gatt") job.byteCount=luaBluetooth_.result(job.bytes,sizeof(job.bytes));
    else job.written=job.payloadCount;
    job.state=1;luaBluetooth_.cancel(job.id);
  }
#else
  job.state=2;job.errorCode="unavailable";
#endif
}
