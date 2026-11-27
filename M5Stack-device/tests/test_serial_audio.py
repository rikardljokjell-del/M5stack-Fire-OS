"""Extracted production serial-audio producers, handoff, worker and HTTP paths.

The host supplies clocks, RTOS parking, byte streams and the mbedTLS primitive.
Production methods and guards are read verbatim at test time. Golden digest
adapters verify byte identity/plumbing, not the ESP32 crypto implementation or
physical microphone, TLS, memory or latency. Windows compiles only; Linux runs.
"""
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

import test_native_guards as native
import test_session_transport as transport
import test_run_status as run_status

ROOT = native.ROOT
PCM = struct.pack('<hhhh', 0, 100, -100, 0)
WAV = (b'RIFF' + struct.pack('<I', 36 + len(PCM)) + b'WAVEfmt ' +
       struct.pack('<IHHIIHH', 16, 1, 1, 8000, 16000, 2, 16) + b'data' +
       struct.pack('<I', len(PCM)) + PCM)


def method(text, signature):
    at = text.index(signature)
    return text[at:text.index('\n}\n', at) + 3]


def source():
    cpp = (ROOT / 'src/fire_backend_client.cpp').read_text(encoding='utf-8')
    header = (ROOT / 'src/fire_backend_client.h').read_text(encoding='utf-8')
    strings = transport.PREAMBLE.split('struct SerialSpy', 1)[0]
    strings = strings.replace('String()=default;', '''String()=default;
  template<class N,typename std::enable_if<std::is_integral<N>::value,int>::type=0>
  String(N n,int base=10){std::ostringstream out;if(base==16)out<<std::hex;out<<n;value=out.str();}''')
    strings = strings.replace('long toInt()const', '''void setCharAt(size_t at,char c){value.at(at)=c;}
  String substring(size_t a,size_t b)const{return value.substr(a,b-a);}
  bool startsWith(const String& s)const{return value.rfind(s.value,0)==0;}
  bool endsWith(const String& s)const{return value.size()>=s.length() && value.compare(value.size()-s.length(),s.length(),s.value)==0;}
  void toLowerCase(){for(char& c:value)c=static_cast<char>(std::tolower(static_cast<unsigned char>(c)));}
  bool equalsIgnoreCase(const String& s)const{String a=*this,b=s;a.toLowerCase();b.toLowerCase();return a==b;}
  long toInt()const''')
    fields = header[header.index('  enum class AudioTransfer'):header.index('  bool receiveCallbackActive_')]
    begin_selection = next(line for line in header.splitlines() if line.startswith('  bool beginSelection('))
    ops = cpp[cpp.index('struct AudioTaskOps {'):cpp.index('constexpr size_t kMaxFrameBytes')]
    names = (
        'String jsonStringField(', 'uint32_t jsonUintField(',
        'void FireBackendClient::snapshotAudioEndpoint(',
        'void FireBackendClient::closeControl(',
        'uint32_t FireBackendClient::audioNow(', 'bool FireBackendClient::audioScope(',
        'bool FireBackendClient::audioNetworkPaused(', 'bool FireBackendClient::audioOtherNetworksPaused(',
        'bool FireBackendClient::audioOwnsNetwork(', 'bool FireBackendClient::audioOwnsBuffer(',
        'const char* FireBackendClient::audioStatus(', 'void FireBackendClient::finishAudioTransfer(',
        'void FireBackendClient::releaseAudioResult(', 'void FireBackendClient::reapAudioWorker(',
        'bool FireBackendClient::startAudioWorker(', 'bool FireBackendClient::sendAudioCommit(',
        'bool FireBackendClient::handleAudioMessage(', 'void FireBackendClient::serviceAudioTransfer(',
        'bool FireBackendClient::listenStop(', 'bool FireBackendClient::beginAudioUpload(',
        'bool FireBackendClient::beginAudioDownload(', 'void FireBackendClient::cancelAudioTransfer(',
        'void FireBackendClient::audioTaskEntry(', 'void FireBackendClient::runAudioTransfer(',
        'String FireBackendClient::eventId(', 'bool FireBackendClient::uploadAudio(',
        'bool FireBackendClient::downloadAudio(',
        'bool FireBackendClient::audioPlaybackStarted(', 'bool FireBackendClient::audioPlaybackFinished(',
    )
    relative = method((ROOT / 'src/fire_async_client.cpp').read_text(encoding='utf-8'), 'bool fireRelativePath(')
    golden = '\n'.join(
        'static const std::vector<uint8_t> %s={%s};\nstatic const char* %sHash="%s";' %
        (name, ','.join(map(str, data)), name, hashlib.sha256(data).hexdigest())
        for name, data in (('wav', WAV), ('pcm', PCM), ('badPcm', PCM[:-1] + b'\x01')))
    qa = (ROOT / 'src/fire_os_local_qa.inc').read_text(encoding='utf-8')
    actual_qa = method(qa, 'bool FireOS::localQaActionAllowed(') + method(qa, 'fire_local_qa::Code FireOS::localQaAct(')
    os_source = (ROOT / 'src/fire_os.cpp').read_text(encoding='utf-8')
    audio_ready = run_status.block(os_source.split('void FireOS::handleBackendMessage(', 1)[1], 'if (type == "audio_ready")')
    output = (method(os_source, 'bool validSha256Hex(') + method(os_source, 'void FireOS::completeAiAudioUpload(') +
              method(os_source, 'void FireOS::updateAiAudioOutput(') +
              'void FireOS::audioReady(const String& message){const String type="audio_ready";' + audio_ready + '}\n')
    return (INCLUDES + strings + ADAPTERS.replace('/*GOLDEN*/', golden) + relative + ops +
            CLASS.replace('/*FIELDS*/', fields).replace('/*BEGIN_SELECTION*/', begin_selection) + '\n'.join(method(cpp, n) for n in names) +
            QA_CLASS + actual_qa + output + QA_MAIN + MAIN.replace('int main(){', 'int main(){qaMatrix();outputMatrix();completionMatrix();newIntentMatrix();'))


