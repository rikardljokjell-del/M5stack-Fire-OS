#include "fire_ai_menu_ui.h"

bool FireOS::aiRepairResumeAvailable() const {
  return luaRepairId_.length() && luaRepairStatus_!="cancelled" && luaRepairStatus_!="failed" && luaRepairStatus_!="unavailable";
}
uint8_t FireOS::aiBuildResumeMask() const {
  uint8_t mask=0;for (uint8_t i=0;i<buildJobCount_ && i<4;++i)
    if (buildJobIds_[i].length() && buildJobStatuses_[i]!="cancelled") mask|=1u<<i;
  return mask;
}
String FireOS::aiRepairResumeName() const {
  if (luaRepairAppName_.length()) return luaRepairAppName_;
  for (uint8_t i=0;i<luaAppCount_;++i) if (luaAppIds_[i]==luaRepairAppId_) return luaAppDisplayNames_[i].length()?luaAppDisplayNames_[i]:luaAppNames_[i];
  return "Appnavn ikke hentet";
}
void FireOS::selectAiProject(fire_ai_menu::Kind kind,uint8_t index) {
  using fire_ai_menu::Kind;
  aiVoiceTestMode_=kind==Kind::Voice;aiConversationMode_=(kind==Kind::Chat || aiVoiceTestMode_)?1:0;
  aiProjectId_=String();aiBasePackageId_=String();aiProposalProjectId_=String();
  aiEvolutionGoal_=String();aiEvolutionGoalProject_=String();aiDevelopmentContext_=String();aiEvolutionNewPending_=false;
  aiProjectName_=kind==Kind::Chat?"Chat":aiVoiceTestMode_?"Voice test":"New app";
  if (kind==Kind::App) {
    if (index>=luaAppCount_) return;
    const String source=luaAppPaths_[index];const int slash=source.lastIndexOf('/');
    const String folder=slash>0?source.substring(0,slash):source,app=sdBaseName(folder);
    fire_lua_install::Identity identity;
    const auto result=fire_lua_install::read(SD,(folder+"/"+fire_lua_install::kFilename).c_str(),identity);
    if (result==fire_lua_install::Read::Invalid || (result==fire_lua_install::Read::Valid && app!=identity.app)) {
      aiWorkflowText_="metadata_error";return;
    }
    aiProjectId_=result==fire_lua_install::Read::Valid?(identity.project[0]?String(identity.project):app):preferences.getString(compactPreferenceKey("pr_",app).c_str(),app);
    aiProjectName_=luaAppDisplayNames_[index].length()?luaAppDisplayNames_[index]:luaAppNames_[index];
    aiBasePackageId_=luaAppPackageIds_[index];
  }
  if (backendClient_) {
    backendClient_->setProjectId(aiProjectId_);
    backendClient_->setConversationMode(aiConversationMode_?"chat":"develop");
    if (kind==Kind::NewApp) backendClient_->setAppMode("new");
    else if (kind==Kind::App) backendClient_->setAppMode("update",aiBasePackageId_);
  }
  aiProjectPickerActive_=false;aiDeveloperMode_=0;aiWorkflowState_=0;aiAssistantText_=String();
  aiWorkflowText_=aiVoiceTestMode_?"VOICE TEST - PRESS B TO RECORD":kind==Kind::App?"EDIT "+aiProjectName_:kind==Kind::Chat?"Chat er klar":"NEW APP";
}
void FireOS::handleAiPicker(uint8_t index) {
  if (backendSettingsUi_.page!=FireBackendSettingsUi::None) {handleBackendSettingsButton(index);return;}
  using fire_ai_menu::Kind;using fire_ai_menu::Page;
  const bool repair=aiRepairResumeAvailable();const uint8_t builds=aiBuildResumeMask();
  const uint8_t count=fire_ai_menu::count(aiPickerPage_,repair,builds,luaAppCount_);
  if (aiProjectSelection_>=count) aiProjectSelection_=count-1;
  if (index!=1) aiProjectSelection_=(aiProjectSelection_+count+(index==0?-1:1))%count;
  else {
    const auto item=fire_ai_menu::at(aiPickerPage_,aiProjectSelection_,repair,builds,luaAppCount_);
    const String identity=item.kind==Kind::Build?buildJobIds_[item.index]:item.kind==Kind::Repair?luaRepairId_:item.kind==Kind::App?luaAppIds_[item.index]:String();
    if (item.kind!=aiPickerShownKind_ || identity!=aiPickerShownId_) {aiWorkflowText_="Listen er endret. Velg igjen";redrawRequested_=true;return;}
    if (item.kind==Kind::Back) {
      if (aiPickerPage_==Page::Main) back();else {aiPickerPage_=Page::Main;aiProjectSelection_=aiProjectOffset_=0;}
    } else if (item.kind==Kind::SelectApp) {
      aiPickerPage_=Page::Apps;aiProjectSelection_=aiProjectOffset_=0;scanLuaApps();
    } else if (item.kind==Kind::Evolution) {
      if (aiProjectId_.length()) openEvolution(true);
      else if (backendClient_ && backendClient_->sessionReady()) {
        selectAiProject(Kind::NewApp);aiProjectPickerActive_=true;
        aiEvolutionNewPending_=true;aiEvolutionNewAt_=millis();aiWorkflowText_="Venter på appidentitet";
      } else aiWorkflowText_="Koble til backend først";
    } else if (item.kind==Kind::Settings) {
      aiPickerPage_=Page::Settings;aiProjectSelection_=aiProjectOffset_=0;
    } else if (item.kind==Kind::Runtime) requestBackendSettings("summary");
    else if (item.kind==Kind::Models) requestBackendSettings("models");
    else if (item.kind==Kind::Usage) requestBackendSettings("usage");
    else if (item.kind==Kind::Limits) requestBackendSettings("limits");
    else if (item.kind==Kind::Connection) open(Screen::AiApi);
    else if (item.kind==Kind::Repair) {
      aiProjectPickerActive_=false;aiRepairResumePending_=true;
      if (luaRepairAppId_.length()) {luaErrorAppId_=luaRepairAppId_;luaErrorAppName_=aiRepairResumeName();}
      luaAppError_="Henter reparasjonsstatus";previousScreen_=Screen::AiDeveloper;screen_=Screen::LuaApp;requestLuaRepairStatus();
    } else if (item.kind==Kind::Build) {
      const uint8_t i=item.index;aiProjectPickerActive_=false;aiBuildId_=buildJobIds_[i];aiProjectName_=buildJobNames_[i];
      aiBuildErrorCode_=buildJobErrorCodes_[i];aiBuildErrorStatus_=buildJobErrors_[i];aiBuildDiagnosticMessage_=buildJobDiagnostics_[i];
      aiBuildCanResume_=buildJobCanResume_[i];aiBuildCanRetry_=buildJobCanRetry_[i];aiBuildResumePending_=buildJobStatuses_[i]=="failed";aiBuildRetryPending_=false;
      backgroundBuildActive_=!aiBuildResumePending_;aiWorkflowState_=aiBuildResumePending_?2:4;aiDeveloperMode_=2;
      aiWorkflowText_=aiBuildResumePending_?"Byggingen trenger oppfølging":"Gjenopptar byggingen";aiAssistantText_=aiBuildErrorStatus_;
      if (backendClient_) backendClient_->buildResume(aiBuildId_);
    } else selectAiProject(item.kind,item.index);
  }
  aiProjectOffset_=fire_ai_menu::scroll(aiProjectSelection_,aiProjectOffset_);redrawRequested_=true;
}
void FireOS::drawAiPicker() {
  if (backendSettingsUi_.page!=FireBackendSettingsUi::None) {drawBackendSettings();return;}
  using fire_ai_menu::Kind;using fire_ai_menu::Page;
  const bool repair=aiRepairResumeAvailable();const uint8_t builds=aiBuildResumeMask();
  const uint8_t count=fire_ai_menu::count(aiPickerPage_,repair,builds,luaAppCount_);
  if (aiProjectSelection_>=count) aiProjectSelection_=count-1;
  aiProjectOffset_=fire_ai_menu::scroll(aiProjectSelection_,aiProjectOffset_);
  String labels[4],selectedName;
  const auto current=fire_ai_menu::at(aiPickerPage_,aiProjectSelection_,repair,builds,luaAppCount_);
  aiPickerShownKind_=current.kind;aiPickerShownId_=current.kind==Kind::Build?buildJobIds_[current.index]:current.kind==Kind::Repair?luaRepairId_:current.kind==Kind::App?luaAppIds_[current.index]:String();
  if (current.kind==Kind::Build) selectedName=buildJobNames_[current.index].length()?buildJobNames_[current.index]:String("Appnavn ikke hentet");
  else if (current.kind==Kind::Repair) selectedName=aiRepairResumeName();
  else if (current.kind==Kind::App) selectedName=luaAppDisplayNames_[current.index].length()?luaAppDisplayNames_[current.index]:luaAppNames_[current.index];
  const uint8_t rows=min<uint8_t>(4,count-aiProjectOffset_);
  for (uint8_t row=0;row<rows;++row) {
    const auto item=fire_ai_menu::at(aiPickerPage_,aiProjectOffset_+row,repair,builds,luaAppCount_);
    switch(item.kind) {
      case Kind::Repair:labels[row]="Resume feilretting";break;
      case Kind::Build:labels[row]="Resume bygging";break;
      case Kind::Chat:labels[row]="Chat only";break;
      case Kind::NewApp:labels[row]="New app";break;
      case Kind::SelectApp:labels[row]="Select app";break;
      case Kind::Evolution:labels[row]="Evolution";break;
      case Kind::Settings:labels[row]="Settings";break;
      case Kind::Back:labels[row]="Back";break;
      case Kind::App:labels[row]=luaAppDisplayNames_[item.index].length()?luaAppDisplayNames_[item.index]:luaAppNames_[item.index];break;
      case Kind::Runtime:labels[row]=String("Runtime AI: ")+(aiRuntimeAuto_?"AUTO":"OFF")+(aiRuntimeModeAcked_?"":" (ukjent)");break;
      case Kind::Models:labels[row]="Model";break;
      case Kind::Usage:labels[row]="Usage";break;
      case Kind::Limits:labels[row]="Pengegrenser";break;
      case Kind::Voice:labels[row]="Voice test";break;
      case Kind::Connection:labels[row]="Forbindelse";break;
    }
  }
  const char* rowsText[]={labels[0].c_str(),labels[1].c_str(),labels[2].c_str(),labels[3].c_str()};
  const char* connection=!backendClient_ || !backendClient_->configured()?"Backend er ikke satt opp":backendClient_->sessionReady()?"Backend er tilkoblet":"Kobler til backend";
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  fire_ai_menu_ui::draw(surface,aiPickerPage_==Page::Apps?"SELECT APP":aiPickerPage_==Page::Settings?"SETTINGS":"AI DEVELOPER",connection,
      backendClient_ && backendClient_->sessionReady()?kGreen:kOrange,selectedName.c_str(),rowsText,rows,aiProjectSelection_-aiProjectOffset_,aiWorkflowText_.length()<=40?aiWorkflowText_.c_str():"Velg en handling");
}
