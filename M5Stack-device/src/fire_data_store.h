#pragma once
#include <Arduino.h>
#include <FS.h>
#include <mbedtls/sha256.h>
#include "fire_data_engine_contract.h"

// UI-owner only. No filesystem work runs in a Lua callback. One streamed hash
// and one catalog cursor share the existing four-job broker, never a new task.
class FireDataStore {
 public:
  struct Owner { String app, package, source, run, boot, instance; };
  struct Dataset {
    String id, label, kind, metadata, state, sha, indexSha, eventsSha, instance;
    String package, source, run, boot, acquisition="app_recorded";
    uint32_t size=0, created=0, samples=0, dropped=0, indexSize=0, eventsSize=0;
  };
  void configure(fs::FS& fs,const Owner& owner);
  void close();
  bool catalogStep(const char*& error);
  bool catalogReady() const { return ready_; }
  bool create(const String& label,const String& kind,const String& metadata,Dataset& out,const char*& error);
  bool load(const String& id,Dataset& out,const char*& error);
  bool append(Dataset& data,const uint8_t* bytes,size_t length,const char*& error);
  bool prepareCapture(Dataset& data,const String& acquisition,const String& metadata,const char*& error);
  bool captureSummary(Dataset& data,uint32_t samples,uint32_t dropped,const char*& error);
  bool partialCapture(const String& id,bool overflow,const char*& error);
  bool hasCapacity(uint32_t size) const {return size<=FireDataEngineContract::kAppBytes-used_;}
  bool mark(Dataset& data,const String& label,const char*& error);
  bool read(const Dataset& data,uint32_t offset,uint8_t* bytes,size_t& length,const char*& error);
  bool readPart(const Dataset& data,const String& part,uint32_t offset,uint8_t* bytes,size_t& length,const char*& error);
  static uint32_t partSize(const Dataset& data,const String& part);
  bool startSeal(uint16_t job,Dataset& data,const char*& error);
  int sealStep(uint16_t job,Dataset& data,const char*& error);
  void cancel(uint16_t job);
  uint16_t hashingJob() const {return hashJob_;}
  bool owns(const Dataset& data) const;
  String folder(const String& id) const;
  String info(const Dataset& data) const;
  String descriptor(const Dataset& data) const;
  String recent() const;
  const Owner& owner() const { return owner_; }
  void bindRun(const String& run) {owner_.run=run;}
  static bool identifier(const char* text,size_t length);
  static bool generatedId(const String& id);
 private:
  fs::FS* fs_=nullptr;
  Owner owner_;
  String root_;
  File directory_, hashFile_;
  bool ready_=false, scanning_=false;
  uint32_t used_=0;
  uint16_t count_=0, hashJob_=0;
  uint32_t hashBytes_=0;
  uint8_t hashPart_=0;
  String hashId_;
  mbedtls_sha256_context hash_{};
  String recent_[FireDataEngineContract::kContextDatasetRefs];
  uint8_t recentCount_=0;
  bool save(const Dataset& data,const char*& error);
  bool recoverData(const Dataset& data,const char*& error,bool markerOnly=false);
  bool writeChecked(const String& path,const uint8_t* bytes,size_t length,bool append,const char*& error);
  void remember(const String& id);
};
