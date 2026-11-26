#include "fire_ws_handshake.h"
#include "fire_backend_policy.h"
#include "fire_session_selection.h"
#include "fire_json_guard.h"
#include <cassert>
#include <string>
#include <cstdio>
static void selectionTests() {
  using Text=std::string;
  fire_session::Selection<Text> pending;
  assert(pending.begin());
  pending.queueMode("develop","boot-mode1");
  pending.queueApp("new","stale-project","stale-package","boot-app1");
  const Text admission="{\"event\":\"session_start\""+fire_session::startFields(Text("old-session"),Text())+"}";
  assert(admission=="{\"event\":\"session_start\",\"resume_session_id\":\"old-session\"}");
  assert(pending.sendApp() && !pending.sendMode());
  assert(!pending.appAck("boot-app1") && !pending.modeAck("boot-mode1"));
  const Text create="{\"event\":\"app_select\""+fire_session::appFields(pending.appMode,pending.project,pending.base)+"}";
  assert(create=="{\"event\":\"app_select\",\"app_mode\":\"new\"}");
  pending.appSent=true;
  assert(pending.pending() && !pending.sendApp() && !pending.begin());
  pending.lost(); // socket lost after write, before app_selected
  assert(pending.unclear() && !pending.sendApp() && !pending.sendMode());
  assert(!pending.appAck("another-event") && pending.pending());
  // Matching selection_ack from a successor is a receipt, never a replay.
  assert(pending.appAck("boot-app1") && !pending.unclear() && pending.sendMode());
  pending.modeSent=true;pending.lost();
  assert(!pending.sendMode() && !pending.modeAck("wrong"));
  assert(pending.modeAck("boot-mode1") && !pending.pending());
  assert(pending.begin());
  pending.queueApp("update","project-two","package-two","boot-app2");
  pending.queueMode("develop","boot-mode2");
  const Text update="{\"event\":\"app_select\""+fire_session::appFields(pending.appMode,pending.project,pending.base)+"}";
  pending.appSent=true;
  assert(!pending.rejected("unrelated-error") && pending.pending());
  assert(pending.rejected("boot-app2") && !pending.pending()); // busy: scope was never optimistic
  pending.queueMode("chat","boot-mode3");pending.modeSent=true;
  assert(!pending.begin());pending.lost();assert(pending.begin()); // explicit choice after unresolved result
  assert(!pending.pending());
  const Text context="{\"event\":\"session_start\""+fire_session::startFields(Text("old-session"),Text("context-exact"))+"}";
  const Text mode="{\"event\":\"mode_select\""+fire_session::modeFields(Text("chat"))+"}";
  const Text quoted="{\"event\":\"app_select\""+fire_session::appFields(Text("update"),Text("a\"\\\n\r\t"),Text("p"))+"}";
  assert(fireJsonSafe(quoted.data(),quoted.size(),8192));
  assert(fire_session::escape(Text("\xc3\xa5"))=="\xc3\xa5");
  std::printf("SELECTION_JSON %s\n",admission.c_str());
  std::printf("SELECTION_JSON %s\n",create.c_str());
  std::printf("SELECTION_JSON %s\n",update.c_str());
  std::printf("SELECTION_JSON %s\n",context.c_str());
  std::printf("SELECTION_JSON %s\n",mode.c_str());
  std::printf("SELECTION_JSON %s\n",quoted.c_str());
  std::puts("PASS actual session/app/mode producers and lost receipt without replay");
}
static void connectionPolicyTests() {
  using namespace fire_backend_policy;
  for (int poll=0;poll<1000;++poll) assert(progress(false,true,false)==Progress::Waiting);
  assert(progress(false,false,true)==Progress::Waiting);
  assert(progress(false,false,false,true)==Progress::Waiting); // Failed state, TLS cleanup still owns worker
  assert(progress(false,false,false,false)==Progress::Failed);
  assert(progress(false,false,false)==Progress::Failed);
  assert(progress(true,false,false)==Progress::Ready);
  struct Store {
    unsigned writes=0,reads=0;uint8_t saved=0;bool fail=false,wrong=false;
    size_t putUChar(const char* key,uint8_t mode) {assert(std::string(key)=="backend_mode");++writes;if(fail)return 0;saved=mode;return 1;}
    uint8_t getUChar(const char* key,uint8_t) {assert(std::string(key)=="backend_mode");++reads;return wrong?255:saved;}
  } store;
  uint8_t mode=0;
  assert(saveMode(store,mode,1) && mode==1 && store.writes==1 && store.reads==1);
  store.fail=true;assert(!saveMode(store,mode,2) && mode==1 && store.reads==1);
  store.fail=false;store.wrong=true;assert(!saveMode(store,mode,2) && mode==1);
  const auto writes=store.writes;assert(!saveMode(store,mode,3) && store.writes==writes);
  ConnectFailure last{3u<<8|17u,-32512,450,7};
  assert(last.matches(7) && !last.matches(8)); // stale attempt never attributed to a new connection
  assert(failureReadable(false,false,true));
  assert(!failureReadable(true,false,true)); // worker still owns the snapshot
  assert(!failureReadable(false,true,true)); // explicit stop cancels visibility
  assert(!failureReadable(false,false,false)); // success/idle is not a failure
  last={};assert(!last.matches(8)); // actual new attempt resets old evidence
  TlsFailure failure;failure.beforeStop(true,2,0);assert(!failure.captured);
  failure.beforeStop(true,2,-1);failure.beforeStop(false,0,-1);
  assert(failure.captured && failure.socket && failure.state==2 && failure.error==-1);
  TlsFailure tcp;tcp.beforeStop(false,0,-1);assert(tcp.captured && !tcp.socket && tcp.state==0);
  std::puts("PASS async connect polling, single-key Sync persistence and pre-cleanup TLS failure evidence");
}
int main() {
  connectionPolicyTests();
  selectionTests();
  const char* accept = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=";
  const std::string valid = std::string("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: keep-alive, Upgrade\r\nSec-WebSocket-Accept: ") + accept + "\r\n\r\n";
  assert(fireWsAccepted(valid.data(), valid.size(), accept));
  assert(!fireWsAccepted(valid.data(), valid.size(), "AAAAAAAAAAAAAAAAAAAAAAAAAAA="));
  for (const char* field : {"Upgrade: websocket", "Sec-WebSocket-Accept: ", "HTTP/1.1 101 ", "Connection: keep-alive, Upgrade"}) {
    std::string wrong = valid; const size_t at = wrong.find(field); wrong[at] = '!';
    assert(!fireWsAccepted(wrong.data(), wrong.size(), accept));
  }
  std::string duplicate = valid.substr(0, valid.size() - 2) + "Sec-WebSocket-Accept: " + accept + "\r\n\r\n";
  assert(!fireWsAccepted(duplicate.data(), duplicate.size(), accept));
  assert(!fireWsAccepted(valid.data(), valid.size() - 1, accept));
  std::string nul = valid; nul[22] = 0; assert(!fireWsAccepted(nul.data(), nul.size(), accept));
  assert(fireWsNewSession("new","old","old"));
  assert(!fireWsNewSession("old","old",""));
  assert(!fireWsNewSession("old","","old"));
  assert(!fireWsNewSession("","old","old"));
  assert(fireWsNewSession("new","",""));
  assert(!fireWsSessionExpired(false,5999,1000));
  assert(fireWsSessionExpired(false,6000,1000));
  assert(fireWsSessionExpired(false,65000,1000)); // healthy transport PONG cannot admit a session
  assert(!fireWsSessionExpired(true,65000,1000));
  const uint32_t nearWrap=UINT32_MAX-2500;
  assert(!fireWsSessionExpired(false,nearWrap+4999,nearWrap));
  assert(fireWsSessionExpired(false,nearWrap+5000,nearWrap));
  assert(fireWsSessionRejected(false,"error","session_start_rejected",true));
  assert(!fireWsSessionRejected(true,"error","session_start_rejected",true));
  assert(!fireWsSessionRejected(false,"error","session_start_rejected",false));
  assert(!fireWsSessionRejected(false,"error","event_rejected",true));
  assert(!fireWsSessionRejected(false,"app_failed","session_start_rejected",true));
  assert(!fireWsSessionRejected(false,nullptr,nullptr,true));
  FireWsSessionAdmission admission;
  assert(admission.allowed());
  assert(!admission.reject(true,"error","session_start_rejected",true) && admission.allowed());
  assert(admission.reject(false,"error","session_start_rejected",true) && !admission.allowed());
  assert(!admission.reject(false,"error","event_rejected",true) && !admission.allowed()); // no implicit unblock/replay
  admission.retry(); // the same production operation used by explicit OFF-to-ON/configuration
  assert(admission.allowed());
  assert(!admission.reject(false,"session_started",nullptr,false) && admission.allowed()); // safe backend expired/stopped recovery
  assert(admission.reject(false,"error","session_start_rejected",true) && !admission.allowed()); // mismatch remains terminal
  std::puts("PASS bounded session deadline typed rejection and explicit policy retry");
  std::puts("PASS strict WebSocket nonce/header validation");
}
