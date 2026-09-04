// Self-contained Braccio driver for the Arduino UNO Q (arduino:zephyr).
//
// The classic `Braccio` library has no arduino:zephyr build, so we drive the
// six servos directly with `Servo` on the Braccio shield pins and move them
// smoothly (one degree per 20 ms step). Exposes the same `move_braccio(...)`
// entry point the remote agent's Python side calls over the App Lab Bridge.

#include "UnoQBraccioBridge.h"

#include <Servo.h>

namespace {
const int JOINTS = 6;
const int MIN_LIMITS[JOINTS] = {0, 15, 0, 0, 0, 10};
const int MAX_LIMITS[JOINTS] = {180, 165, 180, 180, 180, 110};
const int SERVO_PINS[JOINTS] = {11, 10, 9, 6, 5, 3};
const int SOFT_START_PIN = 12;

Servo base;
Servo shoulder;
Servo elbow;
Servo wrist_ver;
Servo wrist_rot;
Servo gripper;

int current[JOINTS] = {90, 45, 180, 180, 90, 10};

int clampJoint(int index, int value) {
  if (value < MIN_LIMITS[index]) {
    return MIN_LIMITS[index];
  }
  if (value > MAX_LIMITS[index]) {
    return MAX_LIMITS[index];
  }
  return value;
}

void writeCurrent() {
  base.write(current[0]);
  shoulder.write(current[1]);
  elbow.write(current[2]);
  wrist_ver.write(current[3]);
  wrist_rot.write(current[4]);
  gripper.write(current[5]);
}
}  // namespace

void setupBraccioBridge() {
  pinMode(SOFT_START_PIN, OUTPUT);
  digitalWrite(SOFT_START_PIN, HIGH);
  base.attach(SERVO_PINS[0]);
  shoulder.attach(SERVO_PINS[1]);
  elbow.attach(SERVO_PINS[2]);
  wrist_ver.attach(SERVO_PINS[3]);
  wrist_rot.attach(SERVO_PINS[4]);
  gripper.attach(SERVO_PINS[5]);
  writeCurrent();
}

bool move_braccio(
  int base_angle,
  int shoulder_angle,
  int elbow_angle,
  int wrist_vertical_angle,
  int wrist_rotation_angle,
  int gripper_angle
) {
  int target[JOINTS] = {
    clampJoint(0, base_angle),
    clampJoint(1, shoulder_angle),
    clampJoint(2, elbow_angle),
    clampJoint(3, wrist_vertical_angle),
    clampJoint(4, wrist_rotation_angle),
    clampJoint(5, gripper_angle)
  };

  for (int step = 0; step < 110; step++) {
    bool done = true;
    for (int i = 0; i < JOINTS; i++) {
      if (current[i] < target[i]) {
        current[i]++;
        done = false;
      } else if (current[i] > target[i]) {
        current[i]--;
        done = false;
      }
    }
    writeCurrent();
    if (done) {
      break;
    }
    delay(20);
  }
  return true;
}
