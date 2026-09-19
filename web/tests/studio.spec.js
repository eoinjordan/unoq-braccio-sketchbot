import { test, expect } from "@playwright/test";

test.beforeEach(async ({ request }) => {
  await request.post("/api/control/stop", { data: {} });
  await request.post("/api/settings/tools", { data: { active: "sketch" } });
  await request.post("/api/settings/workspace", { data: { paper: { rotation_deg: 0 } } });
  await request.post("/api/settings/controls", { data: { child_mode: true, step_deg: 0.75, gamepad_enabled: false } });
  for (const role of ["face", "gripper"]) await request.post("/api/settings/camera", { data: { role, spec: { enabled: false } } });
});

async function ready(page) {
  await page.goto("/");
  await expect(page.locator("#connection")).toHaveText("Arm connected");
  await expect(page.locator("#model-status")).toHaveText("Paper reachable");
  await expect.poll(async () => Number(await page.locator("canvas").getAttribute("data-rendered"))).toBeGreaterThan(2);
}

async function canvasPixels(page) {
  return page.locator("canvas").evaluate(canvas => {
    const context = canvas.getContext("webgl2");
    const pixels = new Uint8Array(canvas.width * canvas.height * 4);
    context.readPixels(0, 0, canvas.width, canvas.height, context.RGBA, context.UNSIGNED_BYTE, pixels);
    let orange = 0;
    for (let index = 0; index < pixels.length; index += 32) {
      if (pixels[index] > 130 && pixels[index] > pixels[index + 1] * 1.3 && pixels[index] > pixels[index + 2] * 1.5) orange++;
    }
    return orange;
  });
}

test("desktop renders the real 3D scene, local assets and disarmed defaults", async ({ page }) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await ready(page);
  expect(await canvasPixels(page)).toBeGreaterThan(100);
  await expect(page.getByRole("radio", { name: "Preview", exact: true })).toBeChecked();
  await expect(page.getByRole("button", { name: "Hold to move" })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "../output/studio-desktop.png", fullPage: true });
  expect(errors).toEqual([]);
});

