import "@fontsource/space-grotesk/latin-400.css";
import "@fontsource/space-grotesk/latin-600.css";
import { createIcons, Bot, Settings2, Box, Radio, ShieldCheck, Gamepad2, LockKeyhole, Square,
  RotateCcw, Scan, ZoomIn, ZoomOut, UserRound, SlidersHorizontal, Camera, Pencil,
  Crosshair, Hand, Activity, X, Save, UnlockKeyhole, Minus, Plus, Grab, Play, ListChecks, MapPin, Video, Trash2, Download } from "lucide";
import { createRobotView } from "./robot.js";
import { boundedPose, GamepadGate, jointNames } from "./input.js";
import { installTabletCameraControls } from "./tablet.js";
import { withRequestTimeout } from "./http.js";

const icons = { Bot, Settings2, Box, Radio, ShieldCheck, Gamepad2, LockKeyhole, Square,
  RotateCcw, Scan, ZoomIn, ZoomOut, UserRound, SlidersHorizontal, Camera, Pencil,
  Crosshair, Hand, Activity, X, Save, UnlockKeyhole, Minus, Plus, Grab, Play, ListChecks, MapPin, Video, Trash2, Download };
const element = id => document.getElementById(id);
const queryAll = selector => [...document.querySelectorAll(selector)];
const labels = ["Base", "Shoulder", "Elbow", "Wrist tilt", "Wrist rotation", "Gripper"];
const restPose = [90, 45, 180, 180, 90, 10];
let pose = [...restPose];
let limits = [[0, 180], [15, 165], [3, 180], [17, 180], [0, 180], [10, 110]];
let state = null;
let mode = "preview";
let token = null;
let armingPending = false;
let controlGeneration = 0;
let selectedJoint = 0;
let targetEdited = false;
let holding = null;
let motionPending = false;
let noticeTimer;
let deviceReport = [];
let initialized = false;
let sceneKey = "";
let padIdentity = "";
let selectedPad = "auto";
let settingsBusy = false;
let taskPlan = null;
let previewTimer = null;
const frameUrls = {};
const gamepadGate = new GamepadGate();
const eventView = new URLSearchParams(location.search).get("event") === "1";
document.body.classList.toggle("event-view", eventView);
const tabletCameras = installTabletCameraControls({ getState: () => state, notify: message => notice(message),
  refreshIcons: () => createIcons({ icons }) });
element("camera-format").append(new Option("This tablet / phone", "tablet"));

function notice(message) {
  element("notice").textContent = message;
  element("notice").hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { element("notice").hidden = true; }, 6000);
}
async function api(path, body) {
  return withRequestTimeout(path.includes("diagnostics") ? 35000 : 8000, async signal => {
    const response = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store", signal,
    });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.error || `Request failed (${response.status})`);
      error.retryable = response.status === 409 && data.retryable === true;
      throw error;
    }
    return data;
  });
}
function stopHolding() {
  holding = null;
  queryAll(".holding").forEach(button => button.classList.remove("holding"));
}
async function disarm(report = false) {
  controlGeneration++; stopHolding(); token = null; gamepadGate.reset(); updateButtons();
  clearTimeout(previewTimer); previewTimer = null; taskPlan = null; updateTask();
  try {
    await api("/api/control/stop", {});
    if (report) notice("Stopped and disarmed. Servo power remains on.");
  } catch { if (report) notice("Stop not confirmed. Use the physical power cutoff if needed."); }
}
function releaseOwnedSession() {
  stopHolding(); gamepadGate.reset();
  if (token || armingPending) return disarm();
}
function updateButtons() {
  const ownArmed = Boolean(token && mode === "real");
  const armButton = element("arm-button");
  armButton.disabled = mode !== "real" || !state?.motion_enabled || !state?.arm.connected ||
    (state?.tools.active === "sketch" && !state?.paper_check.ok) || Boolean(state?.armed && !token) ||
    (eventView && !state?.controls.child_mode);
  armButton.classList.toggle("armed", ownArmed);
  armButton.querySelector("span").textContent = ownArmed ? "Armed" : "Disarmed";
  armButton.setAttribute("aria-label", ownArmed ? "Armed" : "Disarmed");
  armButton.title = ownArmed ? "Disarm controls" : "Arm controls";
  element("apply-pose").disabled = !ownArmed;
  element("scene-mode").textContent = mode === "real" ? "TARGET PREVIEW" : "PREVIEW";
  updateTask();
}

