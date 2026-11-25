#include "fire_data_paths.h"
#include "fire_data_journal.h"
#include "fire_hardware_policy.h"
#include "fire_data_deadline.h"
#include "fire_audio_capture_core.h"
#include <assert.h>
#include <map>
#include <string>
#include <vector>
#include <stdio.h>

struct Files {
  std::map<std::string,std::string> contents;
  bool shortWrite=false,corruptRead=false,openFailure=false,resizeFailure=false;
  std::vector<std::string> resized;
  struct File {
    Files* fs=nullptr;std::string name;size_t offset=0;bool opened=false;
    explicit operator bool() const {return opened;}
    bool setBufferSize(size_t) {return opened;}
    size_t size() const {return opened?fs->contents.at(name).size():0;}
    bool seek(size_t value) {if (!opened || value>size()) return false;offset=value;return true;}
    void close() {opened=false;}
    size_t write(const uint8_t* bytes,size_t length) {
      if (!opened) return 0;
      const size_t n=fs->shortWrite?std::min<size_t>(length,1):length;
      auto& data=fs->contents[name];
      if (offset+n>data.size()) data.resize(offset+n);
      if (n) memcpy(&data[offset],bytes,n);
      offset+=n;return n;
    }
    size_t read(uint8_t* bytes,size_t length) {
      if (!opened) return 0;
      const auto& data=fs->contents.at(name);const size_t n=std::min(length,data.size()-offset);
      if (n) {memcpy(bytes,data.data()+offset,n);if (fs->corruptRead) bytes[0]^=1;}
      offset+=n;return n;
    }
  };
  File open(const char* path,const char* mode) {
    const std::string name(path);
    if (openFailure || (mode[0]=='r' && !contents.count(name))) return {};
    if (mode[0]=='w') contents[name].clear();
    if (mode[0]=='a') contents.try_emplace(name,"");
    File file{this,name,mode[0]=='a'?contents[name].size():0,true};return file;
  }
  bool resize(const std::string& name,uint32_t length) {
    if (resizeFailure) return false;
    contents[name].resize(length);resized.push_back(name);return true;
  }
};