INCLUDES = r'''
#include <atomic>
#include <cctype>
#include <cstring>
#include <map>
#include <memory>
#include <sstream>
#include <type_traits>
#include <vector>
#include "fire_firmware_http.h"
#include "fire_lua_install_identity.h"
#include "fire_package_delivery.h"
#include "fire_local_qa.h"
#include "fire_buttons.h"
#include "fire_ai_menu.h"
#include "fire_ai_workflow.h"
'''

ADAPTERS = r'''
/*GOLDEN*/
constexpr int HEX=16;
static uint32_t nowMs=1000;
uint32_t millis(){return nowMs;}
void delay(unsigned ms){nowMs+=ms;}
String jsonEscape(const String& s){return fire_session::escape(s);}
// cJSON compatibility adapter over the actual bounded production JSON reader.
// It parses real test wire bytes; it does not choose expected branch results.
struct cJSON {
  std::shared_ptr<std::string> bytes;
  fire_session_json::Span span;
  std::string text;const char* valuestring=nullptr;double valuedouble=0;
  std::map<std::string,cJSON> fields;
};
cJSON* cJSON_Parse(const char* s){
  auto* p=new cJSON;p->bytes=std::make_shared<std::string>(s);
  fire_session_json::Document doc(p->bytes->data(),p->bytes->size());
  if(!doc.valid()){delete p;return nullptr;}p->span=doc.root();return p;
}
const cJSON* cJSON_GetObjectItemCaseSensitive(const cJSON* value,const char* key){
  if(!value)return nullptr;
  auto* p=const_cast<cJSON*>(value);auto old=p->fields.find(key);if(old!=p->fields.end())return &old->second;
  fire_session_json::Document doc(p->bytes->data(),p->bytes->size());const auto span=doc.field(p->span,key);
  if(!span.present())return nullptr;
  auto& child=p->fields[key];child.bytes=p->bytes;child.span=span;
  if(span.is('"')){String decoded;assert(doc.text(span,decoded));child.text=decoded.value;child.valuestring=child.text.c_str();}
  else if(span.is('-') || (span.size && span.data[0]>='0' && span.data[0]<='9')) child.valuedouble=std::strtod(span.data,nullptr);
  return &child;
}
bool cJSON_IsString(const cJSON* p){return p && p->span.is('"');}
bool cJSON_IsObject(const cJSON* p){return p && p->span.is('{');}
bool cJSON_IsNumber(const cJSON* p){return p && (p->span.is('-') || (p->span.size && std::isdigit(static_cast<unsigned char>(p->span.data[0]))));}
bool cJSON_IsTrue(const cJSON* p){return p && p->span.size==4 && !memcmp(p->span.data,"true",4);}
bool cJSON_IsBool(const cJSON* p){return p && (p->span.is('t') || p->span.is('f'));}
bool cJSON_IsNull(const cJSON* p){return p && p->span.is('n');}
void cJSON_Delete(cJSON* p){delete p;}
char* cJSON_PrintUnformatted(const cJSON*){assert(false && "DataUpload not exercised by serial-audio fixture");return nullptr;}
void cJSON_free(void*){}
int jsonIntField(const String& s,const char* key,int fallback=0){auto* p=cJSON_Parse(s.c_str());const auto* field=cJSON_GetObjectItemCaseSensitive(p,key);const int value=cJSON_IsNumber(field)?static_cast<int>(field->valuedouble):fallback;cJSON_Delete(p);return value;}
bool jsonBoolField(const String& s,const char* key,bool fallback=false){auto* p=cJSON_Parse(s.c_str());const auto* field=cJSON_GetObjectItemCaseSensitive(p,key);const bool value=cJSON_IsBool(field)?cJSON_IsTrue(field):fallback;cJSON_Delete(p);return value;}
// Primitive boundary only: exact known PCM/WAV bytes map to hashlib goldens.
struct mbedtls_sha256_context {std::vector<uint8_t> bytes;};
void mbedtls_sha256_init(mbedtls_sha256_context* p){p->bytes.clear();}
int mbedtls_sha256_starts_ret(mbedtls_sha256_context* p,int){p->bytes.clear();return 0;}
int mbedtls_sha256_update_ret(mbedtls_sha256_context* p,const uint8_t* bytes,size_t n){p->bytes.insert(p->bytes.end(),bytes,bytes+n);return 0;}
int mbedtls_sha256_finish_ret(mbedtls_sha256_context* p,uint8_t* out){
  const char* hex=p->bytes==wav?wavHash:p->bytes==pcm?pcmHash:p->bytes==badPcm?badPcmHash:nullptr;
  assert(hex && "Unexpected bytes reached SHA primitive adapter");
  for(unsigned i=0;i<32;++i){unsigned value=0;assert(std::sscanf(hex+2*i,"%2x",&value)==1);out[i]=static_cast<uint8_t>(value);}return 0;
}
void mbedtls_sha256_free(mbedtls_sha256_context*){}
int mbedtls_sha256_ret(const uint8_t* p,size_t n,uint8_t* out,int){mbedtls_sha256_context c;c.bytes.assign(p,p+n);return mbedtls_sha256_finish_ret(&c,out);}
struct WiFiClient {
  bool opened=false,worker=false,holdStop=false,pending=false,connectOk=true;
  unsigned connects=0,stops=0;size_t cursor=0,chunk=3;std::string response,request,body;
  bool connected()const{return opened;}bool running()const{return worker;}
  bool pendingWrites()const{return pending;}void secure(bool){}
  void stop(){++stops;opened=false;if(!holdStop)worker=false;}
  bool connectBlocking(const char*,uint16_t,uint32_t,std::atomic<bool>* cancel){++connects;if(*cancel||!connectOk)return false;opened=worker=true;cursor=0;return true;}
  size_t print(const String& s){request+=s.value;return s.length();}
  size_t write(const uint8_t* p,size_t n){n=min(n,chunk);body.append(reinterpret_cast<const char*>(p),n);return n;}
  int available()const{return opened?static_cast<int>(min(chunk,response.size()-cursor)):0;}
  int read(){return cursor<response.size()?static_cast<unsigned char>(response[cursor++]):-1;}
  size_t read(uint8_t* p,size_t n){n=min(n,min(chunk,response.size()-cursor));memcpy(p,response.data()+cursor,n);cursor+=n;return n;}
};
struct FireReverseTransport {
  uint32_t generation(){return 1;}WiFiClient* acquire(uint32_t){return nullptr;}
  void release(WiFiClient*){}bool cancelled(WiFiClient*){return false;}
};
struct Task {void(*entry)(void*)=nullptr;void* context=nullptr;int core=0;bool suspended=false;};
using TaskHandle_t=Task*;static int currentCore=1;static unsigned created=0,destroyed=0;static TaskHandle_t executing=nullptr;
constexpr int pdPASS=1,eSuspended=3;
int xPortGetCoreID(){return currentCore;}int xTaskGetAffinity(TaskHandle_t h){return h->core;}
int eTaskGetState(TaskHandle_t h){return h->suspended?eSuspended:0;}
int xTaskCreatePinnedToCore(void(*entry)(void*),const char*,unsigned bytes,void* context,unsigned,TaskHandle_t* h,int core){
  assert(bytes==6144);*h=new Task{entry,context,core,false};++created;return pdPASS;
}
void vTaskDelete(TaskHandle_t h){assert(h && h->suspended);++destroyed;delete h;}
struct Parked {};
void vTaskSuspend(void*){assert(executing);executing->suspended=true;throw Parked();}
static void runTask(TaskHandle_t task){executing=task;try{task->entry(task->context);assert(false);}catch(const Parked&){}executing=nullptr;}
namespace FireDataEngineContract {constexpr size_t kHttpChunkBytes=4096;constexpr uint32_t kNetworkJobTimeoutMs=100;}
'''

