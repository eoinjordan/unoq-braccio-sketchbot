export const setupUrl = "https://eoinjordan.github.io/unoq-braccio-sketchbot/";
export const repositoryUrl = "https://github.com/eoinjordan/unoq-braccio-sketchbot";

export function deviceAddress(value) {
  const input = String(value || "").trim();
  if (!input || /\s/.test(input)) throw new Error("Enter the UNO Q hostname or its local IP address.");
  let address;
  try { address = new URL(input.includes("://") ? input : `http://${input}`); }
  catch { throw new Error("The device address is not a valid URL."); }
  if (!["http:", "https:"].includes(address.protocol) || address.username || address.password) {
    throw new Error("Use an HTTP or HTTPS device address without passwords or tokens.");
  }
  const host = address.hostname.toLowerCase();
  const dnsName = host.split(".").every(label => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label));
  const ipv6 = /^\[[0-9a-f:.]+\]$/.test(host);
  if (!dnsName && !ipv6) throw new Error("Use a normal hostname or IP address, without shell characters.");
  const parts = host.split(".").map(Number);
  const ipv4 = parts.length === 4 && parts.every(part => Number.isInteger(part) && part >= 0 && part <= 255);
  const privateIp = ipv4 && (parts[0] === 10 || parts[0] === 127 ||
    (parts[0] === 192 && parts[1] === 168) || (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) ||
    (parts[0] === 169 && parts[1] === 254));
  const local = privateIp || host === "localhost" || host === "[::1]" || host.endsWith(".local") ||
    host.endsWith(".lan") || /^[a-z][a-z0-9-]*$/.test(host);
  if (address.protocol === "http:" && !local) throw new Error("Public HTTP control is blocked. Use a local address or private HTTPS access.");
  if (address.search || address.hash || address.pathname !== "/") throw new Error("Enter only the device address, without a path, query or token.");
  if (address.protocol === "http:" && !address.port) address.port = "7100";
  return address.origin;
}

export function controllerUrl(address, event = true) {
  return `${deviceAddress(address)}/${event ? "?event=1" : ""}`;
}

export function installCommand({ agent = false, servoPowerOff = false, motion = false, tabletCamera = true } = {}) {
  if (agent && !servoPowerOff) throw new Error("Disconnect servo power before selecting arm-driver installation.");
  const flags = [];
  if (tabletCamera) flags.push("--tablet-camera");
  if (agent) flags.push("--install-agent", "--servo-power-off");
  if (motion) flags.push("--allow-motion");
  return `installer=$(mktemp) && curl -fsSL '${setupUrl}install.sh' -o "$installer" && bash "$installer"${flags.length ? ` ${flags.join(" ")}` : ""}`;
}

export function savedDevices(raw) {
  try {
    const values = JSON.parse(raw || "[]");
    if (!Array.isArray(values)) return [];
    return values.slice(0, 12).flatMap(device => {
      try { return [{ name: String(device.name || "Sketchbot").slice(0, 60), address: deviceAddress(device.address) }]; }
      catch { return []; }
    });
  } catch { return []; }
}