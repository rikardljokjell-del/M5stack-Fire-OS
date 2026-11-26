#include "fire_evolution_core.h"
#include "fire_ai_menu.h"
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
  puts("PASS Evolution bounded aggregates outbox capacity and exact accepted duplicate ACK gate");

  using namespace fire_ai_menu;
  assert(count(Page::Main,false,0,32)==6);
  assert(at(Page::Main,3,false,0,32).kind==Kind::Evolution && at(Page::Main,4,false,0,32).kind==Kind::Settings && at(Page::Main,5,false,0,32).kind==Kind::Back);
  assert(count(Page::Main,true,15,32)==11);
  for (uint8_t i=0;i<4;++i) {const auto item=at(Page::Main,i+1,true,15,32);assert(item.kind==Kind::Build && item.index==i);}
  assert(count(Page::Apps,false,0,32)==33 && at(Page::Apps,31,false,0,32).index==31 && at(Page::Apps,32,false,0,32).kind==Kind::Back);
  assert(at(Page::Settings,4,false,0,32).kind==Kind::Voice && at(Page::Settings,6,false,0,32).kind==Kind::Back);
  assert(scroll(31,0)==28 && scroll(0,28)==0);
  static Canvas canvas;const char* labels[]={"Resume feilretting","Resume bygging","Settings","Back"};
  const char* longName="Måleappen for kjøleskap og bodelsbatteri med mange avlesninger";
  std::array<uint16_t,320*18> footer{};
  for (uint8_t selected=0;selected<4;++selected) {
    canvas.fillRect(0,0,320,240,FireUI::Bg);canvas.spans=0;
    fire_ai_menu_ui::draw(canvas,"AI DEVELOPER","Backend er tilkoblet",FireUI::Green,longName,labels,4,selected,"Velg en handling");
    assert(canvas.spans<10000);
    if (!selected) memcpy(footer.data(),canvas.pixels.data()+222*320,sizeof(footer));
    else assert(!memcmp(footer.data(),canvas.pixels.data()+222*320,sizeof(footer)));
  }
  char line[81];size_t offset=0;const size_t length=strlen(longName);
  for (uint8_t i=0;i<3 && offset<length;++i) {const size_t before=offset;offset=fire_ai_menu_ui::line(longName,length,offset,line,284,"small10");assert(offset>before && strlen(line)<=80);}
  assert(offset==length);
  const char* utf8="æøåÆØÅ æøåÆØÅ æøåÆØÅ æøåÆØÅ æøåÆØÅ æøåÆØÅ æøåÆØÅ";
  offset=0;while (offset<strlen(utf8)) {offset=fire_ai_menu_ui::line(utf8,strlen(utf8),offset,line,284);size_t at=0;uint32_t cp=0;while(at<strlen(line)) assert(fire_app_bitmap::codepoint(line,strlen(line),at,cp));}
  puts("PASS actual AI menu renderer Resume footer parity long UTF8 names independent job mapping and32app pagination");
}
