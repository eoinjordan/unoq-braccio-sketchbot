// ESP-EYE camera bridge for the UNO Q sketchbot.
//
// Shares JPEG frames with the UNO Q two ways, so it can replace the wrist USB
// webcam:
//   * Wi-Fi  : HTTP  GET /capture -> one JPEG,  GET /stream -> MJPEG,  GET / -> status
//   * USB    : plug the ESP-EYE micro-USB into the UNO Q USB-C; the board shows
//              up as a serial port and answers a tiny request/response protocol
//              (send 'C' -> get one framed JPEG). No Wi-Fi needed.
//
// Face detection runs on the UNO Q (the sketchbot's portrait pipeline); this
// firmware's job is to deliver clean frames reliably over whichever link is up.
//
// Board: "ESP32 Wrover Module" (or "ESP32 Dev Module" with PSRAM: Enabled).
// Partition: "Huge APP (3MB No OTA)". See README.md for flashing steps.

#include "esp_camera.h"
#include "esp_http_server.h"
#include "esp_timer.h"
#include <WiFi.h>
#include <ESPmDNS.h>

// ---- Wi-Fi credentials -----------------------------------------------------
// Put these in a secrets.h next to this sketch (git-ignored), or edit here.
// Leave WIFI_SSID empty ("") to run USB-only with no Wi-Fi.
#if __has_include("secrets.h")
#include "secrets.h"
#endif
#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif
#ifndef WIFI_PASS
#define WIFI_PASS ""
#endif
#ifndef HOSTNAME
#define HOSTNAME "esp-eye"   // reachable as http://esp-eye.local/ (mDNS)
#endif

// ---- Camera: ESP-EYE (ESP32) pin map ---------------------------------------
#define PWDN_GPIO_NUM -1
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 4
#define SIOD_GPIO_NUM 18
#define SIOC_GPIO_NUM 23
#define Y9_GPIO_NUM 36
#define Y8_GPIO_NUM 37
#define Y7_GPIO_NUM 38
#define Y6_GPIO_NUM 39
#define Y5_GPIO_NUM 35
#define Y4_GPIO_NUM 14
#define Y3_GPIO_NUM 13
#define Y2_GPIO_NUM 34
#define VSYNC_GPIO_NUM 5
#define HREF_GPIO_NUM 27
#define PCLK_GPIO_NUM 25

// ---- Tunables --------------------------------------------------------------
#define SERIAL_BAUD 921600          // USB frame link speed
#define FRAME_SIZE FRAMESIZE_SVGA   // 800x600; VGA/HD also fine for face capture
#define JPEG_QUALITY 12             // 10 (better) .. 30 (smaller); lower = larger
#define VFLIP 0                     // set 1 if the image is upside down
#define HMIRROR 0                   // set 1 to mirror left/right

// Serial frame framing: 0xA5 0x5A | len (4 bytes, little-endian) | JPEG bytes.
static const uint8_t FRAME_MAGIC0 = 0xA5;
static const uint8_t FRAME_MAGIC1 = 0x5A;

static httpd_handle_t http_server = NULL;
static bool wifi_up = false;

// ---- Camera init -----------------------------------------------------------
static bool startCamera() {
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
  config.frame_size = FRAME_SIZE;
  config.pixel_format = PIXFORMAT_JPEG;
  config.grab_mode = CAMERA_GRAB_LATEST;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.jpeg_quality = JPEG_QUALITY;
  config.fb_count = 1;

  // ESP-EYE has 8MB PSRAM: double-buffer for smoother capture/stream.
  if (psramFound()) {
    config.jpeg_quality = JPEG_QUALITY;
    config.fb_count = 2;
    config.grab_mode = CAMERA_GRAB_LATEST;
  } else {
    config.frame_size = FRAMESIZE_VGA;
    config.fb_location = CAMERA_FB_IN_DRAM;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("INFO camera init failed: 0x%x\n", err);
    return false;
  }

  sensor_t *s = esp_camera_sensor_get();
  if (s) {
    if (VFLIP) s->set_vflip(s, 1);
    if (HMIRROR) s->set_hmirror(s, 1);
    s->set_brightness(s, 1);
    s->set_saturation(s, 0);
  }
  return true;
}

// ---- HTTP handlers (Wi-Fi) -------------------------------------------------
static esp_err_t capture_handler(httpd_req_t *req) {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }
  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Content-Disposition", "inline; filename=capture.jpg");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  esp_err_t res = httpd_resp_send(req, (const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);
  return res;
}

#define PART_BOUNDARY "frameboundary"
static const char *STREAM_CONTENT_TYPE =
    "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char *STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char *STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

