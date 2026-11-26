#pragma once
#include <stdint.h>
#include <cstring>
namespace fire_ai_menu {
// Backend work facts only: minimizing and 100 percent are not completion.
inline bool workPhase(const char* phase) {
  if (!phase) return false;
  const char* active[]={"queued","building","preparing","generating","validating","compiling","testing","reviewing","review","packaging","api_wait"};
  for (const char* value:active) if (!strcmp(phase,value)) return true;
  return false;
}
inline bool workActive(const char* status,const char* phase) {
  if (status && *status) {
    if (strcmp(status,"queued") && strcmp(status,"building") && strcmp(status,"testing")) return false;
    // An explicit terminal/waiting phase must not inherit an older active status.
    return !phase || !*phase || workPhase(phase);
  }
  return workPhase(phase);
}
inline bool stopsTrackedWork(const char* tracked,const char* received,const char* status,const char* phase) {
  return tracked && *tracked && received && !strcmp(tracked,received) && !workActive(status,phase);
}
inline bool workReady(const char* status,const char* phase,const char* package) {
  return package && *package && (status && *status? !strcmp(status,"ready") && (!phase || !*phase || !strcmp(phase,"ready")):
      phase && !strcmp(phase,"ready"));
}
inline uint32_t completionStamp(uint32_t now,uint32_t previous,bool wasReady,const char* status,const char* phase,const char* package) {
  return workReady(status,phase,package)?(wasReady?previous:now):0;
}
inline bool doneVisible(uint32_t now,uint32_t completedAt) {return completedAt && uint32_t(now-completedAt)<6000;}
enum class WorkIndicator:uint8_t {None,Build,Repair,Done};
inline WorkIndicator workIndicator(bool build,bool repair,uint32_t now,uint32_t completedAt) {
  return build?WorkIndicator::Build:repair?WorkIndicator::Repair:doneVisible(now,completedAt)?WorkIndicator::Done:WorkIndicator::None;
}

enum class Kind:uint8_t {Chat,NewApp,SelectApp,Evolution,Settings,Back,App,Runtime,Models,Usage,Limits,Voice,Connection,Jobs};
struct Item {Kind kind;uint8_t index=0;};
enum class Page:uint8_t {Main,Apps,Settings,Jobs,Job,Work};
inline uint8_t count(Page page,bool repair,uint8_t builds,uint8_t apps) {
  if (page==Page::Apps) return apps+1;
  if (page==Page::Settings) return 7;
  (void)repair;(void)builds;return 7;
}
inline Item at(Page page,uint8_t row,bool repair,uint8_t builds,uint8_t apps) {
  if (page==Page::Apps) return row<apps?Item{Kind::App,row}:Item{Kind::Back};
  if (page==Page::Settings) {
    const Kind items[]={Kind::Runtime,Kind::Models,Kind::Usage,Kind::Limits,Kind::Voice,Kind::Connection,Kind::Back};
    return {items[row<7?row:6]};
  }
  (void)repair;(void)builds;
  if (!row) return {Kind::Jobs};
  --row;
  const Kind items[]={Kind::Chat,Kind::NewApp,Kind::SelectApp,Kind::Evolution,Kind::Settings,Kind::Back};
  return {items[row<6?row:5]};
}
inline bool sameJob(const char* build,const char* repair,const char* receivedBuild,const char* receivedRepair) {
  if (build && *build) return receivedBuild && !strcmp(build,receivedBuild);
  return repair && *repair && receivedRepair && !strcmp(repair,receivedRepair);
}
inline bool autoConfirmRepair(bool requested,bool readonlyView) {return requested && !readonlyView;}
enum class OpenRoute:uint8_t {None,Repair,Build};
inline OpenRoute openRoute(bool available,const char* build,const char* repair) {
  return !available?OpenRoute::None:repair && *repair?OpenRoute::Repair:build && *build?OpenRoute::Build:OpenRoute::None;
}
enum class JobAction:uint8_t {Open,Resume,Delete,Pause,Cancel,Background,Context,Back};
inline uint8_t actions(bool work,bool resume,bool remove,bool pause,bool context,JobAction (&out)[5],bool open=false) {
  uint8_t n=0;
  if (work) {
    if (pause) out[n++]=JobAction::Pause;
    out[n++]=JobAction::Cancel;out[n++]=JobAction::Background;
    if (context) out[n++]=JobAction::Context;
  } else {
    if (open) out[n++]=JobAction::Open;
    if (resume) out[n++]=JobAction::Resume;
    if (remove) out[n++]=JobAction::Delete;
  }
  out[n++]=JobAction::Back;return n;
}
inline const char* actionLabel(JobAction action) {
  switch(action) {
    case JobAction::Open:return "Åpne jobb";
    case JobAction::Resume:return "Resume";
    case JobAction::Delete:return "Fjern fra listen";
    case JobAction::Pause:return "Pause";
    case JobAction::Cancel:return "Avbryt";
    case JobAction::Background:return "Minimer";
    case JobAction::Context:return "Gi mer kontekst";
    default:return "Back";
  }
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
