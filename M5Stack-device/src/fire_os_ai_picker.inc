#include "fire_ai_menu_ui.h"
#include <cJSON.h>


bool FireOS::aiRepairResumeAvailable() const {
  return luaRepairId_.length() && luaRepairStatus_!="cancelled" && luaRepairStatus_!="failed" && luaRepairStatus_!="unavailable";
}
String FireOS::aiRepairResumeName() const {
  if (luaRepairAppName_.length()) return luaRepairAppName_;
  for (uint8_t i=0;i<luaAppCount_;++i) if (luaAppIds_[i]==luaRepairAppId_) return luaAppDisplayNames_[i].length()?luaAppDisplayNames_[i]:luaAppNames_[i];
  return "Appnavn ikke hentet";
}
bool FireOS::selectAiProject(fire_ai_menu::Kind kind,uint8_t index) {
  using fire_ai_menu::Kind;
  if (kind==Kind::App && index>=luaAppCount_) return false;
  if (kind!=Kind::Voice && backendClient_ && !backendClient_->beginSelection()) {
    aiWorkflowText_="Venter på appvalg";redrawRequested_=true;return false;
  }
  aiVoiceTestMode_=kind==Kind::Voice;aiConversationMode_=(kind==Kind::Chat || aiVoiceTestMode_)?1:0;
  aiProjectId_=String();aiBasePackageId_=String();aiProposalProjectId_=String();aiProposalJobId_=String();aiProposalAppName_=String();
  aiEvolutionGoal_=String();aiEvolutionGoalProject_=String();aiDevelopmentContext_=String();aiEvolutionNewPending_=false;
  aiProjectName_=kind==Kind::Chat?"Chat":aiVoiceTestMode_?"Voice test":"New app";
  if (kind==Kind::App) {
    const String source=luaAppPaths_[index];const int slash=source.lastIndexOf('/');
    const String folder=slash>0?source.substring(0,slash):source,app=sdBaseName(folder);
    fire_lua_install::Identity identity;
    const auto result=fire_lua_install::read(SD,(folder+"/"+fire_lua_install::kFilename).c_str(),identity);
    if (result==fire_lua_install::Read::Invalid || (result==fire_lua_install::Read::Valid && app!=identity.app)) {
      aiWorkflowText_="metadata_error";return false;
    }
    aiProjectId_=result==fire_lua_install::Read::Valid?(identity.project[0]?String(identity.project):app):preferences.getString(compactPreferenceKey("pr_",app).c_str(),app);
    aiProjectName_=luaAppDisplayNames_[index].length()?luaAppDisplayNames_[index]:luaAppNames_[index];
    aiBasePackageId_=luaAppPackageIds_[index];
  }
  if (backendClient_ && !aiVoiceTestMode_) {
    backendClient_->setProjectId(aiProjectId_);
    // app_select itself confirms develop mode and restores this app's history.
    // A subsequent redundant mode_select would clear that restored history.
    if (kind==Kind::NewApp) backendClient_->setAppMode("new");
    else if (kind==Kind::App) backendClient_->setAppMode("update",aiBasePackageId_);
    else backendClient_->setConversationMode("chat");
  }
  aiProjectPickerActive_=false;aiDeveloperMode_=0;aiWorkflowState_=0;aiAssistantText_=String();
  aiWorkflowText_=aiVoiceTestMode_?"VOICE TEST - PRESS B TO RECORD":kind==Kind::App?"EDIT "+aiProjectName_:kind==Kind::Chat?"Chat er klar":"NEW APP";
  if (!aiVoiceTestMode_ && backendClient_ && backendClient_->selectionPending()) aiWorkflowText_="Venter på appvalg";
  return true;
}
void FireOS::handleAiPicker(uint8_t index) {
  if (backendSettingsUi_.page!=FireBackendSettingsUi::None) {handleBackendSettingsButton(index);return;}
  using fire_ai_menu::Kind;using fire_ai_menu::Page;
  if (aiPickerPage_==Page::Jobs || aiPickerPage_==Page::Job || aiPickerPage_==Page::Work) {handleAiJobMenu(index);return;}
  const bool repair=false;const uint8_t builds=0;
  const uint8_t count=fire_ai_menu::count(aiPickerPage_,repair,builds,luaAppCount_);
  if (aiProjectSelection_>=count) aiProjectSelection_=count-1;
  if (index!=1) aiProjectSelection_=(aiProjectSelection_+count+(index==0?-1:1))%count;
  else {
    const auto item=fire_ai_menu::at(aiPickerPage_,aiProjectSelection_,repair,builds,luaAppCount_);
    const String identity=item.kind==Kind::App?luaAppIds_[item.index]:String();
    if (item.kind!=aiPickerShownKind_ || identity!=aiPickerShownId_) {aiWorkflowText_="Listen er endret. Velg igjen";redrawRequested_=true;return;}
    if (item.kind==Kind::Back) {
      if (aiPickerPage_==Page::Main) back();else {aiPickerPage_=Page::Main;aiProjectSelection_=aiProjectOffset_=0;}
    } else if (item.kind==Kind::Jobs) {
      openAiJobs();
    } else if (item.kind==Kind::SelectApp) {
      aiPickerPage_=Page::Apps;aiProjectSelection_=aiProjectOffset_=0;scanLuaApps();
    } else if (item.kind==Kind::Evolution) {
      if (aiProjectId_.length()) openEvolution(true);
      else if (backendClient_ && backendClient_->sessionReady()) {
        if (selectAiProject(Kind::NewApp)) {
          aiProjectPickerActive_=true;aiEvolutionNewPending_=true;
          aiEvolutionNewAt_=millis();aiWorkflowText_="Venter på appidentitet";
        }
      } else aiWorkflowText_="Koble til backend først";
    } else if (item.kind==Kind::Settings) {
      aiPickerPage_=Page::Settings;aiProjectSelection_=aiProjectOffset_=0;
    } else if (item.kind==Kind::Runtime) requestBackendSettings("summary");
    else if (item.kind==Kind::Models) requestBackendSettings("models");
    else if (item.kind==Kind::Usage) requestBackendSettings("usage");
    else if (item.kind==Kind::Limits) requestBackendSettings("limits");
    else if (item.kind==Kind::Connection) open(Screen::AiApi);
    else selectAiProject(item.kind,item.index);
  }
  aiProjectOffset_=fire_ai_menu::scroll(aiProjectSelection_,aiProjectOffset_);redrawRequested_=true;
}
void FireOS::drawAiPicker() {
  if (backendSettingsUi_.page!=FireBackendSettingsUi::None) {drawBackendSettings();return;}
  using fire_ai_menu::Kind;using fire_ai_menu::Page;
  if (aiPickerPage_==Page::Jobs || aiPickerPage_==Page::Job || aiPickerPage_==Page::Work) {drawAiJobMenu();return;}
  const bool repair=false;const uint8_t builds=0;
  const uint8_t count=fire_ai_menu::count(aiPickerPage_,repair,builds,luaAppCount_);
  if (aiProjectSelection_>=count) aiProjectSelection_=count-1;
  aiProjectOffset_=fire_ai_menu::scroll(aiProjectSelection_,aiProjectOffset_);
  String labels[4],selectedName;const char* icons[4]={};
  const auto current=fire_ai_menu::at(aiPickerPage_,aiProjectSelection_,repair,builds,luaAppCount_);
  aiPickerShownKind_=current.kind;aiPickerShownId_=current.kind==Kind::App?luaAppIds_[current.index]:String();
  if (current.kind==Kind::App) selectedName=luaAppDisplayNames_[current.index].length()?luaAppDisplayNames_[current.index]:luaAppNames_[current.index];
  const uint8_t rows=min<uint8_t>(4,count-aiProjectOffset_);
  for (uint8_t row=0;row<rows;++row) {
    const auto item=fire_ai_menu::at(aiPickerPage_,aiProjectOffset_+row,repair,builds,luaAppCount_);
    switch(item.kind) {
      case Kind::Jobs:labels[row]="Resume bygging";break;
      case Kind::Chat:labels[row]="Chat only";break;
      case Kind::NewApp:labels[row]="New app";break;
      case Kind::SelectApp:labels[row]="Select app";break;
      case Kind::Evolution:labels[row]="Evolution";break;
      case Kind::Settings:labels[row]="Settings";break;
      case Kind::Back:labels[row]="Back";break;
      case Kind::App:labels[row]=luaAppDisplayNames_[item.index].length()?luaAppDisplayNames_[item.index]:luaAppNames_[item.index];icons[row]=luaAppIcons_[item.index];break;
      case Kind::Runtime:labels[row]=String("Runtime AI: ")+(aiRuntimeAuto_?"AUTO":"OFF")+(aiRuntimeModeAcked_?"":" (ukjent)");break;
      case Kind::Models:labels[row]="Model";break;
      case Kind::Usage:labels[row]="Usage";break;
      case Kind::Limits:labels[row]="Pengegrenser";break;
      case Kind::Voice:labels[row]="Voice test";break;
      case Kind::Connection:labels[row]="Forbindelse";break;
    }
  }
  const char* rowsText[]={labels[0].c_str(),labels[1].c_str(),labels[2].c_str(),labels[3].c_str()};
  const char* connection=packageManager_ && packageManager_->networkPaused()?"Overfører app":!backendClient_ || !backendClient_->configured()?"Backend er ikke satt opp":backendClient_->sessionRejected()?"Tilkobling avvist":backendClient_->sessionReady()?"Backend er tilkoblet":"Kobler til backend";
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  fire_ai_menu_ui::draw(surface,aiPickerPage_==Page::Apps?"SELECT APP":aiPickerPage_==Page::Settings?"SETTINGS":"AI DEVELOPER",connection,
      backendClient_ && backendClient_->sessionReady()?kGreen:kOrange,selectedName.c_str(),rowsText,rows,aiProjectSelection_-aiProjectOffset_,aiWorkflowText_.length()<=40?aiWorkflowText_.c_str():"Velg en handling",icons);
}


