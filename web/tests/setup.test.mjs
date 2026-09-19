import test from "node:test";
import assert from "node:assert/strict";
import { deviceAddress, controllerUrl, installCommand, savedDevices } from "../src/setup-model.js";

test("local device names and private IP addresses receive the Studio port", () => {
  assert.equal(deviceAddress("unoq.local"), "http://unoq.local:7100");
  assert.equal(deviceAddress("192.168.1.12"), "http://192.168.1.12:7100");
  assert.equal(deviceAddress("http://localhost:17100/"), "http://localhost:17100");
  assert.equal(deviceAddress("https://robot.owner.ts.net"), "https://robot.owner.ts.net");
});

test("public insecure, credential and executable addresses are rejected", () => {
  for (const value of ["http://example.com", "javascript:alert(1)", "file:///etc/passwd", "https://user:pass@robot.local",
    "http://robot.local/?token=secret", "https://robot.local/admin", "robot.local ; curl bad", "http://robot$(id).local", "http://robot`id`.local", ""]) {
    assert.throws(() => deviceAddress(value));
  }
});

test("event links are explicit and do not carry credentials", () => {
  assert.equal(controllerUrl("unoq.local"), "http://unoq.local:7100/?event=1");
  assert.equal(controllerUrl("unoq.local", false), "http://unoq.local:7100/");
});

test("installer defaults to no flashing and no motion", () => {
  const command = installCommand();
  assert.ok(command.includes("mktemp"));
  assert.ok(!command.includes("--allow-motion"));
  assert.ok(!command.includes("--install-agent"));
  assert.throws(() => installCommand({ agent: true }), /servo power/);
  assert.ok(installCommand({ agent: true, servoPowerOff: true }).includes("--install-agent --servo-power-off"));
});

test("device storage discards malformed or unsafe records", () => {
  assert.deepEqual(savedDevices("not-json"), []);
  assert.deepEqual(savedDevices("{}"), []);
  assert.deepEqual(savedDevices(JSON.stringify([{ name: "Robot", address: "unoq.local" }, { address: "http://public.example" }])),
    [{ name: "Robot", address: "http://unoq.local:7100" }]);
});