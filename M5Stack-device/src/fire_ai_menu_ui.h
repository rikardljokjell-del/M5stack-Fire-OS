#pragma once
#include "fire_ui.h"
#include "fire_ai_menu.h"
#include <cstring>

// One layout for the AI Developer picker and all of its settings subpages.
// It is rendered by the firmware and the portable pixel/bounds regression.
namespace fire_ai_menu_ui {
// Same bounded header strip for progress and a short verified-ready notice.
template<class Surface>
void workStatus(Surface& canvas,fire_ai_menu::WorkIndicator kind,uint8_t progress) {
  using fire_ai_menu::WorkIndicator;
  if (kind==WorkIndicator::Done) {
    FireUI::text(canvas,112,17,"Done",FireUI::Green,"small10",96,1);
  } else if (kind==WorkIndicator::Build || kind==WorkIndicator::Repair) {
    FireUI::roundRect(canvas,112,23,96,3,1,FireUI::Muted,false);
    const int width=progress>100?94:94*progress/100;
    canvas.fillRect(113,24,width<2?2:width,1,kind==WorkIndicator::Build?FireUI::Accent:FireUI::Amber);
  }
}

inline size_t line(const char* text,size_t length,size_t offset,char (&out)[81],int width,const char* font="ui12") {
  const size_t start=offset;size_t end=start,space=start;int advance=0;
  while (offset<length && offset-start<80) {
    const size_t before=offset;uint32_t cp=0;
    if (!fire_app_bitmap::codepoint(text,length,offset,cp)) {out[0]=0;return length;}
    if (offset-start>80) break;
    if (cp=='\n') {const size_t n=before-start;memcpy(out,text+start,n);out[n]=0;return offset;}
    const auto* glyph=fire_app_bitmap::glyph(FireUI::font(font),cp);
    if (advance+(glyph?glyph->advance:0)>width) break;
    advance+=glyph?glyph->advance:0;end=offset;if (cp==' ') space=before;
  }
  if (end<length && space>start) {end=space;offset=space+1;} else offset=end;
  if (offset<=start && offset<length) {uint32_t cp=0;fire_app_bitmap::codepoint(text,length,offset,cp);end=offset;}
  const size_t n=end-start;memcpy(out,text+start,n);out[n]=0;
  while (offset<length && text[offset]==' ') ++offset;
  return offset;
}
template<class Surface>
void proposalName(Surface& canvas,const char* actualName) {
  if (!actualName) return;
  size_t offset=0;const size_t length=strlen(actualName);char text[81];
  for (uint8_t i=0;i<3 && offset<length;++i) {
    offset=line(actualName,length,offset,text,292,"small10");
    FireUI::text(canvas,14,8+i*12,text,FireUI::Text,"small10",292);
  }
}
template<class Surface>
void draw(Surface& canvas,const char* title,const char* connection,uint16_t connectionColor,
          const char* selectedName,const char* const (&labels)[4],uint8_t rows,uint8_t selected,const char* status,const char* const* icons=nullptr) {
  FireUI::panel(canvas,8,6,304,214);
  FireUI::text(canvas,18,12,title,FireUI::Text,"ui16",284);
  FireUI::text(canvas,18,35,connection,connectionColor,"small10",284);
  if (selectedName) {
    size_t offset=0;const size_t length=strlen(selectedName);char text[81];
    for (uint8_t i=0;i<3 && offset<length;++i) {offset=line(selectedName,length,offset,text,284,"small10");FireUI::text(canvas,18,50+i*12,text,FireUI::Muted,"small10",284);}
  }
  for (uint8_t row=0;row<rows && row<4;++row) {
    const int y=92+row*27;
    if (row==selected) FireUI::roundRect(canvas,14,y-2,292,25,6,FireUI::Selected,true);
    const bool icon=icons && icons[row];
    if (icon) FireUI::icon(canvas,icons[row],22,y+1,FireUI::Accent,20);
    FireUI::text(canvas,icon?49:22,y+2,labels[row],FireUI::Text,"ui12",icon?249:276);
  }
  FireUI::text(canvas,18,205,status?status:"",FireUI::Muted,"small10",284);
  // This helper never reads or changes M5 text datum. Resume details cannot
  // shift these three fixed footer positions.
  FireUI::footer(canvas,"Forrige","Velg","Neste");
}
} // namespace fire_ai_menu_ui
