// The existing OS/UI owner, backend socket and application lifecycle.
#include "fire_ai_menu_ui.h"
namespace {
String evoText(const cJSON* obj,const char* name) {
  const cJSON* value=cJSON_GetObjectItemCaseSensitive(obj,name);
  return cJSON_IsString(value)?String(value->valuestring):String();
}
String evoCompact(const cJSON* obj) {
  char* raw=obj?cJSON_PrintUnformatted(obj):nullptr;String result=raw?String(raw):String();cJSON_free(raw);return result;
}
String evoRequest() {return "evo-"+String(esp_random(),HEX)+"-"+String(millis(),HEX);}
bool evoConsent(const cJSON* obj) {
  const cJSON* config=cJSON_GetObjectItemCaseSensitive(obj,"config");
  return cJSON_IsObject(config) && cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(config,"enabled")) &&
      cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(config,"telemetry_consent"));
}
const char* const evoFeatures[]={"generate","repair","optimize","expand","evolve"};
const char* const evoModes[]={"manual","suggest","auto_build","assisted"};
const char* const evoModeNames[]={"Manuell","Foreslå","Bygg kandidat","Assistert utvikling"};
String evoShort(const cJSON* obj,const char* fallback) {
  const String value=evoText(obj,"display_text");return value.length() && value.length()<=28?value:String(fallback);
}
String evoLine(const String& text,uint16_t& offset,int width=290) {
  char line[81];offset=fire_ai_menu_ui::line(text.c_str(),text.length(),offset,line,width);
  return String(line);
}
String evoReview(const cJSON* proposal) {
  String text="Handling: "+evoText(proposal,"operation")+"\n";
  const cJSON* config=cJSON_GetObjectItemCaseSensitive(proposal,"config");
  if (cJSON_IsObject(config)) {
    text+=String("Evolution: ")+(cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(config,"enabled"))?"På":"Av")+"\n";
    const cJSON* flags=cJSON_GetObjectItemCaseSensitive(config,"flags");
    for (const char* name:evoFeatures) text+=String(name)+": "+(cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(flags,name))?"På":"Av")+"\n";
    text+="Autonomi: "+evoText(config,"autonomy")+"\nTelemetri: "+String(cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(config,"telemetry_consent"))?"Tillatt":"Av")+"\n";
    text+="Grenser: "+evoCompact(cJSON_GetObjectItemCaseSensitive(config,"limits"));
  } else {
    const auto* goal=cJSON_GetObjectItemCaseSensitive(proposal,"goal");
    text+="Mål: "+(cJSON_IsObject(goal)?evoCompact(goal):evoText(proposal,"goal"))+"\nAutonomi: "+evoText(proposal,"autonomy")+"\n";
    text+="Grenser: "+evoCompact(cJSON_GetObjectItemCaseSensitive(proposal,"limits"))+"\n";
    const auto* scope=cJSON_GetObjectItemCaseSensitive(proposal,"binding");
    if (!cJSON_IsObject(scope)) scope=cJSON_GetObjectItemCaseSensitive(proposal,"scope");
    text+="Grunnlag og tillatelser: "+evoCompact(scope)+"\n";
    const String strategy=evoText(proposal,"strategy_id");if (strategy.length()) text+="Strategi: "+strategy+"\n";
  }
  return text;
}
String evoCost(const cJSON* obj,const char* title) {
  if (!cJSON_IsObject(obj)) return String(title)+": Ikke målt\n";
  String text=String(title)+"\n";
  const char* keys[]={"provider_calculated_usd","empirical_estimated_usd","unknown_usage_requests","unestimated_requests","pending_requests","budget_reserved_usd","budget_exposure_usd"};
  const char* labels[]={"Beregnet USD","Usikkert anslag USD","Ukjent bruk","Uten prisanslag","Pågår","Intern reserve USD","Budsjetteksponering USD"};
  for (uint8_t i=0;i<7;++i) {const cJSON* value=cJSON_GetObjectItemCaseSensitive(obj,keys[i]);
    text+=String(labels[i])+": "+(cJSON_IsNumber(value)?String(value->valuedouble,(i<2 || i>4)?4:0):String("Ukjent"))+"\n";}
  return text;
}
} // namespace