void FireOS::openAiJobs(uint32_t offset) {
  aiProjectPickerActive_=true;aiPickerPage_=fire_ai_menu::Page::Jobs;
  aiProjectSelection_=aiProjectOffset_=0;buildJobCount_=0;buildJobsOffset_=offset;buildJobsNext_=false;
  aiWorkflowText_="Henter jobber";
  if (backendClient_ && backendClient_->buildJobs(offset)) {buildJobsRequested_=true;buildJobsRequestAt_=millis();}
  else aiWorkflowText_="Backend er frakoblet";
  redrawRequested_=true;
}

void FireOS::openAiJob() {
  if (!backendClient_ || !backendClient_->sessionReady()) {aiWorkflowText_="Koble til backend først";return;}
  const auto route=fire_ai_menu::openRoute(aiJobCanOpen_,aiJobBuild_.c_str(),aiJobRepair_.c_str());
  if(route==fire_ai_menu::OpenRoute::None) return;
  if ((packageManager_ && packageManager_->busy()) || luaRepairCancelPending_ || luaRepairConfirmPending_ || userRunAfterInstall_.length()) {aiWorkflowText_="Venter på jobbhandlingen";return;}
  aiJobOpenPending_=true;aiJobViewing_=true;aiJobNeedsInstall_=false;
  aiWorkflowText_="Henter jobbstatus";
  if (route==fire_ai_menu::OpenRoute::Repair) {
    // Open is read-only, including an awaiting-confirmation repair. It never
    // enters the existing automatic confirm branch for a newly requested fix.
    luaRepairId_=aiJobRepair_;luaRepairAppId_=String();luaRepairAppName_=aiJobName_;
    luaRepairRequested_=false;luaRepairConfirmPending_=false;luaRepairBuildConfirmed_=false;
    luaRepairReadyPackageId_=String();luaRepairReadyVersion_=String();
    luaRepairProposalId_=String();luaRepairProjectId_=String();luaRepairStatus_="loading";
    luaRepairPhase_="loading";luaRepairMessage_="Henter jobbstatus";luaErrorAction_=0;
    userRunAfterInstall_=String();
    luaErrorAppId_=String();luaErrorAppName_=aiJobName_;luaAppError_="Reparasjon av "+aiJobName_;
    aiRepairResumePending_=false;aiProjectPickerActive_=false;
    previousScreen_=Screen::AiDeveloper;screen_=Screen::LuaApp;
    requestLuaRepairStatus();
  } else if (backendClient_->buildJobs(buildJobsOffset_)) {
    buildJobsRequested_=true;buildJobsRequestAt_=millis();
  } else {aiJobOpenPending_=false;aiWorkflowText_="Kunne ikke hente jobben";}
  redrawRequested_=true;
}

