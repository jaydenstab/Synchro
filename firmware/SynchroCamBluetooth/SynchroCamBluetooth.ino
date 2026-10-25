// ESP32-CAM (original ESP32), Arduino ESP32 core 2.0.17.
// Bluetooth Classic SPP; Wi-Fi stays off. Nano remains the USB upload bridge.
#include <Arduino.h>
#include <BluetoothSerial.h>
#include <atomic>
#include "esp_camera.h"
#include "secrets.h"

#if !defined(CONFIG_BT_SPP_ENABLED)
#error This sketch needs the original ESP32's Bluetooth Classic SPP support.
#endif

BluetoothSerial SerialBT;
const char *BT_NAME = "Synchro-Cam-BT";
bool cameraReady = false, bluetoothReady = false;
uint16_t sensorPid = 0;
uint32_t sentFrames = 0, captureFailures = 0;
std::atomic<uint8_t> bluetoothChannel{0};
std::atomic<bool> resetBluetoothCommand{false};
String usbCommand, bluetoothCommand, bluetoothAddress;

String statusJson() {
  char buffer[448];
  snprintf(buffer, sizeof(buffer),
    "{\"firmware\":\"bluetooth-2\",\"camera_ready\":%s,\"bluetooth_ready\":%s,\"bt_client\":%s,\"bt_name\":\"%s\",\"bt_address\":\"%s\",\"bt_channel\":%u,\"sensor\":\"0x%04X\",\"width\":640,\"height\":480,\"frames\":%lu,\"capture_failures\":%lu,\"free_heap\":%u,\"uptime_ms\":%lu}",
    cameraReady ? "true" : "false", bluetoothReady ? "true" : "false",
    SerialBT.hasClient() ? "true" : "false", BT_NAME, bluetoothAddress.c_str(),
    bluetoothChannel.load(), sensorPid, static_cast<unsigned long>(sentFrames),
    static_cast<unsigned long>(captureFailures), ESP.getFreeHeap(), millis());
  return String(buffer);
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
  config.frame_size = FRAMESIZE_VGA;
  config.jpeg_quality = 16;
  config.fb_count = psramFound() ? 2 : 1;
  config.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
  config.grab_mode = CAMERA_GRAB_LATEST;
  esp_err_t result = esp_camera_init(&config);
  if (result != ESP_OK) { Serial.printf("CAMERA_ERROR 0x%X\n", result); return false; }
  sensor_t *sensor = esp_camera_sensor_get();
  sensorPid = sensor->id.PID;
  if (sensorPid == OV3660_PID) {
    sensor->set_vflip(sensor, 1);
    sensor->set_brightness(sensor, 1);
    sensor->set_saturation(sensor, -2);
  }
  return true;
}

void sendPhoto(Print &output) {
  camera_fb_t *frame = cameraReady ? esp_camera_fb_get() : nullptr;
  if (!frame || frame->format != PIXFORMAT_JPEG || frame->len < 4 ||
      frame->buf[0] != 0xFF || frame->buf[1] != 0xD8 ||
      frame->buf[frame->len - 2] != 0xFF || frame->buf[frame->len - 1] != 0xD9) {
    if (frame) esp_camera_fb_return(frame);
    captureFailures++;
    output.println("CAPTURE_ERROR");
    return;
  }
  char header[80];
  int headerSize = snprintf(header, sizeof(header), "JPEG_BEGIN %u %u %u\n",
    static_cast<unsigned>(frame->len), static_cast<unsigned>(frame->width), static_cast<unsigned>(frame->height));
  const char tail[] = "\nJPEG_END\n";
  // Queue one complete response, so header/body/trailer cannot interleave.
  size_t packetSize = headerSize + frame->len + sizeof(tail) - 1;
  uint8_t *packet = static_cast<uint8_t *>(ps_malloc(packetSize));
  if (!packet) packet = static_cast<uint8_t *>(malloc(packetSize));
  if (!packet) {
    esp_camera_fb_return(frame); captureFailures++;
    output.println("CAPTURE_ERROR"); return;
  }
  memcpy(packet, header, headerSize);
  memcpy(packet + headerSize, frame->buf, frame->len);
  memcpy(packet + headerSize + frame->len, tail, sizeof(tail) - 1);
  esp_camera_fb_return(frame);
  if (output.write(packet, packetSize) == packetSize) sentFrames++;
  else captureFailures++;
  free(packet);
}

void processCommands(Stream &input, String &command) {
  // The viewer waits for each response before asking for another image.
  while (input.available() > 0) {
    char c = static_cast<char>(input.read());
    if (c == '\n') {
      command.trim();
      if (command == "STATUS") input.println(statusJson());
      else if (command == "CAPTURE") sendPhoto(input);
      else if (command.length()) input.println("UNKNOWN_COMMAND");
      command = "";
      break;
    } else if (c != '\r') {
      if (command.length() < 32) command += c;
      else command = "";
    }
  }
}

void onBluetoothEvent(esp_spp_cb_event_t event, esp_spp_cb_param_t *param) {
  if (event == ESP_SPP_START_EVT) bluetoothChannel = param->start.scn;
  if (event == ESP_SPP_CLOSE_EVT || event == ESP_SPP_SRV_OPEN_EVT) resetBluetoothCommand = true;
}

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(false);
  pinMode(4, OUTPUT); digitalWrite(4, LOW);
  delay(300);
  Serial.println("\nSYNCHRO_CAM_BLUETOOTH_BOOT v2");
  cameraReady = startCamera();
  SerialBT.register_callback(onBluetoothEvent);
  SerialBT.onAuthComplete([](boolean success) { Serial.printf("BT_AUTH %s\n", success ? "true" : "false"); });
  bluetoothReady = SerialBT.begin(BT_NAME);
  if (bluetoothReady) {
    SerialBT.setPin(BT_PAIRING_PIN);
    bluetoothAddress = SerialBT.getBtAddressString();
  }
  Serial.println(statusJson());
  Serial.println("COMMANDS STATUS CAPTURE");
}

void loop() {
  if (resetBluetoothCommand.exchange(false)) bluetoothCommand = "";
  processCommands(Serial, usbCommand);
  if (bluetoothReady) processCommands(SerialBT, bluetoothCommand);
  delay(1);
}
