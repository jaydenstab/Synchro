// ESP32-CAM (original ESP32), Arduino ESP32 core 2.0.17.
// Bluetooth Classic SPP; Wi-Fi stays off. Nano remains the USB upload bridge.
#include <Arduino.h>
#include <BluetoothSerial.h>
#include <atomic>
#include <cstring>
#include "esp_bt.h"
#include "esp_gap_bt_api.h"
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
std::atomic<bool> releaseClient{false};
std::atomic<bool> reopenRadio{false};
std::atomic<bool> announceOpen{false};
std::atomic<bool> announceClose{false};
std::atomic<uint32_t> lastRxMs{0};
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
  // 0 is largest, 63 is smallest. 24 stays at 640x480 and keeps a settled
  // indoor frame from growing into a one-second transfer.
  config.jpeg_quality = 24;
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
    // -2..2. One step above the driver default; denoise 0 keeps edges from being smoothed away.
    if (sensor->set_sharpness) sensor->set_sharpness(sensor, 1);
    if (sensor->set_denoise) sensor->set_denoise(sensor, 0);
  }
  // Automatic gain otherwise climbs for several seconds and the JPEG swells.
  // The first frames stay near 4–5 fps; later frames then fall toward 1 fps.
  if (sensor->set_gainceiling) sensor->set_gainceiling(sensor, GAINCEILING_16X);
  return true;
}

bool writeAll(Print &output, const uint8_t *data, size_t length) {
  // BluetoothSerial mallocs each write in internal RAM, then sends it in
  // 330-byte pieces. One full-frame copy fragments that heap once exposure
  // settles. Small chunks are freed as the radio drains them.
  const size_t chunk = 512;
  while (length > 0) {
    size_t step = length < chunk ? length : chunk;
    size_t wrote = output.write(data, step);
    if (wrote == 0) return false;
    data += wrote;
    length -= wrote;
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
  // Each chunk is copied by BluetoothSerial. Return this buffer once those
  // copies are queued so the other buffer can keep capturing.
  bool ok = writeAll(output, reinterpret_cast<const uint8_t *>(header), headerSize)
      && writeAll(output, frame->buf, frame->len)
      && writeAll(output, reinterpret_cast<const uint8_t *>(tail), sizeof(tail) - 1);
  esp_camera_fb_return(frame);
  if (ok) {
    sentFrames++;
    lastRxMs.store(millis());
  } else {
    captureFailures++;
    // A failed send usually means the laptop is already gone. This stack
    // keeps that one client slot until something disconnects it.
    releaseClient = true;
  }
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

void onGapEvent(esp_bt_gap_cb_event_t event, esp_bt_gap_cb_param_t *param) {
  // Core 2.0.17 answers every PIN request with 1234. Pairing then fails
  // whenever secrets.h uses a different PIN, so this callback replaces that reply.
  if (event == ESP_BT_GAP_PIN_REQ_EVT) {
    esp_bt_pin_code_t pin = {};
    uint8_t length = strlen(BT_PAIRING_PIN);
    if (length > ESP_BT_PIN_CODE_LEN) length = ESP_BT_PIN_CODE_LEN;
    memcpy(pin, BT_PAIRING_PIN, length);
    bool accept = !(param->pin_req.min_16_digit && length < 16);
    esp_bt_gap_pin_reply(param->pin_req.bda, accept, accept ? length : 0, accept ? pin : nullptr);
  } else if (event == ESP_BT_GAP_CFM_REQ_EVT) {
    esp_bt_gap_ssp_confirm_reply(param->cfm_req.bda, true);
  } else if (event == ESP_BT_GAP_KEY_REQ_EVT) {
    uint32_t passkey = 0;
    bool numeric = BT_PAIRING_PIN[0];
    for (const char *digit = BT_PAIRING_PIN; *digit; ++digit) {
      if (*digit < '0' || *digit > '9' || passkey > 99999) { numeric = false; break; }
      passkey = passkey * 10u + static_cast<uint32_t>(*digit - '0');
    }
    esp_bt_gap_ssp_passkey_reply(param->key_req.bda, numeric, numeric ? passkey : 0);
  } else if (event == ESP_BT_GAP_AUTH_CMPL_EVT) {
    Serial.printf("BT_AUTH %s\n", param->auth_cmpl.stat == ESP_BT_STATUS_SUCCESS ? "true" : "false");
  }
}

void onBluetoothEvent(esp_spp_cb_event_t event, esp_spp_cb_param_t *param) {
  if (event == ESP_SPP_START_EVT) bluetoothChannel = param->start.scn;
  if (event == ESP_SPP_SRV_OPEN_EVT) {
    resetBluetoothCommand = true;
    lastRxMs.store(millis());
    announceOpen = true;
  }
  if (event == ESP_SPP_CLOSE_EVT) {
    resetBluetoothCommand = true;
    reopenRadio = true;
    announceClose = true;
  }
}

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(false);
  pinMode(4, OUTPUT); digitalWrite(4, LOW);
  delay(300);
  Serial.println("\nSYNCHRO_CAM_BLUETOOTH_BOOT v2");
  cameraReady = startCamera();
  SerialBT.register_callback(onBluetoothEvent);
  SerialBT.setPin(BT_PAIRING_PIN);
  bluetoothReady = SerialBT.begin(BT_NAME);
  if (bluetoothReady) {
    esp_err_t gap = esp_bt_gap_register_callback(onGapEvent);
    Serial.printf("BT_PIN %s\n", gap == ESP_OK ? "custom" : "default");
    bluetoothAddress = SerialBT.getBtAddressString();
    lastRxMs.store(millis());
    // Keep the controller awake so Windows can page the camera after a drop.
    // Sniff mode itself has no public switch in this core.
    esp_err_t sleep = esp_bt_sleep_disable();
    esp_err_t power = esp_bredr_tx_power_set(ESP_PWR_LVL_P9, ESP_PWR_LVL_P9);
    Serial.printf("BT_SLEEP %s\n", sleep == ESP_OK ? "off" : "unavailable");
    Serial.printf("BT_POWER %s\n", power == ESP_OK ? "9dBm" : "unavailable");
  }
  Serial.println(statusJson());
  Serial.println("COMMANDS STATUS CAPTURE");
}

void loop() {
  if (announceOpen.exchange(false)) Serial.println("BT_CLIENT open");
  if (announceClose.exchange(false)) Serial.println("BT_CLIENT closed");
  if (reopenRadio.exchange(false)) {
    esp_bt_gap_set_scan_mode(ESP_BT_CONNECTABLE, ESP_BT_GENERAL_DISCOVERABLE);
    Serial.println("BT_LISTEN");
  }
  if (resetBluetoothCommand.exchange(false)) bluetoothCommand = "";
  processCommands(Serial, usbCommand);
  if (bluetoothReady) {
    if (SerialBT.available()) lastRxMs.store(millis());
    processCommands(SerialBT, bluetoothCommand);
    bool stale = SerialBT.hasClient() && millis() - lastRxMs.load() > 12000;
    if (releaseClient.exchange(false) || stale) {
      Serial.println(stale ? "BT_RELEASE idle" : "BT_RELEASE send");
      SerialBT.disconnect();
      lastRxMs.store(millis());
    }
  }
  delay(1);
}