test("sliders animate only the preview and do not move the arm", async ({ page, request }) => {
  await ready(page);
  const before = (await (await request.get("/api/control/state")).json()).arm.pose;
  await page.getByRole("slider", { name: "Base preview angle" }).evaluate(slider => {
    slider.value = "120"; slider.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await expect.poll(async () => Number((await page.locator("canvas").getAttribute("data-pose")).split(",")[0])).toBeGreaterThan(118);
  const after = (await (await request.get("/api/control/state")).json()).arm.pose;
  expect(after).toEqual(before);
  await page.getByRole("button", { name: "Top view", exact: true }).click();
  expect(await canvasPixels(page)).toBeGreaterThan(50);
});

test("paper side saves, rear position fails clearly, and geometry persists", async ({ page, request }) => {
  await ready(page);
  await page.getByRole("button", { name: "Open setup" }).click();
  await page.getByRole("tab", { name: "Paper", exact: true }).click();
  await page.getByLabel("Paper side").selectOption("60");
  await page.getByRole("button", { name: "Save paper", exact: true }).click();
  await expect(page.locator("#paper-summary")).toContainText("Left");
  await page.getByLabel("Paper side").selectOption("180");
  await page.getByRole("button", { name: "Save paper", exact: true }).click();
  await expect(page.locator("#settings-error")).toBeVisible();
  const state = await (await request.get("/api/control/state")).json();
  expect(state.workspace.paper.rotation_deg).toBe(60);
  expect(state.armed).toBe(false);
});

test("camera menu switches format, mount and orientation", async ({ page, request }) => {
  await ready(page);
  await page.getByRole("button", { name: "Face camera settings", exact: true }).click();
  await page.getByLabel("Enabled", { exact: true }).check();
  await page.getByLabel("Input format").selectOption("snapshot");
  await page.getByLabel("Camera URL").fill("http://127.0.0.1:1/capture");
  await page.getByText("Wrist-mounted", { exact: true }).click();
  await page.getByRole("combobox", { name: "Rotation", exact: true }).selectOption("90");
  await page.getByLabel("Mirror image").check();
  await page.screenshot({ path: "../output/studio-camera-setup.png", fullPage: true });
  await page.getByRole("button", { name: "Save camera", exact: true }).click();
  await expect(page.locator("#notice")).toContainText("Camera settings saved");
  const state = await (await request.get("/api/control/state")).json();
  expect(state.cameras.face.mounted_on_arm).toBe(true);
  expect(state.cameras.face.rotation).toBe(90);
  expect(state.cameras.face.mirror).toBe(true);
  expect(state.armed).toBe(false);
});

test("held touch control makes bounded simulator steps and stop disarms", async ({ page, request }) => {
  await ready(page);
  await page.getByText("Real arm", { exact: true }).click();
  const arm = page.getByRole("button", { name: "Disarmed", exact: true });
  await expect(arm).toBeEnabled();
  await arm.click();
  await page.getByLabel("Adult supervision, clear workspace and power cutoff within reach").check();
  await page.getByRole("button", { name: "Arm controls", exact: true }).click();
  await expect(page.getByRole("button", { name: "Armed", exact: true })).toBeVisible();
  const before = (await (await request.get("/api/control/state")).json()).arm.pose[0];
  const button = page.getByRole("button", { name: "Increase base", exact: true });
  await button.scrollIntoViewIfNeeded();
  const box = await button.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  const moved = page.waitForResponse(response => response.url().endsWith("/api/control/move"));
  await page.mouse.down();
  const response = await moved;
  await page.mouse.up();
  expect(response.status()).toBe(200);
  const result = await response.json();
  expect(result.pose[0] - before).toBeGreaterThan(0);
  expect(result.pose[0] - before).toBeLessThanOrEqual(0.75);
  await page.getByRole("button", { name: "Stop and disarm", exact: true }).click();
  await expect.poll(async () => (await (await request.get("/api/control/state")).json()).armed).toBe(false);
});

test("gamepad API input moves preview only and obeys enable", async ({ page, request }) => {
  await request.post("/api/settings/controls", { data: { gamepad_enabled: true } });
  await page.addInitScript(() => {
    window.testPad = { id: "Test Bluetooth controller", index: 0, connected: true, axes: [0, 0, 0, 0], buttons: Array.from({ length: 8 }, () => ({ pressed: false })) };
    Object.defineProperty(navigator, "getGamepads", { value: () => [window.testPad] });
  });
  await ready(page);
  await expect(page.locator("#gamepad-label")).toHaveText("Controller ready");
  const before = (await (await request.get("/api/control/state")).json()).arm.pose;
  await page.evaluate(() => { window.testPad.axes[0] = 1; window.testPad.buttons[4].pressed = true; });
  await expect.poll(async () => Number(await page.locator("#joint-0").inputValue())).toBeGreaterThan(before[0]);
  await page.evaluate(() => { window.testPad.buttons[4].pressed = false; });
  expect((await (await request.get("/api/control/state")).json()).arm.pose).toEqual(before);
});

test("held controls recover from unqueued busy replies without disarming", async ({ page, request }) => {
  await ready(page);
  await page.getByText("Real arm", { exact: true }).click();
  await page.getByRole("button", { name: "Disarmed", exact: true }).click();
  await page.getByLabel("Adult supervision, clear workspace and power cutoff within reach").check();
  await page.getByRole("button", { name: "Arm controls", exact: true }).click();
  await expect(page.getByRole("button", { name: "Armed", exact: true })).toBeVisible();
  let attempts = 0;
  await page.route("**/api/control/move", async route => {
    if (++attempts <= 2) {
      await route.fulfill({ status: 409, contentType: "application/json",
        body: JSON.stringify({ error: "Arm is busy; no move was queued", retryable: true }) });
    } else await route.continue();
  });
  const button = page.getByRole("button", { name: "Increase base", exact: true });
  const box = await button.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  const moved = page.waitForResponse(response => response.url().endsWith("/api/control/move") && response.status() === 200);
  await page.mouse.down();
  await moved;
  await page.mouse.up();
  expect(attempts).toBeGreaterThanOrEqual(3);
  await expect(page.getByRole("button", { name: "Armed", exact: true })).toBeVisible();
  expect((await (await request.get("/api/control/state")).json()).armed).toBe(true);
  await page.getByRole("button", { name: "Stop and disarm", exact: true }).click();
});

test("late pre-arm status cannot cancel a newly armed browser session", async ({ page }) => {
  await ready(page);
  await page.getByText("Real arm", { exact: true }).click();
  let release;
  let observed;
  const gate = new Promise(resolve => { release = resolve; });
  const captured = new Promise(resolve => { observed = resolve; });
  let delayed = false;
  await page.route("**/api/control/state", async route => {
    if (delayed) return route.continue();
    delayed = true;
    const response = await route.fetch();
    observed();
    await gate;
    await route.fulfill({ response });
  });
  await captured;
  await page.getByRole("button", { name: "Disarmed", exact: true }).click();
  await page.getByLabel("Adult supervision, clear workspace and power cutoff within reach").check();
  await page.getByRole("button", { name: "Arm controls", exact: true }).click();
  await expect(page.getByRole("button", { name: "Armed", exact: true })).toBeVisible();
  const delivered = page.waitForResponse(response => response.url().endsWith("/api/control/state"));
  release();
  await delivered;
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(page.getByRole("button", { name: "Armed", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Stop and disarm", exact: true }).click();
});

test("gripper setup and pick-place preview preserve the real commanded pose", async ({ page, request }) => {
  await ready(page);
  const before = (await (await request.get("/api/control/state")).json()).arm.pose;
  await page.locator(".taskbar").getByText("Gripper", { exact: true }).click();
  await expect(page.locator("canvas")).toHaveAttribute("data-tool", "gripper");
  await expect(page.getByRole("button", { name: "Open gripper", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Tool settings", exact: true }).click();
  await expect(page.getByLabel("Wrist to grasp point (mm)")).toHaveValue("100");
  await page.screenshot({ path: "../output/studio-gripper-setup.png", fullPage: true });
  await page.getByLabel("Closed angle (degrees)").fill("66");
  await page.getByRole("button", { name: "Save gripper", exact: true }).click();
  await expect(page.locator("#notice")).toContainText("Gripper settings saved");
  await page.getByRole("button", { name: "Close setup" }).click();
  await page.getByRole("button", { name: "Plan pick & place", exact: true }).click();
  await expect(page.locator("#task-status")).toContainText("1 / 9");
  await page.getByRole("button", { name: "Play task preview", exact: true }).click();
  await expect(page.locator("#task-status")).toHaveText("Preview complete", { timeout: 10000 });
  expect(await canvasPixels(page)).toBeGreaterThan(50);
  expect((await (await request.get("/api/control/state")).json()).arm.pose).toEqual(before);
  await page.screenshot({ path: "../output/studio-gripper.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "../output/studio-gripper-mobile.png", fullPage: true });
});

test("real gripper tasks require tool confirmation and advance only while held", async ({ page, request }) => {
  await ready(page);
  await page.locator(".taskbar").getByText("Gripper", { exact: true }).click();
  await expect(page.locator("canvas")).toHaveAttribute("data-tool", "gripper");
  await page.getByText("Real arm", { exact: true }).click();
  await page.getByRole("button", { name: "Plan pick & place", exact: true }).click();
  await expect(page.locator("#task-status")).toContainText("1 / 9");
  await page.getByRole("button", { name: "Disarmed", exact: true }).click();
  await page.getByLabel("Adult supervision, clear workspace and power cutoff within reach").check();
  await expect(page.getByRole("button", { name: "Arm controls", exact: true })).toBeDisabled();
  await page.getByLabel("Gripper fitted, pen removed and tool dimensions checked").check();
  await page.getByRole("button", { name: "Arm controls", exact: true }).click();
  const run = page.getByRole("button", { name: "Hold to run task", exact: true });
  await expect(run).toBeEnabled();
  const box = await run.boundingBox();
  const moved = page.waitForResponse(response => response.url().endsWith("/api/control/task/step") && response.status() === 200);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  const result = await (await moved).json();
  await page.mouse.up();
  expect(result.complete).toBe(false);
  await page.getByRole("button", { name: "Stop and disarm", exact: true }).click();
  const state = await (await request.get("/api/control/state")).json();
  expect(state.armed).toBe(false);
  expect(state.task).toBeNull();
});

test("gallery shows an explicitly labelled simulation card and returns to studio", async ({ page }) => {
  await ready(page);
  await page.getByRole("link", { name: "Gallery", exact: true }).click();
  await expect(page.locator(".card")).toHaveCount(1);
  await expect(page.getByText("Simulation preview", { exact: true })).toBeVisible();
  await expect.poll(() => page.locator(".card img").evaluate(image => image.naturalWidth)).toBeGreaterThan(0);
  await page.screenshot({ path: "../output/studio-gallery.png", fullPage: true });
  await page.getByRole("link", { name: "Open Sketchbot Studio", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Joint control", exact: true })).toBeVisible();
});

test("mobile viewport has a visible model, usable menus and no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await ready(page);
  expect(await canvasPixels(page)).toBeGreaterThan(60);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "../output/studio-mobile.png", fullPage: true });
  await page.getByRole("button", { name: "Open setup" }).click();
  await page.getByRole("tab", { name: "Controller", exact: true }).click();
  await expect(page.getByLabel("Stick deadzone", { exact: false })).toBeVisible();
  const modal = await page.locator("#settings").boundingBox();
  expect(modal.x).toBeGreaterThanOrEqual(0);
  expect(modal.x + modal.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: "../output/studio-mobile-settings.png", fullPage: true });
});