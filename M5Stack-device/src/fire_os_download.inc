// One production download intent shared by repair, jobs, App Manager and updates.
// An offer is authority from the backend, not authority to retain a cancelled RUN.
void FireOS::downloadIntentStatus(const String& text) {
  managerStatus_=text;
  if(downloadPackage_==luaRepairReadyPackageId_) luaRepairMessage_=text;
  if(downloadPackage_==aiReadyPackageId_ || downloadPackage_==aiPackageId_) aiWorkflowText_=text;
  redrawRequested_=true;
}

bool FireOS::requestAppDownload(const String& project,const String& package,const String& app,bool runAfter) {
  if(downloadPhase_==1 || downloadPhase_==2 || (packageManager_ && packageManager_->busy())) {
    downloadIntentStatus("En appoverføring pågår");if(package==luaRepairReadyPackageId_) luaRepairMessage_=managerStatus_;return false;
  }
  if(!backendClient_ || !backendClient_->sessionReady()) {
    downloadIntentStatus("Backend er ikke tilkoblet");if(package==luaRepairReadyPackageId_) luaRepairMessage_=managerStatus_;return false;
  }
  downloadRequest_="dl-"+String(esp_random(),HEX)+"-"+String(esp_random(),HEX);
  downloadProject_=project;downloadApp_=app;downloadPackage_=package;
  downloadSession_=backendClient_->sessionId();downloadBoot_=backendClient_->bootId();
  downloadRequestedAt_=millis();downloadPhase_=1;
  if(runAfter) userRunAfterInstall_=package;
  downloadIntentStatus("Ber om appoverføring");
  if(backendClient_->appDownload(project,package,app,downloadRequest_)) return true;
  cancelAppDownload();downloadIntentStatus("Forespørselen kunne ikke sendes");return false;
}

void FireOS::cancelAppDownload() {
  // Synchronous revocation precedes asynchronous worker/socket cleanup and ACKs.
  if(userRunAfterInstall_==downloadPackage_) userRunAfterInstall_=String();
  if(downloadPhase_==2 && packageManager_ && packageManager_->packageId()==downloadPackage_)
    packageManager_->cancel();
  downloadPhase_=3;
  if(appUpdateCandidate_==downloadPackage_ && appUpdateStage_==2) {
    appUpdateStage_=1;appUpdateFailure_=1;appUpdateSelection_=1;
  }
  downloadIntentStatus("Appoverføringen er avbrutt");
}

void FireOS::serviceDownloadIntent() {
  if(downloadPhase_!=1 && downloadPhase_!=2) return;
  const bool scopeChanged=backendClient_ && backendClient_->sessionReady() &&
    (backendClient_->sessionId()!=downloadSession_ || backendClient_->bootId()!=downloadBoot_);
  if(scopeChanged || (downloadPhase_==1 && uint32_t(millis()-downloadRequestedAt_)>=15000)) {
    cancelAppDownload();downloadIntentStatus(scopeChanged?"Appvalget må bekreftes på nytt":"Ingen overføring mottatt. Prøv igjen.");
  }
}

bool FireOS::handleDownloadIntent(const String& message) {
  if(!downloadRequest_.length() || jsonStringField(message,"event_id")!=downloadRequest_) return false;
  const String type=jsonStringField(message,"type");
  if(type!="event_ack" && type!="error") return false;
  if(downloadPhase_!=1 && downloadPhase_!=2) return true; // cancelled/late ACK has no effect
  cJSON* reply=cJSON_Parse(message.c_str());
  const cJSON* result=cJSON_GetObjectItemCaseSensitive(reply,"result");
  const String outer=aiJobText(reply,"status"),status=aiJobText(result,"status");
  const bool failed=type=="error" || (outer!="accepted" && outer!="duplicate") ||
    cJSON_GetObjectItemCaseSensitive(result,"error") || status=="failed" || status=="rejected";
  cJSON_Delete(reply);
  if(failed) {cancelAppDownload();downloadIntentStatus("Appoverføringen ble avvist. Prøv igjen.");}
  else if(downloadPhase_==1 && status=="awaiting_device_install") downloadIntentStatus("Venter på appoverføring");
  return true;
}

bool FireOS::handleFeedbackAck(const String& message) {
  if(!luaFeedbackAck_.length() || jsonStringField(message,"event_id")!=luaFeedbackAck_)return false;
  const String type=jsonStringField(message,"type");if(type!="event_ack" && type!="error")return false;
  cJSON* reply=cJSON_Parse(message.c_str());const cJSON* result=cJSON_GetObjectItemCaseSensitive(reply,"result");
  const String status=aiJobText(reply,"status");
  const bool confirmed=type=="event_ack" && (status=="accepted" || status=="duplicate") &&
    aiJobText(result,"status")=="recorded" && aiJobText(result,"context_id")==luaDevelopContext_ &&
    aiJobText(result,"observation_action")==luaFeedbackOutcome_ && !cJSON_GetObjectItemCaseSensitive(result,"error") &&
    luaFeedbackAck_=="obs-"+luaDevelopContext_+"-"+luaFeedbackOutcome_;
  cJSON_Delete(reply);luaFeedbackAck_=String();luaFeedbackConfirmation_=!confirmed;
  if(!confirmed)luaFeedbackOutcome_="unconfirmed";redrawRequested_=true;return true;
}
