// Arduino Nano ESP32 USB-to-UART bridge for an ESP32-CAM.
// Nano D2 (RX) <- camera U0T; Nano D3 (TX) -> camera U0R.
// Common GND required. Both boards use 3.3 V serial signals.
// UART follows the USB host baud rate; start at 115200 baud.
// Use esptool --before no_reset
// --after no_reset_stub (esptool v4 syntax). Reset the camera manually.

#include <Arduino.h>

#if !defined(ARDUINO_NANO_ESP32) || ARDUINO_USB_MODE || !ARDUINO_USB_CDC_ON_BOOT
#error "Select Arduino Nano ESP32 with USB Mode: Normal mode (TinyUSB)."
#endif

constexpr uint32_t BRIDGE_BAUD = 115200;
uint32_t currentBaud = BRIDGE_BAUD;
uint8_t toComputer[512];
size_t pendingBytes = 0;
size_t sentBytes = 0;

void setup() {
  // Prevent esptool's serial control signals from rebooting the bridge.
  // The Nano's normal DFU upload interface remains available.
  Serial.enableReboot(false);
  Serial.setRxBufferSize(16384);
  Serial.begin(BRIDGE_BAUD);

  Serial1.setRxBufferSize(32768);
  Serial1.setTxBufferSize(4096);
  Serial1.begin(BRIDGE_BAUD, SERIAL_8N1, D2, D3);

  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);  // Solid yellow: bridge sketch running.
}

void loop() {
  const uint32_t requestedBaud = Serial.baudRate();
  if (requestedBaud >= 9600 && requestedBaud <= 921600 && requestedBaud != currentBaud) {
    Serial1.flush();
    Serial1.updateBaudRate(requestedBaud);
    currentBaud = requestedBaud;
  }
  // no_reset preserves the asserted DTR/RTS needed by this USB CDC core.
  // Discard camera logs when there is no host listening.
  if (!Serial) {
    for (size_t i = 0; i < 256 && Serial1.available() > 0; ++i) {
      Serial1.read();
    }
    pendingBytes = sentBytes = 0;
    delay(1);
    return;
  }

  uint8_t toCamera[256];
  const int uartSpace = Serial1.availableForWrite();
  size_t count = 0;
  while (uartSpace > 0 && count < static_cast<size_t>(uartSpace) && count < sizeof(toCamera) && Serial.available() > 0) {
    toCamera[count++] = static_cast<uint8_t>(Serial.read());
  }
  if (count > 0) Serial1.write(toCamera, count);

  if (sentBytes == pendingBytes) {
    pendingBytes = sentBytes = 0;
    while (pendingBytes < sizeof(toComputer) && Serial1.available() > 0) {
      toComputer[pendingBytes++] = static_cast<uint8_t>(Serial1.read());
    }
  }

  const int available = Serial.availableForWrite();
  if (available > 0 && sentBytes < pendingBytes) {
    size_t countToSend = pendingBytes - sentBytes;
    if (countToSend > static_cast<size_t>(available)) countToSend = available;
    sentBytes += Serial.write(toComputer + sentBytes, countToSend);
  }
  delay(1);
}
