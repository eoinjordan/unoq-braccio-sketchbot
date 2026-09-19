import "@fontsource/space-grotesk/latin-400.css";
import "@fontsource/space-grotesk/latin-600.css";
import { createIcons, Bot, Github, ArrowUpRight, BookmarkPlus, ShieldCheck, Copy, Tablet, Gamepad2,
  Camera, Terminal, HardDrive, RefreshCw, Smartphone, Monitor, Package, Download, Plus, Network, Trash2 } from "lucide";
import QRCode from "qrcode";
import { controllerUrl, deviceAddress, installCommand, repositoryUrl, savedDevices } from "./setup-model.js";
import { withRequestTimeout } from "./http.js";

const icons = { Bot, Github, ArrowUpRight, BookmarkPlus, ShieldCheck, Copy, Tablet, Gamepad2,
  Camera, Terminal, HardDrive, RefreshCw, Smartphone, Monitor, Package, Download, Plus, Network, Trash2 };
const byId = id => document.getElementById(id);
const storageKey = "sketchbot-devices-v1";
let installationPrompt;
let toastTimer;
let currentLink = "";
let devices;
try { devices = savedDevices(localStorage.getItem(storageKey)); } catch { devices = []; }

function notify(message) {
  byId("toast").textContent = message; byId("toast").hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { byId("toast").hidden = true; }, 6000);
}
async function copy(value) {
  try { await navigator.clipboard.writeText(value); notify("Copied."); }
  catch { notify("Clipboard unavailable. Select and copy the command directly."); }
}
function refreshAddress() {
  try {
    currentLink = controllerUrl(byId("device-address").value, byId("event-mode").checked);
    byId("address-error").hidden = true;
    byId("pairing").hidden = false;
    byId("device-link").href = currentLink;
    byId("device-link").textContent = currentLink;
    const host = new URL(currentLink).hostname;
    byId("ssh-command").textContent = `ssh 'arduino@${host}'`;
    byId("copy-ssh").disabled = false;
    QRCode.toCanvas(byId("device-qr"), currentLink, { width: 224, margin: 2,
      color: { dark: "#172c2c", light: "#ffffff" } }).catch(error => notify(error.message));
    return true;
  } catch (error) {
    currentLink = ""; byId("pairing").hidden = true; byId("copy-ssh").disabled = true;
    byId("address-error").textContent = error.message; byId("address-error").hidden = false;
    return false;
  }
}
function renderDevices() {
  byId("saved-devices").textContent = "";
  devices.forEach((device, index) => {
    const row = document.createElement("div"); row.className = "saved-device";
    row.innerHTML = '<i data-lucide="bot"></i><a target="_blank" rel="noopener noreferrer"><strong></strong><small></small></a><button class="icon-button" title="Forget device" aria-label="Forget device"><i data-lucide="trash-2"></i></button>';
    row.querySelector("a").href = controllerUrl(device.address, byId("event-mode").checked);
    row.querySelector("strong").textContent = device.name;
    row.querySelector("small").textContent = device.address;
    row.querySelector("button").onclick = () => { devices.splice(index, 1); storeDevices(); renderDevices(); };
    byId("saved-devices").append(row);
  });
  createIcons({ icons });
}
function storeDevices() {
  try { localStorage.setItem(storageKey, JSON.stringify(devices)); }
  catch { notify("This browser could not save the device list."); }
}
byId("device-form").onsubmit = event => {
  event.preventDefault();
  if (refreshAddress()) window.open(currentLink, "_blank", "noopener,noreferrer");
};
byId("device-address").onchange = refreshAddress;
byId("event-mode").onchange = () => { if (byId("device-address").value) refreshAddress(); renderDevices(); };
byId("remember-device").onclick = () => {
  if (!refreshAddress()) return;
  const address = deviceAddress(byId("device-address").value);
  devices = [{ name: byId("device-name").value.trim() || new URL(address).hostname, address },
    ...devices.filter(device => device.address !== address)].slice(0, 12);
  storeDevices(); renderDevices(); notify("Device remembered on this browser only.");
};
byId("copy-device").onclick = () => { if (currentLink) copy(currentLink); };
byId("copy-ssh").onclick = () => copy(byId("ssh-command").textContent);

function renderInstall() {
  byId("power-confirm-row").hidden = !byId("include-driver").checked;
  try {
    byId("install-command").textContent = installCommand({ agent: byId("include-driver").checked,
      servoPowerOff: byId("servo-power-off").checked, motion: byId("allow-motion").checked,
      tabletCamera: byId("tablet-camera").checked });
    byId("install-error").hidden = true; byId("copy-install").disabled = false;
  } catch (error) {
    byId("install-command").textContent = ""; byId("copy-install").disabled = true;
    byId("install-error").textContent = error.message; byId("install-error").hidden = false;
  }
}
for (const id of ["include-driver", "servo-power-off", "allow-motion", "tablet-camera"]) byId(id).onchange = renderInstall;
byId("copy-install").onclick = () => copy(byId("install-command").textContent);

async function releases() {
  try {
    const release = await withRequestTimeout(8000, async signal => {
      const response = await fetch("https://api.github.com/repos/eoinjordan/unoq-braccio-sketchbot/releases/latest", { signal });
      if (!response.ok) throw new Error("Release list unavailable");
      return response.json();
    });
    byId("release-version").textContent = release.tag_name;
    for (const link of document.querySelectorAll("[data-package]")) {
      const asset = release.assets.find(item => item.name.endsWith(`.${link.dataset.package}`));
      if (!asset || !asset.browser_download_url.startsWith(`${repositoryUrl}/releases/download/`)) continue;
      link.href = asset.browser_download_url;
      link.querySelector("span").textContent = `Download ${link.dataset.package.toUpperCase()}`;
      link.title = `${asset.name} / ${(asset.size / 1024 / 1024).toFixed(1)} MB`;
    }
    byId("checksums-link").href = release.html_url;
    byId("download-status").textContent = `${release.tag_name} / Packages published on GitHub Releases. Verify SHA256SUMS before installing.`;
  } catch {
    byId("download-status").textContent = "Package status unavailable. Open GitHub Releases for published downloads.";
  }
}
window.addEventListener("beforeinstallprompt", event => { event.preventDefault(); installationPrompt = event; });
byId("install-pwa").onclick = async () => {
  if (installationPrompt) { await installationPrompt.prompt(); installationPrompt = null; }
  else notify("Use your browser's Install app or Add to Home Screen action. On iPad, it is in Safari's Share menu.");
};
function offlineStatus() { byId("offline-status").textContent = navigator.onLine ? "" : "Offline launcher"; }
window.addEventListener("online", offlineStatus); window.addEventListener("offline", offlineStatus);
if ("serviceWorker" in navigator) navigator.serviceWorker.register("./sw.js").catch(() => {});
const incoming = new URLSearchParams(location.hash.slice(1)).get("device");
if (incoming) { byId("device-address").value = incoming; refreshAddress(); }
renderDevices(); renderInstall(); releases(); offlineStatus(); createIcons({ icons });