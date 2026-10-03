// arduino-cue ESP32-CAM ring firmware. UNTESTED ON HARDWARE.
//
// Based on the official espressif/arduino-esp32 CameraWebServer example (Apache-2.0):
//   app_httpd.cpp / camera_index.h / camera_pins.h / partitions.csv are vendored unchanged except the
//   2 lines marked "arduino-cue" in app_httpd.cpp. All upstream endpoints are kept:
//   :80  /  /status  /control?var=&val=  /capture  /bmp  ...      :81  /stream
// Added here:
//   :80  /haptic?pattern=ok|none|error|boot_fail   (laptop asks the ring to vibrate)
//   :80  /cue                                       (JSON: device info, presses, laptop reachability)
//   button GPIO13 -> POST http://LAPTOP_IP:PORT/trigger {"source":"ring","device":"esp32cam","ts":0}
//   -> vibration pattern from the response on GPIO14.
//
// Board: "AI Thinker ESP32-CAM", core "esp32" by Espressif >= 3.0. Copy secrets.example.h -> secrets.h.

#include <Arduino.h>
#include "esp_camera.h"
#include "esp_http_server.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include "board_config.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "Copy secrets.example.h to secrets.h and fill in your hotspot + LAPTOP_IP"
#endif

// ======================= EDIT THESE IF NEEDED =======================
const int BUTTON_PIN = 13;
const int MOTOR_PIN  = 14;
const int BUTTON_WIRING = 0;     // 0 = Grove/module (active HIGH), 1 = bare button to GND (pull-up, active LOW)
const unsigned long DEBOUNCE_MS = 50;
const unsigned long COOLDOWN_MS = 1500;
const uint16_t HTTP_TIMEOUT_MS = 5000;
const unsigned long HEALTH_RETRY_MS = 5000;
const unsigned long WIFI_WAIT_MS = 20000;
// ====================================================================

void startCameraServer();
void setupLedFlash();

// ---------------- haptics (non-blocking; only loop() touches the motor) ----------------
enum Pattern { P_NONE_PENDING = -1, P_SILENT = 0, P_OK, P_NOTHING, P_ERROR, P_BOOT_FAIL, P_BOOT };
volatile int pendingPattern = P_NONE_PENDING;   // set from any task, consumed in loop()

unsigned long hapSteps[8]; int hapCount = 0, hapIndex = 0; unsigned long hapStepStart = 0; bool hapActive = false;
void hapticStart(int pulses, unsigned long onMs, unsigned long gapMs = 120) {
  hapCount = 0;
  for (int i = 0; i < pulses && hapCount < 7; i++) { hapSteps[hapCount++] = onMs; if (i < pulses - 1) hapSteps[hapCount++] = gapMs; }
  hapIndex = 0; hapStepStart = millis(); hapActive = hapCount > 0;
  digitalWrite(MOTOR_PIN, hapActive ? HIGH : LOW);
}
void hapticUpdate() {
  if (!hapActive) return;
  if (millis() - hapStepStart >= hapSteps[hapIndex]) {
    hapIndex++; hapStepStart = millis();
    if (hapIndex >= hapCount) { hapActive = false; digitalWrite(MOTOR_PIN, LOW); return; }
    digitalWrite(MOTOR_PIN, (hapIndex % 2 == 0) ? HIGH : LOW);
  }
}
void playPattern(int p) {
  switch (p) {
    case P_OK:        hapticStart(1, 150); break;        // ok: 1 x 150 ms
    case P_NOTHING:   hapticStart(2, 100); break;        // none: 2 x 100 ms
    case P_ERROR:     hapticStart(1, 600); break;        // error / timeout / unreachable: 1 x 600 ms
    case P_BOOT_FAIL: hapticStart(3, 100); break;        // /health unreachable at boot: 3 pulses
    case P_BOOT:      hapticStart(1, 150); break;        // boot: 1 pulse
    default: break;                                      // busy: nothing
  }
}
int patternFromName(const String &s) {
  if (s == "ok") return P_OK;
  if (s == "none") return P_NOTHING;
  if (s == "error" || s == "timeout" || s == "unreachable") return P_ERROR;
  if (s == "boot_fail") return P_BOOT_FAIL;
  return P_SILENT;   // "busy" or unknown
}

