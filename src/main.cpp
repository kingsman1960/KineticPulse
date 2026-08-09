/**
 * KineticPulse wristband TCP client (ESP32-S3).
 *
 * Wire format must match kineticpulse/sensors/tcp.py — one NDJSON event
 * per line. Fake HR/accel until MAX30102 + IMU firmware lands.
 *
 * Setup:
 *   cp src/wifi_secrets.h.example src/wifi_secrets.h
 *   # edit SSID / password / Jetson SERVER_IP
 *   pio run -e seeed_xiao_esp32s3 -t upload
 */
#include <Arduino.h>
#include <WiFi.h>

#include "wifi_secrets.h"

#ifndef DEVICE_ID
#define DEVICE_ID "esp32-kp-001"
#endif
#ifndef FW_VERSION
#define FW_VERSION "0.2.0"
#endif

WiFiClient client;
int bpm = 72;
bool hello_sent = false;

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
  // caps: synthetic hr+accel until real PPG/IMU drivers land
  char buf[192];
  snprintf(
      buf,
      sizeof(buf),
      "{\"type\":\"hello\",\"device\":\"%s\",\"fw\":\"%s\",\"caps\":[\"hr\",\"accel\"]}",
      DEVICE_ID,
      FW_VERSION);
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

  // Synthetic resting vitals — swap for MAX30102 / IMU reads later.
  bpm += random(-1, 2);
  if (bpm < 60) bpm = 60;
  if (bpm > 90) bpm = 90;

  float ax = random(-30, 31) / 100.0f;
  float ay = random(-30, 31) / 100.0f;
  float az = 1.0f + random(-10, 11) / 100.0f;

  sendHr(bpm);
  sendAccel(ax, ay, az);

  delay(200);  // ~5 Hz; Jetson idle timeout is 10s by default
}