void FireOS::openEvolution(bool developer) {
  if (developer? !aiProjectId_.length():managerSelection_>=managerItemCount_) return;
  // A safe pending Pause/Stop must survive ordinary menu navigation. It is
  // not claimed applied until the matching backend response arrives.
  auto& e=evolutionUi_;const String controlRequest=e.controlRequest,controlAction=e.controlAction,controlApp=e.controlApp,controlJob=e.controlJob,controlMandate=e.controlMandate;
  const uint32_t controlRevision=e.controlRevision;
  e=FireEvolutionUi();e.controlRequest=controlRequest;e.controlAction=controlAction;e.controlApp=controlApp;
  e.controlJob=controlJob;e.controlMandate=controlMandate;e.controlRevision=controlRevision;
  e.developer=developer;
  if (developer) {e.app=e.project=aiProjectId_;e.name=aiProjectName_;e.package=aiBasePackageId_;e.context=aiDevelopmentContext_;}
  else {
    const auto& item=managerItems_[managerSelection_];e.app=item.appId;e.name=item.name;e.project=item.projectId;
    e.package=item.localPackageId.length()?item.localPackageId:item.packageId;
    for (uint8_t i=0;i<luaAppCount_;++i) if (luaAppPaths_[i]==item.localPath) {e.app=luaAppIds_[i];e.source=luaAppChecksums_[i];break;}
  }
  if (e.project.length() && e.project==aiEvolutionGoalProject_) {e.goal=aiEvolutionGoal_;e.context=aiDevelopmentContext_;}
  if (!e.app.length()) {managerStatus_="Appen mangler identitet";return;}
  open(Screen::Evolution);requestEvolutionView("summary");
}
void FireOS::requestEvolutionView(const char* view,uint32_t offset) {
  auto& e=evolutionUi_;e.view=view;e.offset=offset;e.request=evoRequest();e.requestAt=millis();
  if (!backendClient_ || !backendClient_->evolutionStatus(e.request,e.app,e.view,offset)) {
    e.request=String();e.message="Backend er frakoblet";
  } else e.message="Henter status";
}
void FireOS::prepareEvolution(const char* operation,const String& body) {
  auto& e=evolutionUi_;
  if (!e.loaded || e.request.length() || e.controlRequest.length()) {e.message="Hent ny status først";return;}
  e.operation=operation;e.request=evoRequest();e.requestAt=millis();e.proposalId=String();
  if (!backendClient_ || !backendClient_->evolutionPrepare(e.request,e.app,operation,e.revision,body,e.package,e.source)) {
    e.request=String();e.message="Backend er frakoblet";
  } else e.message="Forbereder forslag";
}
void FireOS::handleEvolutionMessage(const String& message) {
  cJSON* envelope=cJSON_Parse(message.c_str());if (!envelope) return;
  const String type=evoText(envelope,"type"),request=evoText(envelope,"request_id"),app=evoText(envelope,"app_id");
  auto& e=evolutionUi_;
  if (type=="error") {
    if (request==e.request) {e.request=String();e.message="Avvist. Hent ny status";}
    if (request==e.controlRequest) {e.controlRequest=String();e.controlAction=String();e.message="Ikke bekreftet. Hent status";}
    if (request==e.policyRequest) {e.policyRequest=String();e.upload=FireEvolution::Entry();e.uploadAllowed=false;e.uploadSent=false;}
    if (request==e.runtimeRequest) {e.runtimeRequest=String();e.runtimeApp=String();}
    cJSON_Delete(envelope);redrawRequested_=true;return;
  }
  if (type=="evolution_telemetry_ack") {
    const String batch=evoText(envelope,"batch_id"),status=evoText(envelope,"status");
    evolution_.acknowledge(request,batch,status);
    if (request=="evt-"+e.upload.batch && batch==e.upload.batch) {e.upload=FireEvolution::Entry();e.policyRequest=String();e.uploadAllowed=false;e.uploadSent=false;}
    cJSON_Delete(envelope);return;
  }
  const String body=evoText(envelope,"evolution_json");
  if (!fireJsonSafe(body.c_str(),body.length(),FireEvolutionContract::kSnapshotJsonBytes)) {cJSON_Delete(envelope);return;}
  cJSON* obj=cJSON_Parse(body.c_str());if (!cJSON_IsObject(obj)) {cJSON_Delete(obj);cJSON_Delete(envelope);return;}
  const cJSON* revision=cJSON_GetObjectItemCaseSensitive(envelope,"revision");
  if (!cJSON_IsNumber(revision) || revision->valuedouble<0 || revision->valuedouble>UINT32_MAX || floor(revision->valuedouble)!=revision->valuedouble) {
    cJSON_Delete(obj);cJSON_Delete(envelope);return;
  }
  if (type=="evolution_snapshot") {
    if (request==e.runtimeRequest && app==luaAppId_ && e.runtimeApp==luaPackageId_) {
      evolution_.consent(app,evoConsent(obj),millis());e.runtimeRequest=String();
    }
    if (request==e.policyRequest && app==e.upload.app) {
      e.uploadAllowed=evoConsent(obj);e.policyRequest=String();
      evolution_.consent(app,e.uploadAllowed,millis());
      if (!e.uploadAllowed) {e.upload=FireEvolution::Entry();e.message="Telemetri er av";}
    }
    const bool controlAck=request==e.controlRequest && app==e.controlApp;
    if (controlAck) {e.controlRequest=String();e.controlAction=String();}
    if (request==e.request || (controlAck && app==e.app)) {
      if (app!=e.app) {cJSON_Delete(obj);cJSON_Delete(envelope);return;}
      e.request=String();e.revision=static_cast<uint32_t>(revision->valuedouble);
      const cJSON* config=cJSON_GetObjectItemCaseSensitive(obj,"config");
      if (cJSON_IsObject(config)) {
        e.config=evoCompact(config);e.loaded=true;e.enabled=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(config,"enabled"));
        e.consent=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(config,"telemetry_consent"));
        const cJSON* flags=cJSON_GetObjectItemCaseSensitive(config,"flags");
        for (uint8_t i=0;i<5;++i) e.flags[i]=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(flags,evoFeatures[i]));
        const String mode=evoText(config,"autonomy");for (uint8_t i=0;i<4;++i) if (mode==evoModes[i]) e.autonomy=i;
        e.acknowledgedConsent=e.enabled && e.consent;e.consentAt=millis();
        evolution_.consent(app,e.acknowledgedConsent,millis());
      }
      const cJSON* job=cJSON_GetObjectItemCaseSensitive(obj,"job"),*mandate=cJSON_GetObjectItemCaseSensitive(obj,"mandate");
      e.job=evoText(job,"id");e.mandate=evoText(mandate,"id");e.message=evoShort(job,e.enabled?"Evolution er klar":"Evolution er av");
      e.permissionRequest=String();e.permissionOperation=String();
      const auto* permission=cJSON_GetObjectItemCaseSensitive(obj,"permission_request");
      if (evoText(job,"state")=="permission_required" && cJSON_IsObject(permission)) {
        const String operation=evoText(permission,"operation");const auto* prepare=cJSON_GetObjectItemCaseSensitive(permission,"prepare");
        const String id=evoText(prepare,"permission_job_id");bool allowed=false;
        for (const char* name:evoFeatures) if (operation==name) allowed=true;
        if (allowed && cJSON_IsObject(prepare) && cJSON_GetArraySize(prepare)==1 && id.length() && id.length()<=64) {
          const String body=evoCompact(prepare);
          if (fireJsonSafe(body.c_str(),body.length(),FireEvolutionContract::kControlJsonBytes)) {e.permissionRequest=body;e.permissionOperation=operation;}
        }
      }
      e.costReview=evoCost(cJSON_GetObjectItemCaseSensitive(obj,"app_cost"),"Evolution: denne appen")+
          evoCost(cJSON_GetObjectItemCaseSensitive(obj,"daily_cost"),"Evolution: i dag")+
          evoCost(cJSON_GetObjectItemCaseSensitive(job,"cost"),"Denne jobben");
      if (e.page==FireEvolutionUi::Costs) e.review=e.costReview;
      if (cJSON_GetObjectItemCaseSensitive(obj,"metric_choices")) {
      e.metricOffset=e.offset;e.metricHasMore=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(obj,"metric_has_more"));
      e.metricCount=0;const auto* metrics=cJSON_GetObjectItemCaseSensitive(obj,"metric_choices");const cJSON* metric=nullptr;
      if (cJSON_IsArray(metrics)) cJSON_ArrayForEach(metric,metrics) {
        if (e.metricCount>=16) break;
        const String id=evoText(metric,"id"),label=evoText(metric,"display_text");
        if (!id.length() || id.length()>48 || !label.length()) continue;
        e.metricIds[e.metricCount]=id;e.metricLabels[e.metricCount]=label;++e.metricCount;
      }
      }
      e.itemCount=0;const cJSON* item=nullptr;const cJSON* items=cJSON_GetObjectItemCaseSensitive(obj,"items");
      if (cJSON_IsArray(items)) cJSON_ArrayForEach(item,items) {
        if (e.itemCount>=FireEvolutionContract::kPageItems) break;
        e.itemIds[e.itemCount]=evoText(item,"id");e.itemLabels[e.itemCount]=evoShort(item,"Se detaljer");
        e.itemReviews[e.itemCount]=evoText(item,"display_text");++e.itemCount;
      }
      e.hasMore=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(obj,"has_more"));
      const auto* comparison=cJSON_GetObjectItemCaseSensitive(obj,"comparison");
      if (e.view=="compare") e.comparisonReview=String();
      if (e.view=="compare" && cJSON_IsObject(comparison)) {
        e.comparisonReview="Basis: "+evoText(comparison,"base_package_id")+"\nKandidat: "+evoText(comparison,"candidate_package_id")+
            "\nResultat: "+evoText(comparison,"status")+"\nMetrikk: "+evoText(comparison,"metric")+"\n";
        const auto* measured=cJSON_GetObjectItemCaseSensitive(comparison,"measurement");
        if (cJSON_IsObject(measured)) {
          const char* keys[]={"before","after","improvement_percent","evidence"};
          const char* labels[]={"Før","Etter","Forbedring prosent","Evidens"};
          for (uint8_t i=0;i<4;++i) {const auto* value=cJSON_GetObjectItemCaseSensitive(measured,keys[i]);
            e.comparisonReview+=String(labels[i])+": "+(value?evoCompact(value):String("Ikke målt"))+"\n";}
        } else e.comparisonReview+="Ikke målt\n";
        e.comparisonReview+="Fysisk protokollverifikasjon: "+String(cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(comparison,"physical_resolution_verified"))?"Bekreftet":"Ikke bekreftet");
      }
    }
  } else if (type=="evolution_proposal" && request==e.request && app==e.app) {
    e.request=String();e.proposalId=evoText(envelope,"proposal_id");e.proposalRevision=static_cast<uint32_t>(revision->valuedouble);
    const cJSON* expires=cJSON_GetObjectItemCaseSensitive(envelope,"expires_at");
    e.expiresAt=cJSON_IsNumber(expires) && expires->valuedouble>0 && expires->valuedouble<=UINT32_MAX?static_cast<uint32_t>(expires->valuedouble):0;
    e.proposal=body;e.review=evoReview(obj);e.reviewOffset=0;e.page=FireEvolutionUi::Proposal;e.selection=e.scroll=0;
    e.message=evoShort(obj,"Forslag klart til vurdering");
  }
  cJSON_Delete(obj);cJSON_Delete(envelope);redrawRequested_=true;
}
void FireOS::noteEvolutionJob(LuaHardwareJob& job) {
  if (!job.id || job.state==0 || job.evolutionCounted) return;
  job.evolutionCounted=true;if (job.state!=2) return; // expected cancellation is not a defect
  const char* op=job.kind==LuaJobKind::Data?"data":job.kind==LuaJobKind::RuntimeAi?"runtime_ai":
      job.kind==LuaJobKind::Bluetooth?"bluetooth":job.kind==LuaJobKind::WifiScan?"wifi":job.kind==LuaJobKind::MicRecord?"mic":
      job.kind==LuaJobKind::I2cScan || job.kind==LuaJobKind::I2cRead || job.kind==LuaJobKind::I2cWrite?"i2c":
      job.kind==LuaJobKind::SpeakerPlay || job.kind==LuaJobKind::SpeakerTone?"speaker":
      job.kind==LuaJobKind::UartRead || job.kind==LuaJobKind::UartWrite?"uart":job.kind==LuaJobKind::SpiTransfer?"spi":"sd";
  evolution_.error(op,job.errorCode.c_str());
}
void FireOS::serviceEvolution() {
  auto& e=evolutionUi_;const uint32_t now=millis();
  const bool storage=sdReady_ && !firmwareBusy() && !luaDataCaptureJob_ && !luaDataStore_.hashingJob() &&
      !aiAudioCaptureActive_ && !(packageManager_ && packageManager_->busy());
  evolution_.service(SD,now,storage);
  if (aiEvolutionNewPending_ && now-aiEvolutionNewAt_>20000) {
    aiEvolutionNewPending_=false;aiWorkflowText_="Appvalg er ikke bekreftet";redrawRequested_=true;
  }
  if (evolution_.pending() && (!e.connectAt || now-e.connectAt>=FireEvolutionContract::kTelemetryIntervalMs)) e.connectAt=now;
  auto& settings=backendSettingsUi_;
  if (settings.request.length() && now-settings.requestAt>20000) {
    settings.request=String();settings.confirming=false;settings.proposalId=String();
    settings.message="Svar mangler. Hent ny status";redrawRequested_=true;
  }
  if (e.request.length() && now-e.requestAt>20000) {e.request=String();e.message="Svar mangler. Hent status";}
  if (e.controlAction=="resume" && e.controlRequest.length() && now-e.controlAt>20000) {
    e.controlRequest=String();e.controlAction=String();e.message="Ukjent utfall. Hent ny status";
  }
  if (!backendClient_ || !backendClient_->sessionReady()) return;
  if (luaAppActive_ && luaPackageId_.length() && e.runtimeApp!=luaPackageId_ && (!e.runtimeAt || now-e.runtimeAt>=5000)) {
    e.runtimeRequest=evoRequest();e.runtimeAt=now;
    if (backendClient_->evolutionStatus(e.runtimeRequest,luaAppId_,"settings",0)) e.runtimeApp=luaPackageId_;
  }
  if (e.runtimeRequest.length() && now-e.runtimeAt>15000) {e.runtimeApp=String();e.runtimeRequest=String();}

  if (e.controlRequest.length() && e.controlAction!="resume" && (!e.controlAt || now-e.controlAt>=5000)) {
    e.controlAt=now;backendClient_->evolutionControl(e.controlRequest,e.controlApp,e.controlAction,e.controlRevision,e.controlJob,e.controlMandate);
  }
  if (!storage || !evolution_.ready()) return;
  if (e.upload.slot<0 && evolution_.pending() && (!e.lastAttemptAt || now-e.lastAttemptAt>=FireEvolutionContract::kTelemetryIntervalMs)) {
    e.lastAttemptAt=now;
    if (evolution_.next(e.upload)) {
      e.policyRequest=evoRequest();e.policyAt=now;e.uploadAllowed=false;e.uploadSent=false;
      if (!backendClient_->evolutionStatus(e.policyRequest,e.upload.app,"settings",0)) e.upload=FireEvolution::Entry();
    }
  }
  if (e.upload.slot>=0 && e.uploadAllowed && !e.uploadSent) {
    const String request="evt-"+e.upload.batch;
    if (backendClient_->evolutionTelemetry(request,e.upload.app,e.upload.package,e.upload.source,e.upload.payload)) {
      evolution_.sent(e.upload,request);e.uploadSent=true;e.lastUploadAt=now;
    }
  }
  if (e.upload.slot>=0 && now-e.policyAt>30000) {e.upload=FireEvolution::Entry();e.policyRequest=String();e.uploadAllowed=false;e.uploadSent=false;}
}