CLASS = r'''
struct FireBackendClient {
  /*FIELDS*/
  enum class State {Offline,Connected};State state_=State::Connected;
  WiFiClient client_,audioClient_;WiFiClient* transportClient_=nullptr,*audioTransportClient_=nullptr;
  FireReverseTransport* reverseTransport_=nullptr;
  bool secureEndpoint_=true,sessionStarted_=true,usingReverseTransport_=false;
  bool releaseReadBuffersPending_=false;uint8_t fragmentOpcode_=0;
  uint32_t connectionEpoch_=4,reconnectAt_=99,eventCounter_=0;uint8_t selectionReply_=0;
  String bootId_="boot-one",sessionId_="session-one",resumeSessionId_;
  String confirmedProject_="project-one",confirmedBase_="base-one",confirmedMode_="develop";
  String host_="fixture.invalid",token_="test-only-fake-credential",handshakeBuffer_,frameBuffer_,fragmentBuffer_;
  uint16_t port_=443;fire_session::Selection<String> selection_;
  fire_backend_policy::SendDisposition lastSendDisposition_=fire_backend_policy::SendDisposition::NotQueued;
  struct Event {String kind,fields,id;};std::vector<Event> events;
  bool sends=true;
  FireBackendClient(){client_.opened=client_.worker=true;}
  bool connected()const{return state_==State::Connected && sessionStarted_;}
  bool sessionReady()const{return connected() && sessionId_.length()>0;}
  bool active()const{return state_!=State::Offline;}
  bool pendingWrites()const{return !usingReverseTransport_ && client_.pendingWrites();}
  bool configured()const{return true;}
  bool selectionPending()const{return selection_.pending();}
  /*BEGIN_SELECTION*/
  bool serialAudioSupported()const{return serialAudioSupported_;}
  const String& confirmedProject()const{return confirmedProject_;}
  const String& confirmedMode()const{return confirmedMode_;}
  const String& confirmedAppMode()const{return confirmedAppMode_;}
  String confirmedAppMode_="new";
  void resetReceiveFrame(){}void releaseReadBuffers(){}
  void setState(State s,const String&){state_=s;}
  bool sendEvent(const String& event,const String& fields=String(),const String& id=String()){
    lastSendDisposition_=sends?fire_backend_policy::SendDisposition::Queued:fire_backend_policy::SendDisposition::NotQueued;
    if(!sessionReady() || !sends) {
      return false;
    }
    events.push_back({event,fields,id});
    return true;
  }
  bool audioTransferActive()const{return audioTransferRunning_ || (serialAudioTransfer_ && audioPhase_!=AudioPhase::Idle);}
  bool audioTransferFinished()const{return (dataTransferActive_ && dataChunkDone_) || (!audioTransferRunning_ && audioTransferFinished_);}
  bool audioTransferOk()const{return audioTransferOk_;}size_t audioTransferLength()const{return audioTransferLength_;}
  bool audioPlaybackStarted(const String&,const String&);bool audioPlaybackFinished(const String&,const String&);
  bool audioPlaybackFailed(const String&,const String&,const String&,const String&,const String&){return false;}
  bool beginAudioUpload(const String&,const uint8_t*,size_t);
  bool beginAudioDownload(const String&,uint8_t*,size_t,const String&,const String&,const String&,uint32_t,bool);
  bool uploadAudio(const String&,const uint8_t*,size_t);bool downloadAudio(const String&,uint8_t*,size_t,size_t&);
  void cancelAudioTransfer();bool listenStop(const String&);String eventId(const char*);
  bool handleAudioMessage(const String&,const String&);void serviceAudioTransfer(bool,bool,bool);
  bool audioNetworkPaused()const;bool audioOtherNetworksPaused()const;bool audioOwnsNetwork()const;
  bool audioOwnsBuffer(const uint8_t*)const;const char* audioStatus()const;void releaseAudioResult();
};
'''

