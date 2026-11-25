#include "fire_data_store.h"
#include "fire_json_guard.h"
#include "fire_data_journal.h"
#include "fire_data_paths.h"
#include <cJSON.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <unistd.h>
#include <string.h>
#include <initializer_list>

namespace {
String compact(cJSON* json) {
  if (!json) return String();
  char* text=cJSON_PrintUnformatted(json);
  String out=text?String(text):String();
  cJSON_free(text);
  return out;
}
String field(const cJSON* obj,const char* key) {
  const cJSON* value=cJSON_GetObjectItemCaseSensitive(obj,key);
  return cJSON_IsString(value)?String(value->valuestring):String();
}
uint32_t number(const cJSON* obj,const char* key) {
  const cJSON* value=cJSON_GetObjectItemCaseSensitive(obj,key);
  return cJSON_IsNumber(value) && value->valuedouble>=0 && value->valuedouble<=UINT32_MAX
      && value->valuedouble==static_cast<uint32_t>(value->valuedouble)?static_cast<uint32_t>(value->valuedouble):0;
}
bool kindValid(const String& kind) {return kind=="csv" || kind=="text" || kind=="binary" || kind=="audio";}
String readSmall(fs::FS& fs,const String& path,size_t maximum=3072) {
  File file=fs.open(path,FILE_READ);
  if (!file || file.isDirectory() || file.size()>maximum) { file.close(); return String(); }
  const size_t length=file.size();
  String text;
  if (!text.reserve(length)) {file.close();return String();}
  uint8_t buffer[128];
  while (text.length()<length) {
    const size_t amount=min<size_t>(sizeof(buffer),length-text.length());
    if (file.read(buffer,amount)!=amount || !text.concat(reinterpret_cast<const char*>(buffer),amount)) break;
  }
  file.close();
  return text.length()==length?text:String();
}
bool shaValid(const String& sha) {
  if (sha.length()!=64) return false;
  for (size_t i=0;i<64;++i) if (!((sha[i]>='0' && sha[i]<='9') || (sha[i]>='a' && sha[i]<='f'))) return false;
  return true;
}
} // namespace

bool FireDataStore::identifier(const char* text,size_t length) {
  if (!text || !length || length>FireDataEngineContract::kIdentifierBytes) return false;
  for (size_t i=0;i<length;++i) {
    const char c=text[i];
    if (!((c>='a' && c<='z') || (c>='A' && c<='Z') || (c>='0' && c<='9') || c=='-' || c=='_')) return false;
  }
  return true;
}
bool FireDataStore::generatedId(const String& id) {
  return fire_data_paths::generated(id.c_str(),id.length());
}
void FireDataStore::configure(fs::FS& fs,const Owner& owner) {
  close();fs_=&fs;owner_=owner;root_="/apps/"+owner.app+"/appdata/datasets";
  used_=0;count_=0;ready_=false;scanning_=false;recentCount_=0;
  for (auto& id:recent_) id=String();
}
void FireDataStore::close() {
  directory_.close();hashFile_.close();
  if (hashJob_) mbedtls_sha256_free(&hash_);
  hashJob_=0;fs_=nullptr;ready_=false;scanning_=false;
}
String FireDataStore::folder(const String& id) const {return root_+"/"+id;}
void FireDataStore::remember(const String& id) {
  for (uint8_t i=0;i<recentCount_;++i) if (recent_[i]==id) return;
  if (recentCount_<FireDataEngineContract::kContextDatasetRefs) recent_[recentCount_++]=id;
  else {for (uint8_t i=1;i<recentCount_;++i) recent_[i-1]=recent_[i];recent_[recentCount_-1]=id;}
}
bool FireDataStore::catalogStep(const char*& error) {
  if (ready_) return true;
  if (!fs_) {error="storage_unavailable";return false;}
  if (!scanning_) {
    if (!fs_->exists(root_) && !fs_->mkdir(root_)) {error="storage_unavailable";return false;}
    directory_=fs_->open(root_,FILE_READ);
    if (!directory_ || !directory_.isDirectory()) {error="storage_unavailable";return false;}
    scanning_=true;
  }
  File entry=directory_.openNextFile();
  if (!entry) {directory_.close();ready_=true;return true;}
  String id=entry.name();const int slash=id.lastIndexOf('/');if (slash>=0) id=id.substring(slash+1);
  const bool isDirectory=entry.isDirectory();entry.close();
  if (isDirectory && generatedId(id)) {
    if (++count_>FireDataEngineContract::kDatasetsPerApp) {error="quota_exceeded";return false;}
    Dataset data;
    if (!load(id,data,error)) return false;
    const uint64_t bytes=static_cast<uint64_t>(data.size)+data.indexSize+data.eventsSize;
    if (bytes>FireDataEngineContract::kAppBytes-used_) {error="quota_exceeded";return false;}
    used_+=static_cast<uint32_t>(bytes);
    if (data.state=="sealed") remember(data.id);
  }
  return false;
}
bool FireDataStore::owns(const Dataset& data) const {return data.instance==owner_.instance && data.boot==owner_.boot;}

