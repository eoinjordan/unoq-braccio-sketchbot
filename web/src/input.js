export const jointNames = ["base", "shoulder", "elbow", "wrist_vertical", "wrist_rotation", "gripper"];

export function deadzone(value, threshold) {
  if (!Number.isFinite(value) || !Number.isFinite(threshold) || threshold < 0 || threshold >= 1) return 0;
  const magnitude = Math.min(1, Math.abs(value));
  return magnitude <= threshold ? 0 : Math.sign(value) * (magnitude - threshold) / (1 - threshold);
}

export function readGamepad(pad, settings) {
  const idle = { enabled: false, stop: false, deltas: [0, 0, 0, 0], grip: null };
  if (!pad?.connected || !settings.gamepad_enabled) return idle;
  if (pad.buttons?.[settings.gamepad_stop_button]?.pressed) return { ...idle, stop: true };
  if (!pad.buttons?.[settings.gamepad_enable_button]?.pressed) return idle;
  const deltas = settings.gamepad_axes.map((axis, index) => {
    const value = deadzone(pad.axes?.[axis], settings.gamepad_deadzone);
    return settings.gamepad_invert[index] ? -value : value;
  });
  const open = Boolean(pad.buttons?.[settings.gamepad_open_button]?.pressed);
  const close = Boolean(pad.buttons?.[settings.gamepad_close_button]?.pressed);
  return { enabled: true, stop: false, deltas, grip: open === close ? null : open ? "open" : "close" };
}

export class GamepadGate {
  constructor() { this.reset(); }
  reset() { this.ready = false; this.identity = null; }
  read(pad, settings) {
    const state = readGamepad(pad, settings);
    if (!pad?.connected || this.identity !== `${pad.index}:${pad.id}`) {
      this.ready = false;
      this.identity = pad?.connected ? `${pad.index}:${pad.id}` : null;
    }
    const enableHeld = Boolean(pad?.buttons?.[settings.gamepad_enable_button]?.pressed);
    const neutral = (pad?.axes || []).every(value => Number.isFinite(value) && Math.abs(value) <= settings.gamepad_deadzone);
    if (!enableHeld && neutral && !state.stop) this.ready = true;
    return this.ready ? state : { enabled: false, stop: state.stop, deltas: [0, 0, 0, 0], grip: null };
  }
}

export function boundedPose(pose, deltas, limits, maximum) {
  return pose.map((value, index) => {
    const delta = Number.isFinite(deltas[index]) ? Math.max(-maximum, Math.min(maximum, deltas[index])) : 0;
    return Math.max(limits[index][0], Math.min(limits[index][1], value + delta));
  });
}