void FireOS::restoreAiJob(const cJSON* row) {
  if (!aiJobOpenPending_ || aiJobRepair_.length() || aiJobBuild_!=aiJobText(row,"build_id")) return;
  aiJobOpenPending_=false;
  if (!cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(row,"can_open"))) {aiWorkflowText_="Jobben kan ikke åpnes";return;}
  const String project=aiJobText(row,"project_id"),status=aiJobText(row,"status"),package=aiJobText(row,"package_id");
  if (!project.length() || (status=="ready" && !package.length())) {aiWorkflowText_="Jobbgrunnlag mangler";return;}
  aiBuildId_=aiJobBuild_;aiProjectId_=project;aiProjectName_=aiJobText(row,"app_name");
  if (!aiProjectName_.length()) aiProjectName_=aiJobText(row,"name");
  if(!aiProjectName_.length()) aiProjectName_="Appnavn ikke hentet";
  aiJobName_=aiProjectName_;aiProjectPickerActive_=false;aiDeveloperMode_=2;
  aiReadyPackageId_=package;aiPackageId_=package;aiJobNeedsInstall_=status=="ready";
  const cJSON* progress=cJSON_GetObjectItemCaseSensitive(row,"progress");
  aiBuildProgress_=cJSON_IsNumber(progress)?constrain(progress->valueint,0,100):0;
  buildPhase_=aiJobText(row,"phase");aiWorkflowText_=aiJobText(row,"display_text");
  if (!aiWorkflowText_.length()) aiWorkflowText_=aiJobText(row,"message");
  aiWorkflowState_=status=="ready"?5:status=="failed"?0:4;
  aiBuildResumePending_=aiBuildRetryPending_=false;
  // The next explicit Run first uses appDownload(project,package). Merely
  // viewing this owned row does not change the server's authoring session.
}