function updateTask() {
  const gripper = state?.tools.active === "gripper";
  element("prepare-task").querySelector("span").textContent = gripper ? "Plan pick & place" : "Plan test square";
  element("contact-check").hidden = gripper;
  element("play-task").disabled = !taskPlan || mode !== "preview";
  element("run-task").disabled = !token || mode !== "real" || !taskPlan || taskPlan.complete ||
    (!gripper && (state?.controls.child_mode || !element("contact-confirmed").checked));
  element("task-status").textContent = taskPlan ?
    (taskPlan.complete ? "Task complete" : `${taskPlan.index + 1} / ${taskPlan.count} - ${taskPlan.label}`) : "No task planned";
  if (mode === "preview" && taskPlan?.previewLabel) element("task-status").textContent = taskPlan.previewLabel;
}
function selectJoint(index) {
  selectedJoint = index;
  element("selected-label").textContent = `${String(index + 1).padStart(2, "0")} / ${labels[index]}`;
  queryAll(".joint").forEach((joint, jointIndex) => joint.classList.toggle("selected", jointIndex === index));
  robot?.select(index);
}
function renderPose() {
  pose.forEach((value, index) => {
    const slider = element(`joint-${index}`);
    if (slider) { slider.value = value; element(`angle-${index}`).textContent = `${value.toFixed(1)}\u00b0`; }
  });
  robot?.setPose(pose);
  element("pose-label").textContent = mode === "real" && !targetEdited ? "Commanded pose" : "Preview target";
}
function renderJoints() {
  element("joint-controls").innerHTML = labels.map((label, index) => `
    <div class="joint${index === selectedJoint ? " selected" : ""}">
      <div class="joint-heading"><button type="button" data-select="${index}">${label}</button><output id="angle-${index}"></output></div>
      <input id="joint-${index}" type="range" min="${limits[index][0]}" max="${limits[index][1]}" step="0.1" aria-label="${label} preview angle">
      <div class="jog-row"><button class="icon-button nudge" data-joint="${index}" data-direction="-1" title="Decrease ${label.toLowerCase()}" aria-label="Decrease ${label.toLowerCase()}"><i data-lucide="minus"></i></button><small>${limits[index][0]} - ${limits[index][1]}</small><button class="icon-button nudge" data-joint="${index}" data-direction="1" title="Increase ${label.toLowerCase()}" aria-label="Increase ${label.toLowerCase()}"><i data-lucide="plus"></i></button></div>
    </div>`).join("");
  queryAll("[data-select]").forEach(button => button.addEventListener("click", () => selectJoint(Number(button.dataset.select))));
  pose.forEach((value, index) => element(`joint-${index}`).addEventListener("input", event => {
    stopHolding(); targetEdited = true; pose[index] = Number(event.target.value); selectJoint(index); renderPose();
  }));
  queryAll(".nudge").forEach(button => bindHold(button, () => ({ joint: Number(button.dataset.joint), direction: Number(button.dataset.direction) })));
  createIcons({ icons }); renderPose();
}
function bindHold(button, action) {
  button.addEventListener("pointerdown", event => {
    if (event.button !== 0 || button.disabled) return;
    if (mode === "real" && !token) { notice("Real-arm controls are disarmed."); return; }
    event.preventDefault(); button.setPointerCapture(event.pointerId);
    stopHolding(); holding = action(); button.classList.add("holding"); applyHeld();
  });
  for (const eventName of ["pointerup", "pointercancel", "lostpointercapture"]) button.addEventListener(eventName, stopHolding);
  button.addEventListener("keydown", event => {
    if (![" ", "Enter"].includes(event.key) || event.repeat || button.disabled) return;
    if (mode === "real" && !token) return;
    event.preventDefault(); stopHolding(); holding = action(); button.classList.add("holding"); applyHeld();
  });
  button.addEventListener("keyup", stopHolding);
}
async function sendMotion(payload) {
  if (motionPending || !token || mode !== "real" || document.hidden) return;
  if (eventView && !state?.controls.child_mode) { await disarm(); notice("Event controls require child mode enabled by the operator."); return; }
  motionPending = true;
  try {
    const result = await api("/api/control/move", { ...payload, token, held: true });
    if (state) state.arm.pose = result.pose;
    if (!targetEdited) { pose = [...result.pose]; renderPose(); }
  } catch (error) {
    if (!error.retryable) { await disarm(); notice(error.message); }
  }
  finally { motionPending = false; }
}
function applyHeld() {
  if (!holding || document.hidden || element("settings").open || element("arm-confirm").open) return;
  if (holding.task) { advanceTask(); return; }
  if (holding.grip) {
    const target = [...(mode === "real" && state?.arm.pose ? state.arm.pose : pose)];
    target[5] = state.tools.gripper[holding.grip === "open" ? "open_deg" : "closed_deg"];
    selectJoint(5);
    if (mode === "real") { targetEdited = false; sendMotion({ angles: target }); }
    else { pose = boundedPose(pose, target.map((value, index) => value - pose[index]), limits, state.controls.step_deg); targetEdited = true; renderPose(); }
    return;
  }
  if (holding.target) { if (mode === "real") sendMotion({ angles: [...pose] }); return; }
  const { joint, direction } = holding;
  selectJoint(joint);
  const step = Math.min(state?.controls.step_deg || 0.75, state?.controls.child_mode ? 0.75 : 2);
  if (mode === "real") { targetEdited = false; sendMotion({ joint: jointNames[joint], delta: direction * step }); }
  else {
    const deltas = pose.map((value, index) => index === joint ? direction * step : 0);
    pose = boundedPose(pose, deltas, limits, step); targetEdited = true; renderPose();
  }
}
let robot = null;
try {
  robot = createRobotView(element("robot-view"), selectJoint, async (localX, localY, target) => {
    try {
      const result = await api("/api/control/preview", target || { x: Math.max(0, Math.min(state.workspace.paper.width_mm, localX)), y: Math.max(0, Math.min(state.workspace.paper.height_mm, localY)) });
      targetEdited = true; pose = result.angles; renderPose();
    } catch (error) { notice(error.message); }
  });
} catch (error) { element("model-status").textContent = "3D view unavailable"; notice(`WebGL unavailable: ${error.message}`); }
renderJoints();
bindHold(element("apply-pose"), () => ({ target: true }));
bindHold(element("run-task"), () => ({ task: true }));
bindHold(element("open-grip"), () => ({ grip: "open" }));
bindHold(element("close-grip"), () => ({ grip: "close" }));
element("view-reset").onclick = () => robot?.resetView();
element("view-top").onclick = () => robot?.topView();
element("view-in").onclick = () => robot?.zoom(0.85);
element("view-out").onclick = () => robot?.zoom(1.15);
element("rest-preview").onclick = () => { targetEdited = true; pose = [...restPose]; renderPose(); };
element("hover-preview").onclick = async () => {
  if (!state) return;
  try {
    const target = state.tools.active === "gripper" ? { ...state.tools.gripper.pick, z: state.tools.gripper.lift_z_mm } :
      { x: state.workspace.paper.width_mm / 2, y: state.workspace.paper.height_mm / 2 };
    const result = await api("/api/control/preview", target);
    targetEdited = true; pose = result.angles; renderPose();
  } catch (error) { notice(error.message); }
};
element("place-preview").onclick = async () => {
  try {
    const result = await api("/api/control/preview", { ...state.tools.gripper.place, z: state.tools.gripper.lift_z_mm });
    targetEdited = true; pose = result.angles; renderPose();
  } catch (error) { notice(error.message); }
};
queryAll("input[name=tool]").forEach(input => input.addEventListener("change", async () => {
  try {
    await disarm(); await api("/api/settings/tools", { active: input.value });
    targetEdited = false; element("contact-confirmed").checked = false;
    await refreshState(); fillForms();
  } catch (error) { notice(error.message); await refreshState(); }
}));
element("contact-confirmed").onchange = updateTask;
element("prepare-task").onclick = async () => {
  if (!state) return;
  element("prepare-task").disabled = true;
  try {
    await disarm(); element("contact-confirmed").checked = false;
    taskPlan = await api("/api/control/task/prepare", { kind: state.tools.active === "gripper" ? "pick_place" : "test_sketch",
      ...(state.arm.connected ? {} : { start: pose }) });
    pose = [...taskPlan.start]; targetEdited = true; renderPose(); updateTask();
  } catch (error) { notice(error.message); }
  finally { element("prepare-task").disabled = false; }
};
element("play-task").onclick = () => {
  if (!taskPlan || mode !== "preview") return;
  clearTimeout(previewTimer);
  let index = 0;
  const plan = taskPlan;
  const frame = () => {
    if (plan !== taskPlan || mode !== "preview") return;
    const waypoint = plan.waypoints[index];
    pose = [...waypoint.angles]; targetEdited = true; renderPose();
    plan.previewLabel = `Preview ${index + 1} / ${plan.count} - ${waypoint.label}`;
    updateTask();
    if (++index < plan.waypoints.length) previewTimer = setTimeout(frame, 450);
    else { previewTimer = null; plan.previewLabel = "Preview complete"; updateTask(); }
  };
  frame();
};
async function advanceTask() {
  if (motionPending || !token || !taskPlan || mode !== "real" || document.hidden) return;
  motionPending = true;
  const generation = controlGeneration;
  try {
    const result = await api("/api/control/task/step", { token, held: true, task_id: taskPlan.id,
      contact_confirmed: element("contact-confirmed").checked });
    if (generation !== controlGeneration) return;
    if (result.task) taskPlan = { ...taskPlan, ...result.task };
    state.arm.pose = result.pose; pose = [...result.pose]; targetEdited = false; renderPose();
    if (result.complete) { token = null; stopHolding(); }
    updateButtons();
  } catch (error) { if (!error.retryable) { await disarm(); notice(error.message); } }
  finally { motionPending = false; }
}
queryAll("input[name=mode]").forEach(input => input.addEventListener("change", async () => {
  await disarm(); mode = input.value; targetEdited = false;
  if (state?.arm.pose) pose = [...state.arm.pose];
  renderPose(); updateButtons();
}));
element("stop").onclick = () => disarm(true);
element("arm-button").onclick = () => {
  if (token) { disarm(); return; }
  stopHolding(); element("operator-confirmed").checked = false; element("confirm-arm").disabled = true;
  element("tool-confirmed").checked = false;
  element("tool-confirm-label").hidden = state.tools.active !== "gripper";
  element("arm-confirm").showModal();
};
function confirmEnabled() {
  element("confirm-arm").disabled = !element("operator-confirmed").checked ||
    (state?.tools.active === "gripper" && !element("tool-confirmed").checked);
}
element("operator-confirmed").onchange = confirmEnabled;
element("tool-confirmed").onchange = confirmEnabled;
element("confirm-arm").onclick = async () => {
  const generation = ++controlGeneration;
  armingPending = true;
  element("confirm-arm").disabled = true;
  try {
    const result = await api("/api/control/arm", { confirmed: element("operator-confirmed").checked,
      tool_confirmed: element("tool-confirmed").checked });
    if (generation !== controlGeneration || document.hidden || !document.hasFocus()) { await disarm(); return; }
    controlGeneration++;
    token = result.token; gamepadGate.reset(); element("arm-confirm").close(); updateButtons();
  } catch (error) { notice(error.message); }
  finally { armingPending = false; confirmEnabled(); }
};
queryAll(".close-dialog").forEach(button => button.onclick = () => {
  if (button.closest("dialog").id === "arm-confirm") disarm();
  button.closest("dialog").close();
});
queryAll("dialog").forEach(dialog => dialog.addEventListener("close", () => { stopHolding(); gamepadGate.reset(); }));
document.addEventListener("keydown", event => { if (event.key === "Escape") disarm(); });
document.addEventListener("keyup", event => { if ([" ", "Enter"].includes(event.key)) stopHolding(); });
window.addEventListener("pointerup", stopHolding);
window.addEventListener("blur", releaseOwnedSession);
document.addEventListener("visibilitychange", () => { if (document.hidden) releaseOwnedSession(); });
window.addEventListener("pagehide", () => {
  const ownedSession = Boolean(token || armingPending);
  controlGeneration++; token = null; stopHolding();
  if (ownedSession) navigator.sendBeacon("/api/control/stop", new Blob(["{}"], { type: "application/json" }));
});

