import { UndoStack } from "/static/lib/undo.js";

const PALETTES = {
  parking: {
    left: { r: 40, g: 220, b: 40 },
    right: { r: 220, g: 40, b: 40 },
    initial: "fill-allowed",
  },
  orientation: {
    left: { r: 0, g: 255, b: 0 },
    right: { r: 0, g: 60, b: 255 },
    initial: "transparent",
  },
};

function debounce(fn, ms) {
  let t = null;
  return (...args) => {
    if (t) clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function rgbToCss({ r, g, b }, alpha = 1) {
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function initMaskPage(ctx, kind) {
  const { api, store, toast } = ctx;
  const root = document.getElementById(`page-mask-${kind}`);
  if (!root) throw new Error(`page-mask-${kind} not found`);

  const wrap = root.querySelector("[data-canvas-wrap]");
  const stack = root.querySelector("[data-mask-stack]");
  const underlay = root.querySelector("[data-bev-underlay]");
  const canvas = root.querySelector("[data-mask-canvas]");
  const ctx2d = canvas.getContext("2d", { willReadFrequently: true });

  const brushSizeInput = root.querySelector("[data-brush-size]");
  const brushSizeLabel = root.querySelector("[data-brush-size-label]");
  const underlayToggle = root.querySelector("[data-underlay-toggle]");
  const underlayOpacity = root.querySelector("[data-underlay-opacity]");
  const underlayOpacityLabel = root.querySelector("[data-underlay-opacity-label]");
  const undoBtn = root.querySelector("[data-undo-btn]");
  const redoBtn = root.querySelector("[data-redo-btn]");
  const importBtn = root.querySelector("[data-import-btn]");
  const importInput = root.querySelector("[data-import-input]");
  const clearBtn = root.querySelector("[data-clear-btn]");
  const saveBtn = root.querySelector("[data-save-btn]");
  const saveStatus = root.querySelector("[data-save-status]");

  const palette = PALETTES[kind];
  const undoStack = new UndoStack(20);
  let bevDims = null;
  let lastPaintXY = null;
  let activeButton = null;
  let activeMode = null;
  let dirtyAfterSave = false;
  let initialized = false;
  let underlayBlobUrl = null;

  let fitW = 0;
  let fitH = 0;
  let viewState = { scale: 1, tx: 0, ty: 0 };
  let panStart = null;
  let resizeObs = null;

  function getEraseMode() {
    if (kind !== "orientation") return false;
    const r = root.querySelector('input[name="orient-tool"]:checked');
    return r && r.value === "erase";
  }

  function modeForButton(button) {
    if (kind === "orientation" && getEraseMode()) return { type: "erase" };
    return {
      type: "paint",
      color: button === 0 ? palette.left : palette.right,
    };
  }

  function setupCanvas(width, height) {
    canvas.width = width;
    canvas.height = height;
  }

  function fillInitial() {
    ctx2d.clearRect(0, 0, canvas.width, canvas.height);
    if (palette.initial === "fill-allowed") {
      ctx2d.globalCompositeOperation = "source-over";
      ctx2d.fillStyle = rgbToCss(palette.left, 1);
      ctx2d.fillRect(0, 0, canvas.width, canvas.height);
    }
  }

  function fitStack(resetView = true) {
    if (!stack || !bevDims) return;
    const wrapW = wrap.clientWidth;
    const wrapH = wrap.clientHeight;
    if (wrapW < 10 || wrapH < 10) return;
    const ratio = bevDims.width / bevDims.height;
    fitW = wrapW;
    fitH = fitW / ratio;
    if (fitH > wrapH) {
      fitH = wrapH;
      fitW = fitH * ratio;
    }
    stack.style.width = `${fitW}px`;
    stack.style.height = `${fitH}px`;
    if (resetView) {
      viewState = {
        scale: 1,
        tx: (wrapW - fitW) / 2,
        ty: (wrapH - fitH) / 2,
      };
    }
    applyTransform();
  }

  function applyTransform() {
    stack.style.transform = `translate(${viewState.tx}px, ${viewState.ty}px) scale(${viewState.scale})`;
  }

  function pushSnapshot() {
    const data = ctx2d.getImageData(0, 0, canvas.width, canvas.height);
    undoStack.push(data);
    refreshUndoButtons();
  }

  function refreshUndoButtons() {
    undoBtn.disabled = !undoStack.canUndo();
    redoBtn.disabled = !undoStack.canRedo();
  }

  function restoreSnapshot(snap) {
    if (!snap) return;
    ctx2d.globalCompositeOperation = "source-over";
    ctx2d.putImageData(snap, 0, 0);
  }

  function clientToCanvas(clientX, clientY) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((clientX - rect.left) / rect.width) * canvas.width,
      y: ((clientY - rect.top) / rect.height) * canvas.height,
    };
  }

  function applyMode(mode) {
    if (mode.type === "erase") {
      ctx2d.globalCompositeOperation = "destination-out";
      ctx2d.fillStyle = "rgba(0,0,0,1)";
      ctx2d.strokeStyle = "rgba(0,0,0,1)";
    } else {
      ctx2d.globalCompositeOperation = "source-over";
      ctx2d.fillStyle = rgbToCss(mode.color, 1);
      ctx2d.strokeStyle = rgbToCss(mode.color, 1);
    }
  }

  function paintDot(x, y, mode) {
    applyMode(mode);
    const r = Number(brushSizeInput.value) / 2;
    ctx2d.beginPath();
    ctx2d.arc(x, y, r, 0, Math.PI * 2);
    ctx2d.fill();
  }

  function paintLine(from, to, mode) {
    applyMode(mode);
    const r = Number(brushSizeInput.value);
    ctx2d.lineWidth = r;
    ctx2d.lineCap = "round";
    ctx2d.lineJoin = "round";
    ctx2d.beginPath();
    ctx2d.moveTo(from.x, from.y);
    ctx2d.lineTo(to.x, to.y);
    ctx2d.stroke();
  }

  canvas.addEventListener("contextmenu", (ev) => ev.preventDefault());
  wrap.addEventListener("contextmenu", (ev) => ev.preventDefault());

  canvas.addEventListener("pointerdown", (ev) => {
    if (activeButton !== null || panStart) return;
    if (ev.ctrlKey) return;
    if (ev.button === 1) return;
    if (ev.button !== 0 && ev.button !== 2) return;
    ev.preventDefault();
    activeButton = ev.button;
    activeMode = modeForButton(ev.button);
    canvas.setPointerCapture(ev.pointerId);
    const p = clientToCanvas(ev.clientX, ev.clientY);
    paintDot(p.x, p.y, activeMode);
    lastPaintXY = p;
    dirtyAfterSave = true;
  });

  canvas.addEventListener("pointermove", (ev) => {
    if (activeButton === null) return;
    const p = clientToCanvas(ev.clientX, ev.clientY);
    paintLine(lastPaintXY, p, activeMode);
    lastPaintXY = p;
  });

  function endStroke(ev) {
    if (activeButton === null) return;
    try { canvas.releasePointerCapture(ev.pointerId); } catch (_) {}
    ctx2d.globalCompositeOperation = "source-over";
    activeButton = null;
    activeMode = null;
    lastPaintXY = null;
    pushSnapshot();
    scheduleAutosave();
  }
  canvas.addEventListener("pointerup", endStroke);
  canvas.addEventListener("pointercancel", endStroke);
  canvas.addEventListener("pointerleave", (ev) => {
    if (activeButton !== null && ev.pointerType === "mouse" && ev.buttons === 0) {
      endStroke(ev);
    }
  });

  wrap.addEventListener(
    "wheel",
    (ev) => {
      if (!ev.ctrlKey) return;
      ev.preventDefault();
      ev.stopPropagation();
      const factor = ev.deltaY < 0 ? 1.15 : 0.87;
      const newScale = Math.max(0.2, Math.min(8, viewState.scale * factor));
      const rect = wrap.getBoundingClientRect();
      const mx = ev.clientX - rect.left;
      const my = ev.clientY - rect.top;
      const r = newScale / viewState.scale;
      viewState.tx = mx - (mx - viewState.tx) * r;
      viewState.ty = my - (my - viewState.ty) * r;
      viewState.scale = newScale;
      applyTransform();
    },
    { passive: false },
  );

  wrap.addEventListener("pointerdown", (ev) => {
    if (activeButton !== null) return;
    const isPan = ev.button === 1 || (ev.button === 0 && ev.ctrlKey);
    if (!isPan) return;
    ev.preventDefault();
    ev.stopPropagation();
    panStart = {
      x: ev.clientX,
      y: ev.clientY,
      tx: viewState.tx,
      ty: viewState.ty,
      pointerId: ev.pointerId,
    };
    wrap.setPointerCapture(ev.pointerId);
    wrap.classList.add("panning");
  });

  wrap.addEventListener("pointermove", (ev) => {
    if (!panStart) return;
    viewState.tx = panStart.tx + (ev.clientX - panStart.x);
    viewState.ty = panStart.ty + (ev.clientY - panStart.y);
    applyTransform();
  });

  function endPan(ev) {
    if (!panStart) return;
    try { wrap.releasePointerCapture(panStart.pointerId); } catch (_) {}
    panStart = null;
    wrap.classList.remove("panning");
  }
  wrap.addEventListener("pointerup", endPan);
  wrap.addEventListener("pointercancel", endPan);

  brushSizeInput.addEventListener("input", () => {
    brushSizeLabel.textContent = brushSizeInput.value;
  });

  function applyDisplaySettings() {
    underlay.style.display = underlayToggle.checked ? "" : "none";
    underlay.style.opacity = "1";
    canvas.style.opacity = String(Number(underlayOpacity.value) / 100);
    underlayOpacityLabel.textContent = underlayOpacity.value;
  }

  underlayToggle.addEventListener("change", applyDisplaySettings);
  underlayOpacity.addEventListener("input", applyDisplaySettings);

  undoBtn.addEventListener("click", () => {
    const snap = undoStack.undo();
    if (snap) {
      restoreSnapshot(snap);
      dirtyAfterSave = true;
      scheduleAutosave();
    }
    refreshUndoButtons();
  });
  redoBtn.addEventListener("click", () => {
    const snap = undoStack.redo();
    if (snap) {
      restoreSnapshot(snap);
      dirtyAfterSave = true;
      scheduleAutosave();
    }
    refreshUndoButtons();
  });

  importBtn.addEventListener("click", () => importInput.click());
  importInput.addEventListener("change", async () => {
    const file = importInput.files && importInput.files[0];
    importInput.value = "";
    if (!file) return;
    const url = URL.createObjectURL(file);
    try {
      const img = new Image();
      await new Promise((res, rej) => {
        img.onload = res;
        img.onerror = rej;
        img.src = url;
      });
      ctx2d.clearRect(0, 0, canvas.width, canvas.height);
      ctx2d.drawImage(img, 0, 0, canvas.width, canvas.height);
      convertFinalToEditing();
      pushSnapshot();
      dirtyAfterSave = true;
      scheduleAutosave();
      saveStatus.textContent = "Імпортовано";
      saveStatus.className = "status inline ok";
    } catch (e) {
      saveStatus.textContent = `Помилка імпорту: ${e.message}`;
      saveStatus.className = "status inline err";
    } finally {
      URL.revokeObjectURL(url);
    }
  });

  clearBtn.addEventListener("click", () => {
    if (!confirm("Очистити маску до початкового стану?")) return;
    fillInitial();
    pushSnapshot();
    dirtyAfterSave = true;
    scheduleAutosave();
  });

  function convertEditingToFinal() {
    const out = document.createElement("canvas");
    out.width = canvas.width;
    out.height = canvas.height;
    const octx = out.getContext("2d");

    const src = ctx2d.getImageData(0, 0, canvas.width, canvas.height).data;
    const dst = octx.createImageData(out.width, out.height);
    const d = dst.data;

    if (kind === "parking") {
      for (let i = 0; i < src.length; i += 4) {
        const r = src[i], g = src[i + 1], a = src[i + 3];
        const allowed = a > 30 && g > r;
        const v = allowed ? 255 : 0;
        d[i] = v; d[i + 1] = v; d[i + 2] = v; d[i + 3] = 255;
      }
    } else {
      for (let i = 0; i < src.length; i += 4) {
        const r = src[i], g = src[i + 1], b = src[i + 2], a = src[i + 3];
        if (a < 30) {
          d[i] = 0; d[i + 1] = 0; d[i + 2] = 0; d[i + 3] = 255;
        } else if (g >= b && g > r) {
          d[i] = 0; d[i + 1] = 255; d[i + 2] = 0; d[i + 3] = 255;
        } else if (b > r) {
          d[i] = 0; d[i + 1] = 0; d[i + 2] = 255; d[i + 3] = 255;
        } else {
          d[i] = 0; d[i + 1] = 0; d[i + 2] = 0; d[i + 3] = 255;
        }
      }
    }
    octx.putImageData(dst, 0, 0);
    return out;
  }

  function convertFinalToEditing() {
    const data = ctx2d.getImageData(0, 0, canvas.width, canvas.height);
    const d = data.data;
    if (kind === "parking") {
      const allow = palette.left;
      const forbid = palette.right;
      for (let i = 0; i < d.length; i += 4) {
        const v = d[i];
        if (v > 127) {
          d[i] = allow.r; d[i + 1] = allow.g; d[i + 2] = allow.b; d[i + 3] = 255;
        } else {
          d[i] = forbid.r; d[i + 1] = forbid.g; d[i + 2] = forbid.b; d[i + 3] = 255;
        }
      }
    } else {
      const par = palette.left;
      const per = palette.right;
      for (let i = 0; i < d.length; i += 4) {
        const r = d[i], g = d[i + 1], b = d[i + 2];
        if (g > 100 && g > b && g > r) {
          d[i] = par.r; d[i + 1] = par.g; d[i + 2] = par.b; d[i + 3] = 255;
        } else if (b > 100 && b > r) {
          d[i] = per.r; d[i + 1] = per.g; d[i + 2] = per.b; d[i + 3] = 255;
        } else {
          d[i] = 0; d[i + 1] = 0; d[i + 2] = 0; d[i + 3] = 0;
        }
      }
    }
    ctx2d.putImageData(data, 0, 0);
  }

  async function doSave() {
    if (!bevDims) return;
    const finalCanvas = convertEditingToFinal();
    const base64 = finalCanvas.toDataURL("image/png").split(",")[1];
    saveStatus.textContent = "Зберігаю...";
    saveStatus.className = "status inline";
    try {
      await api.saveMask(kind, base64);
      await store.refresh();
      saveStatus.textContent = "Збережено";
      saveStatus.className = "status inline ok";
      dirtyAfterSave = false;
    } catch (e) {
      saveStatus.textContent = `Помилка: ${e.message}`;
      saveStatus.className = "status inline err";
    }
  }

  const scheduleAutosave = debounce(() => { if (dirtyAfterSave) doSave(); }, 1200);

  saveBtn.addEventListener("click", () => doSave());

  document.addEventListener("keydown", (ev) => {
    if (root.classList.contains("hidden")) return;
    if (ev.ctrlKey && ev.key.toLowerCase() === "z" && !ev.shiftKey) {
      ev.preventDefault();
      undoBtn.click();
    } else if ((ev.ctrlKey && ev.key.toLowerCase() === "y") ||
               (ev.ctrlKey && ev.shiftKey && ev.key.toLowerCase() === "z")) {
      ev.preventDefault();
      redoBtn.click();
    }
  });

  async function loadUnderlay() {
    if (underlayBlobUrl) { URL.revokeObjectURL(underlayBlobUrl); underlayBlobUrl = null; }
    if (!store.state.bev) return;
    try {
      const blob = await api.previewBev(
        store.state.bev.src_points,
        store.state.bev.width,
        store.state.bev.height,
      );
      underlayBlobUrl = URL.createObjectURL(blob);
      underlay.src = underlayBlobUrl;
    } catch (_) {
      underlay.removeAttribute("src");
    }
  }

  async function loadExistingMask() {
    try {
      const blob = await api.fetchMask(kind);
      if (!blob) return false;
      const url = URL.createObjectURL(blob);
      const img = new Image();
      await new Promise((res, rej) => {
        img.onload = res;
        img.onerror = rej;
        img.src = url;
      });
      ctx2d.clearRect(0, 0, canvas.width, canvas.height);
      ctx2d.drawImage(img, 0, 0, canvas.width, canvas.height);
      convertFinalToEditing();
      URL.revokeObjectURL(url);
      return true;
    } catch (_) {
      return false;
    }
  }

  function ensureResizeObserver() {
    if (resizeObs) return;
    resizeObs = new ResizeObserver(() => {
      if (root.classList.contains("hidden")) return;
      fitStack(false);
    });
    resizeObs.observe(wrap);
  }

  let lastBevSignature = null;
  return {
    show: async () => {
      const bev = store.state.bev;
      if (!bev) return;
      const sig = `${bev.width}x${bev.height}`;
      if (!initialized || sig !== lastBevSignature) {
        bevDims = { width: bev.width, height: bev.height };
        setupCanvas(bev.width, bev.height);
        fillInitial();
        await loadUnderlay();
        const hadMask = await loadExistingMask();
        undoStack.reset();
        pushSnapshot();
        initialized = true;
        lastBevSignature = sig;
        saveStatus.textContent = hadMask ? "Завантажено збережену маску" : "";
        saveStatus.className = "status inline";
      } else {
        await loadUnderlay();
      }
      ensureResizeObserver();
      fitStack(true);
      requestAnimationFrame(() => fitStack(true));
      applyDisplaySettings();
      brushSizeLabel.textContent = brushSizeInput.value;
    },
    onReset: () => {
      initialized = false;
      lastBevSignature = null;
      bevDims = null;
      undoStack.reset();
      if (underlayBlobUrl) { URL.revokeObjectURL(underlayBlobUrl); underlayBlobUrl = null; }
      saveStatus.textContent = "";
      viewState = { scale: 1, tx: 0, ty: 0 };
      stack.style.transform = "";
      stack.style.width = "";
      stack.style.height = "";
    },
  };
}
