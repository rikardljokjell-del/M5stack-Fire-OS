#pragma once
#include <Arduino.h>
struct FireBackendSettingsUi {
  enum Page:uint8_t {None,Runtime,Models,Usage,Limits,Values,Proposal,Review};
  Page page=None,returnPage=None;
  String request,view="summary",role,key,snapshot,proposalId,review,selectedModel,message="Henter innstillinger";
  String ids[9],labels[9],values[9];
  uint32_t revision=0,proposalRevision=0,expiresAt=0,requestAt=0,offset=0;
  uint16_t reviewOffset=0,reviewNext=0;
  uint8_t count=0,selection=0,scroll=0;
  bool available=false,hasMore=false,confirming=false;
};
