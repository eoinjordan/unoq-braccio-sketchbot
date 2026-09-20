#pragma once

#include <stdint.h>

namespace BraccioPulse {
constexpr int MIN_US = 500;
constexpr int MAX_US = 2500;
constexpr int FREQUENCY_HZ = 50;
constexpr uint32_t PERIOD_US = 1000000UL / FREQUENCY_HZ;
constexpr uint8_t RESOLUTION_BITS = 16;
constexpr uint32_t MAX_DUTY = (1UL << RESOLUTION_BITS) - 1UL;

inline int forAngle(float degrees) {
  const float bounded = degrees < 0.0f ? 0.0f : (degrees > 180.0f ? 180.0f : degrees);
  return static_cast<int>(MIN_US + bounded * (MAX_US - MIN_US) / 180.0f + 0.5f);
}

inline uint32_t dutyForMicroseconds(int pulseUs) {
  const int bounded = pulseUs < MIN_US ? MIN_US : (pulseUs > MAX_US ? MAX_US : pulseUs);
  return (static_cast<uint32_t>(bounded) * MAX_DUTY + PERIOD_US - 1UL) / PERIOD_US;
}
}