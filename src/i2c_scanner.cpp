#include <Arduino.h>
#include <Wire.h>

// Seeed XIAO ESP32-S3 wristband bring-up pins.
#define I2C_SDA 5
#define I2C_SCL 6
#ifndef LED_BUILTIN
#define LED_BUILTIN 21
#endif

static const uint8_t MAX30102_ADDR = 0x57;

static void blink(int times, int on_ms = 120, int off_ms = 120) {
    for (int i = 0; i < times; i++) {
        digitalWrite(LED_BUILTIN, HIGH);
        delay(on_ms);
        digitalWrite(LED_BUILTIN, LOW);
        delay(off_ms);
    }
}

static void announceResult(int count, bool max30102) {
    // LED patterns (no serial required):
    //   1 long  = scan finished
    //   N short = N devices found (capped at 5)
    //   3 fast  = MAX30102 (0x57) seen
    //   2 long  = no devices
    if (count == 0) {
        blink(2, 400, 200);
        return;
    }
    blink(1, 500, 300);
    blink(min(count, 5), 100, 100);
    if (max30102) {
        delay(200);
        blink(3, 60, 60);
    }
}

void setup() {
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);

    Serial.begin(115200);
    delay(1500);
    Serial.println();
    Serial.println("[i2c_scanner] boot SDA=5 SCL=6");
    Serial.flush();

    Wire.begin(I2C_SDA, I2C_SCL);
    // Boot ack: 1 short blink
    blink(1, 80, 80);
}

void loop() {
    int count = 0;
    bool max30102 = false;

    Serial.println("Scanning...");
    for (uint8_t address = 1; address < 127; address++) {
        Wire.beginTransmission(address);
        if (Wire.endTransmission() == 0) {
            Serial.printf("Found I2C device at 0x%02X\n", address);
            count++;
            if (address == MAX30102_ADDR) {
                max30102 = true;
                Serial.println("  -> likely MAX30102 PPG sensor");
            }
        }
    }

    if (count == 0) {
        Serial.println("No I2C devices found (check wiring / 3V3 / GND / pull-ups)");
    } else {
        Serial.printf("Devices found: %d\n", count);
    }
    Serial.println();
    Serial.flush();

    announceResult(count, max30102);
    delay(2500);
}