bool FireDataStore::writeChecked(const String& path,const uint8_t* bytes,size_t length,bool append,const char*& error) {
  if (!fire_data_journal::writeChecked(*fs_,path,bytes,length,append)) {error="checksum_mismatch";return false;}
  return true;
}
bool FireDataStore::save(const Dataset& data,const char*& error) {
  cJSON* obj=cJSON_CreateObject();if (!obj) {error="busy";return false;}
  cJSON_AddNumberToObject(obj,"schema",1);
  cJSON_AddStringToObject(obj,"app_id",owner_.app.c_str());
  cJSON_AddStringToObject(obj,"dataset_id",data.id.c_str());
  cJSON_AddStringToObject(obj,"label",data.label.c_str());
  cJSON_AddStringToObject(obj,"kind",data.kind.c_str());
  cJSON_AddStringToObject(obj,"metadata_json",data.metadata.c_str());
  cJSON_AddStringToObject(obj,"state",data.state.c_str());
  cJSON_AddStringToObject(obj,"sha256",data.sha.c_str());
  cJSON_AddStringToObject(obj,"index_sha256",data.indexSha.c_str());
  cJSON_AddStringToObject(obj,"events_sha256",data.eventsSha.c_str());
  cJSON_AddStringToObject(obj,"creator_instance",data.instance.c_str());
  cJSON_AddStringToObject(obj,"origin_package_id",data.package.c_str());
  cJSON_AddStringToObject(obj,"origin_source_sha256",data.source.c_str());
  cJSON_AddStringToObject(obj,"origin_run_id",data.run.c_str());
  cJSON_AddStringToObject(obj,"boot_id",data.boot.c_str());
  cJSON_AddStringToObject(obj,"acquisition",data.acquisition.c_str());
  cJSON_AddNumberToObject(obj,"size",data.size);cJSON_AddNumberToObject(obj,"created_ms",data.created);
  cJSON_AddNumberToObject(obj,"samples",data.samples);cJSON_AddNumberToObject(obj,"dropped",data.dropped);
  cJSON_AddNumberToObject(obj,"index_size",data.indexSize);cJSON_AddNumberToObject(obj,"events_size",data.eventsSize);
  const String body=compact(obj);cJSON_Delete(obj);
  if (!body.length() || body.length()>3072) {error="invalid_data";return false;}
  const String path=folder(data.id)+"/manifest.json",stage=path+".new",previous=path+".previous";
  if (!writeChecked(stage,reinterpret_cast<const uint8_t*>(body.c_str()),body.length(),false,error)) return false;
  const bool existed=fs_->exists(path);
  if (existed) {
    if (fs_->exists(previous) && !fs_->remove(previous)) {error="storage_unavailable";return false;}
    if (!fs_->rename(path,previous)) {error="storage_unavailable";return false;}
  }
  if (!fs_->rename(stage,path)) {
    if (existed) fs_->rename(previous,path);
    error="storage_unavailable";return false;
  }
  return true;
}
bool FireDataStore::load(const String& id,Dataset& out,const char*& error) {
  if (!fs_ || !identifier(id.c_str(),id.length())) {error="invalid_handle";return false;}
  const String path=folder(id)+"/manifest.json";
  // Recover only the interrupted known manifest rename, never invalid content.
  if (!fs_->exists(path) && fs_->exists(path+".previous")) fs_->rename(path+".previous",path);
  const String body=readSmall(*fs_,path);
  if (!body.length() || !fireJsonSafe(body.c_str(),body.length(),3072,6,256)) {error="not_found";return false;}
  cJSON* obj=cJSON_Parse(body.c_str());if (!obj) {error="invalid_data";return false;}
  Dataset data;
  data.id=field(obj,"dataset_id");data.label=field(obj,"label");data.kind=field(obj,"kind");
  data.metadata=field(obj,"metadata_json");data.state=field(obj,"state");data.sha=field(obj,"sha256");
  data.indexSha=field(obj,"index_sha256");data.eventsSha=field(obj,"events_sha256");
  data.instance=field(obj,"creator_instance");data.package=field(obj,"origin_package_id");
  data.source=field(obj,"origin_source_sha256");data.run=field(obj,"origin_run_id");data.boot=field(obj,"boot_id");
  data.acquisition=field(obj,"acquisition");
  data.size=number(obj,"size");data.created=number(obj,"created_ms");
  data.samples=number(obj,"samples");data.dropped=number(obj,"dropped");
  data.indexSize=number(obj,"index_size");data.eventsSize=number(obj,"events_size");
  const bool valid=number(obj,"schema")==1 && field(obj,"app_id")==owner_.app && data.id==id && kindValid(data.kind) &&
      data.label.length()<=FireDataEngineContract::kLabelBytes && data.metadata.length()<=FireDataEngineContract::kMetadataBytes &&
      static_cast<uint64_t>(data.size)+data.indexSize+data.eventsSize<=FireDataEngineContract::kDatasetBytes && shaValid(data.source) && data.instance.length()>0 &&
      (data.state=="open" || data.state=="partial" || (data.state=="sealed" && shaValid(data.sha) && shaValid(data.indexSha) && shaValid(data.eventsSha)));
  cJSON_Delete(obj);
  if (!valid) {error="invalid_data";return false;}
  out=data;return true;
}
bool FireDataStore::create(const String& label,const String& kind,const String& metadata,Dataset& out,const char*& error) {
  if (!ready_) {error="busy";return false;}
  if (count_>=FireDataEngineContract::kDatasetsPerApp || used_>=FireDataEngineContract::kAppBytes) {error="quota_exceeded";return false;}
  if (!kindValid(kind) || label.length()>FireDataEngineContract::kLabelBytes || metadata.length()>FireDataEngineContract::kMetadataBytes) {error="invalid_argument";return false;}
  Dataset data;data.id="ds-"+String(esp_random(),HEX)+"-"+String(esp_random(),HEX)+"-"+String(millis(),HEX);
  data.label=label;data.kind=kind;data.metadata=metadata;data.state="open";
  data.instance=owner_.instance;data.package=owner_.package;data.source=owner_.source;data.run=owner_.run;data.boot=owner_.boot;
  data.created=millis();
  const String path=folder(data.id);
  if (fs_->exists(path) || !fs_->mkdir(path)) {error="storage_unavailable";return false;}
  // Empty raw file is explicitly created and size-checked before its manifest.
  if (!writeChecked(path+"/data",nullptr,0,false,error) ||
      !writeChecked(path+"/index.jsonl",nullptr,0,false,error) ||
      !writeChecked(path+"/events.jsonl",nullptr,0,false,error) || !save(data,error)) return false;
  ++count_;out=data;return true;
}
bool FireDataStore::recoverData(const Dataset& data,const char*& error,bool markerOnly) {
  const char* names[]={"data","index.jsonl","events.jsonl"};
  const uint32_t sizes[]={data.size,data.indexSize,data.eventsSize};
  for (uint8_t i=markerOnly?2:0;i<3;++i) {
    const String path=folder(data.id)+"/"+names[i];
    const auto resize=[](const String& target,uint32_t length) {
      // initSdCard mounts this validated, engine-owned tree at /sd.
      return ::truncate((String("/sd")+target).c_str(),length)==0;
    };
    if (!fire_data_journal::recoverPart(*fs_,path,sizes[i],data.state=="sealed",resize)) {
      error="checksum_mismatch";return false;
    }
  }
  return true;
}
bool FireDataStore::append(Dataset& data,const uint8_t* bytes,size_t length,const char*& error) {
  if (hashJob_ && hashId_==data.id) {error="busy";return false;}
  if (!owns(data)) {error="stale_run";return false;}
  if (data.state=="sealed") {error="sealed";return false;}
  if (!length || length>FireDataEngineContract::kAppendBytes) {error="invalid_argument";return false;}
  Dataset latest;if (!load(data.id,latest,error)) return false;
  if (latest.size!=data.size || latest.state=="sealed") {error="offset_mismatch";return false;}
  data.eventsSize=latest.eventsSize;
  if (!recoverData(data,error)) return false;
  const String path=folder(data.id);
  const String index="{\"offset\":"+String(data.size)+",\"length\":"+String(length)+",\"monotonic_us\":"+String(static_cast<uint64_t>(esp_timer_get_time()))+"}\n";
  const uint64_t total=static_cast<uint64_t>(data.size)+data.indexSize+data.eventsSize;
  if (total+length+index.length()>FireDataEngineContract::kDatasetBytes || !hasCapacity(length+index.length())) {error="quota_exceeded";return false;}
  if (!writeChecked(path+"/data",bytes,length,true,error)) return false;
  if (!writeChecked(path+"/index.jsonl",reinterpret_cast<const uint8_t*>(index.c_str()),index.length(),true,error)) return false;
  Dataset next=data;next.size+=length;next.indexSize+=index.length();
  if (!save(next,error)) return false;
  used_+=length+index.length();data=next;return true;
}
bool FireDataStore::mark(Dataset& data,const String& label,const char*& error) {
  if (hashJob_ && hashId_==data.id) {error="busy";return false;}
  if (!owns(data)) {error="stale_run";return false;}
  if (data.state=="sealed") {error="sealed";return false;}
  if (!recoverData(data,error,true)) return false;
  cJSON* obj=cJSON_CreateObject();if (!obj) {error="busy";return false;}
  cJSON_AddStringToObject(obj,"label",label.c_str());cJSON_AddNumberToObject(obj,"offset",data.size);
  cJSON_AddNumberToObject(obj,"monotonic_us",static_cast<double>(esp_timer_get_time()));
  const String line=compact(obj)+"\n";cJSON_Delete(obj);
  const uint64_t total=static_cast<uint64_t>(data.size)+data.indexSize+data.eventsSize;
  if (total+line.length()>FireDataEngineContract::kDatasetBytes || !hasCapacity(line.length())) {error="quota_exceeded";return false;}
  if (!writeChecked(folder(data.id)+"/events.jsonl",reinterpret_cast<const uint8_t*>(line.c_str()),line.length(),true,error)) return false;
  Dataset next=data;next.eventsSize+=line.length();if (!save(next,error)) return false;
  used_+=line.length();data=next;return true;
}
bool FireDataStore::prepareCapture(Dataset& data,const String& acquisition,const String& metadata,const char*& error) {
  if (!owns(data) || data.state=="sealed" || data.size || metadata.length()>FireDataEngineContract::kMetadataBytes) {error="invalid_data";return false;}
  cJSON* merged=cJSON_Parse(data.metadata.c_str());cJSON* native=cJSON_Parse(metadata.c_str());
  if (!cJSON_IsObject(merged) || !cJSON_IsObject(native)) {cJSON_Delete(merged);cJSON_Delete(native);error="invalid_json";return false;}
  const cJSON* item=nullptr;
  cJSON_ArrayForEach(item,native) {
    cJSON_DeleteItemFromObjectCaseSensitive(merged,item->string);
    cJSON_AddItemToObject(merged,item->string,cJSON_Duplicate(item,true));
  }
  for (const char* key:{"samples","dropped","overflow","capture_complete"}) cJSON_DeleteItemFromObjectCaseSensitive(merged,key);
  cJSON_AddNumberToObject(merged,"samples",0);cJSON_AddNumberToObject(merged,"dropped",0);
  cJSON_AddBoolToObject(merged,"overflow",false);cJSON_AddBoolToObject(merged,"capture_complete",false);
  const String body=compact(merged);const bool bounded=cJSON_GetArraySize(merged)<=static_cast<int>(FireDataEngineContract::kJsonItems) && body.length()+24<=FireDataEngineContract::kMetadataBytes;
  cJSON_Delete(merged);cJSON_Delete(native);
  if (!bounded) {error="result_too_large";return false;}
  Dataset next=data;next.acquisition=acquisition;next.metadata=body;
  if (!save(next,error)) return false;
  data=next;return true;
}
bool FireDataStore::captureSummary(Dataset& data,uint32_t samples,uint32_t dropped,const char*& error) {
  Dataset latest;if (!load(data.id,latest,error)) return false;
  if (!owns(latest) || latest.state=="sealed") {error="stale_run";return false;}
  latest.samples=samples;latest.dropped=dropped;
  cJSON* metadata=cJSON_Parse(latest.metadata.c_str());if (!metadata) {error="invalid_data";return false;}
  for (const char* key:{"samples","dropped","overflow","capture_complete"}) cJSON_DeleteItemFromObjectCaseSensitive(metadata,key);
  cJSON_AddNumberToObject(metadata,"samples",samples);cJSON_AddNumberToObject(metadata,"dropped",dropped);
  cJSON_AddBoolToObject(metadata,"overflow",false);cJSON_AddBoolToObject(metadata,"capture_complete",true);
  latest.metadata=compact(metadata);cJSON_Delete(metadata);
  if (latest.metadata.length()>FireDataEngineContract::kMetadataBytes) {error="result_too_large";return false;}
  if (!save(latest,error)) return false;
  data=latest;return true;
}
bool FireDataStore::partialCapture(const String& id,bool overflow,const char*& error) {
  Dataset data;if (!load(id,data,error)) return false;
  if (!owns(data) || data.state=="sealed" || data.acquisition=="app_recorded") {error="stale_run";return false;}
  data.state="partial";
  cJSON* metadata=cJSON_Parse(data.metadata.c_str());if (!metadata) {error="invalid_data";return false;}
  const bool complete=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(metadata,"capture_complete"));
  for (const char* key:{"samples","dropped","overflow","capture_complete"}) cJSON_DeleteItemFromObjectCaseSensitive(metadata,key);
  cJSON_AddNumberToObject(metadata,"samples",data.samples);
  if (complete) cJSON_AddNumberToObject(metadata,"dropped",data.dropped);
  else cJSON_AddNullToObject(metadata,"dropped");
  cJSON_AddBoolToObject(metadata,"overflow",overflow);cJSON_AddBoolToObject(metadata,"capture_complete",complete);
  data.metadata=compact(metadata);cJSON_Delete(metadata);
  if (data.metadata.length()>FireDataEngineContract::kMetadataBytes) {error="result_too_large";return false;}
  return save(data,error);
}
bool FireDataStore::read(const Dataset& data,uint32_t offset,uint8_t* bytes,size_t& length,const char*& error) {
  return readPart(data,"data",offset,bytes,length,error);
}
uint32_t FireDataStore::partSize(const Dataset& data,const String& part) {
  return part=="data"?data.size:part=="index"?data.indexSize:part=="events"?data.eventsSize:UINT32_MAX;
}
bool FireDataStore::readPart(const Dataset& data,const String& part,uint32_t offset,uint8_t* bytes,size_t& length,const char*& error) {
  const uint32_t size=partSize(data,part);
  if (size==UINT32_MAX || offset>size) {error="offset_mismatch";return false;}
  length=min<size_t>(length,size-offset);
  const String filename=part=="data"?String("data"):part+".jsonl";
  File file=fs_->open(folder(data.id)+"/"+filename,FILE_READ);
  if (!file || file.size()<size || !file.seek(offset) || file.read(bytes,length)!=length) {file.close();error="storage_unavailable";return false;}
  file.close();return true;
}
bool FireDataStore::startSeal(uint16_t job,Dataset& data,const char*& error) {
  if (hashJob_) {error="busy";return false;}
  if (!owns(data)) {error="stale_run";return false;}
  if (data.state=="sealed") {error="sealed";return false;}
  Dataset latest;if (!load(data.id,latest,error)) return false;
  if (latest.size!=data.size || latest.state=="sealed") {error="offset_mismatch";return false;}
  data.eventsSize=latest.eventsSize;data.indexSize=latest.indexSize;
  if (!recoverData(data,error)) return false;
  hashFile_=fs_->open(folder(data.id)+"/data",FILE_READ);
  if (!hashFile_ || hashFile_.size()!=data.size) {hashFile_.close();error="checksum_mismatch";return false;}
  if (data.kind=="audio") {
    uint8_t header[44];
    if (hashFile_.read(header,sizeof(header))!=sizeof(header) ||
        !fire_data_journal::pcm16Wav(header,sizeof(header),data.size) || !hashFile_.seek(0)) {
      hashFile_.close();error="invalid_data";return false;
    }
  }
  mbedtls_sha256_init(&hash_);
  if (mbedtls_sha256_starts_ret(&hash_,0)) {mbedtls_sha256_free(&hash_);hashFile_.close();error="busy";return false;}
  hashJob_=job;hashBytes_=0;hashPart_=0;hashId_=data.id;return true;
}
int FireDataStore::sealStep(uint16_t job,Dataset& data,const char*& error) {
  if (hashJob_!=job) {error="invalid_handle";return -1;}
  uint8_t buffer[512];
  const uint32_t size=hashPart_==0?data.size:hashPart_==1?data.indexSize:data.eventsSize;
  const int64_t started=esp_timer_get_time();
  for (uint8_t i=0;i<8 && hashBytes_<size && esp_timer_get_time()-started<3000;++i) {
    const size_t amount=min<size_t>(sizeof(buffer),size-hashBytes_);
    if (hashFile_.read(buffer,amount)!=amount || mbedtls_sha256_update_ret(&hash_,buffer,amount)) {cancel(job);error="checksum_mismatch";return -1;}
    hashBytes_+=amount;
  }
  if (hashBytes_<size) return 0;
  uint8_t digest[32];
  const int status=mbedtls_sha256_finish_ret(&hash_,digest);
  if (status) {cancel(job);error="checksum_mismatch";return -1;}
  const char* hex="0123456789abcdef";String sha;sha.reserve(64);
  for (uint8_t value:digest) {sha+=hex[value>>4];sha+=hex[value&15];}
  if (hashPart_==0) data.sha=sha;
  else if (hashPart_==1) data.indexSha=sha;
  else data.eventsSha=sha;
  hashFile_.close();mbedtls_sha256_free(&hash_);
  if (++hashPart_<3) {
    const String name=hashPart_==1?String("index.jsonl"):String("events.jsonl");
    hashFile_=fs_->open(folder(data.id)+"/"+name,FILE_READ);
    mbedtls_sha256_init(&hash_);
    if (!hashFile_ || hashFile_.size()!=(hashPart_==1?data.indexSize:data.eventsSize) || mbedtls_sha256_starts_ret(&hash_,0)) {cancel(job);error="checksum_mismatch";return -1;}
    hashBytes_=0;return 0;
  }
  hashJob_=0;hashId_=String();
  Dataset next=data;next.state="sealed";
  if (!save(next,error)) return -1;
  data=next;remember(data.id);return 1;
}
void FireDataStore::cancel(uint16_t job) {
  if (hashJob_!=job) return;
  hashFile_.close();mbedtls_sha256_free(&hash_);hashJob_=0;hashId_=String();
}
String FireDataStore::info(const Dataset& data) const {
  cJSON* obj=cJSON_CreateObject();if (!obj) return String();
  cJSON_AddBoolToObject(obj,"ok",true);cJSON_AddStringToObject(obj,"dataset_id",data.id.c_str());
  cJSON_AddStringToObject(obj,"kind",data.kind.c_str());cJSON_AddStringToObject(obj,"label",data.label.c_str());
  cJSON_AddStringToObject(obj,"state",data.state.c_str());cJSON_AddStringToObject(obj,"sha256",data.sha.c_str());
  cJSON_AddNumberToObject(obj,"size",data.size);
  const String out=compact(obj);cJSON_Delete(obj);return out;
}
String FireDataStore::descriptor(const Dataset& data) const {
  cJSON* obj=cJSON_CreateObject();if (!obj) return String();
  cJSON_AddStringToObject(obj,"dataset_id",data.id.c_str());cJSON_AddStringToObject(obj,"kind",data.kind.c_str());
  cJSON_AddStringToObject(obj,"label",data.label.c_str());cJSON_AddStringToObject(obj,"sha256",data.sha.c_str());
  cJSON_AddNumberToObject(obj,"size",data.size);cJSON_AddNumberToObject(obj,"created_ms",data.created);
  cJSON_AddStringToObject(obj,"metadata_json",data.metadata.c_str());cJSON_AddStringToObject(obj,"origin_package_id",data.package.c_str());
  cJSON_AddStringToObject(obj,"origin_source_sha256",data.source.c_str());cJSON_AddStringToObject(obj,"origin_run_id",data.run.c_str());
  cJSON_AddStringToObject(obj,"acquisition",data.acquisition.c_str());
  cJSON* components=cJSON_AddObjectToObject(obj,"components");
  const char* names[]={"data","index","events"};
  const uint32_t sizes[]={data.size,data.indexSize,data.eventsSize};
  const String* hashes[]={&data.sha,&data.indexSha,&data.eventsSha};
  for (uint8_t i=0;i<3;++i) {
    cJSON* part=cJSON_AddObjectToObject(components,names[i]);
    cJSON_AddNumberToObject(part,"size",sizes[i]);cJSON_AddStringToObject(part,"sha256",hashes[i]->c_str());
  }
  const String out=compact(obj);cJSON_Delete(obj);return out;
}
String FireDataStore::recent() const {
  String out="[";
  for (uint8_t i=0;i<recentCount_;++i) {if (i) out+=",";out+="\""+recent_[i]+"\"";}
  return out+"]";
}
