#pragma once
#include "fire_evolution.h"

struct FireEvolutionUi {
  enum Page:uint8_t {Menu,Settings,Autonomy,Limits,Operation,Snapshot,Proposal,Review,Strategy,Costs,Metric};
  Page page=Menu;
  String app,name,package,source,project,config,proposal,proposalId,request,view="summary";
  String message="Evolution er av",job,mandate,operation,review,selectedItem,costReview,comparisonReview,goal,context,metric,permissionRequest,permissionOperation;
  String itemIds[FireEvolutionContract::kPageItems],itemLabels[FireEvolutionContract::kPageItems],itemReviews[FireEvolutionContract::kPageItems];
  String metricIds[16],metricLabels[16];
  uint8_t metricCount=0;
  uint32_t metricOffset=0;
  bool metricHasMore=false;
  bool developer=false;
  uint32_t revision=0,proposalRevision=0,expiresAt=0,requestAt=0,offset=0;
  uint8_t selection=0,scroll=0,itemCount=0,autonomy=0;
  bool loaded=false,hasMore=false,enabled=false,consent=false,acknowledgedConsent=false,flags[5]={};
  uint32_t consentAt=0;
  uint16_t reviewOffset=0,reviewNext=0;
  Page reviewReturn=Proposal;
  // Separate correlation IDs: a telemetry authorization response never edits
  // the settings/proposal being reviewed by the user.
  String runtimeRequest,runtimeApp,policyRequest,controlRequest,controlAction,controlApp,controlJob,controlMandate;
  uint32_t controlRevision=0;
  uint32_t runtimeAt=0,policyAt=0,lastUploadAt=0,lastAttemptAt=0,controlAt=0,connectAt=0;
  bool uploadAllowed=false,uploadSent=false;
  FireEvolution::Entry upload;
};