// ---------------- laptop HTTP (runs in its own FreeRTOS task, never in loop()) ----------------
volatile bool httpBusy = false;
volatile bool laptopReachable = false;
volatile unsigned long pressCount = 0;

String laptopUrl(const char *path) { return String("http://") + LAPTOP_IP + ":" + String(LAPTOP_PORT) + path; }

String jsonField(const String &body, const char *key) {   // tiny parser: "key":"value"
  String k = String("\"") + key + "\":\"";
  int i = body.indexOf(k);
  if (i < 0) return "";
  i += k.length();
  int j = body.indexOf('"', i);
  return j < 0 ? "" : body.substring(i, j);
}

void triggerTask(void *arg) {
  unsigned long n = (unsigned long)arg;
  String status = "unreachable";
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.setConnectTimeout(HTTP_TIMEOUT_MS);
    http.setTimeout(HTTP_TIMEOUT_MS);
    if (http.begin(laptopUrl("/trigger"))) {
      http.addHeader("Content-Type", "application/json");
      int code = http.POST("{\"source\":\"ring\",\"device\":\"esp32cam\",\"ts\":0}");
      if (code == 200) {
        String body = http.getString();
        status = jsonField(body, "status");
        Serial.printf("[press #%lu] -> %s label=%s\n", n, status.c_str(), jsonField(body, "label").c_str());
        laptopReachable = true;
      } else if (code > 0) {
        status = "error";
        Serial.printf("[press #%lu] HTTP %d\n", n, code);
      } else {
        status = (code == HTTPC_ERROR_READ_TIMEOUT) ? "timeout" : "unreachable";
      }
      http.end();
    }
  }
  if (status == "unreachable" || status == "timeout") {
    laptopReachable = false;
    Serial.printf("BUTTON OK, LAPTOP UNREACHABLE (%s) -> long pulse\n", status.c_str());
  }
  pendingPattern = patternFromName(status);
  httpBusy = false;
  vTaskDelete(NULL);
}

void healthTask(void *arg) {
  for (int attempt = 1;; attempt++) {
    bool ok = false;
    if (WiFi.status() == WL_CONNECTED) {
      HTTPClient http;
      http.setConnectTimeout(3000);
      http.setTimeout(3000);
      if (http.begin(laptopUrl("/health"))) {
        ok = http.GET() == 200 && http.getString().indexOf("\"ok\":true") >= 0;
        http.end();
      }
    }
    if (ok) {
      laptopReachable = true;
      Serial.printf("laptop reachable at %s\n", laptopUrl("/health").c_str());
      if (attempt > 1) pendingPattern = P_OK;
      break;
    }
    laptopReachable = false;
    Serial.printf("laptop NOT reachable at %s (wifi=%d); retry in 5 s\n", laptopUrl("/health").c_str(), WiFi.status());
    if (!httpBusy) pendingPattern = P_BOOT_FAIL;
    vTaskDelay(HEALTH_RETRY_MS / portTICK_PERIOD_MS);
  }
  vTaskDelete(NULL);
}

// ---------------- extra HTTP endpoints on :80 (registered from app_httpd.cpp) ----------------
static esp_err_t haptic_handler(httpd_req_t *req) {
  char query[64] = {0}, pattern[16] = {0};
  if (httpd_req_get_url_query_str(req, query, sizeof(query)) != ESP_OK ||
      httpd_query_key_value(query, "pattern", pattern, sizeof(pattern)) != ESP_OK) {
    httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "use /haptic?pattern=ok|none|error");
    return ESP_FAIL;
  }
  pendingPattern = patternFromName(String(pattern));
  char out[64];
  snprintf(out, sizeof(out), "{\"ok\":true,\"pattern\":\"%s\"}", pattern);
  httpd_resp_set_type(req, "application/json");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  return httpd_resp_send(req, out, strlen(out));
}

static esp_err_t cue_handler(httpd_req_t *req) {
  char out[192];
  snprintf(out, sizeof(out), "{\"device\":\"esp32cam\",\"presses\":%lu,\"laptop_reachable\":%s,\"laptop\":\"%s:%d\",\"rssi\":%d,\"uptime_s\":%lu}",
           pressCount, laptopReachable ? "true" : "false", LAPTOP_IP, LAPTOP_PORT, WiFi.RSSI(), millis() / 1000);
  httpd_resp_set_type(req, "application/json");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  return httpd_resp_send(req, out, strlen(out));
}

