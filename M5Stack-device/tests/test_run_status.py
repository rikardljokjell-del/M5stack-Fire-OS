"""Actual current-run handlers + actual frame/event producers with bounded I/O spies.

No fake consent, VM execution, hardware/network or physical performance claim.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_native_guards as native
import test_session_transport as transport

ROOT=native.ROOT

def block(text,marker):
    at=text.index(marker);start=text.index('{',at);depth=1;end=start+1;quoted=False;escape=False
    while depth:
        c=text[end]
        if quoted:
            if escape:escape=False
            elif c=='\\':escape=True
            elif c=='"':quoted=False
        elif c=='"':quoted=True
        elif c=='{':depth+=1
        elif c=='}':depth-=1
        end+=1
    return text[at:end]

def source():
    backend=(ROOT/'src/fire_backend_client.cpp').read_text(encoding='utf-8')
    os_source=(ROOT/'src/fire_os.cpp').read_text(encoding='utf-8')
    def method(text,name):
        at=text.index(name);return text[at:text.index('\n}\n',at)+3]
    string=transport.PREAMBLE.split('struct SerialSpy',1)[0]
    string=string.replace('String()=default;', 'bool startsWith(const String& p)const{return value.compare(0,p.value.size(),p.value)==0;}String()=default;')
    string=string.replace('std::string value;','std::string value;static bool failId;')
    string=string.replace('String(const char* s):value(s?s:""){}','String(const char* s):value(s?s:""){if(failId && s && (!strncmp(s,"rs-",3) || !strncmp(s,"rh-",3)))value.clear();}')
    string+='\nbool String::failId=false;\n'
    methods=''.join(method(backend,name) for name in ('String jsonStringField(','uint32_t jsonUintField(',
        'bool FireBackendClient::sendFrame(','bool FireBackendClient::sendEvent(',
        'bool FireBackendClient::appStarted(','bool FireBackendClient::appHealthy('))
    methods+=method(os_source,'int jsonIntField(')
    methods+=''.join(method(os_source,name) for name in ('void FireOS::noteRunStatusUnconfirmed(',
        'bool FireOS::deferLuaRunRebind(',
        'bool FireOS::bindLuaRunStatus(','void FireOS::serviceLuaRunStatus(','void FireOS::updateLuaApp(',
        'bool FireOS::backendCommandUnexpired('))
    dispatch=os_source.split('void FireOS::handleBackendMessage(',1)[1]
    methods+='void FireOS::runRequest(const String& message){const String type="run_request";'+block(dispatch,'if (type == "run_request")')+'}\n'
    state=os_source.split('void FireOS::backendState(',1)[1]
    methods+='void FireOS::bindingState(bool connected){auto* os=this;if(!connected){'+block(state,'if(os->luaAppActive_ &&')+'}}\n'
    update=os_source.split('void FireOS::updateBackend()',1)[1]
    methods+='void FireOS::bindingSend(){'+block(update,'if(luaAiBindPackageId_.length())')+'}\n'
    stop=method(os_source,'void FireOS::stopLuaApp(')
    prefix=stop.split('  luaSdkFrame_.invalidate();',1)[0].split('{',1)[1]
    natural=block(stop,'if (stoppedRunId.length() > 0 && backendClient_)')
    methods+='void FireOS::stopLuaApp(const String& reason){'+prefix+r'''
      const String stoppedRunId=luaRunId_,stoppedPackageId=luaPackageId_,stoppedDiagnostics;
      const bool userExit=reason=="back" || reason=="home" || reason=="user_exit";
      const bool requestedStop=reason=="remote_stop" || reason=="rollback",osNavigation=reason=="os_navigation";
      luaAppActive_=false;if(luaRuntime_)luaRuntime_->executing=false;luaRunId_=String();luaHealthySent_=false;
      '''+natural+'}\n'
    # Loader spy uses the ACTUAL revocation statement before simulating a single
    # verified VM load. The full run_request branch controls every invocation.
    start=method(os_source,'bool FireOS::startLuaApp(')
    clear=start.split('{',1)[1].split('\n',2)[1]
    assert 'luaRunDelivery_.clear();' in clear
    methods+='bool FireOS::startLuaApp(const String& path,const String&,const String& package,const String& source){'+clear+r'''
      ++loads;if(!loadOk)return false;luaAppPath_=path;luaPackageId_=package;luaSourceHash_=source;
      luaAppActive_=true;luaRuntime_->executing=true;return true;}
'''
    return string+PREAMBLE+methods+MAIN

PREAMBLE=r'''
#include <vector>
#include "fire_run_receipts.h"
using std::min;
uint32_t nowMs=1000,randomValue=0;
uint32_t millis(){return nowMs;}uint32_t esp_random(){return ++randomValue;}
constexpr unsigned MALLOC_CAP_INTERNAL=1,MALLOC_CAP_8BIT=2;
unsigned heap_caps_get_free_size(unsigned){return 100000;}
constexpr size_t kMaxFrameBytes=8192;
String jsonEscape(const String& text){return fire_session::escape(text);}
struct Wire {
  bool open=true;size_t capacity=8192;int partialAt=-1;unsigned writes=0;
  std::vector<uint8_t> bytes;
  bool connected(){return open;}bool canWrite(size_t n){return open && capacity>=n;}
  size_t write(const uint8_t* data,size_t n){if(int(writes++)==partialAt)n=n? n-1:0;bytes.insert(bytes.end(),data,data+n);capacity-=min(capacity,n);return n;}
};
using WiFiClient=Wire;
struct FireBackendClient {
  Wire client_;bool usingReverseTransport_=false,ready=true;
  String deviceId_="device-one",bootId_="boot-one",sessionId_="session-one";uint32_t epoch=1;
  unsigned generated=0,failures=0,stops=0,confirms=0;
  String stoppedRun,stoppedPackage,stoppedReason;
  void (*onDisconnect)(FireBackendClient&)=nullptr;
  fire_backend_policy::SendDisposition lastSendDisposition_=fire_backend_policy::SendDisposition::NotQueued;
  WiFiClient* activeClient(){return &client_;}bool sessionReady()const{return ready;}
  const String& sessionId()const{return sessionId_;}const String& bootId()const{return bootId_;}
  uint32_t connectionEpoch()const{return epoch;}
  bool pendingWrites()const{return false;}
  bool confirmRun(const String&){++confirms;return true;}
  auto lastSendDisposition()const -> fire_backend_policy::SendDisposition{return lastSendDisposition_;}
  void disconnect(){ready=false;client_.open=false;if(onDisconnect)onDisconnect(*this);}
  String eventId(const char*){++generated;return "automatic-event";}
  bool sendFrame(uint8_t,const uint8_t*,size_t);bool sendEvent(const String&,const String&,const String& stable=String());
  bool appStarted(const String&,const String&,const String&,const String& diag=String(),const String& stable=String());
  bool appHealthy(const String&,const String&,const String& diag=String(),const String& stable=String());
  bool appFailed(const String&,const String&,const String&,const String&,const String& =String()){++failures;return true;}
  bool appStopped(const String& run,const String& package,const String&,const String& reason,const String& =String()){++stops;stoppedRun=run;stoppedPackage=package;stoppedReason=reason;return true;}
};
struct Runtime {
  bool executing=false,updateOk=true;uint32_t frames=0;
  bool running()const{return executing;}uint32_t frameCount()const{return frames;}
  bool update(uint32_t){if(updateOk)++frames;return updateOk;}
  uint32_t lastCallbackUs()const{return 10;}uint32_t peakMemoryUsed()const{return 1024;}
  String lastError()const{return "callback failed";}
};
struct Package {bool active=false;bool busy()const{return active;}};
struct Evolution {void callback(unsigned,unsigned,unsigned,unsigned){}void bindRun(const String&,uint32_t){}};
struct Data {void bindRun(const String&){}};
bool validSha256Hex(const String& value){return fire_lua_install::hash(value.c_str());}
String sdBaseName(const String&){return "test-app";}
struct FireOS {
  FireBackendClient* backendClient_=nullptr;Runtime* luaRuntime_=nullptr;Package* packageManager_=nullptr;
  fire_run_receipts::Ring luaRunReceipts_;fire_run_receipts::Delivery luaRunDelivery_;
  bool luaHealthySent_=false,luaAppActive_=false,luaAiBindSent_=false,redrawRequested_=false,loadOk=true,resolveOk=true;
  bool luaRuntimeAiAllowed_=false,luaDataAllowed_=false,luaDevelopJob_=false,appInventoryPending_=false,luaScanPending_=false,luaCacheComplete_=true;
  uint32_t luaAiBindAt_=0;
  uint8_t wifiMode_=1,backendMode_=1,aiWorkflowState_=0,aiDeveloperMode_=0;
  unsigned loads=0,rgb=0;uint32_t luaLastFrameAt_=0;
  String luaRunId_,luaPackageId_,luaSourceHash_,luaAppPath_,luaAiBindPackageId_,luaAppError_;
  String aiWorkflowText_,managerStatus_,luaRepairMessage_,luaRepairReadyPackageId_,luaRepairStatus_,luaRepairPhase_,aiPackageId_;
  Evolution evolution_;Data luaDataStore_;
  uint32_t backendCommandNow()const{return 1000+nowMs/1000;}
  bool backendCommandUnexpired(uint32_t)const;
  bool resolveLuaPackage(const String&,const String&,const String&,String& path){path="/apps/test-app/main.lua";return resolveOk;}
  bool startLuaApp(const String&,const String&,const String&,const String&);
  void stopLuaApp(const String&);void flushLuaRgb(){++rgb;}
  void runRequest(const String&);bool bindLuaRunStatus(fire_run_receipts::Entry*);
  void serviceLuaRunStatus();void noteRunStatusUnconfirmed();void updateLuaApp();
  bool deferLuaRunRebind()const;void bindingState(bool);void bindingSend();
};
struct Fixture {
  FireBackendClient backend;Runtime runtime;Package package;FireOS os;
  Fixture(){os.backendClient_=&backend;os.luaRuntime_=&runtime;os.packageManager_=&package;}
};
'''

MAIN=r'''
static std::vector<std::string> bodies(const Wire& wire){
  std::vector<std::string> result;size_t at=0;
  while(at<wire.bytes.size()){
    assert(wire.bytes.size()-at>=6);assert(wire.bytes[at++]==129);
    size_t n=wire.bytes[at++]&127;
    if(n==126){assert(wire.bytes.size()-at>=2);n=size_t(wire.bytes[at])*256+wire.bytes[at+1];at+=2;}
    assert(wire.bytes.size()-at>=n+4);uint8_t mask[4];memcpy(mask,wire.bytes.data()+at,4);at+=4;
    std::string body;for(size_t i=0;i<n;++i)body+=char(wire.bytes[at+i]^mask[i&3]);at+=n;
    assert(fire_session_json::Document(body.data(),body.size()).valid());result.push_back(body);
  }return result;
}
static const std::string sourceHash(64,'a'),archiveHash(64,'b');
static String command(const std::string& id="run-one",uint32_t expiry=0,const char* sid="session-one"){
  if(!expiry)expiry=1000+nowMs/1000+30;
  return std::string("{\"type\":\"run_request\",\"run_id\":\"")+id+"\",\"package_id\":\"package-one\",\"session_id\":\""+sid+"\",\"boot_id\":\"boot-one\",\"source_sha256\":\""+sourceHash+"\",\"archive_sha256\":\""+archiveHash+"\",\"expires_at\":"+std::to_string(expiry)+"}";
}
int main(){
  using fire_backend_policy::SendDisposition;
  static_assert(sizeof(fire_run_receipts::Delivery)<=160,"One bounded current-run record");
  nowMs=1000;Fixture first;first.backend.client_.capacity=0;const String request=command();
  first.os.runRequest(request);assert(first.os.loads==1 && first.os.luaAppActive_ && !first.os.luaHealthySent_);
  assert(first.backend.lastSendDisposition()==SendDisposition::NotQueued && first.backend.client_.bytes.empty());
  first.os.updateLuaApp();assert(!first.os.luaHealthySent_ && first.backend.client_.bytes.empty());
  first.backend.client_.capacity=8192;nowMs+=249;first.os.serviceLuaRunStatus();assert(first.backend.client_.bytes.empty());
  ++nowMs;first.os.serviceLuaRunStatus();assert(bodies(first.backend.client_).size()==1 && !first.os.luaHealthySent_);
  first.os.updateLuaApp();auto ordered=bodies(first.backend.client_);assert(ordered.size()==2 && first.os.luaHealthySent_);
  assert(ordered[0].find("\"event_id\":\"rs-run-one\"")!=std::string::npos && ordered[0].find("\"event\":\"app_started\"")!=std::string::npos);
  assert(ordered[1].find("\"event_id\":\"rh-run-one\"")!=std::string::npos && ordered[1].find("\"event\":\"app_healthy\"")!=std::string::npos);
  assert(ordered[0].find("diagnostics")==std::string::npos && ordered[1].find("diagnostics")==std::string::npos);
  for(unsigned i=0;i<10;++i){nowMs+=250;first.os.serviceLuaRunStatus();}assert(bodies(first.backend.client_).size()==2);
  first.os.runRequest(request);ordered=bodies(first.backend.client_);
  assert(ordered.size()==3 && ordered[2]==ordered[0] && first.os.loads==1 && first.backend.generated==0);
  puts("PASS actual full-queue retry Started-before-Healthy canonical explicit duplicate one VM");

  nowMs=1000;Fixture noUpdate;noUpdate.os.runRequest(command());nowMs+=500;noUpdate.os.serviceLuaRunStatus();
  assert(!noUpdate.os.luaHealthySent_ && bodies(noUpdate.backend.client_).size()==1);
  noUpdate.runtime.updateOk=false;noUpdate.os.updateLuaApp();assert(!noUpdate.os.luaRunDelivery_.entry && !noUpdate.os.luaHealthySent_ && bodies(noUpdate.backend.client_).size()==1);
  nowMs=1000;Fixture reconnect;reconnect.backend.client_.capacity=0;reconnect.os.runRequest(command());
  const uint32_t originalExpiry=reconnect.os.luaRunDelivery_.entry->expires;
  reconnect.backend.ready=false;nowMs+=250;reconnect.os.serviceLuaRunStatus();assert(reconnect.os.luaRunDelivery_.entry);
  reconnect.backend.ready=true;++reconnect.backend.epoch;reconnect.backend.client_.capacity=8192;
  reconnect.os.serviceLuaRunStatus();reconnect.os.updateLuaApp();
  assert(reconnect.os.luaHealthySent_ && reconnect.os.loads==1 && reconnect.os.luaRunDelivery_.entry->expires==originalExpiry && bodies(reconnect.backend.client_).size()==2);

  nowMs=1000;Fixture health;health.os.runRequest(command());health.backend.client_.capacity=0;
  health.os.updateLuaApp();assert(!health.os.luaHealthySent_ && bodies(health.backend.client_).size()==1);
  health.backend.client_.capacity=8192;nowMs+=249;health.os.serviceLuaRunStatus();assert(!health.os.luaHealthySent_);
  ++nowMs;health.os.serviceLuaRunStatus();assert(health.os.luaHealthySent_ && bodies(health.backend.client_).size()==2);
  assert(health.os.loads==1);

  for(int failedWrite:{0,1}) {
    nowMs=1000;Fixture partial;partial.backend.client_.partialAt=failedWrite;
    partial.backend.onDisconnect=[](FireBackendClient& backend){assert(!backend.sendEvent("cancel_turn",String()));};
    partial.os.runRequest(command());
    assert(partial.backend.lastSendDisposition()==SendDisposition::Uncertain && partial.os.luaRunDelivery_.uncertain());
    const auto partialBytes=partial.backend.client_.bytes.size();partial.backend.ready=true;partial.backend.client_.open=true;partial.backend.client_.partialAt=-1;++partial.backend.epoch;
    for(unsigned i=0;i<3;++i){nowMs+=250;partial.os.updateLuaApp();partial.os.serviceLuaRunStatus();}
    assert(partial.backend.client_.bytes.size()==partialBytes && !partial.os.luaHealthySent_ && partial.os.luaAppActive_ && partial.os.loads==1);
    assert(partial.os.aiWorkflowText_=="Kjørestatus uavklart");partial.os.stopLuaApp("back");assert(!partial.backend.stops);
  }
  nowMs=1000;Fixture changedEpoch;changedEpoch.os.runRequest(command());++changedEpoch.backend.epoch;
  changedEpoch.os.updateLuaApp();assert(changedEpoch.os.luaRunDelivery_.uncertain() && !changedEpoch.os.luaHealthySent_ && bodies(changedEpoch.backend.client_).size()==1);
  puts("PASS actual partial-write and post-Started epoch uncertainty no automatic replay");

  for(unsigned why=0;why<8;++why){
    nowMs=1000;Fixture stale;stale.backend.client_.capacity=0;stale.os.runRequest(command());
    if(why==0)stale.backend.sessionId_="new-session";
    if(why==1)stale.backend.bootId_="new-boot";
    if(why==2)nowMs+=30000;
    if(why==3)stale.os.backendMode_=2;
    if(why==4)stale.os.wifiMode_=2;
    if(why==5)stale.os.stopLuaApp("back");
    if(why==6)stale.os.luaSourceHash_="different-source";
    if(why==7)stale.os.backendClient_=nullptr;
    stale.backend.client_.capacity=8192;stale.os.serviceLuaRunStatus();
    assert(!stale.os.luaRunDelivery_.entry && stale.backend.client_.bytes.empty() && !stale.os.luaHealthySent_);
    if(why==5)assert(!stale.backend.stops);
  }
  nowMs=1000;Fixture next;next.backend.client_.capacity=0;next.os.runRequest(command("run-old"));
  next.backend.client_.capacity=8192;next.os.runRequest(command("run-new"));next.os.updateLuaApp();
  const auto latest=bodies(next.backend.client_);assert(latest.size()==2 && latest[0].find("run-new")!=std::string::npos && latest[0].find("run-old")==std::string::npos && next.os.loads==1);
  Fixture full;full.backend.client_.capacity=0;
  for(unsigned i=0;i<8;++i)full.os.runRequest(command("run-"+std::to_string(i)));
  assert(full.os.luaRunDelivery_.entry);full.os.runRequest(command("run-ninth"));
  full.backend.client_.capacity=8192;nowMs+=250;full.os.serviceLuaRunStatus();
  assert(!full.os.luaRunDelivery_.entry && full.backend.client_.bytes.empty() && full.os.loads==1);
  nowMs=1000;Fixture stopped;stopped.os.runRequest(command());stopped.os.stopLuaApp("back");nowMs+=500;stopped.os.serviceLuaRunStatus();assert(stopped.backend.stops==1 && bodies(stopped.backend.client_).size()==1);
  puts("PASS actual scope expiry OFF Stop new-run invalidation no late status");
  // Admission expiry closes retries, not the lifecycle of a Started VM.
  for(const char* reason:{"back","home","os_navigation"}) {
    nowMs=1000;Fixture ongoing;ongoing.os.runRequest(command());ongoing.os.updateLuaApp();
    const auto sent=bodies(ongoing.backend.client_).size();assert(sent==2 && ongoing.os.luaRunDelivery_.healthy());
    nowMs+=61000;ongoing.os.serviceLuaRunStatus();
    assert(ongoing.os.luaRunDelivery_.entry && ongoing.os.luaRunDelivery_.started() && ongoing.os.luaRunDelivery_.admissionClosed());
    assert(!ongoing.os.luaRunDelivery_.pending() && ongoing.os.deferLuaRunRebind());
    ongoing.os.bindingState(false);assert(ongoing.os.luaRunId_=="run-one" && !ongoing.backend.confirms);
    ongoing.os.luaRunDelivery_.duplicate();ongoing.os.updateLuaApp();ongoing.os.serviceLuaRunStatus();
    assert(bodies(ongoing.backend.client_).size()==sent && ongoing.os.loads==1);
    ongoing.os.stopLuaApp(reason);ongoing.os.serviceLuaRunStatus();
    assert(ongoing.backend.stops==1 && ongoing.backend.stoppedRun=="run-one" && ongoing.backend.stoppedPackage=="package-one" && ongoing.backend.stoppedReason=="user_exit");
    assert(!ongoing.os.luaRunDelivery_.entry && !ongoing.os.luaAppActive_);
  }
  nowMs=1000;Fixture lateHealth;lateHealth.os.runRequest(command());lateHealth.backend.client_.capacity=0;lateHealth.os.updateLuaApp();
  assert(lateHealth.os.luaRunDelivery_.started() && !lateHealth.os.luaRunDelivery_.healthy());
  nowMs+=31000;lateHealth.os.serviceLuaRunStatus();lateHealth.backend.client_.capacity=8192;
  lateHealth.os.updateLuaApp();assert(!lateHealth.os.luaHealthySent_ && bodies(lateHealth.backend.client_).size()==1);
  lateHealth.os.stopLuaApp("home");assert(lateHealth.backend.stops==1);
  for(unsigned why=0;why<4;++why) {
    nowMs=1000;Fixture invalid;invalid.os.runRequest(command());invalid.os.updateLuaApp();nowMs+=31000;invalid.os.serviceLuaRunStatus();
    if(why==0)invalid.backend.sessionId_="other-session";
    if(why==1)invalid.backend.bootId_="other-boot";
    if(why==2)invalid.os.backendMode_=2;
    if(why==3)invalid.os.wifiMode_=2;
    invalid.os.serviceLuaRunStatus();invalid.os.stopLuaApp("back");assert(!invalid.backend.stops);
  }
  // An expired ongoing Entry cannot be overwritten while admission evaluates
  // a different run. No extra Ring slot or new authority is created.
  nowMs=1000;Fixture pinned;pinned.os.runRequest(command());pinned.os.updateLuaApp();
  auto* live=pinned.os.luaRunDelivery_.entry;nowMs+=31000;pinned.os.serviceLuaRunStatus();
  fire_run_receipts::Entry* fresh=nullptr;
  assert(pinned.os.luaRunReceipts_.admit("run-next","package-one",sourceHash.c_str(),archiveHash.c_str(),1100,1032,true,fresh,live)==fire_run_receipts::Admission::New);
  assert(fresh!=live && !strcmp(live->id,"run-one"));pinned.os.stopLuaApp("back");assert(pinned.backend.stops==1);
  puts("PASS actual expired Started lifecycle connected Back Home navigation and no late Start Healthy replay");

  nowMs=1000;Fixture pendingBind;pendingBind.os.luaDataAllowed_=true;pendingBind.backend.client_.capacity=0;pendingBind.os.runRequest(command());
  pendingBind.os.bindingState(false);assert(pendingBind.os.luaRunId_=="run-one" && !pendingBind.os.luaAiBindPackageId_.length());
  pendingBind.os.luaAiBindPackageId_=pendingBind.os.luaPackageId_;pendingBind.os.bindingSend();assert(!pendingBind.backend.confirms);
  Fixture uncertainBind;uncertainBind.os.luaRuntimeAiAllowed_=true;uncertainBind.os.runRequest(command());
  uncertainBind.os.luaAiBindPackageId_=uncertainBind.os.luaPackageId_;++uncertainBind.backend.epoch;uncertainBind.os.serviceLuaRunStatus();
  assert(uncertainBind.os.luaRunDelivery_.uncertain() && !uncertainBind.os.luaAiBindPackageId_.length());
  uncertainBind.os.bindingState(false);assert(uncertainBind.os.luaRunId_=="run-one" && !uncertainBind.os.luaAiBindPackageId_.length());
  uncertainBind.os.luaAiBindPackageId_=uncertainBind.os.luaPackageId_;uncertainBind.os.bindingSend();assert(!uncertainBind.backend.confirms);
  Fixture localBind;localBind.os.luaRuntimeAiAllowed_=true;localBind.os.runRequest(command());localBind.os.luaRunId_="local-other";
  localBind.os.bindingState(false);assert(!localBind.os.luaRunId_.length() && localBind.os.luaAiBindPackageId_==localBind.os.luaPackageId_);
  localBind.os.bindingSend();assert(localBind.backend.confirms==1);
  puts("PASS actual backendState and updateBackend bind guards current pending uncertain unrelated VM");

  nowMs=1000;Fixture tooLong;tooLong.os.runRequest(command(std::string(62,'r')));assert(!tooLong.os.loads && tooLong.backend.client_.bytes.empty());
  Fixture bound;bound.os.runRequest(command(std::string(61,'r')));assert(bound.os.loads==1);
  Fixture producer;const String run="run-producer",package="package-one",hash(sourceHash),event="rs-run-producer";
  producer.backend.lastSendDisposition_=SendDisposition::Queued;String::allocationLimit=0;
  assert(!producer.backend.appStarted(run,package,hash,String(),event));String::allocationLimit=-1;
  assert(producer.backend.lastSendDisposition()==SendDisposition::NotQueued && producer.backend.client_.bytes.empty());
  String::reserveLimit=0;assert(!producer.backend.appStarted(run,package,hash,String(),event));String::reserveLimit=-1;
  assert(producer.backend.lastSendDisposition()==SendDisposition::NotQueued && producer.backend.client_.bytes.empty());
  assert(producer.backend.appStarted(run,package,hash,String(),event));const auto original=bodies(producer.backend.client_)[0];
  assert(producer.backend.appStarted(run,package,hash,String(),event));assert(bodies(producer.backend.client_)[1]==original);
  assert(!producer.backend.appStarted(run,package,hash,"{}",event));assert(bodies(producer.backend.client_).size()==2 && !producer.backend.generated);
  producer.backend.ready=false;producer.backend.lastSendDisposition_=SendDisposition::Uncertain;
  assert(!producer.backend.appHealthy(run,package,String(),"rh-run-producer"));assert(producer.backend.lastSendDisposition()==SendDisposition::NotQueued);
  nowMs=1000;Fixture idOom;String::failId=true;idOom.os.runRequest(command());String::failId=false;
  assert(idOom.backend.client_.bytes.empty() && !idOom.backend.generated && !idOom.os.luaHealthySent_);
  nowMs+=250;idOom.os.serviceLuaRunStatus();idOom.os.updateLuaApp();assert(idOom.os.luaHealthySent_ && idOom.os.loads==1 && bodies(idOom.backend.client_).size()==2 && !idOom.backend.generated);
  puts("PASS actual canonical producers fail closed OOM full identity and exact payload");
}
'''

class RunStatusTests(unittest.TestCase):
    def build(self,execute):
        compiler=native.host_compiler()
        if not compiler:self.skipTest('No host C++ compiler')
        prefix=[compiler,'c++'] if Path(compiler).stem.lower()=='zig' else [compiler]
        if os.name=='nt' and Path(compiler).stem.lower()=='zig':prefix+=['-target','x86_64-windows-gnu']
        with tempfile.TemporaryDirectory(prefix='fire-current-run-') as tmp:
            path=Path(tmp)/'run.cpp';path.write_text(source(),encoding='utf-8')
            binary=Path(tmp)/('run' if execute else 'run.o')
            command=prefix+['-std=c++17','-Os','-UNDEBUG','-Wall','-Wextra','-Werror','-pedantic','-I',str(ROOT/'src')]
            if not execute:command+=['-c']
            result=subprocess.run(command+[str(path),'-o',str(binary)],capture_output=True,text=True,timeout=180)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            if execute:
                run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=15)
                self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                self.assertIn('PASS actual canonical producers',run.stdout)
    def test_actual_current_run_compile(self):self.build(False)
    @unittest.skipIf(os.name=='nt','Windows policy4551: object only, Linux executes actual assertions')
    def test_actual_current_run_execute(self):self.build(True)
    def test_single_ui_writer_and_bounded_demand(self):
        source=(ROOT/'src/fire_backend_client.cpp').read_text(encoding='utf-8')
        worker=source.split('void FireBackendClient::audioTaskEntry(',1)[1].split('String FireBackendClient::eventId(',1)[0]
        self.assertNotIn('sendEvent(',worker);self.assertNotIn('sendFrame(',worker)
        for name in ('bool FireBackendClient::uploadAudio(', 'bool FireBackendClient::downloadAudio('):
            body=source.split(name,1)[1].split('\n}\n',1)[0]
            self.assertNotIn('sendEvent(',body);self.assertNotIn('sendFrame(',body)
        disconnect=source.split('void FireBackendClient::disconnect()',1)[1].split('void FireBackendClient::releaseReadBuffers',1)[0]
        self.assertNotIn('lastSendDisposition_',disconnect)
        os_source=(ROOT/'src/fire_os.cpp').read_text(encoding='utf-8')
        self.assertIn('luaRunDelivery_.pending() ||',os_source)
        start=os_source.split('bool FireOS::startLuaApp(',1)[1]
        self.assertLess(start.index('luaRunDelivery_.clear()'),start.index('if (!luaRuntime_)'))
        owner=os_source.split('void FireOS::clearBackendCatalog()',1)[1].split('\n}\n',1)[0]
        self.assertIn('luaRunDelivery_.clear()',owner)

if __name__=='__main__':unittest.main()