QA_CLASS = r'''
static const String kQaPackage="fixture-package",kQaSource="fixture-source";
struct SpeakerSpy {
  bool playing=false,enabled=true,accept=true;unsigned starts=0;
  bool isPlaying()const{return playing;}bool isEnabled()const{return enabled;}
  void stop(){playing=false;}
  bool playRaw(const int16_t*,size_t samples,unsigned rate,bool,unsigned,unsigned,bool){assert(samples==4 && rate==24000);++starts;playing=accept;return accept;}
};
struct {SpeakerSpy Speaker;} M5;
void* ps_malloc(size_t size){return malloc(size);}
String fireNetworkHost(const String& s){return s;}
bool fireNetworkTls(const String&,uint16_t port){return port==443;}
size_t strlcpy(char* out,const char* in,size_t capacity){const size_t n=strlen(in);if(capacity){const size_t copied=min(n,capacity-1);memcpy(out,in,copied);out[copied]=0;}return n;}
struct FireBackendSettingsUi {enum {None=0};unsigned page=None;};
struct PackageManager {bool active=false;bool busy()const{return active;}};
struct FireOS {
  enum class Screen {Main,Home,Evolution,AppsSettings,AiDeveloper,AiApi,LuaApp,FactoryReset,Power,Firmware,FileExplorer,Settings,QuickSettings,Apps,Help};
  struct LocalQa {bool voiceConsumed=false;char voiceTurn[65]={};fire_local_qa::Snapshot presented;};
  LocalQa qa;LocalQa* localQa_=&qa;FireBackendClient* backendClient_=nullptr;
  Screen screen_=Screen::AiDeveloper;
  String backendHost_="fire-device.ljoekjell.no",wifiSsid_="fixture",luaRunId_,luaPackageId_,luaSourceHash_;
  String aiProjectId_="project-one",aiWorkflowText_="Valg bekreftet",aiTurnId_,aiProposalId_,aiReadyPackageId_,luaRepairReadyPackageId_;
  uint16_t backendPort_=443;unsigned appUpdateStage_=0,appUpdateSelection_=0;
  String appUpdateCandidate_;bool buildNoticeActive_=false;
  bool wifiSetupActive_=false,portalApplying_=false,luaDevelopJob_=false,luaAppActive_=false;
  bool aiProjectPickerActive_=false,aiAudioCaptureActive_=false,aiAudioOutputActive_=false;
  bool aiAudioStopSent_=false,aiVoiceTestMode_=false,aiJobViewing_=false,backgroundBuildActive_=false;
  bool aiConversationCancelPending_=false,aiJobNeedsInstall_=false;
  unsigned aiWorkflowState_=0,mainIndex_=0,settingsIndex_=0,quickIndex_=0,detailIndex_=0;
  unsigned externalAppSelection_=0,externalAppCount_=0,luaAppCount_=0;
  static constexpr unsigned kSystemMainCount=5;
  String luaAppPackageIds_[16],luaAppChecksums_[16];
  bool appManagerDeleteConfirm_=false,appManagerDevelopConfirm_=false,appManagerDeleteWaiting_=false;
  bool appManagerVersionDialog_=false,appManagerActionMenu_=false;
  unsigned appManagerVersionSelection_=0,appManagerVersionCount_=0,appManagerActionIndex_=0;
  String appManagerVersionPackageIds_[8];uint8_t appManagerActionCodes_[8]{};
  struct {String localPackageId,appId;} managerTarget_;
  FireBackendSettingsUi backendSettingsUi_;PackageManager* packageManager_=nullptr;
  fire_ai_menu::Page aiPickerPage_=fire_ai_menu::Page::Main;unsigned aiProjectSelection_=0;
  bool aiJobCanResume_=false,aiJobCanDelete_=false,aiJobCanPause_=false,aiJobCanContext_=false,aiJobCanOpen_=false;
  unsigned luaErrorAction_=0;
  uint32_t inputContext_=7,lastActivity_=0;uint64_t inputShownView_=11;
  String inputShownIdentity_="shown";fire_local_qa::Snapshot current;
  unsigned starts=0,finishes=0,actions=0;bool failStart=false;
  bool aiVoiceTestPlaybackActive_=false,aiAudioCaptureFinished_=false;
  bool aiAudioDownloadPending_=false,aiAudioDownloadStarted_=false,aiAudioDownloadSerial_=true;
  uint8_t* aiAudioOutputBuffer_=nullptr;size_t aiAudioOutputLength_=0,aiAudioDownloadSize_=0;
  String aiAudioDownloadId_,aiAudioDownloadTurnId_,aiAudioDownloadUrl_,aiAudioDownloadHash_;
  String aiAudioOutputId_,aiAudioOutputTurnId_,aiLastAudioId_,aiLastAudioTurnId_;
  uint32_t aiAudioFetchExpires_=0;unsigned aiDeveloperMode_=0,playbackErrors=0;String playbackCode;
  String aiTranscriptText_,aiAssistantText_;bool redrawRequested_=false;
  FireOS(){current.context=7;current.view=11;current.presented=1;memset(current.identity,'a',64);qa.presented=current;}
  uint64_t buttonView()const{return 11;}String buttonViewIdentity()const{return "shown";}
  void localQaSnapshot(fire_local_qa::Snapshot& out){out=current;}
  void onButton(uint8_t button,bool hold){
    ++actions;assert(button==1 && !hold && localQa_->voiceConsumed);
    if(!aiAudioCaptureActive_){++starts;if(!failStart){aiAudioCaptureActive_=true;aiTurnId_="qa-turn-one";aiWorkflowState_=1;}}
    else {++finishes;assert(aiTurnId_==localQa_->voiceTurn);aiAudioStopSent_=true;}
  }
  bool localQaActionAllowed(uint8_t,bool)const;
  static fire_local_qa::Code localQaAct(void*,const fire_local_qa::Command&,fire_local_qa::Snapshot&);
  void updateAiAudioOutput();void audioReady(const String&);
  void completeAiAudioUpload(bool,bool,const String&);
  void restoreVoiceTestRadio(){}String audioDiagnosticsJson(const char*){return "{}";}
  void failAiAudioPlayback(const String&,const String&,const String& code,const String&,const String&,bool release=true){
    ++playbackErrors;playbackCode=code;aiAudioDownloadPending_=aiAudioDownloadStarted_=false;
    if(release){free(aiAudioOutputBuffer_);aiAudioOutputBuffer_=nullptr;}
  }
};
'''

