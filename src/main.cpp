/**
 * KineticPulse wristband TCP client (ESP32-S3).
 *
 * Wire format must match kineticpulse/sensors/tcp.py — one NDJSON event
 * per line. Real MPU accel at 50 Hz and real MAX30102/30105 HR (the beat
 * detector is the same one the sensor_display HUD env uses).
 *
 * Setup:
 *   cp src/wifi_secrets.h.example src/wifi_secrets.h
 *   # edit SSID / password / Jetson SERVER_IP
 *   pio run -e seeed_xiao_esp32s3 -t upload
 */
#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>

#include "MAX30105.h"
#include "heartRate.h"

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

// MAX30105 beat detection. getIR() must be polled at roughly the 100 Hz
// sample rate configured in setup(), so it runs every loop() pass rather
// than on the HR_PERIOD_MS send cadence.
MAX30105 ppg;
static const byte RATE_SIZE = 4;
static byte rates[RATE_SIZE];
static byte rateSpot = 0;
static long lastBeat = 0;
static float beatsPerMinute = 0;
static int beatAvg = 0;
static bool ppgOk = false;
// Below this IR level nothing is on the sensor; report "no reading" rather
// than a stale BPM, so fusion sees an absent HR instead of a wrong one.
static const long IR_PRESENT_MIN = 50000;

static void pollHeartRate() {
  if (!ppgOk) return;
  long ir = ppg.getIR();
  if (checkForBeat(ir)) {
    long delta = millis() - lastBeat;
    lastBeat = millis();
    if (delta > 0) {
      beatsPerMinute = 60.0f / (delta / 1000.0f);
      if (beatsPerMinute > 20 && beatsPerMinute < 255) {
        rates[rateSpot++] = (byte)beatsPerMinute;
        rateSpot %= RATE_SIZE;
        int sum = 0;
        byte filled = 0;
        for (byte i = 0; i < RATE_SIZE; i++) {
          if (rates[i] != 0) {
            sum += rates[i];
            filled++;
          }
        }
        if (filled) beatAvg = sum / filled;
      }
    }
  }
  if (ir < IR_PRESENT_MIN) {
    beatAvg = 0;
    beatsPerMinute = 0;
    memset(rates, 0, sizeof(rates));
    rateSpot = 0;
  }
}

WiFiClient client;
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
  // Advertise only what actually came up on the I2C bus this boot, so the
  // Jetson can tell a missing sensor from a silent one.
  char caps[48] = "";
  if (ppgOk) strncat(caps, "\"hr\"", sizeof(caps) - strlen(caps) - 1);
  if (mpuOk) {
    if (caps[0]) strncat(caps, ",", sizeof(caps) - strlen(caps) - 1);
    strncat(caps, "\"accel\"", sizeof(caps) - strlen(caps) - 1);
  }
  snprintf(
      buf,
      sizeof(buf),
      "{\"type\":\"hello\",\"device\":\"%s\",\"fw\":\"%s\",\"caps\":[%s]}",
      DEVICE_ID,
      FW_VERSION,
      caps);
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

  ppgOk = ppg.begin(Wire, I2C_SPEED_FAST, 0x57);
  if (ppgOk) {
    // ledBright, sampleAvg, mode(2=Red+IR), rateHz, pulseWidth, adcRange
    // — same configuration the sensor_display HUD env validated.
    ppg.setup(0x2F, 4, 2, 100, 411, 4096);
    ppg.setPulseAmplitudeIR(0x3F);
    ppg.setPulseAmplitudeRed(0x1F);
    ppg.setPulseAmplitudeGreen(0);
  }

  Serial.printf("IMU %s who=0x%02X | PPG %s\n",
                mpuOk ? "ok" : "missing", mpuWho,
                ppgOk ? "ok" : "missing");
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

  // Must run every pass: checkForBeat() needs the full ~100 Hz IR stream.
  pollHeartRate();

  if ((now - lastHrMs) >= HR_PERIOD_MS) {
    lastHrMs = now;
    // Only publish a settled average. Skipping the send while the finger is
    // off the sensor lets the Jetson's pulse_loss_timeout_s do its job
    // instead of being fed a fabricated resting BPM.
    if (beatAvg > 0) {
      sendHr(beatAvg);
    }
  }
}
