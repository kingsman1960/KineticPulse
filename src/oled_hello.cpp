/**
 * OLED bring-up — SSD1306 @ 0x3C on XIAO ESP32-S3 (SDA=5, SCL=6).
 *   pio run -e oled_hello -t upload
 */
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include "tum_logo.h"

#define I2C_SDA 5
#define I2C_SCL 6
#define SCREEN_W 128
#define SCREEN_H 64
#define OLED_ADDR 0x3C

Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);

void setup() {
  Serial.begin(115200);
  delay(800);
  Wire.begin(I2C_SDA, I2C_SCL);

  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println("OLED init failed @ 0x3C");
    for (;;) delay(1000);
  }

  display.clearDisplay();
  display.drawBitmap(0, 0, TUM_LOGO, TUM_LOGO_W, TUM_LOGO_H, SSD1306_WHITE);
  display.display();

  Serial.println("TUM logo drawn");
}

void loop() { delay(1000); }
