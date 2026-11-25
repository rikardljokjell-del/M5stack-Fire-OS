#pragma once
#include "fire_json_guard.h"
#include "fire_runtime_ai_contract.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <initializer_list>

// Bounded streaming JSON, only for the optional AI adapter. No DOM, allocation,
// loader or public JSON API. Callers supply a NUL-terminated Lua/String span.
namespace fire_runtime_ai_json {
struct Ignore {
  bool object() {return true;} bool array() {return true;}
  bool key(const char*,size_t) {return true;} bool index(unsigned) {return true;}
  bool pair() {return true;} bool end() {return true;}
  bool string(const char*,size_t) {return true;}
  bool number(double) {return true;} bool boolean(bool) {return true;} bool null() {return true;}
};
template<class Sink> class Reader {
 public:
  Reader(const char* text,size_t length,Sink& sink,unsigned depth):text_(text),length_(length),sink_(sink),depth_(depth) {}
  bool object() {
    if(length_>UINT16_MAX || !fireJsonSafe(text_,length_,length_,depth_,2048)) return false;
    space();if(at_==length_ || text_[at_]!='{') return false;
    if(!value(1)) return false;space();return at_==length_;
  }
 private:
  const char* text_;size_t length_,at_=0;Sink& sink_;unsigned depth_;
  char scratch_[FireRuntimeAiContract::kJsonStringBytes+1],compare_[FireRuntimeAiContract::kJsonStringBytes+1];
  void space() {while(at_<length_ && (text_[at_]==' ' || text_[at_]=='\n' || text_[at_]=='\r' || text_[at_]=='\t')) ++at_;}
  bool take(char c) {space();if(at_>=length_ || text_[at_]!=c) return false;++at_;return true;}
  bool hex(unsigned& cp) {
    cp=0;if(length_-at_<4) return false;
    for(unsigned i=0;i<4;++i) {const char c=text_[at_++];unsigned n;
      if(c>='0' && c<='9') n=c-'0';else if(c>='a' && c<='f') n=c-'a'+10;
      else if(c>='A' && c<='F') n=c-'A'+10;else return false;cp=cp*16+n;}
    return true;
  }
  bool string(char* out,size_t& used) {
    used=0;if(!take('"')) return false;
    const auto append=[&](char c) {if(used>=FireRuntimeAiContract::kJsonStringBytes) return false;out[used++]=c;return true;};
    while(at_<length_) {
      unsigned c=static_cast<unsigned char>(text_[at_++]);
      if(c=='"') {out[used]=0;return true;}
      if(c<32) return false;
      if(c!='\\') {if(!append(char(c))) return false;continue;}
      if(at_==length_) return false;c=static_cast<unsigned char>(text_[at_++]);
      if(c=='"' || c=='\\' || c=='/') {if(!append(char(c))) return false;continue;}
      if(c=='b' || c=='f' || c=='n' || c=='r' || c=='t') {
        const char decoded=c=='b'?'\b':c=='f'?'\f':c=='n'?'\n':c=='r'?'\r':'\t';
        if(!append(decoded)) return false;continue;
      }
      if(c!='u' || !hex(c)) return false;
      if(c>=0xd800 && c<=0xdbff) {
        if(length_-at_<2 || text_[at_]!='\\' || text_[at_+1]!='u') return false;at_+=2;
        unsigned low;if(!hex(low) || low<0xdc00 || low>0xdfff) return false;c=0x10000+(c-0xd800)*1024+low-0xdc00;
      } else if(c>=0xdc00 && c<=0xdfff) return false;
      if(c<0x80) {if(!append(char(c))) return false;}
      else if(c<0x800) {if(!append(char(0xc0|(c>>6))) || !append(char(0x80|(c&63)))) return false;}
      else if(c<0x10000) {if(!append(char(0xe0|(c>>12))) || !append(char(0x80|((c>>6)&63))) || !append(char(0x80|(c&63)))) return false;}
      else if(!append(char(0xf0|(c>>18))) || !append(char(0x80|((c>>12)&63))) || !append(char(0x80|((c>>6)&63))) || !append(char(0x80|(c&63)))) return false;
    }return false;
  }
  bool value(unsigned depth) {
    if(depth>depth_) return false;space();if(at_==length_) return false;
    const char c=text_[at_];
    if(c=='{') {
      ++at_;if(!sink_.object()) return false;space();if(at_<length_ && text_[at_]=='}') {++at_;return sink_.end();}
      uint16_t keys[FireRuntimeAiContract::kJsonObjectKeys];size_t count=0;
      do {
        if(count==FireRuntimeAiContract::kJsonObjectKeys) return false;space();const size_t keyAt=at_;size_t size;
        if(!string(scratch_,size)) return false;
        const size_t after=at_;
        for(size_t i=0;i<count;++i) {at_=keys[i];size_t previous;if(!string(compare_,previous)) return false;
          if(previous==size && !memcmp(scratch_,compare_,size)) return false;}
        at_=after;keys[count++]=static_cast<uint16_t>(keyAt);
        if(!sink_.key(scratch_,size) || !take(':') || !value(depth+1) || !sink_.pair()) return false;
        space();if(at_<length_ && text_[at_]=='}') {++at_;return sink_.end();}
      } while(take(','));return false;
    }
    if(c=='[') {
      ++at_;if(!sink_.array()) return false;space();if(at_<length_ && text_[at_]==']') {++at_;return sink_.end();}
      unsigned count=0;
      do {if(count==FireRuntimeAiContract::kJsonArrayItems || !sink_.index(++count) || !value(depth+1) || !sink_.pair()) return false;
        space();if(at_<length_ && text_[at_]==']') {++at_;return sink_.end();}
      } while(take(','));return false;
    }
    if(c=='"') {size_t size;return string(scratch_,size) && sink_.string(scratch_,size);}
    for(const char* word:{"true","false","null"}) {
      const size_t size=strlen(word);if(size<=length_-at_ && !memcmp(text_+at_,word,size)) {
        at_+=size;return word[0]=='n'?sink_.null():sink_.boolean(word[0]=='t');}
    }
    const size_t start=at_;if(text_[at_]=='-') {if(++at_==length_) return false;}
    if(text_[at_]=='0') ++at_;
    else {if(text_[at_]<'1' || text_[at_]>'9') return false;while(at_<length_ && text_[at_]>='0' && text_[at_]<='9') ++at_;}
    if(at_<length_ && text_[at_]=='.') {const size_t digits=++at_;while(at_<length_ && text_[at_]>='0' && text_[at_]<='9') ++at_;if(at_==digits) return false;}
    if(at_<length_ && (text_[at_]=='e' || text_[at_]=='E')) {++at_;if(at_<length_ && (text_[at_]=='+' || text_[at_]=='-')) ++at_;
      const size_t digits=at_;while(at_<length_ && text_[at_]>='0' && text_[at_]<='9') ++at_;if(at_==digits) return false;}
    char* end=nullptr;const double number=strtod(text_+start,&end);
    return end==text_+at_ && isfinite(number) && sink_.number(number);
  }
};
inline bool validObject(const char* text,size_t length,size_t maximum,unsigned depth=FireRuntimeAiContract::kJsonDepth) {
  if(!length || length>maximum) return false;Ignore sink;return Reader<Ignore>(text,length,sink,depth).object();
}
} // namespace fire_runtime_ai_json
