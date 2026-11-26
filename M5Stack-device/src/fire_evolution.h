#pragma once
#include <Arduino.h>
#include <FS.h>
#include "fire_evolution_core.h"

// Owned solely by the OS/UI thread. Lua cannot grant consent or produce batches.
class FireEvolution {
 public:
  struct Entry {String app,package,source,payload,batch;int slot=-1;};
  void select(fs::FS& fs,const String& app,const String& package,const String& source,const String& boot,uint32_t now);
  void bindRun(const String& run,uint32_t now);
  void consent(const String& app,bool enabled,uint32_t now);
  bool consented() const {return consent_;}
  const String& app() const {return app_;}
  void callback(uint8_t phase,uint32_t us,uint32_t heap,uint32_t luaPeak);
  void button(uint8_t index);
  void error(const char* operation,const char* code);
  void finish(uint32_t now);
  void service(fs::FS& fs,uint32_t now,bool allowStorage);
  bool next(Entry& out);
  bool acknowledge(const String& request,const String& batch,const String& status);
  void sent(const Entry& entry,const String& request);
  uint8_t pending() const {return box_.count;}
  uint32_t dropped() const {return dropped_;}
  const char* status() const {return error_;}
  bool ready() const {return scan_>=FireEvolutionContract::kOutboxBatches;}
 private:
  static constexpr size_t kRecordMax=2560;
  fs::FS* fs_=nullptr;
  fire_evolution::Aggregate aggregate_;
  fire_evolution::Outbox box_;
  String app_,package_,source_,boot_,run_;
  uint32_t started_=0,dropped_=0;
  uint8_t scan_=0,next_=0;
  bool consent_=false,stageBlocked_=false,storageAllowed_=false;
  int pendingSlot_=-1;
  String pendingRequest_,pendingBatch_,pendingHash_;
  const char* error_="";
  String path(uint8_t slot) const;
  bool read(uint8_t slot,Entry& out,String* checksum=nullptr);
  bool readPath(const String& path,Entry& out,String* checksum=nullptr);
  bool queue(uint32_t now);
};
