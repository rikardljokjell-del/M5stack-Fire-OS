"""Boundary matrices over the actual production session-sensitive UI branches.

Reuse the existing extracted-handler translation unit and its small String,
parsed-field and backend spies. No replacement handler implementation, firmware
build, serial port, credential, network or model is involved. Windows compiles
only; Linux executes the actual extracted C++ assertions.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import test_native_guards as native
import test_production_app_flow as flow


MAIN = r'''
static void updateMatrix() {
  for (unsigned missing=0;missing<2;++missing) {
    Backend backend;backend.ready=false;FireOS os;
    os.backendClient_=missing?nullptr:&backend;
    os.appUpdateStage_=3;os.appUpdateReady_=true;os.appUpdateCandidate_="selected-ready";
    os.updateRunButton(1);
    assert(os.appUpdateStage_==3 && os.appUpdateReady_ && os.appUpdateFailure_==3);
    assert(backend.runs==0 && os.redrawRequested_);
  }
  Backend backend;backend.send=false;FireOS os;os.backendClient_=&backend;
  os.appUpdateStage_=3;os.appUpdateReady_=true;os.appUpdateCandidate_="selected-ready";
  os.updateRunButton(1);
  assert(os.appUpdateStage_==3 && os.appUpdateReady_ && os.appUpdateFailure_==4);
  assert(backend.runs==1); // Attempted send is not an accepted RUN.
  backend.send=true;os.updateRunButton(1);
  assert(backend.runs==2 && backend.package=="selected-ready");
  assert(os.appUpdateStage_==0 && !os.appUpdateReady_);
  assert(os.aiWorkflowText_=="Starter app" && os.managerStatus_=="Starter app");
  for (unsigned ready=0;ready<2;++ready) {
    FireOS back;back.backendClient_=&backend;back.appUpdateStage_=3;
    back.appUpdateReady_=ready;back.appUpdateCandidate_="selected-ready";
    const unsigned runs=backend.runs;back.updateRunButton(2);
    assert(!back.appUpdateStage_ && !back.appUpdateReady_ && backend.runs==runs);
  }
  FireOS noApproval;noApproval.backendClient_=&backend;noApproval.appUpdateStage_=3;
  noApproval.appUpdateReady_=false;const unsigned runs=backend.runs;
  noApproval.updateRunButton(1);assert(backend.runs==runs && noApproval.appUpdateStage_==3);
  puts("PASS extracted update admission send failure explicit Run and Back");
}

static FireOS reading(Backend& backend,uint32_t start) {
  FireOS os;os.backendClient_=&backend;os.aiJobViewing_=os.aiJobOpenPending_=true;
  os.aiJobOpenAt_=start;os.aiJobOpenEpoch_=backend.epoch;
  os.aiJobOpenRequest_="read-one";os.aiJobRepair_="repair-one";os.luaRepairId_="repair-one";
  os.luaRepairStatus_="loading";os.luaRepairStatusQueryPending_=true;
  return os;
}

static void readOnlyMatrix() {
  const uint32_t starts[]={0,1234,UINT32_MAX-25};
  const uint32_t ages[]={0,9999,10000,10001};
  for (const uint32_t start:starts) for (const uint32_t age:ages) {
    Backend backend;FireOS os=reading(backend,start);nowMs=uint32_t(start+age);
    os.serviceAiJobOpen();
    const bool expired=age>=10000;
    assert(os.aiJobOpenPending_==!expired && bool(os.aiJobOpenRequest_.length())==!expired);
    assert(os.luaRepairStatusQueryPending_==!expired);
    assert(os.aiJobViewing_ && os.aiJobRepair_=="repair-one" && os.luaRepairId_=="repair-one");
    assert(backend.runs==0 && backend.downloads==0 && os.homes==0);
  }
  for (unsigned reason=0;reason<2;++reason) {
    Backend backend;FireOS os=reading(backend,42);nowMs=42;
    if(reason)os.backendClient_=nullptr;else ++backend.epoch;
    os.serviceAiJobOpen();assert(!os.aiJobOpenPending_ && !os.aiJobOpenRequest_.length());
    assert(os.redrawRequested_ && backend.runs==0 && backend.downloads==0);
  }
  for (unsigned viewing=0;viewing<2;++viewing) {
    Backend backend;FireOS os=reading(backend,0);nowMs=10000;
    if(viewing)os.aiJobOpenPending_=false;else os.aiJobViewing_=false;
    os.serviceAiJobOpen();assert(os.aiJobOpenRequest_=="read-one"); // No unrelated view mutation.
  }
  for (unsigned pending=0;pending<2;++pending) for (unsigned cancelling=0;cancelling<2;++cancelling) {
    Backend backend;Package package;FireOS os=reading(backend,0);os.packageManager_=&package;
    os.aiJobOpenPending_=pending;os.luaRepairCancelPending_=cancelling;
    os.luaRepairRequested_=false;os.userRunAfterInstall_="unrelated-intent";
    os.readOnlyBack(2); // The exact first read-only C branch in handleLuaErrorButton.
    assert(!os.aiJobViewing_ && !os.aiJobOpenPending_ && !os.aiJobOpenRequest_.length());
    assert(!os.luaRepairStatusQueryPending_ && os.screen_==FireOS::Screen::AiDeveloper);
    assert(os.aiProjectPickerActive_ && os.aiPickerPage_==fire_ai_menu::Page::Job);
    assert(os.luaRepairCancelPending_==bool(cancelling) && !os.luaRepairRequested_);
    assert(os.luaRepairId_=="repair-one" && os.userRunAfterInstall_=="unrelated-intent");
    assert(backend.runs==0 && backend.downloads==0 && !package.cancelled && os.homes==0 && os.opened==0);
  }
  puts("PASS extracted read-only timeout wrap epoch and Back without work");
}

static void correlationMatrix() {
  // Production status prefix: an old/mismatched status cannot revive a failed
  // read-only Open. Epoch/10s expiry are checked before target adoption.
  for (unsigned mismatch=0;mismatch<6;++mismatch) {
    Backend backend;FireOS os=reading(backend,UINT32_MAX-50);nowMs=25;
    reply=cJSON();reply.fields["repair_id"].text="repair-one";
    if(mismatch==1)reply.fields["repair_id"].text="another-repair";
    if(mismatch==2)++backend.epoch;
    if(mismatch==3)nowMs=uint32_t(os.aiJobOpenAt_+10000);
    if(mismatch==4)os.backendClient_=nullptr;
    if(mismatch==5) {os.aiJobOpenPending_=false;os.aiJobOpenRequest_=String();}
    const bool adopted=os.repairGate("parsed-status");
    assert(adopted==(mismatch==0));
    if(adopted)assert(!os.aiJobOpenPending_ && !os.aiJobOpenRequest_.length());
    assert(backend.runs==0 && backend.downloads==0);
  }
  const char* statuses[]={"accepted","duplicate","rejected","unexpected"};
  for (const char* status:statuses) for (unsigned wrong=0;wrong<2;++wrong) {
    Backend backend;FireOS os=reading(backend,0);nowMs=0;
    reply=cJSON();reply.fields["type"].text="event_ack";
    reply.fields["event_id"].text=wrong?"another-read":"read-one";
    reply.fields["status"].text=status;
    os.jobAck("parsed-ack");
    const bool failure=String(status)!="accepted" && String(status)!="duplicate";
    assert(os.aiJobOpenPending_==!(failure && !wrong));
    assert(backend.runs==0 && backend.downloads==0);
  }
  for (unsigned kind=0;kind<2;++kind) {
    Backend backend;FireOS os=reading(backend,0);
    reply=cJSON();reply.fields["event_id"].text="read-one";reply.fields["status"].text="accepted";
    reply.fields["type"].text=kind?"event_ack":"error";
    if(kind)reply.fields["result"].fields["error"].text="denied";
    os.jobAck("parsed-error");assert(!os.aiJobOpenPending_ && !os.aiJobOpenRequest_.length());
    assert(backend.runs==0 && backend.downloads==0);
  }
  puts("PASS extracted correlated error and status admission guards");
}

static FireOS selected(Backend& backend,Package& package,uint8_t phase) {
  FireOS os;os.backendClient_=&backend;os.packageManager_=&package;
  os.aiJobViewing_=os.aiJobNeedsInstall_=true;os.aiReadyPackageId_="selected-ready";
  os.aiWorkflowState_=4;os.downloadPhase_=phase;os.downloadPackage_="selected-ready";
  os.downloadSession_=backend.sid;os.downloadBoot_=backend.boot;os.downloadRequest_="download-one";
  os.userRunAfterInstall_="selected-ready";package.package="selected-ready";
  return os;
}

static void cancelMatrix() {
  for (uint8_t phase=1;phase<=2;++phase) for (unsigned viewing=0;viewing<2;++viewing)
    for (unsigned needs=0;needs<2;++needs) for (unsigned same=0;same<2;++same) {
      Backend backend;Package package;FireOS os=selected(backend,package,phase);
      os.aiJobViewing_=viewing;os.aiJobNeedsInstall_=needs;
      if(!same)os.aiReadyPackageId_="another-job";
      os.cancelAppDownload();
      const bool restore=phase==1 && viewing && needs && same;
      assert(os.aiWorkflowState_==(restore?5:4));
      assert(os.downloadPhase_==3 && !os.userRunAfterInstall_.length());
      assert(package.cancelled==(phase==2) && backend.runs==0 && backend.downloads==0);
    }
  for (unsigned other=0;other<2;++other) {
    Backend backend;Package package;FireOS os=selected(backend,package,1);
    os.downloadPackage_=String();os.aiReadyPackageId_=String();
    if(other)os.userRunAfterInstall_="another-intent";
    os.cancelAppDownload();assert(os.aiWorkflowState_==4 && backend.runs==0);
    if(other)assert(os.userRunAfterInstall_=="another-intent");
  }
  // Rejected offer, timeout and changed scope use the SAME production cancel
  // function, preserving a selected READY candidate but never a latent RUN.
  for (unsigned path=0;path<6;++path) {
    Backend backend;Package package;FireOS os=selected(backend,package,1);
    nowMs=UINT32_MAX-50;os.downloadRequestedAt_=nowMs;
    if(path<3) {
      reply=cJSON();reply.fields["event_id"].text="download-one";
      reply.fields["type"].text=path==0?"error":"event_ack";
      reply.fields["status"].text="accepted";
      reply.fields["result"].fields["status"].text=path==1?"rejected":"recorded";
      if(path==2)reply.fields["result"].fields["error"].text="denied";
      assert(os.handleDownloadIntent("parsed-offer"));
    } else {
      if(path==3)nowMs=uint32_t(nowMs+15000);
      if(path==4)backend.sid="another-session";
      if(path==5)backend.boot="another-boot";
      os.serviceDownloadIntent();
    }
    assert(os.aiWorkflowState_==5 && os.downloadPhase_==3 && !os.userRunAfterInstall_.length());
    assert(os.aiJobNeedsInstall_ && backend.runs==0 && !package.cancelled);
  }
  Backend backend;Package package;FireOS os=selected(backend,package,0);backend.send=false;
  assert(!os.requestAppDownload("project-one","selected-ready","app-one",true));
  assert(os.aiWorkflowState_==5 && os.downloadPhase_==3 && !os.userRunAfterInstall_.length());
  assert(backend.downloads==1 && backend.runs==0);
  puts("PASS extracted pre-offer cancel retryable READY negative matrix");
}

int main() {updateMatrix();readOnlyMatrix();correlationMatrix();cancelMatrix();}
'''


def source():
    extracted = flow.source()
    if not extracted.endswith(flow.MAIN):
        raise AssertionError('Production extraction fixture changed its main boundary')
    return extracted[:-len(flow.MAIN)] + MAIN


class SessionUiTests(unittest.TestCase):
    def build(self, *, execute):
        compiler = native.host_compiler()
        if compiler is None:
            self.skipTest('No C++ host compiler; no runtime verification claimed')
        prefix = [compiler, 'c++'] if Path(compiler).stem.lower() == 'zig' else [compiler]
        if os.name == 'nt' and Path(compiler).stem.lower() == 'zig':
            prefix += ['-target', 'x86_64-windows-gnu']
        with tempfile.TemporaryDirectory(prefix='fire-session-ui-') as directory:
            directory = Path(directory)
            path = directory / 'session_ui.cpp'
            path.write_text(source(), encoding='utf-8')
            output = directory / ('session_ui' if execute else 'session_ui.o')
            command = prefix + ['-std=c++17', '-O2', '-UNDEBUG', '-Wall', '-Wextra',
                                '-Werror', '-pedantic', '-I', str(native.ROOT / 'src')]
            if not execute:
                command += ['-c']
            built = subprocess.run(command + [str(path), '-o', str(output)],
                                   capture_output=True, text=True, timeout=180)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            self.assertTrue(output.is_file())
            if execute:
                result = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

    def test_actual_branch_matrices_compile_strictly(self):
        self.build(execute=False)

    @unittest.skipIf(os.name == 'nt', 'Windows policy4551: compile only; execute actual assertions on Linux CI')
    def test_actual_branch_matrices_execute(self):
        result = self.build(execute=True)
        for marker in ('PASS extracted update admission', 'PASS extracted read-only timeout',
                       'PASS extracted correlated error', 'PASS extracted pre-offer cancel'):
            self.assertIn(marker, result)


if __name__ == '__main__':
    unittest.main()