QA_MAIN = r'''
static fire_local_qa::Code qaPress(FireOS& os,uint8_t button=1,uint32_t context=7){
  fire_local_qa::Command cmd;cmd.op=fire_local_qa::Op::Click;cmd.button=button;cmd.context=context;
  auto shown=os.current;return FireOS::localQaAct(&os,cmd,shown);
}
static void qaMatrix(){
  using Code=fire_local_qa::Code;
  for(unsigned fault=0;fault<12;++fault){
    FireBackendClient backend;backend.serialAudioSupported_=true;FireOS os;os.backendClient_=&backend;PackageManager manager;os.packageManager_=&manager;
    if(fault==0)backend.sessionStarted_=false;
    if(fault==1)os.backendHost_="not-public.invalid";
    if(fault==2)backend.confirmedAppMode_="update";
    if(fault==3)backend.confirmedMode_="chat";
    if(fault==4)os.aiProjectId_="unconfirmed";
    if(fault==5)os.aiWorkflowText_="idle";
    if(fault==6)os.aiWorkflowState_=3;
    if(fault==7)os.backgroundBuildActive_=true;
    if(fault==8)manager.active=true;
    if(fault==9)os.aiProposalId_="current-proposal";
    if(fault==10)backend.serialAudioSupported_=false;
    if(fault==11)os.aiJobViewing_=true;
    assert(qaPress(os)==Code::Blocked && !os.actions && !os.localQa_->voiceConsumed);
  }
  FireBackendClient backend;backend.serialAudioSupported_=true;FireOS os;os.backendClient_=&backend;
  assert(qaPress(os,1,6)==Code::Stale && !os.actions && !os.localQa_->voiceConsumed);
  assert(qaPress(os)==Code::Ok && os.starts==1 && os.localQa_->voiceConsumed && os.aiAudioCaptureActive_);
  assert(!strcmp(os.localQa_->voiceTurn,"qa-turn-one"));
  os.aiTurnId_="unrelated";assert(qaPress(os)==Code::Blocked && os.finishes==0);
  os.aiTurnId_="qa-turn-one";assert(qaPress(os)==Code::Ok && os.finishes==1);
  assert(qaPress(os)==Code::Blocked && os.finishes==1);
  os.aiAudioCaptureActive_=false;assert(qaPress(os)==Code::Blocked && os.starts==1);
  FireOS failed;failed.backendClient_=&backend;failed.failStart=true;
  assert(qaPress(failed)==Code::Ok && failed.starts==1 && failed.localQa_->voiceConsumed && !failed.aiAudioCaptureActive_);
  assert(qaPress(failed)==Code::Blocked && failed.starts==1);
  FireOS build;build.backendClient_=&backend;build.aiWorkflowState_=3;build.aiProposalId_="proposal";
  assert(qaPress(build,0)==Code::Blocked && !build.actions);
  puts("PASS extracted actual QA one confirmed-New public voice intent beforehandler finish exactturn no BUILD");
}
static String outputMetadata(const char* turn="turn-one",const char* hash=nullptr,unsigned bytes=8){
  return "{\"audio_id\":\"audio-one\",\"turn_id\":\""+String(turn)+"\",\"download_url\":\"/audio/audio-one\",\"format\":\"pcm_s16le\",\"sha256\":\""+String(hash?hash:pcmHash)+"\",\"sample_rate\":24000,\"channels\":1,\"size_bytes\":"+String(bytes)+",\"serial_audio\":true,\"fetch_expires_at\":1020}";
}
static void outputMatrix(){
  for(unsigned fault=0;fault<4;++fault){
    nowMs=1000;M5.Speaker=SpeakerSpy();FireBackendClient backend;backend.serialAudioSupported_=true;
    FireOS os;os.backendClient_=&backend;os.aiTurnId_="turn-one";
    os.audioReady(outputMetadata("old-turn"));assert(!os.aiAudioDownloadPending_ && !os.playbackErrors);
    os.audioReady(outputMetadata());assert(os.aiAudioDownloadPending_ && os.aiAudioOutputBuffer_);
    uint8_t* const allocation=os.aiAudioOutputBuffer_;os.audioReady(outputMetadata());assert(os.aiAudioOutputBuffer_==allocation && !os.playbackErrors);
    const auto& bytes=fault==1?badPcm:pcm;memcpy(allocation,bytes.data(),bytes.size());
    // Delivery has already passed the actual transport/reap/rejoin matrix.
    backend.audioTransferFinished_=true;backend.audioTransferLength_=fault==2?6:8;
    backend.audioTransferOk_=fault!=3;
    os.aiAudioDownloadStarted_=true;os.updateAiAudioOutput();
    if(fault){assert(os.playbackErrors==1 && !M5.Speaker.starts && backend.events.empty());
      assert(os.playbackCode==(fault==1?"sha256_mismatch":fault==2?"audio_length_mismatch":"http_error"));}
    else {
      assert(M5.Speaker.starts==1 && os.aiAudioOutputActive_ && !os.playbackErrors && backend.events.size()==1);
      assert(backend.events[0].kind=="audio_playback_started" && backend.events[0].fields.indexOf("audio-one")>=0 && backend.events[0].fields.indexOf("turn-one")>=0);
      os.updateAiAudioOutput();assert(backend.events.size()==1);M5.Speaker.playing=false;os.updateAiAudioOutput();
      assert(backend.events.size()==2 && backend.events[1].kind=="audio_playback_finished" && !os.aiAudioOutputBuffer_);
    }
  }
  puts("PASS extracted actual audio_ready immutable scope exact size SHA before playback and correlated receipts");
}
static void completionMatrix(){
  for(unsigned response=0;response<7;++response)for(const bool ok:{false,true}){
    FireOS os;os.aiTurnId_="current-turn";os.aiWorkflowState_=2;os.aiWorkflowText_="SERVER RESPONSE";
    String completed="current-turn";
    if(response==0){os.aiWorkflowState_=3;os.aiProposalId_="actual-proposal";}
    if(response==1)os.aiTranscriptText_="actual transcript";
    if(response==2)os.aiAssistantText_="actual reply";
    if(response==3){os.aiWorkflowState_=0;os.aiWorkflowText_="ACTUAL ERROR";}
    if(response==4)completed="old-turn";
    if(response==5)os.aiProjectPickerActive_=true;
    if(response==6)completed="";
    const String text=os.aiWorkflowText_;const unsigned state=os.aiWorkflowState_;
    os.completeAiAudioUpload(ok,true,completed);
    assert(os.aiWorkflowText_==text && os.aiWorkflowState_==state && !os.redrawRequested_);
  }
  for(const bool ok:{false,true})for(const bool uncertain:{false,true}){
    FireOS os;os.aiTurnId_="current-turn";os.aiWorkflowState_=2;os.aiWorkflowText_="SENDING AUDIO";
    os.completeAiAudioUpload(ok,uncertain,"current-turn");
    assert(os.redrawRequested_ && os.aiWorkflowState_==(ok?2:0));
    assert(os.aiWorkflowText_==(ok?"TRANSCRIBING":uncertain?"Talestatus uavklart. Ta nytt opptak":"Opptaket ble ikke sendt. Ta nytt opptak"));
  }
  puts("PASS extracted actual upload completion preserves server response proposal error picker and newer turn");
}
'''

