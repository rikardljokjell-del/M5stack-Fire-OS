#pragma once
#include <stdlib.h>
constexpr int MALLOC_CAP_SPIRAM=1;
constexpr int MALLOC_CAP_8BIT=2;
inline void* heap_caps_realloc(void* value,size_t bytes,int) {return realloc(value,bytes);}
inline void heap_caps_free(void* value) {free(value);}
