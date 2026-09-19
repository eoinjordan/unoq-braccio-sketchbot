export function installTabletCameraControls({ getState, notify, refreshIcons }) {
  let stream = null;
  let activeRole = null;
  let timer = null;
  let generation = 0;
  let pendingUpload = null;

  function stopCamera() {
    generation++;
    clearTimeout(timer);
    stream?.getTracks().forEach(track => track.stop());
    stream = null;
    if (activeRole) document.getElementById(`tablet-video-${activeRole}`).srcObject = null;
    activeRole = null;
    for (const role of ["face", "gripper"]) {
      document.getElementById(`tablet-live-${role}`).setAttribute("aria-pressed", "false");
    }
  }

  async function upload(role, source, width, height) {
    const scale = Math.min(1, 1280 / Math.max(width, height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    canvas.getContext("2d").drawImage(source, 0, 0, canvas.width, canvas.height);
    const jpeg = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.82));
    if (!jpeg) throw new Error("Camera frame could not be encoded");
    const operation = fetch(`/api/camera-input/${role}`, {
      method: "POST", headers: { "Content-Type": "image/jpeg" }, body: jpeg,
      signal: AbortSignal.timeout(8000),
    });
    pendingUpload = operation.then(async response => {
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Camera upload failed");
      return result;
    });
    return pendingUpload;
  }

  for (const role of ["face", "gripper"]) {
    const panel = document.getElementById(`${role}-frame`).closest(".camera-panel");
    const toolbar = document.createElement("div");
    toolbar.id = `tablet-tools-${role}`;
    toolbar.className = "tablet-tools";
    toolbar.hidden = true;
    toolbar.innerHTML = `<input type="file" id="tablet-file-${role}" accept="image/*" capture="${role === "face" ? "user" : "environment"}" hidden>
      <button class="button secondary" id="tablet-photo-${role}" title="Take or choose a ${role === "face" ? "face" : "paper"} photo"><i data-lucide="camera"></i>Take photo</button>
      <button class="icon-button" id="tablet-live-${role}" aria-label="Start or stop ${role} tablet camera" title="Live tablet camera (HTTPS or localhost)" aria-pressed="false"><i data-lucide="video"></i></button>
      <button class="icon-button" id="tablet-clear-${role}" aria-label="Clear ${role} tablet photo" title="Clear tablet photo"><i data-lucide="trash-2"></i></button>
      <video id="tablet-video-${role}" muted playsinline hidden></video>`;
    panel.append(toolbar);
    const fileInput = document.getElementById(`tablet-file-${role}`);
    document.getElementById(`tablet-photo-${role}`).onclick = () => fileInput.click();
    fileInput.onchange = async () => {
      const file = fileInput.files?.[0];
      if (!file) return;
      stopCamera();
      let bitmap;
      try {
        if (file.size > 25_000_000) throw new Error("Choose a photo smaller than 25 MB");
        bitmap = await createImageBitmap(file);
        await upload(role, bitmap, bitmap.width, bitmap.height);
        notify("Photo sent to this UNO Q. It expires after five minutes.");
      } catch (error) { notify(error.message); }
      finally { bitmap?.close(); fileInput.value = ""; }
    };
    document.getElementById(`tablet-live-${role}`).onclick = async () => {
      const wasActive = activeRole === role;
      stopCamera();
      if (wasActive) return;
      if (!isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        notify("Live camera needs HTTPS or localhost. Take photo works on the local network.");
        return;
      }
      const session = generation;
      try {
        const media = await navigator.mediaDevices.getUserMedia({ audio: false,
          video: { facingMode: role === "face" ? "user" : "environment", width: { ideal: 1280 } } });
        if (session !== generation || document.hidden) { media.getTracks().forEach(track => track.stop()); return; }
        stream = media;
        activeRole = role;
        const video = document.getElementById(`tablet-video-${role}`);
        video.srcObject = stream;
        await video.play();
        document.getElementById(`tablet-live-${role}`).setAttribute("aria-pressed", "true");
        const capture = async () => {
          if (session !== generation || !stream || document.hidden) return;
          try {
            await upload(role, video, video.videoWidth, video.videoHeight);
            if (session === generation) timer = setTimeout(capture, 800);
          } catch (error) { stopCamera(); notify(error.message); }
        };
        capture();
      } catch (error) { stopCamera(); notify(error.message); }
    };
    document.getElementById(`tablet-clear-${role}`).onclick = async () => {
      stopCamera();
      try {
        await pendingUpload?.catch(() => {});
        const response = await fetch("/api/camera-input/clear", { method: "POST",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role }) });
        if (!response.ok) throw new Error("Could not clear the camera frame");
        notify("Tablet photo cleared.");
      } catch (error) { notify(error.message); }
    };
  }
  refreshIcons();
  window.addEventListener("pagehide", stopCamera);
  document.addEventListener("visibilitychange", () => { if (document.hidden) stopCamera(); });
  return {
    stopCamera,
    update() {
      const state = getState();
      for (const role of ["face", "gripper"]) {
        const enabled = state?.cameras[role]?.format === "tablet" && state.cameras[role].enabled !== false;
        document.getElementById(`tablet-tools-${role}`).hidden = !enabled;
        if (!enabled && role === activeRole) stopCamera();
      }
    },
  };
}