void FireOS::openAiWork() {
  aiWorkReturnRepair_=screen_==Screen::LuaApp && !luaAppActive_;
  aiJobBuild_=!aiWorkReturnRepair_ && (aiWorkflowState_==4 || aiBuildResumePending_)?aiBuildId_:String();aiJobRepair_=String();aiJobName_=aiProjectName_;
  aiJobCanPause_=jobControlsSupported_ && aiWorkflowState_==4 && aiJobBuild_.length();
  aiJobCanContext_=aiJobCanPause_;
  for (uint8_t i=0;i<buildJobCount_;++i) if (buildJobIds_[i]==aiJobBuild_ && aiJobBuild_.length()) {
    aiJobName_=buildJobNames_[i];aiJobCanPause_=buildJobCanPause_[i];aiJobCanContext_=buildJobCanContext_[i];break;
  }
  if (aiWorkReturnRepair_ && aiRepairResumeAvailable()) {
    aiJobRepair_=luaRepairId_;aiJobName_=aiRepairResumeName();
    aiJobCanPause_=jobControlsSupported_ && (luaRepairStatus_=="queued" || luaRepairStatus_=="building");
    aiJobCanContext_=jobControlsSupported_ && (luaRepairStatus_=="queued" || luaRepairStatus_=="paused");
    for (uint8_t i=0;i<buildJobCount_;++i) if (!buildJobIds_[i].length() && buildJobRepairIds_[i]==aiJobRepair_) {
      aiJobCanPause_=buildJobCanPause_[i];aiJobCanContext_=buildJobCanContext_[i];
      aiWorkflowText_=compactStatusText(buildJobStatuses_[i]);break;
    }
  }
  // Ordinary dialog has no job yet: only its existing turn operations apply.
  if (!aiJobBuild_.length() && !aiJobRepair_.length()) aiJobCanContext_=true;
  screen_=Screen::AiDeveloper;
  aiProjectPickerActive_=true;aiPickerPage_=fire_ai_menu::Page::Work;
  aiProjectSelection_=aiProjectOffset_=0;redrawRequested_=true;
}