void FireOS::prepareEvolutionOperation(uint8_t index) {
  auto& e=evolutionUi_;
  if (index>=5 || !e.loaded || !e.enabled || !e.flags[index]) return;
  if ((index==0 || index==3) && !e.goal.length()) {
    e.message="Angi målet i AI Developer først";return;
  }
  const char* fallback[]={"","Rett dokumenterte kildefeil og bevar fungerende funksjoner.",
      "Reduser valgt målt ressursbruk. Bevar fungerende funksjoner.","","Evaluer en appavgrenset strategi mot uendrede akseptansekrav."};
  cJSON* body=cJSON_CreateObject();cJSON_AddStringToObject(body,"goal",e.goal.length()?e.goal.c_str():fallback[index]);
  if (e.package.length()) cJSON_AddStringToObject(body,"base_package_id",e.package.c_str());
  if (e.context.length()) cJSON_AddStringToObject(body,"development_context_id",e.context.c_str());
  if (index==2 || index==4) cJSON_AddStringToObject(body,"metric",e.metric.c_str());
  cJSON_AddStringToObject(body,"autonomy",evoModes[e.autonomy]);
  cJSON* config=cJSON_Parse(e.config.c_str());const auto* limits=cJSON_GetObjectItemCaseSensitive(config,"limits");
  if (limits) cJSON_AddItemToObject(body,"limits",cJSON_Duplicate(limits,true));
  const String text=evoCompact(body);cJSON_Delete(body);cJSON_Delete(config);
  prepareEvolution(evoFeatures[index],text);
}