void cue_register_handlers(httpd_handle_t server) {
  httpd_uri_t haptic_uri = {};
  haptic_uri.uri = "/haptic"; haptic_uri.method = HTTP_GET; haptic_uri.handler = haptic_handler;
  httpd_register_uri_handler(server, &haptic_uri);
  httpd_uri_t cue_uri = {};
  cue_uri.uri = "/cue"; cue_uri.method = HTTP_GET; cue_uri.handler = cue_handler;
  httpd_register_uri_handler(server, &cue_uri);
}

// ---------------- camera (from upstream CameraWebServer.ino, AI Thinker) ----------------
bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.frame_size = FRAMESIZE_UXGA;
  config.pixel_format = PIXFORMAT_JPEG;
  config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.jpeg_quality = 12;
  config.fb_count = 1;
  if (psramFound()) {
    config.jpeg_quality = 10;
    config.fb_count = 2;
    config.grab_mode = CAMERA_GRAB_LATEST;
  } else {
    config.frame_size = FRAMESIZE_SVGA;
    config.fb_location = CAMERA_FB_IN_DRAM;
  }
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x (check ribbon cable / power)\n", err);
    return false;
  }
  sensor_t *s = esp_camera_sensor_get();
  s->set_framesize(s, FRAMESIZE_VGA);   // 640x480: good balance of detail and frame rate over a hotspot
  return true;
}

// ---------------- setup / loop ----------------
int rawState, stableState;
unsigned long lastRawChange = 0, lastTrigger = 0;

void setup() {
  pinMode(MOTOR_PIN, OUTPUT);
  digitalWrite(MOTOR_PIN, LOW);
  pinMode(BUTTON_PIN, BUTTON_WIRING == 1 ? INPUT_PULLUP : INPUT_PULLDOWN);
  Serial.begin(115200);
  Serial.println("\narduino-cue ESP32-CAM ring (UNTESTED ON HARDWARE)");
  playPattern(P_BOOT);   // boot pulse

  bool cam = initCamera();
  if (cam) setupLedFlash();   // flash LED on GPIO4 stays OFF (led_intensity 0) unless set via /control

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  Serial.print("WiFi connecting");
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < WIFI_WAIT_MS) {
    hapticUpdate();
    delay(250);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    if (cam) startCameraServer();
    Serial.printf("Camera Ready! Use 'http://%s' to connect. Stream: http://%s:81/stream\n",
                  WiFi.localIP().toString().c_str(), WiFi.localIP().toString().c_str());
    Serial.printf("Set on laptop:  $env:ESP32_IP=\"%s\"\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("WiFi NOT connected (check secrets.h / hotspot 2.4 GHz). Button still gives local feedback.");
  }
  if (!cam) pendingPattern = P_ERROR;
  xTaskCreate(healthTask, "cue_health", 6144, NULL, 1, NULL);

  rawState = stableState = digitalRead(BUTTON_PIN);
}

void loop() {
  unsigned long now = millis();
  hapticUpdate();

  int r = digitalRead(BUTTON_PIN);
  if (r != rawState) { rawState = r; lastRawChange = now; }
  if (r != stableState && now - lastRawChange >= DEBOUNCE_MS) {
    stableState = r;
    bool pressed = (stableState == HIGH) == (BUTTON_WIRING == 0);
    if (pressed) {
      if (now - lastTrigger < COOLDOWN_MS) {
        Serial.println("press ignored (cooldown)");
      } else if (httpBusy) {
        Serial.println("press ignored (request in flight)");
      } else {
        lastTrigger = now;
        pressCount++;
        Serial.printf("BUTTON PRESSED #%lu\n", pressCount);
        httpBusy = true;
        if (xTaskCreate(triggerTask, "cue_trigger", 8192, (void *)pressCount, 1, NULL) != pdPASS) {
          httpBusy = false;
          pendingPattern = P_ERROR;
        }
      }
    }
  }

  int p = pendingPattern;
  if (p != P_NONE_PENDING) {
    pendingPattern = P_NONE_PENDING;
    playPattern(p);
  }
  delay(2);
}