bool FireOS::sendAiJobAction(const String& action) {
  if (!backendClient_ || !backendClient_->sessionReady()) {aiWorkflowText_="Backend er frakoblet";return false;}
  const bool job=aiJobBuild_.length() || aiJobRepair_.length();
  if (job) {
    if (!jobControlsSupported_) {aiWorkflowText_="Jobbkontroll er utilgjengelig";return false;}
    if (!backendClient_->jobControl(action,aiJobBuild_,aiJobBuild_.length()?String():aiJobRepair_)) return false;
    aiWorkflowText_="Venter på jobbkvittering";
  } else if (action=="cancel") cancelConversationTurn("Avbryter samtalen",false);
  else if (action=="context") {
    cancelConversationTurn("Si mer kontekst",true);
    aiProjectPickerActive_=false;
    if (!startAiRecording()) {aiWorkflowText_=aiAudioError_;return false;}
  } else if (action!="background") return false;
  if (action=="background") {home();}
  else if (action=="resume") {
    aiProjectName_=aiJobName_;aiProjectPickerActive_=false;
    if (aiJobBuild_.length()) {aiBuildId_=aiJobBuild_;aiBuildResumePending_=false;aiWorkflowState_=4;aiDeveloperMode_=2;}
    else {
      luaRepairId_=aiJobRepair_;luaRepairAppId_=String();luaRepairRequested_=true;aiRepairResumePending_=true;
      luaRepairAppName_=aiJobName_;luaErrorAppName_=aiJobName_;luaAppError_="Reparasjon av "+aiJobName_;
      previousScreen_=Screen::AiDeveloper;screen_=Screen::LuaApp;requestLuaRepairStatus();
    }
  }
  return true;
}

void FireOS::handleAiJobMenu(uint8_t index) {
  using fire_ai_menu::Page;using fire_ai_menu::JobAction;
  if (index==1 && aiProjectSelection_!=aiJobShownSelection_) {aiWorkflowText_="Velg den viste handlingen";redrawRequested_=true;return;}
  if (aiPickerPage_==Page::Jobs) {
    const uint8_t count=buildJobCount_+(buildJobsOffset_?1:0)+(buildJobsNext_?1:0)+1;
    if (index!=1) aiProjectSelection_=(aiProjectSelection_+count+(index==0?-1:1))%count;
    else if (aiProjectSelection_<buildJobCount_) {
      const uint8_t i=aiProjectSelection_;
      const String identity=buildJobIds_[i].length()?buildJobIds_[i]:buildJobRepairIds_[i];
      if (aiJobShownId_!=identity) {aiWorkflowText_="Listen er endret. Velg igjen";return;}
      aiJobBuild_=buildJobIds_[i];aiJobRepair_=buildJobRepairIds_[i];
      aiJobName_=buildJobNames_[i].length()?buildJobNames_[i]:String("Appnavn ikke hentet");
      aiJobCanOpen_=buildJobCanOpen_[i];aiJobCanResume_=buildJobCanResume_[i];aiJobCanDelete_=buildJobCanDelete_[i];
      aiJobCanPause_=buildJobCanPause_[i];aiJobCanContext_=buildJobCanContext_[i];
      aiPickerPage_=Page::Job;aiProjectSelection_=aiProjectOffset_=0;
    } else {
      uint8_t at=buildJobCount_;
      if (buildJobsOffset_ && aiProjectSelection_==at++) openAiJobs(buildJobsOffset_>=4?buildJobsOffset_-4:0);
      else if (buildJobsNext_ && aiProjectSelection_==at) openAiJobs(buildJobsOffset_+4);
      else {aiPickerPage_=Page::Main;aiProjectSelection_=aiProjectOffset_=0;}
    }
  } else {
    JobAction actions[5];const uint8_t count=fire_ai_menu::actions(aiPickerPage_==Page::Work,aiJobCanResume_,aiJobCanDelete_,aiJobCanPause_,aiJobCanContext_,actions,aiJobCanOpen_);
    if (aiProjectSelection_>=count) aiProjectSelection_=count-1;
    if (index!=1) aiProjectSelection_=(aiProjectSelection_+count+(index==0?-1:1))%count;
    else if (aiJobShownId_!=(aiJobBuild_.length()?aiJobBuild_:aiJobRepair_)) {aiWorkflowText_="Jobben er endret. Velg igjen";}
    else {
      switch(actions[aiProjectSelection_]) {
        case JobAction::Open:openAiJob();break;
        case JobAction::Resume:sendAiJobAction("resume");break;
        case JobAction::Delete:sendAiJobAction("delete");break;
        case JobAction::Pause:sendAiJobAction("pause");break;
        case JobAction::Cancel:sendAiJobAction("cancel");break;
        case JobAction::Background:sendAiJobAction("background");break;
        case JobAction::Context:sendAiJobAction("context");break;
        case JobAction::Back:backAiDeveloper();break;
      }
    }
  }
  aiProjectOffset_=fire_ai_menu::scroll(aiProjectSelection_,aiProjectOffset_);redrawRequested_=true;
}

