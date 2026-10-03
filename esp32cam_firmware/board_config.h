#ifndef BOARD_CONFIG_H
#define BOARD_CONFIG_H
// arduino-cue: fixed to the AI Thinker ESP32-CAM (OV2640, has PSRAM).
// Upstream: espressif/arduino-esp32 libraries/ESP32/examples/Camera/CameraWebServer/board_config.h
#define CAMERA_MODEL_AI_THINKER  // Has PSRAM
#include "camera_pins.h"
#endif  // BOARD_CONFIG_H
