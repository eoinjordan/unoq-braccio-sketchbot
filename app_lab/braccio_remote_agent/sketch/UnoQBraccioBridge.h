#pragma once

// Angles are floats: the sketchbot streams tenths of a degree. One whole degree
// of base rotation sweeps the pen tip about 3 mm at the paper, which is far too
// coarse to draw a face -- see sketch_artist/kinematics.py ServoAngles.
void setupBraccioBridge();

bool move_braccio(
  float base_angle,
  float shoulder_angle,
  float elbow_angle,
  float wrist_vertical_angle,
  float wrist_rotation_angle,
  float gripper_angle
);
