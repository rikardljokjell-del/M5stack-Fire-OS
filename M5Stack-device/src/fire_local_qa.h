#pragma once
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

// Authenticated UART policy only. No transport, token, filesystem, grants or
// backend client lives here. The OS supplies crypto and actual UI callbacks.
namespace fire_local_qa {
static const size_t kMaxWireBytes=512;
static const uint32_t kArmWindowMs=120000, kMaxTtlSeconds=900, kMaxCommands=500;
static const char kDomain[]="FIRE-LOCAL-QA-v1\n";
enum class Op:uint8_t {State,Click,Hold,Stop};
enum class Code:uint8_t {Ok=0,Malformed=1,Auth=2,Off=3,Expired=4,Used=5,Replay=6,
  Limit=7,Permission=8,Stale=9,Unavailable=10,Blocked=11,Internal=12};
struct Snapshot {
  uint16_t screen=0,index=0,count=0,error=0;
  uint32_t context=0,presented=0,frameCrc=0;
  uint64_t view=0;
  bool busy=false;
  char identity[65]={}; // Lowercase SHA256 of the presented confirmation identity.
  char label[65]={},detail[33]={}; // Already sanitized by the trusted OS.
};
struct Command {
  Op op=Op::State;
  uint8_t button=0;
  uint32_t seq=0,context=0;
  uint64_t view=0;
  char identity[65]={};
};
struct Callbacks {
  void* context=nullptr;
  bool (*verify)(void*,const char*,size_t,const char*)=nullptr;
  bool (*sign)(void*,const char*,size_t,char*)=nullptr;
  bool (*snapshot)(void*,Snapshot&)=nullptr;
  Code (*action)(void*,const Command&,Snapshot&)=nullptr;
  void (*stop)(void*)=nullptr;
};
inline bool equal(const char* a,const char* b,size_t n) {
  unsigned diff=0;for(size_t i=0;i<n;++i)diff|=unsigned(uint8_t(a[i])^uint8_t(b[i]));return diff==0;
}
inline bool hex(const char* value,size_t n) {
  if(!value)return false;
  for(size_t i=0;i<n;++i)if(!((value[i]>='0'&&value[i]<='9')||(value[i]>='a'&&value[i]<='f')))return false;
  return value[n]==0;
}
inline bool decimal(const char* text,uint32_t& value) {
  if(!text || !*text || (text[0]=='0'&&text[1]))return false;
  value=0;for(size_t i=0;text[i];++i) {
    if(text[i]<'0'||text[i]>'9')return false;
    const uint32_t digit=uint32_t(text[i]-'0');
    if(value>(UINT32_MAX-digit)/10)return false;
    value=value*10+digit;
  }return true;
}
inline bool hex64(const char* text,uint64_t& value) {
  if(!hex(text,16))return false;
  value=0;
  for(unsigned i=0;i<16;++i)value=(value<<4)|uint64_t(text[i]<='9'?text[i]-'0':text[i]-'a'+10);
  return true;
}
inline bool zero(const char* value,size_t n) {
  for(size_t i=0;i<n;++i)if(value[i]!='0')return false;
  return true;
}
inline bool textHex(const char* text,size_t capacity,char* out,size_t outCapacity) {
  const char* digits="0123456789abcdef";size_t n=0;
  while(n<capacity&&text[n])++n;
  if(n==capacity||n*2+1>outCapacity)return false;
  for(size_t i=0;i<n;++i){out[i*2]=digits[uint8_t(text[i])>>4];out[i*2+1]=digits[uint8_t(text[i])&15];}
  out[n*2]=0;return true;
}

// The owner reads a bounded byte budget and handles at most one Ready per UI
// turn. An invalid/oversized line is discarded through LF, never truncated.
class LineReader {
 public:
  enum class Result:uint8_t {None,Ready,Rejected};
  Result feed(uint8_t byte) {
    if(byte=='\n') {
      if(dropping_){clear();return Result::Rejected;}
      line_[used_]=0;return used_?Result::Ready:Result::Rejected;
    }
    if(dropping_)return Result::None;
    if(byte<32||byte>126||used_>=kMaxWireBytes-1){dropping_=true;used_=0;return Result::None;}
    line_[used_++]=char(byte);return Result::None;
  }
  const char* data() const{return line_;}
  size_t size() const{return used_;}
  void clear(){used_=0;dropping_=false;line_[0]=0;}
 private:
  char line_[kMaxWireBytes]={};size_t used_=0;bool dropping_=false;
};

class Policy {
 public:
  void begin(uint32_t now,const char* nonce,const Callbacks& callbacks) {
    *this=Policy();bootAt_=now;callbacks_=callbacks;
    if(hex(nonce,32)){memcpy(nonce_,nonce,33);configured_=callbacks.verify&&callbacks.sign&&callbacks.snapshot;}
  }
  bool armed(uint32_t now){expire(now);return armed_;}
  bool consumed() const{return used_;}
  uint32_t remaining() const{return limit_>lastSeq_?limit_-lastSeq_:0;}
  void tick(uint32_t now){expire(now);}
  // Sign/verify callbacks receive kDomain + this canonical body, WITHOUT |MAC.
  bool handle(const char* line,size_t size,uint32_t now,char* out,size_t capacity) {
    if(out&&capacity)out[0]=0;
    expire(now);
    if(!configured_||!line||!out||capacity<kMaxWireBytes||!size||size>=kMaxWireBytes)return false;
    for(size_t i=0;i<size;++i)if(uint8_t(line[i])<32||uint8_t(line[i])>126)return false;
    if(size==9&&!memcmp(line,"FQ1|HELLO",9))return challenge(now,out,capacity);
    char fields[kMaxWireBytes];memcpy(fields,line,size);fields[size]=0;
    char* parts[11]={};size_t count=0;parts[count++]=fields;
    for(size_t i=0;i<size;++i)if(fields[i]=='|') {
      fields[i]=0;if(count>=11)return false;parts[count++]=fields+i+1;
    }
    if(count<3||strcmp(parts[0],"FQ1")||!hex(parts[2],32)||!equal(parts[2],nonce_,32))return false;
    if(!strcmp(parts[1],"ARM"))return arm(line,size,parts,count,now,out,capacity);
    if(strcmp(parts[1],"DO")||count!=10||!hex(parts[9],64))return false;
    uint32_t seq=0,button=0,context=0;uint64_t view=0;
    if(!decimal(parts[3],seq)||!seq||!decimal(parts[5],button)||button>2||
       !decimal(parts[6],context)||!hex64(parts[7],view)||!hex(parts[8],64))return false;
    if(!verify(line,size-65,parts[9]))return reply(Code::Auth,seq,false,Snapshot(),out,capacity);
    if(expired_)return reply(Code::Expired,seq,false,Snapshot(),out,capacity);
    if(lastSeq_&&seq==lastSeq_&&equal(parts[9],lastMac_,64))
      return reply(lastCode_,seq,true,lastSnapshot_,out,capacity);
    if(!armed_)return reply(Code::Off,seq,false,Snapshot(),out,capacity);
    if(seq!=lastSeq_+1)return reply(Code::Replay,seq,false,Snapshot(),out,capacity);
    if(lastSeq_>=limit_)return reply(Code::Limit,seq,false,Snapshot(),out,capacity);
    Command command;command.seq=seq;command.button=uint8_t(button);command.context=context;command.view=view;
    memcpy(command.identity,parts[8],65);
    if(!strcmp(parts[4],"STATE"))command.op=Op::State;
    else if(!strcmp(parts[4],"CLICK"))command.op=Op::Click;
    else if(!strcmp(parts[4],"HOLD"))command.op=Op::Hold;
    else if(!strcmp(parts[4],"STOP"))command.op=Op::Stop;
    else return reply(Code::Malformed,seq,false,Snapshot(),out,capacity);
    if((command.op==Op::State||command.op==Op::Stop)&&(button||context||view||!zero(parts[8],64)))
      return reply(Code::Malformed,seq,false,Snapshot(),out,capacity);
    // Authenticated well-formed commands consume their sequence EVEN on a
    // stale/blocked action. Replaying that exact command cannot execute later.
    lastSeq_=seq;memcpy(lastMac_,parts[9],65);Snapshot shown;
    Code code=callbacks_.snapshot(callbacks_.context,shown)?Code::Ok:Code::Unavailable;
    if(command.op==Op::Stop) {
      armed_=false;if(callbacks_.stop)callbacks_.stop(callbacks_.context);code=Code::Ok;
    } else if(command.op!=Op::State) {
      if(!(mask_&2))code=Code::Permission;
      else if(code==Code::Ok&&(!context||context!=shown.context||view!=shown.view||!equal(command.identity,shown.identity,64)))code=Code::Stale;
      else if(code==Code::Ok)code=callbacks_.action?callbacks_.action(callbacks_.context,command,shown):Code::Unavailable;
    }
    lastCode_=code;lastSnapshot_=shown;return reply(code,seq,false,shown,out,capacity);
  }
 private:
  Callbacks callbacks_;
  bool configured_=false,used_=false,armed_=false,expired_=false,armWindowClosed_=false;
  uint32_t bootAt_=0,armAt_=0,ttlMs_=0,limit_=0,mask_=0,lastSeq_=0;
  char nonce_[33]={},armMac_[65]={},lastMac_[65]={};
  Snapshot armSnapshot_,lastSnapshot_;Code lastCode_=Code::Off;
  bool verify(const char* body,size_t bytes,const char* mac) {
    char message[kMaxWireBytes+sizeof(kDomain)];const size_t prefix=sizeof(kDomain)-1;
    if(bytes+prefix>=sizeof(message))return false;
    memcpy(message,kDomain,prefix);memcpy(message+prefix,body,bytes);
    return callbacks_.verify(callbacks_.context,message,prefix+bytes,mac);
  }
  bool sign(char* out,size_t capacity) {
    const size_t bytes=strlen(out),prefix=sizeof(kDomain)-1;char message[kMaxWireBytes+sizeof(kDomain)],mac[65]={};
    if(bytes+67>capacity||bytes+prefix>=sizeof(message))return false;
    memcpy(message,kDomain,prefix);memcpy(message+prefix,out,bytes);
    if(!callbacks_.sign(callbacks_.context,message,prefix+bytes,mac)||!hex(mac,64))return false;
    out[bytes]='|';memcpy(out+bytes+1,mac,64);out[bytes+65]='\n';out[bytes+66]=0;return true;
  }
  void expire(uint32_t now) {
    if(uint32_t(now-bootAt_)>=kArmWindowMs)armWindowClosed_=true;
    if(armed_&&uint32_t(now-armAt_)>=ttlMs_){armed_=false;expired_=true;if(callbacks_.stop)callbacks_.stop(callbacks_.context);}
  }
  bool challenge(uint32_t now,char* out,size_t capacity) {
    if(used_||armWindowClosed_)return false;
    const int n=snprintf(out,capacity,"FQ1|C|%s|%lu",nonce_,(unsigned long)(kArmWindowMs-uint32_t(now-bootAt_)));
    return n>0&&size_t(n)<capacity&&sign(out,capacity);
  }
  bool arm(const char* line,size_t size,char** p,size_t count,uint32_t now,char* out,size_t capacity) {
    uint32_t ttl=0,limit=0,mask=0;
    if(count!=7||!decimal(p[3],ttl)||!ttl||ttl>kMaxTtlSeconds||!decimal(p[4],limit)||!limit||limit>kMaxCommands||
       !decimal(p[5],mask)||(mask!=1&&mask!=3)||!hex(p[6],64))return false;
    if(!verify(line,size-65,p[6]))return reply(Code::Auth,0,false,Snapshot(),out,capacity);
    if(used_) {
      if(armed_&&equal(p[6],armMac_,64))return reply(Code::Ok,0,true,armSnapshot_,out,capacity);
      return reply(Code::Used,0,false,Snapshot(),out,capacity);
    }
    if(armWindowClosed_)return reply(Code::Expired,0,false,Snapshot(),out,capacity);
    used_=true;armed_=true;armAt_=now;ttlMs_=ttl*1000;limit_=limit;mask_=mask;memcpy(armMac_,p[6],65);
    callbacks_.snapshot(callbacks_.context,armSnapshot_);
    return reply(Code::Ok,0,false,armSnapshot_,out,capacity);
  }
  bool reply(Code code,uint32_t seq,bool duplicate,const Snapshot& state,char* out,size_t capacity) {
    char label[129],detail[65];
    if(!textHex(state.label,sizeof(state.label),label,sizeof(label))||!textHex(state.detail,sizeof(state.detail),detail,sizeof(detail)))return false;
    const char* identity=hex(state.identity,64)?state.identity:"0000000000000000000000000000000000000000000000000000000000000000";
    const int n=snprintf(out,capacity,"FQ1|R|%s|%lu|%u|%u|%lu|%u|%u|%u|%lu|%016llx|%s|%lu|%u|%u|%08lx|%s|%s",
      nonce_,(unsigned long)seq,unsigned(code),duplicate?1u:0u,(unsigned long)remaining(),unsigned(state.screen),unsigned(state.index),unsigned(state.count),
      (unsigned long)state.context,(unsigned long long)state.view,identity,(unsigned long)state.presented,state.busy?1u:0u,unsigned(state.error),
      (unsigned long)state.frameCrc,label,detail);
    return n>0&&size_t(n)<capacity&&sign(out,capacity);
  }
};
} // namespace fire_local_qa
