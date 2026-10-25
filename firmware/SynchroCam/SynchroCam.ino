// Camera bring-up for Inland / AI-Thinker ESP32-CAM (ESP32, not ESP32-S3).
// Pin map: Espressif's CameraWebServer example, CAMERA_MODEL_AI_THINKER.
// https://github.com/espressif/arduino-esp32/tree/2.0.17/libraries/ESP32/examples/Camera/CameraWebServer
#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <StreamString.h>
#include <atomic>
#include "esp_camera.h"
#include "esp_http_server.h"
#include "secrets.h"

bool cameraReady = false;
bool webReady = false;
uint16_t sensorPid = 0;
std::atomic<uint32_t> capturedFrames{0};
std::atomic<uint32_t> lastCaptureMs{0};
std::atomic<uint32_t> lastSendMs{0};
std::atomic<uint32_t> lastJpegBytes{0};
std::atomic<uint32_t> sendFailures{0};
httpd_handle_t webServer = nullptr;
httpd_handle_t streamServer = nullptr;
String serialCommand;

const char PAGE[] PROGMEM = R"HTML(<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Synchro Camera</title><style>
body{margin:0;background:#10181c;color:#eaf1ee;font:16px system-ui,sans-serif}main{max-width:900px;margin:auto;padding:32px 20px}
h1{font-size:32px;margin-bottom:8px}p{color:#aec1b9}section{background:#1a262b;border:1px solid #34443f;border-radius:14px;padding:20px}
button,a{display:inline-block;font:inherit;border:0;border-radius:8px;padding:11px 16px;margin:5px 8px 5px 0;background:#b5e5ca;color:#16291f;text-decoration:none;cursor:pointer}
button:disabled{opacity:.5;cursor:default}img{display:none;width:100%;height:auto;margin-top:16px;border-radius:8px}#status{font-size:14px}small{color:#aec1b9}
</style></head><body><main><small>SYNCHRO / CAMERA TEST</small><h1>Your camera, live.</h1>
<p>This page connects directly to your ESP32-CAM. Video stays on this local network.</p>
<section><div id="status">Checking camera...</div><p><button id="start" disabled>Start live view</button><button id="stop" disabled>Stop</button><a href="/capture" target="_blank" rel="noopener">Take a photo</a></p>
<img id="video" alt="Live image from the ESP32-CAM"><p id="hint">Press Start live view to see the camera.</p></section>
<p>Keep the board powered while viewing. The camera Wi-Fi network does not provide internet.</p></main>
<script>
const video=document.querySelector('#video'),start=document.querySelector('#start'),stop=document.querySelector('#stop'),hint=document.querySelector('#hint');
let generation=0,activeRequest=null,displayedUrl=null,viewerTask=Promise.resolve();
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function stopVideo(message='Live view stopped.'){
  generation++;
  if(activeRequest)activeRequest.abort();
  activeRequest=null;
  video.removeAttribute('src');video.style.display='none';
  if(displayedUrl)URL.revokeObjectURL(displayedUrl);
  displayedUrl=null;start.disabled=false;stop.disabled=true;hint.textContent=message;
}
function startVideo(){
  const run=++generation;
  start.disabled=true;stop.disabled=false;hint.textContent='Connecting...';
  // Let a cancelled request settle before a rapid Stop/Start opens another.
  viewerTask=viewerTask.catch(()=>{}).then(()=>runViewer(run));
  return viewerTask;
}
async function runViewer(run){
  let shown=0,windowStart=performance.now(),measured=false;
  while(run===generation){
    const began=performance.now(),controller=new AbortController();
    activeRequest=controller;
    const timeout=setTimeout(()=>controller.abort(),2500);
    let nextUrl=null,retry=false;
    try{
      // Wait for each complete image before asking for another. No video backlog.
      const response=await fetch('/capture',{cache:'no-store',signal:controller.signal});
      if(!response.ok)throw new Error('Camera unavailable');
      const blob=await response.blob();
      if(run!==generation)break;
      nextUrl=URL.createObjectURL(blob);
      const decoded=new Image();decoded.src=nextUrl;await decoded.decode();
      if(run!==generation)break;
      const previous=displayedUrl;displayedUrl=nextUrl;nextUrl=null;
      video.src=displayedUrl;video.style.display='block';
      if(previous)URL.revokeObjectURL(previous);
      shown++;
      const now=performance.now(),elapsed=now-windowStart;
      if(elapsed>=1000){hint.textContent='Live · '+(shown*1000/elapsed).toFixed(1)+' fps · '+Math.round(now-began)+' ms per image';shown=0;windowStart=now;measured=true;}
      else if(shown===1&&!measured)hint.textContent='Live view running.';
    }catch(error){
      if(run!==generation)break;
      hint.textContent='Connection slow — retrying. Keep this page open near the camera.';retry=true;
    }finally{
      clearTimeout(timeout);
      if(nextUrl)URL.revokeObjectURL(nextUrl);
      if(activeRequest===controller)activeRequest=null;
    }
    if(run===generation)await wait(retry?400:Math.max(0,50-(performance.now()-began)));
  }
}
start.onclick=startVideo;stop.onclick=()=>stopVideo();
window.addEventListener('pagehide',()=>stopVideo());
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopVideo('Paused. Press Start live view to resume.');});
fetch('/status',{cache:'no-store'}).then(r=>r.json()).then(s=>{document.querySelector('#status').textContent=(s.camera_ready?'Camera ready':'Camera unavailable')+' · '+s.sensor+' · '+s.width+' × '+s.height;start.disabled=!s.camera_ready}).catch(()=>document.querySelector('#status').textContent='Cannot reach the camera. Reconnect to its Wi-Fi and reload.');
</script></body></html>)HTML";

