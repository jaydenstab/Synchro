// Nano ESP32 acquisition companion to tools/motion_sensor.py.
// MPU-6050: 3V3 -> VCC, GND -> GND + AD0, A4 -> SDA, A5 -> SCL.
// Thumb -> GND, index -> D4, middle -> D5. INT is not needed (FIFO).
// 1 kHz synchronized accel/gyro acquisition; double-precision quaternion
// fusion and calibration run on the laptop. No mouse events are injected.
#include <Arduino.h>
#include <Wire.h>
#include <esp_timer.h>
#include <tusb.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLE2902.h>

#if !defined(ARDUINO_NANO_ESP32)
#error "Select Arduino Nano ESP32 (arduino:esp32:nano_nora)."
#endif

constexpr uint8_t ADDRESS = 0x68;
constexpr size_t MAX_SAMPLES = 15; // 238-byte frame fits negotiated 247-byte BLE MTU.
constexpr uint32_t DEBOUNCE_MS = 25;
const uint8_t MAGIC[8] = {'S','Y','N','I','M','U','1','\n'};

struct Contact {
  uint8_t pin;
  bool down = false, candidate = false;
  uint32_t changedAt = 0, presses = 0;
  explicit Contact(uint8_t p) : pin(p) {}
  void begin() { pinMode(pin, INPUT_PULLUP); }
  void update(uint32_t now) {
    bool next = digitalRead(pin) == LOW;
    if (next != candidate) { candidate = next; changedAt = now; }
    if (candidate != down && now - changedAt >= DEBOUNCE_MS) {
      down = candidate;
      if (down) ++presses;
    }
  }
};
Contact left(D4), right(D5);

// Little-endian packed wire format; mirrored by Python struct.Struct.
struct __attribute__((packed)) Header {
  uint32_t packetSequence, firstSample;
  uint64_t readTimeUs;
  uint16_t count;
  int16_t temperature;
  uint8_t contacts, ready;
  uint32_t leftPresses, rightPresses, fifoResets, i2cErrors, reserved;
};
static_assert(sizeof(Header) == 42, "Wire header changed");
uint8_t tx[10 + sizeof(Header) + MAX_SAMPLES * 12 + 4];
size_t txLength = 0, txOffset = 0;
uint32_t packets = 0, samples = 0, resets = 0, errors = 0;
uint32_t lastProbe = 0, lastTemperature = 0, lastHeartbeat = 0;
int16_t temperatureRaw = 0;
bool ready = false, connectedBefore = false;
constexpr char SERVICE_UUID[] = "8870a001-49a5-4a7c-8d92-a1f003b7d601";
constexpr char DATA_UUID[] = "8870a002-49a5-4a7c-8d92-a1f003b7d601";
constexpr char IDENTITY_UUID[] = "8870a003-49a5-4a7c-8d92-a1f003b7d601";
BLEServer* bleServer = nullptr;
BLECharacteristic* bleData = nullptr;
BLE2902* bleSubscription = nullptr;
volatile bool bleConnected = false;
volatile uint32_t bleGeneration = 0, bleDrops = 0;
struct BleFrame { uint32_t generation; uint16_t size; uint8_t bytes[sizeof(tx)]; };
QueueHandle_t bleQueue = nullptr;

class GloveCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* server, esp_ble_gatts_cb_param_t* param) override {
    ++bleGeneration;
    bleConnected = true;
    // 7.5–15 ms interval request; the laptop ultimately chooses the interval.
    server->updateConnParams(param->connect.remote_bda, 6, 12, 0, 400);
  }
  void onDisconnect(BLEServer* server) override {
    bleConnected = false;
    ++bleGeneration;
    bleSubscription->setNotifications(false);
    server->startAdvertising();
  }
};
void bleSender(void*) {
  BleFrame frame;
  for (;;) {
    if (xQueueReceive(bleQueue, &frame, portMAX_DELAY) != pdTRUE) continue;
    if (!bleConnected || frame.generation != bleGeneration || !bleSubscription->getNotifications()) continue;
    size_t mtu = bleServer->getPeerMTU(bleServer->getConnId());
    size_t payload = mtu > 23 ? min(size_t(244), mtu - 3) : 20;
    for (size_t offset = 0; offset < frame.size; offset += payload) {
      if (!bleConnected || frame.generation != bleGeneration) break;
      size_t length = min(payload, size_t(frame.size) - offset);
      bleData->setValue(frame.bytes + offset, length);
      bleData->notify();
      // Yield to the Bluetooth stack, without blocking the I2C acquisition task.
      vTaskDelay(1);
    }
  }
}
void initializeBle() {
  BLEDevice::init("Synchro-Glove");
  BLEDevice::setMTU(247);
  bleServer = BLEDevice::createServer();
  bleServer->setCallbacks(new GloveCallbacks());
  BLEService* service = bleServer->createService(SERVICE_UUID);
  bleData = service->createCharacteristic(DATA_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  bleSubscription = new BLE2902();
  bleData->addDescriptor(bleSubscription);
  uint8_t mac[6];
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  char identity[13];
  snprintf(identity, sizeof(identity), "%02X%02X%02X%02X%02X%02X",
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  service->createCharacteristic(IDENTITY_UUID, BLECharacteristic::PROPERTY_READ)->setValue(identity);
  service->start();
  auto advertising = bleServer->getAdvertising();
  advertising->addServiceUUID(SERVICE_UUID);
  advertising->setScanResponse(true);
  advertising->setMinPreferred(6);
  advertising->setMaxPreferred(12);
  bleQueue = xQueueCreate(8, sizeof(BleFrame));
  if (bleQueue) {
    xTaskCreatePinnedToCore(bleSender, "glove-ble", 4096, nullptr, 1, nullptr, 0);
    advertising->start();
  }
}

bool writeReg(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(ADDRESS); Wire.write(reg); Wire.write(value);
  return Wire.endTransmission() == 0;
}
bool readReg(uint8_t reg, uint8_t* bytes, size_t size) {
  Wire.beginTransmission(ADDRESS); Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(ADDRESS, size, true) != size) {
    while (Wire.available()) Wire.read();
    return false;
  }
  for (size_t i = 0; i < size; ++i) bytes[i] = Wire.read();
  return true;
}
int16_t word(const uint8_t* b) { return int16_t((uint16_t(b[0]) << 8) | b[1]); }
bool resetFifo() {
  ++resets;
  if (!writeReg(0x23, 0) || !writeReg(0x6A, 0x04)) return false;
  delayMicroseconds(100);
  if (!writeReg(0x6A, 0x40) || !writeReg(0x23, 0x78)) return false;
  uint8_t enabled, control;
  return readReg(0x23, &enabled, 1) && readReg(0x6A, &control, 1) &&
         enabled == 0x78 && (control & 0x40);
}
bool initialize() {
  uint8_t id;
  if (!readReg(0x75, &id, 1) || id != 0x68) return false;
  if (!writeReg(0x6B, 0x80)) return false;
  delay(100);
  // X gyro PLL, all axes enabled, DLPF=2: accel 94 Hz / gyro 98 Hz.
  // Divider 0 gives 1000 fresh accel+gyro samples/s (accel limit).
  // +/-500 deg/s and +/-4 g provide headroom for hand movements.
  if (!writeReg(0x6B, 1) || !writeReg(0x6C, 0) ||
      !writeReg(0x1A, 2) || !writeReg(0x19, 0) ||
      !writeReg(0x1B, 8) || !writeReg(0x1C, 8) ||
      !writeReg(0x37, 0) || !writeReg(0x38, 0x10)) return false;
  delay(100);
  uint8_t config[4];
  if (!readReg(0x19, config, 4) || config[0] != 0 || config[1] != 2 ||
      config[2] != 8 || config[3] != 8) return false;
  uint8_t temp[2];
  if (!readReg(0x41, temp, 2)) return false;
  temperatureRaw = word(temp);
  return resetFifo();
}
uint32_t crc32(const uint8_t* bytes, size_t length) {
  uint32_t crc = 0xFFFFFFFF;
  while (length--) {
    crc ^= *bytes++;
    for (int bit = 0; bit < 8; ++bit)
      crc = (crc >> 1) ^ (0xEDB88320U & (0U - (crc & 1U)));
  }
  return ~crc;
}
void packet(const uint8_t* raw, uint16_t count, uint64_t readTime) {
  Header h = {packets++, samples, readTime, count, temperatureRaw,
              uint8_t(unsigned(left.down) | (unsigned(right.down) << 1)),
              uint8_t(ready), left.presses, right.presses, resets, errors, bleDrops};
  samples += count;
  bool usbConnected = tud_cdc_connected();
  bool bluetooth = bleConnected && bleSubscription->getNotifications();
  if (!usbConnected && !bluetooth) return;
  uint16_t length = sizeof(h) + count * 12;
  memcpy(tx, MAGIC, 8); memcpy(tx + 8, &length, 2);
  memcpy(tx + 10, &h, sizeof(h));
  for (size_t i = 0; i < count * 6; ++i) {
    int16_t value = word(raw + i * 2);
    memcpy(tx + 10 + sizeof(h) + i * 2, &value, 2);
  }
  uint32_t crc = crc32(tx + 10, length);
  memcpy(tx + 10 + length, &crc, 4);
  txLength = 10 + length + 4; txOffset = 0;
  if (bluetooth) {
    BleFrame frame;
    frame.generation = bleGeneration;
    frame.size = txLength;
    memcpy(frame.bytes, tx, txLength);
    if (xQueueSend(bleQueue, &frame, 0) != pdTRUE) ++bleDrops;
  }
  if (!usbConnected) txLength = txOffset = 0;
}
void flushTx() {
  if (txOffset >= txLength) return;
  int available = Serial.availableForWrite();
  if (available <= 0) return;
  size_t count = min(size_t(available), txLength - txOffset);
  txOffset += Serial.write(tx + txOffset, count);
}
void setup() {
  Serial.begin(115200); // Native USB CDC; baud does not limit throughput.
  Serial.setTxTimeoutMs(0);
  Serial.enableReboot(false); // Uploads use DFU, not the RTS/DTR reboot sequence.
  left.begin(); right.begin();
  initializeBle();
  Wire.setBufferSize(256);
  Wire.begin(A4, A5, 400000); // MPU-6050 rated I2C maximum.
  Wire.setTimeOut(10);
  ready = initialize();
  lastProbe = millis();
}
void loop() {
  uint32_t now = millis();
  left.update(now); right.update(now);
  // USBCDC::operator bool also requires RTS, which Windows may not assert.
  // TinyUSB's actual CDC/DTR connection flag works with this laptop's driver.
  bool connected = tud_cdc_connected();
  if (connected != connectedBefore) {
    connectedBefore = connected;
    txLength = txOffset = 0;
    if (ready && !resetFifo()) { ready = false; ++errors; }
  }
  flushTx();
  if (txOffset < txLength) { delay(1); return; }
  if (!ready) {
    if (now - lastProbe >= 2000) { lastProbe = now; ready = initialize(); }
    if (now - lastHeartbeat >= 50) {
      lastHeartbeat = now; packet(nullptr, 0, esp_timer_get_time());
    }
    delay(1); return;
  }
  uint8_t status, fifoCount[2];
  if (!readReg(0x3A, &status, 1) || !readReg(0x72, fifoCount, 2)) {
    ++errors; ready = false; return;
  }
  uint16_t bytes = (uint16_t(fifoCount[0]) << 8) | fifoCount[1];
  if ((status & 0x10) || bytes >= 1008) {
    if (!resetFifo()) { ++errors; ready = false; }
    return;
  }
  uint16_t count = min(size_t(bytes / 12), MAX_SAMPLES);
  // Batch ~10ms of raw samples, reducing BLE notification overhead while
  // preserving every 1kHz sample for the double-precision laptop filter.
  if (bleConnected && count < 10 && now - lastHeartbeat < 15) {
    delay(1); return;
  }
  if (count) {
    uint8_t raw[MAX_SAMPLES * 12];
    if (!readReg(0x74, raw, count * 12)) { ++errors; ready = false; return; }
    packet(raw, count, esp_timer_get_time());
    lastHeartbeat = now;
  } else if (now - lastHeartbeat >= 50) {
    // Report the connection and contacts even if the FIFO produces no data.
    lastHeartbeat = now;
    packet(nullptr, 0, esp_timer_get_time());
  }
  if (now - lastTemperature >= 1000) {
    lastTemperature = now;
    uint8_t raw[2];
    if (readReg(0x41, raw, 2)) temperatureRaw = word(raw);
    else { ++errors; ready = false; }
  }
  if (!count) delay(1);
}
