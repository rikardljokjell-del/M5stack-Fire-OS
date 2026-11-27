"""Actual session observer/frame ownership/start producer, with host I/O spies.

These assertions establish parsing and ownership, never physical heap/latency.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_native_guards as native

ROOT=native.ROOT

def source():
    backend=(ROOT/'src/fire_backend_client.cpp').read_text(encoding='utf-8')
    def method(start):
        at=backend.index(start)
        return backend[at:backend.index('\n}\n',at)+3]
    observe=method('void FireBackendClient::observeSession(')
    frame=method('void FireBackendClient::handleFrame(')
    release=method('void FireBackendClient::releaseReadBuffers(')
    receive=method('void FireBackendClient::resetReceiveFrame(')+method('void FireBackendClient::readFrames(')
    legacy=(ROOT/'tests/session_start_rc14.inc').read_text(encoding='utf-8')
    start=backend.split('void FireBackendClient::handleHandshake()',1)[1].split('  const String startEvent=',1)[1].split('  // Pending choices',1)[0]
    start='  const String startEvent='+start.replace('return;}','return String();}')+'  return payload;\n'
    fields=method('String jsonStringField(')+method('uint32_t jsonUintField(')
    return PREAMBLE+fields+observe+frame+release+receive+'String FireBackendClient::legacyStart(){\n'+legacy+'return payload;\n}\nString FireBackendClient::start(){\n'+start+'}\n'+MAIN

PREAMBLE=r'''
#include <cassert>
#include <cstdio>
#include <string>
#include <utility>
#include <cstdint>
#include <cstdlib>
#include <algorithm>
#include "fire_session_json.h"
#include "fire_session_selection.h"
#include "fire_backend_policy.h"
#include "fire_ws_handshake.h"
using std::min;
static_assert(sizeof(fire_session_json::Document)<=16,"No document/token storage");
static_assert(sizeof(fire_session_json::Span)<=16,"Only borrowed spans");
struct String {
  std::string value;
  static int copies,allocationLimit,reserveLimit;
  String()=default;String(const char* s):value(s?s:""){}String(std::string s):value(std::move(s)){}
  String(const String& s):value(s.value){++copies;}String(String&& s):value(std::move(s.value)){s.value.clear();}
  String& operator=(const String& s){value=s.value;++copies;return *this;}
  String& operator=(String&& s){value=std::move(s.value);s.value.clear();return *this;}
  size_t length()const{return value.size();}const char* c_str()const{return value.c_str();}
  bool reserve(size_t n){if(reserveLimit==0)return false;if(reserveLimit>0)--reserveLimit;value.reserve(n);return true;}
  bool concat(const char* s){if(allocationLimit==0)return false;if(allocationLimit>0)--allocationLimit;value+=s;return true;}
  bool concat(const char* s,size_t n){value.append(s,n);return true;}
  char operator[](size_t n)const{return value[n];}
  String& operator+=(char c){value+=c;return *this;}
  String& operator+=(const String& s){value+=s.value;return *this;}
  int indexOf(char c,int from=0)const{auto n=value.find(c,size_t(from));return n==std::string::npos?-1:int(n);}
  int indexOf(const String& s,int from=0)const{auto n=value.find(s.value,size_t(from));return n==std::string::npos?-1:int(n);}
  String substring(size_t start)const{return value.substr(start);}
  long toInt()const{return std::strtol(value.c_str(),nullptr,10);}
  friend bool operator==(const String&a,const String&b){return a.value==b.value;}
  friend bool operator!=(const String&a,const String&b){return !(a==b);}
  friend String operator+(const String&a,const String&b){return a.value+b.value;}
};
int String::copies=0;int String::allocationLimit=-1;int String::reserveLimit=-1;
struct SerialSpy {template<class... T>void printf(const char*,T...) {}} Serial;
uint32_t millis(){return 100;}int64_t esp_timer_get_time(){return 100;}
unsigned memory[6][5]{};
void fireNetMemory(unsigned phase,unsigned kind){++memory[phase][kind];}
struct cJSON {const char* valuestring=nullptr;};
unsigned jsonParses=0;
cJSON* cJSON_Parse(const char*){++jsonParses;return nullptr;}
const cJSON* cJSON_GetObjectItemCaseSensitive(const cJSON*,const char*){return nullptr;}
bool cJSON_IsString(const cJSON*){return false;}bool cJSON_IsFalse(const cJSON*){return false;}
void cJSON_Delete(cJSON*){}
constexpr size_t kMaxFrameBytes=8192;
struct FireLuaRuntime {static const char* hardwareApiContract(){return "hardware";}static const char* appSdkVersion(){return "sdk";}static const char* appSdkContract(){return "sdkhash";}};
namespace FireRuntimeAiContract {const char* kVersion="runtime";const char* kContract="runtimehash";}
namespace FireEvolutionContract {const char* kVersion="evolution";const char* kContract="evolutionhash";}
String dataCapabilities(){return "{\"capture\":true}";}String hardwareServiceCapabilities(){return ",\"services\":[]";}
String i2cWriteResources(){return "[60]";}String jsonEscape(const String& s){return fire_session::escape(s);}
struct WiFiClient {
  std::string wire;size_t at=0;
  bool connected(){return true;}int available(){return int(wire.size()-at);}
  int read(){return at<wire.size()?static_cast<unsigned char>(wire[at++]):-1;}
  int read(uint8_t* out,size_t n){n=min(n,wire.size()-at);memcpy(out,wire.data()+at,n);at+=n;return int(n);}
};
struct FireBackendClient {
  String confirmedProject_="old-project",confirmedBase_="old-base",confirmedMode_="develop",confirmedAppMode_="update";
  fire_session::Selection<String> selection_;uint8_t selectionReply_=0,memoryKinds_=0;
  bool receiveCallbackActive_=false,releaseReadBuffersPending_=false,sessionStarted_=true,usingReverseTransport_=false;
  uint32_t lastReceiveAt_=0,lastPongAt_=0,lastServerSeq_=0,connectionEpoch_=0;
  String frameBuffer_,fragmentBuffer_,handshakeBuffer_,sessionId_="old-session",resumeSessionId_,developmentContext_;
  String bootId_="boot-one",deviceId_="device-one",firmwareVersion_="fire-os-test",sent;
  WiFiClient client;
  enum class ReceiveStage:uint8_t {Header,ExtendedLength,Mask,Payload};ReceiveStage receiveStage_=ReceiveStage::Header;
  uint8_t receiveHeaderBytes_=0,receiveOpcode_=0,receiveExtendedNeeded_=0,receiveExtendedBytes_=0,receiveMaskBytes_=0,fragmentOpcode_=0;
  uint8_t receiveExtended_[8]{},receiveMask_[4]{};bool receiveFin_=false,receiveMasked_=false;
  uint64_t receiveLength_=0;size_t receivePayloadBytes_=0;
  WiFiClient* activeClient(){return &client;}
  unsigned disconnected=0,callbacks=0;uint8_t sentOpcode=0;
  const char* expectedPayload=nullptr;
  enum class State {Offline,Connected};FireWsSessionAdmission sessionAdmission_;
  void* callbackContext_=this;
  void (*messageCallback_)(void*,const String&)=[](void* context,const String& message){
    auto* self=static_cast<FireBackendClient*>(context);++self->callbacks;
    if(self->expectedPayload)assert(message.c_str()==self->expectedPayload);
    if(message.value.find("disconnect_callback")!=std::string::npos){
      const char* owned=message.c_str();self->disconnect();assert(message.c_str()==owned && message.length()>20);
    }
  };
  void disconnect(){++disconnected;releaseReadBuffersPending_=true;releaseReadBuffers();}
  void setState(State,const char*){}void bootstrapDiagnostic(uint8_t,uint32_t=0,uint32_t=0){}
  bool sendFrame(uint8_t op,const uint8_t* data,size_t n){sentOpcode=op;sent=String(std::string(reinterpret_cast<const char*>(data),n));return true;}
  bool eventIdentityAvailable=true;
  String eventId(const char*){return eventIdentityAvailable?String("evt-fixed"):String();}
  void observeSession(const String&,const String&);void handleFrame(uint8_t,String&);void releaseReadBuffers();void resetReceiveFrame();void readFrames();
  String legacyStart();String start();
};
'''

MAIN=r'''
static std::string wire(unsigned opcode,bool fin,const std::string& payload) {
  assert(payload.size()<126);return std::string(1,char(opcode|(fin?128:0)))+char(payload.size())+payload;
}
static void invalid(const std::string& json) {
  FireBackendClient c;c.selection_.queueApp("new","","","evt-one");c.selection_.appSent=true;
  c.observeSession("session_snapshot",String(json));
  assert(c.confirmedProject_=="old-project" && c.confirmedBase_=="old-base" && c.selection_.pending());
}
int main(){
  using fire_session_json::Document;
  for(const char* malformed:{"{} garbage","{\"project_id\":\"new\",}","{\"x\":[1,]}","{\"x\":01}","{\"x\":truefalse}","{\"x\":1e+}","{\"x\":\"\\x20\"}","{\"x\":\"\\ud800\"}","{\"x\":\"\\udc00\"}","{\"x\":\"\\ud800\\u0000\"}"}) {
    assert(!Document(malformed,strlen(malformed)).valid());invalid(malformed);
  }
  invalid("{\"project_id\":\"new\",\"base_package_id\":\""+std::string(129,'a')+"\"}");
  invalid("{\"project_id\":\"new\",\"selection_ack\":{\"app_select\":\"\\u0000evt-one\"}}");
  invalid("{\"project_id\\u0000suffix\":\"evil\",\"project_id\":\"new\"}");
  const std::string badUtf8="{\"x\":\""+std::string(1,char(0xc0))+"\"}";
  assert(!Document(badUtf8.data(),badUtf8.size()).valid());
  std::string deep="0";for(unsigned i=0;i<12;++i)deep="["+deep+"]";
  const std::string tooDeep="{\"x\":"+deep+"}";assert(!Document(tooDeep.data(),tooDeep.size()).valid());
  deep="0";for(unsigned i=0;i<11;++i)deep="["+deep+"]";
  const std::string allowedDepth="{\"x\":"+deep+"}";assert(Document(allowedDepth.data(),allowedDepth.size()).valid());
  FireBackendClient c;
  c.observeSession("session_snapshot"," {\"nested\":{\"project_id\":\"evil\"},\"project_id\":\"first\",\"project_id\":\"second\",\"base_package_id\":null} \n");
  assert(c.confirmedProject_=="first" && c.confirmedBase_=="");
  c.observeSession("session_snapshot","{\"project_id\":null,\"project_id\":\"second\"}");assert(c.confirmedProject_=="");
  c.observeSession("session_snapshot","{\"project\\u005fid\":\"decoded-first\",\"project_id\":\"second\",\"conversation_mode\":null}");
  assert(c.confirmedProject_=="decoded-first" && c.confirmedMode_=="develop");
  c.observeSession("session_snapshot","{\"project\\u005fid\":\"ok\\u00e5\\ud83d\\ude00\",\"conversation_mode\":\"chat\"}");
  assert(c.confirmedProject_==String("ok\xc3\xa5\xf0\x9f\x98\x80") && c.confirmedMode_=="chat");
  c.selection_.queueApp("new","","","evt-app");c.selection_.appSent=true;c.selection_.lost();
  c.observeSession("session_started","{\"project_id\":\"new-project\",\"selection_ack\":{\"app_select\":\"evt-app\"}}");
  assert(!c.selection_.pending() && c.selectionReply_==1 && c.confirmedProject_=="new-project");
  c.selection_.queueMode("chat","evt-mode");c.selection_.modeSent=true;
  c.observeSession("event_ack","{\"event_id\":\"evt-mode\",\"result\":{\"conversation_mode\":\"chat\"}}");
  assert(!c.selection_.pending() && c.selectionReply_==2);
  c.selection_.queueApp("new","","","evt-busy");c.selection_.appSent=true;
  c.observeSession("error","{\"event_id\":\"other\"}");assert(c.selection_.pending());
  c.observeSession("event_ack","{\"event_id\":\"evt-busy\",\"result\":{\"error\":null,\"project_id\":\"evil\"}}");
  assert(!c.selection_.pending() && c.selectionReply_==4 && c.confirmedProject_=="new-project");
  assert(jsonParses==0); // Actual observer never constructs a JSON DOM.
  // A short SSO receipt must NOT be consumed when ANY later scope field
  // cannot allocate. Exercise both root-bootstrap and result-ACK staging.
  const std::string scope="\"project_id\":\""+std::string(90,'p')+"\",\"base_package_id\":\""+std::string(90,'b')+"\",\"conversation_mode\":\"chat\",\"app_mode\":\"new\"";
  for(bool bootstrap:{false,true})for(int failedField=0;failedField<4;++failedField) {
    FireBackendClient oom;oom.selection_.queueApp("new","pending-project","pending-base","e");oom.selection_.appSent=true;oom.selection_.appUnclear=true;
    oom.selection_.queueMode("chat","m");oom.selection_.modeSent=true;oom.selection_.modeUnclear=true;oom.selectionReply_=7;
    const String input(bootstrap?"{"+scope+",\"selection_ack\":{\"app_select\":\"e\",\"mode_select\":\"m\"}}":"{\"event_id\":\"e\",\"result\":{"+scope+"}}");
    String::reserveLimit=failedField;oom.observeSession(bootstrap?"session_snapshot":"event_ack",input);String::reserveLimit=-1;
    assert(oom.confirmedProject_=="old-project" && oom.confirmedBase_=="old-base" && oom.confirmedMode_=="develop" && oom.confirmedAppMode_=="update");
    assert(oom.selection_.appEvent=="e" && oom.selection_.modeEvent=="m" && oom.selection_.appSent && oom.selection_.modeSent && oom.selection_.appUnclear && oom.selection_.modeUnclear && oom.selectionReply_==0);
  }
  FireBackendClient staged;staged.selection_.queueApp("new","","","e");staged.selection_.appSent=true;
  const String stagedInput("{\"event_id\":\"e\",\"result\":{"+scope+"}}");
  String::reserveLimit=4;staged.observeSession("event_ack",stagedInput);String::reserveLimit=-1;
  assert(!staged.selection_.pending() && staged.selectionReply_==1 && staged.confirmedProject_.length()==90 && staged.confirmedBase_.length()==90 && staged.confirmedMode_=="chat" && staged.confirmedAppMode_=="new");
  // Actual frame handler moves both ordinary and completed-fragment owners.
  FireBackendClient f;f.frameBuffer_="{\"type\":\"app_catalog\",\"seq\":1,\"disconnect_callback\":true}";
  const char* data=f.frameBuffer_.c_str();f.expectedPayload=data;String::copies=0;f.handleFrame(1,f.frameBuffer_);f.expectedPayload=nullptr;
  assert(f.callbacks==1 && f.disconnected==1 && !f.receiveCallbackActive_ && !f.frameBuffer_.length());
  assert(data!=nullptr && memory[3][3]==1 && memory[4][3]==1 && memory[5][3]==1);
  assert(String::copies==0);
  f.fragmentBuffer_="{\"type\":\"session_snapshot\",\"seq\":2,\"project_id\":\"fragment-project\"}";
  f.handleFrame(1,f.fragmentBuffer_);assert(f.confirmedProject_=="fragment-project" && !f.fragmentBuffer_.length());
  f.frameBuffer_="ping";f.handleFrame(9,f.frameBuffer_);assert(f.sentOpcode==10 && f.sent=="ping" && f.frameBuffer_=="ping");
  f.handleFrame(10,f.frameBuffer_);assert(f.lastPongAt_==100);
  f.sessionStarted_=false;f.lastServerSeq_=900;f.resumeSessionId_="old-session";
  f.frameBuffer_="{\"type\":\"session_started\",\"session_id\":\"new-session\",\"seq\":1}";
  f.handleFrame(1,f.frameBuffer_);assert(f.sessionId_=="new-session" && f.lastServerSeq_==1 && f.sessionStarted_);
  FireBackendClient fragments;
  const std::string frames=wire(1,false,"{\"type\":\"session_")+wire(9,true,"ping")+
    wire(0,false,"snapshot\",\"project_id\":")+wire(0,true,"\"fragmented\",\"seq\":1}");
  for(char byte:frames){fragments.client.wire=std::string(1,byte);fragments.client.at=0;fragments.readFrames();}
  assert(fragments.callbacks==1 && fragments.confirmedProject_=="fragmented" && fragments.sent=="ping" && !fragments.fragmentBuffer_.length());
  FireBackendClient producer;
  for(const char* resume:{"","old-session"})for(const char* context:{"","context-one"}) {
    producer.resumeSessionId_=resume;producer.developmentContext_=context;
    assert(producer.start()==producer.legacyStart());
  }
  String::allocationLimit=3;assert(!producer.start().length() && producer.disconnected==1);String::allocationLimit=-1;
  producer.eventIdentityAvailable=false;
  assert(!producer.start().length() && producer.disconnected==2); // Actual bootstrap empty-ID guard.
  puts("PASS actual session observer, owned frames and byte-exact session_start");
}
'''

class SessionTransportTests(unittest.TestCase):
    def test_actual_session_transport(self):
        compiler=native.host_compiler()
        if not compiler:self.skipTest('No C++ compiler')
        prefix=[compiler,'c++'] if Path(compiler).stem.lower()=='zig' else [compiler]
        if os.name=='nt' and Path(compiler).stem.lower()=='zig':prefix+=['-target','x86_64-windows-gnu']
        with tempfile.TemporaryDirectory(prefix='fire-session-transport-') as tmp:
            path=Path(tmp)/'session.cpp';path.write_text(source(),encoding='utf-8')
            binary=Path(tmp)/('session.exe' if os.name=='nt' else 'session')
            result=subprocess.run(prefix+['-std=c++11','-UNDEBUG','-Wall','-Wextra','-Werror','-pedantic','-I',str(ROOT/'src'),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=180)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn('PASS actual session observer',run.stdout)

if __name__=='__main__':unittest.main()