void FireOS::handleEvolutionButton(uint8_t index) {
  auto& e=evolutionUi_;
  const auto page=[&](FireEvolutionUi::Page value) {e.page=value;e.selection=e.scroll=0;};
  if (e.page==FireEvolutionUi::Review || e.page==FireEvolutionUi::Costs) {
    if (index==1) page(e.page==FireEvolutionUi::Costs?FireEvolutionUi::Menu:e.reviewReturn);
    else if (index==2 && e.reviewNext<e.review.length()) e.reviewOffset=e.reviewNext;
    else if (index==0) e.reviewOffset=0;
    redrawRequested_=true;return;
  }
  uint8_t count=e.page==FireEvolutionUi::Menu?(e.permissionRequest.length()?16:15):e.page==FireEvolutionUi::Settings?11:
      e.page==FireEvolutionUi::Autonomy?5:e.page==FireEvolutionUi::Limits?6:e.page==FireEvolutionUi::Operation?6:
      e.page==FireEvolutionUi::Snapshot?e.itemCount+3:e.page==FireEvolutionUi::Metric?e.metricCount+3:3;
  if (index!=1) {e.selection=(e.selection+count+(index==0?-1:1))%count;}
  else if (e.page==FireEvolutionUi::Menu) {
    if (e.selection==0) page(FireEvolutionUi::Operation);
    else if (e.selection==1) {page(FireEvolutionUi::Settings);requestEvolutionView("settings");}
    else if (e.selection==2 || e.selection==4 || e.selection==5) {
      const char* view=e.selection==2?"findings":e.selection==4?"history":"compare";
      page(FireEvolutionUi::Snapshot);requestEvolutionView(view);
    } else if (e.selection==3) {
      if (e.developer) {e.message="Velg den installerte appen i Apps";return;}
      bool safe=e.app.length()>0 && e.app.length()<=64;
      for (size_t i=0;i<e.app.length();++i) {const char c=e.app[i];if (!((c>='a' && c<='z') || (c>='0' && c<='9') || c=='-' || c=='_')) safe=false;}
      if (!safe) {e.message="Appidentitet er ugyldig";return;}
      open(Screen::FileExplorer);sdPath_="/apps/"+e.app+"/appdata/datasets";fileExplorerScanPending_=true;
    } else if (e.selection==6 || e.selection==7) {
      if (e.developer) {e.message="Velg den installerte appen i Apps";return;}
      int found=-1;
      for (uint8_t i=0;i<managerItemCount_;++i) {
        const auto& candidate=managerItems_[i];
        if (candidate.appId==e.app && (candidate.localPackageId.length()?candidate.localPackageId:candidate.packageId)==e.package) {found=i;break;}
      }
      if (found<0) {e.message="Applisten er endret. Velg igjen";return;}
      managerSelection_=found;screen_=Screen::AppsSettings;
      if (e.selection==7) {requestSelectedAppVersions();redrawRequested_=true;return;}
      const auto& item=managerItems_[managerSelection_];
      if (luaAppActive_ && luaPackageId_==item.localPackageId) {
        const char* error=nullptr;if (!queueDataDevelop("feedback","",true,&error)) managerStatus_=error?error:"Tilbakemelding utilgjengelig";
      } else appManagerDevelopConfirm_=9;
    } else if (e.selection==14 && e.permissionRequest.length()) {
      prepareEvolution(e.permissionOperation.c_str(),e.permissionRequest);
    } else if (e.selection==14 || e.selection==15) {
      screen_=e.developer?Screen::AiDeveloper:Screen::AppsSettings;
      if (e.developer) aiProjectPickerActive_=false; // continue this verified Developer project, never create another app
    }
    else if (e.selection==13) requestEvolutionView("summary");
    else if (e.selection==12) {e.review=e.costReview;e.reviewOffset=0;page(FireEvolutionUi::Costs);requestEvolutionView("summary");}
    else {
      const char* action=e.selection==8?"pause":e.selection==9?"resume":e.selection==11?"revoke":"stop";
      if (e.controlRequest.length()) e.message="En handling venter på svar";
      else if (e.loaded && (strcmp(action,"resume") || (backendClient_ && backendClient_->sessionReady()))) {
        e.controlApp=e.app;e.controlRevision=e.revision;e.controlJob=e.job;e.controlMandate=e.mandate;
        e.controlAction=action;e.controlRequest=evoRequest();e.controlAt=0;e.message="Venter på backendkvittering";
        if (!strcmp(action,"resume")) {e.controlAt=millis();backendClient_->evolutionControl(e.controlRequest,e.app,action,e.revision,e.job,e.mandate);}
      } else e.message="Hent ny status først";
    }
  } else if (e.page==FireEvolutionUi::Settings) {
    if (!e.loaded) {e.message="Hent innstillinger først";}
    else if (e.selection==0) {e.enabled=!e.enabled;e.message="Ulagrede valg. Vurder endringer";}
    else if (e.selection<=5) {e.flags[e.selection-1]=!e.flags[e.selection-1];e.message="Ulagrede valg. Vurder endringer";}
    else if (e.selection==6) page(FireEvolutionUi::Autonomy);
    else if (e.selection==7) {e.consent=!e.consent;e.message="Ulagrede valg. Vurder endringer";
      if (!e.consent) {e.acknowledgedConsent=false;evolution_.consent(e.app,false,millis());}}
    else if (e.selection==8) page(FireEvolutionUi::Limits);
    else if (e.selection==9) {
      cJSON* config=cJSON_Parse(e.config.c_str());
      if (config) {
        cJSON_ReplaceItemInObjectCaseSensitive(config,"enabled",cJSON_CreateBool(e.enabled));
        cJSON_ReplaceItemInObjectCaseSensitive(config,"telemetry_consent",cJSON_CreateBool(e.consent));
        cJSON_ReplaceItemInObjectCaseSensitive(config,"autonomy",cJSON_CreateString(evoModes[e.autonomy]));
        cJSON* flags=cJSON_GetObjectItemCaseSensitive(config,"flags");
        for (uint8_t i=0;i<5;++i) cJSON_ReplaceItemInObjectCaseSensitive(flags,evoFeatures[i],cJSON_CreateBool(e.flags[i]));
        const String body=evoCompact(config);cJSON_Delete(config);prepareEvolution("configure",body);
      }
    } else page(FireEvolutionUi::Menu);
  } else if (e.page==FireEvolutionUi::Autonomy) {
    if (e.selection<4) {e.autonomy=e.selection;e.message="Ulagrede valg. Vurder endringer";}
    page(FireEvolutionUi::Settings);
  } else if (e.page==FireEvolutionUi::Limits) {
    cJSON* config=cJSON_Parse(e.config.c_str());cJSON* limits=cJSON_GetObjectItemCaseSensitive(config,"limits");
    if (e.selection<5 && cJSON_IsObject(limits)) {
      const char* keys[]={"budget_usd","max_builds","max_generations_per_build","mandate_ttl_days","daily_app_budget_usd"};
      const cJSON* old=cJSON_GetObjectItemCaseSensitive(limits,keys[e.selection]);
      const double value=cJSON_IsNumber(old)?old->valuedouble:0;
      double next=value;
      if (e.selection==0 || e.selection==4) next=value<.5?.5:value<1?1:value<2?2:value<5?5:.25;
      else if (e.selection==1) next=value<2?2:value<3?3:value<4?4:value<8?8:1;
      else if (e.selection==2) next=value<2?2:value<3?3:value<4?4:1;
      else next=value<3?3:value<7?7:1;
      cJSON_ReplaceItemInObjectCaseSensitive(limits,keys[e.selection],cJSON_CreateNumber(next));e.config=evoCompact(config);e.message="Ulagrede valg. Vurder endringer";
    } else page(FireEvolutionUi::Settings);
    cJSON_Delete(config);
  } else if (e.page==FireEvolutionUi::Operation) {
    if (e.selection==5) page(FireEvolutionUi::Menu);
    else if (!e.enabled || !e.flags[e.selection]) e.message="Slå på egenskapen først";
    else {
      if (e.selection==2 || e.selection==4) {
        if (!e.metricCount) {e.message="Ingen mål hentet. Oppdater status";return;}
        e.operation=evoFeatures[e.selection];page(FireEvolutionUi::Metric);
      } else prepareEvolutionOperation(e.selection);
    }
  } else if (e.page==FireEvolutionUi::Metric) {
    if (e.selection<e.metricCount) {e.metric=e.metricIds[e.selection];prepareEvolutionOperation(e.operation=="optimize"?2:4);}
    else if (e.selection==e.metricCount) {if (e.metricHasMore) {e.selection=e.scroll=0;requestEvolutionView("settings",e.metricOffset+4);}}
    else if (e.selection==e.metricCount+1) {if (e.metricOffset) {e.selection=e.scroll=0;requestEvolutionView("settings",e.metricOffset>=4?e.metricOffset-4:0);}}
    else page(FireEvolutionUi::Operation);
  } else if (e.page==FireEvolutionUi::Snapshot) {
    if (e.selection<e.itemCount) {
      e.selectedItem=e.itemIds[e.selection];e.review=(e.view=="compare" && e.comparisonReview.length()?e.comparisonReview:e.itemReviews[e.selection])+"\nID: "+e.selectedItem;e.reviewOffset=0;e.reviewReturn=FireEvolutionUi::Snapshot;
      page(e.view=="history"?FireEvolutionUi::Strategy:FireEvolutionUi::Review);
    }
    else if (e.selection==e.itemCount) {if (e.hasMore) {e.selection=e.scroll=0;requestEvolutionView(e.view.c_str(),e.offset+FireEvolutionContract::kPageItems);}}
    else if (e.selection==e.itemCount+1) {if (e.offset) {e.selection=e.scroll=0;requestEvolutionView(e.view.c_str(),e.offset>=4?e.offset-4:0);}}
    else page(FireEvolutionUi::Menu);
  } else if (e.page==FireEvolutionUi::Strategy) {
    if (e.selection==2) page(FireEvolutionUi::Snapshot);
    else {
      cJSON* obj=cJSON_CreateObject();cJSON_AddStringToObject(obj,"strategy_id",e.selectedItem.c_str());const String body=evoCompact(obj);cJSON_Delete(obj);
      prepareEvolution(e.selection==0?"strategy_app":"strategy_owner",body);
    }
  } else if (e.page==FireEvolutionUi::Proposal) {
    if (e.selection==0) {e.reviewOffset=0;e.reviewReturn=FireEvolutionUi::Proposal;page(FireEvolutionUi::Review);}
    else if (e.selection==2) {e.proposalId=String();page(FireEvolutionUi::Menu);}
    else if (!e.proposalId.length() || !backendCommandUnexpired(e.expiresAt)) e.message="Forslaget er utløpt";
    else if (backendClient_ && backendClient_->sessionReady()) {
      e.request=evoRequest();e.requestAt=millis();
      if (backendClient_->evolutionConfirm(e.request,e.app,e.proposalId,e.proposalRevision)) {e.proposalId=String();page(FireEvolutionUi::Menu);e.message="Venter på bekreftelse";}
    } else e.message="Backend er frakoblet";
  }
  if (e.selection<e.scroll) e.scroll=e.selection;
  if (e.selection>=e.scroll+4) e.scroll=e.selection-3;
  redrawRequested_=true;
}

