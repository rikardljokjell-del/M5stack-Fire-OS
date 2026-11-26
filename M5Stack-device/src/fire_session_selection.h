#pragma once
#include <stdint.h>
#include <stddef.h>

// Bounded records owned by the existing backend client. A transmitted choice
// is never replayed; only an exact server receipt can confirm its effect.
namespace fire_session {
template<class Text> Text escape(const Text& input) {
  Text output;output.reserve(input.length()+8);
  for (size_t i=0;i<input.length();++i) {
    const char c=input[i];
    if (c=='\\' || c=='"') output+='\\';
    if (c=='\n') output+="\\n";
    else if (c=='\r') output+="\\r";
    else if (static_cast<unsigned char>(c)<32) {
      const char hex[]="0123456789abcdef";output+="\\u00";
      output+=hex[(static_cast<unsigned char>(c)>>4)&15];output+=hex[static_cast<unsigned char>(c)&15];
    } else output+=c;
  }
  return output;
}
// Session admission carries acknowledged identity, never a queued app/mode
// choice. The server's scoped session ID resolves authoritative project/mode.
template<class Text> Text startFields(const Text& resume,const Text& context) {
  Text fields;
  if (resume.length()) fields+=Text(",\"resume_session_id\":\"")+escape(resume)+"\"";
  if (context.length()) fields+=Text(",\"development_context_id\":\"")+escape(context)+"\"";
  return fields;
}
template<class Text> Text appFields(const Text& mode,const Text& project,const Text& base) {
  Text fields=Text(",\"app_mode\":\"")+escape(mode)+"\"";
  if (mode=="update" && project.length()) fields+=Text(",\"project_id\":\"")+escape(project)+"\"";
  if (mode=="update" && base.length()) fields+=Text(",\"base_package_id\":\"")+escape(base)+"\"";
  return fields;
}
template<class Text> Text modeFields(const Text& mode) {return Text(",\"conversation_mode\":\"")+escape(mode)+"\"";}

template<class Text> struct Selection {
  Text appMode,project,base,mode,appEvent,modeEvent;
  bool appSent=false,modeSent=false,appUnclear=false,modeUnclear=false;
  bool pending() const {return appEvent.length() || modeEvent.length();}
  bool unclear() const {return appUnclear || modeUnclear;}
  void clearApp() {appMode=project=base=appEvent=Text();appSent=appUnclear=false;}
  void clearMode() {mode=modeEvent=Text();modeSent=modeUnclear=false;}
  void clear() {clearApp();clearMode();}
  bool begin() {
    if ((appSent && !appUnclear) || (modeSent && !modeUnclear)) return false;
    clear();return true; // actual new user choice may replace an unresolved one
  }
  void queueApp(const Text& value,const Text& target,const Text& package,const Text& event) {
    appMode=value;project=target;base=package;appEvent=event;appSent=appUnclear=false;
  }
  void queueMode(const Text& value,const Text& event) {mode=value;modeEvent=event;modeSent=modeUnclear=false;}
  bool sendApp() const {return appEvent.length() && !appSent && !appUnclear && !modeSent;}
  bool sendMode() const {return modeEvent.length() && !modeSent && !modeUnclear && !appEvent.length();}
  void lost() {if (appSent) appUnclear=true;if (modeSent) modeUnclear=true;}
  bool appAck(const Text& event) {if (!appSent || !appEvent.length() || appEvent!=event) return false;clearApp();return true;}
  bool modeAck(const Text& event) {if (!modeSent || !modeEvent.length() || modeEvent!=event) return false;clearMode();return true;}
  bool rejected(const Text& event) {
    if (appEvent.length() && appEvent==event) {clear();return true;}
    if (modeEvent.length() && modeEvent==event) {clearMode();return true;}
    return false;
  }
};
} // namespace fire_session