void FireOS::drawAiJobMenu() {
  using fire_ai_menu::Page;using fire_ai_menu::JobAction;
  String labels[7],name=aiJobName_,status=aiWorkflowText_;uint8_t count=0;
  if (aiPickerPage_==Page::Jobs) {
    for (uint8_t i=0;i<buildJobCount_;++i) labels[count++]=buildJobNames_[i].length()?buildJobNames_[i]:String("Appnavn ikke hentet");
    if (buildJobsOffset_) labels[count++]="Forrige side";
    if (buildJobsNext_) labels[count++]="Neste side";
    labels[count++]="Back";
    if (aiProjectSelection_>=count) aiProjectSelection_=count-1;
    aiJobShownId_=aiProjectSelection_<buildJobCount_?(buildJobIds_[aiProjectSelection_].length()?buildJobIds_[aiProjectSelection_]:buildJobRepairIds_[aiProjectSelection_]):String();
    name=aiProjectSelection_<buildJobCount_?labels[aiProjectSelection_]:String();
    status=aiProjectSelection_<buildJobCount_?buildJobStatuses_[aiProjectSelection_]:String("Nyeste jobber først");
  } else {
    JobAction actions[5];count=fire_ai_menu::actions(aiPickerPage_==Page::Work,aiJobCanResume_,aiJobCanDelete_,aiJobCanPause_,aiJobCanContext_,actions,aiJobCanOpen_);
    for (uint8_t i=0;i<count;++i) labels[i]=fire_ai_menu::actionLabel(actions[i]);
    if(aiPickerPage_==Page::Job && aiProjectSelection_<count && actions[aiProjectSelection_]==JobAction::Delete) status="Fjern fra listen sletter ikke appdata";
    aiJobShownId_=aiJobBuild_.length()?aiJobBuild_:aiJobRepair_;
  }
  if (aiProjectSelection_>=count) aiProjectSelection_=count-1;
  aiProjectOffset_=fire_ai_menu::scroll(aiProjectSelection_,aiProjectOffset_);
  aiJobShownSelection_=aiProjectSelection_;
  const uint8_t rows=min<uint8_t>(4,count-aiProjectOffset_);
  const char* text[4]={"","","",""};for(uint8_t i=0;i<rows;++i) text[i]=labels[aiProjectOffset_+i].c_str();
  const bool online=backendClient_ && backendClient_->sessionReady();
  fire_canvas_fill::Surface<M5Canvas> surface(ui);
  fire_ai_menu_ui::draw(surface,aiPickerPage_==Page::Jobs?"RESUME BYGGING":aiPickerPage_==Page::Work?"ARBEID":"VALGT JOBB",
      packageManager_ && packageManager_->networkPaused()?"Overfører app":online?"Backend er tilkoblet":"Backend er frakoblet",online?kGreen:kOrange,name.c_str(),text,rows,aiProjectSelection_-aiProjectOffset_,
      status.c_str());
}

void FireOS::backAiDeveloper() {
  using fire_ai_menu::Page;
  if (backendSettingsUi_.page!=FireBackendSettingsUi::None) {
    auto& s=backendSettingsUi_;
    if (s.page==FireBackendSettingsUi::Review) s.page=s.proposalId.length()?FireBackendSettingsUi::Proposal:s.returnPage;
    else if (s.page==FireBackendSettingsUi::Proposal) {s.proposalId=String();s.page=s.returnPage;}
    else if (s.page==FireBackendSettingsUi::Values) requestBackendSettings("limits");
    else if (s.page==FireBackendSettingsUi::Models && s.role.length()) requestBackendSettings("models");
    else s.page=FireBackendSettingsUi::None;
    redrawRequested_=true;return;
  }
  if (!aiProjectPickerActive_ && aiJobViewing_) {
    aiJobOpenPending_=false;aiJobViewing_=false;aiProjectPickerActive_=true;
    aiPickerPage_=Page::Job;aiProjectSelection_=aiProjectOffset_=0;redrawRequested_=true;return;
  }
  if (aiProjectPickerActive_) {
    if (aiPickerPage_==Page::Job) {aiPickerPage_=Page::Jobs;aiProjectSelection_=aiProjectOffset_=0;}
    else if (aiPickerPage_==Page::Work) {aiProjectPickerActive_=false;if (aiWorkReturnRepair_) screen_=Screen::LuaApp;}
    else if (aiPickerPage_!=Page::Main) {aiPickerPage_=Page::Main;aiProjectSelection_=aiProjectOffset_=0;}
    else {screen_=previousScreen_==Screen::AiDeveloper?Screen::Main:previousScreen_;}
  } else {
    aiProjectPickerActive_=true;aiPickerPage_=Page::Main;aiProjectSelection_=aiProjectOffset_=0;
  }
  redrawRequested_=true;
}