function settingsTab(name) {
  queryAll("[data-tab]").forEach(tab => tab.setAttribute("aria-selected", String(tab.dataset.tab === name)));
  queryAll("[data-pane]").forEach(pane => { pane.hidden = pane.dataset.pane !== name; });
  element("settings-error").hidden = true;
}
function openSettings(tab = "cameras", role = null) {
  disarm(); fillForms();
  if (role) { element("camera-role").value = role; fillCameraForm(); }
  settingsTab(tab); element("settings").showModal();
}
element("open-settings").onclick = () => openSettings();
element("tool-settings").onclick = () => openSettings("tools");
queryAll(".camera-setup").forEach(button => button.onclick = () => openSettings("cameras", button.dataset.role));
queryAll("[data-tab]").forEach(button => button.onclick = () => settingsTab(button.dataset.tab));
function setValue(id, value) { element(id).value = value ?? ""; }
function numeric(id) { return Number(element(id).value); }
function fillCameraForm() {
  if (!state) return;
  const spec = state.cameras[element("camera-role").value] || {};
  element("camera-enabled").checked = spec.enabled !== false;
  const format = spec.format || (spec.url ? "snapshot" : spec.serial ? "serial" : "usb");
  setValue("camera-format", format);
  document.querySelector(`input[name=mount][value=${spec.mounted_on_arm === false ? "fixed" : "wrist"}]`).checked = true;
  for (const [id, value] of Object.entries({ "camera-url": spec.url || "", "camera-device": spec.device ?? 0,
    "camera-usb-id": spec.usb_id || "", "camera-serial": spec.serial || "auto", "camera-baud": spec.baud || 921600,
    "camera-width": spec.width || 640, "camera-height": spec.height || 480, "camera-fps": spec.fps || 15,
    "camera-rotation": spec.rotation || 0, "camera-pixel": spec.pixel_format || "auto" })) setValue(id, value);
  element("camera-mirror").checked = Boolean(spec.mirror);
  cameraFields();
}
function cameraFields() {
  const format = element("camera-format").value;
  element("url-field").hidden = ["usb", "serial", "tablet"].includes(format);
  element("usb-fields").hidden = format !== "usb";
  element("serial-fields").hidden = format !== "serial";
}
element("camera-role").onchange = fillCameraForm;
element("camera-format").onchange = cameraFields;
element("detected-cameras").onchange = event => {
  const selected = deviceReport[Number(event.target.value)];
  if (event.target.value === "" || !selected) return;
  setValue("camera-format", "usb"); setValue("camera-device", selected.device);
  setValue("camera-usb-id", selected.usb_id || "");
  document.querySelector("input[name=mount][value=fixed]").checked = true;
  cameraFields();
};
element("paper-side").onchange = event => { if (event.target.value !== "custom") setValue("paper-rotation", event.target.value); };
element("paper-rotation").oninput = () => {
  const angle = element("paper-rotation").value;
  setValue("paper-side", ["0", "60", "-60", "180"].includes(angle) ? angle : "custom");
};
element("gamepad-deadzone").oninput = event => { element("deadzone-value").textContent = event.target.value; };
element("controller-device").onchange = event => { selectedPad = event.target.value; disarm(); };
function fillForms() {
  if (!state) return;
  fillCameraForm();
  const { paper, links, pen } = state.workspace;
  for (const [id, value] of Object.entries({ "paper-rotation": paper.rotation_deg || 0, "paper-x": paper.origin_x_mm,
    "paper-y": paper.origin_y_mm, "paper-width": paper.width_mm, "paper-height": paper.height_mm,
    "pen-down": pen.down_z_mm, "pen-up": pen.up_z_mm, "step-deg": state.controls.step_deg,
    "gamepad-deadzone": state.controls.gamepad_deadzone, "enable-button": state.controls.gamepad_enable_button,
    "stop-button": state.controls.gamepad_stop_button })) setValue(id, value);
  element("paper-rotation").oninput();
  element("paper-reach").textContent = state.paper_check.ok ? `Reach verified / ${state.paper_check.samples} samples / ${state.paper_check.margin_deg} deg margin` : state.paper_check.error;
  element("paper-reach").classList.toggle("failed", !state.paper_check.ok);
  element("child-mode").checked = state.controls.child_mode;
  element("gamepad-enabled").checked = state.controls.gamepad_enabled;
  element("deadzone-value").textContent = state.controls.gamepad_deadzone;
  queryAll("[data-link]").forEach(input => { input.value = links[input.dataset.link]; });
  element("advanced-workspace").value = JSON.stringify(state.workspace, null, 2);
  const grip = state.tools.gripper;
  for (const [id, key] of Object.entries({ "grip-length": "length_mm", "grip-pitch": "pitch_deg",
    "grip-open": "open_deg", "grip-closed": "closed_deg", "grip-clearance": "clearance_mm", "grip-lift": "lift_z_mm" })) setValue(id, grip[key]);
  for (const target of ["pick", "place"]) for (const axis of ["x", "y", "z"]) setValue(`${target}-${axis}`, grip[target][axis]);
  element("axis-mappings").innerHTML = labels.slice(0, 4).map((label, index) => `<div class="axis-row"><span>${label}</span><label>Axis<select id="axis-${index}">${Array.from({ length: 16 }, (_, axis) => `<option value="${axis}"${axis === state.controls.gamepad_axes[index] ? " selected" : ""}>${axis}</option>`).join("")}</select></label><label class="check-label"><input id="invert-${index}" type="checkbox"${state.controls.gamepad_invert[index] ? " checked" : ""}>Invert</label></div>`).join("");
  element("axis-mappings").insertAdjacentHTML("beforeend", `<div class="form-grid"><label>Open gripper button<input id="open-button" type="number" min="0" max="31" value="${state.controls.gamepad_open_button}"></label><label>Close gripper button<input id="close-button" type="number" min="0" max="31" value="${state.controls.gamepad_close_button}"></label></div>`);
}
async function saveSettings(path, payload, success) {
  if (settingsBusy) return;
  settingsBusy = true; element("settings-error").hidden = true;
  try {
    await disarm(); await api(path, payload); await refreshState(); fillForms(); notice(success);
  } catch (error) { element("settings-error").textContent = error.message; element("settings-error").hidden = false; }
  finally { settingsBusy = false; }
}
element("camera-form").onsubmit = event => {
  event.preventDefault();
  const deviceText = element("camera-device").value.trim();
  const spec = { enabled: element("camera-enabled").checked, format: element("camera-format").value,
    mounted_on_arm: document.querySelector("input[name=mount]:checked").value === "wrist",
    url: element("camera-url").value, device: /^\d+$/.test(deviceText) ? Number(deviceText) : deviceText,
    usb_id: element("camera-usb-id").value, serial: element("camera-serial").value, baud: numeric("camera-baud"),
    width: numeric("camera-width"), height: numeric("camera-height"), fps: numeric("camera-fps"),
    rotation: numeric("camera-rotation"), mirror: element("camera-mirror").checked, pixel_format: element("camera-pixel").value };
  saveSettings("/api/settings/camera", { role: element("camera-role").value, spec }, "Camera settings saved. Controls disarmed.");
};
element("paper-form").onsubmit = event => {
  event.preventDefault(); saveSettings("/api/settings/workspace", { paper: { rotation_deg: numeric("paper-rotation"),
    origin_x_mm: numeric("paper-x"), origin_y_mm: numeric("paper-y"), width_mm: numeric("paper-width"), height_mm: numeric("paper-height") } }, "Paper settings saved. Physical calibration needs checking.");
};
element("geometry-form").onsubmit = event => {
  event.preventDefault(); const links = {};
  queryAll("[data-link]").forEach(input => { links[input.dataset.link] = Number(input.value); });
  saveSettings("/api/settings/workspace", { links, pen: { down_z_mm: numeric("pen-down"), up_z_mm: numeric("pen-up") } }, "Arm geometry saved. Physical calibration needs checking.");
};
element("save-advanced").onclick = () => {
  try { saveSettings("/api/settings/workspace", JSON.parse(element("advanced-workspace").value), "Advanced workspace saved. Controls disarmed."); }
  catch (error) { element("settings-error").textContent = error.message; element("settings-error").hidden = false; }
};
element("controller-form").onsubmit = event => {
  event.preventDefault(); saveSettings("/api/settings/controls", { child_mode: element("child-mode").checked,
    step_deg: numeric("step-deg"), gamepad_enabled: element("gamepad-enabled").checked, gamepad_deadzone: numeric("gamepad-deadzone"),
    gamepad_enable_button: numeric("enable-button"), gamepad_stop_button: numeric("stop-button"),
    gamepad_open_button: numeric("open-button"), gamepad_close_button: numeric("close-button"),
    gamepad_axes: [0, 1, 2, 3].map(index => numeric(`axis-${index}`)),
    gamepad_invert: [0, 1, 2, 3].map(index => element(`invert-${index}`).checked) }, "Controller settings saved. Controls disarmed.");
};
element("tools-form").onsubmit = event => {
  event.preventDefault();
  const target = name => Object.fromEntries(["x", "y", "z"].map(axis => [axis, numeric(`${name}-${axis}`)]));
  saveSettings("/api/settings/tools", { gripper: { length_mm: numeric("grip-length"), pitch_deg: numeric("grip-pitch"),
    open_deg: numeric("grip-open"), closed_deg: numeric("grip-closed"), clearance_mm: numeric("grip-clearance"),
    lift_z_mm: numeric("grip-lift"), pick: target("pick"), place: target("place") } }, "Gripper settings saved. Controls disarmed.");
};

