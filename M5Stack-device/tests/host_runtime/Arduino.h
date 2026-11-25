#pragma once
// Host-only adapters for testing the production Lua VM. No hardware simulation
// result from these adapters establishes physical support or timing.
#include <stdint.h>
#include <stddef.h>
#include <string>
#include <algorithm>
#include <string.h>
using std::min;
using std::max;
template<class A,class B,class C> A constrain(A value,B low,C high) {
  return value<low?A(low):value>high?A(high):value;
}
class String {
  std::string value_;
 public:
  String()=default;
  String(const char* value):value_(value?value:"") {}
  String(std::string value):value_(value) {}
  const char* c_str() const {return value_.c_str();}
  size_t length() const {return value_.size();}
  String substring(unsigned from,unsigned to) const {return value_.substr(from,to-from);}
  String& operator+=(const char* value) {value_+=value;return *this;}
  friend String operator+(const String& a,const char* b) {return a.value_+(b?b:"");}
};
extern int64_t fireTestClockUs;
inline uint32_t millis() {return uint32_t(fireTestClockUs/1000);}
inline void delay(uint32_t milliseconds) {fireTestClockUs+=int64_t(milliseconds)*1000;}
inline size_t strlcpy(char* target,const char* source,size_t size) {
  const size_t length=strlen(source);if(size) {const size_t copied=std::min(length,size-1);memcpy(target,source,copied);target[copied]=0;}return length;
}