bool FireOS::saveAppUpdatePreference(const String& app,bool suppressed) {
  const String key=compactPreferenceKey("up_",backendDeviceId_+"|"+app);
  if(preferences.putBool(key.c_str(),suppressed)!=1 || preferences.getBool(key.c_str(),!suppressed)!=suppressed) return false;
  if(updatePrefsOwner_!=backendDeviceId_) {
    for(uint8_t i=0;i<luaAppCount_;++i) luaUpdateSuppressed_[i]=preferences.getBool(compactPreferenceKey("up_",backendDeviceId_+"|"+luaAppIds_[i]).c_str(),false);
    updatePrefsOwner_=backendDeviceId_;
  }
  for(uint8_t i=0;i<luaAppCount_;++i) if(luaAppIds_[i]==app) luaUpdateSuppressed_[i]=suppressed;
  return true;
}

bool FireOS::requestLuaAppOpen(const String& path,const String& name,const String& package) {
  userRunAfterInstall_=String();appUpdateStage_=0;appUpdateFailure_=0;appUpdateRequest_=String();aiJobViewing_=aiJobOpenPending_=false;
  // All eligibility inputs already exist in RAM. This function never requests
  // metadata, reconnects, scans SD, waits, or makes a provider call.
  if(path.length()<=192 && (!package.length() || package.length()<=96) && !luaAppActive_ && luaCacheValid_ && luaCacheComplete_ && backendClient_ && backendClient_->sessionReady() && WiFi.status()==WL_CONNECTED) {
    for(uint8_t i=0;i<luaAppCount_;++i) if(luaAppPaths_[i]==path && (!package.length() || package==luaAppPackageIds_[i])) {
      for(uint8_t b=0;b<backendAppCount_;++b) {
        const auto& remote=backendApps_[b];
        if(luaAppIds_[i].length()>80 || luaAppPackageIds_[i].length()>96 || remote.latestPackageId.length()>96 || remote.projectId.length()>96) continue;
        const bool suppressed=updatePrefsOwner_==backendDeviceId_ && luaUpdateSuppressed_[i];
        if (!fire_app_updates::eligible(true,suppressed,remote.downloadable,backendClient_->connectionEpoch(),backendCatalogEpoch_,millis(),backendCatalogAt_,
            luaAppIds_[i].c_str(),remote.appId.c_str(),remote.projectId.c_str(),luaAppPackageIds_[i].c_str(),remote.latestPackageId.c_str(),luaAppVersions_[i].c_str(),remote.latestVersion.c_str())) continue;
        appUpdatePath_=path;appUpdateApp_=luaAppIds_[i];appUpdateInstalled_=luaAppPackageIds_[i];
        appUpdateCandidate_=remote.latestPackageId;appUpdateProject_=remote.projectId;
        appUpdateStage_=1;appUpdateSelection_=1;redrawRequested_=true;return true;
      }
      break;
    }
  }
  return startLuaApp(path,name,package);
}

