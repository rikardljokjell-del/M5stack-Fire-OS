#pragma once
#include <stdint.h>
#include <cstring>
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
// A received proposal belongs to this project, or to the exact selected
// server-owned cohort job. A cross-project target must have its actual name.
// Opening never confirms a build or changes the backend's app selection.
inline bool canOpenProposal(uint8_t workflow,const char* proposal,const char* project,const char* selectedProject,
    const char* proposalJob=nullptr,const char* selectedJob=nullptr,const char* targetName=nullptr) {
  if (workflow!=3 || !proposal || !*proposal || !project || !*project || !selectedProject || !*selectedProject) return false;
  if (!strcmp(project,selectedProject)) return true;
  return proposalJob && *proposalJob && selectedJob && *selectedJob && !strcmp(proposalJob,selectedJob) && targetName && *targetName;
}
enum class EvolutionTail:uint8_t {Main,Permissions,Proposal,Back};
inline uint8_t evolutionCount(bool permissions,bool proposal) {return 15+(permissions?1:0)+(proposal?1:0);}
inline EvolutionTail evolutionTail(uint8_t row,bool permissions,bool proposal) {
  if (row<14) return EvolutionTail::Main;
  row-=14;
  if (permissions) {if (!row) return EvolutionTail::Permissions;--row;}
  if (proposal && !row) return EvolutionTail::Proposal;
  return EvolutionTail::Back; // stale removed rows must never become Stop
}
inline uint8_t scroll(uint8_t selection,uint8_t offset) {
  return selection<offset?selection:selection>=offset+4?selection-3:offset;
}
} // namespace fire_ai_menu
