#pragma once
#include <stdint.h>
#include "fire_data_engine_contract.h"
namespace fire_data_deadline {
// A byte-bounded local hash/catalog cursor has an inactivity deadline. Network
// preparation is bounded by its total 180s. These are OS jobs, not Lua callback
// timers; no render/VM time is discounted or moved out of a callback budget.
inline bool expired(uint32_t now,uint32_t started,uint32_t progress,uint32_t limit,
                    bool localData,bool waitingForSync) {
  const uint32_t budget=waitingForSync?FireDataEngineContract::kNetworkJobTimeoutMs:limit;
  return now-(localData?progress:started)>budget;
}
} // namespace fire_data_deadline
