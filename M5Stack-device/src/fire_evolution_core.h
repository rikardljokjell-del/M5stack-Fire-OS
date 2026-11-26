#pragma once
#include "fire_evolution_contract.h"
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <algorithm>

namespace fire_evolution {
inline void increment(uint32_t& value) {if (value!=UINT32_MAX) ++value;}
struct Callback {
  uint32_t count=0,maxUs=0;uint64_t totalUs=0;
  void add(uint32_t us) {
    increment(count);maxUs=std::max(maxUs,us);
    totalUs=UINT64_MAX-totalUs<us?UINT64_MAX:totalUs+us;
  }
};
struct Error {char operation[16]={},code[32]={};uint32_t count=0;};
struct Aggregate {
  Callback callbacks[3];uint32_t buttons[3]={},heapMin=UINT32_MAX,luaPeak=0;
  Error errors[8];uint8_t errorCount=0;
  void sample(uint32_t heap,uint32_t lua) {heapMin=std::min(heapMin,heap);luaPeak=std::max(luaPeak,lua);}
  bool empty() const {return !callbacks[0].count && !callbacks[1].count && !callbacks[2].count && !buttons[0] && !buttons[1] && !buttons[2] && !errorCount;}
  void error(const char* op,const char* code) {
    if (!op || !code) return;
    if (strlen(op)>=sizeof(Error::operation) || strlen(code)>=sizeof(Error::code)) {op="other";code="other";}
    for (const char* s:{op,code}) for (size_t i=0;s[i];++i)
      if (s[i]<' ' || static_cast<unsigned char>(s[i])>=127) {op="other";code="other";break;}
    for (uint8_t i=0;i<errorCount;++i)
      if (!strcmp(errors[i].operation,op) && !strcmp(errors[i].code,code)) {increment(errors[i].count);return;}
    // The eighth bin is a visible overflow category, never an unbounded label.
    if (errorCount>=7) {op="other";code="other";}
    uint8_t index=errorCount<8?errorCount++:7;
    auto& e=errors[index];
    const size_t a=std::min(strlen(op),sizeof(e.operation)-1),b=std::min(strlen(code),sizeof(e.code)-1);
    memcpy(e.operation,op,a);e.operation[a]=0;memcpy(e.code,code,b);e.code[b]=0;increment(e.count);
  }
};
struct Outbox {
  uint16_t bytes[FireEvolutionContract::kOutboxBatches]={};uint32_t used=0;uint8_t count=0;
  bool blocked[FireEvolutionContract::kOutboxBatches]={};
  int freeSlot(size_t length) const {
    if (!length || length>FireEvolutionContract::kOutboxBytes-used || count>=FireEvolutionContract::kOutboxBatches) return -1;
    for (uint8_t i=0;i<FireEvolutionContract::kOutboxBatches;++i) if (!bytes[i]) return i;
    return -1;
  }
  bool add(uint8_t slot,size_t length) {
    if (slot>=FireEvolutionContract::kOutboxBatches || bytes[slot] || length>UINT16_MAX || freeSlot(length)<0) return false;
    bytes[slot]=static_cast<uint16_t>(length);used+=length;++count;return true;
  }
  void remove(uint8_t slot) {
    if (slot>=FireEvolutionContract::kOutboxBatches || !bytes[slot]) return;
    used-=bytes[slot];bytes[slot]=0;blocked[slot]=false;--count;
  }
};
inline bool acceptedAck(const char* expectedRequest,const char* expectedBatch,const char* request,const char* batch,const char* status) {
  return expectedRequest && *expectedRequest && expectedBatch && *expectedBatch && request && batch && status &&
    !strcmp(expectedRequest,request) && !strcmp(expectedBatch,batch) && (!strcmp(status,"accepted") || !strcmp(status,"duplicate"));
}
} // namespace fire_evolution
