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
    lifetime=backend.split('void FireBackendClient::handleFrame(',1)[1].split('  const auto* data=',1)[0].split('{',1)[1]
    release='void FireBackendClient::releaseReadBuffers()'+release
    lifetime='void FireBackendClient::callbackLifetimeTest() {'+lifetime+"\n releaseReadBuffersPending_=true;releaseReadBuffers();assert(frameBuffer_.length()==8192);\n}\n"
    picker=(ROOT/'src/fire_os_ai_picker.inc').read_text(encoding='utf-8')
    def block(text,marker):
        at=text.index(marker);start=text.index('{',at);depth=1;end=start+1
        while depth:
            if text[end]=='{':depth+=1
            elif text[end]=='}':depth-=1
            end+=1
        return text[at:end]
    update=picker.split('void FireOS::handleAppUpdateButton',1)[1]
    ui='void FireOS::updateRunButton(uint8_t index){const auto action=fire_app_updates::confirm(appUpdateStage_,appUpdateSelection_,appUpdateReady_);'+block(update,'if(appUpdateStage_==3)')+'}\n'
    error=os_source.split('void FireOS::handleLuaErrorButton(',1)[1]
    ui+='void FireOS::readOnlyBack(uint8_t index){'+block(error,'if(aiJobViewing_ && index==2)')+block(error,'if(aiJobViewing_ && index==1')+'}\n'
    for signature in ('void FireOS::failAiJobOpen(','void FireOS::serviceAiJobOpen('):
        at=picker.index(signature);ui+=picker[at:picker.index('\n}\n',at)+3]
    ui+='void FireOS::jobAck(const String& message){const String type=jsonStringField(message,"type");'+block(os_source.split('void FireOS::handleBackendMessage(',1)[1],'if(aiJobViewing_ && aiJobOpenPending_ && aiJobOpenRequest_.length()')+'}\n'
    repair=os_source.split('void FireOS::handleLuaRepairStatus(',1)[1].split('  if (incomingApp.length())',1)[0]
    ui+='bool FireOS::repairGate(const String& message) {'+repair.split('{',1)[1].replace('return;','return false;')+'return opened;}\n'
    draw_at=os_source.index('    const auto repairPanel=')
    draw=os_source[draw_at:os_source.index('    String appLabel',draw_at)]
    action_at=os_source.index('    drawText(160, 185, repairPanel.action,',draw_at)
    draw+=os_source[action_at:os_source.index('FireUI::Selected);',action_at)+len('FireUI::Selected);')]
    ui+='void FireOS::repairDraw(){'+draw+'}\n'
    qa=(ROOT/'src/fire_os_local_qa.inc').read_text(encoding='utf-8')
    qa_case=qa.split('    case Screen::LuaApp:',1)[1].split('    case Screen::QuickSettings:',1)[0]
    ui+='void FireOS::repairQa(){struct {unsigned count=0;bool error=false;}out;String label,detail;switch(screen_){case Screen::LuaApp:'+qa_case+'default:return;}qaLabel=label;qaError=out.error;qaCount=out.count;}\n'
    return PREAMBLE+'\n#include "fire_os_download.inc"\n'+methods+manager+release+lifetime+ui+MAIN

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
#include "fire_ai_menu.h"
constexpr unsigned HEX=16;
constexpr uint16_t kOrange=1,kCyan=2,kBg=3,kText=4;
namespace FireUI {constexpr uint16_t Selected=5;}
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
  uint32_t epoch=111;
  String sid="session-one",boot="boot-one",project,package,app,event;
  uint32_t connectionEpoch(){return epoch;}
  bool sessionReady(){return ready;}const String& sessionId(){return sid;}const String& bootId(){return boot;}
  bool appDownload(const String&p,const String&k,const String&a,const String&e){++downloads;project=p;package=k;app=a;event=e;return send;}
  bool confirmRun(const String& k){++runs;package=k;return send;}
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
  enum class Screen {Main,AppsSettings,AiDeveloper,LuaApp};Screen screen_=Screen::Main;
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
  bool aiJobViewing_=false;
  bool luaAppActive_=false,qaError=false;unsigned qaCount=0;
  String drawnTitle,drawnAction,qaLabel;
  void drawText(int,int y,const char* text,uint16_t,unsigned,uint16_t){if(y==28)drawnTitle=text;if(y==185)drawnAction=text;}
  void repairDraw();void repairQa();
  bool aiJobOpenPending_=false,luaRepairStatusQueryPending_=false,aiProjectPickerActive_=false;
  fire_ai_menu::Page aiPickerPage_=fire_ai_menu::Page::Main;
  String aiJobOpenRequest_,aiJobRepair_,luaRepairAppId_,luaErrorAppId_;
  uint32_t aiJobOpenAt_=0,aiJobOpenEpoch_=111;unsigned opened=0;
  void openAiJob(){++opened;}
  void updateRunButton(uint8_t);void readOnlyBack(uint8_t);void jobAck(const String&);bool repairGate(const String&);
  void failAiJobOpen(const char*);void serviceAiJobOpen();
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
  // The exact post-update handler reports both unsent cases and requires a
  // separate B. C is Back and never consumes a latent Run intent.
  os.appUpdateStage_=3;os.appUpdateSelection_=0;os.appUpdateReady_=true;os.appUpdateCandidate_="verified-new";
  b.ready=false;const unsigned runs=b.runs;os.updateRunButton(1);
  assert(os.appUpdateStage_==3 && os.appUpdateFailure_==3 && b.runs==runs);
  b.ready=true;b.send=false;os.updateRunButton(1);assert(os.appUpdateStage_==3 && os.appUpdateFailure_==4);
  b.send=true;os.updateRunButton(1);assert(os.appUpdateStage_==0 && b.package=="verified-new" && os.managerStatus_=="Starter app");
  os.appUpdateStage_=3;os.appUpdateReady_=true;const unsigned afterRun=b.runs;os.updateRunButton(2);
  assert(os.appUpdateStage_==0 && !os.appUpdateReady_ && b.runs==afterRun);
  // Dropped read-only status is bounded, explicit retry stays a read-only Open,
  // and Back returns to this Job rather than cancelling any repair.
  os.aiJobViewing_=os.aiJobOpenPending_=true;os.aiJobRepair_="repair-a";os.luaRepairId_="repair-a";
  os.luaRepairStatus_="loading";os.aiJobOpenRequest_="read-a";os.aiJobOpenAt_=nowMs;
  nowMs+=10000;os.serviceAiJobOpen();assert(!os.aiJobOpenPending_ && !os.aiJobOpenRequest_.length());
  os.readOnlyBack(1);assert(os.opened==1 && b.runs==afterRun);
  reply=cJSON();reply.fields["repair_id"].text="repair-a";assert(!os.repairGate("late"));
  os.aiJobOpenPending_=true;os.aiJobOpenRequest_="read-b";os.aiJobOpenAt_=nowMs;
  reply.fields["repair_id"].text="repair-b";assert(!os.repairGate("wrong-target") && os.aiJobOpenPending_);
  reply.fields["repair_id"].text="repair-a";b.epoch=112;assert(!os.repairGate("wrong-epoch"));b.epoch=111;
  assert(os.repairGate("current") && !os.aiJobOpenPending_);
  os.aiJobOpenPending_=true;os.aiJobOpenRequest_="read-c";
  ack("unrelated","accepted","recorded",true);os.jobAck("ack");assert(os.aiJobOpenPending_);
  ack("read-c","accepted","recorded",true);os.jobAck("ack");assert(!os.aiJobOpenPending_);
  os.luaRepairCancelPending_=false;os.readOnlyBack(2);
  assert(!os.aiJobViewing_ && os.screen_==FireOS::Screen::AiDeveloper && os.aiPickerPage_==fire_ai_menu::Page::Job && !os.luaRepairCancelPending_);
  // Cancel/error/offer timeout restores ONLY the selected actual READY job.
  os.aiJobViewing_=os.aiJobNeedsInstall_=true;os.aiReadyPackageId_="ready-job";os.aiWorkflowState_=4;
  os.downloadPackage_="other-job";os.cancelAppDownload();assert(os.aiWorkflowState_==4);
  os.downloadPackage_="ready-job";os.downloadPhase_=1;os.userRunAfterInstall_="ready-job";os.cancelAppDownload();
  assert(os.aiWorkflowState_==5 && os.aiJobNeedsInstall_ && !os.userRunAfterInstall_.length());
  os.downloadPhase_=1;os.aiWorkflowState_=4;os.downloadRequest_="reject-ready";
  ack("reject-ready","accepted","rejected");os.handleDownloadIntent("ack");assert(os.aiWorkflowState_==5 && b.runs==afterRun);
  os.downloadPhase_=1;os.aiWorkflowState_=4;os.downloadRequestedAt_=nowMs;nowMs+=15000;os.serviceDownloadIntent();assert(os.aiWorkflowState_==5);
  os.downloadPhase_=2;os.aiWorkflowState_=4;os.cancelAppDownload();assert(os.aiWorkflowState_==4);
  // Actual LCD statements and actual LuaApp QA switch branch share one tiny
  // presentation, with no change to action dispatch/permission guards.
  os.screen_=FireOS::Screen::LuaApp;os.luaAppActive_=false;os.aiJobViewing_=true;
  os.luaRepairStatus_="loading";os.aiJobOpenPending_=true;os.luaErrorAction_=0;os.luaRepairRequested_=false;
  os.repairDraw();os.repairQa();assert(os.drawnTitle=="JOBBSTATUS" && os.drawnAction=="Venter" && os.qaLabel==os.drawnAction && !os.qaError && os.qaCount==1);
  os.aiJobOpenPending_=false;os.repairDraw();os.repairQa();
  assert(os.drawnTitle=="JOBBSTATUS" && os.drawnAction=="Prøv igjen" && os.qaLabel==os.drawnAction && !os.qaError);
  os.luaRepairStatus_="ready";os.luaErrorAction_=1;os.repairDraw();os.repairQa();
  assert(os.drawnTitle=="JOBBSTATUS" && os.drawnAction=="Kjør rettet app" && os.qaLabel==os.drawnAction && !os.qaError);
  os.luaRepairStatus_="building";os.luaErrorAction_=0;os.repairDraw();os.repairQa();
  assert(os.drawnTitle=="JOBBSTATUS" && os.drawnAction=="Fiks feil" && os.qaLabel==os.drawnAction && !os.qaError);
  os.aiJobViewing_=false;os.luaRepairStatus_="failed";os.repairDraw();os.repairQa();
  assert(os.drawnTitle=="APP ERROR" && os.drawnAction=="Fiks feil" && os.qaLabel==os.drawnAction && os.qaError);
  os.luaRepairRequested_=true;os.repairDraw();os.repairQa();assert(os.drawnAction=="Venter" && os.qaLabel==os.drawnAction && os.qaError);
  os.luaAppActive_=true;os.repairQa();assert(!os.qaError && os.qaLabel=="App running");
  puts("PASS actual readonly job LCD QA title action and real fault parity");
  puts("PASS production download intent cancel receipt no paid replay and exact manager target");
}
'''

class ProductionAppFlowTests(unittest.TestCase):
    def test_real_app_start_clears_readonly_view_before_load_errors(self):
        source=(ROOT/'src/fire_os.cpp').read_text(encoding='utf-8').split('bool FireOS::startLuaApp(',1)[1]
        self.assertLess(source.index('aiJobViewing_=aiJobOpenPending_=false'),source.index('if (!luaRuntime_)'))
        self.assertLess(source.index('aiJobViewing_=aiJobOpenPending_=false'),source.index('SD.exists(manifestPath)'))

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
