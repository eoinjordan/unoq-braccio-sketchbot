// Self-contained Braccio driver for the Arduino UNO Q (arduino:zephyr).
//
// Neither the classic `Braccio` nor `Servo` library has an arduino:zephyr
// build, so we drive the six servos with `RoboServo` (which supports the UNO Q)
// on the Braccio shield pins and move them smoothly (a bounded step per 20 ms
// tick). Exposes the same `move_braccio(...)` entry point the remote agent's
// Python side calls over the App Lab Bridge.
//
// Angles are FLOATS and are written as microseconds rather than whole degrees.
// The paper sits ~175 mm from the base axis, so one degree of base rotation
// moves the pen ~3 mm and a 40 mm sheet spans only 13 degrees: rounded to whole
// degrees a portrait collapses into about a dozen columns. `write()` takes
// integer degrees, so `writeMicroseconds()` is what actually carries the
// fraction (~10.3 us per degree, so 0.1 deg is ~1 us).

#include "UnoQBraccioBridge.h"

#include <RoboServo.h>

namespace {
const int JOINTS = 6;
const int MIN_LIMITS[JOINTS] = {0, 15, 0, 0, 0, 10};
const int MAX_LIMITS[JOINTS] = {180, 165, 180, 180, 180, 110};
const int SERVO_PINS[JOINTS] = {11, 10, 9, 6, 5, 3};
const int SOFT_START_PIN = 12;

// MUST match RoboServo's own defaults (ROBOSERVO_DEFAULT_MIN_PULSE_US /
// _MAX_PULSE_US = 500/2500), because that is the band write(deg) used before
// this change. Any other band silently shifts every joint and invalidates the
// servo_calibration in config/workspace.yaml. The servos are attached with
// these limits explicitly so a library default change cannot move the arm.
const int MIN_PULSE_US = 500;
const int MAX_PULSE_US = 2500;
// Largest change applied per 20 ms tick, in degrees. Same slew rate as the
// original one-degree-per-step loop.
const float MAX_STEP_DEG = 1.0f;
// Below this the joint is treated as arrived, so the loop always terminates.
const float ARRIVED_DEG = 0.05f;

// Same 0-180 -> pulse mapping RoboServo::write() applies, but keeping the
// fraction: ~11.1 us per degree, so 0.1 deg is about 1 us.
int pulseFor(float degrees) {
  const float span = (float)(MAX_PULSE_US - MIN_PULSE_US);
  return (int)((float)MIN_PULSE_US + (degrees / 180.0f) * span + 0.5f);
}

RoboServo base;
RoboServo shoulder;
RoboServo elbow;
RoboServo wrist_ver;
RoboServo wrist_rot;
RoboServo gripper;

float current[JOINTS] = {90.0f, 45.0f, 180.0f, 180.0f, 90.0f, 10.0f};

float clampJoint(int index, float value) {
  if (value < MIN_LIMITS[index]) {
    return MIN_LIMITS[index];
  }
  if (value > MAX_LIMITS[index]) {
    return MAX_LIMITS[index];
  }
  return value;
}

void writeCurrent() {
  // Microseconds, not write(): write() quantises to whole degrees and would
  // discard exactly the precision this change exists to carry.
  base.writeMicroseconds(pulseFor(current[0]));
  shoulder.writeMicroseconds(pulseFor(current[1]));
  elbow.writeMicroseconds(pulseFor(current[2]));
  wrist_ver.writeMicroseconds(pulseFor(current[3]));
  wrist_rot.writeMicroseconds(pulseFor(current[4]));
  gripper.writeMicroseconds(pulseFor(current[5]));
}
}  // namespace

void setupBraccioBridge() {
  pinMode(SOFT_START_PIN, OUTPUT);
  digitalWrite(SOFT_START_PIN, HIGH);
  base.attach(SERVO_PINS[0], MIN_PULSE_US, MAX_PULSE_US);
  shoulder.attach(SERVO_PINS[1], MIN_PULSE_US, MAX_PULSE_US);
  elbow.attach(SERVO_PINS[2], MIN_PULSE_US, MAX_PULSE_US);
  wrist_ver.attach(SERVO_PINS[3], MIN_PULSE_US, MAX_PULSE_US);
  wrist_rot.attach(SERVO_PINS[4], MIN_PULSE_US, MAX_PULSE_US);
  gripper.attach(SERVO_PINS[5], MIN_PULSE_US, MAX_PULSE_US);
  writeCurrent();
}

bool move_braccio(
  float base_angle,
  float shoulder_angle,
  float elbow_angle,
  float wrist_vertical_angle,
  float wrist_rotation_angle,
  float gripper_angle
) {
  float target[JOINTS] = {
    clampJoint(0, base_angle),
    clampJoint(1, shoulder_angle),
    clampJoint(2, elbow_angle),
    clampJoint(3, wrist_vertical_angle),
    clampJoint(4, wrist_rotation_angle),
    clampJoint(5, gripper_angle)
  };

  for (int step = 0; step < 220; step++) {
    bool done = true;
    for (int i = 0; i < JOINTS; i++) {
      float delta = target[i] - current[i];
      if (fabsf(delta) <= ARRIVED_DEG) {
        current[i] = target[i];
        continue;
      }
      done = false;
      float move = delta > 0.0f ? MAX_STEP_DEG : -MAX_STEP_DEG;
      if (fabsf(delta) < MAX_STEP_DEG) {
        move = delta;
      }
      current[i] += move;
    }
    writeCurrent();
    if (done) {
      break;
    }
    delay(20);
  }
  return true;
}
