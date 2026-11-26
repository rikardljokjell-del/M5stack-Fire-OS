namespace {
const char* const settingRoles[]={"dialog_model","code_model","review_model","transcribe_model","speech_model","runtime_model"};
const char* const settingRoleNames[]={"Dialog","Kode","Review","Tale til tekst","Talesvar","Runtime AI"};
const char* const settingLimits[]={"cost_limits_enabled","daily_budget_usd","build_budget_usd","request_budget_usd","runtime_ai_limits_enabled",
    "runtime_ai_request_budget_usd","runtime_ai_daily_budget_usd","runtime_ai_daily_calls","evolution_cost_limits_enabled"};
const char* const settingLimitNames[]={"Pengegrenser","USD per dag","USD per bygg","USD per forespørsel","Runtime AI pengegrenser",
    "Runtime AI USD per kall","Runtime AI USD per dag","Runtime AI kall per dag","Evolution pengegrenser"};
String settingLabel(const String& name) {
  for (uint8_t i=0;i<6;++i) if (name==settingRoles[i]) return settingRoleNames[i];
  for (uint8_t i=0;i<9;++i) if (name==settingLimits[i]) return settingLimitNames[i];
  if (name=="runtime_ai_enabled") return "Runtime AI aktiv";
  if (name=="runtime_ai_developer_mode") return "Runtime AI i Developer";
  return String();
}
String settingValue(const cJSON* value) {
  if (cJSON_IsTrue(value)) return "På";
  if (cJSON_IsFalse(value)) return "Av";
  if (cJSON_IsString(value)) return String(value->valuestring);
  if (cJSON_IsNumber(value)) return evoCompact(value);
  return "Ukjent";
}
String usagePrice(const cJSON* row) {
  const String kind=evoText(row,"price_kind");
  const auto* actual=cJSON_GetObjectItemCaseSensitive(row,"provider_calculated_usd");
  const auto* estimate=cJSON_GetObjectItemCaseSensitive(row,"empirical_estimated_usd");
  if ((kind=="provider" || kind=="duration") && cJSON_IsNumber(actual)) return "Beregnet pris USD "+String(actual->valuedouble,6);
  if (kind=="empirical" && cJSON_IsNumber(estimate)) return "Ukjent pris; anslag USD "+String(estimate->valuedouble,6);
  return kind=="pending"?String("Pågår; pris er ikke klar"):String("Pris ukjent");
}
String usageDetails(const cJSON* row) {
  String text="App: "+evoText(row,"app_name")+"\nProsjekt: "+evoText(row,"project_id")+"\nBygg: "+evoText(row,"build_id")+
      "\nOperasjon: "+evoText(row,"operation")+"\nModell: "+evoText(row,"model")+"\nStatus: "+evoText(row,"status")+"\n"+usagePrice(row)+"\n";
  text+="Bruksgrunnlag: "+evoText(row,"usage_source")+"\n";
  const char* keys[]={"input_tokens","cached_tokens","output_tokens"};
  const char* labels[]={"Inn-tokens","Cache-tokens","Ut-tokens"};
  const bool measured=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(row,"tokens_measured"));
  for (uint8_t i=0;i<3;++i) {const auto* value=cJSON_GetObjectItemCaseSensitive(row,keys[i]);
    text+=String(labels[i])+": "+(measured && cJSON_IsNumber(value)?String(value->valuedouble,0):String("Ikke målt"))+"\n";}
  return text;
}
} // namespace

