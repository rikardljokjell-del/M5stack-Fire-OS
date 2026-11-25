#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <algorithm>
namespace fire_data_journal {
inline uint32_t little32(const uint8_t* bytes) {return uint32_t(bytes[0])|(uint32_t(bytes[1])<<8)|(uint32_t(bytes[2])<<16)|(uint32_t(bytes[3])<<24);}
inline void put32(uint8_t* bytes,uint32_t value) {for (uint8_t i=0;i<4;++i) bytes[i]=static_cast<uint8_t>(value>>(i*8));}
inline bool pcm16Wav(const uint8_t* header,size_t bytes,uint32_t size,bool partial=false) {
  if (!header || bytes<44 || size<46 || (size&1u) || memcmp(header,"RIFF",4) || memcmp(header+8,"WAVEfmt ",8) ||
      little32(header+16)!=16 || header[20]!=1 || header[21] || header[22]!=1 || header[23] ||
      header[32]!=2 || header[33] || header[34]!=16 || header[35] || memcmp(header+36,"data",4)) return false;
  const uint32_t rate=little32(header+24),data=little32(header+40),riff=little32(header+4);
  if ((rate!=8000 && rate!=16000) || little32(header+28)!=rate*2 || data>UINT32_MAX-36 || riff!=data+36 || (data&1u)) return false;
  return partial?data>=size-44:data==size-44;
}
// Shared by the actual SD store and fault-injecting native filesystem tests.
// fwrite success is not persistence proof: close, reopen, exact length/bytes.
template<class FS,class Path>
bool writeChecked(FS& fs,const Path& path,const uint8_t* bytes,size_t length,bool append) {
  auto file=fs.open(path.c_str(),append?"a":"w");
  if (!file || !file.setBufferSize(512)) {file.close();return false;}
  const uint32_t offset=append?file.size():0;
  const bool written=!length || file.write(bytes,length)==length;
  file.close();if (!written) return false;
  file=fs.open(path.c_str(),"r");
  if (!file || file.size()!=offset+length || !file.seek(offset)) {file.close();return false;}
  uint8_t buffer[128];size_t at=0;
  while (at<length) {
    const size_t amount=std::min<size_t>(sizeof(buffer),length-at);
    if (file.read(buffer,amount)!=amount || memcmp(buffer,bytes+at,amount)) {file.close();return false;}
    at+=amount;
  }
  file.close();return true;
}
template<class FS,class Path,class Resize>
bool recoverPart(FS& fs,const Path& path,uint32_t committed,bool sealed,Resize resize) {
  auto file=fs.open(path.c_str(),"r");
  if (!file && !committed) return true;
  if (!file || file.size()<committed) {file.close();return false;}
  const uint32_t actual=file.size();file.close();
  if (actual==committed) return true;
  return !sealed && resize(path,committed);
}
} // namespace fire_data_journal
