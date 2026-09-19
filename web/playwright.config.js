import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const python = process.env.SKETCHBOT_PYTHON || path.resolve(directory, "../.venv/bin/python");

export default defineConfig({
  testDir: "./tests", testMatch: "studio.spec.js", workers: 1,
  timeout: 30000, outputDir: "../output/browser-tests", reporter: "list",
  use: { baseURL: "http://127.0.0.1:7119", viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure", trace: "retain-on-failure",
    launchOptions: { args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] } },
  webServer: { command: `"${python}" tests/serve.py`, url: "http://127.0.0.1:7119",
    reuseExistingServer: false, timeout: 30000 },
});