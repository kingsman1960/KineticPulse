/**
 * MPU6050 / MPU9250 accel on the XIAO I2C bus.
 * Shared by the TCP firmware and the OLED HUD.
 *
 * Range is ±8 g (4096 LSB/g) so fusion's 3 g impact threshold is on-scale.
 * Default chip range is ±2 g, which saturates below that threshold.
 */
#pragma once

#include <Arduino.h>
#include <Wire.h>
#include <stdint.h>

#ifndef MPU_ADDR
#define MPU_ADDR 0x68
#endif

// ACCEL_CONFIG AFS_SEL=2 → ±8 g.
static const float MPU_ACCEL_LSB_PER_G = 4096.0f;

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
  if (!mpuWrite(0x1C, 0x10)) return false;  // ±8 g
  delay(10);
  return who != 0 && who != 0xFF;
}

static bool mpuAccelG(float *ax, float *ay, float *az) {
  uint8_t raw[6];
  if (!mpuRead(0x3B, raw, 6)) return false;
  int16_t x = (int16_t)((raw[0] << 8) | raw[1]);
  int16_t y = (int16_t)((raw[2] << 8) | raw[3]);
  int16_t z = (int16_t)((raw[4] << 8) | raw[5]);
  *ax = x / MPU_ACCEL_LSB_PER_G;
  *ay = y / MPU_ACCEL_LSB_PER_G;
  *az = z / MPU_ACCEL_LSB_PER_G;
  return true;
}
