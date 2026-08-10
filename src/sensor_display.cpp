/**
 * Live sensor HUD on SSD1306 — MAX30102 + MPU6050 + battery/USB.
 *
 *   pio run -e sensor_display -t upload
 *
 * Battery % needs a 1:2 divider from BAT+ → BAT_ADC_PIN → GND.
 * XIAO ESP32-S3 has no onboard BAT ADC (Seeed wiki). Leave BAT_ADC_PIN
 * as -1 to skip voltage; USB VBUS still reports charge-port presence.
 */
#include <Arduino.h>
#include <Wire.h>
#include <string.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "MAX30105.h"
#include "heartRate.h"

#define I2C_SDA 5
#define I2C_SCL 6
#define SCREEN_W 128
#define SCREEN_H 64
#define OLED_ADDR 0x3C
#define MPU_ADDR 0x68
// ponytail: no onboard BAT sense on XIAO-S3 — wire 2x100k divider to this ADC or leave -1.
#define BAT_ADC_PIN (-1)
#define BAT_VMIN_MV 3300
#define BAT_VMAX_MV 4200

Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);
MAX30105 ppg;

static const byte RATE_SIZE = 4;
static byte rates[RATE_SIZE];
static byte rateSpot = 0;
static long lastBeat = 0;
static float beatsPerMinute = 0;
static int beatAvg = 0;
static bool ppgOk = false;
static bool mpuOk = false;
static uint8_t mpuWho = 0;

static bool mpuWrite(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission() == 0;
}

static bool mpuRead(uint8_t reg, uint8_t *buf, size_t n) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)MPU_ADDR, (int)n) != (int)n) return false;
  for (size_t i = 0; i < n; i++) buf[i] = Wire.read();
  return true;
}

static bool mpuBegin() {
  uint8_t who = 0;
  if (!mpuRead(0x75, &who, 1)) return false;
  mpuWho = who;
  // 0x68 MPU6050; 0x71 MPU9250; 0x19 ICM-ish — wake still works for accel.
  if (!mpuWrite(0x6B, 0x00)) return false;
  delay(50);
  return who != 0 && who != 0xFF;
}

static bool mpuAccelG(float *ax, float *ay, float *az) {
  uint8_t raw[6];
  if (!mpuRead(0x3B, raw, 6)) return false;
  int16_t x = (int16_t)((raw[0] << 8) | raw[1]);
  int16_t y = (int16_t)((raw[2] << 8) | raw[3]);
  int16_t z = (int16_t)((raw[4] << 8) | raw[5]);
  // ±2g default → 16384 LSB/g
  *ax = x / 16384.0f;
  *ay = y / 16384.0f;
  *az = z / 16384.0f;
  return true;
}

struct BatStatus {
  bool sensed;
  bool usb;
  int mv;
  int pct;
  const char *mode;  // USB / CHG / BAT / --
};

static BatStatus readBattery() {
  BatStatus b = {};
  // XIAO uses USB-Serial/JTAG CDC — isPlugged tracks host VBUS/SOF presence.
  b.usb = Serial.isPlugged();
  b.sensed = false;
  b.mv = 0;
  b.pct = -1;
  b.mode = b.usb ? "USB" : "--";

#if BAT_ADC_PIN >= 0
  // 1:2 divider → ADC sees ~half of pack voltage.
  int adc_mv = analogReadMilliVolts(BAT_ADC_PIN);
  int pack_mv = adc_mv * 2;
  if (pack_mv >= 2500 && pack_mv <= 4500) {
    b.sensed = true;
    b.mv = pack_mv;
    int pct = (int)((pack_mv - BAT_VMIN_MV) * 100L / (BAT_VMAX_MV - BAT_VMIN_MV));
    if (pct < 0) pct = 0;
    if (pct > 100) pct = 100;
    b.pct = pct;
    b.mode = b.usb ? "CHG" : "BAT";
  } else if (!b.usb) {
    b.mode = "BAT?";
  }
#else
  if (!b.usb) b.mode = "BAT";  // running off pads; % unknown
#endif
  return b;
}

static void drawHud(long ir, float ax, float ay, float az, const BatStatus &bat) {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("HR ");
  if (ir < 50000) {
    display.print("--  no finger");
  } else if (beatAvg > 0) {
    display.print(beatAvg);
    display.print(" bpm");
  } else if (beatsPerMinute > 0) {
    display.print((int)beatsPerMinute);
    display.print(" bpm*");
  } else {
    display.print(".. measuring");
  }

  display.setCursor(0, 12);
  if (mpuOk) {
    char line[22];
    snprintf(line, sizeof(line), "A %+0.2f %+0.2f %+0.2f", ax, ay, az);
    display.print(line);
  } else {
    display.print("IMU missing");
  }

  display.setCursor(0, 24);
  display.print("IR ");
  display.print(ir);

  display.setCursor(0, 36);
  display.print("BAT ");
  if (bat.sensed) {
    display.print(bat.pct);
    display.print("% ");
    display.print(bat.mv / 1000.0f, 2);
    display.print("V ");
  } else {
    display.print("--% ");
  }
  display.print(bat.mode);

  display.setCursor(0, 48);
  display.print(ppgOk ? "PPG ok" : "PPG FAIL");
  display.print("  ");
  display.print(mpuOk ? "IMU ok" : "IMU FAIL");
  display.display();
}

void setup() {
  Serial.begin(115200);
  delay(800);
  Wire.begin(I2C_SDA, I2C_SCL);

  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println("OLED init failed");
    for (;;) delay(1000);
  }

  ppgOk = ppg.begin(Wire, I2C_SPEED_FAST, 0x57);
  if (ppgOk) {
    // ledBright, sampleAvg, mode(2=Red+IR), rateHz, pulseWidth, adcRange
    ppg.setup(0x2F, 4, 2, 100, 411, 4096);
    ppg.setPulseAmplitudeIR(0x3F);
    ppg.setPulseAmplitudeRed(0x1F);
    ppg.setPulseAmplitudeGreen(0);
  }

  mpuOk = mpuBegin();
  Serial.printf("self-check PPG=%d IMU=%d who=0x%02X\n", ppgOk, mpuOk, mpuWho);
  // ponytail: one assert-style gate — bus bring-up must see at least one sensor.
  if (!ppgOk && !mpuOk) {
    Serial.println("FAIL: no sensors on I2C");
  }

#if BAT_ADC_PIN >= 0
  analogReadResolution(12);
  analogSetPinAttenuation(BAT_ADC_PIN, ADC_11db);
#endif
}

void loop() {
  static long ir = 0;
  static float ax = 0, ay = 0, az = 0;
  static BatStatus bat = {};
  static uint32_t lastHudMs = 0;

  // Beat detector needs ~100 Hz IR samples — don't stall on OLED/Serial.
  if (ppgOk) {
    ir = ppg.getIR();
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
    if (ir < 50000) {
      beatAvg = 0;
      beatsPerMinute = 0;
      memset(rates, 0, sizeof(rates));
      rateSpot = 0;
    }
  }

  uint32_t now = millis();
  if (now - lastHudMs < 250) return;
  lastHudMs = now;

  if (mpuOk) mpuAccelG(&ax, &ay, &az);
  bat = readBattery();
  drawHud(ir, ax, ay, az, bat);

  Serial.printf("IR=%ld BPM=%.0f avg=%d A=%.2f,%.2f,%.2f USB=%d\n",
                ir, beatsPerMinute, beatAvg, ax, ay, az, bat.usb);
}
