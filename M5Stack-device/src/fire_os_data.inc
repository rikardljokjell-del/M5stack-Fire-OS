// Included by fire_os.cpp: the same OS/UI owner and four hardware jobs.
uint16_t FireOS::luaDataRequestCallback(void* context,const char* operation,
    const char* first,const char* second,const char* options,const uint8_t* payload,
    size_t length,uint32_t offset,uint16_t count,const char** error) {
  auto* os=static_cast<FireOS*>(context);
  if (!os || !os->luaDataAllowed_) {setLuaError(error,"permission_denied");return 0;}
  if (!os->sdReady_ || os->firmwareBusy()) {setLuaError(error,"storage_unavailable");return 0;}
  if (!operation || !first || !second || !options || length>FireDataEngineContract::kAppendBytes) {
    setLuaError(error,"invalid_argument");return 0;
  }
  const bool network=!strcmp(operation,"process") || !strcmp(operation,"develop");
  if (network && (!os->luaAppActive_ || !os->backendClient_ || !os->backendClient_->sessionReady() || !os->luaRunId_.length())) {
    if (os->luaPackageId_.length() && !os->luaAiBindPackageId_.length()) {
      os->luaAiBindPackageId_=os->luaPackageId_;os->luaAiBindAt_=millis();os->luaAiBindSent_=false;
    }
    setLuaError(error,"not_connected");return 0;
  }
  const uint16_t id=os->createLuaJob(LuaJobKind::Data,error);if (!id) return 0;
  auto* job=os->findLuaJob(id);
  job->dataOperation=operation;job->path=first;job->text=second;job->aiSchema=options;
  job->offset=offset;job->count=count;job->payloadCount=length;
  if (length) memcpy(job->payload,payload,length);
  job->timeoutMs=network?FireDataEngineContract::kNetworkJobTimeoutMs:FireDataEngineContract::kLocalJobTimeoutMs;
  return id;
}

bool FireOS::luaDataDevelopCallback(void* context,const char* mode,const char* instruction,const char** error) {
  auto* os=static_cast<FireOS*>(context);
  return os && os->queueDataDevelop(mode,instruction,false,error);
}
bool FireOS::queueDataDevelop(const char* mode,const char* instruction,bool fromOs,const char** error) {
  if (!luaAppActive_ || !luaPackageId_.length() || (!fromOs && !luaDataAllowed_)) {setLuaError(error,"permission_denied");return false;}
  if (luaDevelopJob_) {setLuaError(error,"busy");return false;}
  const uint16_t id=createLuaJob(LuaJobKind::Data,error);
  if (!id) return false;
  auto* job=findLuaJob(id);job->dataOperation="develop";job->aiSchema="{}";
  job->append=fromOs;job->timeoutMs=FireDataEngineContract::kNetworkJobTimeoutMs;
  luaDevelopMode_=mode;luaDevelopInstruction_=instruction;luaDevelopJob_=id;
  luaFeedbackOutcome_=String();luaFeedbackAck_=String();luaFeedbackConfirmation_=false;
  if (!strcmp(mode,"feedback") && !luaDevelopInstruction_.length()) luaDevelopInstruction_="Appen fungerte som forventet.";
  if (!luaRunId_.length() && !luaAiBindPackageId_.length()) {
    luaAiBindPackageId_=luaPackageId_;luaAiBindAt_=millis();luaAiBindSent_=false;
  }
  redrawRequested_=true;
  return true;
}

void FireOS::cancelLuaDataJob(LuaHardwareJob& job,const char* reason) {
  if (job.kind!=LuaJobKind::Data || job.state!=0) return;
  if (job.started && job.aiRequestId.length() && backendClient_ && backendClient_->sessionReady())
    backendClient_->dataCancel(job.aiRequestId,luaAppId_,luaPackageId_,luaSourceHash_,luaRunId_);
  if (job.dataOperation=="record" && job.dataset && job.dataset->acquisition!="app_recorded") {
    luaDataPartialId_=job.dataset->id;luaDataPartialOverflow_=job.path=="imu" && luaDataImu_.overflow();
  }
  if (luaDataUploadJob_==job.id) {
    if (backendClient_) backendClient_->cancelAudioTransfer();
    luaDataUploadCancelled_=true;
  }
  job.state=!strcmp(reason,"cancelled")?3:2;job.errorCode=reason;
  job.payloadCount=0;job.uploadId=String();
  if (luaDevelopJob_==job.id) {luaDevelopJob_=0;luaDevelopMode_=String();luaDevelopInstruction_=String();luaDevelopContext_=String();luaFeedbackConfirmation_=false;luaFeedbackOutcome_=String();luaFeedbackAck_=String();}
}
void FireOS::finishPartialDataCapture() {
  if (!luaDataPartialId_.length()) return;
  luaDataImu_.end();
  if (luaMicJobId_==luaDataCaptureJob_) releaseLuaMic();
  luaBluetooth_.cancel(luaDataCaptureJob_);
  const char* error=nullptr;
  if (!luaDataStore_.partialCapture(luaDataPartialId_,luaDataPartialOverflow_,error))
    Serial.printf("FIRE data partial metadata failed: %s\n",error?error:"storage_unavailable");
  luaDataPartialId_=String();luaDataPartialOverflow_=false;luaDataCaptureJob_=0;
}