async function refreshState() {
  const generation = controlGeneration;
  let incoming;
  try { incoming = await api("/api/control/state"); }
  catch (error) { if (generation !== controlGeneration) return; throw error; }
  if (generation !== controlGeneration) return;
  state = incoming;
  tabletCameras.update();
  if (taskPlan && incoming.task?.id === taskPlan.id) Object.assign(taskPlan, incoming.task);
  else if (taskPlan && !taskPlan.complete && !incoming.task && !motionPending) { taskPlan = null; clearTimeout(previewTimer); }
  if (token && !incoming.armed) { token = null; stopHolding(); gamepadGate.reset(); }
  const connection = element("connection");
  connection.className = `status ${incoming.arm.connected ? "connected" : "disconnected"}`;
  connection.setAttribute("role", "status");
  connection.setAttribute("aria-label", incoming.arm.connected ? "Arm connected" : "Arm offline");
  connection.innerHTML = `<span class="dot"></span>${incoming.arm.connected ? "Arm connected" : "Arm offline"}`;
  connection.title = incoming.arm.error || "Commanded joint targets; not encoder feedback";
  if (JSON.stringify(limits) !== JSON.stringify(incoming.limits)) { limits = incoming.limits; renderJoints(); }
  const nextKey = JSON.stringify([incoming.workspace, incoming.tools, incoming.cameras.face?.mounted_on_arm]);
  if (sceneKey !== nextKey) { sceneKey = nextKey; robot?.rebuild(incoming.tool_workspace, incoming.cameras, incoming.tools); }
  const gripperMode = incoming.tools.active === "gripper";
  queryAll("input[name=tool]").forEach(input => { input.checked = input.value === incoming.tools.active; });
  for (const id of ["open-grip", "close-grip", "place-preview"]) element(id).hidden = !gripperMode;
  element("hover-preview").querySelector("span").textContent = gripperMode ? "Pick hover" : "Paper centre";
  const paper = incoming.workspace.paper;
  const side = ({ 0: "Front", 60: "Left", "-60": "Right", 180: "Rear" })[paper.rotation_deg || 0] || `${paper.rotation_deg} deg`;
  element("paper-summary").textContent = `${side} / ${paper.width_mm} x ${paper.height_mm} mm`;
  if (gripperMode) element("paper-summary").textContent = `Gripper / ${incoming.tools.gripper.length_mm} mm / ${incoming.tools.gripper.pitch_deg} deg`;
  element("model-status").textContent = incoming.paper_check.ok ? "Paper reachable" : "Paper out of reach";
  if (gripperMode) element("model-status").textContent = "Grasp-point preview";
  element("child-state").hidden = !incoming.controls.child_mode;
  element("calibration-status").textContent = incoming.calibration_required ? "Calibration unverified" : "Calibration verified";
  if (eventView && !incoming.controls.child_mode) element("calibration-status").textContent = "Operator: enable child mode";
  for (const role of ["face", "gripper"]) element(`${role}-mount`).textContent = incoming.cameras[role]?.mounted_on_arm === false ? "Fixed" : "Wrist";
  if (!initialized) {
    if (incoming.arm.pose) pose = [...incoming.arm.pose];
    initialized = true; fillForms();
  } else if (mode === "real" && !targetEdited && incoming.arm.pose && !motionPending) pose = [...incoming.arm.pose];
  renderPose(); updateButtons();
}
async function pollState() {
  try { if (!initialized || !document.hidden) await refreshState(); }
  catch (error) {
    token = null; stopHolding(); gamepadGate.reset();
    if (state) state.arm.connected = false;
    element("connection").className = "status disconnected";
    element("connection").setAttribute("aria-label", "Connection lost");
    element("connection").innerHTML = '<span class="dot"></span>Connection lost';
    updateButtons();
  } finally { setTimeout(pollState, 1300); }
}
async function runChecks(probe = false) {
  const button = element("run-checks"); button.disabled = true;
  try {
    const report = await api(`/api/control/diagnostics${probe ? "?probe=1" : ""}`);
    deviceReport = report.devices;
    const select = element("detected-cameras"); select.textContent = ""; select.add(new Option("Custom input", ""));
    report.devices.forEach((device, index) => select.add(new Option(device.label, String(index))));
    element("startup-summary").textContent = `${report.arm.connected ? "Arm available" : "Preview only"} / ${report.devices.length} USB camera${report.devices.length === 1 ? "" : "s"} / ${report.paper.ok ? "workspace valid" : "workspace needs attention"}`;
    if (probe) notice(`Checks complete. Face: ${report.cameras.face.ok ? "available" : "unavailable"}; paper: ${report.cameras.gripper.ok ? "available" : "unavailable"}. No motion sent.`);
  } catch (error) { element("startup-summary").textContent = "Hardware check incomplete"; if (probe) notice(error.message); }
  finally { button.disabled = false; }
}
element("run-checks").onclick = () => runChecks(true);
async function pollCamera(role) {
  try {
    if (document.hidden || !state) return;
    if (state.cameras[role]?.enabled === false) throw new Error("Disabled");
    const { response, blob } = await withRequestTimeout(15000, async signal => {
      const response = await fetch(`/api/camera/${role}.jpg`, { cache: "no-store", signal });
      if (!response.ok) throw new Error((await response.json()).error || "Unavailable");
      return { response, blob: await response.blob() };
    });
    const nextUrl = URL.createObjectURL(blob);
    const image = element(`${role}-frame`);
    image.src = nextUrl; await image.decode();
    if (frameUrls[role]) URL.revokeObjectURL(frameUrls[role]);
    frameUrls[role] = nextUrl;
    image.hidden = false; element(`${role}-empty`).hidden = true;
    element(`${role}-status`).textContent = role === "face" ? (response.headers.get("X-Face-Detected") === "1" ? "Live / face detected" : "Live / no face detected") : `Live / ${image.naturalWidth} x ${image.naturalHeight}`;
    if (role === "face" && response.headers.get("X-Face-Detector") === "0") element(`${role}-status`).textContent = "Live / detector unavailable";
    if (response.headers.get("X-Camera-Source") === "tablet") element(`${role}-status`).textContent = `Tablet frame / ${image.naturalWidth} x ${image.naturalHeight}`;
    element(`${role}-status`).title = "";
  } catch (error) {
    element(`${role}-frame`).hidden = true; element(`${role}-empty`).hidden = false;
    element(`${role}-empty`).querySelector("span").textContent = error.message === "Disabled" ? "Camera disabled" : "Camera unavailable";
    element(`${role}-status`).textContent = error.message === "Disabled" ? "Disabled" : "No current frame";
    element(`${role}-status`).title = error.message;
  } finally { setTimeout(() => pollCamera(role), 900); }
}
queryAll(".capture").forEach(button => button.onclick = () => {
  const role = button.dataset.role;
  if (!frameUrls[role] || element(`${role}-frame`).hidden) { notice("No current camera frame."); return; }
  const link = document.createElement("a"); link.href = frameUrls[role]; link.download = `sketchbot-${role}-${Date.now()}.jpg`; link.click();
});
function gamepadTick() {
  let pads = [];
  try { pads = [...(navigator.getGamepads?.() || [])].filter(Boolean); }
  catch { pads = []; }
  if (window.__sketchbotNativePad?.connected) pads = [window.__sketchbotNativePad];
  const identity = pads.map(pad => `${pad.index}:${pad.id}`).join("|");
  if (identity !== padIdentity) {
    padIdentity = identity; gamepadGate.reset();
    const select = element("controller-device"); select.textContent = ""; select.add(new Option("First connected controller", "auto"));
    pads.forEach(pad => select.add(new Option(pad.id, String(pad.index))));
    select.value = selectedPad;
  }
  const pad = selectedPad === "auto" ? pads[0] : pads.find(candidate => candidate.index === Number(selectedPad));
  element("gamepad-label").textContent = pad ? (state?.controls.gamepad_enabled ? "Controller ready" : "Controller disabled") : "No controller";
  element("gamepad-status").title = pad?.id || "Bluetooth / USB gamepad";
  if (!state || document.hidden || element("settings").open || element("arm-confirm").open) return;
  const input = gamepadGate.read(pad, state.controls);
  if (input.stop) { if (token || holding) disarm(true); return; }
  if (!input.enabled || holding || (input.deltas.every(delta => delta === 0) && !input.grip)) return;
  const maximum = Math.min(state.controls.step_deg, state.controls.child_mode ? 0.75 : 2);
  const deltas = [...input.deltas.map(value => value * maximum), 0, 0];
  if (state.tools.active === "gripper" && input.grip) {
    const basePose = mode === "real" && state.arm.pose ? state.arm.pose : pose;
    deltas[5] = state.tools.gripper[input.grip === "open" ? "open_deg" : "closed_deg"] - basePose[5];
  }
  if (mode === "real") {
    if (!token || !state.arm.pose) return;
    targetEdited = false; sendMotion({ angles: boundedPose(state.arm.pose, deltas, limits, maximum) });
  } else { targetEdited = true; pose = boundedPose(pose, deltas, limits, maximum); renderPose(); }
}
window.addEventListener("gamepaddisconnected", releaseOwnedSession);
window.addEventListener("gamepadconnected", () => { gamepadGate.reset(); });
setInterval(() => { applyHeld(); gamepadTick(); }, 200);
createIcons({ icons });
pollState(); runChecks(); pollCamera("face"); pollCamera("gripper");