MAIN = r'''
using Phase=FireBackendClient::AudioPhase;
static void bootstrap(FireBackendClient& c){
  c.handleAudioMessage("session_snapshot","{\"features\":[\"serial_audio_v1\"],\"server_time\":1000}");
}
static String ack(const FireBackendClient& c,const char* result,const char* status="accepted",const char* event=nullptr){
  return "{\"session_id\":\""+c.audioSession_+"\",\"event_id\":\""+String(event?event:c.audioEvent_.c_str())+"\",\"status\":\""+status+"\",\"result\":"+result+"}";
}
static const char* deadlines="{\"turn_id\":\"turn-one\",\"serial_audio\":true,\"upload_expires_at\":1025.75,\"commit_expires_at\":1045.75}";
static void stopped(FireBackendClient& c){
  bootstrap(c);assert(c.listenStop("turn-one"));assert(c.events.size()==1);
  assert(c.events.back().kind=="listen_stop" && c.events.back().fields.indexOf("\"serial_audio\":true")>=0);
  assert(c.audioPhase_==Phase::StopAck);
  assert(c.beginAudioUpload("turn-one",wav.data(),wav.size()));
  assert(c.handleAudioMessage("event_ack",ack(c,deadlines)));
  assert(c.audioPhase_==Phase::Queued && !c.audioEvent_.length());
}
static std::string http(const std::string& body,const char* code="202 Accepted"){
  return std::string("HTTP/1.1 ")+code+"\r\nContent-Length: "+std::to_string(body.size())+"\r\nConnection: close\r\n\r\n"+body;
}
static std::string staged(const char* hash=nullptr){return std::string("{\"status\":\"staged\",\"turn_id\":\"turn-one\",\"sha256\":\"")+(hash?hash:wavHash)+"\",\"expires_at\":1045.75}";}
static void startWorker(FireBackendClient& c){
  c.serviceAudioTransfer(true,true,false);assert(c.audioPhase_==Phase::Quiet);
  c.serviceAudioTransfer(true,true,false);assert(c.audioPhase_==Phase::Http && c.audioTask_);
  assert(!c.sessionReady() && c.audioNetworkPaused());
}
static void admitted(FireBackendClient& c){
  c.state_=FireBackendClient::State::Connected;c.sessionStarted_=true;
  c.sessionId_=c.audioSession_;++c.connectionEpoch_;
}
static void newIntentMatrix(){
  for(const Phase phase:{Phase::Resume,Phase::Commit}){
    nowMs=1000;FireBackendClient c;stopped(c);admitted(c);c.audioPhase_=phase;memcpy(c.audioHash_,wavHash,65);
    assert(c.beginSelection() && c.audioTransferCancel_ && c.events.size()==1);
    assert(!c.sendAudioCommit() && c.events.size()==1 && c.lastSendDisposition_==fire_backend_policy::SendDisposition::NotQueued);
  }
  for(const bool unclearOnly:{false,true}){
    nowMs=1000;FireBackendClient c;stopped(c);admitted(c);c.audioPhase_=Phase::Commit;memcpy(c.audioHash_,wavHash,65);
    if(unclearOnly)c.selection_.appUnclear=true;
    else c.selection_.queueApp("new","","","selection-one");
    assert(!c.sendAudioCommit() && !c.audioTransferCancel_ && c.events.size()==1);
    assert(c.lastSendDisposition_==fire_backend_policy::SendDisposition::NotQueued);
  }
  nowMs=1000;FireBackendClient blocked;stopped(blocked);admitted(blocked);blocked.audioPhase_=Phase::Commit;
  blocked.selection_.queueApp("new","","","selection-one");blocked.selection_.appSent=true;
  assert(!blocked.beginSelection() && !blocked.audioTransferCancel_ && blocked.audioPhase_==Phase::Commit);
  assert(!blocked.sendAudioCommit() && blocked.events.size()==1);
  puts("PASS extracted successful new intent immediately revokes commit pending unclear and failed selection do not send");
}
static void uploadMatrix(){
  nowMs=1000;FireBackendClient c;bootstrap(c);assert(c.listenStop("turn-one"));
  assert(!c.listenStop("turn-two") && !c.beginAudioUpload("wrong",wav.data(),wav.size()));
  assert(c.beginAudioUpload("turn-one",wav.data(),wav.size()));
  for(unsigned i=0;i<3;++i)c.serviceAudioTransfer(true,true,false);
  assert(!c.audioClient_.connects && !c.audioTask_ && c.sessionReady());
  assert(!c.handleAudioMessage("event_ack",ack(c,deadlines,"accepted","unrelated")));
  assert(c.audioPhase_==Phase::StopAck);
  const String stopAck=ack(c,deadlines);assert(c.handleAudioMessage("event_ack",stopAck));
  assert(!c.handleAudioMessage("event_ack",stopAck)); // consumed stop receipt does not queue twice
  c.serviceAudioTransfer(true,true,true);assert(c.audioPhase_==Phase::Queued && !c.audioTask_);
  c.serviceAudioTransfer(true,true,false);assert(c.audioPhase_==Phase::Quiet);
  c.client_.pending=true;c.serviceAudioTransfer(true,true,false);assert(c.sessionReady() && !c.audioTask_);
  c.client_.pending=false;c.client_.holdStop=true;
  c.serviceAudioTransfer(true,true,false);assert(!c.sessionReady() && c.client_.running() && !c.audioTask_);
  c.client_.worker=false;c.serviceAudioTransfer(true,false,false);assert(!c.audioTask_);
  c.audioClient_.response=http(staged());c.serviceAudioTransfer(true,true,false);assert(c.audioPhase_==Phase::Http);
  const auto frozenHost=c.audioHost_;c.host_="changed.invalid";c.token_="changed";c.port_=80;
  runTask(c.audioTask_);assert(c.audioWorkerFinished_ && c.audioTransferRunning_ && c.audioTask_->suspended);
  assert(c.audioTransferOk_ && c.audioClient_.connects==1);
  assert(c.audioClient_.request.find("POST /sessions/session-one/audio/turn-one HTTP/1.1\r\n")!=std::string::npos);
  assert(c.audioClient_.request.find("Host: "+frozenHost.value+":443\r\n")!=std::string::npos);
  assert(c.audioClient_.request.find("Bearer test-only-fake-credential\r\n")!=std::string::npos);
  assert(c.audioClient_.body==std::string(reinterpret_cast<const char*>(wav.data()),wav.size()));
  assert(c.audioOwnsBuffer(wav.data()) && c.events.size()==1);
  currentCore=0;c.serviceAudioTransfer(true,true,false);assert(c.audioTask_ && c.audioPhase_==Phase::Http);
  currentCore=1;c.audioClient_.worker=true;c.serviceAudioTransfer(true,true,false);
  assert(!c.audioTask_ && c.audioPhase_==Phase::Cleanup && c.audioNetworkPaused());
  c.serviceAudioTransfer(true,true,false);assert(c.audioPhase_==Phase::Cleanup);
  c.audioClient_.worker=false;c.serviceAudioTransfer(true,true,false);assert(c.audioPhase_==Phase::Resume && !c.audioNetworkPaused());
  assert(c.audioOtherNetworksPaused());c.serviceAudioTransfer(true,true,false);assert(c.events.size()==1);
  c.state_=FireBackendClient::State::Connected;c.sessionStarted_=true;c.sessionId_=c.audioSession_;
  c.serviceAudioTransfer(true,true,false);assert(c.audioPhase_==Phase::Resume); // same epoch is not new admission
  admitted(c);c.serviceAudioTransfer(true,true,false);assert(c.audioPhase_==Phase::Commit && c.events.size()==1);
  nowMs+=249;c.serviceAudioTransfer(true,true,false);assert(c.events.size()==1);
  ++nowMs;c.serviceAudioTransfer(true,true,false);assert(c.events.size()==2 && c.events.back().kind=="audio_input_commit");
  const String stable=c.audioEvent_;assert(stable.length() && c.events.back().fields.indexOf(wavHash)>=0);
  for(unsigned i=0;i<5;++i) {
    c.serviceAudioTransfer(true,true,false);
  }
  assert(c.events.size()==2 && c.audioEvent_==stable);
  const String result="{\"turn_id\":\"turn-one\",\"status\":\"queued\",\"sha256\":\""+String(wavHash)+"\"}";
  const String commitAck=ack(c,result.c_str(),"duplicate");
  assert(c.handleAudioMessage("event_ack",commitAck) && c.audioPhase_==Phase::Finished && c.audioTransferOk_);
  assert(c.handleAudioMessage("event_ack",commitAck) && c.audioPhase_==Phase::Finished && c.audioTransferOk_ && !c.audioTransferCancel_);
  c.releaseAudioResult();assert(c.audioPhase_==Phase::Idle && !c.audioTransferActive() && !c.audioTransferUploadData_);
  puts("PASS extracted serial upload StopACK quiet actual202 worker reap exact admission stable commit");
}
static void negativeMatrix(){
  for(unsigned fault=0;fault<10;++fault){
    nowMs=1000;FireBackendClient c;bootstrap(c);assert(c.listenStop("turn-one"));
    String result=deadlines;
    if(fault==0)result="{\"turn_id\":\"wrong\",\"serial_audio\":true,\"upload_expires_at\":1025,\"commit_expires_at\":1045}";
    if(fault==1)result="{\"turn_id\":\"turn-one\",\"serial_audio\":false,\"upload_expires_at\":1025,\"commit_expires_at\":1045}";
    if(fault==2)result="{\"turn_id\":\"turn-one\",\"serial_audio\":true,\"upload_expires_at\":1000,\"commit_expires_at\":1045}";
    if(fault==3)result="{\"turn_id\":\"turn-one\",\"serial_audio\":true,\"upload_expires_at\":1027,\"commit_expires_at\":1045}";
    if(fault==4)result="{\"turn_id\":\"turn-one\",\"serial_audio\":true,\"upload_expires_at\":1025,\"commit_expires_at\":1047}";
    if(fault<5){assert(c.handleAudioMessage("event_ack",ack(c,result.c_str())));}
    else {assert(c.handleAudioMessage("event_ack",ack(c,deadlines)));if(fault==5)c.bootId_="boot-two";if(fault==6)c.confirmedProject_="other";if(fault==7)c.confirmedBase_="other";if(fault==8)c.confirmedMode_="chat";if(fault==9)nowMs+=45000;c.serviceAudioTransfer(true,true,false);}
    assert(c.audioTransferCancel_ && !c.audioClient_.connects && c.events.size()==1);
    c.releaseAudioResult();
  }
  for(const uint32_t start:{uint32_t(0),uint32_t(UINT32_MAX-100u)}){
    nowMs=start;FireBackendClient c;bootstrap(c);assert(c.listenStop("turn-one"));
    nowMs=uint32_t(start+4999);c.serviceAudioTransfer(true,true,false);assert(c.audioPhase_==Phase::StopAck);
    nowMs=uint32_t(start+5000);c.serviceAudioTransfer(true,true,false);assert(c.audioPhase_==Phase::Finished && !c.audioTransferOk_);
  }
  nowMs=1000;FireBackendClient cancelled;stopped(cancelled);startWorker(cancelled);
  cancelled.cancelAudioTransfer();assert(cancelled.audioTransferCancel_ && cancelled.audioOwnsBuffer(wav.data()));
  cancelled.serviceAudioTransfer(true,true,false);cancelled.releaseAudioResult();
  assert(cancelled.audioTask_ && cancelled.audioTransferUploadData_==wav.data() && cancelled.audioNetworkPaused());
  runTask(cancelled.audioTask_);cancelled.serviceAudioTransfer(true,true,false);
  assert(!cancelled.audioTask_ && cancelled.audioPhase_==Phase::Resume && cancelled.events.size()==1);
  admitted(cancelled);cancelled.serviceAudioTransfer(true,true,false);assert(cancelled.audioPhase_==Phase::Finished && !cancelled.audioTransferOk_);
  cancelled.releaseAudioResult();assert(!cancelled.audioTransferUploadData_ && cancelled.events.size()==1);
  puts("PASS extracted wrongscope deadline wrap unrelated duplicate and cancel retained-buffer no recommit");
}
static void httpNegativeMatrix(){
  for(unsigned fault=0;fault<5;++fault){
    nowMs=1000;FireBackendClient c;stopped(c);
    std::string response=http(staged());
    if(fault==0)response=http(staged(),"200 OK");
    if(fault==1)response=http(staged(pcmHash));
    if(fault==2)response=http("{\"status\":\"staged\",\"turn_id\":\"wrong\"}");
    if(fault==3)response="HTTP/1.1 202 Accepted\r\nContent-Length: 10\r\nTransfer-Encoding: chunked\r\n\r\n0123456789";
    if(fault==4)response="HTTP/1.1 202 Accepted\r\nContent-Length: 513\r\n\r\n"+std::string(513,'x');
    c.audioClient_.response=response;startWorker(c);runTask(c.audioTask_);assert(!c.audioTransferOk_);
    c.cancelAudioTransfer();c.serviceAudioTransfer(false,true,false);c.releaseAudioResult();assert(!c.audioTask_);
  }
  puts("PASS extracted actual HTTP staged status hash turn size and encoding rejection");
}
static void downloadMatrix(){
  for(unsigned fault=0;fault<5;++fault){
    nowMs=1000;FireBackendClient c;bootstrap(c);uint8_t out[32]{};
    const String hash=pcmHash;
    assert(!c.beginAudioDownload("https://elsewhere.invalid/a",out,sizeof(out),"audio-one","turn-one",hash,1020,true));
    assert(!c.beginAudioDownload("/audio/audio-one",out,sizeof(out),"audio-one","turn-one",hash,1000,true));
    assert(c.beginAudioDownload("/audio/audio-one",out,sizeof(out),"audio-one","turn-one",hash,1020,true));
    const auto& data=fault==1?badPcm:pcm;
    c.audioClient_.response=http(std::string(reinterpret_cast<const char*>(data.data()),data.size()),fault==2?"202 Accepted":"200 OK");
    if(fault==3)c.audioClient_.response="HTTP/1.1 200 OK\r\nContent-Length: 33\r\n\r\n"+std::string(33,'x');
    if(fault==4)c.audioClient_.response="HTTP/1.1 200 OK\r\nContent-Length: 7\r\n\r\n1234567";
    startWorker(c);runTask(c.audioTask_);
    assert(bool(c.audioTransferOk_)==(fault<2)); // Digest is validated by actual OS before playback.
    c.serviceAudioTransfer(true,true,false);assert(c.audioPhase_==Phase::Cleanup);
    c.serviceAudioTransfer(true,true,false);assert(c.audioPhase_==Phase::Resume && c.events.empty());
    admitted(c);c.serviceAudioTransfer(true,true,false);
    assert(c.audioPhase_==Phase::Finished && bool(c.audioTransferOk_)==(fault<2) && c.events.empty());
    if(!fault){assert(c.audioTransferLength_==pcm.size() && !memcmp(out,pcm.data(),pcm.size()));assert(c.audioClient_.request.find("GET /audio/audio-one HTTP/1.1\r\n")!=std::string::npos);}
    c.releaseAudioResult();
  }
  puts("PASS extracted immutable output quiet GET size hash cleanup admission no input commit");
}
int main(){uploadMatrix();negativeMatrix();httpNegativeMatrix();downloadMatrix();assert(created==destroyed);}
'''


