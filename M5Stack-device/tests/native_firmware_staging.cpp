#include "fire_firmware_staging.h"
#include <assert.h>
#include <stdio.h>
#include <stdint.h>

struct Hash {
  size_t bytes = 0;
  bool fail = false;
  int update(const unsigned char*, size_t size) { bytes += size; return fail ? -1 : 0; }
};

int main() {
  assert(!FireFirmwareStaging::fits(0,100,100,100,10));
  assert(!FireFirmwareStaging::fits(101,100,200,200,10));
  assert(!FireFirmwareStaging::fits(90,100,100,89,10)); // fragmentation
  assert(!FireFirmwareStaging::fits(91,100,100,100,10)); // preserve reserve
  assert(!FireFirmwareStaging::fits(SIZE_MAX,100,SIZE_MAX,SIZE_MAX,10));
  assert(FireFirmwareStaging::fits(90,100,100,100,10));
  unsigned char storage[5] = {0,0,0,0,0x7a};
  const unsigned char input[] = {1,0,2,3};
  FireFirmwareStaging stage; Hash hash;
  stage.attach(storage,4);
  assert(!stage.readyForSd(false));
  assert(stage.append(hash,input,2));
  assert(!stage.verify(true)); // signed length not yet complete
  assert(!stage.append(hash,input,3)); // overflow; do not hash or copy
  assert(hash.bytes==2 && stage.received()==2 && storage[4]==0x7a);
  assert(stage.append(hash,input+2,2));
  assert(!stage.verify(false)); // corrupted network hash
  assert(!stage.readyForSd(false));
  assert(stage.verify(true));
  assert(!stage.readyForSd(true)); // TLS worker still owns socket/stack
  assert(stage.readyForSd(false));
  assert(!stage.append(hash,input,1)); // verified bytes cannot change
  assert(storage[0]==1 && storage[1]==0 && storage[2]==2 && storage[3]==3 && storage[4]==0x7a);
  stage.attach(storage,4); hash.fail=true;
  assert(!stage.append(hash,input,4) && stage.received()==0 && !stage.verify(true));
  stage.attach(nullptr,0);
  assert(!stage.append(hash,input,1) && !stage.readyForSd(false));
  puts("PASS actual firmware PSRAM bounds and TLS/SD phase guards");
}
