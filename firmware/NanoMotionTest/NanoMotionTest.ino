// Nano ESP32 + one MPU-6050 / GY-521 on the back of the hand.
// VCC -> 3V3, GND -> GND, SDA -> A4, SCL -> A5.
// AD0 -> GND (0x68). Conductive thumb contact -> GND.
// Index contact -> D4 (left), middle contact -> D5 (right).
// Contacts must touch each other directly; inputs use internal pull-ups.
// This sketch replaces the Nano's camera UART bridge while testing motion.
// It does not change the separate ESP32-CAM's Bluetooth firmware.

#include <Arduino.h>
#include <Wire.h>

#if !defined(ARDUINO_NANO_ESP32)
#error "Select Arduino Nano ESP32."
#endif

constexpr uint8_t MPU_ADDRESS = 0x68;
constexpr uint32_t SAMPLE_MS = 20;
constexpr uint32_t DEBOUNCE_MS = 25;
bool sensorReady = false;
bool busReady = false;
bool wasConnected = false;
uint32_t lastSample = 0;
uint32_t lastProbe = 0;
uint32_t failures = 0;

struct Contact {
  uint8_t pin;
  bool down = false;
  bool candidate = false;
  uint32_t changedAt = 0;

  explicit Contact(uint8_t contactPin) : pin(contactPin) {}

  void begin() {
    pinMode(pin, INPUT_PULLUP);
    candidate = digitalRead(pin) == LOW;
    changedAt = millis();
  }

  void update(uint32_t now) {
    const bool reading = digitalRead(pin) == LOW;
    if (reading != candidate) {
      candidate = reading;
      changedAt = now;
    }
    if (now - changedAt >= DEBOUNCE_MS) down = candidate;
  }
};

Contact leftContact(D4);
Contact rightContact(D5);

bool writeRegister(uint8_t address, uint8_t reg, uint8_t value) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool readRegisters(uint8_t address, uint8_t reg, uint8_t *data, size_t count) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(address, count, true) != count) {
    while (Wire.available()) Wire.read();
    return false;
  }
  for (size_t i = 0; i < count; ++i) data[i] = Wire.read();
  return true;
}

bool initializeSensor(uint8_t address) {
  uint8_t identity = 0;
  if (!readRegisters(address, 0x75, &identity, 1)) return false;
  // Verify the expected MPU-6050 identity before changing registers.
  if (identity != 0x68) {
    Serial.printf("# unexpected_identity,address=0x%02X,value=0x%02X\n", address, identity);
    return false;
  }
  if (!writeRegister(address, 0x6B, 0x80)) return false;  // Device reset.
  delay(100);
  // Wake, enable all axes, PLL clock, 44/42 Hz low-pass filter,
  // 50 Hz sensor sampling, +/-500 degrees/s and +/-4 g ranges.
  if (!writeRegister(address, 0x6B, 0x01) ||
      !writeRegister(address, 0x6C, 0x00) ||
      !writeRegister(address, 0x1A, 0x03) ||
      !writeRegister(address, 0x19, 19) ||
      !writeRegister(address, 0x1B, 0x08) ||
      !writeRegister(address, 0x1C, 0x08)) return false;
  delay(100);
  uint8_t ranges[2];
  return readRegisters(address, 0x1B, ranges, 2) &&
         ranges[0] == 0x08 && ranges[1] == 0x08;
}

int16_t signedWord(const uint8_t *bytes) {
  const uint16_t value = (uint16_t(bytes[0]) << 8) | bytes[1];
  return static_cast<int16_t>(value);
}

void setup() {
  Serial.begin(115200);
  leftContact.begin();
  rightContact.begin();
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
  busReady = Wire.begin(A4, A5, 100000);
  Wire.setTimeOut(25);
}

void loop() {
  const uint32_t now = millis();
  leftContact.update(now);
  rightContact.update(now);
  const bool connected = bool(Serial);
  if (!connected) {
    wasConnected = false;
    delay(5);
    return;
  }
  const bool justConnected = !wasConnected;
  if (justConnected) {
    wasConnected = true;
    Serial.println("# Synchro motion test v2; one MPU; D4/D5 contacts; 50 Hz target");
    Serial.println("# Uncalibrated diagnostic only; does not control the laptop cursor");
    Serial.println("ms,address,imu_ready,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,temp_c,left_down,right_down");
  }
  if (justConnected || now - lastProbe >= 2000) {
    lastProbe = now;
    if (!busReady) Serial.println("# I2C initialization failed");
    if (busReady && !sensorReady) sensorReady = initializeSensor(MPU_ADDRESS);
    Serial.printf("# sensor,address=0x%02X,ready=%u,read_failures=%lu\n",
                  MPU_ADDRESS, unsigned(sensorReady), (unsigned long)failures);
    digitalWrite(LED_BUILTIN, sensorReady ? HIGH : LOW);
  }
  const uint32_t sampleTime = millis();
  if (sampleTime - lastSample < SAMPLE_MS) {
    delay(1);
    return;
  }
  lastSample = sampleTime;
  uint8_t bytes[14];
  if (sensorReady && !readRegisters(MPU_ADDRESS, 0x3B, bytes, sizeof(bytes))) {
    ++failures;
    sensorReady = false;
    digitalWrite(LED_BUILTIN, LOW);
    Serial.printf("# read_failed,address=0x%02X\n", MPU_ADDRESS);
  }
  // Continue reporting contact states even if the motion sensor is absent.
  // Missing motion data is explicitly invalid, never fabricated as zeros.
  if (!sensorReady) {
    Serial.printf("%lu,0x%02X,0,nan,nan,nan,nan,nan,nan,nan,%u,%u\n",
                  (unsigned long)sampleTime, MPU_ADDRESS,
                  unsigned(leftContact.down), unsigned(rightContact.down));
  } else {
    Serial.printf("%lu,0x%02X,1,%.4f,%.4f,%.4f,%.3f,%.3f,%.3f,%.2f,%u,%u\n",
                  (unsigned long)sampleTime, MPU_ADDRESS,
                  signedWord(bytes) / 8192.0, signedWord(bytes + 2) / 8192.0,
                  signedWord(bytes + 4) / 8192.0,
                  signedWord(bytes + 8) / 65.5, signedWord(bytes + 10) / 65.5,
                  signedWord(bytes + 12) / 65.5,
                  signedWord(bytes + 6) / 340.0 + 36.53,
                  unsigned(leftContact.down), unsigned(rightContact.down));
  }
}