void FireOS::serviceLuaDataJob(LuaHardwareJob& job) {
  const char* error=nullptr;
  const auto fail=[&](const char* code) {cancelLuaDataJob(job,code?code:"invalid_data");};
  const auto done=[&](const String& result) {
    if (result.length()>FireDataEngineContract::kResultBytes || !result.length()) {fail("result_too_large");return;}
    job.text=result;job.state=1;job.dataset.reset();
  };
  const bool legacyDevelop=job.dataOperation=="develop" && job.append && !luaDataAllowed_;
  if ((!luaDataAllowed_ && !legacyDevelop) || !sdReady_) {fail("storage_unavailable");return;}
  if (!legacyDevelop && !luaDataStore_.catalogReady()) {
    if (!luaDataStore_.catalogStep(error)) {if (error) fail(error);else job.lastProgressAt=millis();return;}
  }
  if (luaDataCaptureJob_ && luaDataCaptureJob_!=job.id &&
      (job.dataOperation=="create" || job.dataOperation=="append" || job.dataOperation=="seal" || job.dataOperation=="record")) return;
  if (job.dataOperation=="create") {
    FireDataStore::Dataset data;
    if (!luaDataStore_.create(job.path,job.text,job.aiSchema,data,error)) {fail(error);return;}
    done("{\"ok\":true,\"dataset_id\":\""+data.id+"\",\"path\":\"datasets/"+data.id+"/data\",\"kind\":\""+data.kind+"\"}");
    return;
  }
  if (job.dataOperation=="develop" || job.dataOperation=="process" || job.dataOperation=="sync") {
    serviceLuaDataNetwork(job);return;
  }
  if (job.dataOperation=="record") {serviceLuaDataRecord(job);return;}
  if (!job.dataset) {
    job.dataset.reset(new (std::nothrow) FireDataStore::Dataset());
    if (!job.dataset) {fail("busy");return;}
    if (!luaDataStore_.load(job.path,*job.dataset,error)) {fail(error);return;}
  }
  auto& data=*job.dataset;
  if (job.dataOperation=="info") {done(luaDataStore_.info(data));return;}
  if (job.dataOperation=="append") {
    if (data.acquisition!="app_recorded") {fail("permission_denied");return;}
    if (data.kind=="text" || data.kind=="csv") {
      size_t at=0;uint32_t cp=0;
      while (at<job.payloadCount) if (!fire_app_bitmap::codepoint(reinterpret_cast<const char*>(job.payload),job.payloadCount,at,cp) || !cp) {fail("invalid_data");return;}
    }
    if (!luaDataStore_.append(data,job.payload,job.payloadCount,error)) {fail(error);return;}
    done("{\"ok\":true,\"dataset_id\":\""+data.id+"\",\"size\":"+String(data.size)+"}");return;
  }
  if (job.dataOperation=="mark") {
    if (!luaDataStore_.mark(data,job.text,error)) {fail(error);return;}
    done("{\"ok\":true,\"dataset_id\":\""+data.id+"\"}");return;
  }
  if (job.dataOperation=="read") {
    size_t count=job.count;
    if (!luaDataStore_.read(data,job.offset,job.bytes,count,error)) {fail(error);return;}
    job.byteCount=count;job.append=job.offset+count==data.size;job.state=1;return;
  }
  if (job.dataOperation=="seal") {
    if (!job.started) {
      if (!luaDataStore_.startSeal(job.id,data,error)) {if (error && !strcmp(error,"busy")) return;fail(error);return;}
      job.started=true;
    }
    const int status=luaDataStore_.sealStep(job.id,data,error);
    if (status>=0) job.lastProgressAt=millis();
    if (status<0) fail(error);
    else if (status>0) done(luaDataStore_.info(data));
    return;
  }
  fail("unsupported_operation");
}