void FireOS::drawEvolution() {
  auto& e=evolutionUi_;drawStatusBar("Evolution");
  uint16_t at=0;
  for (uint8_t i=0;i<2 && at<e.name.length();++i) {const String line=evoLine(e.name,at);FireUI::text(ui,14,34+i*15,line.c_str(),kText,"ui12b",292);}
  if (e.page==FireEvolutionUi::Review || e.page==FireEvolutionUi::Costs) {
    uint16_t offset=e.reviewOffset;
    for (uint8_t row=0;row<7 && offset<e.review.length();++row) {const String line=evoLine(e.review,offset);FireUI::text(ui,14,76+row*19,line.c_str(),kText,"ui12",292);}
    e.reviewNext=offset;drawFooter("Start","Tilbake","Neste");return;
  }
  const char* menu[]={"Forbedre nå","Innstillinger","Funn","Målinger","Historikk","Sammenlign","Tilbakemelding","Versjoner / rollback","Pause","Gjenoppta","Stopp","Tilbakekall mandat","Kostnad","Oppdater status","Tilbake"};
  const char* settings[]={"Evolution","Generate","Repair","Optimize","Expand","Evolve","Autonomi","Telemetri","Mandatgrenser","Vurder endringer","Tilbake"};
  const char* operations[]={"Generate","Repair","Optimize","Expand","Evolve","Tilbake"};
  const char* proposal[]={"Vis hele grunnlaget","Godkjenn forslaget","Avvis"};
  const char* strategy[]={"Strategi for denne appen","Global strategi","Tilbake"};
  const uint8_t count=e.page==FireEvolutionUi::Menu?(e.permissionRequest.length()?16:15):e.page==FireEvolutionUi::Settings?11:e.page==FireEvolutionUi::Operation?6:
      e.page==FireEvolutionUi::Autonomy?5:e.page==FireEvolutionUi::Limits?6:e.page==FireEvolutionUi::Snapshot?e.itemCount+3:e.page==FireEvolutionUi::Metric?e.metricCount+3:3;
  for (uint8_t row=0;row<4 && e.scroll+row<count;++row) {
    const uint8_t index=e.scroll+row;String label,value;
    if (e.page==FireEvolutionUi::Menu) label=index==14 && e.permissionRequest.length()?"Vurder tillatelser":index==15?"Tilbake":menu[index];
    else if (e.page==FireEvolutionUi::Settings) {
      label=settings[index];
      if (!index) value=e.enabled?"På":"Av";
      else if (index<=5) value=e.flags[index-1]?"På":"Av";
      else if (index==6) value=evoModeNames[e.autonomy];
      else if (index==7) value=e.consent?"Tillatt":"Av";
    } else if (e.page==FireEvolutionUi::Autonomy) label=index<4?evoModeNames[index]:"Tilbake";
    else if (e.page==FireEvolutionUi::Operation) label=operations[index];
    else if (e.page==FireEvolutionUi::Metric) label=index<e.metricCount?e.metricLabels[index]:index==e.metricCount?"Neste side":index==e.metricCount+1?"Forrige side":"Tilbake";
    else if (e.page==FireEvolutionUi::Proposal) label=proposal[index];
    else if (e.page==FireEvolutionUi::Strategy) label=strategy[index];
    else if (e.page==FireEvolutionUi::Limits) {
      const char* labels[]={"USD per mandat","Kandidatbygg","Forsøk per bygg","Gyldig i dager","USD per app per dag","Tilbake"};label=labels[index];
      if (index<5) {cJSON* config=cJSON_Parse(e.config.c_str());const auto* limits=cJSON_GetObjectItemCaseSensitive(config,"limits");
        const char* keys[]={"budget_usd","max_builds","max_generations_per_build","mandate_ttl_days","daily_app_budget_usd"};const auto* v=cJSON_GetObjectItemCaseSensitive(limits,keys[index]);
        if (cJSON_IsNumber(v)) value=String(v->valuedouble,index==0?2:0);cJSON_Delete(config);}
    } else if (e.page==FireEvolutionUi::Snapshot) {
      label=index<e.itemCount?e.itemLabels[index]:index==e.itemCount?"Neste side":index==e.itemCount+1?"Forrige side":"Tilbake";
    }
    const int y=78+row*30;const bool selected=index==e.selection;
    if (selected) drawSelection(8,y-2,304,28,kCyan);
    FireUI::text(ui,16,y,label.c_str(),kText,"ui12",value.length()?190:290);
    if (value.length()) FireUI::text(ui,208,y,value.c_str(),kCyan,"ui12",94,2);
  }
  const String status=evolution_.status()[0]?String(evolution_.status()):e.message;
  FireUI::text(ui,14,207,status.c_str(),kMuted,"small10",292);
  drawFooter("Forrige","Velg","Neste");
}