class SerialAudioTests(unittest.TestCase):
    def build(self, *, execute):
        compiler = native.host_compiler()
        if compiler is None:
            self.skipTest('No C++ host compiler; no runtime verification claimed')
        prefix = [compiler, 'c++'] if Path(compiler).stem.lower() == 'zig' else [compiler]
        if os.name == 'nt' and Path(compiler).stem.lower() == 'zig':
            prefix += ['-target', 'x86_64-windows-gnu']
        with tempfile.TemporaryDirectory(prefix='fire-serial-audio-') as directory:
            directory = Path(directory)
            path = directory / 'serial_audio.cpp'
            path.write_text(source(), encoding='utf-8')
            output = directory / ('serial_audio' if execute else 'serial_audio.o')
            command = prefix + ['-std=c++17', '-O2', '-UNDEBUG', '-Wall', '-Wextra',
                                '-Werror', '-pedantic', '-I', str(ROOT / 'src')]
            if not execute:
                command += ['-c']
            built = subprocess.run(command + [str(path), '-o', str(output)], capture_output=True,
                                   text=True, timeout=180)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            self.assertTrue(output.is_file())
            if execute:
                result = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

    def test_actual_serial_audio_compiles_strictly(self):
        self.build(execute=False)

    @unittest.skipIf(os.name == 'nt', 'Windows policy4551: compile only; execute actual assertions on Linux CI')
    def test_actual_serial_audio_executes(self):
        result = self.build(execute=True)
        for marker in ('PASS extracted serial upload', 'PASS extracted wrongscope',
                       'PASS extracted actual HTTP', 'PASS extracted immutable output',
                       'PASS extracted actual QA', 'PASS extracted actual audio_ready',
                       'PASS extracted actual upload completion', 'PASS extracted successful new intent'):
            self.assertIn(marker, result)


if __name__ == '__main__':
    unittest.main()
