"""Execute extracted production intent/receipt handlers with bounded host I/O spies.

The adapters model ACK fields and clocks, not ESP32/TLS/SD performance. The
physical UART suite uses the same handlers on the signed production image.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_native_guards as native

ROOT=native.ROOT

def source():
    os_source=(ROOT/'src/fire_os.cpp').read_text(encoding='utf-8')
    def method(name):
        begin=os_source.index(name)
        return os_source[begin:os_source.index('\n}\n',begin)+3]
    methods='\n'.join(method(n) for n in (
        'void FireOS::finishPackageReceipt(', 'void FireOS::cancelLuaRepair(',
        'bool FireOS::managerTargetCurrent(', 'void FireOS::invalidateManagerTarget(', 'bool FireOS::applyBackendDeleteResult('))
    identity=os_source.split('String FireOS::buttonViewIdentity()',1)[1].split('void FireOS::publishButtonView',1)[0]
    manager=identity.split('  if(screen_==Screen::AppsSettings) {',1)[1].split('  if(screen_==Screen::Apps &&',1)[0]
    manager='String FireOS::managerIdentity() const {\n'+manager.rsplit('}',1)[0]+'\n}\n'
    backend=(ROOT/'src/fire_backend_client.cpp').read_text(encoding='utf-8')
    release=backend.split('void FireBackendClient::releaseReadBuffers()',1)[1].split('void FireBackendClient::resetReceiveFrame',1)[0]
    lifetime=backend.split('void FireBackendClient::handleFrame(',1)[1].split('  lastReceiveAt_',1)[0].split('{',1)[1]
    release='void FireBackendClient::releaseReadBuffers()'+release
    lifetime='void FireBackendClient::callbackLifetimeTest() {'+lifetime+"\n releaseReadBuffersPending_=true;releaseReadBuffers();assert(frameBuffer_.length()==8192);\n}\n"
    return PREAMBLE+'\n#include "fire_os_download.inc"\n'+methods+manager+release+lifetime+MAIN

PREAMBLE=r'''
#include <string>
#include <map>
#include <cassert>
#include <cstdio>
#include <sstream>
#include <stdint.h>
#include "fire_app_updates.h"
#include "fire_buttons.h"
#include "fire_backend_policy.h"
#include "fire_package_delivery.h"
constexpr unsigned HEX=16;
class String {
  std::string s;
 public:
  String()=default;String(const char* v):s(v?v:""){} String(std::string v):s(v){}
  String(uint32_t v,unsigned base=10){std::ostringstream out;if(base==16)out<<std::hex;out<<v;s=out.str();}
  size_t capacity()const{return s.capacity();}
  size_t length()const{return s.size();}const char* c_str()const{return s.c_str();}
  String& operator+=(const String& other){s+=other.s;return *this;}
  friend bool operator==(const String&a,const String&b){return a.s==b.s;}
  friend bool operator!=(const String&a,const String&b){return !(a==b);}
  friend String operator+(const String&a,const String&b){return a.s+b.s;}
};
uint32_t nowMs=100,randomNumber=0;
uint32_t millis(){return nowMs;}uint32_t esp_random(){return ++randomNumber;}
// Field adapter: test cases supply the parsed cJSON nodes; no fake wire emitter.
struct cJSON {std::map<std::string,cJSON> fields;String text;int valueint=0;bool number=false;};
bool cJSON_IsNumber(const cJSON* p){return p && p->number;}
cJSON reply;
cJSON* cJSON_Parse(const char*){return &reply;}
const cJSON* cJSON_GetObjectItemCaseSensitive(const cJSON* p,const char* key){if(!p)return nullptr;auto it=p->fields.find(key);return it==p->fields.end()?nullptr:&it->second;}
void cJSON_Delete(cJSON*){}
String aiJobText(const cJSON* p,const char* key){const auto* v=cJSON_GetObjectItemCaseSensitive(p,key);return v?v->text:String();}
String jsonStringField(const String&,const char* key){return aiJobText(&reply,key);}
struct Backend {
  bool ready=true,send=true;unsigned downloads=0,runs=0;
  String sid="session-one",boot="boot-one",project,package,app,event;
  uint32_t connectionEpoch(){return 111;}
  bool sessionReady(){return ready;}const String& sessionId(){return sid;}const String& bootId(){return boot;}
  bool appDownload(const String&p,const String&k,const String&a,const String&e){++downloads;project=p;package=k;app=a;event=e;return send;}
  bool confirmRun(const String& k){++runs;package=k;return true;}
};
struct Package {
  bool active=false,receipt=true,ok=true,cancelled=false;
  String package="package-one",message="installed";
  bool busy(){return active;}const String& packageId(){return package;}
  void cancel(){cancelled=true;}bool receiptReady(){return receipt;}
  bool outcomeOk(){return ok;}const String& outcomeMessage(){return message;}
  void finishReceipt(){receipt=active=false;}
};
struct FireOS {
  enum class Screen {Main,AppsSettings};Screen screen_=Screen::Main;
  Backend* backendClient_=nullptr;Package* packageManager_=nullptr;
  String downloadRequest_,downloadProject_,downloadApp_,downloadPackage_,downloadSession_,downloadBoot_;
  uint32_t downloadRequestedAt_=0;uint8_t downloadPhase_=0;
  String luaFeedbackAck_,luaDevelopContext_,luaFeedbackOutcome_;bool luaFeedbackConfirmation_=false;
  String userRunAfterInstall_,managerStatus_,luaRepairMessage_,luaRepairReadyPackageId_,luaRepairStatus_,luaRepairPhase_;
  String aiReadyPackageId_,aiPackageId_,aiWorkflowText_,luaAiBindPackageId_;
  bool redrawRequested_=false,appUpdateReady_=false,aiJobNeedsInstall_=false,luaAiBindSent_=false;
  String appUpdateCandidate_,appUpdateRequest_;uint8_t appUpdateStage_=0,appUpdateFailure_=0,appUpdateSelection_=0,aiWorkflowState_=0,luaErrorAction_=0;
  bool repairCancelSupported_=true,luaRepairRequested_=false,luaRepairPrepareSent_=false,luaRepairBuildConfirmed_=false,luaRepairConfirmPending_=false,luaRepairCancelPending_=false;
  String luaRepairId_;unsigned inventories=0,homes=0;
  struct ManagerItem {String appId,localPath,localPackageId,projectId,packageId;uint8_t kind=1;};
  ManagerItem managerTarget_,managerItems_[2];uint8_t managerItemCount_=0,managerSelection_=0;
  String appManagerVersionPackageIds_[8];uint8_t appManagerVersionSelection_=0,appManagerVersionCount_=0;
  String managerIdentity()const;
  bool managerTargetValid_=false,appManagerActionMenu_=false,appManagerDeleteConfirm_=false,appManagerDeleteWaiting_=false;
  uint8_t appManagerDeleteMode_=0,appManagerDevelopConfirm_=0;
  bool appManagerVersionDialog_=false,appManagerVersionsWaiting_=false;
  String appManagerRequest_,appManagerDeleteRequest_,appManagerDeleteId_;uint32_t appManagerRequestEpoch_=111;
  struct BackendAppInfo {String appId;};BackendAppInfo backendApps_[2];uint8_t backendAppCount_=0;
  bool backendCatalogLoading_=false;String backendCatalogRequest_;
  void rebuildAppManagerItems(){}void invalidateBackendCatalog(){}
  bool applyBackendDeleteResult(const cJSON*);
  void sendAppInventory(){++inventories;}void goToBootApp(){++homes;}
  const char* packageTransferLabel()const;
  void downloadIntentStatus(const String&);bool requestAppDownload(const String&,const String&,const String&,bool runAfter=false);
  void cancelAppDownload();void serviceDownloadIntent();bool handleDownloadIntent(const String&);bool handleFeedbackAck(const String&);
  void finishPackageReceipt(bool);void cancelLuaRepair();bool managerTargetCurrent()const;void invalidateManagerTarget();
};
struct FireBackendClient {
  bool receiveCallbackActive_=false,releaseReadBuffersPending_=false;
  String handshakeBuffer_,frameBuffer_,fragmentBuffer_;
  void releaseReadBuffers();void callbackLifetimeTest();
};
'''

MAIN=r'''
static void ack(const String& id,const char* outer,const char* status,bool error=false){
  reply=cJSON();reply.fields["type"].text="event_ack";reply.fields["event_id"].text=id;
  reply.fields["status"].text=outer;reply.fields["result"].fields["status"].text=status;
  if(error)reply.fields["result"].fields["error"].text="rejected";
}
int main(){
  Backend b;Package p;FireOS os;os.backendClient_=&b;os.packageManager_=&p;
  os.luaRepairReadyPackageId_="package-one";
  assert(os.requestAppDownload("project-one","package-one","app-one",true));
  const String id=os.downloadRequest_;assert(b.downloads==1 && b.event==id && os.userRunAfterInstall_=="package-one");
  ack("unrelated","accepted","awaiting_device_install");assert(!os.handleDownloadIntent("fields"));
  ack(id,"accepted","awaiting_device_install");assert(os.handleDownloadIntent("fields") && os.downloadPhase_==1 && b.downloads==1);
  // Exact production C handler revokes RUN before asynchronous transfer cancellation.
  os.downloadPhase_=2;p.active=true;os.cancelLuaRepair();assert(p.cancelled && !os.userRunAfterInstall_.length());
  p.receipt=true;p.ok=true;os.finishPackageReceipt(true);assert(b.runs==0 && os.inventories==1);
  // Late ACK of a cancelled offer cannot revive it or automatically retry.
  ack(id,"duplicate","awaiting_device_install");assert(os.handleDownloadIntent("fields") && os.downloadPhase_==3 && b.downloads==1);
  assert(os.requestAppDownload("project-one","package-one","app-one",true));
  ack(os.downloadRequest_,"accepted","rejected",true);assert(os.handleDownloadIntent("fields"));
  assert(os.downloadPhase_==3 && !os.userRunAfterInstall_.length() && b.runs==0);
  // Missing offer has a wrap-safe deadline; no replay on timeout/reconnect.
  nowMs=UINT32_MAX-100;assert(os.requestAppDownload("project-one","package-one","app-one",true));
  nowMs=14900;os.serviceDownloadIntent();assert(os.downloadPhase_==3 && !os.userRunAfterInstall_.length());
  assert(os.requestAppDownload("project-one","package-one","app-one",true));b.sid="session-two";
  os.serviceDownloadIntent();assert(os.downloadPhase_==3 && !os.userRunAfterInstall_.length());
  // Explicit original RUN succeeds only after the matching recorded successful receipt.
  assert(os.requestAppDownload("project-one","package-one","app-one",true));os.downloadPhase_=2;p.receipt=true;p.ok=true;
  os.finishPackageReceipt(true);assert(b.runs==1);
  assert(os.requestAppDownload("project-one","package-one","app-one",true));os.downloadPhase_=2;p.receipt=true;
  os.finishPackageReceipt(false);assert(b.runs==1);
  assert(os.requestAppDownload("project-one","package-one","app-one",false));os.downloadPhase_=2;p.receipt=true;
  os.finishPackageReceipt(true);assert(b.runs==1); // Download-only is not RUN approval.
  // Exact feedback ACKs unblock handoff; rejected/error/wrong context keep confirmation.
  os.luaDevelopContext_="context-one";os.luaFeedbackOutcome_="confirm";os.luaFeedbackConfirmation_=true;
  os.luaFeedbackAck_="obs-context-one-confirm";ack(os.luaFeedbackAck_,"duplicate","recorded");
  reply.fields["result"].fields["context_id"].text="context-one";reply.fields["result"].fields["observation_action"].text="confirm";
  assert(os.handleFeedbackAck("fields") && !os.luaFeedbackConfirmation_);
  os.luaFeedbackAck_="obs-context-one-confirm";os.luaFeedbackOutcome_="confirm";ack(os.luaFeedbackAck_,"duplicate","recorded",true);
  assert(os.handleFeedbackAck("fields") && os.luaFeedbackConfirmation_ && !os.luaFeedbackAck_.length());
  os.luaFeedbackAck_="obs-context-one-confirm";os.luaFeedbackOutcome_="confirm";ack(os.luaFeedbackAck_,"accepted","recorded");
  reply.fields["type"].text="error";assert(os.handleFeedbackAck("fields") && os.luaFeedbackConfirmation_);
  // A scan reorder keeps the exact frozen target; replacement/package change does not.
  os.managerTargetValid_=true;os.managerTarget_.appId="app-a";os.managerTarget_.localPath="/apps/a/main.lua";
  os.managerTarget_.localPackageId="package-one";os.managerTarget_.projectId="project-one";
  os.managerItemCount_=2;os.managerItems_[0].appId="app-b";os.managerItems_[1]=os.managerTarget_;
  assert(os.managerTargetCurrent());os.managerItems_[1].localPackageId="replacement";assert(!os.managerTargetCurrent());
  os.appManagerDeleteConfirm_=os.appManagerActionMenu_=true;os.invalidateManagerTarget();
  assert(!os.appManagerDeleteConfirm_ && !os.appManagerActionMenu_ && !os.managerTargetValid_);
  os.managerTargetValid_=true;os.managerTarget_.appId="app-a";os.managerTarget_.projectId="project-one";
  os.appManagerDeleteId_="delete-a";os.backendAppCount_=2;os.backendApps_[0].appId="app-a";os.backendApps_[1].appId="app-b";
  cJSON deleted;deleted.fields["status"].text="deleted";deleted.fields["delete_id"].text="delete-a";
  deleted.fields["app_id"].text="app-b";deleted.fields["project_id"].text="project-one";
  deleted.fields["remaining_versions"].number=true;deleted.fields["remaining_versions"].valueint=0;
  assert(!os.applyBackendDeleteResult(&deleted) && os.backendAppCount_==2);
  deleted.fields["app_id"].text="app-a";assert(os.applyBackendDeleteResult(&deleted) && os.backendAppCount_==1);
  assert(os.backendApps_[0].appId=="app-b" && !os.applyBackendDeleteResult(&deleted));
  // Exact production deferral + destructor guard keep borrowed bytes alive through callback.
  FireBackendClient buffers;buffers.handshakeBuffer_=String(std::string(4096,'h'));
  buffers.frameBuffer_=String(std::string(8192,'p'));buffers.fragmentBuffer_=String(std::string(1024,'f'));
  assert(buffers.frameBuffer_.capacity()>=8192);
  buffers.callbackLifetimeTest();
  assert(!buffers.receiveCallbackActive_ && !buffers.releaseReadBuffersPending_);
  assert(!buffers.frameBuffer_.length() && buffers.frameBuffer_.capacity()<8192 && !buffers.handshakeBuffer_.length());
  // Actual identity branch: Actions A -> Back -> replacement at SAME row before paint.
  os.managerTargetValid_=true;os.managerTarget_.appId="app-a";os.managerItems_[0]=os.managerTarget_;
  os.managerItemCount_=1;os.managerSelection_=0;os.appManagerActionMenu_=true;
  const String modal=os.managerIdentity();os.appManagerActionMenu_=false;
  const String painted=os.managerIdentity();assert(painted==modal);
  os.managerItems_[0].appId="app-x";const String upcoming=os.managerIdentity();assert(upcoming!=painted);
  fire_buttons::Event tap;tap.kind=fire_buttons::Kind::Click;tap.context=42;
  const uint64_t sameRowView=11;
  assert(!fire_buttons::visibleClick(tap,42,sameRowView,sameRowView,upcoming==painted));
  assert(!fire_buttons::visibleClick(tap,43,sameRowView,sameRowView,true)); // old B cannot approve a newly shown row
  tap.context=43;assert(fire_buttons::visibleClick(tap,43,sameRowView,sameRowView,true));
  puts("PASS production download intent cancel receipt no paid replay and exact manager target");
}
'''

class ProductionAppFlowTests(unittest.TestCase):
    def test_actual_handlers(self):
        compiler=native.host_compiler()
        if compiler is None:self.skipTest('No host C++ compiler')
        prefix=[compiler,'c++'] if Path(compiler).stem.lower()=='zig' else [compiler]
        if os.name=='nt' and Path(compiler).stem.lower()=='zig':prefix+=['-target','x86_64-windows-gnu']
        with tempfile.TemporaryDirectory(prefix='fire-production-intent-') as tmp:
            path=Path(tmp)/'handlers.cpp';path.write_text(source(),encoding='utf-8')
            binary=Path(tmp)/('handlers.exe' if os.name=='nt' else 'handlers')
            result=subprocess.run(prefix+['-std=c++17','-UNDEBUG','-Wall','-Wextra','-Werror','-pedantic','-I',str(ROOT/'src'),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=180)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn('PASS production download intent',run.stdout)

    def test_actual_ack_dispatch_and_presented_qa_boundary(self):
        source=(ROOT/'src/fire_os.cpp').read_text(encoding='utf-8')
        dispatch=source.split('void FireOS::handleBackendMessage(',1)[1]
        self.assertLess(dispatch.index('handleDownloadIntent(message)'),dispatch.index('handleBackgroundBuildMessage(message)'))
        group=dispatch.split('if (type == "build_progress"',1)[1].split('handleBackgroundBuildMessage(message)',1)[0]
        self.assertNotIn('type == "event_ack"',group)
        self.assertIn('result,"status"',source)
        view=source.split('uint64_t FireOS::buttonView()',1)[1].split('String FireOS::buttonViewIdentity',1)[0]
        self.assertIn('uint64_t(row)<<40',view)
        for member in ('mainIndex_','externalAppSelection_','settingsIndex_','quickIndex_','appManagerActionIndex_','aiProjectSelection_','evolutionUi_.selection'):
            self.assertIn(member,view)
        self.assertIn('localQaAttempted_=true', (ROOT/'src/fire_os_local_qa.inc').read_text(encoding='utf-8'))
        qa=(ROOT/'src/fire_os_local_qa.inc').read_text(encoding='utf-8')
        for forbidden in ('setInsecure(', 'NVS', 'preferences.', 'appDownload(', 'confirmRun(', 'confirmBuild('):
            self.assertNotIn(forbidden,qa)
        self.assertIn('Serial.availableForWrite()',qa)
        self.assertIn('q.policy.tick(millis())',qa)
        self.assertIn('os->onButton(command.button,hold)',qa)
        self.assertIn('MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT',qa)
        self.assertIn('!fire_local_qa::equal(current.identity,out.identity,64)',qa)

if __name__=='__main__':unittest.main()
