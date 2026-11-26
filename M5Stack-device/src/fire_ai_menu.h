#pragma once
#include <stdint.h>
namespace fire_ai_menu {
enum class Kind:uint8_t {Repair,Build,Chat,NewApp,SelectApp,Evolution,Settings,Back,App,Runtime,Models,Usage,Limits,Voice,Connection};
struct Item {Kind kind;uint8_t index=0;};
enum class Page:uint8_t {Main,Apps,Settings};
inline uint8_t count(Page page,bool repair,uint8_t builds,uint8_t apps) {
  if (page==Page::Apps) return apps+1;
  if (page==Page::Settings) return 7;
  uint8_t n=repair?1:0;for (uint8_t i=0;i<4;++i) if (builds&(1u<<i)) ++n;return n+6;
}
inline Item at(Page page,uint8_t row,bool repair,uint8_t builds,uint8_t apps) {
  if (page==Page::Apps) return row<apps?Item{Kind::App,row}:Item{Kind::Back};
  if (page==Page::Settings) {
    const Kind items[]={Kind::Runtime,Kind::Models,Kind::Usage,Kind::Limits,Kind::Voice,Kind::Connection,Kind::Back};
    return {items[row<7?row:6]};
  }
  if (repair) {if (!row) return {Kind::Repair};--row;}
  for (uint8_t i=0;i<4;++i) if (builds&(1u<<i)) {if (!row) return {Kind::Build,i};--row;}
  const Kind items[]={Kind::Chat,Kind::NewApp,Kind::SelectApp,Kind::Evolution,Kind::Settings,Kind::Back};
  return {items[row<6?row:5]};
}
inline uint8_t scroll(uint8_t selection,uint8_t offset) {
  return selection<offset?selection:selection>=offset+4?selection-3:offset;
}
} // namespace fire_ai_menu