int main() {
  assert(fire_audio_capture_core::rawPcm(0)==INT16_MIN);
  assert(fire_audio_capture_core::rawPcm(2048)==0);
  assert(fire_audio_capture_core::rawPcm(4095)==32752);
  int16_t pcm[2]={-1,-1};std::atomic<size_t> published{0};
  fire_audio_capture_core::publish(pcm,0,123,published);
  assert(published.load(std::memory_order_acquire)==1 && pcm[0]==123 && pcm[1]==-1);
  fire_audio_capture_core::publish(pcm,1,-321,published);
  assert(published.load(std::memory_order_acquire)==2 && pcm[1]==-321);
  uint8_t wav[44]={};
  memcpy(wav,"RIFF",4);memcpy(wav+8,"WAVEfmt ",8);memcpy(wav+36,"data",4);
  fire_data_journal::put32(wav+4,40);fire_data_journal::put32(wav+16,16);
  wav[20]=1;wav[22]=1;wav[32]=2;wav[34]=16;
  fire_data_journal::put32(wav+24,16000);fire_data_journal::put32(wav+28,32000);
  fire_data_journal::put32(wav+40,4);
  assert(fire_data_journal::pcm16Wav(wav,sizeof(wav),48));
  assert(!fire_data_journal::pcm16Wav(wav,sizeof(wav),46));
  assert(!fire_data_journal::pcm16Wav(wav,sizeof(wav),47));
  assert(!fire_data_journal::pcm16Wav(wav,43,48));
  wav[22]=2;assert(!fire_data_journal::pcm16Wav(wav,sizeof(wav),48));wav[22]=1;
  fire_data_journal::put32(wav+24,8000);fire_data_journal::put32(wav+28,16000);
  assert(fire_data_journal::pcm16Wav(wav,sizeof(wav),48));
  fire_data_journal::put32(wav+40,2);assert(!fire_data_journal::pcm16Wav(wav,sizeof(wav),48));
  puts("PASS raw PCM publish ordering and strict mono PCM WAV format and length");
  assert(!fire_data_deadline::expired(31000,0,0,30000,false,true));
  assert(fire_data_deadline::expired(180001,0,0,30000,false,true));
  assert(!fire_data_deadline::expired(180000,170000,0,30000,false,false));
  assert(fire_data_deadline::expired(200001,170000,0,30000,false,false));
  assert(fire_data_deadline::expired(31000,0,0,30000,false,false)); // old AI without refs
  assert(!fire_data_deadline::expired(90000,0,89000,5000,true,false));
  assert(fire_data_deadline::expired(94001,0,89000,5000,true,false));
  assert(!fire_data_deadline::expired(100,UINT32_MAX-100,0,5000,false,false));
  puts("PASS data sync and model deadlines bounded independently with local progress and wraparound");
  using fire_data_paths::safeMutation;
  for (const char* path:{"notes.txt","datasets/user-notes/test.csv","datasets/measurement old/data","measurements/æøå.txt"}) assert(safeMutation(path));
  for (const char* path:{"datasets/ds-a-b-c/data","DATASETS/DS-A-B-C/MANIFEST.JSON","datasets/DS-1234-5678-9/events.jsonl",
      "DATASETS/DS-123~1/DATA","DATAS~1/ds-a-b-c/data","datasets//ds-a-b-c/data","./datasets/ds-a-b-c/data",
      "datasets /ds-a-b-c/data","datasets./ds-a-b-c/data","datasets/../data","datasets/./ds-a-b-c/data","/datasets/ds-a-b-c/data"}) assert(!safeMutation(path));
  assert(!safeMutation("dataſets/ds-a-b-c/data"));
  assert(!safeMutation("datasets",true) && !safeMutation("DATASETS",true));
  assert(safeMutation("datasets",false));
  assert(!fire_data_paths::generated("ds-user-data",12));
  assert(fire_data_paths::generated("ds-a-b-c",8));
  puts("PASS data protected paths preserve user folders and reject FAT case dot slash DOS aliases");
  for (uint8_t address:{0x29,0x34,0x41,0x44,0x51,0x60,0x69,0x76}) assert(fire_hardware_policy::externalI2cWrite(address));
  for (uint8_t address:{0,7,0x10,0x68,0x75,0x78,0x7f}) assert(!fire_hardware_policy::externalI2cWrite(address));
  assert(fire_hardware_policy::externalSpi(2,18,19,23,26));
  assert(!fire_hardware_policy::externalSpi(2,18,19,23,27));
  assert(!fire_hardware_policy::externalSpi(2,16,19,23,26));
  puts("PASS FIRE external I2C policy and separate shared-SPI CS leave board pins reserved");
  Files fs;const std::string path="data";const uint8_t bytes[]={0,1,2,255};
  assert(fire_data_journal::writeChecked(fs,path,bytes,sizeof(bytes),false));
  assert(fs.contents[path]==std::string(reinterpret_cast<const char*>(bytes),sizeof(bytes)));
  assert(fire_data_journal::writeChecked(fs,path,bytes,sizeof(bytes),true));
  const auto committed=fs.contents[path];
  fs.shortWrite=true;assert(!fire_data_journal::writeChecked(fs,path,bytes,sizeof(bytes),true));
  assert(fs.contents[path].substr(0,committed.size())==committed);
  fs.shortWrite=false;fs.corruptRead=true;
  assert(!fire_data_journal::writeChecked(fs,std::string("corrupt"),bytes,sizeof(bytes),false));
  fs.corruptRead=false;fs.openFailure=true;
  assert(!fire_data_journal::writeChecked(fs,path,bytes,sizeof(bytes),false));fs.openFailure=false;
  const auto resize=[&](const std::string& name,uint32_t length) {return fs.resize(name,length);};
  assert(fire_data_journal::recoverPart(fs,path,committed.size(),false,resize));assert(fs.contents[path]==committed);
  fs.contents[path]+="tail";
  assert(!fire_data_journal::recoverPart(fs,path,committed.size(),true,resize));assert(fs.contents[path]==committed+"tail");
  fs.resizeFailure=true;
  assert(!fire_data_journal::recoverPart(fs,path,committed.size(),false,resize));fs.resizeFailure=false;
  fs.contents["events.jsonl"]="committed-mark\npartial";
  const auto rawBefore=fs.contents[path];
  assert(fire_data_journal::recoverPart(fs,std::string("events.jsonl"),15,false,resize));
  assert(fs.contents[path]==rawBefore); // growing raw capture is never an events recovery target
  assert(fire_data_journal::writeChecked(fs,std::string("events.jsonl"),bytes,sizeof(bytes),true));
  assert(fs.contents[path]==rawBefore);
  assert(fire_data_journal::writeChecked(fs,std::string("empty-component"),bytes,0,false));
  puts("PASS data journal short writes corrupt readback committed-prefix recovery and mark beside growing capture");
}
