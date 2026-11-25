#include "fire_byte_queue.h"
#include "fire_json_guard.h"
#include "fire_runtime_ai_json.h"
#include "fire_ai_workflow.h"
#include "fire_lua_install_identity.h"
#include "fire_run_receipts.h"
#include <assert.h>
#include <string>
#include <thread>
#include <vector>
#include <map>
#include <algorithm>
#include <stdio.h>

namespace {
struct InstallFs {
  struct Node {bool directory=false;std::string bytes;bool operator==(const Node& v) const {return directory==v.directory && bytes==v.bytes;}};
  std::map<std::string,Node> nodes;
  bool shortWrite=false,corruptRead=false,readError=false;unsigned renameCalls=0,failRenameAt=0,closed=0;
  struct File {
    InstallFs* fs;std::string path;bool open;size_t position=0;
    explicit operator bool() const {return open;}
    bool isDirectory() const {return fs->nodes.at(path).directory;}
    size_t size() const {return fs->nodes.at(path).bytes.size();}
    size_t write(const uint8_t* data,size_t n) {
      const size_t count=fs->shortWrite?n-1:n;fs->nodes[path].bytes.assign(reinterpret_cast<const char*>(data),count);return count;
    }
    size_t read(uint8_t* data,size_t n) {
      const auto& text=fs->nodes.at(path).bytes;const size_t count=std::min(n,text.size()-position);
      memcpy(data,text.data()+position,count);position+=count;
      if(fs->corruptRead && count) data[0]^=1;
      return count;
    }
    void close() {if(open) ++fs->closed;open=false;}
  };
  File open(const char* path,const char* mode) {
    if(mode[0]=='w') {nodes[path]=Node{};return {this,path,true};}
    if(readError) {errno=EIO;return {this,path,false};}
    if(!nodes.count(path)) {errno=ENOENT;return {this,path,false};}
    return {this,path,true};
  }
  bool exists(const char* path) {return nodes.count(path)!=0;}
  bool rename(const char* from,const char* to) {
    if(++renameCalls==failRenameAt || !nodes.count(from) || nodes.count(to)) return false;
    std::map<std::string,Node> moved;
    const std::string prefix=std::string(from)+"/";
    for(auto it=nodes.begin();it!=nodes.end();) {
      if(it->first==from || it->first.compare(0,prefix.size(),prefix)==0) {
        moved[std::string(to)+it->first.substr(strlen(from))]=it->second;it=nodes.erase(it);
      } else ++it;
    }
    nodes.insert(moved.begin(),moved.end());return true;
  }
};
void installIdentityTests() {
  using namespace fire_lua_install;
  Identity identity;strcpy(identity.app,"test-app");strcpy(identity.package,"build-tested");strcpy(identity.project,"app-project");
  strcpy(identity.archive,std::string(64,'a').c_str());strcpy(identity.source,std::string(64,'b').c_str());
  char body[kMaxBytes+1];const size_t n=encode(identity,body,sizeof(body));Identity decoded;
  assert(n && decode(body,n,decoded) && decoded==identity);
  assert(identity.matches("test-app","build-tested",identity.archive,identity.source));
  assert(!identity.matches("other-app","build-tested",identity.archive,identity.source));
  assert(!identity.matches("test-app","build-other",identity.archive,identity.source));
  assert(!identity.matches("test-app","build-tested",identity.source,identity.source));
  assert(!identity.matches("test-app","build-tested",identity.archive,identity.archive));
  assert(!decode(body,n-1,decoded));body[n]='x';assert(!decode(body,n+1,decoded));body[n]=0;
  const char* path="/apps/.staging-build/.fire-install.json";InstallFs fs;
  assert(read(fs,path,decoded)==Read::Absent);
  // The actual writer/readback helper has no NVS dependency or cache lookup.
  assert(writeVerified(fs,path,identity) && fs.closed==2 && read(fs,path,decoded)==Read::Valid && decoded==identity);
  fs.nodes[path].bytes="{}";assert(read(fs,path,decoded)==Read::Invalid);
  fs.shortWrite=true;assert(!writeVerified(fs,path,identity));fs.shortWrite=false;
  fs.corruptRead=true;assert(!writeVerified(fs,path,identity));fs.corruptRead=false;
  fs.readError=true;assert(read(fs,path,decoded)==Read::Invalid);fs.readError=false;
  assert(writeVerified(fs,path,identity));
  fs.nodes[path].directory=true;assert(read(fs,path,decoded)==Read::Invalid);fs.nodes[path].directory=false;
  const std::string current="/apps/test-app",previous="/apps/.previous-test-app",temporary="/apps/.rollback-test-app";
  InstallFs versions;versions.nodes[current]={true,{}};versions.nodes[previous]={true,{}};
  versions.nodes[current+"/appdata"]={true,{}};versions.nodes[current+"/appdata/value"]={false,"USER DATA"};
  versions.nodes[current+"/.fire-install.json"]={false,"new package identity"};
  versions.nodes[previous+"/.fire-install.json"]={false,"previous package identity"};
  const auto before=versions.nodes;
  for(unsigned failure=1;failure<=4;++failure) {
    InstallFs attempt=versions;attempt.failRenameAt=failure;
    assert(!swapPrevious(attempt,current,previous,temporary) && attempt.nodes==before);
  }
  assert(swapPrevious(versions,current,previous,temporary));
  assert(versions.nodes[current+"/.fire-install.json"].bytes=="previous package identity");
  assert(versions.nodes[previous+"/.fire-install.json"].bytes=="new package identity");
  assert(versions.nodes[current+"/appdata/value"].bytes=="USER DATA" && !versions.nodes.count(temporary));
  puts("PASS installation identity cache-miss binding, shortwrite/corrupt readback rejection and rollback/appdata parity");
}
void runReceiptTests() {
  using namespace fire_run_receipts;Ring ring;Entry* entry=nullptr;
  const std::string source(64,'a'),archive(64,'b');
  for(unsigned i=0;i<Ring::kCapacity;++i) {
    const std::string id="run-"+std::to_string(i);
    assert(ring.admit(id.c_str(),"build-test",source.c_str(),archive.c_str(),20,10,true,entry)==Admission::New);
    entry->state=State::Started;
  }
  assert(ring.admit("run-more","build-test",source.c_str(),archive.c_str(),20,10,true,entry)==Admission::Busy && !entry);
  assert(ring.admit("run-0","build-test",source.c_str(),archive.c_str(),20,10,true,entry)==Admission::Duplicate && entry->state==State::Started);
  assert(ring.admit("run-0","build-other",source.c_str(),archive.c_str(),20,10,true,entry)==Admission::Invalid);
  assert(ring.admit("run-0","build-test",archive.c_str(),archive.c_str(),20,10,true,entry)==Admission::Invalid);
  assert(ring.admit("run-other","build-test",source.c_str(),archive.c_str(),30,10,false,entry)==Admission::Invalid);
  assert(ring.admit("run-old","build-test",source.c_str(),archive.c_str(),20,20,true,entry)==Admission::Invalid);
  assert(ring.admit("run-new","build-test",source.c_str(),archive.c_str(),30,20,true,entry)==Admission::New);
  for(const char* key:{"rr_0","rr_abcdef12","rr_123"}) assert(legacyKey(key));
  for(const char* key:{"rr_","rr_0001","rr_ABC","rr_123456789","wifi_pass","lp_123"}) assert(!legacyKey(key));
  for(const char* value:{"starting","started","healthy","failed"}) assert(legacyValue(value));
  assert(!legacyValue("token") && !legacyValue("started-other"));
  puts("PASS bounded boot-bound run receipts preserve replay/state until expiry and safely reject full ring");
}
} // namespace