String statusJson() {
  char buffer[512];
  snprintf(buffer, sizeof(buffer),
    "{\"firmware\":2,\"camera_ready\":%s,\"http_ready\":%s,\"sensor\":\"0x%04X\",\"psram_bytes\":%u,\"free_heap\":%u,\"frames\":%u,\"uptime_ms\":%lu,\"ip\":\"%s\",\"width\":320,\"height\":240,\"clients\":%u,\"capture_ms\":%u,\"send_ms\":%u,\"jpeg_bytes\":%u,\"send_failures\":%u}",
    cameraReady ? "true" : "false", webReady ? "true" : "false", sensorPid,
    ESP.getPsramSize(), ESP.getFreeHeap(), capturedFrames.load(), millis(), WiFi.softAPIP().toString().c_str(),
    WiFi.softAPgetStationNum(), lastCaptureMs.load(), lastSendMs.load(), lastJpegBytes.load(), sendFailures.load());
  return String(buffer);
}

bool validJpeg(camera_fb_t *frame) {
  return frame && frame->format == PIXFORMAT_JPEG && frame->len >= 4 &&
    frame->buf[0] == 0xFF && frame->buf[1] == 0xD8 &&
    frame->buf[frame->len - 2] == 0xFF && frame->buf[frame->len - 1] == 0xD9;
}

esp_err_t rootHandler(httpd_req_t *request) {
  httpd_resp_set_type(request, "text/html; charset=utf-8");
  httpd_resp_set_hdr(request, "Cache-Control", "no-store");
  return httpd_resp_send(request, PAGE, HTTPD_RESP_USE_STRLEN);
}

esp_err_t statusHandler(httpd_req_t *request) {
  httpd_resp_set_type(request, "application/json");
  httpd_resp_set_hdr(request, "Cache-Control", "no-store");
  String payload = statusJson();
  return httpd_resp_send(request, payload.c_str(), payload.length());
}

esp_err_t captureHandler(httpd_req_t *request) {
  uint32_t began = millis();
  camera_fb_t *frame = cameraReady ? esp_camera_fb_get() : nullptr;
  lastCaptureMs = millis() - began;
  if (!validJpeg(frame)) {
    if (frame) esp_camera_fb_return(frame);
    return httpd_resp_send_err(request, HTTPD_500_INTERNAL_SERVER_ERROR, "Camera capture failed");
  }
  httpd_resp_set_type(request, "image/jpeg");
  httpd_resp_set_hdr(request, "Cache-Control", "no-store");
  lastJpegBytes = frame->len;
  began = millis();
  esp_err_t result = httpd_resp_send(request, reinterpret_cast<const char *>(frame->buf), frame->len);
  lastSendMs = millis() - began;
  if (result == ESP_OK) capturedFrames++;
  else sendFailures++;
  esp_camera_fb_return(frame);
  return result;
}

esp_err_t streamHandler(httpd_req_t *request) {
  if (!cameraReady) return httpd_resp_send_err(request, HTTPD_500_INTERNAL_SERVER_ERROR, "Camera unavailable");
  httpd_resp_set_type(request, "multipart/x-mixed-replace;boundary=synchro-frame");
  httpd_resp_set_hdr(request, "Cache-Control", "no-store");
  while (true) {
    camera_fb_t *frame = esp_camera_fb_get();
    if (!validJpeg(frame)) {
      if (frame) esp_camera_fb_return(frame);
      return ESP_FAIL;
    }
    char header[128];
    int length = snprintf(header, sizeof(header), "\r\n--synchro-frame\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n", static_cast<unsigned>(frame->len));
    esp_err_t result = httpd_resp_send_chunk(request, header, length);
    if (result == ESP_OK) result = httpd_resp_send_chunk(request, reinterpret_cast<const char *>(frame->buf), frame->len);
    esp_camera_fb_return(frame);
    if (result != ESP_OK) return result;
    capturedFrames++;
    delay(1);  // Yield without the initial test's artificial 100 ms delay.
  }
}