static esp_err_t stream_handler(httpd_req_t *req) {
  esp_err_t res = httpd_resp_set_type(req, STREAM_CONTENT_TYPE);
  if (res != ESP_OK) return res;
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

  char part_buf[64];
  while (true) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      res = ESP_FAIL;
    } else {
      size_t hlen = snprintf(part_buf, sizeof(part_buf), STREAM_PART, fb->len);
      res = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY));
      if (res == ESP_OK)
        res = httpd_resp_send_chunk(req, part_buf, hlen);
      if (res == ESP_OK)
        res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
      esp_camera_fb_return(fb);
    }
    if (res != ESP_OK) break;  // client disconnected
  }
  return res;
}

static esp_err_t index_handler(httpd_req_t *req) {
  char html[512];
  snprintf(html, sizeof(html),
           "<!doctype html><meta charset=utf-8><title>ESP-EYE</title>"
           "<body style='font-family:sans-serif'>"
           "<h2>ESP-EYE sketchbot camera</h2>"
           "<p>IP: %s &nbsp; mDNS: %s.local</p>"
           "<p><a href='/capture'>/capture</a> (single JPEG) &middot; "
           "<a href='/stream'>/stream</a> (MJPEG)</p>"
           "<img src='/stream' style='max-width:100%%;border:1px solid #ccc'>"
           "</body>",
           WiFi.localIP().toString().c_str(), HOSTNAME);
  httpd_resp_set_type(req, "text/html");
  return httpd_resp_send(req, html, strlen(html));
}

static void startHttp() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;
  config.ctrl_port = 32768;
  if (httpd_start(&http_server, &config) != ESP_OK) {
    Serial.println("INFO http start failed");
    return;
  }
  httpd_uri_t index_uri = {"/", HTTP_GET, index_handler, NULL};
  httpd_uri_t capture_uri = {"/capture", HTTP_GET, capture_handler, NULL};
  httpd_uri_t stream_uri = {"/stream", HTTP_GET, stream_handler, NULL};
  httpd_register_uri_handler(http_server, &index_uri);
  httpd_register_uri_handler(http_server, &capture_uri);
  httpd_register_uri_handler(http_server, &stream_uri);
}

// ---- Wi-Fi -----------------------------------------------------------------
static void startWifi() {
  if (strlen(WIFI_SSID) == 0) {
    Serial.println("INFO no WIFI_SSID set - running USB-only");
    return;
  }
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("INFO connecting to Wi-Fi '%s'", WIFI_SSID);
  uint32_t deadline = millis() + 20000;
  while (WiFi.status() != WL_CONNECTED && millis() < deadline) {
    delay(300);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    wifi_up = true;
    Serial.printf("INFO Wi-Fi up: http://%s/  (http://%s.local/)\n",
                  WiFi.localIP().toString().c_str(), HOSTNAME);
    if (MDNS.begin(HOSTNAME)) MDNS.addService("http", "tcp", 80);
    startHttp();
  } else {
    Serial.println("INFO Wi-Fi failed - running USB-only");
  }
}

// ---- USB serial frame protocol --------------------------------------------
static void sendSerialFrame() {
  camera_fb_t *fb = esp_camera_fb_get();
  uint32_t len = fb ? fb->len : 0;
  uint8_t header[6] = {FRAME_MAGIC0, FRAME_MAGIC1, (uint8_t)(len), (uint8_t)(len >> 8),
                       (uint8_t)(len >> 16), (uint8_t)(len >> 24)};
  Serial.write(header, sizeof(header));  // len == 0 signals "no frame"
  if (fb) {
    Serial.write(fb->buf, fb->len);
    esp_camera_fb_return(fb);
  }
  Serial.flush();
}

static void sendSerialInfo() {
  Serial.printf("INFO esp-eye ready wifi=%s ip=%s\n", wifi_up ? "up" : "off",
                wifi_up ? WiFi.localIP().toString().c_str() : "-");
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  Serial.setDebugOutput(false);
  delay(100);

  // ESP-EYE needs these pulled up for the camera bus to enumerate.
  pinMode(13, INPUT_PULLUP);
  pinMode(14, INPUT_PULLUP);

  if (!startCamera()) {
    // Keep answering serial so the host sees the error instead of a dead port.
    Serial.println("INFO camera init failed - check the ribbon/board");
  }
  startWifi();
  Serial.println("INFO ready ('C'=capture over USB)");
}

void loop() {
  if (Serial.available()) {
    int c = Serial.read();
    if (c == 'C' || c == 'c')
      sendSerialFrame();
    else if (c == 'I' || c == 'i')
      sendSerialInfo();
    // any other byte (newline, whitespace, noise) is ignored
  }
  delay(1);
}
