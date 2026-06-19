// ── Constants ─────────────────────────────────────────────────────────────────
const POLL_MS  = 2500;
const BEV_W    = 1200;
const BEV_H    = 800;
const DOT_R    = 12;
const COLOR_FREE     = "#30d060";
const COLOR_OCCUPIED = "#f04040";
const SVG_NS   = "http://www.w3.org/2000/svg";

// ── DOM refs ──────────────────────────────────────────────────────────────────
const dotLayer      = document.getElementById("dot-layer");
const svgLayer      = document.getElementById("svg-layer");
const svgPlaceholder = document.getElementById("svg-placeholder");
const statusPill    = document.getElementById("status-pill");
const valTotal      = document.getElementById("val-total");
const valOccupied   = document.getElementById("val-occupied");
const valFree       = document.getElementById("val-free");
const valPct        = document.getElementById("val-pct");

// ── SVG map loading ───────────────────────────────────────────────────────────
async function loadSvgMap() {
  try {
    const res = await fetch("/parking_map.svg");
    if (!res.ok) return;
    const svgText = await res.text();
    svgLayer.innerHTML = svgText;
    // Make the embedded SVG fill the container
    const embedded = svgLayer.querySelector("svg");
    if (embedded) {
      embedded.style.width = "100%";
      embedded.style.height = "100%";
      embedded.removeAttribute("width");
      embedded.removeAttribute("height");
    }
    svgLayer.style.display = "block";
    svgPlaceholder.style.display = "none";
  } catch {
    // SVG unavailable — placeholder remains visible
  }
}

loadSvgMap();

// ── Spot rendering ────────────────────────────────────────────────────────────
function renderSpots(spots) {
  while (dotLayer.firstChild) {
    dotLayer.removeChild(dotLayer.firstChild);
  }

  for (const spot of spots) {
    const { x1, y1, x2, y2 } = spot.bbox_bev;
    const color = spot.status === "occupied" ? COLOR_OCCUPIED : COLOR_FREE;
    const pct   = Math.round(spot.confidence * 100);

    const rect = document.createElementNS(SVG_NS, "rect");
    rect.setAttribute("x", x1);
    rect.setAttribute("y", y1);
    rect.setAttribute("width",  x2 - x1);
    rect.setAttribute("height", y2 - y1);
    rect.setAttribute("rx", "4");
    rect.setAttribute("ry", "4");
    rect.setAttribute("fill", color);
    rect.setAttribute("fill-opacity", "0.55");
    rect.setAttribute("stroke", color);
    rect.setAttribute("stroke-width", "2");

    const title = document.createElementNS(SVG_NS, "title");
    title.textContent = `${spot.status} \u00b7 ${spot.orientation} \u00b7 conf ${pct}%`;
    rect.appendChild(title);

    dotLayer.appendChild(rect);
  }
}

// ── Stats bar ─────────────────────────────────────────────────────────────────
function updateStats(state) {
  valTotal.textContent    = state.total_spots;
  valOccupied.textContent = state.occupied;
  valFree.textContent     = state.free;
  valPct.textContent      = state.occupancy_percent.toFixed(1) + "%";
}

// ── Status pill ───────────────────────────────────────────────────────────────
function setStatus(text, cls) {
  statusPill.textContent = text;
  statusPill.className   = cls || "";
}

// ── Polling ───────────────────────────────────────────────────────────────────
let lastTimestamp = null;

async function poll() {
  try {
    const res = await fetch("/api/state");

    if (res.status === 503) {
      setStatus("initializing");
      return;
    }
    if (!res.ok) {
      setStatus("error " + res.status, "error");
      return;
    }

    const state = await res.json();

    if (state.timestamp !== lastTimestamp) {
      lastTimestamp = state.timestamp;
      renderSpots(state.spots);
      updateStats(state);
    }

    setStatus("live", "live");
  } catch {
    setStatus("offline", "error");
  }
}

poll();
setInterval(poll, POLL_MS);
