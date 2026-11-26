#include "fire_evolution.h"
#include "fire_data_journal.h"
#include "fire_json_guard.h"
#include <cJSON.h>
#include <mbedtls/sha256.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <initializer_list>

namespace {
constexpr char kRoot[]="/logs/evolution/outbox";
String compact(cJSON* obj) {char* raw=obj?cJSON_PrintUnformatted(obj):nullptr;String text=raw?String(raw):String();cJSON_free(raw);return text;}
String field(const cJSON* obj,const char* name) {const auto* v=cJSON_GetObjectItemCaseSensitive(obj,name);return cJSON_IsString(v)?String(v->valuestring):String();}
bool identifier(const String& text) {
  if (!text.length() || text.length()>64) return false;
  for (size_t i=0;i<text.length();++i) {const char c=text[i];if (!((c>='a' && c<='z') || (c>='0' && c<='9') || c=='-' || c=='_')) return false;}
  return true;
}
String digest(const String& app,const String& package,const String& source,const String& payload) {
  mbedtls_sha256_context ctx;mbedtls_sha256_init(&ctx);int rc=mbedtls_sha256_starts_ret(&ctx,0);
  for (const String* value:{&app,&package,&source,&payload}) {
    rc|=mbedtls_sha256_update_ret(&ctx,reinterpret_cast<const uint8_t*>(value->c_str()),value->length());
    const uint8_t zero=0;rc|=mbedtls_sha256_update_ret(&ctx,&zero,1);
  }
  uint8_t bytes[32];rc|=mbedtls_sha256_finish_ret(&ctx,bytes);mbedtls_sha256_free(&ctx);
  if (rc) return String();
  String result;result.reserve(64);const char* hex="0123456789abcdef";
  for (uint8_t b:bytes) {result+=hex[b>>4];result+=hex[b&15];}return result;
}
String readFile(fs::FS& fs,const String& path,size_t maxBytes) {
  File f=fs.open(path,FILE_READ);if (!f || f.isDirectory() || f.size()>maxBytes) {f.close();return String();}
  const size_t length=f.size();String value;if (!value.reserve(length)) {f.close();return String();}
  uint8_t chunk[128];
  while (value.length()<length) {const size_t n=min<size_t>(sizeof(chunk),length-value.length());if (f.read(chunk,n)!=n || !value.concat(reinterpret_cast<const char*>(chunk),n)) break;}
  f.close();return value.length()==length?value:String();
}
} // namespace

