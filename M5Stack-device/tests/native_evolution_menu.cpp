#include "fire_evolution_core.h"
#include "fire_ai_menu.h"
#include "fire_app_updates.h"
#include "fire_ai_menu_ui.h"
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>

struct Canvas {
  std::array<uint16_t,320*240> pixels{};
  unsigned spans=0;
  void fillRect(int x,int y,int w,int h,uint16_t color) {
    assert(x>=0 && y>=0 && w>=0 && h>=0 && x+w<=320 && y+h<=240);++spans;
    for (int row=y;row<y+h;++row) for (int col=x;col<x+w;++col) pixels[row*320+col]=color;
  }
  uint16_t readPixel(int x,int y) {assert(x>=0 && y>=0 && x<320 && y<240);return pixels[y*320+x];}
};
int main() {
  static_assert(sizeof(fire_evolution::Aggregate)<768,"bounded OS aggregate, no raw input stream");
  fire_evolution::Aggregate aggregate;assert(aggregate.empty());
  aggregate.callbacks[1].add(100);aggregate.callbacks[1].add(300);
  assert(aggregate.callbacks[1].count==2 && aggregate.callbacks[1].totalUs==400 && aggregate.callbacks[1].maxUs==300);
  aggregate.sample(50000,2000);aggregate.sample(60000,3000);assert(aggregate.heapMin==50000 && aggregate.luaPeak==3000);
  for (unsigned i=0;i<20;++i) aggregate.error(i&1?"mic":"data",i&2?"timeout":"permission_denied");
  assert(aggregate.errorCount==4);
  for (unsigned i=0;i<20;++i) {char code[16];std::snprintf(code,sizeof(code),"error%u",i);aggregate.error("test",code);}
  assert(aggregate.errorCount==8 && !strcmp(aggregate.errors[7].operation,"other"));
  uint32_t saturated=UINT32_MAX;fire_evolution::increment(saturated);assert(saturated==UINT32_MAX);
  fire_evolution::Outbox box;
  for (uint8_t i=0;i<32;++i) {assert(box.freeSlot(1536)==i);assert(box.add(i,1536));}
  assert(box.count==32 && box.used==49152 && box.freeSlot(1)<0);
  assert(!box.add(0,1536));box.remove(4);assert(box.freeSlot(1536)==4);assert(box.add(4,1536));
  assert(!fire_evolution::acceptedAck("request","batch","other","batch","accepted"));
  assert(!fire_evolution::acceptedAck("request","batch","request","other","accepted"));
  assert(!fire_evolution::acceptedAck("request","batch","request","batch","rejected"));
  assert(fire_evolution::acceptedAck("request","batch","request","batch","duplicate"));
  assert(fire_evolution::acceptedAck("request","batch","request","batch","accepted"));
  fire_evolution::Outbox capacity;for (uint8_t i=0;i<25;++i) assert(capacity.add(i,2560));
  assert(capacity.freeSlot(1537)<0);assert(capacity.freeSlot(1536)>=0);
  {
    using namespace fire_app_updates;
    assert(newer("0.1.9","0.1.10") && !newer("0.1.10","0.1.9"));
    assert(!newer("1.2.3","1.2.3") && !newer("1.2.3","1.2.4-beta"));
    auto available=[&](bool online,bool suppressed,uint32_t epoch,uint32_t cached,uint32_t now,const char* app="app-one") {
      return eligible(online,suppressed,true,epoch,cached,now,1000,"app-one",app,"project-one","installed","ready","0.1.5","0.1.6");
    };
    assert(available(true,false,7,7,2000));
    assert(!available(false,false,7,7,2000)); // offline: caller directly launches original; no network operation in policy
    assert(!available(true,true,7,7,2000)); // per-app preference
    assert(!available(true,false,8,7,2000)); // new admission epoch invalidates old metadata
    assert(!available(true,false,7,7,62000));
    assert(!available(true,false,7,7,2000,"other-app"));
    assert(active(1,false) && !active(1,true) && !active(2,true) && !active(3,true)); // Quick Settings owns its A/C/B
    assert(confirm(1,0,false)==Action::Download); // Ja is download, never Run
    assert(completed(2,true)==3 && confirm(3,0,false)==Action::Wait);
    assert(confirm(3,0,true)==Action::RunVerified); // NEW explicit post-install B only
    assert(confirm(1,1,false)==Action::Installed && confirm(1,2,false)==Action::Suppress);
    assert(completed(0,true)==0 && confirm(0,0,true)==Action::Wait); // minimized completion cannot steal screen/run
    assert(completed(2,false)==1);
    assert(eligible(true,false,true,7,7,10,UINT32_MAX-100,"app","app","project","old","new","1.0.0","1.0.1"));
    puts("PASS cached update decisions offline stale epoch per-app suppression and separate post-install Run");
  }
  puts("PASS Evolution bounded aggregates outbox capacity and exact accepted duplicate ACK gate");

  using namespace fire_ai_menu;
  assert(count(Page::Main,false,0,32)==7);
  assert(count(Page::Main,true,15,32)==7); // one Resume entry, no per-job duplicates
  assert(at(Page::Main,0,true,15,32).kind==Kind::Jobs);
  assert(at(Page::Main,4,false,0,32).kind==Kind::Evolution && at(Page::Main,5,false,0,32).kind==Kind::Settings && at(Page::Main,6,false,0,32).kind==Kind::Back);
  assert(sameJob("build-one","","build-one","child-repair"));
  assert(!sameJob("build-one","","other-build","child-repair"));
  assert(sameJob("","repair-one","linked-build","repair-one"));
  assert(!sameJob("","repair-one","linked-build","repair-two"));
  assert(!sameJob("","","",""));
  JobAction menu[5];
  assert(actions(false,false,true,false,false,menu,true)==3 && menu[0]==JobAction::Open && menu[1]==JobAction::Delete);
  assert(openRoute(true,"build-ready","repair-ready")==OpenRoute::Repair); // both IDs retained; exact repair query
  assert(openRoute(true,"build-two","")==OpenRoute::Build);
  assert(openRoute(false,"build-two","")==OpenRoute::None);
  assert(!sameJob("build-two","","build-one",""));
  assert(!autoConfirmRepair(false,true) && !autoConfirmRepair(true,true)); // read-only Open never pays
  assert(autoConfirmRepair(true,false)); // actual explicit Resume/current proposal path

  assert(actions(false,true,true,false,false,menu)==3 && menu[0]==JobAction::Resume && menu[1]==JobAction::Delete && menu[2]==JobAction::Back);
  assert(actions(true,false,false,true,true,menu)==5 && menu[0]==JobAction::Pause && menu[3]==JobAction::Context && menu[4]==JobAction::Back);
  assert(actions(true,false,false,false,true,menu)==4 && menu[0]==JobAction::Cancel && menu[2]==JobAction::Context); // thinking has no invented Pause
  assert(count(Page::Apps,false,0,32)==33 && at(Page::Apps,31,false,0,32).index==31 && at(Page::Apps,32,false,0,32).kind==Kind::Back);
  assert(at(Page::Settings,4,false,0,32).kind==Kind::Voice && at(Page::Settings,6,false,0,32).kind==Kind::Back);
  assert(scroll(31,0)==28 && scroll(0,28)==0);
  assert(canOpenProposal(3,"proposal-current","project-one","project-one"));
  assert(!canOpenProposal(3,"proposal-current","project-one","project-two"));
  assert(!canOpenProposal(3,"proposal-current","","project-one"));
  assert(!canOpenProposal(3,"proposal-current",nullptr,"project-one"));
  assert(!canOpenProposal(3,"proposal-current","project-one",nullptr));
  assert(!canOpenProposal(3,"","project-one","project-one"));
  assert(!canOpenProposal(3,nullptr,"project-one","project-one"));
  assert(canOpenProposal(3,"proposal-second","project-two","project-one","cohort-job","cohort-job","Målapp to"));
  assert(!canOpenProposal(3,"proposal-second","project-two","project-one","other-job","cohort-job","Målapp to"));
  assert(!canOpenProposal(3,"proposal-second","project-two","project-one",nullptr,"cohort-job","Målapp to"));
  assert(!canOpenProposal(3,"proposal-second","project-two","project-one","cohort-job","","Målapp to"));
  assert(!canOpenProposal(3,"proposal-second","project-two","project-one","cohort-job","cohort-job",nullptr));
  assert(!canOpenProposal(3,"proposal-second","project-two","project-one","cohort-job","cohort-job",""));
  for (uint8_t state:{0,1,2,4,5,6}) assert(!canOpenProposal(state,"proposal-current","project-one","project-one"));
  for (bool permissions:{false,true}) for (bool proposal:{false,true}) {
    const uint8_t size=evolutionCount(permissions,proposal);
    assert(evolutionTail(size-1,permissions,proposal)==EvolutionTail::Back);
    unsigned proposals=0,grants=0;
    for (uint8_t row=0;row<size;++row) {
      const auto tail=evolutionTail(row,permissions,proposal);
      if (row<14) assert(tail==EvolutionTail::Main);
      proposals+=tail==EvolutionTail::Proposal;grants+=tail==EvolutionTail::Permissions;
    }
    assert(proposals==unsigned(proposal) && grants==unsigned(permissions));
    assert(evolutionTail(20,permissions,proposal)==EvolutionTail::Back);
  }
  puts("PASS Evolution proposal project binding absent stale mismatch and permission menu coexistence");
  static Canvas canvas;const char* labels[]={"Resume feilretting","Resume bygging","Settings","Back"};
  const char* longName="Måleappen for kjøleskap og bodelsbatteri med mange avlesninger";
  canvas.fillRect(0,0,320,240,FireUI::Bg);fire_ai_menu_ui::proposalName(canvas,"Målapp to");
  const auto targetPixels=canvas.pixels;
  canvas.fillRect(0,0,320,240,FireUI::Bg);fire_ai_menu_ui::proposalName(canvas,"Opprinnelsesapp en");
  assert(canvas.pixels!=targetPixels);
  for (size_t i=44*320;i<canvas.pixels.size();++i) assert(canvas.pixels[i]==FireUI::Bg && targetPixels[i]==FireUI::Bg);
  std::array<uint16_t,320*18> footer{};
  for (uint8_t selected=0;selected<4;++selected) {
    canvas.fillRect(0,0,320,240,FireUI::Bg);canvas.spans=0;
    fire_ai_menu_ui::draw(canvas,"AI DEVELOPER","Backend er tilkoblet",FireUI::Green,longName,labels,4,selected,"Velg en handling");
    assert(canvas.spans<10000);
    if (!selected) memcpy(footer.data(),canvas.pixels.data()+222*320,sizeof(footer));
    else assert(!memcmp(footer.data(),canvas.pixels.data()+222*320,sizeof(footer)));
  }
  const char* appIcons[]={"icon.timer","icon.activity","icon.compass","icon.code"};
  canvas.fillRect(0,0,320,240,FireUI::Bg);
  fire_ai_menu_ui::draw(canvas,"SELECT APP","Backend er tilkoblet",FireUI::Green,longName,labels,4,3,"Velg en app",appIcons);
  assert(!memcmp(footer.data(),canvas.pixels.data()+222*320,sizeof(footer)));
  char line[81];size_t offset=0;const size_t length=strlen(longName);
  for (uint8_t i=0;i<3 && offset<length;++i) {const size_t before=offset;offset=fire_ai_menu_ui::line(longName,length,offset,line,284,"small10");assert(offset>before && strlen(line)<=80);}
  assert(offset==length);
  const char* utf8="æøåÆØÅ æøåÆØÅ æøåÆØÅ æøåÆØÅ æøåÆØÅ æøåÆØÅ æøåÆØÅ";
  offset=0;while (offset<strlen(utf8)) {offset=fire_ai_menu_ui::line(utf8,strlen(utf8),offset,line,284);size_t at=0;uint32_t cp=0;while(at<strlen(line)) assert(fire_app_bitmap::codepoint(line,strlen(line),at,cp));}
  {
    for (const char* phase:{"queued","preparing","generating","validating","compiling","testing","reviewing","packaging","api_wait"}) {
      assert(workActive("building",phase));assert(workActive("",phase));
    }
    for (const char* status:{"ready","failed","cancelled","paused","interrupted","unknown","awaiting_confirmation","unavailable","not_found"}) {
      assert(!workActive(status,"generating"));assert(!workActive("",status));
    }
    assert(!workActive("building","paused") && !workActive("building","unknown"));
    assert(!stopsTrackedWork("active-B","history-A","ready","ready")); // another paginated row cannot hide B
    assert(!stopsTrackedWork("active-B","active-B","building","testing"));
    assert(stopsTrackedWork("active-B","active-B","paused","paused"));
    assert(stopsTrackedWork("active-B","active-B","ready","ready"));
    assert(!stopsTrackedWork("","history-A","ready","ready"));

    assert(workReady("ready","ready","verified-package") && workReady("","ready","verified-package"));
    assert(!workReady("building","testing","verified-package") && !workReady("ready","ready",""));
    assert(!workReady("failed","ready","verified-package")); // 100 percent or stale phase cannot produce Done
    assert(workIndicator(false,false,1000,0)==WorkIndicator::None);
    assert(workIndicator(false,false,6999,1000)==WorkIndicator::Done);
    assert(workIndicator(false,false,7000,1000)==WorkIndicator::None);
    assert(workIndicator(true,false,1100,1000)==WorkIndicator::Build); // ready A cannot hide active B
    assert(workIndicator(false,true,1100,1000)==WorkIndicator::Repair);
    assert(doneVisible(20,UINT32_MAX-100) && !doneVisible(6000,UINT32_MAX-100));
    uint32_t done=completionStamp(1000,0,false,"ready","ready","package-A");
    assert(done==1000 && completionStamp(2000,done,true,"ready","ready","package-A")==1000);
    for (const char* status:{"failed","paused","cancelled","unknown","awaiting_confirmation"})
      assert(completionStamp(2000,done,true,status,status,"package-A")==0);
    done=completionStamp(2000,done,false,"building","generating",""); // new active B clears A
    assert(done==0);
    done=completionStamp(2500,done,false,"failed","failed","");
    assert(workIndicator(false,false,2600,done)==WorkIndicator::None);

    for (WorkIndicator kind:{WorkIndicator::Build,WorkIndicator::Repair,WorkIndicator::Done,WorkIndicator::None}) {
      canvas.fillRect(0,0,320,240,FireUI::Bg);
      FireUI::text(canvas,10,7,"20:38",FireUI::Text,"ui12b",48);
      FireUI::text(canvas,72,7,"26.11.2026",FireUI::Muted,"ui12",138,1);
      // Reserved status-icon region and separator must remain untouched.
      canvas.fillRect(232,5,78,18,FireUI::Blue);canvas.fillRect(10,27,300,1,FireUI::Border);
      const auto before=canvas.pixels;
      fire_ai_menu_ui::workStatus(canvas,kind,100);
      unsigned changed=0;
      for (int y=0;y<240;++y) for (int x=0;x<320;++x) if (before[y*320+x]!=canvas.pixels[y*320+x]) {
        ++changed;assert(x>=112 && x<208 && y>=20 && y<27);
        assert(before[y*320+x]==FireUI::Bg); // never covers date, time, icons or border
      }
      assert(kind==WorkIndicator::None?changed==0:changed>0);
    }
    puts("PASS exact work status READY Done expiry wrap and actual320x240 header no-overlap rendering");
  }
  puts("PASS actual AI menu renderer Resume footer parity long UTF8 names independent job mapping and32app pagination");
}
