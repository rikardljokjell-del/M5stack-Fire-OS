"""Actual New app picker, queue, wire producer, receipt and UI adoption.

The shared portable String fixture and bounded I/O spies replace hardware only.
Production methods/branches and Selection policy are extracted, not mirrored.
This proves inert event production/adoption, not live backend or physical UI.
Windows compiles strictly; Linux CI executes the C++ assertions.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import test_native_guards as native
import test_session_transport as transport
import test_run_status as run_status


def method(text, marker):
    start = text.index(marker)
    return text[start:text.index('\n}\n', start) + 3]


def source():
    backend = (native.ROOT / 'src/fire_backend_client.cpp').read_text(encoding='utf-8')
    header = (native.ROOT / 'src/fire_backend_client.h').read_text(encoding='utf-8')
    picker = (native.ROOT / 'src/fire_os_ai_picker.inc').read_text(encoding='utf-8')
    os_source = (native.ROOT / 'src/fire_os.cpp').read_text(encoding='utf-8')
    text = transport.PREAMBLE.split('struct SerialSpy ', 1)[0]
    # Extend only the shared Arduino String adapter for the actual eventId and
    # the unexecuted installed-app branch. No production policy is substituted.
    text = '#include <sstream>\n#include <vector>\nconstexpr unsigned HEX=16;\n' + text
    text = text.replace('  String(const String& s)',
        '  String(uint32_t n,unsigned base=10){std::ostringstream out;if(base==16)out<<std::hex;out<<n;value=out.str();}\n'
        '  String(const String& s)', 1)
    text = text.replace('  long toInt()',
        '  int lastIndexOf(char c)const{auto n=value.rfind(c);return n==std::string::npos?-1:int(n);}\n'
        '  String substring(size_t a,size_t b)const{return value.substr(a,b-a);}\n'
        '  long toInt()', 1)
    accessors = '\n'.join(line for line in header.splitlines() if any(
        line.startswith('  ' + prefix) for prefix in (
            'void setProjectId(', 'bool beginSelection(', 'bool selectionPending(',
            'bool selectionUnclear(', 'bool selectionAppAck(', 'bool selectionModeAck(',
            'bool selectionFailed(', 'const String& confirmedProject(', 'const String& confirmedBase(',
            'const String& confirmedMode(', 'const String& confirmedAppMode(')))
    start = os_source.index('  const bool selectedApp=backendClient_')
    end = os_source.index('  if (type=="app_selected" || type=="conversation_mode") return;', start)
    adoption = os_source[start:os_source.index('\n', end) + 1]
    draw = os_source.split('void FireOS::drawAiDeveloper()', 1)[1]
    start = draw.index('  const bool failedBuildView =')
    failed_condition = draw[start:draw.index(';', start) + 1]
    failed_draw = run_status.block(draw, 'if (failedBuildView)')
    dispatch = os_source.split('void FireOS::handleBackendMessage(', 1)[1]
    proposal = run_status.block(dispatch, 'if (type == "build_proposal")')
    error = run_status.block(dispatch, 'if (type == "error" || type == "app_failed")')
    activity = run_status.block(dispatch, 'if (type == "ui_event")')
    background = os_source.split('void FireOS::handleBackgroundBuildMessage(', 1)[1]
    start = background.index('  const bool buildEvent =')
    end = background.index('  if(buildEvent && !independentNotice && !aiBuildForeground', start)
    background_guard = background[start:end] + run_status.block(background[end:], 'if(buildEvent &&')
    choice_start = draw.index('  if(const char* choice=fire_ai_menu::choiceLabel(')
    lcd_choice = draw[choice_start:draw.index(';', choice_start) + 1]
    qa = (native.ROOT / 'src/fire_os_local_qa.inc').read_text(encoding='utf-8')
    choice_start = qa.index('const char* choice=fire_ai_menu::choiceLabel(')
    qa_choice = qa[choice_start:qa.index(';', choice_start) + 1]
    audio_start = qa.index('const char* audio=audioWorkflowLabel();', choice_start)
    qa_choice += qa[audio_start:qa.index(';', audio_start) + 1]
    choice_start = qa.index('label=aiAudioCaptureActive_', choice_start)
    qa_choice += qa[choice_start:qa.index(';', choice_start) + 1]
    production = '\n'.join(method(backend, name) for name in (
        'String jsonStringField(', 'String FireBackendClient::eventId(', 'void FireBackendClient::setConversationMode(',
        'void FireBackendClient::setAppMode(', 'void FireBackendClient::serviceSelection(',
        'void FireBackendClient::observeSession('))
    production += '\n' + '\n'.join(method(picker, name) for name in (
        'bool FireOS::selectAiProject(', 'void FireOS::handleAiPicker('))
    production += '\n' + method(os_source, 'bool FireOS::aiBuildForeground(')
    return (text + PREAMBLE.replace('/*ACTUAL_ACCESSORS*/', accessors) + production +
            '\nvoid FireOS::adopt(const String& type) {\n' + adoption + '}\n' +
            'void FireOS::drawFailureProbe(){const int cx=160;' + failed_condition + failed_draw + '}\n' +
            'void FireOS::proposalFrame(const String& message){const String type=jsonStringField(message,"type");' + proposal + '}\n' +
            'void FireOS::errorFrame(const String& message){const String type=jsonStringField(message,"type");' + error + '}\n' +
            'void FireOS::uiEventFrame(const String& message){const String type=jsonStringField(message,"type");' + activity + '}\n' +
            'void FireOS::progressGuard(const String& message){const String type=jsonStringField(message,"type"),buildId=jsonStringField(message,"build_id");' + background_guard + '++foregroundProgressAdoptions;}\n' +
            'String FireOS::lcdChoice()const{String workflowLabel=aiWorkflowText_;' + lcd_choice + 'return workflowLabel;}\n' +
            'String FireOS::qaChoice()const{String label;' + qa_choice + 'return label;}\n' + MAIN)


PREAMBLE = r'''
#include "fire_ai_menu.h"
#include "fire_ai_workflow.h"
uint32_t millis(){return 100;}
unsigned installedAppIo=0;
struct Sd {} SD;
namespace fire_lua_install {
  const char* kFilename="identity";
  struct Identity {char app[81]{};char project[97]{};};
  enum class Read {Invalid,Valid};
  Read read(Sd&,const char*,Identity&){++installedAppIo;return Read::Invalid;}
}
struct Preferences {
  String getString(const char*,const String& fallback){++installedAppIo;return fallback;}
  void putBool(const char*,bool){}
} preferences;
String compactPreferenceKey(const String& prefix,const String& key){return prefix+key;}
String compactStatusText(const String& text){return text;} // Formatting adapter; draw decision is actual production.
constexpr int kOrange=1,kMuted=2,kBg=3;
int constrain(int value,int low,int high){return std::min(high,std::max(low,value));}
int buildProgressField(const String&,int fallback){return fallback;} // Parsed progress value is not under test.
bool jsonBoolField(const String&,const char*,bool fallback){return fallback;} // Runtime-policy parsed-field boundary spy.
struct FireBackendClient {
  struct Event {String type,fields,id;};std::vector<Event> events;
  bool ready=true,writeOk=true;unsigned disconnects=0;uint32_t eventCounter_=0;
  unsigned runtimePolicies=0;String runtimeMode;
  bool serialAudioTransfer_=false;unsigned audioCancels=0;
  void cancelAudioTransfer(){++audioCancels;}
  String projectId_="stale-project",bootId_="boot-one",developmentContext_;
  String confirmedProject_="old-project",confirmedBase_="old-base",confirmedMode_="develop",confirmedAppMode_="update";
  fire_session::Selection<String> selection_;uint8_t selectionReply_=0;
  /*ACTUAL_ACCESSORS*/
  bool sessionReady()const{return ready;}
  bool sendEvent(const String& type,const String& fields,const String& id){events.push_back({type,fields,id});return writeOk;}
  void disconnect(){++disconnects;ready=false;}
  String eventId(const char*);void setConversationMode(const String&);
  void setAppMode(const String&,const String& base=String());void serviceSelection();
  void observeSession(const String&,const String&);
  void setRuntimeAiMode(const String& mode,bool publish){assert(!publish);++runtimePolicies;runtimeMode=mode;}
};
struct FireBackendSettingsUi {enum Page {None};Page page=None;};
struct FireOS {
  enum class Screen {AiApi};
  FireBackendClient* backendClient_=nullptr;FireBackendSettingsUi backendSettingsUi_;
  bool redrawRequested_=false,aiVoiceTestMode_=false,aiEvolutionNewPending_=false;
  bool aiProjectPickerActive_=true,aiJobViewing_=false,aiJobOpenPending_=false,aiJobNeedsInstall_=false;
  bool aiRuntimeAuto_=true,aiRuntimeModeAcked_=false,runtimeAiEnabled_=true;
  bool aiAudioCaptureActive_=false,aiAudioStopSent_=false,aiAudioOutputActive_=false,aiAudioDownloadPending_=false;
  const char* audioWorkflowLabel()const{return nullptr;} // No audio in this inert New-choice matrix.
  enum class LuaJobKind {RuntimeAi,Other};
  struct LuaHardwareJob {LuaJobKind kind=LuaJobKind::RuntimeAi;uint8_t state=0;};
  LuaHardwareJob luaJobs_[1];unsigned runtimeCancels=0;
  void cancelLuaRuntimeAi(LuaHardwareJob& job,const char*){++runtimeCancels;job.state=1;}
  uint8_t aiConversationMode_=0,luaAppCount_=0,aiProjectSelection_=2,aiProjectOffset_=0;
  uint8_t aiDeveloperMode_=0,aiWorkflowState_=0;uint32_t aiEvolutionNewAt_=0;
  fire_ai_menu::Page aiPickerPage_=fire_ai_menu::Page::Main;
  fire_ai_menu::Kind aiPickerShownKind_=fire_ai_menu::Kind::NewApp;
  String aiPickerShownId_,aiProjectId_="stale-ui-project",aiBasePackageId_="stale-ui-base";
  String aiProposalProjectId_,aiProposalJobId_,aiProposalAppName_,aiEvolutionGoal_;
  String aiEvolutionGoalProject_,aiDevelopmentContext_,aiProjectName_,aiAssistantText_,aiWorkflowText_;
  bool aiBuildResumePending_=false,aiBuildRetryPending_=false,aiBuildCanResume_=false,aiBuildCanRetry_=false;
  String aiBuildId_,aiBuildProjectId_,aiProposalId_,aiTurnId_,aiBuildErrorCode_,aiBuildErrorStatus_,aiBuildDiagnosticMessage_;
  String aiReadyPackageId_,aiPackageId_,aiInstallId_;
  String aiJobRepair_,aiJobBuild_,aiJobOpenRequest_,luaRunId_,buildPhase_,backgroundBuildId_;bool backgroundBuildActive_=true;
  uint32_t workCompletedAt_=0;int buildProgress_=0;unsigned foregroundProgressAdoptions=0;
  int aiBuildResumeCount_=-1;uint8_t aiBuildProgress_=0;
  uint8_t buildJobCount_=1;String buildJobIds_[1]={"retained-background"};
  std::vector<String> drawn;
  String luaAppPaths_[1],luaAppDisplayNames_[1],luaAppNames_[1],luaAppPackageIds_[1],luaAppIds_[1];
  unsigned unrelatedUi=0;
  unsigned conversationCancels=0;String cancelledTurn,cancelReason;
  void cancelConversationTurn(const String& reason,bool send){assert(!send);++conversationCancels;cancelledTurn=aiTurnId_;cancelReason=reason;aiAudioCaptureActive_=aiAudioOutputActive_=aiAudioDownloadPending_=false;}
  String sdBaseName(const String& value){++installedAppIo;return value;}
  void handleBackendSettingsButton(uint8_t){++unrelatedUi;}void handleAiJobMenu(uint8_t){++unrelatedUi;}
  void back(){++unrelatedUi;}void openAiJobs(){++unrelatedUi;}void scanLuaApps(){++unrelatedUi;}
  void openEvolution(bool){++unrelatedUi;}void requestBackendSettings(const char*){++unrelatedUi;}
  void open(Screen){++unrelatedUi;}
  void drawText(int,int,const String& text,int,int,int){drawn.push_back(text);}
  void drawFailureProbe();
  bool aiBuildForeground(const String&,const String& build=String())const;
  void proposalFrame(const String&);void errorFrame(const String&);void progressGuard(const String&);
  void uiEventFrame(const String&);
  String lcdChoice()const;String qaChoice()const;
  bool selectAiProject(fire_ai_menu::Kind,uint8_t=0);void handleAiPicker(uint8_t);void adopt(const String&);
};
'''


MAIN = r'''
static void chooseNew(FireOS& os) {
  os.aiProjectPickerActive_=true;os.aiPickerPage_=fire_ai_menu::Page::Main;
  os.aiProjectSelection_=2;os.aiPickerShownKind_=fire_ai_menu::Kind::NewApp;
  os.aiPickerShownId_=String();os.handleAiPicker(1); // Actual B and actual selected-kind guard.
}
static void assertOnlyNew(const FireBackendClient& client,unsigned count) {
  assert(client.events.size()==count);
  for(const auto& event:client.events) {
    assert(event.type=="app_select" && event.fields==",\"app_mode\":\"new\"");
    assert(event.id.length()); // No voice, provider, BUILD or RUN event emitted.
  }
  assert(installedAppIo==0);
}
static String selected(const String& id,const char* project,const char* type="app_selected") {
  return String("{\"type\":\"")+type+"\",\"event_id\":\""+id+
    "\",\"project_id\":\""+project+"\",\"base_package_id\":null,\"app_mode\":\"new\",\"conversation_mode\":\"develop\"}";
}
static void deliver(FireOS& os,const String& type,const String& json) {
  os.backendClient_->observeSession(type,json);os.adopt(type);
}
static void activityKeepsChoice(FireOS& os,const String& expected) {
  const char* messages[]={"{\"type\":\"ui_event\",\"state\":\"idle\"}",
    "{\"type\":\"ui_event\",\"state\":\"listening\"}",
    "{\"type\":\"ui_event\",\"activity\":\"\"}"};
  const uint8_t mode=os.aiDeveloperMode_,state=os.aiWorkflowState_;
  for(const char* message:messages) {
    os.uiEventFrame(message);
    assert(os.aiWorkflowText_==expected && os.aiDeveloperMode_==mode && os.aiWorkflowState_==state);
  }
}
static void choiceRevokesOldVoice() {
  for(unsigned old=0;old<4;++old){
    FireBackendClient backend;backend.serialAudioTransfer_=true;FireOS os;os.backendClient_=&backend;
    if(old==0)os.aiTurnId_="older-voice-turn";
    if(old==1)os.aiAudioCaptureActive_=true;
    if(old==2)os.aiAudioOutputActive_=true;
    if(old==3)os.aiAudioDownloadPending_=true;
    assert(os.selectAiProject(fire_ai_menu::Kind::NewApp));
    assert(backend.audioCancels==1 && os.conversationCancels==1 && os.cancelReason=="Velger app");
    if(old==0)assert(os.cancelledTurn=="older-voice-turn"); // Cancel boundary runs BEFORE foreground reset.
    assert(!os.aiTurnId_.length() && backend.events.empty());
  }
  FireBackendClient busy;busy.serialAudioTransfer_=true;busy.selection_.queueApp("new","","","existing-choice");busy.selection_.appSent=true;
  FireOS os;os.backendClient_=&busy;os.aiTurnId_="still-owned-turn";
  assert(!os.selectAiProject(fire_ai_menu::Kind::NewApp));
  assert(!busy.audioCancels && !os.conversationCancels && os.aiTurnId_=="still-owned-turn" && busy.events.empty());
  FireBackendClient sdkData;sdkData.serialAudioTransfer_=false;assert(sdkData.beginSelection() && !sdkData.audioCancels);
  puts("PASS actual new intent revokes serial voice before reset failed begin retains and SDK data unaffected");
}
int main() {
  choiceRevokesOldVoice();
  FireBackendClient client;FireOS os;os.backendClient_=&client;
  os.aiProjectId_="old-project";os.aiBuildProjectId_="old-project";
  os.aiBuildId_="old-failed-build";os.backgroundBuildId_="old-failed-build";os.aiProposalId_="old-proposal";
  os.aiBuildResumeCount_=7;os.aiBuildProgress_=77;
  os.aiBuildResumePending_=os.aiBuildRetryPending_=os.aiBuildCanResume_=os.aiBuildCanRetry_=true;
  os.aiBuildErrorCode_="old-failure";os.aiBuildErrorStatus_="Apphandling feilet";
  os.aiBuildDiagnosticMessage_="old diagnostic";os.drawFailureProbe();
  assert(os.drawn.size()==2 && os.drawn[0]=="Apphandling feilet"); // Exact current draw branch reproduces old view.
  os.drawn.clear();
  chooseNew(os);
  assert(client.selectionPending() && os.aiWorkflowText_=="Venter på appvalg");
  assert(os.lcdChoice()=="Venter på appvalg" && os.qaChoice()==os.lcdChoice());
  activityKeepsChoice(os,"Venter på appvalg");
  os.proposalFrame("{\"type\":\"build_proposal\",\"project_id\":\"old-project\",\"proposal_id\":\"late-old\"}");
  assert(!os.aiProposalId_.length() && os.aiWorkflowText_=="Venter på appvalg");
  assert(!os.aiProjectPickerActive_ && os.aiProjectName_=="New app");
  assert(!os.aiProjectId_.length() && !os.aiBasePackageId_.length());
  assert(client.confirmedProject_=="old-project" && client.events.empty());
  client.serviceSelection();assertOnlyNew(client,1);const String first=client.events[0].id;
  for(unsigned i=0;i<20;++i) {client.serviceSelection();}assertOnlyNew(client,1);
  chooseNew(os);client.serviceSelection();assertOnlyNew(client,1); // Pending send cannot become a second choice.
  assert(client.selection_.appEvent==first && os.aiWorkflowText_=="Venter på appvalg");
  deliver(os,"event_ack","{\"event_id\":\"unrelated\",\"result\":{\"project_id\":\"wrong\"}}");
  assert(client.selectionPending() && !os.aiProjectId_.length() && client.confirmedProject_=="old-project");
  deliver(os,"error","{\"event_id\":\"unrelated\"}");
  assert(client.selectionPending() && !os.aiProjectId_.length());
  deliver(os,"app_selected",selected(first,"new-project-one"));
  assert(!client.selectionPending() && client.confirmedProject_=="new-project-one");
  assert(os.aiProjectId_=="new-project-one" && !os.aiBasePackageId_.length());
  assert(os.aiWorkflowText_=="Valg bekreftet" && os.aiConversationMode_==0 && os.unrelatedUi==0);
  assert(os.lcdChoice()=="Valg bekreftet" && os.qaChoice()==os.lcdChoice());
  activityKeepsChoice(os,"Valg bekreftet");
  os.runtimeAiEnabled_=false;
  os.uiEventFrame("{\"type\":\"ui_event\",\"event\":\"runtime_ai_policy\",\"mode\":\"off\"}");
  assert(client.runtimePolicies==1 && client.runtimeMode=="off" && os.runtimeCancels==1);
  assert(!os.aiRuntimeAuto_ && os.aiRuntimeModeAcked_ && os.aiWorkflowText_=="Valg bekreftet");
  os.drawFailureProbe();assert(os.drawn.empty()); // Current code before RC18 clearing fails here at runtime.
  assert(!os.aiBuildResumePending_ && !os.aiBuildRetryPending_ && !os.aiBuildErrorStatus_.length());
  assert(!os.aiBuildDiagnosticMessage_.length() && !os.aiProposalId_.length());
  assert(!os.aiBuildId_.length() && !os.aiBuildProjectId_.length() && os.aiBuildResumeCount_==-1 && os.aiBuildProgress_==0);
  assert(os.backgroundBuildId_=="old-failed-build"); // Background tracker retained independently of foreground.
  assert(!os.aiBuildForeground("old-project","old-failed-build") && !os.aiBuildForeground(String(),"old-failed-build"));
  assert(os.buildJobCount_==1 && os.buildJobIds_[0]=="retained-background");
  os.proposalFrame("{\"type\":\"build_proposal\",\"project_id\":\"old-project\",\"proposal_id\":\"late-old\"}");
  os.progressGuard("{\"type\":\"build_job_status\",\"project_id\":\"old-project\",\"build_id\":\"old-failed-build\",\"status\":\"failed\",\"phase\":\"failed\"}");
  os.errorFrame("{\"type\":\"error\",\"project_id\":\"old-project\",\"build_id\":\"old-failed-build\",\"message\":\"Old failure\"}");
  assert(!os.aiProposalId_.length() && os.aiProjectId_=="new-project-one" && os.aiWorkflowText_=="Valg bekreftet");
  assert(os.foregroundProgressAdoptions==0 && os.buildPhase_=="failed"); // Background facts still updated.
  os.errorFrame("{\"type\":\"error\",\"message\":\"Genuine current uncorrelated error\"}");
  assert(os.aiWorkflowText_=="Genuine current uncorrelated error"); // No blanket hiding of real current failures.
  os.proposalFrame("{\"type\":\"build_proposal\",\"project_id\":\"new-project-one\",\"proposal_id\":\"current-proposal\"}");
  assert(os.aiProposalId_=="current-proposal" && os.aiWorkflowState_==3);
  assertOnlyNew(client,1);

  // Each later explicit choice has a new event, never a retry of the old one.
  chooseNew(os);client.serviceSelection();assertOnlyNew(client,2);
  const String second=client.events[1].id;assert(second!=first);
  deliver(os,"event_ack",String("{\"event_id\":\"")+first+"\",\"result\":{\"project_id\":\"late-old\"}}");
  assert(client.selection_.appEvent==second && !os.aiProjectId_.length());
  deliver(os,"error",String("{\"event_id\":\"")+second+"\",\"code\":\"event_rejected\"}");
  assert(!client.selectionPending() && client.confirmedProject_=="new-project-one");
  assert(os.aiProjectId_=="new-project-one" && os.aiWorkflowText_=="Valg avvist. Velg app igjen");
  assert(os.lcdChoice()=="Valg avvist" && os.qaChoice()==os.lcdChoice());
  activityKeepsChoice(os,"Valg avvist. Velg app igjen");
  for(unsigned i=0;i<20;++i) {client.serviceSelection();}assertOnlyNew(client,2);

  chooseNew(os);client.serviceSelection();assertOnlyNew(client,3);
  const String third=client.events[2].id;assert(third!=second && third!=first);
  client.selection_.lost();assert(client.selectionUnclear());
  for(unsigned i=0;i<20;++i) {client.serviceSelection();}assertOnlyNew(client,3);
  const String snapshot=String("{\"project_id\":\"new-project-three\",\"base_package_id\":null,\"app_mode\":\"new\",\"conversation_mode\":\"develop\",\"selection_ack\":{\"app_select\":\"")+third+"\"}}";
  deliver(os,"session_snapshot",snapshot);
  assert(!client.selectionPending() && os.aiProjectId_=="new-project-three");
  assertOnlyNew(client,3);
  puts("PASS actual New app menu pending producer matched receipt and UI adoption");

  FireBackendClient offline;offline.ready=false;FireOS queued;queued.backendClient_=&offline;
  chooseNew(queued);const String unsent=offline.selection_.appEvent;
  offline.serviceSelection();assertOnlyNew(offline,0);
  chooseNew(queued);assert(offline.selection_.appEvent!=unsent);
  offline.ready=true;offline.serviceSelection();assertOnlyNew(offline,1);
  assert(offline.events[0].id!=unsent); // Replaced unsent choice was never transmitted.
  FireBackendClient stale;FireOS hidden;hidden.backendClient_=&stale;
  hidden.aiPickerShownKind_=fire_ai_menu::Kind::Chat;hidden.handleAiPicker(1);
  assert(!stale.selectionPending() && stale.events.empty() && hidden.unrelatedUi==0);
  os.aiBuildId_="current-build";os.aiBuildProjectId_=os.aiProjectId_;
  assert(os.aiBuildForeground(os.aiProjectId_,"current-build"));
  assert(!os.aiBuildForeground(os.aiProjectId_,"older-same-project-build"));
  const String currentText=os.aiWorkflowText_;
  os.errorFrame("{\"type\":\"error\",\"project_id\":\"new-project-three\",\"build_id\":\"older-same-project-build\",\"display_text\":\"Stale same-project error\"}");
  assert(os.aiWorkflowText_==currentText && os.aiBuildId_=="current-build");
  os.errorFrame("{\"type\":\"error\",\"project_id\":\"new-project-three\",\"build_id\":\"current-build\",\"display_text\":\"Bound current error\"}");
  assert(os.aiWorkflowText_=="Bound current error");
  // First progress may establish a build ID only for a real confirmed current
  // proposal BUILD. Mere equality with the selected project is insufficient.
  os.aiBuildId_=String();assert(!os.aiBuildForeground(os.aiProjectId_,"bootstrap-build"));
  os.aiBuildProjectId_=os.aiProjectId_;os.aiWorkflowState_=4;
  os.aiProposalId_="confirmed-current-proposal";os.aiProposalProjectId_=os.aiProjectId_;
  assert(os.aiBuildForeground(os.aiProjectId_,"bootstrap-build") && os.aiBuildForeground(os.aiProjectId_));
  os.aiProposalId_=String();assert(!os.aiBuildForeground(os.aiProjectId_,"bootstrap-build"));
  os.aiBuildId_="current-build";os.aiWorkflowState_=0;os.aiProposalProjectId_=String();
  os.aiConversationMode_=1;assert(!os.aiBuildForeground(os.aiProjectId_,"current-build"));
  os.aiConversationMode_=0;os.aiVoiceTestMode_=true;assert(!os.aiBuildForeground(os.aiProjectId_,"current-build"));
  os.aiJobViewing_=true;os.aiJobBuild_="current-build";os.aiJobRepair_=String();
  assert(os.aiBuildForeground(os.aiProjectId_,"current-build")); // Explicit owned Job Open remains allowed.
  os.aiJobRepair_="repair-other";assert(!os.aiBuildForeground(os.aiProjectId_,"current-build"));
  os.aiJobViewing_=false;os.aiVoiceTestMode_=false;os.aiJobRepair_=String();
  os.errorFrame("{\"type\":\"error\",\"project_id\":\"new-project-three\",\"build_id\":\"current-build\",\"display_text\":\"Current failure\"}");
  assert(os.aiWorkflowText_=="Current failure");
  os.aiBuildResumePending_=true;os.aiBuildErrorStatus_="Current genuine failure";
  os.aiBuildDiagnosticMessage_=String();os.drawFailureProbe();
  assert(os.drawn.size()==1 && os.drawn[0]=="Current genuine failure");
  // A real user workflow change ends choice feedback protection. The normal
  // activity interpreter still runs, and a real error is never hidden.
  os.aiWorkflowText_="Explicit user listening action";os.aiWorkflowState_=0;
  os.uiEventFrame("{\"type\":\"ui_event\",\"state\":\"listening\"}");
  assert(os.aiWorkflowState_==1 && os.aiDeveloperMode_==1 && os.aiWorkflowText_=="listening");
  os.errorFrame("{\"type\":\"error\",\"display_text\":\"Real current dialog failure\"}");
  assert(os.aiWorkflowText_=="Real current dialog failure" && os.aiWorkflowState_==0);
  assertOnlyNew(client,3);
  puts("PASS actual New app busy rejection lost receipt explicit choices and no blind replay");
}
'''


class NewAppFlowTests(unittest.TestCase):
    def build(self, execute):
        compiler = native.host_compiler()
        if compiler is None:
            self.skipTest('No host C++ compiler; no runtime verification claimed')
        prefix = [compiler, 'c++'] if Path(compiler).stem.lower() == 'zig' else [compiler]
        if os.name == 'nt' and Path(compiler).stem.lower() == 'zig':
            prefix += ['-target', 'x86_64-windows-gnu']
        with tempfile.TemporaryDirectory(prefix='fire-new-app-flow-') as directory:
            directory = Path(directory)
            path = directory / 'new_app.cpp'
            path.write_text(source(), encoding='utf-8')
            output = directory / ('new_app' if execute else 'new_app.o')
            command = prefix + ['-std=c++17', '-O2', '-UNDEBUG', '-Wall', '-Wextra', '-Werror',
                                '-pedantic', '-I', str(native.ROOT / 'src')]
            if not execute:
                command += ['-c']
            result = subprocess.run(command + [str(path), '-o', str(output)],
                                    capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(output.is_file())
            if execute:
                result = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

    def test_actual_new_app_pipeline_compiles_strictly(self):
        self.build(False)

    @unittest.skipIf(os.name == 'nt', 'Windows4551: object compile only; actual C++ executes on Linux CI')
    def test_actual_new_app_pipeline_executes(self):
        output = self.build(True)
        self.assertIn('PASS actual New app menu pending producer matched receipt and UI adoption', output)
        self.assertIn('PASS actual New app busy rejection lost receipt explicit choices and no blind replay', output)
        self.assertIn('PASS actual new intent revokes serial voice', output)


if __name__ == '__main__':
    unittest.main()
