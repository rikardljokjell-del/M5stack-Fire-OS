// Lua's protected error path is compiled as C++ so it can use exceptions
// instead of pulling the ESP32 libc setjmp/longjmp implementation into IRAM.
extern "C" {
#include "ldo.c"
}
