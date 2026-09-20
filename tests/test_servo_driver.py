"""Compile the real pulse conversion and reproduce the installed backend maths."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_servo_pulse_conversion_preserves_small_commands(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("A host C++ compiler is needed for the firmware pulse test")
    sketch = Path(__file__).resolve().parents[1] / "app_lab/braccio_remote_agent/sketch"
    source = tmp_path / "pulse_test.cpp"
    source.write_text(r'''
#include "BraccioPulse.hpp"
#include <cassert>
#include <cstdio>

static uint32_t backendTicks(float degrees) {
  const uint32_t duty = BraccioPulse::dutyForMicroseconds(BraccioPulse::forAngle(degrees));
  return (duty * 20000UL / 65535UL) / 4UL;
}

int main() {
  assert(BraccioPulse::forAngle(0.0f) == 500);
  assert(BraccioPulse::forAngle(90.0f) == 1500);
  assert(BraccioPulse::forAngle(180.0f) == 2500);
  assert(BraccioPulse::forAngle(-10.0f) == 500);
  assert(BraccioPulse::forAngle(200.0f) == 2500);
  for (int pulse = 500; pulse <= 2500; ++pulse) {
    const uint32_t duty = BraccioPulse::dutyForMicroseconds(pulse);
    assert(duty * 20000UL / 65535UL == static_cast<uint32_t>(pulse));
  }
  assert(backendTicks(180.0f) != backendTicks(179.25f));
  assert(backendTicks(10.0f) != backendTicks(10.768f));
  for (int tenths = 0; tenths <= 1792; ++tenths) {
    const float degrees = tenths / 10.0f;
    assert(backendTicks(degrees + 0.75f) > backendTicks(degrees));
  }
  std::puts("All pulses preserved before the backend's 4 us tick; 0.75 degree steps change output");
}
''')
    executable = tmp_path / "pulse_test"
    subprocess.run([compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(sketch),
                    str(source), "-o", str(executable)], check=True, capture_output=True, text=True)
    result = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
    assert "0.75 degree steps change output" in result.stdout