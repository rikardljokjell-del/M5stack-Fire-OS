#pragma once
#include <stdint.h>
// Speech/text completion must not replace an explicit app-action phase:
// 3=build confirmation,4=build/install,5=run confirmation,6=starting/running.
inline uint8_t fireConversationState(uint8_t current,uint8_t conversation) {
  return current>=3 && current<=6?current:conversation;
}
