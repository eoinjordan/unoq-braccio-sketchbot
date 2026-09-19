import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { deadzone, readGamepad, GamepadGate, boundedPose } from "../src/input.js";
import { modelRotations } from "../src/robot.js";

const settings = {
  gamepad_enabled: true, gamepad_deadzone: 0.2, gamepad_enable_button: 4,
  gamepad_stop_button: 1, gamepad_axes: [0, 1, 3, 2], gamepad_invert: [false, true, true, false],
  gamepad_open_button: 6, gamepad_close_button: 7,
};
const pad = () => ({ id: "Test controller", index: 0, connected: true, axes: [0, 0, 0, 0],
  buttons: Array.from({ length: 8 }, () => ({ pressed: false })) });

test("deadzone ignores drift, missing and nonfinite axes", () => {
  for (const value of [0, 0.19, -0.19, undefined, NaN, Infinity]) assert.equal(deadzone(value, 0.2), 0);
  assert.equal(deadzone(1, 0.2), 1);
  assert.equal(deadzone(-1, 0.2), -1);
});

test("no movement without a held enable button", () => {
  const controller = pad(); controller.axes[0] = 1;
  assert.equal(readGamepad(controller, settings).enabled, false);
  controller.buttons[4].pressed = true;
  assert.deepEqual(readGamepad(controller, settings).deltas.map(value => value || 0), [1, 0, 0, 0]);
});

test("stop takes priority over enable", () => {
  const controller = pad(); controller.buttons[4].pressed = true; controller.buttons[1].pressed = true;
  assert.equal(readGamepad(controller, settings).stop, true);
  assert.equal(readGamepad(controller, settings).enabled, false);
});

test("disconnect and disabled setting suppress all movement", () => {
  const controller = pad(); controller.buttons[4].pressed = true; controller.axes[0] = 1;
  assert.equal(readGamepad(controller, { ...settings, gamepad_enabled: false }).enabled, false);
  controller.connected = false;
  assert.equal(readGamepad(controller, settings).enabled, false);
});

test("a controller connected with enable held must return to neutral", () => {
  const gate = new GamepadGate(); const controller = pad();
  controller.buttons[4].pressed = true; controller.axes[0] = 1;
  assert.equal(gate.read(controller, settings).enabled, false);
  controller.buttons[4].pressed = false; controller.axes[0] = 0;
  gate.read(controller, settings);
  controller.buttons[4].pressed = true; controller.axes[0] = 1;
  assert.equal(gate.read(controller, settings).enabled, true);
  gate.reset();
  assert.equal(gate.read(controller, settings).enabled, false);
});

test("mapped axes and inversion are respected", () => {
  const controller = pad(); controller.buttons[4].pressed = true; controller.axes = [1, 1, -1, -1];
  assert.deepEqual(readGamepad(controller, settings).deltas, [1, -1, 1, -1]);
});

test("gripper buttons require enable and conflicting presses do nothing", () => {
  const controller = pad(); controller.buttons[7].pressed = true;
  assert.equal(readGamepad(controller, settings).grip, null);
  controller.buttons[4].pressed = true;
  assert.equal(readGamepad(controller, settings).grip, "close");
  controller.buttons[6].pressed = true;
  assert.equal(readGamepad(controller, settings).grip, null);
  controller.buttons[7].pressed = false;
  assert.equal(readGamepad(controller, settings).grip, "open");
  controller.buttons[1].pressed = true;
  assert.equal(readGamepad(controller, settings).grip, null);
});

test("preview changes are bounded and never exceed a joint limit", () => {
  assert.deepEqual(boundedPose([179.8, 15.2], [100, -100], [[0, 180], [15, 165]], 0.75), [180, 15]);
});

for (const angle of [-60, 0, 60]) {
  test(`3D model and paper agree with arm coordinates at ${angle} degrees`, () => {
    const workspace = { paper: { rotation_deg: angle }, servo_calibration: {
      base: { offset: 90, sign: 1 }, shoulder: { offset: 0, sign: 1 },
      elbow: { offset: 90, sign: 1 }, wrist_vertical: { offset: 90, sign: 1 },
    } };
    const rotations = modelRotations(workspace, [90 + angle, 56.4, 25, 23.6, 90, 90]);
    const base = new THREE.Group(); base.rotation.y = rotations.base;
    const shoulder = new THREE.Group(); shoulder.position.y = 82; shoulder.rotation.z = rotations.shoulder; base.add(shoulder);
    const elbow = new THREE.Group(); elbow.position.x = 125; elbow.rotation.z = rotations.elbow; shoulder.add(elbow);
    const wrist = new THREE.Group(); wrist.position.x = 125; wrist.rotation.z = rotations.wrist; elbow.add(wrist);
    base.updateMatrixWorld(true);
    const tip = wrist.localToWorld(new THREE.Vector3(163, 0, 0));
    const paperCentre = new THREE.Vector3(235, 0, 0).applyAxisAngle(new THREE.Vector3(0, 1, 0), rotations.paper);
    const expectedAngle = angle * Math.PI / 180;
    assert.ok(Math.abs(tip.x - 235 * Math.cos(expectedAngle)) < 0.3);
    assert.ok(Math.abs(tip.z + 235 * Math.sin(expectedAngle)) < 0.3);
    assert.ok(Math.abs(tip.y - 10) < 0.3);
    assert.ok(Math.abs(tip.x - paperCentre.x) < 0.3);
    assert.ok(Math.abs(tip.z - paperCentre.z) < 0.3);
  });
}