#include "fire_local_qa.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
using namespace fire_local_qa;

// Deliberately non-cryptographic injected test provider. Production uses the
// existing token+mbedTLS; Python host tests exercise real HMAC-SHA256 vectors.
static std::string testMac(const char* text,size_t bytes) {
  uint32_t value=2166136261u;for(size_t i=0;i<bytes;++i)value=(value^uint8_t(text[i]))*16777619u;
  char result[65];for(unsigned i=0;i<8;++i)std::snprintf(result+i*8,9,"%08x",value^(0x1020304u*i));
  return result;
}
struct Host {
  Snapshot shown;
  unsigned snapshots=0,actions=0,stops=0;
  bool actionAllowed=true,ready=true;
  Op lastOp=Op::State;uint8_t lastButton=0;
  Host() {
    shown.context=7;shown.view=9;shown.presented=1;shown.screen=2;shown.index=1;shown.count=4;
    std::memset(shown.identity,'a',64);shown.identity[64]=0;
    std::strcpy(shown.label,"Main");std::strcpy(shown.detail,"Ready");
  }
  static bool verify(void*,const char* text,size_t bytes,const char* tag) {
    return testMac(text,bytes)==tag;
  }
  static bool sign(void*,const char* text,size_t bytes,char* tag) {
    const auto mac=testMac(text,bytes);std::memcpy(tag,mac.c_str(),65);return true;
  }
  static bool snapshot(void* context,Snapshot& out) {
    Host& self=*static_cast<Host*>(context);++self.snapshots;out=self.shown;return self.ready;
  }
  static Code action(void* context,const Command& command,Snapshot& out) {
    Host& self=*static_cast<Host*>(context);out=self.shown;
    if(!self.actionAllowed)return Code::Blocked;
    ++self.actions;self.lastOp=command.op;self.lastButton=command.button;return Code::Ok;
  }
  static void stop(void* context){++static_cast<Host*>(context)->stops;}
  Callbacks callbacks() {
    Callbacks value;value.context=this;value.verify=verify;value.sign=sign;
    value.snapshot=snapshot;value.action=action;value.stop=stop;return value;
  }
};
static const char* nonce="0123456789abcdef0123456789abcdef";
static const char* zeros="0000000000000000000000000000000000000000000000000000000000000000";
static std::string authenticate(const std::string& body) {
  const std::string signedBody=std::string(kDomain)+body;
  return body+"|"+testMac(signedBody.c_str(),signedBody.size());
}
static std::vector<std::string> fields(const char* wire) {
  std::string text(wire);assert(text.size()<kMaxWireBytes);assert(text.back()=='\n');text.pop_back();
  const auto macAt=text.rfind('|');assert(macAt!=std::string::npos);
  const std::string body=std::string(kDomain)+text.substr(0,macAt);
  assert(testMac(body.c_str(),body.size())==text.substr(macAt+1));
  std::vector<std::string> result;size_t start=0;
  for(size_t i=0;i<=text.size();++i)if(i==text.size()||text[i]=='|'){result.push_back(text.substr(start,i-start));start=i+1;}
  return result;
}
struct Fixture {
  Host host;Policy policy;char reply[kMaxWireBytes]={};
  Fixture(uint32_t boot=0){policy.begin(boot,nonce,host.callbacks());}
  bool raw(const std::string& wire,uint32_t now=10){return policy.handle(wire.c_str(),wire.size(),now,reply,sizeof(reply));}
  std::vector<std::string> send(const std::string& body,uint32_t now=10) {
    assert(raw(authenticate(body),now));return fields(reply);
  }
  void arm(unsigned ttl=10,unsigned limit=20,unsigned mask=3,uint32_t now=10) {
    auto reply=send(std::string("FQ1|ARM|")+nonce+"|"+std::to_string(ttl)+"|"+std::to_string(limit)+"|"+std::to_string(mask),now);
    assert(reply[4]=="0"&&policy.armed(now)&&policy.consumed());
  }
  std::string command(unsigned seq,const char* op="STATE",unsigned button=0,unsigned context=0,uint64_t view=0,const char* id=zeros) {
    char hexView[17];std::snprintf(hexView,sizeof(hexView),"%016llx",(unsigned long long)view);
    return std::string("FQ1|DO|")+nonce+"|"+std::to_string(seq)+"|"+op+"|"+std::to_string(button)+"|"+std::to_string(context)+"|"+hexView+"|"+id;
  }
  std::vector<std::string> button(unsigned seq,const char* op="CLICK",unsigned which=1) {
    return send(command(seq,op,which,host.shown.context,host.shown.view,host.shown.identity));
  }
};
int main() {
  static_assert(sizeof(Policy)<1024,"bounded UART policy, no framebuffer");
  {
    Fixture f;
    assert(!f.policy.armed(0)&&!f.policy.consumed());
    auto off=f.send(f.command(1));assert(off[4]=="3"&&f.host.snapshots==0&&f.host.actions==0);
    assert(f.raw("FQ1|HELLO"));assert(fields(f.reply)[1]=="C");
    std::string bad=authenticate(std::string("FQ1|ARM|")+nonce+"|10|20|3");bad.back()=bad.back()=='0'?'1':'0';
    assert(f.raw(bad)&&fields(f.reply)[4]=="2"&&!f.policy.consumed());
    for(const char* limits:{"0|20|3","901|20|3","10|0|3","10|501|3","10|20|2","01|20|3"})
      assert(!f.raw(authenticate(std::string("FQ1|ARM|")+nonce+"|"+limits))&&!f.policy.consumed());
    f.arm();assert(!f.raw("FQ1|HELLO"));const unsigned snapshots=f.host.snapshots;
    auto duplicate=f.send(std::string("FQ1|ARM|")+nonce+"|10|20|3");
    assert(duplicate[5]=="1"&&f.host.snapshots==snapshots);
    std::string forged=authenticate(f.command(1,"CLICK",1,7,9,f.host.shown.identity));
    forged.back()=forged.back()=='0'?'1':'0';
    assert(f.raw(forged)&&fields(f.reply)[4]=="2"&&f.host.actions==0&&f.host.snapshots==snapshots);
    auto state=f.send(f.command(1));assert(state[4]=="0"&&state[5]=="0");
    const unsigned observed=f.host.snapshots;auto replay=f.send(f.command(1));
    assert(replay[5]=="1"&&f.host.snapshots==observed&&f.host.actions==0);
    auto changed=f.send(f.command(1,"CLICK",1,7,9,f.host.shown.identity));assert(changed[4]=="6"&&f.host.actions==0);
    assert(f.button(2)[4]=="0"&&f.host.actions==1);
    assert(f.button(2)[5]=="1"&&f.host.actions==1);
    assert(f.button(3,"HOLD",2)[4]=="0"&&f.host.actions==2&&f.host.lastOp==Op::Hold&&f.host.lastButton==2);
    assert(f.send(f.command(UINT32_MAX))[4]=="6");
  }
  {
    Fixture f;f.arm(10,10,1);
    assert(f.button(1)[4]=="8"&&f.host.actions==0);
    assert(f.button(2,"HOLD")[4]=="8"&&f.host.actions==0);
    assert(f.send(f.command(3))[4]=="0");
    assert(f.send(f.command(4,"STOP"))[4]=="0"&&!f.policy.armed(11)&&f.host.stops==1);
    assert(f.send(f.command(4,"STOP"))[5]=="1"&&f.host.stops==1);
    assert(f.send(std::string("FQ1|ARM|")+nonce+"|10|10|1")[4]=="5");
  }
  {
    Fixture f;f.arm();
    const auto stale=f.command(1,"CLICK",1,8,9,f.host.shown.identity);
    assert(f.send(stale)[4]=="9"&&f.host.actions==0);
    f.host.shown.context=8;assert(f.send(stale)[5]=="1"&&f.host.actions==0);
    assert(f.send(f.command(2,"CLICK",1,8,10,f.host.shown.identity))[4]=="9");
    assert(f.send(f.command(3,"CLICK",1,8,9,zeros))[4]=="9");
    f.host.actionAllowed=false;assert(f.button(4)[4]=="11"&&f.host.actions==0);
    f.host.ready=false;assert(f.button(5)[4]=="10"&&f.host.actions==0);
  }
  {
    Fixture f;f.arm(1,1);assert(f.send(f.command(1))[4]=="0");
    assert(f.button(2)[4]=="7"&&f.host.actions==0);
    f.policy.tick(1010);assert(!f.policy.armed(1011)&&f.host.stops==1);
    f.policy.tick(4000);assert(f.host.stops==1);
    assert(f.send(f.command(1),1011)[4]=="4");
    assert(!f.raw(authenticate("FQ1|ARM|ffffffffffffffffffffffffffffffff|1|1|3"),1011));
    f.policy.begin(2000,"ffffffffffffffffffffffffffffffff",f.host.callbacks());
    assert(!f.raw(authenticate(std::string("FQ1|ARM|")+nonce+"|1|1|3"),2001));
  }
  {
    Fixture f;assert(!f.raw("FQ1|HELLO",kArmWindowMs));
    assert(f.send(std::string("FQ1|ARM|")+nonce+"|1|1|3",kArmWindowMs)[4]=="4");
    f.policy.tick(UINT32_MAX);
    assert(!f.raw("FQ1|HELLO",0));
    assert(f.send(std::string("FQ1|ARM|")+nonce+"|1|1|3",0)[4]=="4"&&!f.policy.consumed());
    Fixture wrap(UINT32_MAX-100);wrap.arm(1,20,3,50);
    assert(wrap.policy.armed(1049));wrap.policy.tick(1050);assert(!wrap.policy.armed(1050)&&wrap.host.stops==1);
  }
  {
    Fixture f;f.arm(900,500);
    std::memset(f.host.shown.label,'L',64);f.host.shown.label[64]=0;
    std::memset(f.host.shown.detail,'D',32);f.host.shown.detail[32]=0;
    f.host.shown.context=UINT32_MAX;f.host.shown.view=UINT64_MAX;f.host.shown.presented=UINT32_MAX;
    f.host.shown.screen=UINT16_MAX;f.host.shown.index=UINT16_MAX;f.host.shown.count=UINT16_MAX;
    f.host.shown.frameCrc=UINT32_MAX;f.host.shown.error=UINT16_MAX;f.host.shown.busy=true;
    const auto full=f.send(f.command(1));assert(full.size()==20&&strlen(f.reply)<512&&full[18].size()==64);
    char tooSmall[511];assert(!f.policy.handle("FQ1|HELLO",9,1,tooSmall,sizeof(tooSmall)));
  }
  {
    LineReader reader;
    for(unsigned i=0;i<512;++i)assert(reader.feed('x')==LineReader::Result::None);
    assert(reader.feed('\n')==LineReader::Result::Rejected);
    for(char c:std::string("FQ1|HELLO"))assert(reader.feed(uint8_t(c))==LineReader::Result::None);
    assert(reader.feed('\n')==LineReader::Result::Ready&&reader.size()==9);
    reader.clear();assert(reader.feed(0)==LineReader::Result::None&&reader.feed('\n')==LineReader::Result::Rejected);
  }
  std::puts("PASS authenticated local QA policy: off, nonce/MAC, one arm, limits, replay, presentation, wrap and bounded parser");
}