static String fireDataCompact(cJSON* object) {
  if (!object) return String();
  char* text=cJSON_PrintUnformatted(object);String value=text?String(text):String();cJSON_free(text);return value;
}

void FireOS::setDataUploadInstruction(LuaHardwareJob& job,const String& instruction) {
  if (job.uploadStarted) return; // duplicate WS state cannot mutate an in-flight immutable chunk
  cJSON* obj=cJSON_Parse(instruction.c_str());
  const cJSON* name=cJSON_GetObjectItemCaseSensitive(obj,"dataset_id");
  const cJSON* part=cJSON_GetObjectItemCaseSensitive(obj,"part");
  const cJSON* offset=cJSON_GetObjectItemCaseSensitive(obj,"offset");
  bool valid=cJSON_IsString(name) && cJSON_IsString(part) && cJSON_IsNumber(offset) &&
      offset->valuedouble>=0 && offset->valuedouble<=FireDataEngineContract::kDatasetBytes && floor(offset->valuedouble)==offset->valuedouble;
  const String id=cJSON_IsString(name)?String(name->valuestring):String();
  const String component=cJSON_IsString(part)?String(part->valuestring):String();
  const uint32_t position=valid?static_cast<uint32_t>(offset->valuedouble):0;
  cJSON* announced=cJSON_Parse(job.dataDescriptors.c_str());bool found=false;
  const cJSON* descriptor=nullptr;
  if (cJSON_IsArray(announced)) {cJSON_ArrayForEach(descriptor,announced) {
    const cJSON* candidate=cJSON_GetObjectItemCaseSensitive(descriptor,"dataset_id");
    if (cJSON_IsString(candidate) && id==candidate->valuestring) found=true;
  }}
  FireDataStore::Dataset data;const char* error=nullptr;
  valid=valid && found && luaDataStore_.load(id,data,error) && data.state=="sealed" &&
      FireDataStore::partSize(data,component)!=UINT32_MAX && position<=FireDataStore::partSize(data,component);
  cJSON_Delete(announced);cJSON_Delete(obj);
  if (!valid) {cancelLuaDataJob(job,"invalid_data");return;}
  job.uploadId=id;job.uploadPart=component;job.uploadOffset=position;
}

