// Shared NimBLE-Arduino configuration. This file is consumed by NimBLE's
// nimconfig.h in Arduino builds; sdkconfig does not control that path.
#define CONFIG_BT_NIMBLE_MAX_CONNECTIONS 1
#define CONFIG_BT_NIMBLE_MAX_BONDS 1
#define CONFIG_BT_NIMBLE_MAX_CCCDS 2
#define CONFIG_BT_NIMBLE_ATT_PREFERRED_MTU 23
#define CONFIG_BT_NIMBLE_MSYS1_BLOCK_COUNT 8
#define CONFIG_BT_NIMBLE_HOST_TASK_STACK_SIZE 3072
#define CONFIG_BT_NIMBLE_LOG_LEVEL 5
#define CONFIG_NIMBLE_CPP_LOG_LEVEL 0