void FireOS::requestBackendSettings(const char* view,const String& role,uint32_t offset) {
  auto& s=backendSettingsUi_;s.view=view;s.role=role;s.offset=offset;s.selection=s.scroll=0;s.count=0;s.message="Henter backendverdier";
  s.page=s.view=="models"?FireBackendSettingsUi::Models:s.view=="usage"?FireBackendSettingsUi::Usage:s.view=="limits"?FireBackendSettingsUi::Limits:FireBackendSettingsUi::Runtime;
  s.request=evoRequest();s.requestAt=millis();
  if (!backendClient_ || !backendClient_->backendSettingsStatus(s.request,s.view,role,offset)) {s.request=String();s.message="Backend er frakoblet";}
  redrawRequested_=true;
}
void FireOS::prepareBackendSettings(const String& patch) {
  auto& s=backendSettingsUi_;
  if (!s.available || s.request.length()) {s.message="Hent innstillinger først";return;}
  s.returnPage=s.page;s.request=evoRequest();s.requestAt=millis();s.confirming=false;
  if (!backendClient_ || !backendClient_->backendSettingsPrepare(s.request,s.revision,patch)) {s.request=String();s.message="Backend er frakoblet";}
  else s.message="Endringen er ikke lagret";
}
void FireOS::handleBackendSettings(const String& message) {
  auto& s=backendSettingsUi_;cJSON* envelope=cJSON_Parse(message.c_str());if (!envelope) return;
  const String request=evoText(envelope,"request_id"),type=evoText(envelope,"type");
  if (!s.request.length() || request!=s.request) {cJSON_Delete(envelope);return;}
  if (type=="error") {s.request=String();s.message="Ikke lagret. Hent ny status";cJSON_Delete(envelope);redrawRequested_=true;return;}
  const String body=evoText(envelope,"settings_json");const auto* revision=cJSON_GetObjectItemCaseSensitive(envelope,"revision");
  if (!fireJsonSafe(body.c_str(),body.length(),FireEvolutionContract::kSnapshotJsonBytes) || !cJSON_IsNumber(revision) ||
      revision->valuedouble<0 || revision->valuedouble>UINT32_MAX || floor(revision->valuedouble)!=revision->valuedouble) {cJSON_Delete(envelope);return;}
  cJSON* obj=cJSON_Parse(body.c_str());if (!cJSON_IsObject(obj)) {cJSON_Delete(obj);cJSON_Delete(envelope);return;}
  s.request=String();s.revision=static_cast<uint32_t>(revision->valuedouble);
  if (type=="backend_settings_proposal") {
    const auto* changes=cJSON_GetObjectItemCaseSensitive(obj,"changes");bool visible=cJSON_IsObject(changes);const cJSON* item=nullptr;
    String review="Bekreft innstillingen\n";
    cJSON_ArrayForEach(item,changes) {
      const String label=settingLabel(item->string?String(item->string):String());
      if (!label.length() || (!cJSON_IsBool(item) && !cJSON_IsString(item) && !cJSON_IsNumber(item))) {visible=false;break;}
      review+=label+": "+settingValue(item)+"\n";
    }
    if (visible) {
      s.review=review;s.reviewOffset=0;s.proposalId=evoText(envelope,"proposal_id");s.proposalRevision=s.revision;
      const auto* expires=cJSON_GetObjectItemCaseSensitive(envelope,"expires_at");
      s.expiresAt=cJSON_IsNumber(expires) && expires->valuedouble>0 && expires->valuedouble<=UINT32_MAX?static_cast<uint32_t>(expires->valuedouble):0;
      s.page=FireBackendSettingsUi::Proposal;s.selection=s.scroll=0;s.message="Ikke lagret. Krever B";
    } else {s.proposalId=String();s.message="Endringen kan ikke vises";}
  } else if (type=="backend_settings_snapshot") {
    s.available=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(obj,"available"));s.hasMore=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(obj,"has_more")) || cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(obj,"app_totals_has_more"));
    const auto* runtime=cJSON_GetObjectItemCaseSensitive(obj,"runtime");
    const String mode=evoText(runtime,"developer_mode");
    if (mode=="auto" || mode=="off") {
      const bool selected=mode=="auto";if (aiRuntimeAuto_!=selected) preferences.putBool("runtime_ai_auto",selected);
      aiRuntimeAuto_=selected;aiRuntimeModeAcked_=true;runtimeAiEnabled_=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(runtime,"enabled"));
      if (backendClient_) backendClient_->setRuntimeAiMode(mode,false);
    }
    const auto* action=cJSON_GetObjectItemCaseSensitive(obj,"action");const String state=evoText(action,"status");
    if (s.confirming && state=="busy") {
      s.confirming=false;s.page=FireBackendSettingsUi::Proposal;s.message="Ikke lagret. Backend er opptatt";
    } else if (s.confirming && state=="applied") {
      s.confirming=false;s.proposalId=String();s.message="Lagret. Henter faktisk verdi";
      const String view=s.view,role=s.role;const uint32_t offset=s.offset;
      cJSON_Delete(obj);cJSON_Delete(envelope);requestBackendSettings(view.c_str(),role,offset);return;
    } else {
      s.snapshot=body;s.count=0;
      const auto* selected=cJSON_GetObjectItemCaseSensitive(obj,"selected");
      if (s.view=="models") {
        s.selectedModel=s.role.length()?evoText(selected,s.role.c_str()):String();
        const auto* values=cJSON_GetObjectItemCaseSensitive(obj,s.role.length()?"choices":"roles");const cJSON* item=nullptr;
        if (cJSON_IsArray(values)) cJSON_ArrayForEach(item,values) {
          if (s.count>=9 || !cJSON_IsString(item)) break;
          s.ids[s.count]=item->valuestring;
          s.labels[s.count]=s.role.length()?s.ids[s.count]:settingLabel(s.ids[s.count]);
          s.values[s.count]=s.role.length()?"Valgt: "+s.selectedModel:evoText(selected,s.ids[s.count].c_str());++s.count;
        }
      } else if (s.view=="limits") {
        const auto* limits=cJSON_GetObjectItemCaseSensitive(obj,"limits");
        for (uint8_t i=0;i<9;++i) if (cJSON_GetObjectItemCaseSensitive(limits,settingLimits[i])) {
          s.ids[s.count]=settingLimits[i];s.labels[s.count]=settingLimitNames[i];s.values[s.count]=settingValue(cJSON_GetObjectItemCaseSensitive(limits,settingLimits[i]));++s.count;
        }
      } else if (s.view=="usage") {
        const auto* items=cJSON_GetObjectItemCaseSensitive(obj,"items");const cJSON* item=nullptr;
        if (cJSON_IsArray(items)) cJSON_ArrayForEach(item,items) {
          if (s.count>=4) break;
          s.ids[s.count]=evoText(item,"id");s.labels[s.count]=evoText(item,"operation");
          s.values[s.count]=usagePrice(item);++s.count;
        }
      }
      s.message=s.available?"Faktiske backendverdier":"Innstillinger er kun lesbare";
    }
  }
  cJSON_Delete(obj);cJSON_Delete(envelope);redrawRequested_=true;
}
void FireOS::handleBackendSettingsButton(uint8_t index) {
  auto& s=backendSettingsUi_;
  if (s.page==FireBackendSettingsUi::Review) {
    if (index==1) s.page=s.proposalId.length()?FireBackendSettingsUi::Proposal:s.returnPage;
    else if (index==0) s.reviewOffset=0;
    else if (s.reviewNext<s.review.length()) s.reviewOffset=s.reviewNext;
    redrawRequested_=true;return;
  }
  const uint8_t count=s.page==FireBackendSettingsUi::Runtime?3:s.page==FireBackendSettingsUi::Proposal?3:
      s.page==FireBackendSettingsUi::Limits?s.count+2:s.page==FireBackendSettingsUi::Usage?s.count+5:s.page==FireBackendSettingsUi::Models && s.role.length()?s.count+3:s.count+1;
  if (s.selection>=count) s.selection=count-1;
  if (index!=1) s.selection=(s.selection+count+(index==0?-1:1))%count;
  else if (s.page==FireBackendSettingsUi::Proposal) {
    if (!s.selection) {s.reviewOffset=0;s.page=FireBackendSettingsUi::Review;}
    else if (s.selection==2) {s.proposalId=String();s.page=s.returnPage;}
    else if (!s.proposalId.length() || !backendCommandUnexpired(s.expiresAt)) s.message="Forslaget er utløpt";
    else if (backendClient_ && backendClient_->sessionReady() && !s.request.length()) {
      s.request=evoRequest();s.requestAt=millis();
      s.confirming=backendClient_->backendSettingsConfirm(s.request,s.proposalId,s.proposalRevision);
      if (!s.confirming) {s.request=String();s.message="Ikke lagret. Frakoblet";}
      else s.message="Venter på lagringskvittering";
    }
  } else if (s.page==FireBackendSettingsUi::Runtime) {
    if (s.selection==2) s.page=FireBackendSettingsUi::None;
    else prepareBackendSettings(s.selection?"{\"runtime_ai_mode\":\"off\"}":"{\"runtime_ai_mode\":\"auto\"}");
  } else if (s.page==FireBackendSettingsUi::Models) {
    if (s.role.length() && s.selection==s.count) {if (s.hasMore) requestBackendSettings("models",s.role,s.offset+4);}
    else if (s.role.length() && s.selection==s.count+1) {if (s.offset) requestBackendSettings("models",s.role,s.offset>=4?s.offset-4:0);}
    else if (s.selection>=s.count) {if (s.role.length()) requestBackendSettings("models");else s.page=FireBackendSettingsUi::None;}
    else if (!s.role.length()) requestBackendSettings("models",s.ids[s.selection]);
    else {
      cJSON* patch=cJSON_CreateObject();cJSON_AddStringToObject(patch,"model_role",s.role.c_str());cJSON_AddStringToObject(patch,"model",s.ids[s.selection].c_str());
      const String text=evoCompact(patch);cJSON_Delete(patch);prepareBackendSettings(text);
    }
  } else if (s.page==FireBackendSettingsUi::Limits) {
    if (s.selection==s.count+1) s.page=FireBackendSettingsUi::None;
    else if (s.selection==s.count) prepareBackendSettings("{\"disable_all_limits\":true}");
    else {
      s.key=s.ids[s.selection];cJSON* obj=cJSON_Parse(s.snapshot.c_str());const auto* bounds=cJSON_GetObjectItemCaseSensitive(obj,"bounds");
      const auto* bound=cJSON_GetObjectItemCaseSensitive(bounds,s.key.c_str());const auto* values=cJSON_GetObjectItemCaseSensitive(bound,"choices");
      s.count=0;const cJSON* value=nullptr;
      if (cJSON_IsArray(values)) cJSON_ArrayForEach(value,values) {
        if (s.count>=9) break;
        if (!cJSON_IsBool(value) && !cJSON_IsNumber(value)) continue;
        s.ids[s.count]=evoCompact(value);s.labels[s.count]=settingValue(value);s.values[s.count]=String();++s.count;
      }
      cJSON_Delete(obj);s.page=FireBackendSettingsUi::Values;s.selection=s.scroll=0;
    }
  } else if (s.page==FireBackendSettingsUi::Values) {
    if (s.selection==s.count) requestBackendSettings("limits");
    else {
      cJSON* patch=cJSON_CreateObject();cJSON* limits=cJSON_AddObjectToObject(patch,"limits");
      cJSON_AddItemToObject(limits,s.key.c_str(),cJSON_Parse(s.ids[s.selection].c_str()));
      const String text=evoCompact(patch);cJSON_Delete(patch);prepareBackendSettings(text);
    }
  } else if (s.page==FireBackendSettingsUi::Usage) {
    if (s.selection<s.count) {
      cJSON* obj=cJSON_Parse(s.snapshot.c_str());const auto* items=cJSON_GetObjectItemCaseSensitive(obj,"items");
      s.review=usageDetails(cJSON_GetArrayItem(items,s.selection));cJSON_Delete(obj);s.reviewOffset=0;s.returnPage=FireBackendSettingsUi::Usage;s.page=FireBackendSettingsUi::Review;
    } else if (s.selection==s.count) {if (s.hasMore) requestBackendSettings("usage",String(),s.offset+4);}
    else if (s.selection==s.count+1) {if (s.offset) requestBackendSettings("usage",String(),s.offset>=4?s.offset-4:0);}
    else if (s.selection==s.count+2) {
      cJSON* obj=cJSON_Parse(s.snapshot.c_str());const auto* totals=cJSON_GetObjectItemCaseSensitive(obj,"app_totals");const cJSON* row=nullptr;s.review="Appsummer\n";
      if (cJSON_IsArray(totals)) cJSON_ArrayForEach(row,totals) {
        s.review+=evoText(row,"name")+"\n";
        const char* keys[]={"provider_calculated_usd","empirical_estimated_usd","unknown_usage_requests"};
        const char* labels[]={"Beregnet USD","Usikkert anslag USD","Ukjent bruk"};
        for (uint8_t i=0;i<3;++i) {const auto* value=cJSON_GetObjectItemCaseSensitive(row,keys[i]);
          s.review+=String(labels[i])+": "+(cJSON_IsNumber(value)?String(value->valuedouble,i==2?0:6):String("Ukjent"))+"\n";}
        const auto* historical=cJSON_GetObjectItemCaseSensitive(row,"historical_estimate");
        const auto* old=cJSON_GetObjectItemCaseSensitive(historical,"estimated_usd");
        if (cJSON_IsNumber(old) && old->valuedouble>0) s.review+="Eldre usikkert anslag USD: "+String(old->valuedouble,6)+"\n";
      }
      cJSON_Delete(obj);s.reviewOffset=0;s.returnPage=FireBackendSettingsUi::Usage;s.page=FireBackendSettingsUi::Review;
    } else if (s.selection==s.count+3) {
      cJSON* obj=cJSON_Parse(s.snapshot.c_str());const auto* limits=cJSON_GetObjectItemCaseSensitive(obj,"limits_summary");
      s.review="Backendens pengegrenser\n";
      if (cJSON_IsObject(limits)) for (uint8_t i=0;i<9;++i) {
        const auto* value=cJSON_GetObjectItemCaseSensitive(limits,settingLimits[i]);
        if (value) s.review+=String(settingLimitNames[i])+": "+settingValue(value)+"\n";
      }
      else s.review+="Se Pengegrenser for faktisk status\n";
      cJSON_Delete(obj);s.reviewOffset=0;s.returnPage=FireBackendSettingsUi::Usage;s.page=FireBackendSettingsUi::Review;
    } else s.page=FireBackendSettingsUi::None;
  }
  s.scroll=fire_ai_menu::scroll(s.selection,s.scroll);redrawRequested_=true;
}
void FireOS::drawBackendSettings() {
  auto& s=backendSettingsUi_;fire_canvas_fill::Surface<M5Canvas> surface(ui);
  if (s.page==FireBackendSettingsUi::Review) {
    FireUI::panel(surface,8,6,304,214);FireUI::text(surface,18,12,"GRUNNLAG",kText,"ui16",284);
    size_t offset=s.reviewOffset;char line[81];
    for (uint8_t row=0;row<9 && offset<s.review.length();++row) {offset=fire_ai_menu_ui::line(s.review.c_str(),s.review.length(),offset,line,284);FireUI::text(surface,18,42+row*18,line,kText,"ui12",284);}
    s.reviewNext=offset;drawFooter("Start","Tilbake","Neste");return;
  }
  const uint8_t count=s.page==FireBackendSettingsUi::Runtime?3:s.page==FireBackendSettingsUi::Proposal?3:
      s.page==FireBackendSettingsUi::Limits?s.count+2:s.page==FireBackendSettingsUi::Usage?s.count+5:s.page==FireBackendSettingsUi::Models && s.role.length()?s.count+3:s.count+1;
  if (s.selection>=count) s.selection=count-1;
  s.scroll=fire_ai_menu::scroll(s.selection,s.scroll);
  String labels[4],selected;
  const uint8_t rows=min<uint8_t>(4,count-s.scroll);
  for (uint8_t i=0;i<rows;++i) {
    const uint8_t row=s.scroll+i;
    if (s.page==FireBackendSettingsUi::Runtime) labels[i]=row==0?"AUTO":row==1?"OFF":"Back";
    else if (s.page==FireBackendSettingsUi::Proposal) labels[i]=row==0?"Vis hele endringen":row==1?"Bekreft lagring":"Avvis";
    else if (row<s.count) labels[i]=s.labels[row]+(s.page==FireBackendSettingsUi::Models && !s.role.length()?": "+s.values[row]:String());
    else if (s.page==FireBackendSettingsUi::Limits) labels[i]=row==s.count?"Disable all limits":"Back";
    else if (s.page==FireBackendSettingsUi::Usage) labels[i]=row==s.count?"Neste side":row==s.count+1?"Forrige side":row==s.count+2?"Appsummer":row==s.count+3?"Pengegrenser":"Back";
    else if (s.page==FireBackendSettingsUi::Models && s.role.length()) labels[i]=row==s.count?"Neste side":row==s.count+1?"Forrige side":"Alle modellroller";
    else labels[i]="Back";
  }
  if (s.page==FireBackendSettingsUi::Runtime) selected=String("Faktisk Developer: ")+(aiRuntimeModeAcked_?(aiRuntimeAuto_?"AUTO":"OFF"):"Ukjent")+" / Runtime "+(runtimeAiEnabled_?"På":"Av");
  else if (s.selection<s.count) selected=s.values[s.selection];
  const char* title=s.page==FireBackendSettingsUi::Models?"MODEL":s.page==FireBackendSettingsUi::Usage?"USAGE":s.page==FireBackendSettingsUi::Proposal?"BEKREFT ENDRING":s.page==FireBackendSettingsUi::Runtime?"RUNTIME AI":"PENGEGRENSER";
  const char* text[]={labels[0].c_str(),labels[1].c_str(),labels[2].c_str(),labels[3].c_str()};
  fire_ai_menu_ui::draw(surface,title,s.available?"Backendens lagrede innstillinger":"Ingen bekreftet skriveprofil",s.available?kGreen:kOrange,selected.c_str(),text,rows,s.selection-s.scroll,s.message.c_str());
}
