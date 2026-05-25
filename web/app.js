"use strict";

const API_URL = "/api/v1/system";
const HEALTH_URL = "/api/v1/health";
const POLL_INTERVAL = 2000; // ms

// ── Mini canvas chart ──────────────────────────────────────────────────────────

class MiniChart {
  constructor(canvasId, maxVal = 100, color = "#30d060") {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas.getContext("2d");
    this.maxVal = maxVal;
    this.color = color;
    this.data = [];
    this.maxPoints = 150;
  }

  push(value) {
    this.data.push(value);
    if (this.data.length > this.maxPoints) this.data.shift();
    this.draw();
  }

  draw() {
    const { canvas, ctx, data, maxVal, color } = this;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;

    ctx.clearRect(0, 0, w, h);

    if (data.length < 2) return;

    // Grid lines
    ctx.strokeStyle = "#2a2a36";
    ctx.lineWidth = 0.5;
    for (let pct of [25, 50, 75]) {
      const y = h - (pct / 100) * h;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    // Data line
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.lineJoin = "round";

    const step = w / (this.maxPoints - 1);
    const offset = (this.maxPoints - data.length) * step;

    for (let i = 0; i < data.length; i++) {
      const x = offset + i * step;
      const y = h - (Math.min(data[i], maxVal) / maxVal) * h;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Fill under
    ctx.lineTo(offset + (data.length - 1) * step, h);
    ctx.lineTo(offset, h);
    ctx.closePath();
    ctx.fillStyle = color + "18";
    ctx.fill();
  }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmt(val, unit = "") {
  if (val === null || val === undefined) return "—";
  return val + unit;
}

function fmtMB(mb) {
  if (mb >= 1024) return (mb / 1024).toFixed(1) + " GB";
  return mb.toFixed(0) + " MB";
}

function fmtUptime(sec) {
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  let parts = [];
  if (d > 0) parts.push(d + "d");
  parts.push(h + "h");
  parts.push(m + "m");
  return parts.join(" ");
}

function barColor(pct) {
  if (pct > 85) return "red";
  if (pct > 60) return "yellow";
  return "green";
}

function setBar(id, pct) {
  const el = document.getElementById(id);
  el.style.width = pct + "%";
  el.className = "bar-fill " + barColor(pct);
}

function setText(id, text) {
  document.getElementById(id).textContent = text;
}

// ── Charts ──────────────────────────────────────────────────────────────────

const cpuChart = new MiniChart("chart-cpu", 100, "#30d060");
const ramChart = new MiniChart("chart-ram", 100, "#4090f0");

// ── Update UI ───────────────────────────────────────────────────────────────

function updateServerInfo(server) {
  setText("hostname", server.hostname);
  setText("info-os", server.os);
  setText("info-arch", server.architecture);
  setText("info-python", server.python_version);
  setText("info-cores", `${server.cpu_count_physical || "?"} / ${server.cpu_count_logical || "?"}`);
  setText("info-ram", fmtMB(server.ram_total_mb));
}

function updateCurrent(cur) {
  // CPU
  setText("cpu-total", cur.cpu_percent.toFixed(1) + "%");
  setBar("cpu-bar", cur.cpu_percent);
  cpuChart.push(cur.cpu_percent);

  const loadArr = cur.load_avg || [0, 0, 0];
  setText("cpu-load", loadArr.map(v => v.toFixed(2)).join(" / "));

  // Per-core
  const grid = document.getElementById("cores-grid");
  if (cur.cpu_per_core && cur.cpu_per_core.length > 0) {
    if (grid.children.length !== cur.cpu_per_core.length) {
      grid.innerHTML = cur.cpu_per_core.map((_, i) =>
        `<div class="core-item"><div class="core-id">C${i}</div><div class="core-val" id="core-${i}">0%</div></div>`
      ).join("");
    }
    cur.cpu_per_core.forEach((val, i) => {
      const el = document.getElementById(`core-${i}`);
      if (el) {
        el.textContent = val.toFixed(0) + "%";
        el.style.color = val > 85 ? "#f04040" : val > 60 ? "#f0a020" : "#30d060";
      }
    });
  }

  // RAM
  setText("ram-usage", `${fmtMB(cur.ram_used_mb)} / ${fmtMB(cur.ram_total_mb)} (${cur.ram_percent}%)`);
  setBar("ram-bar", cur.ram_percent);
  ramChart.push(cur.ram_percent);

  setText("ram-swap", `${fmtMB(cur.swap_used_mb)} / ${fmtMB(cur.swap_total_mb)}`);

  // Disk
  setText("disk-usage", `${cur.disk_used_gb.toFixed(1)} GB / ${cur.disk_total_gb.toFixed(1)} GB (${cur.disk_percent}%)`);
  setBar("disk-bar", cur.disk_percent);

  // Network
  setText("net-sent", fmtMB(cur.net_sent_mb));
  setText("net-recv", fmtMB(cur.net_recv_mb));

  // Temperature
  const tempCard = document.getElementById("card-temp");
  if (cur.cpu_temp !== null) {
    tempCard.style.display = "";
    setText("temp-cpu", cur.cpu_temp.toFixed(1) + " °C");
  } else {
    tempCard.style.display = "none";
  }

  // Uptime
  setText("info-uptime", fmtUptime(cur.uptime_seconds));
}

// ── Health banner ───────────────────────────────────────────────────────────

function renderHealthBanner(health) {
  const el = document.getElementById("health-banner");
  if (!el) return;

  const pipelineStatus = health?.pipeline?.status;
  const lastError = health?.pipeline?.last_error;
  const cameraConnected = health?.camera?.connected;

  if (health?.status === "error" || pipelineStatus === "error") {
    el.className = "banner error show";
    el.innerHTML =
      "<strong>Pipeline error</strong>" +
      (lastError
        ? `${escapeHtml(lastError)} — check your <code>.env</code> and restart.`
        : "The detection pipeline failed to start. Check container logs: <code>docker compose logs -f</code>.");
    return;
  }

  if (pipelineStatus === "starting" || health?.status === "starting") {
    el.className = "banner warn show";
    el.innerHTML =
      "<strong>Pipeline starting…</strong>Waiting for the first camera frame. This usually takes a few seconds.";
    return;
  }

  if (cameraConnected === false) {
    el.className = "banner warn show";
    el.innerHTML =
      "<strong>Camera disconnected</strong>The pipeline is running but cannot reach the camera. Verify <code>CAMERA_URL</code> and network reachability.";
    return;
  }

  el.className = "banner";
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function pollHealth() {
  try {
    const res = await fetch(HEALTH_URL);
    if (!res.ok) return;
    const health = await res.json();
    renderHealthBanner(health);
  } catch (_e) {
    // Network failure: leave whatever banner state is on screen. The main
    // /system poll already surfaces "Error: …" in the status footer.
  }
}

// ── Polling loop ────────────────────────────────────────────────────────────

let serverInfoSet = false;

async function poll() {
  try {
    const res = await fetch(API_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (!serverInfoSet && data.server) {
      updateServerInfo(data.server);
      serverInfoSet = true;
    }

    if (data.current) {
      updateCurrent(data.current);
    }

    const statusEl = document.getElementById("status-text");
    statusEl.textContent = "● Live — updated " + new Date().toLocaleTimeString();
    statusEl.className = "ok";
  } catch (e) {
    const statusEl = document.getElementById("status-text");
    statusEl.textContent = "● Error: " + e.message;
    statusEl.className = "err";
  }
}

// Initial + interval
poll();
pollHealth();
setInterval(poll, POLL_INTERVAL);
setInterval(pollHealth, POLL_INTERVAL);
