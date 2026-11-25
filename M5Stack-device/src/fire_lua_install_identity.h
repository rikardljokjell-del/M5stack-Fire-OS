#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>

// One bounded, canonical sidecar in the existing current/previous app folder.
// No global registry, NVS dependency, secrets or app-selected path.
namespace fire_lua_install {
constexpr char kFilename[]=".fire-install.json";
constexpr size_t kMaxBytes=640;
inline bool id(const char* s,bool optional=false) {
  if(!s) return false;
  const size_t n=strlen(s);if(n>96 || (!n && !optional)) return false;
  for(size_t i=0;i<n;++i) if(!((s[i]>='a' && s[i]<='z') || (s[i]>='A' && s[i]<='Z') ||
      (s[i]>='0' && s[i]<='9') || s[i]=='-' || s[i]=='_')) return false;
  return true;
}
inline bool hash(const char* s) {
  if(!s || strlen(s)!=64) return false;
  for(size_t i=0;i<64;++i) if(!((s[i]>='0' && s[i]<='9') || (s[i]>='a' && s[i]<='f'))) return false;
  return true;
}
struct Identity {
  char app[97]={},package[97]={},project[97]={},archive[65]={},source[65]={};
  bool valid() const {return id(app) && id(package) && id(project,true) && hash(archive) && hash(source);}
  bool operator==(const Identity& b) const {
    return !strcmp(app,b.app) && !strcmp(package,b.package) && !strcmp(project,b.project) &&
      !strcmp(archive,b.archive) && !strcmp(source,b.source);
  }
  bool matches(const char* appId,const char* packageId,const char* archiveHash,const char* sourceHash) const {
    return appId && packageId && archiveHash && sourceHash && valid() && !strcmp(app,appId) && !strcmp(package,packageId) &&
      !strcmp(archive,archiveHash) && !strcmp(source,sourceHash);
  }
};
inline size_t encode(const Identity& v,char* out,size_t capacity) {
  if(!v.valid() || !out || !capacity) return 0;
  const int n=snprintf(out,capacity,"{\"schema\":1,\"app_id\":\"%s\",\"package_id\":\"%s\",\"project_id\":\"%s\",\"archive_sha256\":\"%s\",\"source_sha256\":\"%s\"}",
    v.app,v.package,v.project,v.archive,v.source);
  return n>0 && size_t(n)<capacity && size_t(n)<=kMaxBytes?size_t(n):0;
}
inline bool decode(const char* text,size_t bytes,Identity& v) {
  if(!text || !bytes || bytes>kMaxBytes || memchr(text,0,bytes)) return false;
  size_t at=0;
  const auto field=[&](const char* prefix,char* out,size_t capacity) {
    const size_t n=strlen(prefix);if(bytes-at<n || memcmp(text+at,prefix,n)) return false;
    at+=n;const size_t begin=at;
    while(at<bytes && text[at]!='"') ++at;
    if(at==bytes || at-begin>=capacity) return false;
    memcpy(out,text+begin,at-begin);out[at-begin]=0;++at;return true;
  };
  return field("{\"schema\":1,\"app_id\":\"",v.app,sizeof(v.app)) &&
    field(",\"package_id\":\"",v.package,sizeof(v.package)) &&
    field(",\"project_id\":\"",v.project,sizeof(v.project)) &&
    field(",\"archive_sha256\":\"",v.archive,sizeof(v.archive)) &&
    field(",\"source_sha256\":\"",v.source,sizeof(v.source)) &&
    at+1==bytes && text[at]=='}' && v.valid();
}
enum class Read {Absent,Valid,Invalid};
template<class FS> Read read(FS& fs,const char* path,Identity& v) {
  errno=0;auto file=fs.open(path,"r");const int error=errno;
  if(!file) {
    if(error && error!=ENOENT) return Read::Invalid;
    errno=0;const bool exists=fs.exists(path);const int existsError=errno;
    return exists || (existsError && existsError!=ENOENT)?Read::Invalid:Read::Absent;
  }
  const size_t n=file.size();char body[kMaxBytes+1];
  if(file.isDirectory() || !n || n>kMaxBytes) {file.close();return Read::Invalid;}
  const size_t got=file.read(reinterpret_cast<uint8_t*>(body),n);file.close();
  return got==n && decode(body,n,v)?Read::Valid:Read::Invalid;
}
template<class FS> bool writeVerified(FS& fs,const char* path,const Identity& v) {
  char body[kMaxBytes+1];const size_t n=encode(v,body,sizeof(body));if(!n) return false;
  auto file=fs.open(path,"w");if(!file) return false;
  const size_t written=file.write(reinterpret_cast<const uint8_t*>(body),n);file.close();
  if(written!=n) return false;
  Identity back;return read(fs,path,back)==Read::Valid && back==v;
}
// The existing two version folders retain their identity files. Appdata follows
// the current app, not its executable version; ambiguous/existing temp data fails
// closed. Never remove a recovery folder to make a swap appear successful.
template<class FS,class Path> bool swapPrevious(FS& fs,const Path& current,const Path& previous,const Path& temporary) {
  if(!fs.exists(current.c_str()) || !fs.exists(previous.c_str()) || fs.exists(temporary.c_str())) return false;
  const Path data=current+"/appdata",oldData=previous+"/appdata";
  const bool moveData=fs.exists(data.c_str());
  if(moveData && (fs.exists(oldData.c_str()) || !fs.rename(data.c_str(),oldData.c_str()))) return false;
  if(!fs.rename(current.c_str(),temporary.c_str())) {
    if(moveData) fs.rename(oldData.c_str(),data.c_str());
    return false;
  }
  if(!fs.rename(previous.c_str(),current.c_str())) {
    if(fs.rename(temporary.c_str(),current.c_str()) && moveData) fs.rename(oldData.c_str(),data.c_str());
    return false;
  }
  if(!fs.rename(temporary.c_str(),previous.c_str())) {
    if(fs.rename(current.c_str(),previous.c_str()) && fs.rename(temporary.c_str(),current.c_str()) && moveData)
      fs.rename(oldData.c_str(),data.c_str());
    return false;
  }
  return true;
}
} // namespace fire_lua_install