void FireOS::handleAppUpdateButton(uint8_t index) {
  const auto action=fire_app_updates::confirm(appUpdateStage_,appUpdateSelection_,appUpdateReady_);
  if(appUpdateStage_==3) {
    if(index==1 && action==fire_app_updates::Action::RunVerified && backendClient_ && backendClient_->sessionReady() && backendClient_->confirmRun(appUpdateCandidate_)) {appUpdateStage_=0;appUpdateReady_=false;redrawRequested_=true;}
    return;
  }
  if(appUpdateStage_==2) {if(index==1 && action==fire_app_updates::Action::Minimize) {appUpdateStage_=0;redrawRequested_=true;}return;} // minimize transfer view
  if(index!=1) {appUpdateSelection_=(appUpdateSelection_+3+(index==0?-1:1))%3;redrawRequested_=true;return;}
  if(appUpdateSelection_!=appUpdateShownSelection_) {redrawRequested_=true;return;}
  String name=sdBaseName(appUpdatePath_);
  for(uint8_t i=0;i<luaAppCount_;++i) if(luaAppIds_[i]==appUpdateApp_ && luaAppPackageIds_[i]==appUpdateInstalled_) name=luaAppDisplayNames_[i];
  if(action==fire_app_updates::Action::Download) {
    bool exact=false;
    if(backendClient_ && backendClient_->sessionReady() && WiFi.status()==WL_CONNECTED && fire_app_updates::knownEpoch(backendClient_->connectionEpoch(),backendCatalogEpoch_))
      for(uint8_t i=0;i<backendAppCount_;++i) if(backendApps_[i].appId==appUpdateApp_ && backendApps_[i].projectId==appUpdateProject_ && backendApps_[i].latestPackageId==appUpdateCandidate_ && backendApps_[i].downloadable) exact=true;
    appUpdateRequest_="update-"+String(esp_random(),HEX)+String(millis(),HEX);
    if(exact && !(packageManager_ && packageManager_->busy()) && backendClient_->appDownload(appUpdateProject_,appUpdateCandidate_,appUpdateApp_,appUpdateRequest_)) {
      appUpdateReady_=false;appUpdateFailure_=0;appUpdateStage_=2;managerStatus_="Laster ned oppdatering";redrawRequested_=true;return;
    }
    appUpdateFailure_=1;redrawRequested_=true;return; // user may retry or choose the original installed app
  } else if(action==fire_app_updates::Action::Suppress && !saveAppUpdatePreference(appUpdateApp_,true)) {
    managerStatus_="Valget kunne ikke lagres";appUpdateFailure_=2;redrawRequested_=true;return;
  }
  appUpdateStage_=0;startLuaApp(appUpdatePath_,name,appUpdateInstalled_);
}

void FireOS::drawAppUpdatePrompt() {
  drawPanel(12,32,296,178);
  drawText(24,45,appUpdateFailure_==2?"Valget ikke lagret":appUpdateFailure_?"Nedlasting mislyktes":"Ny versjon finnes",appUpdateFailure_?kOrange:kText,2,kPanel);
  if(appUpdateStage_==3) {
    drawText(24,90,"Oppdatering installert",kText,1,kPanel);
    drawText(24,120,"Åpne oppdatert app?",kText,1,kPanel);
    drawFooter("","Åpne","");return;
  }
  if(appUpdateStage_==2) {
    drawText(24,90,"Laster ned oppdatering",kText,1,kPanel);
    drawText(24,114,packageManager_?String(packageManager_->progress())+"%":String(),kMuted,1,kPanel);
    drawFooter("","Minimer","");return;
  }
  String name=appUpdateApp_,versions;
  for(uint8_t i=0;i<luaAppCount_;++i) if(luaAppIds_[i]==appUpdateApp_ && luaAppPackageIds_[i]==appUpdateInstalled_) {name=luaAppDisplayNames_[i];versions=luaAppVersions_[i];}
  for(uint8_t i=0;i<backendAppCount_;++i) if(backendApps_[i].appId==appUpdateApp_ && backendApps_[i].latestPackageId==appUpdateCandidate_) versions+=" -> "+backendApps_[i].latestVersion;
  drawText(24,71,name,kText,1,kPanel);drawText(24,90,versions,kMuted,1,kPanel);
  const char* choices[]={appUpdateFailure_==1?"Prøv igjen":"Ja",appUpdateFailure_==1?"Åpne installert":"Nei","Ikke spør igjen"};
  appUpdateShownSelection_=appUpdateSelection_;
  for(uint8_t i=0;i<3;++i) {
    if(appUpdateSelection_==i) drawSelection(20,112+i*28,280,25,kCyan);
    drawText(30,118+i*28,choices[i],kText,1,kPanel);
  }
  drawFooter("Forrige","Velg","Neste");
}