String FireEvolution::path(uint8_t slot) const {return String(kRoot)+"/batch-"+String(slot)+".json";}
void FireEvolution::select(fs::FS& fs,const String& app,const String& package,const String& source,const String& boot,uint32_t now) {
  finish(now);fs_=&fs;app_=app;package_=package;source_=source;boot_=boot;run_=String();started_=now;consent_=false;
}
void FireEvolution::bindRun(const String& run,uint32_t now) {
  if (run_==run) return;
  // Never relabel an unbound window as having belonged to a server run.
  if (consent_ && !aggregate_.empty()) queue(now);
  aggregate_={};started_=now;run_=run;
}
void FireEvolution::consent(const String& app,bool enabled,uint32_t now) {
  if (app!=app_) return;
  if (consent_!=enabled) {aggregate_={};started_=now;}
  consent_=enabled;
}
void FireEvolution::callback(uint8_t phase,uint32_t us,uint32_t heap,uint32_t luaPeak) {
  if (!consent_ || phase>=3) return;
  aggregate_.callbacks[phase].add(us);aggregate_.sample(heap,luaPeak);
}
void FireEvolution::button(uint8_t index) {if (consent_ && index<3) fire_evolution::increment(aggregate_.buttons[index]);}
void FireEvolution::error(const char* operation,const char* code) {if (consent_) aggregate_.error(operation,code);}
void FireEvolution::finish(uint32_t now) {
  if (consent_ && !aggregate_.empty()) queue(now);
  aggregate_={};consent_=false;app_=String();package_=String();source_=String();run_=String();started_=now;
}
bool FireEvolution::queue(uint32_t now) {
  const auto fail=[&](const char* why) {error_=why;fire_evolution::increment(dropped_);return false;};
  if (!fs_ || !storageAllowed_ || !ready() || stageBlocked_) return fail("Outbox ikke klar");
  if (!identifier(app_) || !identifier(package_) || source_.length()!=64 || !boot_.length()) return fail("Ubundet pakke");
  const String batch="evb-"+String(esp_random(),HEX)+"-"+String(now,HEX);
  cJSON* payload=cJSON_CreateObject();if (!payload) return fail("Lite arbeidsminne");
  cJSON_AddNumberToObject(payload,"schema",FireEvolutionContract::kSchemaVersion);cJSON_AddStringToObject(payload,"batch_id",batch.c_str());
  cJSON_AddStringToObject(payload,"captured_boot_id",boot_.c_str());
  if (run_.length()) cJSON_AddStringToObject(payload,"run_id",run_.c_str());
  // Keep boot-relative timestamps ordered across millis()'s 32-bit wrap.
  const uint64_t endMs=static_cast<uint64_t>(esp_timer_get_time())/1000;
  const uint32_t elapsed=now-started_;
  cJSON_AddNumberToObject(payload,"start_ms",static_cast<double>(endMs>=elapsed?endMs-elapsed:0));
  cJSON_AddNumberToObject(payload,"end_ms",static_cast<double>(endMs));
  cJSON* callbacks=cJSON_AddObjectToObject(payload,"callbacks");const char* phases[]={"init","update","on_button"};
  for (uint8_t i=0;i<3;++i) {auto* row=cJSON_AddObjectToObject(callbacks,phases[i]);const auto& v=aggregate_.callbacks[i];
    cJSON_AddNumberToObject(row,"count",v.count);cJSON_AddNumberToObject(row,"total_us",static_cast<double>(v.totalUs));cJSON_AddNumberToObject(row,"max_us",v.maxUs);}
  cJSON* buttons=cJSON_AddObjectToObject(payload,"buttons");const char* names[]={"A","B","C"};
  for (uint8_t i=0;i<3;++i) cJSON_AddNumberToObject(buttons,names[i],aggregate_.buttons[i]);
  cJSON* errors=cJSON_AddArrayToObject(payload,"job_errors");
  for (uint8_t i=0;i<aggregate_.errorCount;++i) {auto* row=cJSON_CreateObject();cJSON_AddItemToArray(errors,row);const auto& v=aggregate_.errors[i];
    cJSON_AddStringToObject(row,"operation",v.operation);cJSON_AddStringToObject(row,"error_code",v.code);cJSON_AddNumberToObject(row,"count",v.count);}
  cJSON_AddNumberToObject(payload,"dropped_batches",dropped_);
  if (aggregate_.heapMin!=UINT32_MAX) cJSON_AddNumberToObject(payload,"free_heap_min",aggregate_.heapMin);
  cJSON_AddNumberToObject(payload,"lua_bytes_peak",aggregate_.luaPeak);
  const String text=compact(payload);cJSON_Delete(payload);
  if (!text.length() || text.length()>FireEvolutionContract::kTelemetryJsonBytes) return fail("For stor statistikk");
  cJSON* record=cJSON_CreateObject();if (!record) return fail("Lite arbeidsminne");
  cJSON_AddStringToObject(record,"app_id",app_.c_str());cJSON_AddStringToObject(record,"package_id",package_.c_str());
  cJSON_AddStringToObject(record,"source_sha256",source_.c_str());cJSON_AddStringToObject(record,"payload",text.c_str());
  const String hash=digest(app_,package_,source_,text);cJSON_AddStringToObject(record,"checksum",hash.c_str());
  const String body=compact(record);cJSON_Delete(record);
  const int slot=box_.freeSlot(body.length());
  if (!hash.length() || !body.length() || body.length()>kRecordMax || slot<0) return fail("Outbox full");
  for (const char* dir:{"/logs","/logs/evolution",kRoot}) if (!fs_->exists(dir) && !fs_->mkdir(dir)) return fail("SD utilgjengelig");
  const String stage=String(kRoot)+"/batch.new";
  if (fs_->exists(stage) || fs_->exists(path(slot))) return fail("Outbox trenger kontroll");
  if (!fire_data_journal::writeChecked(*fs_,stage,reinterpret_cast<const uint8_t*>(body.c_str()),body.length(),false) || !fs_->rename(stage,path(slot))) {
    stageBlocked_=true;return fail("Outbox skrivefeil");
  }
  box_.add(slot,body.length());error_="";return true;
}
void FireEvolution::service(fs::FS& fs,uint32_t now,bool allowStorage) {
  fs_=&fs;storageAllowed_=allowStorage;if (!allowStorage) return;
  if (!ready()) {
    const uint8_t slot=scan_++;File f;if (fs.exists(path(slot))) f=fs.open(path(slot),FILE_READ);
    if (f) {const size_t bytes=f.size();f.close();if (!bytes || bytes>kRecordMax || !box_.add(slot,bytes)) {box_.blocked[slot]=true;error_="Outbox trenger kontroll";stageBlocked_=true;}}
    if (ready() && fs.exists(String(kRoot)+"/batch.new")) {
      const String stage=String(kRoot)+"/batch.new";Entry recovered;
      File f=fs.open(stage,FILE_READ);const size_t bytes=f?f.size():0;f.close();
      const int target=box_.freeSlot(bytes);
      if (target>=0 && readPath(stage,recovered) && fs.rename(stage,path(target))) box_.add(target,bytes);
      else {stageBlocked_=true;error_="Ufullstendig outbox";}
    }
    return;
  }
  if (consent_ && now-started_>=FireEvolutionContract::kTelemetryIntervalMs) {
    if (!aggregate_.empty()) queue(now);
    aggregate_={};started_=now;
  }
}
bool FireEvolution::read(uint8_t slot,Entry& out,String* checksum) {
  if (!readPath(path(slot),out,checksum)) return false;
  out.slot=slot;return true;
}
bool FireEvolution::readPath(const String& path,Entry& out,String* checksum) {
  if (!fs_) return false;
  const String body=readFile(*fs_,path,kRecordMax);
  if (!fireJsonSafe(body.c_str(),body.length(),kRecordMax,5,64)) return false;
  cJSON* obj=cJSON_Parse(body.c_str());out.app=field(obj,"app_id");out.package=field(obj,"package_id");out.source=field(obj,"source_sha256");out.payload=field(obj,"payload");
  const String expected=field(obj,"checksum");cJSON_Delete(obj);
  if (!identifier(out.app) || !identifier(out.package) || out.source.length()!=64 || out.payload.length()>FireEvolutionContract::kTelemetryJsonBytes ||
      !expected.length() || digest(out.app,out.package,out.source,out.payload)!=expected || !fireJsonSafe(out.payload.c_str(),out.payload.length(),FireEvolutionContract::kTelemetryJsonBytes)) return false;
  obj=cJSON_Parse(out.payload.c_str());out.batch=field(obj,"batch_id");cJSON_Delete(obj);
  if (!identifier(out.batch)) return false;
  if (checksum) *checksum=expected;
  return true;
}
bool FireEvolution::next(Entry& out) {
  if (!ready() || !storageAllowed_) return false;
  for (uint8_t n=0;n<FireEvolutionContract::kOutboxBatches;++n) {
    const uint8_t i=next_++%FireEvolutionContract::kOutboxBatches;
    if (!box_.bytes[i] || box_.blocked[i]) continue;
    if (read(i,out)) return true;
    box_.blocked[i]=true;error_="Ugyldig outbox";return false;
  }
  return false;
}
void FireEvolution::sent(const Entry& entry,const String& request) {
  pendingSlot_=entry.slot;pendingRequest_=request;pendingBatch_=entry.batch;pendingHash_=digest(entry.app,entry.package,entry.source,entry.payload);
}
bool FireEvolution::acknowledge(const String& request,const String& batch,const String& status) {
  if (pendingSlot_<0 || request!=pendingRequest_ || batch!=pendingBatch_) return false;
  if (!storageAllowed_) return false; // retain for a later duplicate ACK after the SD owner is free
  if (status=="rejected") {box_.blocked[pendingSlot_]=true;pendingSlot_=-1;error_="Statistikk avvist";return false;}
  if (!fire_evolution::acceptedAck(pendingRequest_.c_str(),pendingBatch_.c_str(),request.c_str(),batch.c_str(),status.c_str())) return false;
  Entry actual;String checksum;
  if (!read(pendingSlot_,actual,&checksum) || actual.batch!=batch || checksum!=pendingHash_ || !fs_->remove(path(pendingSlot_))) {error_="Outbox kvitteringsfeil";return false;}
  box_.remove(pendingSlot_);pendingSlot_=-1;pendingRequest_=String();pendingBatch_=String();pendingHash_=String();return true;
}
