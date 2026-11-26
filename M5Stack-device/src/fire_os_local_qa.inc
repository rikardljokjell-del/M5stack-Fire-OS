// UART is inert unless authenticated during the one boot window. All larger QA
// buffers live in PSRAM and cannot displace the strict TLS internal buffers.
struct FireOS::LocalQa {
  fire_local_qa::Policy policy;
  fire_local_qa::LineReader reader;
  fire_local_qa::Snapshot presented;
  char tx[fire_local_qa::kMaxWireBytes]={};
  uint16_t txAt=0,txBytes=0;
  uint32_t bootTag=0;
};
namespace {
constexpr char kQaPackage[]="build-67b5836c92034bebb8f0";
constexpr char kQaSource[]="386d02a8cec3a6d211c793aff3c51a1f97929b7543d8764e037401448cc188b2";
void qaHex(const uint8_t* bytes,size_t n,char* out) {
  const char* h="0123456789abcdef";
  for(size_t i=0;i<n;++i){out[i*2]=h[bytes[i]>>4];out[i*2+1]=h[bytes[i]&15];}out[n*2]=0;
}
void qaText(char* out,size_t capacity,const String& text) {
  size_t n=min<size_t>(capacity-1,text.length());
  // Never split a UTF-8 code point in the safe visible row label.
  while(n && n<text.length() && (uint8_t(text[n])&0xc0)==0x80)--n;
  for(size_t i=0;i<n;++i)out[i]=uint8_t(text[i])<32?' ':text[i];out[n]=0;
}
}
bool FireOS::localQaSign(void* context,const char* body,size_t size,char* mac) {
  auto* os=static_cast<FireOS*>(context);
  if(!os || os->backendToken_.length()<24) return false;
  uint8_t digest[32];const auto* info=mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  if(!info || mbedtls_md_hmac(info,reinterpret_cast<const uint8_t*>(os->backendToken_.c_str()),
      os->backendToken_.length(),reinterpret_cast<const uint8_t*>(body),size,digest))return false;
  qaHex(digest,sizeof(digest),mac);return true; // Policy already prepended the domain.
}
bool FireOS::localQaVerify(void* context,const char* body,size_t size,const char* mac) {
  char expected[65];return localQaSign(context,body,size,expected) && fire_local_qa::equal(expected,mac,64);
}
void FireOS::beginLocalQa() {
  if(localQaAttempted_)return; // Never reopen after a failed allocation or wake.
  localQaAttempted_=true;
  void* memory=heap_caps_malloc(sizeof(LocalQa),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
  if(!memory)return;
  localQa_=new(memory) LocalQa();
  const String boot=backendClient_?backendClient_->bootId():String();uint8_t hash[32]={};
  mbedtls_sha256_ret(reinterpret_cast<const uint8_t*>(boot.c_str()),boot.length(),hash,0);
  localQa_->bootTag=(uint32_t(hash[0])<<24)|(uint32_t(hash[1])<<16)|(uint32_t(hash[2])<<8)|hash[3];
  uint8_t nonce[16];char hex[33];esp_fill_random(nonce,sizeof(nonce));qaHex(nonce,sizeof(nonce),hex);
  fire_local_qa::Callbacks cb;cb.context=this;cb.verify=localQaVerify;cb.sign=localQaSign;
  cb.snapshot=localQaRead;cb.action=localQaAct;cb.stop=localQaStop;
  localQa_->policy.begin(millis(),hex,cb);
}
void FireOS::localQaStop(void* context) {
  auto* os=static_cast<FireOS*>(context);if(!os || !os->localQa_)return;
  os->localQa_->reader.clear(); // STOP never cancels a user's production app/job.
}
bool FireOS::localQaRead(void* context,fire_local_qa::Snapshot& out) {
  auto* os=static_cast<FireOS*>(context);if(!os || !os->localQa_ || !os->localQa_->presented.presented)return false;
  out=os->localQa_->presented;return true;
}
void FireOS::localQaSnapshot(fire_local_qa::Snapshot& out) const {
  out=fire_local_qa::Snapshot();out.screen=uint16_t(screen_);out.context=inputContext_;out.view=buttonView();
  out.busy=downloadPhase_==1 || downloadPhase_==2 || (packageManager_ && packageManager_->busy());
  String label,detail;
  if(appUpdateStage_) {
    out.index=appUpdateSelection_;out.count=appUpdateStage_==1?3:1;
    label=appUpdateStage_==1?(appUpdateSelection_==0?"Ja":appUpdateSelection_==1?"Nei":"Ikke spør igjen"):
      appUpdateStage_==2?"Minimer":"Åpne oppdatert app";detail=appUpdateFailure_?"Nedlasting mislyktes":"Oppdatering";
  } else if(buildNoticeActive_) {out.count=1;label="Appen er klar";detail=buildNoticeName_;}
  else switch(screen_) {
    case Screen::Main: {
      out.index=mainIndex_;out.count=kSystemMainCount+luaAppCount_;
      const char* titles[]={"Apps","Settings","Power","Files","AI Developer","Home"};
      label=mainIndex_<kSystemMainCount?String(titles[mainIndex_]):mainIndex_-kSystemMainCount<luaAppCount_?luaAppDisplayNames_[mainIndex_-kSystemMainCount]:String();break;
    }
    case Screen::Settings: {
      const char* titles[]={"Date / Time","Display & Sound","Wi-Fi","Bluetooth","File Explorer","Boot","Firmware","Menu Layout","Shortcuts","App Manager","Debug","System Info","Help","Factory Reset","Backend / AI","Power","Back"};
      out.index=settingsIndex_;out.count=kSettingsCount;label=titles[min<uint8_t>(settingsIndex_,kSettingsCount-1)];break;
    }
    case Screen::AppsSettings:
      detail=managerStatus_;
      if(downloadPhase_==1 || downloadPhase_==2 || (packageManager_ && packageManager_->busy())) {label=packageTransferLabel();out.count=1;out.busy=true;}
      else if(appManagerVersionsWaiting_ || appManagerDeleteWaiting_){label="Vennligst vent";out.count=1;out.busy=true;}
      else if(appManagerDevelopConfirm_){label="Start app";out.count=1;}
      else if(appManagerDeleteConfirm_){label="Confirm delete";out.count=1;}
      else if(appManagerVersionDialog_){out.index=appManagerVersionSelection_;out.count=appManagerVersionCount_+1;label=out.index<appManagerVersionCount_?appManagerVersionLabels_[out.index]:String("Back");}
      else if(appManagerActionMenu_){out.index=appManagerActionIndex_;out.count=appManagerActionCount_;label=out.index<out.count?appManagerActionLabels_[out.index]:String();}
      else {out.index=managerSelection_;out.count=managerItemCount_+1;label=out.index<managerItemCount_?managerItems_[out.index].name:String("Back");}break;
    case Screen::Apps:
      out.index=externalAppSelection_;out.count=externalAppCount_+luaAppCount_+1;
      label=out.index<externalAppCount_?externalAppNames_[out.index]:out.index<out.count-1?luaAppDisplayNames_[out.index-externalAppCount_]:String("Back");break;
    case Screen::AiDeveloper:
      detail=aiWorkflowText_;
      if(aiProjectPickerActive_) {
        out.index=aiProjectSelection_;
        if(aiPickerPage_==fire_ai_menu::Page::Jobs) {
          out.count=buildJobCount_+(buildJobsOffset_?1:0)+(buildJobsNext_?1:0)+1;
          if(out.index<buildJobCount_)label=buildJobNames_[out.index];
          else {uint8_t at=buildJobCount_;if(buildJobsOffset_ && out.index==at++)label="Forrige side";
            else if(buildJobsNext_ && out.index==at)label="Neste side";else label="Back";}
        } else if(aiPickerPage_==fire_ai_menu::Page::Job || aiPickerPage_==fire_ai_menu::Page::Work) {
          fire_ai_menu::JobAction actions[5];out.count=fire_ai_menu::actions(aiPickerPage_==fire_ai_menu::Page::Work,aiJobCanResume_,aiJobCanDelete_,aiJobCanPause_,aiJobCanContext_,actions,aiJobCanOpen_);
          if(out.index<out.count)label=fire_ai_menu::actionLabel(actions[out.index]);
        } else {
          out.count=fire_ai_menu::count(aiPickerPage_,false,0,luaAppCount_);
          const auto item=fire_ai_menu::at(aiPickerPage_,out.index,false,0,luaAppCount_);
          switch(item.kind) {
            case fire_ai_menu::Kind::Jobs:label="Resume bygging";break;
            case fire_ai_menu::Kind::SelectApp:label="Select app";break;
            case fire_ai_menu::Kind::Back:label="Back";break;
            case fire_ai_menu::Kind::Settings:label="Settings";break;
            case fire_ai_menu::Kind::App:label=luaAppDisplayNames_[item.index];break;
            default:label="Unavailable in local QA";break;
          }
        }
      } else {out.count=1;label=aiWorkflowState_==5?"Kjør app":aiWorkflowState_==3?"Build proposal":"Developer";}break;
    case Screen::LuaApp:out.count=1;label=luaAppActive_?"App running":luaErrorAction_?"Kjør rettet app":"Fiks feil";detail=luaRepairMessage_;out.error=luaAppActive_?0:1;break;
    case Screen::QuickSettings: {
      const char* labels[]={"Brightness","Volume","Wi-Fi","Bluetooth","Backend-sync","SD card","Power","All settings","Back"};
      out.index=quickIndex_;out.count=kQuickCount;label=labels[min<uint8_t>(quickIndex_,kQuickCount-1)];detail=backendStatus_;break;
    }
    case Screen::AiApi:out.index=detailIndex_;out.count=4;label=detailIndex_==0?"Backend sync":detailIndex_==1?"Backend config":detailIndex_==3?"Back":"Backend status";detail=backendStatus_;break;
    default:label="Navigation only";break;
  }
  qaText(out.label,sizeof(out.label),label);
  const bool online=backendClient_ && backendClient_->sessionReady();
  const bool publicProfile=fireNetworkHost(backendHost_)=="fire-device.ljoekjell.no" && backendPort_==443 && fireNetworkTls(backendHost_,backendPort_);
  const bool current=online && backendCatalogAt_ && fire_app_updates::knownEpoch(backendClient_->connectionEpoch(),backendCatalogEpoch_);
  snprintf(out.detail,sizeof(out.detail),"B%uW%uR%uP%uC%uE%uL%uD%uT%08lx",unsigned(backendMode_),unsigned(wifiMode_),unsigned(online),unsigned(publicProfile),
      unsigned(backendAppCount_),unsigned(current),unsigned(backendCatalogLoading_),unsigned(downloadPhase_),static_cast<unsigned long>(localQa_?localQa_->bootTag:0));
  // Index and label bind the shown row as well as the existing confirmation ID.
  const String identity=String(out.view)+"|"+String(out.index)+"|"+label+"|"+buttonViewIdentity();
  uint8_t hash[32];mbedtls_sha256_ret(reinterpret_cast<const uint8_t*>(identity.c_str()),identity.length(),hash,0);qaHex(hash,32,out.identity);
}
void FireOS::presentLocalQa() {
  if(!localQa_ || (localQa_->presented.presented && !localQa_->policy.armed(millis())))return;
  const uint32_t presented=localQa_->presented.presented+1;
  localQaSnapshot(localQa_->presented);localQa_->presented.presented=presented?presented:1;
}
bool FireOS::localQaActionAllowed(uint8_t button,bool hold) const {
  if(wifiSetupActive_ || portalApplying_ || screen_==Screen::Home || screen_==Screen::Evolution || luaDevelopJob_)return false;
  const auto safeLocal=[&](const String& package,const String& source){return package==kQaPackage && source==kQaSource;};
  const auto safeInstalled=[&](const String& package) {
    for(uint8_t i=0;i<luaAppCount_;++i) if(luaAppPackageIds_[i]==package && safeLocal(package,luaAppChecksums_[i])) return true;
    return false;
  };
  const bool publicProfile=fireNetworkHost(backendHost_)=="fire-device.ljoekjell.no" && backendPort_==443 && fireNetworkTls(backendHost_,backendPort_);
  if(!publicProfile && (screen_==Screen::AppsSettings || screen_==Screen::AiDeveloper || screen_==Screen::AiApi || screen_==Screen::LuaApp || appUpdateStage_))return false;
  if(screen_==Screen::LuaApp && luaAppActive_ && !safeLocal(luaPackageId_,luaSourceHash_))return false;
  if(hold)return button==1 || button==2; // No Home/boot-app shortcut.
  if(appUpdateStage_)return button!=1 || appUpdateSelection_==1 || (appUpdateCandidate_==kQaPackage && (appUpdateStage_!=3 || safeInstalled(appUpdateCandidate_)));
  if(buildNoticeActive_)return button==2; // Opening arbitrary build notices can RUN.
  if(button!=1) {
    if(screen_==Screen::AiDeveloper && !aiProjectPickerActive_ && button==0 && aiWorkflowState_==5)
      return aiReadyPackageId_==kQaPackage && (aiJobNeedsInstall_ || safeInstalled(aiReadyPackageId_));
    return screen_!=Screen::FactoryReset && screen_!=Screen::Power && screen_!=Screen::Firmware && screen_!=Screen::FileExplorer;
  }
  switch(screen_) {
    case Screen::Main:return mainIndex_==0 || mainIndex_==1 || mainIndex_==4 ||
      (mainIndex_>=kSystemMainCount && mainIndex_-kSystemMainCount<luaAppCount_ && safeLocal(luaAppPackageIds_[mainIndex_-kSystemMainCount],luaAppChecksums_[mainIndex_-kSystemMainCount]));
    case Screen::Settings:return settingsIndex_==9 || settingsIndex_==14 || settingsIndex_==12;
    case Screen::QuickSettings:return quickIndex_==4 || quickIndex_==7 || quickIndex_==8 || (quickIndex_==2 && publicProfile && wifiSsid_.length());
    case Screen::AiApi:return detailIndex_==0 || detailIndex_==3;
    case Screen::Apps:return externalAppSelection_>=externalAppCount_ && (externalAppSelection_>=externalAppCount_+luaAppCount_ || safeLocal(luaAppPackageIds_[externalAppSelection_-externalAppCount_],luaAppChecksums_[externalAppSelection_-externalAppCount_]));
    case Screen::AppsSettings:
      if(appManagerDeleteConfirm_ || appManagerDevelopConfirm_ || appManagerDeleteWaiting_)return false;
      if(appManagerVersionDialog_)return appManagerVersionSelection_>=appManagerVersionCount_ || appManagerVersionPackageIds_[appManagerVersionSelection_]==kQaPackage;
      if(appManagerActionMenu_) {
        const uint8_t code=appManagerActionCodes_[appManagerActionIndex_];
        return code==2 || code==5 || code==11 || (code==1 && safeInstalled(managerTarget_.localPackageId) && managerTarget_.appId.length());
      }return true;
    case Screen::AiDeveloper:
      if(backendSettingsUi_.page!=FireBackendSettingsUi::None)return false;
      if(aiProjectPickerActive_) {
        if(aiPickerPage_==fire_ai_menu::Page::Jobs)return true;
        if(aiPickerPage_==fire_ai_menu::Page::Job || aiPickerPage_==fire_ai_menu::Page::Work) {
          fire_ai_menu::JobAction actions[5];const uint8_t n=fire_ai_menu::actions(aiPickerPage_==fire_ai_menu::Page::Work,aiJobCanResume_,aiJobCanDelete_,aiJobCanPause_,aiJobCanContext_,actions,aiJobCanOpen_);
          return aiProjectSelection_<n && (actions[aiProjectSelection_]==fire_ai_menu::JobAction::Open || actions[aiProjectSelection_]==fire_ai_menu::JobAction::Back || actions[aiProjectSelection_]==fire_ai_menu::JobAction::Background || actions[aiProjectSelection_]==fire_ai_menu::JobAction::Cancel);
        }
        const auto item=fire_ai_menu::at(aiPickerPage_,aiProjectSelection_,false,0,luaAppCount_);
        return item.kind==fire_ai_menu::Kind::Jobs || item.kind==fire_ai_menu::Kind::Back || item.kind==fire_ai_menu::Kind::SelectApp;
      }return false; // No BUILD/model/voice action through unattended QA.
    case Screen::LuaApp:return luaAppActive_?safeLocal(luaPackageId_,luaSourceHash_):luaErrorAction_==1 && luaRepairReadyPackageId_==kQaPackage;
    case Screen::Help:return true;
    default:return false;
  }
}
fire_local_qa::Code FireOS::localQaAct(void* context,const fire_local_qa::Command& command,fire_local_qa::Snapshot& out) {
  auto* os=static_cast<FireOS*>(context);if(!os || !os->localQa_)return fire_local_qa::Code::Unavailable;
  fire_local_qa::Snapshot current;os->localQaSnapshot(current);
  if(current.context!=out.context || current.view!=out.view || !fire_local_qa::equal(current.identity,out.identity,64))return fire_local_qa::Code::Stale;
  const bool hold=command.op==fire_local_qa::Op::Hold;
  if(!os->localQaActionAllowed(command.button,hold))return fire_local_qa::Code::Blocked;
  fire_buttons::Event event;event.kind=fire_buttons::Kind::Click;event.context=command.context;
  if(command.button==1 && !hold && !fire_buttons::visibleClick(event,os->inputContext_,os->buttonView(),os->inputShownView_,os->buttonViewIdentity()==os->inputShownIdentity_))return fire_local_qa::Code::Stale;
  os->lastActivity_=millis();os->onButton(command.button,hold); // Same production handler and confirmations.
  out=os->localQa_->presented;return fire_local_qa::Code::Ok;
}
void FireOS::serviceLocalQa() {
  if(!localQa_)return;auto& q=*localQa_;q.policy.tick(millis());
  if(q.txAt<q.txBytes) {
    const size_t count=min<size_t>(64,min<size_t>(Serial.availableForWrite(),q.txBytes-q.txAt));
    if(count)q.txAt+=Serial.write(reinterpret_cast<const uint8_t*>(q.tx+q.txAt),count);
    return; // Do not overwrite a pending authenticated reply.
  }
  for(unsigned n=0;n<128 && Serial.available();++n) {
    const auto result=q.reader.feed(Serial.read());
    if(result==fire_local_qa::LineReader::Result::Ready) {
      q.txAt=q.txBytes=0;
      const bool wasArmed=q.policy.armed(millis());
      if(q.policy.handle(q.reader.data(),q.reader.size(),millis(),q.tx,sizeof(q.tx))) {
        if(!wasArmed && q.policy.armed(millis()))redrawRequested_=true;
        q.txBytes=strlen(q.tx); // Policy already terminates the signed line with LF.
      }
      q.reader.clear();return;
    }
    if(result==fire_local_qa::LineReader::Result::Rejected)return;
  }
}
