async function jsonOrThrow(resp) {
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const data = await resp.json();
      if (data && data.detail) detail = data.detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return resp.json();
}

async function pngOrThrow(resp) {
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const data = await resp.json();
      if (data && data.detail) detail = data.detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return resp.blob();
}

export async function fetchState() {
  return jsonOrThrow(await fetch("/api/state"));
}

export async function buildCameraUrl(params) {
  return jsonOrThrow(
    await fetch("/api/camera/build", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    }),
  );
}

export async function testCameraUrl(url) {
  return jsonOrThrow(
    await fetch("/api/camera/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    }),
  );
}

export async function captureCameraFrame(url) {
  return pngOrThrow(
    await fetch("/api/camera/capture", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    }),
  );
}

export async function fetchCameraFrame() {
  const resp = await fetch("/api/camera/frame");
  if (resp.status === 404) return null;
  return pngOrThrow(resp);
}

export async function previewBev(srcPoints, width, height) {
  return pngOrThrow(
    await fetch("/api/bev/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ src_points: srcPoints, width, height }),
    }),
  );
}

export async function saveBev(srcPoints, width, height) {
  return jsonOrThrow(
    await fetch("/api/bev/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ src_points: srcPoints, width, height }),
    }),
  );
}

export async function saveMask(kind, base64) {
  return jsonOrThrow(
    await fetch("/api/mask/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: kind, png_base64: base64 }),
    }),
  );
}

export async function fetchMask(kind) {
  const resp = await fetch(`/api/mask/${kind}`);
  if (resp.status === 404) return null;
  return pngOrThrow(resp);
}

export async function clearMask(kind) {
  return jsonOrThrow(
    await fetch(`/api/mask/clear/${kind}`, { method: "POST" }),
  );
}

export async function saveMap(shapes) {
  return jsonOrThrow(
    await fetch("/api/map/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ shapes }),
    }),
  );
}

export async function fetchMap() {
  return jsonOrThrow(await fetch("/api/map"));
}

export async function exportZip() {
  const resp = await fetch("/api/export");
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.blob();
}

export async function fetchExportSummary() {
  return jsonOrThrow(await fetch("/api/export/summary"));
}

export async function resetSession() {
  return jsonOrThrow(await fetch("/api/reset", { method: "POST" }));
}

export async function invalidateStep(step) {
  return jsonOrThrow(await fetch(`/api/invalidate/${step}`, { method: "POST" }));
}
