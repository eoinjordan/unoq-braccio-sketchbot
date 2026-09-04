# ESP-EYE camera bridge

Firmware that turns an **Espressif ESP-EYE** (ESP32 + OV2640 + 8 MB PSRAM) into
the sketchbot's camera. It shares JPEG frames with the UNO Q over **Wi-Fi** or
over **USB**, so it can replace the wrist USB webcam.

- **Wi-Fi** — HTTP on port 80: `GET /capture` → one JPEG, `GET /stream` → MJPEG,
  `GET /` → a status/preview page. Advertised over mDNS as `esp-eye.local`.
- **USB** — plug the ESP-EYE micro-USB into the UNO Q's USB-C. The board appears
  as a serial port; the host sends `C` and gets back one length-framed JPEG.

Face detection runs on the UNO Q (the sketchbot's portrait pipeline); this
firmware just delivers clean frames over whichever link is up.

## Flash it

1. **Arduino IDE** → install the **esp32** boards package (Espressif) via Boards
   Manager if you haven't.
2. Board: **ESP32 Wrover Module** (it has PSRAM; equivalently *ESP32 Dev Module*
   with **PSRAM: Enabled**). Partition: **Huge APP (3MB No OTA)**.
3. Wi-Fi creds: copy `secrets.h.example` → `secrets.h` and fill in your network
   (or leave `WIFI_SSID ""` to run USB-only). `secrets.h` is git-ignored.
4. Plug the ESP-EYE in, pick its serial port, and **Upload**.
5. Open Serial Monitor at **921600 baud**. You'll see either
   `INFO Wi-Fi up: http://<ip>/ (http://esp-eye.local/)` or
   `INFO no WIFI_SSID set - running USB-only`.

> No extra libraries needed — `esp_camera`, `WiFi` and `ESPmDNS` all ship with
> the esp32 core.

## Point the sketchbot at it

Edit [`config/cameras.yaml`](../../config/cameras.yaml) so the `single` camera
uses the ESP-EYE instead of a USB webcam. Pick **one** transport:

```yaml
cameras:
  single:
    description: "ESP-EYE over Wi-Fi"
    url: "http://esp-eye.local/capture"   # or http://<esp-eye-ip>/capture
    width: 800
    height: 600
```

or over USB:

```yaml
cameras:
  single:
    description: "ESP-EYE over USB"
    serial: "auto"        # or a fixed node like /dev/ttyUSB0
    baud: 921600
```

Then test the feed and run the demo exactly as before:

```bash
python -m sketch_artist.cameras                       # grabs a frame from the ESP-EYE
python -m sketch_artist.cli --style none --slow       # capture -> caricature -> draw
```

The USB path needs `pyserial` (already in `requirements.txt`).

## Wiring / notes

| Link  | Connection                                   | Sketchbot config      |
| ----- | -------------------------------------------- | --------------------- |
| Wi-Fi | ESP-EYE and UNO Q on the same network        | `url: http://.../capture` |
| USB   | ESP-EYE micro-USB → UNO Q USB-C              | `serial: auto`        |

- On the UNO Q, the USB serial node is usually `/dev/ttyUSB0` (CP210x). If the
  user isn't in the `dialout` group: `sudo usermod -aG dialout $USER` then
  re-login (or set a fixed `serial:` path you can access).
- Upside-down or mirrored image? Set `VFLIP` / `HMIRROR` to `1` at the top of
  the sketch and re-flash.
- Bigger/smaller frames: change `FRAME_SIZE` (e.g. `FRAMESIZE_VGA`,
  `FRAMESIZE_HD`) and `JPEG_QUALITY`.

## USB serial protocol

Request/response on the USB serial port (default **921600 baud**):

| Host sends | Board replies                                                        |
| ---------- | -------------------------------------------------------------------- |
| `C`        | `0xA5 0x5A` + `length` (uint32 little-endian) + `length` JPEG bytes  |
| `I`        | a text line: `INFO esp-eye ready wifi=… ip=…`                        |

`length == 0` means the camera had no frame ready. The host scans for the
`0xA5 0x5A` magic so boot-log text on the same UART doesn't desync it.