bool startWebServers() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;
  config.max_uri_handlers = 4;
  config.lru_purge_enable = true;
  config.send_wait_timeout = 2;
  config.recv_wait_timeout = 2;
  if (httpd_start(&webServer, &config) != ESP_OK) return false;

  httpd_uri_t root = {};
  root.uri = "/"; root.method = HTTP_GET; root.handler = rootHandler;
  httpd_uri_t status = {};
  status.uri = "/status"; status.method = HTTP_GET; status.handler = statusHandler;
  httpd_uri_t capture = {};
  capture.uri = "/capture"; capture.method = HTTP_GET; capture.handler = captureHandler;
  if (httpd_register_uri_handler(webServer, &root) != ESP_OK ||
      httpd_register_uri_handler(webServer, &status) != ESP_OK ||
      httpd_register_uri_handler(webServer, &capture) != ESP_OK) return false;

  config.server_port = 81;
  config.ctrl_port += 1;
  if (httpd_start(&streamServer, &config) != ESP_OK) return false;
  httpd_uri_t stream = {};
  stream.uri = "/stream"; stream.method = HTTP_GET; stream.handler = streamHandler;
  return httpd_register_uri_handler(streamServer, &stream) == ESP_OK;
}

bool startCamera() {
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = 5; config.pin_d1 = 18; config.pin_d2 = 19; config.pin_d3 = 21;
  config.pin_d4 = 36; config.pin_d5 = 39; config.pin_d6 = 34; config.pin_d7 = 35;
  config.pin_xclk = 0; config.pin_pclk = 22; config.pin_vsync = 25; config.pin_href = 23;
  config.pin_sccb_sda = 26; config.pin_sccb_scl = 27;
  config.pin_pwdn = 32; config.pin_reset = -1;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_QVGA;
  config.jpeg_quality = 16;
  config.fb_count = psramFound() ? 2 : 1;
  config.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
  config.grab_mode = CAMERA_GRAB_LATEST;
  esp_err_t result = esp_camera_init(&config);
  if (result != ESP_OK) {
    Serial.printf("CAMERA_ERROR 0x%X\n", result);
    return false;
  }
  sensor_t *sensor = esp_camera_sensor_get();
  sensorPid = sensor->id.PID;
  if (sensorPid == OV3660_PID) {
    sensor->set_vflip(sensor, 1);
    sensor->set_brightness(sensor, 1);
    sensor->set_saturation(sensor, -2);
  }
  return true;
}

void sendSerialPhoto() {
  camera_fb_t *frame = cameraReady ? esp_camera_fb_get() : nullptr;
  if (!validJpeg(frame)) {
    if (frame) esp_camera_fb_return(frame);
    Serial.println("CAPTURE_ERROR");
    return;
  }
  Serial.printf("JPEG_BEGIN %u %u %u\n", static_cast<unsigned>(frame->len), static_cast<unsigned>(frame->width), static_cast<unsigned>(frame->height));
  Serial.write(frame->buf, frame->len);
  Serial.println("\nJPEG_END");
  capturedFrames++;
  esp_camera_fb_return(frame);
}

void httpSelfTest() {
  // Exercises the actual handlers over TCP locally; an external Wi-Fi
  // client is still needed to verify wireless reception and its browser.
  const char *paths[] = {"/", "/status", "/capture"};
  for (const char *path : paths) {
    HTTPClient client;
    client.setTimeout(7000);
    client.begin(String("http://") + WiFi.softAPIP().toString() + path);
    int code = client.GET();
    int length = client.getSize();
    if (code == 200 && length > 0) {
      StreamString body;
      int bytes = client.writeToStream(&body);
      bool valid = bytes == length;
      if (String(path) == "/capture") valid = valid && body.length() >= 4 && static_cast<uint8_t>(body[0]) == 0xFF && static_cast<uint8_t>(body[1]) == 0xD8;
      Serial.printf("HTTP_TEST %s code=%d bytes=%d valid=%s\n", path, code, bytes, valid ? "true" : "false");
    } else {
      Serial.printf("HTTP_TEST %s code=%d bytes=%d valid=false\n", path, code, length);
    }
    client.end();
  }
}

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(false);
  Serial.setTimeout(100);
  pinMode(4, OUTPUT);
  digitalWrite(4, LOW);  // Leave the bright flash LED off.
  delay(300);
  Serial.println("\nSYNCHRO_CAM_BOOT v2");
  cameraReady = startCamera();
  WiFi.mode(WIFI_AP);
  bool apReady = WiFi.softAP(AP_SSID, AP_PASSWORD, 6, false, 2);
  if (apReady) webReady = startWebServers();
  Serial.printf("AP_READY %s ssid=%s ip=%s\n", apReady ? "true" : "false", AP_SSID, WiFi.softAPIP().toString().c_str());
  Serial.println(statusJson());
  Serial.println("COMMANDS STATUS CAPTURE HTTPTEST");
}

void loop() {
  while (Serial.available() > 0) {
    char c = static_cast<char>(Serial.read());
    if (c == '\n') {
      serialCommand.trim();
      if (serialCommand == "STATUS") Serial.println(statusJson());
      else if (serialCommand == "CAPTURE") sendSerialPhoto();
      else if (serialCommand == "HTTPTEST") httpSelfTest();
      serialCommand = "";
    } else if (c != '\r') {
      if (serialCommand.length() < 32) serialCommand += c;
      else serialCommand = "";
    }
  }
  delay(10);
}