void FireOS::serviceLuaDataNetwork(LuaHardwareJob& job) {
  if (job.dataOperation=="develop" && luaDevelopContext_.length()) return;
  if (!luaAppActive_ || !luaRuntime_ || !luaRuntime_->running()) {cancelLuaDataJob(job,"stale_run");return;}
  if (!backendClient_ || !backendClient_->sessionReady() || !luaRunId_.length()) {
    if (job.started) cancelLuaDataJob(job,"not_connected");
    return;
  }
  if (job.started && job.requestRun!=luaRunId_) {cancelLuaDataJob(job,"stale_run");return;}
  if (!job.started) {
    if (luaDataRequestCounter_==UINT32_MAX) {cancelLuaDataJob(job,"busy");return;}
    job.aiRequestId="data-"+backendClient_->bootId()+"-"+String(++luaDataRequestCounter_);
    job.requestRun=luaRunId_;
    cJSON* ids=job.dataOperation=="sync"?cJSON_Parse(job.path.c_str()):
        job.dataOperation=="develop" && luaDataAllowed_?cJSON_Parse(luaDataStore_.recent().c_str()):cJSON_CreateArray();
    if (!ids) {cancelLuaDataJob(job,"busy");return;}
    if (job.dataOperation=="process") {
      cJSON_AddItemToArray(ids,cJSON_CreateString(job.path.c_str()));
      cJSON* options=cJSON_Parse(job.aiSchema.c_str());
      const cJSON* other=cJSON_GetObjectItemCaseSensitive(options,"other_dataset_id");
      if (job.text=="compare" && cJSON_IsString(other)) cJSON_AddItemToArray(ids,cJSON_CreateString(other->valuestring));
      cJSON_DeleteItemFromObjectCaseSensitive(options,"operation");cJSON_AddStringToObject(options,"operation",job.text.c_str());
      job.aiSchema=fireDataCompact(options);cJSON_Delete(options);
      if (!job.aiSchema.length() || job.aiSchema.length()>FireDataEngineContract::kOptionsBytes) {cJSON_Delete(ids);cancelLuaDataJob(job,"invalid_argument");return;}
    }
    cJSON* descriptions=cJSON_CreateArray();
    const cJSON* id=nullptr;const char* error=nullptr;bool valid=descriptions!=nullptr;
    cJSON_ArrayForEach(id,ids) {
      FireDataStore::Dataset data;
      if (!cJSON_IsString(id) || !luaDataStore_.load(id->valuestring,data,error) || data.state!="sealed") {valid=false;break;}
      cJSON* descriptor=cJSON_Parse(luaDataStore_.descriptor(data).c_str());
      if (!descriptor) {valid=false;break;}
      cJSON_AddItemToArray(descriptions,descriptor);
    }
    job.dataDescriptors=fireDataCompact(descriptions);cJSON_Delete(descriptions);
    const String datasetIds=fireDataCompact(ids);cJSON_Delete(ids);
    if (!valid || !job.dataDescriptors.length()) {cancelLuaDataJob(job,error?error:"invalid_data");return;}
    const bool sent=job.dataOperation=="develop"
      ? backendClient_->appDevelop(job.aiRequestId,luaAppId_,luaPackageId_,luaSourceHash_,luaRunId_,luaDevelopMode_,luaDevelopInstruction_,datasetIds,job.dataDescriptors)
      : backendClient_->dataRequest(job.aiRequestId,luaAppId_,luaPackageId_,luaSourceHash_,luaRunId_,job.dataOperation,
          job.dataOperation=="process"?job.path:String(),job.aiSchema,job.dataDescriptors);
    if (!sent) {cancelLuaDataJob(job,"not_connected");return;}
    job.started=true;job.lastProgressAt=millis();return;
  }
  if (!job.uploadId.length()) return;
  if (job.uploadStarted) {
    if (!backendClient_->audioTransferFinished()) return;
    job.uploadStarted=false;
    if (!backendClient_->audioTransferOk()) {cancelLuaDataJob(job,"not_connected");return;}
    job.uploadOffset=backendClient_->audioTransferLength();job.lastProgressAt=millis();
    const String next=backendClient_->dataUploadNext();
    if (next.length()) {job.uploadId=String();setDataUploadInstruction(job,next);return;}
    job.uploadId=String();return; // server emits the next state/result, never paid replay
  }
  const bool ownTransfer=luaDataUploadJob_==job.id && backendClient_->dataTransferActive();
  if ((luaDataUploadJob_ && !ownTransfer) || (backendClient_->audioTransferActive() && !ownTransfer) || aiAudioCaptureActive_ || aiAudioOutputActive_) return;
  FireDataStore::Dataset data;const char* error=nullptr;
  if (!luaDataStore_.load(job.uploadId,data,error) || data.state!="sealed") {cancelLuaDataJob(job,error?error:"not_sealed");return;}
  const uint32_t size=FireDataStore::partSize(data,job.uploadPart);
  if (size==UINT32_MAX || job.uploadOffset>size) {cancelLuaDataJob(job,"offset_mismatch");return;}
  if (!luaDataUploadBuffer_) luaDataUploadBuffer_=static_cast<uint8_t*>(heap_caps_malloc(FireDataEngineContract::kHttpChunkBytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  if (!luaDataUploadBuffer_) {cancelLuaDataJob(job,"busy");return;}
  size_t amount=min<size_t>(FireDataEngineContract::kHttpChunkBytes,size-job.uploadOffset);
  if (!luaDataStore_.readPart(data,job.uploadPart,job.uploadOffset,luaDataUploadBuffer_,amount,error)) {cancelLuaDataJob(job,error);return;}
  uint8_t digest[32];mbedtls_sha256_context sha;mbedtls_sha256_init(&sha);
  const bool hashed=mbedtls_sha256_starts_ret(&sha,0)==0 && mbedtls_sha256_update_ret(&sha,luaDataUploadBuffer_,amount)==0 && mbedtls_sha256_finish_ret(&sha,digest)==0;
  mbedtls_sha256_free(&sha);
  if (!hashed) {cancelLuaDataJob(job,"checksum_mismatch");return;}
  const char* digits="0123456789abcdef";String hash;hash.reserve(64);
  for (uint8_t value:digest) {hash+=digits[value>>4];hash+=digits[value&15];}
  if (backendClient_->beginDataUpload(job.aiRequestId,job.uploadId,job.uploadPart,job.uploadOffset,hash,luaDataUploadBuffer_,amount)) {
    job.uploadStarted=true;luaDataUploadJob_=job.id;
  }
}

void FireOS::handleDataResult(const String& message) {
  if (!luaAppActive_ || !backendClient_ || jsonStringField(message,"app_id")!=luaAppId_ ||
      jsonStringField(message,"package_id")!=luaPackageId_ || jsonStringField(message,"source_sha256")!=luaSourceHash_ ||
      jsonStringField(message,"run_id")!=luaRunId_ || jsonStringField(message,"boot_id")!=backendClient_->bootId()) return;
  const String request=jsonStringField(message,"request_id");
  for (LuaHardwareJob& job:luaJobs_) {
    if (job.kind!=LuaJobKind::Data || !job.started || job.state!=0 || job.aiRequestId!=request || job.requestRun!=luaRunId_) continue;
    const String type=jsonStringField(message,"type");
    if (type=="app_develop_ready") {
      const String context=jsonStringField(message,"context_id");
      if (FireDataStore::identifier(context.c_str(),context.length())) {
        luaDevelopContext_=context;luaFeedbackConfirmation_=luaDevelopMode_=="feedback";
      }
      return;
    }
    cJSON* obj=cJSON_Parse(message.c_str());
    const cJSON* result=cJSON_GetObjectItemCaseSensitive(obj,"result_json");
    const String state=jsonStringField(message,"state");
    const String body=cJSON_IsString(result)?String(result->valuestring):String();
    if (state=="upload_required") {
      cJSON* payload=cJSON_Parse(body.c_str());const cJSON* uploads=cJSON_GetObjectItemCaseSensitive(payload,"uploads");
      if (body.length()>FireDataEngineContract::kResultBytes || !cJSON_IsArray(uploads) || cJSON_GetArraySize(uploads)!=1)
        cancelLuaDataJob(job,"invalid_data");
      else setDataUploadInstruction(job,fireDataCompact(cJSON_GetArrayItem(uploads,0)));
      cJSON_Delete(payload);
    } else if (state=="completed") {
      if (!fire_runtime_ai_json::validObject(body.c_str(),body.length(),FireDataEngineContract::kResultBytes)) cancelLuaDataJob(job,"invalid_data");
      else if (job.dataOperation=="develop") {
        const String context=jsonStringField(body,"context_id");
        if (FireDataStore::identifier(context.c_str(),context.length())) {
          luaDevelopContext_=context;luaFeedbackConfirmation_=luaDevelopMode_=="feedback";
        }
        else cancelLuaDataJob(job,"invalid_data");
      } else {
        job.text=body;job.state=1;
        if (luaDataUploadJob_==job.id) {backendClient_->cancelAudioTransfer();luaDataUploadCancelled_=true;}
      }
    } else if (state=="failed" || state=="cancelled") cancelLuaDataJob(job,jsonStringField(message,"error_code").c_str());
    else cancelLuaDataJob(job,"invalid_data");
    cJSON_Delete(obj);return;
  }
}

void FireOS::serviceDataDevelopHandoff() {
  if(luaFeedbackAck_.length() && uint32_t(millis()-luaFeedbackAt_)>=15000) {
    luaFeedbackAck_=String();luaFeedbackOutcome_="unconfirmed";luaFeedbackConfirmation_=true;redrawRequested_=true;
  }
  if (luaDevelopContext_.length() && !luaFeedbackConfirmation_ && !luaFeedbackAck_.length()) {
    const String context=luaDevelopContext_,name=luaAppName_;
    // Context and raw synchronization are complete before native stop.
    pendingDevelopmentContext_=context;
    open(Screen::AiDeveloper);
    aiProjectPickerActive_=false;aiProjectName_=name;aiWorkflowText_="Grunnlag klart";
    aiConversationMode_=0;aiVoiceTestMode_=false;
    if (backendClient_) {
      backendClient_->setDevelopmentContext(context);
      backendClient_->setConversationMode("develop");
    }
    developmentDrainAt_=millis();
  }
  if (pendingDevelopmentContext_.length() && backendClient_ &&
      millis()-developmentDrainAt_>=300 && (!backendClient_->pendingWrites() || millis()-developmentDrainAt_>=3000)) {
    // Preserve ordering of the real app_stopped receipt before the new normal
    // SessionStart. No synthetic running state or automatic model/build call.
    backendClient_->disconnect();pendingDevelopmentContext_=String();
  }
}

void FireOS::serviceLuaDataRecord(LuaHardwareJob& job) {
  const char* error=nullptr;
  const auto fail=[&](const char* code) {cancelLuaDataJob(job,code?code:"invalid_data");};
  if (job.path!="imu" && job.path!="mic" && job.path!="ble.advertisements") {fail("unsupported_source");return;}
  if (!job.dataset) {
    if (luaDataCaptureJob_ && luaDataCaptureJob_!=job.id) return;
    const bool mic=job.path=="mic";
    const bool ble=job.path=="ble.advertisements";
    if (!(luaServiceMask_&(mic?kLuaServiceMic:ble?kLuaServiceBluetooth:kLuaServiceImu))) {fail("permission_denied");return;}
    if (mic) {
      if (luaMicJobId_ || luaSpeakerJobId_ || aiAudioCaptureActive_ || aiAudioOutputActive_) {fail("busy");return;}
      if (M5.Speaker.isPlaying()) return; // let the user's ordinary button click finish before recording
    }
    cJSON* options=cJSON_Parse(job.aiSchema.c_str());
    if (!options) {fail("invalid_json");return;}
    const cJSON* duration=cJSON_GetObjectItemCaseSensitive(options,"duration_ms");
    const cJSON* rate=cJSON_GetObjectItemCaseSensitive(options,"sample_rate_hz");
    const cJSON* target=cJSON_GetObjectItemCaseSensitive(options,"dataset_id");
    const double ms=cJSON_IsNumber(duration)?duration->valuedouble:1000;
    const double hz=cJSON_IsNumber(rate)?rate->valuedouble:(mic?16000:ble?0:100);
    const bool valid=isfinite(ms) && floor(ms)==ms && ms>=100 && ms<=(mic?FireDataEngineContract::kAudioDurationMaxMs:FireDataEngineContract::kImuDurationMaxMs) &&
        isfinite(hz) && ((mic && (hz==8000 || hz==16000)) || (!mic && !ble && (hz==50 || hz==100)) || (ble && !rate)) &&
        (!target || cJSON_IsString(target));
    const String targetId=cJSON_IsString(target)?String(target->valuestring):String();
    cJSON_Delete(options);
    if (!valid) {fail("invalid_argument");return;}
    job.dataset.reset(new (std::nothrow) FireDataStore::Dataset());
    if (!job.dataset) {fail("busy");return;}
    auto& data=*job.dataset;
    if (targetId.length()) {
      if (!luaDataStore_.load(targetId,data,error)) {fail(error);return;}
      if (data.kind!=(mic?"audio":ble?"text":"csv") || !luaDataStore_.owns(data) || data.size || data.state=="sealed") {fail("invalid_data");return;}
    } else if (!luaDataStore_.create(mic?"Microphone recording":ble?"BLE advertisements":"IMU recording",mic?"audio":ble?"text":"csv","{}",data,error)) {fail(error);return;}
    job.durationMs=static_cast<uint32_t>(ms);job.frequency=static_cast<uint32_t>(hz);
    job.timeoutMs=FireDataEngineContract::kLocalJobTimeoutMs;
    const String metadata=ble?String("{\"encoding\":\"ble-ad-jsonl-v1\",\"clock\":\"esp_timer_monotonic_us\",\"payload\":\"advertising_and_scan_response_bytes\",\"max_ad_bytes\":62}"):mic
        ? "{\"encoding\":\"pcm_s16le_wav\",\"channels\":1,\"sample_rate_hz\":"+String(job.frequency)+",\"clock\":\"ADC_DMA\",\"preprocess\":\"ADC12_box4_center2048_x16\"}"
        : "{\"columns\":[\"sample_index\",\"ax\",\"ay\",\"az\",\"gx\",\"gy\",\"gz\",\"received_us\"],\"units\":[\"count\",\"g\",\"g\",\"g\",\"deg/s\",\"deg/s\",\"deg/s\",\"us\"],\"sample_rate_hz\":"+String(job.frequency)+",\"axes\":\"sensor_native\",\"timing\":\"FIFO_order_nominal_sensor_clock_and_host_receipt\"}";
    if (!luaDataStore_.prepareCapture(data,mic?"native_mic":ble?"native_ble":"native_imu_fifo",metadata,error)) {fail(error);return;}
    luaDataCaptureJob_=job.id;
    if (ble) {
#ifdef FIRE_OS_BLE
      if (bluetoothMode_==2 || bluetoothConnected_ || bluetoothScanInProgress_ || !initBluetooth() || !luaBluetooth_.scan(job.id,job.durationMs)) {fail("busy");return;}
#else
      fail("unsupported_source");return;
#endif
    } else if (mic) {
      const uint32_t bytes=job.frequency*job.durationMs/1000*2+44;
      if (!luaDataStore_.hasCapacity(bytes)) {fail("quota_exceeded");return;}
      luaMicBuffer_=static_cast<uint8_t*>(heap_caps_malloc(bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
      if (!luaMicBuffer_) {fail("busy");return;}
      luaMicBufferBytes_=bytes;luaMicJobId_=job.id;luaMicLevel_=0;writeWavHeader(luaMicBuffer_,bytes-44,job.frequency);
      if (!fireStartMicCapture(reinterpret_cast<int16_t*>(luaMicBuffer_+44),(bytes-44)/2,job.frequency,true)) {fail("invalid_data");return;}
    } else {
      if (!luaDataImu_.begin(job.frequency)) {fail("unsupported_source");return;}
      cJSON* actual=cJSON_Parse(data.metadata.c_str());
      if (!actual) {fail("invalid_data");return;}
      cJSON_AddStringToObject(actual,"driver","MPU6886");cJSON_AddNumberToObject(actual,"divider",1000/job.frequency-1);
      cJSON_AddNumberToObject(actual,"gyro_dlpf_cfg",luaDataImu_.gyroFilter()&7);
      cJSON_AddNumberToObject(actual,"accel_range_g",luaDataImu_.accelRange());
      cJSON_AddNumberToObject(actual,"gyro_range_dps",luaDataImu_.gyroRange());
      const String configured=fireDataCompact(actual);cJSON_Delete(actual);
      if (!luaDataStore_.prepareCapture(data,"native_imu_fifo",configured,error)) {fail(error);return;}
      const char* header="sample_index,ax,ay,az,gx,gy,gz,received_us\n";
      if (!luaDataStore_.append(data,reinterpret_cast<const uint8_t*>(header),strlen(header),error)) {fail(error);return;}
    }
    job.started=true;job.step=1;job.startedAt=millis();job.lastProgressAt=millis();return;
  }
  auto& data=*job.dataset;
  if (job.step==1 && millis()-job.startedAt>job.durationMs+FireDataEngineContract::kLocalJobTimeoutMs) {fail("timeout");return;}
  if (job.step==1 && job.path=="ble.advertisements") {
#ifdef FIRE_OS_BLE
    if (luaBluetooth_.owner()!=job.id || bluetoothMode_==2) {fail("unavailable");return;}
    const int64_t started=esp_timer_get_time();FireBluetoothJobs::Packet packet;
    for (uint8_t i=0;i<4 && data.samples<6000 && esp_timer_get_time()-started<3000 && luaBluetooth_.pop(packet);++i) {
      const char* hex="0123456789abcdef";String payload;payload.reserve(packet.length*2);
      for (uint8_t at=0;at<packet.length;++at) {payload+=hex[packet.bytes[at]>>4];payload+=hex[packet.bytes[at]&15];}
      const String address=fireBleAddress(packet);
      const String line="{\"t_us\":"+String(packet.us)+",\"address\":\""+address+"\",\"address_type\":"+String(packet.type)+
          ",\"rssi\":"+String(packet.rssi)+",\"event_type\":"+String(packet.event)+",\"adv_length\":"+String(packet.advLength)+",\"payload_hex\":\""+payload+"\"}\n";
      if (line.length()>sizeof(job.payload)) {fail("invalid_data");return;}
      if (job.payloadCount+line.length()>sizeof(job.payload)) {
        if (!luaDataStore_.append(data,job.payload,job.payloadCount,error)) {fail(error);return;}
        job.payloadCount=0;
      }
      memcpy(job.payload+job.payloadCount,line.c_str(),line.length());job.payloadCount+=line.length();++data.samples;
      job.lastProgressAt=millis();
      bool known=false;
      for (uint8_t at=0;at<bluetoothScanCount_;++at) if (bluetoothAddresses_[at].equalsIgnoreCase(address)) known=true;
      if (!known && bluetoothScanCount_<kMaxBluetoothDevices) {
        bluetoothAddresses_[bluetoothScanCount_]=address;bluetoothAddressTypes_[bluetoothScanCount_++]=packet.type;
      }
    }
    if (data.samples<6000 && (luaBluetooth_.scanning() || luaBluetooth_.pendingPackets())) {job.lastProgressAt=millis();return;}
    const uint32_t dropped=luaBluetooth_.dropped()+luaBluetooth_.queuedPackets();luaBluetooth_.cancel(job.id);
    if (job.payloadCount && !luaDataStore_.append(data,job.payload,job.payloadCount,error)) {fail(error);return;}
    data.dropped=dropped;
    job.payloadCount=0;job.step=2;
#else
    fail("unsupported_source");return;
#endif
  }
  if (job.step==1 && job.path=="mic") {
    if (!luaMicBuffer_ || fireMicCaptureFailed()) {fail("invalid_data");return;}
    const size_t samples=fireMicCapturedSamples(),available=44+samples*2;
    const bool recording=fireMicCaptureRunning();
    if (samples) {
      const auto* pcm=reinterpret_cast<const int16_t*>(luaMicBuffer_+44);
      uint32_t peak=0;
      for (size_t i=samples-min<size_t>(samples,128);i<samples;++i)
        peak=max<uint32_t>(peak,static_cast<uint32_t>(abs(static_cast<int>(pcm[i]))));
      luaMicLevel_=static_cast<float>(peak)/32768.0f;
    }
    const int64_t started=esp_timer_get_time();
    for (uint8_t i=0;i<8 && data.size<available && esp_timer_get_time()-started<3000;++i) {
      const size_t amount=min<size_t>(FireDataEngineContract::kAppendBytes,available-data.size);
      data.samples=data.size+amount>=44?(data.size+amount-44)/2:0;
      if (!luaDataStore_.append(data,luaMicBuffer_+data.size,amount,error)) {fail(error);return;}
      job.lastProgressAt=millis();
    }
    if (recording || data.size<available) return;
    if (data.size!=luaMicBufferBytes_) {fail("invalid_data");return;}
    releaseLuaMic();job.step=2;
  }
  if (job.step==1 && job.path=="imu") {
    const uint32_t target=job.durationMs*job.frequency/1000;
    const int64_t started=esp_timer_get_time();
    for (uint8_t i=0;i<16 && data.samples<target && esp_timer_get_time()-started<3000;++i) {
      float values[6];uint64_t received=0;
      const int status=luaDataImu_.sample(values,received);
      if (status<0) {fail("invalid_data");return;}
      if (!status) break;
      char row[160];
      const int length=snprintf(row,sizeof(row),"%lu,%.7g,%.7g,%.7g,%.7g,%.7g,%.7g,%llu\n",
          static_cast<unsigned long>(data.samples),values[0],values[1],values[2],values[3],values[4],values[5],
          static_cast<unsigned long long>(received));
      if (length<=0 || static_cast<size_t>(length)>=sizeof(row)) {fail("invalid_data");return;}
      if (job.payloadCount+length>sizeof(job.payload)) {
        if (!luaDataStore_.append(data,job.payload,job.payloadCount,error)) {fail(error);return;}
        job.payloadCount=0;
      }
      memcpy(job.payload+job.payloadCount,row,length);job.payloadCount+=length;++data.samples;
      job.lastProgressAt=millis();
    }
    if (data.samples<target) return;
    if (!luaDataImu_.end()) {fail("invalid_data");return;}
    if (job.payloadCount && !luaDataStore_.append(data,job.payload,job.payloadCount,error)) {fail(error);return;}
    job.payloadCount=0;job.step=2;
  }
  if (job.step==2) {
    if (!luaDataStore_.captureSummary(data,data.samples,data.dropped,error)) {fail(error);return;}
    job.step=4;
  }
  if (job.step==4) {
    if (!luaDataStore_.startSeal(job.id,data,error)) {if (error && !strcmp(error,"busy")) return;fail(error);return;}
    job.step=3;return;
  }
  if (job.step==3) {
    const int status=luaDataStore_.sealStep(job.id,data,error);job.lastProgressAt=millis();
    if (status<0) {fail(error);return;}
    if (status>0) {
      job.text="{\"ok\":true,\"dataset_id\":\""+data.id+"\",\"size\":"+String(data.size)+",\"sha256\":\""+data.sha+"\",\"state\":\"sealed\",\"samples\":"+String(data.samples)+",\"dropped\":"+String(data.dropped)+"}";
      job.state=1;luaDataCaptureJob_=0;job.dataset.reset();
    }
  }
}
