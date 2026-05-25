const SVG_NS = "http://www.w3.org/2000/svg";

function debounce(fn, ms) {
  let t = null;
  return (...args) => {
    if (t) clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

export function initMapPage(ctx) {
  const { api, store, toast } = ctx;

  const wrap = document.getElementById("map-svg-wrap");
  const shapesList = document.getElementById("map-shapes-list");
  const saveBtn = document.getElementById("map-save-btn");
  const saveStatus = document.getElementById("map-save-status");
  const closeBtn = document.getElementById("map-close-btn");
  const deleteBtn = document.getElementById("map-delete-btn");
  const underlayToggle = document.getElementById("map-underlay-toggle");
  const underlayOpacity = document.getElementById("map-underlay-opacity");
  const underlayOpacityLabel = document.getElementById("map-underlay-opacity-label");

  let svg = null;
  let imageEl = null;
  let shapesLayer = null;
  let cursorLineEl = null;
  let bevDims = null;
  let underlayBlobUrl = null;

  let shapes = [];
  let activeDraft = null;
  let selectedId = null;
  let selectedVertex = null;
  let dragging = null;
  let mode = "add";
  let nextIdCounter = 1;
  let dirty = false;
  let initialized = false;
  let lastBevSignature = null;

  let viewBox = { x: 0, y: 0, w: 1, h: 1 };
  let isPanning = false;
  let panStart = null;

  function newShapeId() {
    return `shape-${nextIdCounter++}`;
  }

  function buildSvg(width, height) {
    wrap.innerHTML = "";
    svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    svg.setAttribute("class", "crosshair-cursor");
    setViewBox(0, 0, width, height);

    imageEl = document.createElementNS(SVG_NS, "image");
    imageEl.setAttribute("x", "0");
    imageEl.setAttribute("y", "0");
    imageEl.setAttribute("width", String(width));
    imageEl.setAttribute("height", String(height));
    imageEl.setAttribute("opacity", String(Number(underlayOpacity.value) / 100));
    svg.appendChild(imageEl);

    const frame = document.createElementNS(SVG_NS, "rect");
    frame.setAttribute("x", "0");
    frame.setAttribute("y", "0");
    frame.setAttribute("width", String(width));
    frame.setAttribute("height", String(height));
    frame.setAttribute("fill", "none");
    frame.setAttribute("stroke", "rgba(78,161,255,0.7)");
    frame.setAttribute("stroke-width", "2");
    frame.setAttribute("vector-effect", "non-scaling-stroke");
    frame.setAttribute("pointer-events", "none");
    svg.appendChild(frame);

    shapesLayer = document.createElementNS(SVG_NS, "g");
    shapesLayer.setAttribute("class", "shapes-layer");
    svg.appendChild(shapesLayer);

    cursorLineEl = document.createElementNS(SVG_NS, "line");
    cursorLineEl.setAttribute("stroke", "rgba(78,161,255,0.5)");
    cursorLineEl.setAttribute("stroke-width", "2");
    cursorLineEl.setAttribute("stroke-dasharray", "4 4");
    cursorLineEl.style.display = "none";
    svg.appendChild(cursorLineEl);

    svg.addEventListener("pointerdown", onSvgPointerDown);
    svg.addEventListener("pointermove", onSvgPointerMove);
    svg.addEventListener("pointerup", onSvgPointerUp);
    svg.addEventListener("pointercancel", onSvgPointerUp);
    svg.addEventListener("dblclick", onSvgDblClick);
    svg.addEventListener("contextmenu", (ev) => ev.preventDefault());
    svg.addEventListener("wheel", onWheel, { passive: false });

    wrap.appendChild(svg);
  }

  function setViewBox(x, y, w, h) {
    viewBox = { x, y, w, h };
    if (svg) svg.setAttribute("viewBox", `${x} ${y} ${w} ${h}`);
  }

  function onWheel(ev) {
    if (!ev.ctrlKey) return;
    ev.preventDefault();
    ev.stopPropagation();
    const factor = ev.deltaY < 0 ? 0.85 : 1.18;
    const p = clientToSvg(ev.clientX, ev.clientY);
    const newW = viewBox.w * factor;
    const newH = viewBox.h * factor;
    const newX = p.x - (p.x - viewBox.x) * factor;
    const newY = p.y - (p.y - viewBox.y) * factor;
    setViewBox(newX, newY, newW, newH);
  }

  function setMode(m) {
    mode = m;
    if (mode !== "add") {
      activeDraft = null;
      cursorLineEl.style.display = "none";
    }
    render();
  }

  function clientToSvg(clientX, clientY) {
    const pt = svg.createSVGPoint();
    pt.x = clientX; pt.y = clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    const r = pt.matrixTransform(ctm.inverse());
    return { x: r.x, y: r.y };
  }

  function findShape(id) { return shapes.find((s) => s.id === id); }

  function isInBevBounds(p) {
    return (
      bevDims &&
      p.x >= 0 && p.x <= bevDims.width &&
      p.y >= 0 && p.y <= bevDims.height
    );
  }

  function onSvgPointerDown(ev) {
    if (ev.button === 1 || (ev.button === 0 && ev.ctrlKey)) {
      ev.preventDefault();
      ev.stopPropagation();
      isPanning = true;
      panStart = { clientX: ev.clientX, clientY: ev.clientY, vb: { ...viewBox }, pointerId: ev.pointerId };
      try { svg.setPointerCapture(ev.pointerId); } catch (_) {}
      wrap.classList.add("panning");
      return;
    }
    if (ev.button !== 0) return;
    const target = ev.target;
    if (target.closest("[data-vertex]")) return;
    if (target.closest("[data-shape]")) {
      const sid = target.closest("[data-shape]").getAttribute("data-shape");
      if (mode === "edit") {
        const shape = findShape(sid);
        if (shape && ev.shiftKey) {
          const p = clientToSvg(ev.clientX, ev.clientY);
          insertVertexOnEdge(shape, p);
        }
        selectedId = sid;
        selectedVertex = null;
        render();
      }
      return;
    }
    if (mode === "add") {
      const p = clientToSvg(ev.clientX, ev.clientY);
      if (!isInBevBounds(p)) {
        toast("Клік поза межами BEV — вершину не додано", "warn");
        return;
      }
      addVertexToDraft(p);
    } else if (mode === "edit") {
      selectedId = null;
      selectedVertex = null;
      render();
    }
  }

  function onSvgPointerMove(ev) {
    if (isPanning) {
      const rect = svg.getBoundingClientRect();
      const dx = (ev.clientX - panStart.clientX) * (viewBox.w / rect.width);
      const dy = (ev.clientY - panStart.clientY) * (viewBox.h / rect.height);
      setViewBox(panStart.vb.x - dx, panStart.vb.y - dy, viewBox.w, viewBox.h);
      return;
    }
    if (dragging) {
      const p = clientToSvg(ev.clientX, ev.clientY);
      const shape = findShape(dragging.shapeId);
      if (shape) {
        shape.points[dragging.vertexIdx] = [
          Math.max(0, Math.min(bevDims.width, p.x)),
          Math.max(0, Math.min(bevDims.height, p.y)),
        ];
        dirty = true;
        renderShape(shape);
      }
      return;
    }
    if (mode === "add" && activeDraft && activeDraft.points.length > 0) {
      const p = clientToSvg(ev.clientX, ev.clientY);
      const last = activeDraft.points[activeDraft.points.length - 1];
      cursorLineEl.setAttribute("x1", String(last[0]));
      cursorLineEl.setAttribute("y1", String(last[1]));
      cursorLineEl.setAttribute("x2", String(p.x));
      cursorLineEl.setAttribute("y2", String(p.y));
      cursorLineEl.style.display = "";
    }
  }

  function onSvgPointerUp(ev) {
    if (isPanning) {
      try { svg.releasePointerCapture(ev.pointerId); } catch (_) {}
      isPanning = false;
      panStart = null;
      wrap.classList.remove("panning");
      return;
    }
    if (dragging) {
      try { svg.releasePointerCapture(ev.pointerId); } catch (_) {}
      dragging = null;
      scheduleAutosave();
    }
  }

  function onSvgDblClick(ev) {
    if (ev.button !== 0 || ev.ctrlKey) return;
    if (mode !== "add") return;
    if (activeDraft && activeDraft.points.length >= 2) {
      activeDraft.points.pop();
    }
    closeDraft();
  }

  function addVertexToDraft(p) {
    if (!activeDraft) {
      activeDraft = { id: newShapeId(), points: [], closed: false };
      shapes.push(activeDraft);
    }
    activeDraft.points.push([p.x, p.y]);
    dirty = true;
    render();
  }

  function closeDraft() {
    if (!activeDraft) return;
    if (activeDraft.points.length < 3) {
      shapes = shapes.filter((s) => s !== activeDraft);
      activeDraft = null;
      cursorLineEl.style.display = "none";
      render();
      toast("Полігону потрібно щонайменше 3 вершини", "warn");
      return;
    }
    activeDraft.closed = true;
    selectedId = activeDraft.id;
    activeDraft = null;
    cursorLineEl.style.display = "none";
    dirty = true;
    render();
    scheduleAutosave();
  }

  function insertVertexOnEdge(shape, point) {
    const pts = shape.points;
    let bestIdx = 0;
    let bestDist = Infinity;
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i];
      const b = pts[(i + 1) % pts.length];
      const d = pointSegmentDistance(point, a, b);
      if (d < bestDist) { bestDist = d; bestIdx = i + 1; }
    }
    if (bestDist > 30) return;
    pts.splice(bestIdx, 0, [point.x, point.y]);
    dirty = true;
    render();
    scheduleAutosave();
  }

  function pointSegmentDistance(p, a, b) {
    const ax = a[0], ay = a[1], bx = b[0], by = b[1];
    const dx = bx - ax, dy = by - ay;
    const lenSq = dx * dx + dy * dy;
    let t = lenSq === 0 ? 0 : ((p.x - ax) * dx + (p.y - ay) * dy) / lenSq;
    t = Math.max(0, Math.min(1, t));
    const cx = ax + t * dx, cy = ay + t * dy;
    const ex = p.x - cx, ey = p.y - cy;
    return Math.sqrt(ex * ex + ey * ey);
  }

  function deleteSelected() {
    if (selectedVertex && selectedId) {
      const shape = findShape(selectedId);
      if (shape && shape.points.length > 3) {
        shape.points.splice(selectedVertex.idx, 1);
        selectedVertex = null;
        dirty = true;
        render();
        scheduleAutosave();
        return;
      }
    }
    if (selectedId) {
      shapes = shapes.filter((s) => s.id !== selectedId);
      selectedId = null;
      selectedVertex = null;
      dirty = true;
      render();
      scheduleAutosave();
    }
  }

  function render() {
    if (!shapesLayer) return;
    shapesLayer.innerHTML = "";
    shapes.forEach((shape) => renderShape(shape));
    renderShapesList();
  }

  function renderShape(shape) {
    const existing = shapesLayer.querySelector(`[data-shape="${shape.id}"]`);
    if (existing) existing.remove();
    const oldVerts = shapesLayer.querySelectorAll(`[data-vertex-shape="${shape.id}"]`);
    oldVerts.forEach((n) => n.remove());

    const ptsStr = shape.points.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
    const isSelected = shape.id === selectedId;
    const isDraft = !shape.closed;

    if (isDraft) {
      const pl = document.createElementNS(SVG_NS, "polyline");
      pl.setAttribute("points", ptsStr);
      pl.setAttribute("class", "map-shape-polyline");
      pl.setAttribute("data-shape", shape.id);
      shapesLayer.appendChild(pl);
    } else {
      const pg = document.createElementNS(SVG_NS, "polygon");
      pg.setAttribute("points", ptsStr);
      pg.setAttribute("class", "map-shape-polygon" + (isSelected ? " selected" : ""));
      pg.setAttribute("data-shape", shape.id);
      shapesLayer.appendChild(pg);
    }

    const showVerts = isDraft || (mode === "edit" && isSelected);
    if (showVerts) {
      shape.points.forEach((p, idx) => {
        const c = document.createElementNS(SVG_NS, "circle");
        c.setAttribute("cx", String(p[0]));
        c.setAttribute("cy", String(p[1]));
        c.setAttribute("r", String(Math.max(5, bevDims.width / 200)));
        c.setAttribute("class", "map-vertex" + (isSelected ? " selected-shape" : ""));
        c.setAttribute("data-vertex", idx);
        c.setAttribute("data-vertex-shape", shape.id);
        c.addEventListener("pointerdown", (ev) => {
          if (ev.button !== 0) return;
          ev.stopPropagation();
          if (mode !== "edit" && !isDraft) return;
          selectedId = shape.id;
          selectedVertex = { idx };
          dragging = { shapeId: shape.id, vertexIdx: idx };
          try { svg.setPointerCapture(ev.pointerId); } catch (_) {}
          render();
        });
        shapesLayer.appendChild(c);
      });
    }
  }

  function renderShapesList() {
    shapesList.innerHTML = "";
    if (shapes.length === 0) {
      const li = document.createElement("li");
      li.innerHTML = '<span class="muted">Жодного полігону</span>';
      li.style.cursor = "default";
      shapesList.appendChild(li);
      return;
    }
    shapes.forEach((shape, idx) => {
      const li = document.createElement("li");
      if (shape.id === selectedId) li.classList.add("selected");
      const label = document.createElement("span");
      label.textContent = `${idx + 1}. ${shape.points.length} вершин${shape.closed ? "" : " (open)"}`;
      const rm = document.createElement("button");
      rm.className = "sl-remove";
      rm.textContent = "×";
      rm.title = "Видалити";
      rm.addEventListener("click", (ev) => {
        ev.stopPropagation();
        shapes = shapes.filter((s) => s.id !== shape.id);
        if (selectedId === shape.id) selectedId = null;
        if (activeDraft && activeDraft.id === shape.id) activeDraft = null;
        dirty = true;
        render();
        scheduleAutosave();
      });
      li.addEventListener("click", () => {
        if (!shape.closed) return;
        selectedId = shape.id;
        selectedVertex = null;
        if (mode !== "edit") setMode("edit");
        else render();
        const radio = document.querySelector('input[name="map-mode"][value="edit"]');
        if (radio) radio.checked = true;
      });
      li.append(label, rm);
      shapesList.appendChild(li);
    });
  }

  document.querySelectorAll('input[name="map-mode"]').forEach((r) => {
    r.addEventListener("change", () => setMode(r.value));
  });

  underlayToggle.addEventListener("change", () => {
    if (imageEl) imageEl.style.display = underlayToggle.checked ? "" : "none";
  });
  underlayOpacity.addEventListener("input", () => {
    if (imageEl) imageEl.setAttribute("opacity", String(Number(underlayOpacity.value) / 100));
    underlayOpacityLabel.textContent = underlayOpacity.value;
  });

  closeBtn.addEventListener("click", closeDraft);
  deleteBtn.addEventListener("click", deleteSelected);

  document.addEventListener("keydown", (ev) => {
    const page = document.getElementById("page-map");
    if (!page || page.classList.contains("hidden")) return;
    if (ev.key === "Escape") {
      if (activeDraft) {
        shapes = shapes.filter((s) => s !== activeDraft);
        activeDraft = null;
        cursorLineEl.style.display = "none";
        dirty = true;
        render();
      }
    } else if (ev.key === "Enter") {
      if (activeDraft) closeDraft();
    } else if (ev.key === "Delete" || ev.key === "Backspace") {
      if (selectedId || selectedVertex) {
        ev.preventDefault();
        deleteSelected();
      }
    }
  });

  saveBtn.addEventListener("click", () => doSave());

  async function doSave() {
    const out = shapes
      .filter((s) => s.closed && s.points.length >= 3)
      .map((s) => ({ id: s.id, points: s.points }));
    saveStatus.textContent = "Зберігаю...";
    saveStatus.className = "status inline";
    try {
      await api.saveMap(out);
      await store.refresh();
      saveStatus.textContent = `Збережено (${out.length})`;
      saveStatus.className = "status inline ok";
      dirty = false;
    } catch (e) {
      saveStatus.textContent = `Помилка: ${e.message}`;
      saveStatus.className = "status inline err";
    }
  }

  const scheduleAutosave = debounce(() => { if (dirty) doSave(); }, 1200);

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
      if (imageEl) {
        imageEl.setAttribute("href", underlayBlobUrl);
        imageEl.setAttributeNS("http://www.w3.org/1999/xlink", "xlink:href", underlayBlobUrl);
      }
    } catch (_) {}
  }

  async function loadShapes() {
    try {
      const data = await api.fetchMap();
      shapes = (data.shapes || []).map((s) => ({
        id: s.id,
        points: s.points.map((p) => [Number(p[0]), Number(p[1])]),
        closed: true,
      }));
      nextIdCounter = shapes.length + 1;
    } catch (_) {
      shapes = [];
    }
  }

  return {
    show: async () => {
      const bev = store.state.bev;
      if (!bev) return;
      const sig = `${bev.width}x${bev.height}`;
      if (!initialized || sig !== lastBevSignature) {
        bevDims = { width: bev.width, height: bev.height };
        buildSvg(bev.width, bev.height);
        await loadUnderlay();
        await loadShapes();
        initialized = true;
        lastBevSignature = sig;
        setMode("add");
        const radio = document.querySelector('input[name="map-mode"][value="add"]');
        if (radio) radio.checked = true;
      } else {
        await loadUnderlay();
        render();
      }
      underlayOpacityLabel.textContent = underlayOpacity.value;
    },
    onReset: () => {
      shapes = [];
      activeDraft = null;
      selectedId = null;
      selectedVertex = null;
      initialized = false;
      lastBevSignature = null;
      bevDims = null;
      if (underlayBlobUrl) { URL.revokeObjectURL(underlayBlobUrl); underlayBlobUrl = null; }
      saveStatus.textContent = "";
    },
  };
}