int main() {
  installIdentityTests();runReceiptTests();
  for(uint8_t phase=0;phase<=6;++phase) for(uint8_t speech:{uint8_t(0),uint8_t(1),uint8_t(2)})
    assert(fireConversationState(phase,speech)==(phase>=3?phase:speech));
  puts("PASS assistant/TTS lifecycle preserves ready/build/install/run confirmation phases");
  const auto aiJson=[](const std::string& s) {return fire_runtime_ai_json::validObject(s.c_str(),s.size(),512);};
  assert(aiJson("{\"value\":12.5,\"nested\":{\"a\":[1,2,3]},\"text\":\"\\u00e6\\ud83d\\ude80\",\"null\":null}"));
  assert(!aiJson("{\"x\":1,\"x\":2}") && !aiJson("{\"x\":1,\"\\u0078\":2}"));
  assert(!aiJson("{\"x\":NaN}") && !aiJson("{\"x\":1e999}") && !aiJson("{\"x\":01}"));
  assert(!aiJson("{\"x\":\"\\q\"}") && !aiJson("{\"x\":\"\\ud800\"}"));
  assert(!aiJson("{} garbage") && !aiJson("[]") && !aiJson("{\"a\":{\"b\":{\"c\":{\"d\":1}}}}"));
  assert(aiJson("{\"x\":\""+std::string(256,'a')+"\"}"));
  assert(!aiJson("{\"x\":\""+std::string(257,'a')+"\"}"));
  std::string worst="{\"v\":[";
  for(unsigned i=0;i<16;++i) {if(i) worst+=",";worst+="{\"a\":1,\"b\":2,\"c\":3,\"d\":4}";}
  worst+="]}";assert(worst.size()<=512 && aiJson(worst));
  worst.insert(worst.size()-2,",0");assert(!aiJson(worst));
  puts("PASS Runtime AI strict JSON finite/UTF8/duplicates/depth4/array16/string256 and bounded worst-case result");
  auto safe = [](const std::string& s) { return fireJsonSafe(s.data(), s.size(), 32768); };
  assert(safe("{\"navn\":\"æøå\",\"quoted\":\"[\\\"}\"}"));
  assert(!safe(std::string(500, '[') + std::string(500, ']')));
  assert(!safe("{\"a\": [1,2}"));
  assert(!safe(std::string("{\"a\":\"\xc0\xaf\"}")));
  assert(!safe(std::string("{\"a\":\"\xed\xa0\x80\"}")));
  assert(!safe(std::string("{\"a\":\"\xf4\x90\x80\x80\"}")));
  assert(!safe(std::string("{\"a\":\"a\0b\"}", 11)));
  assert(!safe("{\"a\":\"unterminated}"));
  std::string many = "[";
  for (int i = 0; i < 1200; ++i) many += "0,";
  many += "0]"; assert(!safe(many));
  uint8_t storage[16], out[32] = {}; FireByteQueue queue; queue.initialize(storage, 16);
  const uint8_t first[] = {1,2,3,4,5,6,7,8,9,10,11,12};
  assert(queue.write(first, 12) == 12);
  assert(queue.write(first, 5) == 0); assert(queue.size() == 12);
  assert(queue.read(out, 8) == 8);
  assert(queue.write(first, 12) == 12); assert(queue.free() == 0);
  assert(queue.read(out, 16) == 16);
  for (int i = 0; i < 4; ++i) assert(out[i] == first[i + 8]);
  for (int i = 0; i < 12; ++i) assert(out[i + 4] == first[i]);
  // Exercise the actual SPSC implementation concurrently through many wraps.
  uint8_t ring[1024]; FireByteQueue concurrent; concurrent.initialize(ring, 1024);
  constexpr unsigned count = 1000000;
  std::thread writer([&]() {
    for (unsigned i = 0; i < count; ++i) { uint8_t b = i % 251; while (!concurrent.write(&b, 1)) std::this_thread::yield(); }
  });
  for (unsigned i = 0; i < count; ++i) {
    uint8_t b = 0; while (!concurrent.read(&b, 1)) std::this_thread::yield(); assert(b == i % 251);
  }
  writer.join(); assert(concurrent.size() == 0);
  puts("PASS native UTF-8/depth/token guard and atomic queue/backpressure/wrap/concurrency");
}
