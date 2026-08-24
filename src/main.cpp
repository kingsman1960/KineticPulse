/**
 * KineticPulse wristband TCP client (ESP32-S3).
 *
 * Wire format must match kineticpulse/sensors/tcp.py — one NDJSON event
 * per line. Real MPU accel at 50 Hz; synthetic HR until MAX30102 lands
 * in this firmware (the HUD env already drives the MAX30102).
 *
 * Setup:
 *   cp src/wifi_secrets.h.example src/wifi_secrets.h
 *   # edit SSID / password / Jetson SERVER_IP
 *   pio run -e seeed_xiao_esp32s3 -t upload
 */
#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>

#include "wifi_secrets.h"
#include "mpu6050.h"

#ifndef DEVICE_ID
#define DEVICE_ID "esp32-kp-001"
#endif
#ifndef FW_VERSION
#define FW_VERSION "0.3.0"
#endif

#ifndef I2C_SDA
#define I2C_SDA 5
#endif
#ifndef I2C_SCL
#define I2C_SCL 6
#endif

// Fusion mock/engine assume ~50 Hz. 20 ms is enough to catch a 3 g spike
// that lasts tens of milliseconds; 5 Hz (the old delay(200) loop) was not.
static const uint32_t ACCEL_PERIOD_MS = 20;
static const uint32_t HR_PERIOD_MS = 200;

WiFiClient client;
int bpm = 72;
bool hello_sent = false;
bool mpuOk = false;
uint32_t lastAccelMs = 0;
uint32_t lastHrMs = 0;

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;

  Serial.print("WiFi connecting");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("WiFi OK IP=");
  Serial.println(WiFi.localIP());
}

void connectServer() {
  if (client.connected()) return;

  hello_sent = false;
  Serial.print("TCP connect ");
  Serial.print(SERVER_IP);
  Serial.print(":");
  Serial.print(SERVER_PORT);
  Serial.print(" ... ");

  if (client.connect(SERVER_IP, SERVER_PORT)) {
    Serial.println("ok");
  } else {
    Serial.println("fail");
    delay(1000);
  }
}

void sendLine(const char *line) {
  client.println(line);
  Serial.println(line);
}

void sendHello() {
  char buf[192];
  if (mpuOk) {
    snprintf(
        buf,
        sizeof(buf),
        "{\"type\":\"hello\",\"device\":\"%s\",\"fw\":\"%s\",\"caps\":[\"hr\",\"accel\"]}",
        DEVICE_ID,
        FW_VERSION);
  } else {
    snprintf(
        buf,
        sizeof(buf),
        "{\"type\":\"hello\",\"device\":\"%s\",\"fw\":\"%s\",\"caps\":[\"hr\"]}",
        DEVICE_ID,
        FW_VERSION);
  }
  sendLine(buf);
  hello_sent = true;
}

void sendHr(int value) {
  char buf[96];
  snprintf(
      buf,
      sizeof(buf),
      "{\"type\":\"hr\",\"bpm\":%d,\"ts\":%lu}",
      value,
      (unsigned long)millis());
  sendLine(buf);
}

void sendAccel(float ax, float ay, float az) {
  char buf[128];
  snprintf(
      buf,
      sizeof(buf),
      "{\"type\":\"accel\",\"ax\":%.3f,\"ay\":%.3f,\"az\":%.3f,\"ts\":%lu}",
      ax,
      ay,
      az,
      (unsigned long)millis());
  sendLine(buf);
}

void setup() {
  Serial.begin(115200);
  delay(800);
  Wire.begin(I2C_SDA, I2C_SCL);
  mpuOk = mpuBegin();
  Serial.printf("IMU %s who=0x%02X\n", mpuOk ? "ok" : "missing", mpuWho);
  connectWiFi();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  if (!client.connected()) {
    connectServer();
    if (!client.connected()) {
      delay(500);
      return;
    }
  }

  if (!hello_sent) {
    sendHello();
  }

  uint32_t now = millis();

  if (mpuOk && (now - lastAccelMs) >= ACCEL_PERIOD_MS) {
    lastAccelMs = now;
    float ax, ay, az;
    if (mpuAccelG(&ax, &ay, &az)) {
      sendAccel(ax, ay, az);
    }
  }

  if ((now - lastHrMs) >= HR_PERIOD_MS) {
    lastHrMs = now;
    // ponytail: synthetic BPM until this firmware owns MAX30102 (HUD env does).
    bpm += random(-1, 2);
    if (bpm < 60) bpm = 60;
    if (bpm > 90) bpm = 90;
    sendHr(bpm);
  }
}
