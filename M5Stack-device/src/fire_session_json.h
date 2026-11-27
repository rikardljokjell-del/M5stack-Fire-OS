#pragma once
#include "fire_json_guard.h"
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <initializer_list>

// Private session-envelope view. No DOM, recursion, token array or allocator.
// Only selected small strings are decoded; all other values remain spans of
// the already owned message. This does not change the Lua/Runtime AI parser.
namespace fire_session_json {
struct Span {
  const char* data=nullptr;
  uint16_t size=0;
  Span() = default;
  Span(const char* p,size_t n):data(p),size(static_cast<uint16_t>(n)) {}
  bool present() const {return data!=nullptr;}
  bool is(char c) const {return size && data[0]==c;}
};

class Document {
 public:
  Document(const char* data,size_t size):data_(data),size_(size) {}
  bool valid() const {
    if(!fireJsonSafe(data_,size_,8192,12,1024)) return false;
    size_t at=0;space(at);
    if(at==size_ || data_[at]!='{' || !skip(at)) return false;
    space(at);return at==size_;
  }
  Span root() const {size_t at=0;space(at);return Span(data_+at,size_-at);}
  // Call only after valid(). cJSON's case-sensitive lookup returns the FIRST
  // matching decoded key, including when later duplicates have another type.
  Span field(Span object,const char* key) const {
    if(!object.is('{')) return Span();
    size_t at=static_cast<size_t>(object.data-data_)+1;
    space(at);
    while(at<size_ && data_[at]!='}') {
      const size_t keyAt=at;
      if(!string(at,true)) return Span();
      const Span name(data_+keyAt,at-keyAt);
      space(at);if(at==size_ || data_[at++]!=':') return Span();
      space(at);const size_t start=at;
      if(!skip(at)) return Span();
      if(equal(name,key)) return Span(data_+start,at-start);
      space(at);if(at==size_ || data_[at++]!=',') break;
      space(at);
    }
    return Span();
  }
  static bool selected(Span value) {
    if(!value.is('"')) return true; // null/wrong type retains existing empty-text semantics
    size_t count=0;
    return decode(value,[&](char c) {return c && ++count<=128;});
  }
  // Decode into a fresh staging owner, never an acknowledged client field.
  // Success is explicit: OOM must not look like a valid empty/null value.
  template<class Text> static bool text(Span value,Text& result) {
    if(!value.is('"')) return true;
    size_t count=0;
    if(!decode(value,[&](char c) {return c && ++count<=128;})) return false;
    if(!result.reserve(count)) return false;
    return decode(value,[&](char c) {result+=c;return true;}) && result.length()==count;
  }
  static bool equal(Span value,const char* expected) {
    if(!value.is('"')) return false;
    size_t at=0;
    return decode(value,[&](char c) {return expected[at] && c==expected[at++];}) && !expected[at];
  }
 private:
  const char* data_;size_t size_;
  void space(size_t& at) const {
    while(at<size_ && (data_[at]==' ' || data_[at]=='\t' || data_[at]=='\n' || data_[at]=='\r')) ++at;
  }
  static bool hex(const char* data,size_t size,size_t& at,uint32_t& cp) {
    cp=0;if(size-at<4) return false;
    for(unsigned i=0;i<4;++i) {
      const unsigned char c=data[at++];
      const unsigned n=c>='0' && c<='9'?c-'0':c>='a' && c<='f'?c-'a'+10:c>='A' && c<='F'?c-'A'+10:16;
      if(n==16) return false;
      cp=(cp<<4)|n;
    }
    return true;
  }
  // One raw UTF-8 byte or one escaped Unicode code point. Raw UTF-8 was
  // validated by fireJsonSafe; surrogate pairs are checked here, not copied.
  static bool unit(const char* data,size_t size,size_t& at,uint32_t& cp,bool& unicode) {
    if(at==size) return false;
    cp=static_cast<unsigned char>(data[at++]);unicode=false;
    if(cp<32 || cp=='"') return false;
    if(cp!='\\') return true;
    if(at==size) return false;
    const char c=data[at++];
    if(c=='"' || c=='\\' || c=='/') {cp=static_cast<unsigned char>(c);return true;}
    if(c=='b' || c=='f' || c=='n' || c=='r' || c=='t') {
      cp=c=='b'?'\b':c=='f'?'\f':c=='n'?'\n':c=='r'?'\r':'\t';return true;
    }
    if(c!='u' || !hex(data,size,at,cp)) return false;
    unicode=true;
    if(cp>=0xd800 && cp<=0xdbff) {
      if(size-at<2 || data[at]!='\\' || data[at+1]!='u') return false;
      at+=2;uint32_t low;
      if(!hex(data,size,at,low) || low<0xdc00 || low>0xdfff) return false;
      cp=0x10000+((cp-0xd800)<<10)+(low-0xdc00);
    } else if(cp>=0xdc00 && cp<=0xdfff) return false;
    return true;
  }
  template<class Sink> static bool decode(Span value,Sink sink) {
    if(!value.is('"') || value.size<2 || value.data[value.size-1]!='"') return false;
    const size_t end=size_t(value.size)-1;
    size_t at=1;
    while(at<end) {
      uint32_t cp;bool unicode;
      if(!unit(value.data,end,at,cp,unicode)) return false;
      if(!unicode || cp<0x80) {if(!sink(static_cast<char>(cp))) return false;}
      else if(cp<0x800) {
        if(!sink(char(0xc0|(cp>>6))) || !sink(char(0x80|(cp&63)))) return false;
      } else if(cp<0x10000) {
        if(!sink(char(0xe0|(cp>>12))) || !sink(char(0x80|((cp>>6)&63))) || !sink(char(0x80|(cp&63)))) return false;
      } else if(!sink(char(0xf0|(cp>>18))) || !sink(char(0x80|((cp>>12)&63))) ||
                !sink(char(0x80|((cp>>6)&63))) || !sink(char(0x80|(cp&63)))) return false;
    }
    return at==end;
  }
  bool string(size_t& at,bool key=false) const {
    if(at==size_ || data_[at++]!='"') return false;
    while(at<size_) {
      if(data_[at]=='"') {++at;return true;}
      uint32_t cp;bool unicode;
      if(!unit(data_,size_,at,cp,unicode)) return false;
      if(key && cp==0) return false; // Never let a NUL key alias a cJSON C-string prefix.
    }
    return false;
  }
  bool atom(size_t& at) const {
    for(const char* word:{"true","false","null"}) {
      const size_t length=strlen(word);
      if(size_-at>=length && !memcmp(data_+at,word,length)) {at+=length;return true;}
    }
    if(data_[at]=='-' && ++at==size_) return false;
    if(data_[at]=='0') ++at;
    else {
      if(data_[at]<'1' || data_[at]>'9') return false;
      do {++at;} while(at<size_ && data_[at]>='0' && data_[at]<='9');
    }
    if(at<size_ && data_[at]=='.') {
      const size_t start=++at;
      while(at<size_ && data_[at]>='0' && data_[at]<='9') ++at;
      if(at==start) return false;
    }
    if(at<size_ && (data_[at]=='e' || data_[at]=='E')) {
      ++at;if(at<size_ && (data_[at]=='+' || data_[at]=='-')) ++at;
      const size_t start=at;
      while(at<size_ && data_[at]>='0' && data_[at]<='9') ++at;
      if(at==start) return false;
    }
    return true;
  }
  bool skip(size_t& at) const {
    enum : uint8_t {ObjectFirst,ObjectKey,ObjectColon,ObjectComma,ArrayFirst,ArrayValue,ArrayComma};
    uint8_t stack[12];unsigned depth=0;bool value=true;
    for(;;) {
      space(at);if(at==size_) return false;
      const char c=data_[at];
      if(value) {
        value=false;
        if(c=='{' || c=='[') {
          if(depth==12) return false;
          stack[depth++]=c=='{'?ObjectFirst:ArrayFirst;++at;continue;
        }
        if(c=='"' ? !string(at) : !atom(at)) return false;
        if(!depth) return true;
        continue;
      }
      uint8_t& state=stack[depth-1];
      if(state==ObjectFirst || state==ObjectKey) {
        if(state==ObjectFirst && c=='}') {++at;if(!--depth) return true;continue;}
        if(!string(at,true)) return false;
        state=ObjectColon;
      } else if(state==ObjectColon) {
        if(c!=':') return false;
        ++at;state=ObjectComma;value=true;
      } else if(state==ArrayFirst || state==ArrayValue) {
        if(state==ArrayFirst && c==']') {++at;if(!--depth) return true;continue;}
        state=ArrayComma;value=true;
      } else {
        if(c==',' ) {++at;state=state==ObjectComma?ObjectKey:ArrayValue;}
        else if(c==(state==ObjectComma?'}':']')) {++at;if(!--depth) return true;}
        else return false;
      }
    }
  }
};
} // namespace fire_session_json
