const SVG_NS = "http://www.w3.org/2000/svg";
const CORNER_LABELS = ["TL", "TR", "BR", "BL"];
const CORNER_CLASSES = ["dot-tl", "dot-tr", "dot-br", "dot-bl"];
const CORNER_COLORS = ["#57c97e", "#4ed3d8", "#e35d6a", "#ebd565"];

function debounce(fn, ms) {
  let t = null;
  return (...args) => {
    if (t) clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

export function initBevPage(ctx) {
  const { api, store, toast } = ctx;

  const sourceContainer = document.getElementById("bev-source-container");
  const previewArea = document.getElementById("bev-preview-area");
  const previewStatus = document.getElementById("bev-preview-status");
  const widthInput = document.getElementById("bev-width");
  const heightInput = document.getElementById("bev-height");
  const pointsGrid = document.getElementById("bev-points-grid");
  const copyBtn = document.getElementById("bev-copy-btn");
  const pasteBtn = document.getElementById("bev-paste-btn");
  const resetBtn = document.getElementById("bev-reset-btn");
  const saveBtn = document.getElementById("bev-save-btn");
  const saveStatus = document.getElementById("bev-save-status");

  let frameImageEl = null;
  let frameWidth = 0;
  let frameHeight = 0;
  let svg = null;
  let viewBox = { x: 0, y: 0, w: 1, h: 1 };
  let points = [[0, 0], [1, 0], [1, 1], [0, 1]];
  let pointHandles = [];
  let polygonEl = null;
  let imageEl = null;
  let previewBlobUrl = null;
  let isPanning = false;
  let panStart = null;
  let activeHandle = null;
  let pointInputs = [];

  function buildPointInputs() {
    pointsGrid.innerHTML = "";
    pointInputs = [];
    points.forEach((p, idx) => {
      const labelCell = document.createElement("div");
      labelCell.className = "corner-label";
      labelCell.innerHTML = `<span class="dot ${CORNER_CLASSES[idx]}"></span> ${CORNER_LABELS[idx]}`;
      const xIn = document.createElement("input");
      xIn.type = "number"; xIn.step = "1"; xIn.value = p[0].toFixed(0);
      const yIn = document.createElement("input");
      yIn.type = "number"; yIn.step = "1"; yIn.value = p[1].toFixed(0);
      pointsGrid.append(labelCell, xIn, yIn);
      pointInputs.push([xIn, yIn]);
      xIn.addEventListener("input", () => {
        points[idx][0] = Number(xIn.value);
        updateGeometry();
        schedulePreview();
      });
      yIn.addEventListener("input", () => {
        points[idx][1] = Number(yIn.value);
        updateGeometry();
        schedulePreview();
      });
    });
  }

  function syncInputsFromPoints() {
    pointInputs.forEach(([xIn, yIn], idx) => {
      xIn.value = points[idx][0].toFixed(0);
      yIn.value = points[idx][1].toFixed(0);
    });
  }

  function buildSvg() {
    sourceContainer.innerHTML = "";
    if (!frameImageEl) return;
    svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    setViewBox(0, 0, frameWidth, frameHeight);

    imageEl = document.createElementNS(SVG_NS, "image");
    imageEl.setAttribute("x", "0");
    imageEl.setAttribute("y", "0");
    imageEl.setAttribute("width", String(frameWidth));
    imageEl.setAttribute("height", String(frameHeight));
    imageEl.setAttributeNS(
      "http://www.w3.org/1999/xlink",
      "xlink:href",
      frameImageEl.src,
    );
    imageEl.setAttribute("href", frameImageEl.src);
    svg.appendChild(imageEl);

    polygonEl = document.createElementNS(SVG_NS, "polygon");
    polygonEl.setAttribute("class", "bev-polygon");
    svg.appendChild(polygonEl);

    pointHandles = [];
    for (let i = 0; i < 4; i++) {
      const c = document.createElementNS(SVG_NS, "circle");
      c.setAttribute("class", "bev-handle");
      c.setAttribute("fill", CORNER_COLORS[i]);
      c.setAttribute("stroke", "white");
      c.setAttribute("stroke-width", "2");
      c.setAttribute("r", String(Math.max(8, frameWidth / 220)));
      c.addEventListener("pointerdown", (ev) => onHandlePointerDown(ev, i));
      svg.appendChild(c);
      pointHandles.push(c);
    }

    sourceContainer.appendChild(svg);
    attachPanZoom();
    updateGeometry();
  }

  function setViewBox(x, y, w, h) {
    viewBox = { x, y, w, h };
    if (svg) svg.setAttribute("viewBox", `${x} ${y} ${w} ${h}`);
  }

  function attachPanZoom() {
    svg.addEventListener("wheel", (ev) => {
      if (!ev.ctrlKey) return;
      ev.preventDefault();
      const factor = ev.deltaY < 0 ? 0.85 : 1.18;
      const pt = clientToSvg(ev.clientX, ev.clientY);
      const newW = viewBox.w * factor;
      const newH = viewBox.h * factor;
      const newX = pt.x - (pt.x - viewBox.x) * factor;
      const newY = pt.y - (pt.y - viewBox.y) * factor;
      setViewBox(newX, newY, newW, newH);
      updateHandleRadius();
    }, { passive: false });

    svg.addEventListener("contextmenu", (ev) => ev.preventDefault());

    svg.addEventListener("pointerdown", (ev) => {
      if (activeHandle !== null) return;
      if (ev.button === 2 || (ev.button === 0 && ev.ctrlKey)) {
        isPanning = true;
        panStart = { clientX: ev.clientX, clientY: ev.clientY, vb: { ...viewBox } };
        svg.setPointerCapture(ev.pointerId);
      }
    });
    svg.addEventListener("pointermove", (ev) => {
      if (!isPanning) return;
      const rect = svg.getBoundingClientRect();
      const dx = (ev.clientX - panStart.clientX) * (viewBox.w / rect.width);
      const dy = (ev.clientY - panStart.clientY) * (viewBox.h / rect.height);
      setViewBox(panStart.vb.x - dx, panStart.vb.y - dy, viewBox.w, viewBox.h);
    });
    svg.addEventListener("pointerup", (ev) => {
      if (isPanning) {
        isPanning = false;
        try { svg.releasePointerCapture(ev.pointerId); } catch (_) {}
      }
    });
  }

  function updateHandleRadius() {
    const r = Math.max(6, viewBox.w / 150);
    pointHandles.forEach((c) => c.setAttribute("r", String(r)));
  }

  function clientToSvg(clientX, clientY) {
    const rect = svg.getBoundingClientRect();
    return {
      x: viewBox.x + ((clientX - rect.left) / rect.width) * viewBox.w,
      y: viewBox.y + ((clientY - rect.top) / rect.height) * viewBox.h,
    };
  }

  function onHandlePointerDown(ev, idx) {
    ev.stopPropagation();
    ev.preventDefault();
    activeHandle = idx;
    pointHandles[idx].classList.add("dragging");
    pointHandles[idx].setPointerCapture(ev.pointerId);
    const move = (mv) => {
      const p = clientToSvg(mv.clientX, mv.clientY);
      points[idx][0] = Math.round(p.x);
      points[idx][1] = Math.round(p.y);
      syncInputsFromPoints();
      updateGeometry();
      schedulePreview();
    };
    const up = (uv) => {
      activeHandle = null;
      pointHandles[idx].classList.remove("dragging");
      try { pointHandles[idx].releasePointerCapture(uv.pointerId); } catch (_) {}
      pointHandles[idx].removeEventListener("pointermove", move);
      pointHandles[idx].removeEventListener("pointerup", up);
      pointHandles[idx].removeEventListener("pointercancel", up);
    };
    pointHandles[idx].addEventListener("pointermove", move);
    pointHandles[idx].addEventListener("pointerup", up);
    pointHandles[idx].addEventListener("pointercancel", up);
  }

  function updateGeometry() {
    if (!svg) return;
    pointHandles.forEach((c, i) => {
      c.setAttribute("cx", String(points[i][0]));
      c.setAttribute("cy", String(points[i][1]));
    });
    polygonEl.setAttribute(
      "points",
      points.map((p) => p.join(",")).join(" "),
    );
  }

  const schedulePreview = debounce(async () => {
    const w = Number(widthInput.value) || 1200;
    const h = Number(heightInput.value) || 800;
    if (w < 400 || h < 400) {
      previewStatus.textContent = "Розмір BEV занадто малий";
      return;
    }
    previewStatus.textContent = "...";
    try {
      const blob = await api.previewBev(points, w, h);
      if (previewBlobUrl) URL.revokeObjectURL(previewBlobUrl);
      previewBlobUrl = URL.createObjectURL(blob);
      previewArea.innerHTML = "";
      const img = document.createElement("img");
      img.src = previewBlobUrl;
      previewArea.appendChild(img);
      previewStatus.textContent = `${w}×${h}`;
    } catch (e) {
      previewStatus.textContent = `Помилка: ${e.message}`;
    }
  }, 120);

  widthInput.addEventListener("input", schedulePreview);
  heightInput.addEventListener("input", schedulePreview);

  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(points));
      saveStatus.textContent = "JSON у буфері";
      saveStatus.className = "status inline ok";
    } catch (_) {
      saveStatus.textContent = "Не вдалося скопіювати";
      saveStatus.className = "status inline err";
    }
  });

  pasteBtn.addEventListener("click", async () => {
    try {
      const text = await navigator.clipboard.readText();
      const parsed = JSON.parse(text);
      if (!Array.isArray(parsed) || parsed.length !== 4) throw new Error("Очікую масив з 4 точок");
      parsed.forEach((p, i) => {
        if (!Array.isArray(p) || p.length !== 2) throw new Error(`Точка ${i+1} невалідна`);
        points[i] = [Number(p[0]), Number(p[1])];
      });
      syncInputsFromPoints();
      updateGeometry();
      schedulePreview();
      saveStatus.textContent = "Точки вставлено";
      saveStatus.className = "status inline ok";
    } catch (e) {
      saveStatus.textContent = `Не вдалося: ${e.message}`;
      saveStatus.className = "status inline err";
    }
  });

  resetBtn.addEventListener("click", () => {
    points = [
      [0, 0],
      [frameWidth, 0],
      [frameWidth, frameHeight],
      [0, frameHeight],
    ];
    syncInputsFromPoints();
    updateGeometry();
    setViewBox(0, 0, frameWidth, frameHeight);
    updateHandleRadius();
    schedulePreview();
  });

  saveBtn.addEventListener("click", async () => {
    const w = Number(widthInput.value) || 1200;
    const h = Number(heightInput.value) || 800;
    saveBtn.disabled = true;
    saveStatus.textContent = "Зберігаю...";
    saveStatus.className = "status inline";
    try {
      const prevBev = store.state.bev;
      await api.saveBev(points, w, h);
      await store.refresh();
      saveStatus.textContent = "Збережено";
      saveStatus.className = "status inline ok";
      if (prevBev && (prevBev.width !== w || prevBev.height !== h ||
          JSON.stringify(prevBev.src_points) !== JSON.stringify(points))) {
        toast("BEV оновлено — маски/карту скинуто", "warn");
      } else if (prevBev) {
        toast("BEV збережено", "ok");
      } else {
        toast("BEV збережено. Тепер можна малювати маски.", "ok");
      }
    } catch (e) {
      saveStatus.textContent = `Помилка: ${e.message}`;
      saveStatus.className = "status inline err";
    } finally {
      saveBtn.disabled = false;
    }
  });

  async function loadFrame() {
    const blob = await api.fetchCameraFrame();
    if (!blob) {
      sourceContainer.innerHTML = '<p class="placeholder">Спочатку захопіть кадр у кроці 1</p>';
      return false;
    }
    const url = URL.createObjectURL(blob);
    const img = new Image();
    await new Promise((res, rej) => {
      img.onload = res;
      img.onerror = rej;
      img.src = url;
    });
    frameImageEl = img;
    frameWidth = img.naturalWidth;
    frameHeight = img.naturalHeight;
    return true;
  }

  function applyStateBev() {
    const bev = store.state.bev;
    if (bev && bev.src_points) {
      points = bev.src_points.map((p) => [Number(p[0]), Number(p[1])]);
      widthInput.value = bev.width;
      heightInput.value = bev.height;
    } else {
      points = [
        [0, 0],
        [frameWidth, 0],
        [frameWidth, frameHeight],
        [0, frameHeight],
      ];
    }
  }

  let frameSignature = null;
  return {
    show: async () => {
      const stateSig = store.state.has_frame ? store.state.camera_url : null;
      if (!frameImageEl || stateSig !== frameSignature) {
        const ok = await loadFrame();
        if (!ok) return;
        frameSignature = stateSig;
        applyStateBev();
        buildPointInputs();
        buildSvg();
        schedulePreview();
      }
    },
    onReset: () => {
      frameImageEl = null;
      frameSignature = null;
      sourceContainer.innerHTML = "";
      previewArea.innerHTML = '<p class="placeholder">Тут зʼявиться BEV після переміщення точок</p>';
      previewStatus.textContent = "";
      saveStatus.textContent = "";
      if (previewBlobUrl) { URL.revokeObjectURL(previewBlobUrl); previewBlobUrl = null; }
    },
  };
}
