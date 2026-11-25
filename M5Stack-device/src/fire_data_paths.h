#pragma once
#include <stddef.h>
#include <string.h>
namespace fire_data_paths {
// Arduino String::indexOf('\0') searches with strchr, which finds the normal
// trailing terminator too. Only bytes inside the supplied string are content.
inline bool privateRelative(const char* path,size_t length) {
  if (!path || length>96 || memchr(path,'\0',length) || (length && path[0]=='/')) return false;
  for (size_t i=0;i<length;++i)
    if (path[i]=='\\' || path[i]==':' || (path[i]=='.' && i+1<length && path[i+1]=='.')) return false;
  return true;
}
inline char lower(char c) {return c>='A' && c<='Z'?static_cast<char>(c-'A'+'a'):c;}
inline bool generated(const char* text,size_t length) {
  if (length<8 || lower(text[0])!='d' || lower(text[1])!='s' || text[2]!='-') return false;
  unsigned parts=0,digits=0;
  for (size_t i=3;i<=length;++i) {
    const char c=i<length?lower(text[i]):0;
    if (!c || c=='-') {if (!digits || digits>8) return false;++parts;digits=0;}
    else if ((c>='0' && c<='9') || (c>='a' && c<='f')) ++digits;
    else return false;
  }
  return parts==3;
}
inline bool safeMutation(const char* path,bool removeParent=false) {
  if (!path || !*path) return false;
  size_t start=0,part=0;bool datasets=false;
  const size_t length=strlen(path);
  for (size_t i=0;i<=length;++i) {
    const char c=path[i];
    // FAT Unicode uppercasing can map long-s to ASCII S (DATASETS / DS-).
    if (static_cast<unsigned char>(c)==0xc5 && i+1<length && static_cast<unsigned char>(path[i+1])==0xbf) return false;
    // FAT DOS aliases, ignored trailing dots/spaces, dot and empty components
    // are ambiguous mutation targets. Ordinary reads retain old semantics.
    if (c=='~' || c=='\\' || c==':') return false;
    if (!c || c=='/') {
      const size_t n=i-start;
      if (!n || (n==1 && path[start]=='.') || (n==2 && path[start]=='.' && path[start+1]=='.') ||
          path[i-1]=='.' || path[i-1]==' ') return false;
      if (part==0 && n==8) {
        const char* name="datasets";datasets=true;
        for (size_t j=0;j<8;++j) if (lower(path[start+j])!=name[j]) datasets=false;
        if (datasets && !c && removeParent) return false;
      } else if (part==1 && datasets && generated(path+start,n)) return false;
      ++part;start=i+1;
    }
  }
  return true;
}
} // namespace fire_data_paths
