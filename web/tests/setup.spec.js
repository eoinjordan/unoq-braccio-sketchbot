import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

const setup = "http://127.0.0.1:7121/";
const repository = "https://github.com/eoinjordan/unoq-braccio-sketchbot";
const { version } = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));

test.beforeEach(async ({ page }) => {
  await page.route("https://api.github.com/repos/eoinjordan/unoq-braccio-sketchbot/releases/latest", route => route.fulfill({
    contentType: "application/json", body: JSON.stringify({ tag_name: `v${version}`, html_url: `${repository}/releases/tag/v${version}`,
      assets: [`Sketchbot-Tablet-${version}.apk`, `Sketchbot-Launcher-${version}.msi`, `Sketchbot-Source-${version}.tar.gz`].map(name => ({
        name, size: 100000, browser_download_url: `${repository}/releases/download/v${version}/${name}`,
      })) }),
  }));
});

test("public setup validates addresses, creates a real QR code and remembers devices locally", async ({ page }) => {
  await page.goto(setup);
  await page.getByLabel("UNO Q address").fill("http://example.com");
  await page.getByRole("button", { name: "Remember", exact: true }).click();
  await expect(page.locator("#address-error")).toContainText("Public HTTP");
  await page.getByLabel("UNO Q address").fill("unoq.local");
  await page.getByLabel("Device name", { exact: true }).fill("Workshop robot");
  await page.getByRole("button", { name: "Remember", exact: true }).click();
  await expect(page.locator("#device-link")).toHaveAttribute("href", "http://unoq.local:7100/?event=1");
  await expect(page.locator(".saved-device strong")).toHaveText("Workshop robot");
  const dark = await page.locator("#device-qr").evaluate(canvas => {
    const pixels = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
    let count = 0; for (let index = 0; index < pixels.length; index += 4) if (pixels[index] < 80) count++;
    return count;
  });
  expect(dark).toBeGreaterThan(500);
  await page.reload();
  await expect(page.locator(".saved-device strong")).toHaveText("Workshop robot");
});

test("public installer requires explicit firmware confirmation and defaults to no motion", async ({ page }) => {
  await page.goto(setup);
  await expect(page.locator("#install-command")).not.toContainText("--allow-motion");
  await expect(page.locator("#install-command")).not.toContainText("--install-agent");
  await page.getByLabel("Install Braccio arm driver", { exact: true }).check();
  await expect(page.getByRole("button", { name: "Copy install command", exact: true })).toBeDisabled();
  await page.getByLabel("Servo power is physically disconnected").check();
  await expect(page.locator("#install-command")).toContainText("--install-agent --servo-power-off");
  await expect(page.getByRole("button", { name: "Copy install command", exact: true })).toBeEnabled();
});

test("older Android WebView can remember devices and load downloads", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(Element.prototype, "replaceChildren", { configurable: true, value: undefined });
    Object.defineProperty(AbortSignal, "timeout", { configurable: true, value: undefined });
  });
  await page.goto(setup);
  await page.getByLabel("UNO Q address").fill("unoq.local");
  await page.getByRole("button", { name: "Remember", exact: true }).click();
  await expect(page.locator(".saved-device")).toHaveCount(1);
  await expect(page.locator('[data-package="apk"]')).toHaveAttribute("href", /\/releases\/download\//);
});

test("public page renders verified release links and responsive desktop/mobile assets", async ({ page }) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(setup);
  await expect(page.locator('[data-package="apk"]')).toHaveAttribute("href", `${repository}/releases/download/v${version}/Sketchbot-Tablet-${version}.apk`);
  await expect.poll(() => page.locator(".preview img").evaluate(image => image.naturalWidth)).toBeGreaterThan(100);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.evaluate(() => Promise.all(document.getAnimations().map(animation => animation.finished)));
  await page.screenshot({ path: "../output/setup-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "../output/setup-mobile.png", fullPage: true });
  expect(errors).toEqual([]);
});

test("public setup never sends camera or control requests to a device", async ({ page }) => {
  const privateRequests = [];
  page.on("request", request => { if (request.url().includes("unoq.local")) privateRequests.push(request.url()); });
  await page.goto(`${setup}#device=${encodeURIComponent("http://unoq.local:7100")}`);
  await expect(page.locator("#device-link")).toHaveAttribute("href", "http://unoq.local:7100/?event=1");
  await page.getByRole("button", { name: "Remember", exact: true }).click();
  expect(privateRequests).toEqual([]);
  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);
});